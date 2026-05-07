"""
SimpleISA - 简化指令集核心

这是 RPA 架构的指令执行核心。每个 Domain 可以有不同的 ISA 实现，
SimpleISA 是一个简化版的类 ARM 指令集，用于演示 RPA 的核心机制。

DomainBlock 内存布局 (32 位实现, 4 字节宽度):
==============================================

    ┌──────────┬────────────────────────────────────────────────────────┐
    │ 偏移     │ 字段                                                   │
    ├──────────┼────────────────────────────────────────────────────────┤
    │ 0x00     │ ctrlblock_size      控制块大小                         │
    │ 0x04     │ exception_vector    异常向量 (ESCALATE 跳转地址)       │
    │ 0x08     │ reserved            保留                               │
    │ 0x0C     │ interrupt_ctrl      中断控制器 handle                  │
    │ 0x10     │ ipa_regions         IPA 区域表地址 (父域设置，只读)    │
    │ 0x14     │ domain_id           域ID (系统分配)                    │
    │ 0x18     │ pagetable           页表地址 (子域设置，可写)          │
    │ 0x1C     │ child_block         子域控制块地址                     │
    │ 0x20     │ security_domain     安全域 handle                      │
    │ 0x24     │ access_id           访问 ID (DMA 用)                   │
    ├──────────┴────────────────────────────────────────────────────────┤
    │ 以上为 RPA 通用字段，以下为 SimpleISA 特定字段                      │
    ├──────────┬────────────────────────────────────────────────────────┤
    │ 0x28     │ saved_sp            ESCALATE 保存的栈指针              │
    │ 0x2C     │ saved_lr            ESCALATE 保存的返回地址            │
    │ 0x30     │ saved_psr           ESCALATE 保存的程序状态             │
    │ 0x34     │ reserved            保留                               │
    ├──────────┴────────────────────────────────────────────────────────┤
    │ 中断现场保存区域                                                    │
    ├──────────┬────────────────────────────────────────────────────────┤
    │ 0x40     │ irq_saved_r0        中断保存 R0                        │
    │ 0x44     │ irq_saved_r1        中断保存 R1                        │
    │ ...      │ ...                                                     │
    │ 0x7C     │ irq_saved_pc        中断保存 PC                        │
    │ 0x80     │ irq_saved_psr       中断保存 PSR                       │
    └──────────┴────────────────────────────────────────────────────────┘

IPA 区域表 / 页表条目格式:
==========================

每个条目 12 字节，以全零条目结尾：
    ┌──────────┬────────────────────────────────────────────────────────┐
    │ 偏移     │ 字段                                                   │
    ├──────────┼────────────────────────────────────────────────────────┤
    │ 0x00     │ base                基地址                             │
    │ 0x04     │ size                大小                               │
    │ 0x08     │ attr                属性 (r/w/x/device 等)             │
    └──────────┴────────────────────────────────────────────────────────┘

支持的指令:
============

数据处理：MOV, ADD, SUB, CMP, AND, ORR
加载存储：LDR, STR
分支：B, BEQ, BNE, BL, BX
RPA 指令：DESCEND, ESCALATE, RETURN, SYSOP
特殊：NOP, HALT

调用标准 (Calling Convention):
==============================

寄存器约定:
- r0-r3:  参数/返回值寄存器 (caller-saved)
          - DESCEND 前: 父域在 r0 放控制块地址，r1-r3 可放额外参数
          - ESCALATE 前: 子域在 r0 放 service_type，r1-r3 可放额外参数
          - 返回时: r0-r3 包含返回值
- r4-r12: callee-saved，由被调用者（编译器）负责保存/恢复
- r13 (SP): 栈指针
- r14 (LR): 链接寄存器
- r15 (PC): 程序计数器

上下文保存策略:
- ESCALATE/RETURN: 保存 SP, LR, PSR (12 字节)
- 中断: 保存所有寄存器 R0-R15 + PSR (68 字节)

地址翻译:
============

    LDR/STR 通过 MemoryManager 进行地址翻译:

    ┌─────────────┐      ┌─────────────┐      ┌─────────────┐
    │   Core      │ VA   │ MemoryManager│ PA   │   Memory    │
    │             │─────▶│ translate    │─────▶│             │
    │  LDR/STR    │      │ chain        │      │  read/write │
    └─────────────┘      └─────────────┘      └─────────────┘

    pagetable_chain = [domain_n.pagetable, ..., domain_0.pagetable]
    ipa_regions = 当前域的 IPA 约束 (用于边界检查)
    翻译失败 → TranslationError(memtable_owner)

中断处理:
============

    每条指令执行后检查中断:
    1. 查询 InterruptController.check_interrupt()
    2. 找到最高优先级的待处理中断
    3. 检查 I-bit
    4. 如果需要处理 → 保存所有寄存器 → 跳转到 vector
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any, Tuple
from enum import Enum, auto

# DomainBlock field offsets (imported from rpa_logic)
OFFSET_PAGETABLE = 0x18  # 页表地址 (子域设置)
import re


# DomainBlock 上下文保存区域偏移 (在安全域扩展字段之后)
# 这些偏移是相对于 DomainBlock 起始地址的
# 注意: 0x20-0x27 为 security_domain/access_id 字段，ISA 保存区从 0x28 开始
SAVED_SP_OFFSET = 0x28    # ISA 保存的栈指针
SAVED_LR_OFFSET = 0x2C    # ISA 保存的链接寄存器（返回地址）
SAVED_PSR_OFFSET = 0x30   # ISA 保存的程序状态寄存器 (N, Z, C, V)
# 0x34-0x3F 保留

# 中断现场保存区域偏移 (从 0x40 开始)
IRQ_SAVE_R0 = 0x40
IRQ_SAVE_R1 = 0x44
IRQ_SAVE_R2 = 0x48
IRQ_SAVE_R3 = 0x4C
IRQ_SAVE_R4 = 0x50
IRQ_SAVE_R5 = 0x54
IRQ_SAVE_R6 = 0x58
IRQ_SAVE_R7 = 0x5C
IRQ_SAVE_R8 = 0x60
IRQ_SAVE_R9 = 0x64
IRQ_SAVE_R10 = 0x68
IRQ_SAVE_R11 = 0x6C
IRQ_SAVE_R12 = 0x70
IRQ_SAVE_SP = 0x74
IRQ_SAVE_LR = 0x78
IRQ_SAVE_PC = 0x7C
IRQ_SAVE_PSR = 0x80
IRQ_SAVE_SIZE = 0x44  # 17 * 4 = 68 字节

# 调用标准常量
REG_ARG_START = 0         # r0 - 参数/返回值起始寄存器
REG_ARG_END = 3           # r3 - 参数/返回值结束寄存器
REG_SP = 13               # SP
REG_LR = 14               # LR
REG_PC = 15               # PC
REG_CALLEE_SAVED_START = 4   # r4 - callee-saved 起始
REG_CALLEE_SAVED_END = 12    # r12 - callee-saved 结束


class OpCode(Enum):
    """操作码"""
    # 数据处理
    MOV = auto()
    ADD = auto()
    SUB = auto()
    CMP = auto()
    AND = auto()
    ORR = auto()

    # 加载/存储
    LDR = auto()
    STR = auto()

    # 分支
    B = auto()
    BEQ = auto()
    BNE = auto()
    BL = auto()
    BX = auto()

    # RPA 指令
    DESCEND = auto()
    ESCALATE = auto()
    RETURN = auto()
    EXIT = auto()  # ESCALATE + release child domain

    # 系统操作
    SYSOP = auto()

    # 特殊
    NOP = auto()
    HALT = auto()


@dataclass
class Instruction:
    """单条指令"""
    opcode: OpCode
    rd: int = 0
    rn: int = 0
    rm: int = 0
    imm: int = 0
    addr: int = 0
    label: str = ""
    is_immediate: bool = False
    asm_text: str = ""


@dataclass
class CPUState:
    """CPU 状态"""
    registers: List[int] = field(default_factory=lambda: [0] * 16)
    n: bool = False
    z: bool = False
    c: bool = False
    v: bool = False
    # 中断状态
    irq_disabled: bool = False    # 全局中断禁用（执行中断处理程序时）
    in_interrupt: bool = False    # 是否在中断处理中

    def get_reg(self, idx: int) -> int:
        return self.registers[idx]

    def set_reg(self, idx: int, value: int) -> None:
        self.registers[idx] = value & 0xFFFFFFFF

    @property
    def pc(self) -> int:
        return self.registers[15]

    @pc.setter
    def pc(self, value: int) -> None:
        self.registers[15] = value & 0xFFFFFFFF

    @property
    def sp(self) -> int:
        return self.registers[13]

    @sp.setter
    def sp(self, value: int) -> None:
        self.registers[13] = value & 0xFFFFFFFF

    @property
    def lr(self) -> int:
        return self.registers[14]

    @lr.setter
    def lr(self, value: int) -> None:
        self.registers[14] = value & 0xFFFFFFFF

    def update_flags(self, result: int) -> None:
        result_32 = result & 0xFFFFFFFF
        self.n = (result_32 & 0x80000000) != 0
        self.z = result_32 == 0

    def reset(self) -> None:
        self.registers = [0] * 16
        self.n = False
        self.z = False
        self.c = False
        self.v = False
        self.irq_disabled = False
        self.in_interrupt = False


class Assembler:
    """汇编器"""

    REG_NAMES = {
        'R0': 0, 'R1': 1, 'R2': 2, 'R3': 3,
        'R4': 4, 'R5': 5, 'R6': 6, 'R7': 7,
        'R8': 8, 'R9': 9, 'R10': 10, 'R11': 11,
        'R12': 12, 'R13': 13, 'SP': 13,
        'R14': 14, 'LR': 14,
        'R15': 15, 'PC': 15,
    }

    def __init__(self):
        self.labels: Dict[str, int] = {}
        self.instructions: List[Tuple[int, Instruction]] = []

    def parse_register(self, s: str) -> int:
        s = s.strip().upper()
        if s in self.REG_NAMES:
            return self.REG_NAMES[s]
        raise ValueError(f"未知寄存器: {s}")

    def parse_immediate(self, s: str) -> int:
        s = s.strip()
        if s.startswith('#'):
            s = s[1:]
        s = s.strip()
        if s.startswith('0x') or s.startswith('0X'):
            return int(s, 16)
        elif s.startswith('0b') or s.startswith('0B'):
            return int(s, 2)
        else:
            return int(s)

    def parse_address(self, s: str) -> Tuple[str, int, int]:
        s = s.strip()

        # [Rn]
        match = re.match(r'\[(\w+)\]', s)
        if match:
            reg = self.parse_register(match.group(1))
            return ('reg', reg, 0)

        # [Rn, #offset]
        match = re.match(r'\[(\w+),\s*#([^\]]+)\]', s)
        if match:
            reg = self.parse_register(match.group(1))
            offset = self.parse_immediate(match.group(2))
            return ('reg_offset', reg, offset)

        # =addr
        if s.startswith('='):
            addr = self.parse_immediate(s[1:])
            return ('absolute', 0, addr)

        raise ValueError(f"无法解析地址: {s}")

    def assemble(self, code: str, base_addr: int = 0) -> List[Tuple[int, Instruction]]:
        self.labels = {}
        self.instructions = []

        lines = []
        addr = base_addr

        for line in code.split('\n'):
            if ';' in line:
                line = line[:line.index(';')]
            line = line.strip()

            if not line:
                continue

            if ':' in line:
                parts = line.split(':', 1)
                label = parts[0].strip()
                self.labels[label] = addr
                line = parts[1].strip() if len(parts) > 1 else ''

                if not line:
                    continue

            lines.append((addr, line))
            addr += 4

        for addr, line in lines:
            inst = self._parse_instruction(line, addr)
            if inst:
                inst.asm_text = line
                self.instructions.append((addr, inst))

        return self.instructions

    def _parse_instruction(self, line: str, addr: int) -> Optional[Instruction]:
        parts = line.split(None, 1)
        if not parts:
            return None

        opcode_str = parts[0].upper()
        operands = parts[1] if len(parts) > 1 else ''

        opcode_map = {
            'MOV': OpCode.MOV,
            'ADD': OpCode.ADD,
            'SUB': OpCode.SUB,
            'CMP': OpCode.CMP,
            'AND': OpCode.AND,
            'ORR': OpCode.ORR,
            'LDR': OpCode.LDR,
            'STR': OpCode.STR,
            'B': OpCode.B,
            'BEQ': OpCode.BEQ,
            'BNE': OpCode.BNE,
            'BL': OpCode.BL,
            'BX': OpCode.BX,
            'DESCEND': OpCode.DESCEND,
            'ESCALATE': OpCode.ESCALATE,
            'RETURN': OpCode.RETURN,
            'EXIT': OpCode.EXIT,
            'SYSOP': OpCode.SYSOP,
            'NOP': OpCode.NOP,
            'HALT': OpCode.HALT,
        }

        opcode = opcode_map.get(opcode_str)
        if opcode is None:
            raise ValueError(f"未知操作码: {opcode_str}")

        return self._parse_operands(opcode, operands, addr)

    def _parse_operands(self, opcode: OpCode, operands: str, addr: int) -> Instruction:
        if opcode == OpCode.MOV:
            parts = [p.strip() for p in operands.split(',')]
            rd = self.parse_register(parts[0])
            if parts[1].startswith('#'):
                imm = self.parse_immediate(parts[1])
                return Instruction(opcode=opcode, rd=rd, imm=imm, is_immediate=True)
            else:
                rn = self.parse_register(parts[1])
                return Instruction(opcode=opcode, rd=rd, rn=rn)

        elif opcode in (OpCode.ADD, OpCode.SUB, OpCode.AND, OpCode.ORR):
            parts = [p.strip() for p in operands.split(',')]
            rd = self.parse_register(parts[0])
            rn = self.parse_register(parts[1])
            if parts[2].startswith('#'):
                imm = self.parse_immediate(parts[2])
                return Instruction(opcode=opcode, rd=rd, rn=rn, imm=imm, is_immediate=True)
            else:
                rm = self.parse_register(parts[2])
                return Instruction(opcode=opcode, rd=rd, rn=rn, rm=rm)

        elif opcode == OpCode.CMP:
            parts = [p.strip() for p in operands.split(',')]
            rn = self.parse_register(parts[0])
            if parts[1].startswith('#'):
                imm = self.parse_immediate(parts[1])
                return Instruction(opcode=opcode, rn=rn, imm=imm, is_immediate=True)
            else:
                rm = self.parse_register(parts[1])
                return Instruction(opcode=opcode, rn=rn, rm=rm)

        elif opcode in (OpCode.LDR, OpCode.STR):
            parts = [p.strip() for p in operands.split(',', 1)]
            rd = self.parse_register(parts[0])
            mode, rn, offset = self.parse_address(parts[1])

            if mode == 'absolute':
                return Instruction(opcode=opcode, rd=rd, addr=offset)
            elif mode == 'reg_offset':
                return Instruction(opcode=opcode, rd=rd, rn=rn, imm=offset)
            else:
                return Instruction(opcode=opcode, rd=rd, rn=rn)

        elif opcode in (OpCode.B, OpCode.BEQ, OpCode.BNE, OpCode.BL):
            label = operands.strip()
            if label in self.labels:
                target = self.labels[label]
            else:
                target = self.parse_immediate(label)
            return Instruction(opcode=opcode, addr=target, label=label)

        elif opcode == OpCode.BX:
            rm = self.parse_register(operands.strip())
            return Instruction(opcode=opcode, rm=rm)

        elif opcode in (OpCode.DESCEND, OpCode.ESCALATE, OpCode.RETURN, OpCode.EXIT):
            rd = self.parse_register(operands.strip())
            return Instruction(opcode=opcode, rd=rd)

        elif opcode == OpCode.SYSOP:
            parts = [p.strip() for p in operands.split(',')]
            if len(parts) < 2:
                raise ValueError(f"SYSOP 需要至少 2 个操作数: {operands}")

            op_str = parts[0].upper()
            subop_str = parts[1].upper()

            op_codes = {'IRQ': 0x01, 'MEMTABLE': 0x02, 'PAGETABLE': 0x03, 'SECDOMAIN': 0x04}
            subop_codes = {
                # IRQ subops
                'READ': 0x01, 'WRITE': 0x02, 'ENABLE': 0x03, 'DISABLE': 0x04,
                'SETVEC': 0x05, 'GETPENDING': 0x06, 'CLEAR': 0x07,
                'REQUEST': 0x08, 'RELEASE': 0x09, 'SGI': 0x0A,
                # MEMTABLE/PAGETABLE subops
                'QUERY': 0x10,      # 查询条目，返回 base/size/attr
                'COUNT': 0x11,      # 获取条目数
            }

            op_code = op_codes.get(op_str, 0)
            subop_code = subop_codes.get(subop_str, 0)

            arg1, arg2, rd, rn = 0, 0, 0, 0
            rm = 0  # Third register for multi-register operations

            # Parse arguments based on operation type
            if op_code in (0x02, 0x03) and subop_code == 0x10:
                # MEMTABLE/PAGETABLE QUERY: sysop memtable, query, #index, #regmask
                # regmask: 8-bit bitmap, each bit indicates R0-R7
                # Values assigned: base→lowest, size→middle, attr→highest
                # Example: 0b0111 = R0(base), R1(size), R2(attr)
                if len(parts) >= 3:
                    arg1 = self.parse_immediate(parts[2])  # index
                if len(parts) >= 4:
                    arg2 = self.parse_immediate(parts[3])  # regmask
            elif op_code in (0x02, 0x03) and subop_code == 0x11:
                # MEMTABLE/PAGETABLE COUNT: sysop memtable, count, Rd
                # Returns: Rd = number of entries
                if len(parts) >= 3:
                    rd = self.parse_register(parts[2])
            else:
                # Original format: sysop irq, subop, arg1, arg2
                if len(parts) >= 3:
                    if parts[2].startswith('#'):
                        arg1 = self.parse_immediate(parts[2])
                    else:
                        rn = self.parse_register(parts[2])
                        arg1 = rn

                if len(parts) >= 4:
                    if parts[3].startswith('#'):
                        arg2 = self.parse_immediate(parts[3])
                    else:
                        rd = self.parse_register(parts[3])
                        arg2 = rd

            imm = (op_code << 24) | (subop_code << 16) | (arg1 << 8) | arg2
            return Instruction(opcode=opcode, rd=rd, rn=rn, rm=rm, imm=imm)

        elif opcode in (OpCode.RETURN, OpCode.NOP, OpCode.HALT):
            return Instruction(opcode=opcode)

        return Instruction(opcode=opcode)


class SimpleISA:
    """
    简化指令集核心。

    LDR/STR 通过 MemoryManager 进行地址翻译:
    - pagetable_chain 保存当前域的页表链
    - ipa_regions 保存当前域的 IPA 约束
    - 翻译失败触发 TranslationError (包含 fault_owner)

    DESCEND/ESCALATE/RETURN 指令:
    - DESCEND: 读取 DomainBlock，跳转到 saved_lr (0x2C)
    - ESCALATE: 保存上下文，切换到父域
    - RETURN: 从控制块恢复上下文

    中断处理:
    - 每条指令执行后检查中断
    - 通过 InterruptController 查询待处理中断
    - 保存所有寄存器到中断现场保存区
    """

    def __init__(self, rpa, memory=None, memory_manager=None, interrupt_controller=None, security_controller=None):
        """
        初始化核心。

        Args:
            rpa: RPALogic 实例（管理域状态）
            memory: Memory 实例（物理内存）
            memory_manager: MemoryManager 实例（带翻译的读写）
            interrupt_controller: InterruptController 实例（中断管理）
            security_controller: SecurityDomainController 实例（安全域管理）
        """
        self.state = CPUState()
        self.rpa = rpa
        self.memory = memory
        self.memory_manager = memory_manager
        self.interrupt_controller = interrupt_controller
        self.security_controller = security_controller

        # 当前 Domain 的页表翻译链
        # [domain_n.pagetable, ..., domain_0.pagetable]
        self.pagetable_chain: List[int] = []

        # 当前 Domain 的 IPA 约束 (父域设置的地址范围)
        self.ipa_regions: int = 0

        # 当前 Domain 的控制块地址
        self.domain_block_addr: int = 0

        # 指令存储
        self.instructions: Dict[int, Instruction] = {}
        self.labels: Dict[str, int] = {}
        self.assembler = Assembler()

        # 回调处理器（可选，用于测试和扩展）
        self.sysop_handler: Optional[Callable] = None
        self.fault_handler: Optional[Callable] = None

        # 执行控制
        self.running = False
        self.halted = False
        self.execution_log: List[Dict] = []

    def load_assembly(self, code: str, base_addr: int = 0) -> int:
        """加载汇编代码，返回结束地址"""
        instructions = self.assembler.assemble(code, base_addr)

        for addr, inst in instructions:
            self.instructions[addr] = inst

        self.labels.update(self.assembler.labels)

        if self.memory:
            for addr, inst in instructions:
                encoded = self._encode_instruction(inst)
                self.memory.write_word(addr, encoded)

        return base_addr + len(instructions) * 4

    def _encode_instruction(self, inst: Instruction) -> int:
        """编码指令为 32 位值"""
        opcode_val = inst.opcode.value
        return (opcode_val << 24) | (inst.rd << 16) | (inst.rn << 12) | (inst.rm << 8) | (inst.imm & 0xFF)

    def step(self) -> bool:
        """执行单条指令"""
        if self.halted:
            return False

        pc = self.state.pc
        inst = self.instructions.get(pc)

        if inst is None:
            self.halted = True
            return False

        log_entry = {
            "pc": pc,
            "instruction": inst.asm_text or f"{inst.opcode.name}",
            "registers_before": self.state.registers.copy(),
        }

        self._execute(inst)

        log_entry["registers_after"] = self.state.registers.copy()
        self.execution_log.append(log_entry)

        if self.state.pc == pc and not self.halted:
            self.state.pc = pc + 4

        # 检查中断
        self._check_interrupt()

        return not self.halted

    def run(self, max_steps: int = 10000) -> int:
        """运行直到停机"""
        self.running = True
        steps = 0
        while self.running and steps < max_steps:
            if not self.step():
                break
            steps += 1
        self.running = False
        return steps

    def _execute(self, inst: Instruction) -> None:
        """执行单条指令"""
        opcode = inst.opcode

        # 数据处理
        if opcode == OpCode.MOV:
            if inst.is_immediate:
                self.state.set_reg(inst.rd, inst.imm)
            else:
                self.state.set_reg(inst.rd, self.state.get_reg(inst.rn))

        elif opcode == OpCode.ADD:
            val_n = self.state.get_reg(inst.rn)
            val_m = inst.imm if inst.is_immediate else self.state.get_reg(inst.rm)
            self.state.set_reg(inst.rd, val_n + val_m)
            self.state.update_flags(val_n + val_m)

        elif opcode == OpCode.SUB:
            val_n = self.state.get_reg(inst.rn)
            val_m = inst.imm if inst.is_immediate else self.state.get_reg(inst.rm)
            self.state.set_reg(inst.rd, val_n - val_m)
            self.state.update_flags(val_n - val_m)

        elif opcode == OpCode.CMP:
            val_n = self.state.get_reg(inst.rn)
            val_m = inst.imm if inst.is_immediate else self.state.get_reg(inst.rm)
            self.state.update_flags(val_n - val_m)

        elif opcode == OpCode.AND:
            val_n = self.state.get_reg(inst.rn)
            val_m = inst.imm if inst.is_immediate else self.state.get_reg(inst.rm)
            self.state.set_reg(inst.rd, val_n & val_m)
            self.state.update_flags(val_n & val_m)

        elif opcode == OpCode.ORR:
            val_n = self.state.get_reg(inst.rn)
            val_m = inst.imm if inst.is_immediate else self.state.get_reg(inst.rm)
            self.state.set_reg(inst.rd, val_n | val_m)
            self.state.update_flags(val_n | val_m)

        # 加载/存储
        elif opcode == OpCode.LDR:
            self._execute_ldr(inst)

        elif opcode == OpCode.STR:
            self._execute_str(inst)

        # 分支
        elif opcode == OpCode.B:
            self.state.pc = inst.addr

        elif opcode == OpCode.BEQ:
            if self.state.z:
                self.state.pc = inst.addr

        elif opcode == OpCode.BNE:
            if not self.state.z:
                self.state.pc = inst.addr

        elif opcode == OpCode.BL:
            self.state.lr = self.state.pc + 4
            self.state.pc = inst.addr

        elif opcode == OpCode.BX:
            self.state.pc = self.state.get_reg(inst.rm)

        # RPA 指令
        elif opcode == OpCode.DESCEND:
            self._execute_descend(inst)

        elif opcode == OpCode.ESCALATE:
            self._execute_escalate(inst)

        elif opcode == OpCode.EXIT:
            self._execute_exit(inst)

        elif opcode == OpCode.RETURN:
            self._execute_return(inst)

        elif opcode == OpCode.SYSOP:
            self._execute_sysop(inst)

        elif opcode == OpCode.HALT:
            self.halted = True

        elif opcode == OpCode.NOP:
            pass

    def _execute_ldr(self, inst: Instruction) -> None:
        """执行 LDR 指令，通过 MemoryManager 翻译地址"""
        # 计算虚拟地址
        if inst.addr != 0:
            va = inst.addr
        elif inst.imm != 0:
            va = self.state.get_reg(inst.rn) + inst.imm
        else:
            va = self.state.get_reg(inst.rn)

        try:
            # 使用 MemoryManager 进行带翻译的读取
            if self.memory_manager and len(self.pagetable_chain) > 0:
                value, fault_owner = self.memory_manager.read_with_translation(
                    va, self.pagetable_chain, size=4, ipa_regions=self.ipa_regions
                )
                if fault_owner is not None:
                    # 翻译失败，触发异常
                    if self.fault_handler:
                        self.fault_handler('translation', va, fault_owner)
                    else:
                        self.halted = True
                    return
            elif self.memory:
                # 无翻译链，直接访问
                value = self.memory.read_word(va)
            else:
                value = 0

            self.state.set_reg(inst.rd, value)

        except MemoryError as e:
            # 内存访问错误
            if self.fault_handler:
                self.fault_handler('memory', va, str(e))
            else:
                self.halted = True
        except Exception as e:
            # 权限错误或其他异常
            if self.fault_handler:
                # PermissionError 有 owner_domain 属性
                owner = getattr(e, 'owner_domain', 0)
                self.fault_handler('permission', va, owner)
            else:
                self.halted = True

    def _execute_str(self, inst: Instruction) -> None:
        """执行 STR 指令，通过 MemoryManager 翻译地址"""
        # 计算虚拟地址
        if inst.addr != 0:
            va = inst.addr
        elif inst.imm != 0:
            va = self.state.get_reg(inst.rn) + inst.imm
        else:
            va = self.state.get_reg(inst.rn)

        value = self.state.get_reg(inst.rd)

        try:
            # 使用 MemoryManager 进行带翻译的写入
            if self.memory_manager and len(self.pagetable_chain) > 0:
                fault_owner = self.memory_manager.write_with_translation(
                    va, value, self.pagetable_chain, size=4, ipa_regions=self.ipa_regions
                )
                if fault_owner is not None:
                    # 翻译失败，触发异常
                    if self.fault_handler:
                        self.fault_handler('translation', va, fault_owner)
                    else:
                        self.halted = True
                    return
            elif self.memory:
                # 无翻译链，直接访问
                self.memory.write_word(va, value)

        except MemoryError as e:
            # 内存访问错误
            if self.fault_handler:
                self.fault_handler('memory', va, str(e))
            else:
                self.halted = True
        except Exception as e:
            # 权限错误或其他异常
            if self.fault_handler:
                # PermissionError 有 owner_domain 属性
                owner = getattr(e, 'owner_domain', 0)
                self.fault_handler('permission', va, owner)
            else:
                self.halted = True

    def _execute_sysop(self, inst: Instruction) -> None:
        """执行 SYSOP 指令"""
        op = (inst.imm >> 24) & 0xFF
        subop = (inst.imm >> 16) & 0xFF
        arg1 = (inst.imm >> 8) & 0xFF
        arg2 = inst.imm & 0xFF

        # Operation codes:
        # 0x01: IRQ
        # 0x02: MEMTABLE (IPA regions query)
        # 0x03: PAGETABLE
        # 0x04: SECDOMAIN

        # IRQ 操作
        if op == 0x01 and self.interrupt_controller:
            self._execute_sysop_irq(subop, arg1, arg2, inst.rd, inst.rn)
            return

        # MEMTABLE/PAGETABLE 操作
        if op in (0x02, 0x03):
            self._execute_sysop_table(op, subop, arg1, arg2, inst.rd, inst.rn, inst.rm)
            return

        # 安全域操作
        if op == 0x04 and self.security_controller:
            self._execute_sysop_secdomain(subop, arg1, arg2, inst.rd, inst.rn)
            return

        # 其他操作使用自定义 handler
        if self.sysop_handler:
            result = self.sysop_handler(op, subop, arg1, arg2, inst.rd, inst.rn)
            if result is not None:
                self.state.set_reg(inst.rd, result)

    def _execute_sysop_irq(self, subop: int, arg1: int, arg2: int, rd: int, rn: int) -> None:
        """执行 sysop irq 指令"""
        if not self.interrupt_controller:
            return

        from .interrupt import IrqSubOp

        if subop == IrqSubOp.REQUEST:
            # sysop irq, request, R0, R1  (R0=perms, R1=返回handle)
            # 需要父域调用，简化处理：使用当前域 ID
            permissions = self.state.get_reg(0)
            domain_id = self.rpa.current_domain.domain_id
            handle = self.interrupt_controller.request(domain_id, permissions)
            self.state.set_reg(1, handle)

        elif subop == IrqSubOp.RELEASE:
            # sysop irq, release, Rn
            handle = self.state.get_reg(rn) if rn else arg1
            self.interrupt_controller.release(handle)

        elif subop == IrqSubOp.ENABLE:
            # sysop irq, enable, Rn  (Rn = handle)
            handle = self.state.get_reg(rn) if rn else arg1
            self.interrupt_controller.enable(handle)

        elif subop == IrqSubOp.DISABLE:
            # sysop irq, disable, Rn
            handle = self.state.get_reg(rn) if rn else arg1
            self.interrupt_controller.disable(handle)

        elif subop == IrqSubOp.SETVEC:
            # sysop irq, setvec, Rn, #vector
            handle = self.state.get_reg(rn) if rn else arg1
            vector = arg2
            self.interrupt_controller.set_vector(handle, vector)

        elif subop == IrqSubOp.GETPENDING:
            # sysop irq, getpending, Rn, Rd
            handle = self.state.get_reg(rn) if rn else arg1
            pending = self.interrupt_controller.get_pending(handle)
            self.state.set_reg(rd, pending)

        elif subop == IrqSubOp.CLEAR:
            # sysop irq, clear, Rn, #N
            handle = self.state.get_reg(rn) if rn else arg1
            irq_num = arg2
            self.interrupt_controller.clear_pending(handle, irq_num)

        elif subop == IrqSubOp.SGI:
            # sysop irq, sgi, Rn, #N  (Rn=target_handle, N=irq_num)
            target_handle = self.state.get_reg(rn) if rn else arg1
            irq_num = arg2
            # 需要当前域的 handle
            current_handle = self.rpa.current_domain.block.interrupt_ctrl
            if current_handle:
                self.interrupt_controller.sgi(current_handle, target_handle, irq_num)

    def _execute_sysop_table(self, op: int, subop: int, arg1: int, arg2: int, rd: int, rn: int, rm: int) -> None:
        """
        执行 sysop memtable/pagetable 指令

        sysop memtable, query, #index, #regmask
            - 读取 ipa_regions 表的第 index 个条目
            - regmask: 8-bit bitmap, each bit indicates R0-R7
            - Values assigned in order: base→lowest, size→middle, attr→highest
            - Example: regmask=0x07 (0b0111) means R0=base, R1=size, R2=attr

        sysop memtable, count, Rd
            - 返回 ipa_regions 表的条目数

        sysop pagetable, query, #index, #regmask
            - 读取 pagetable 表的第 index 个条目

        sysop pagetable, count, Rd
            - 返回 pagetable 表的条目数
        """
        # Subop codes
        QUERY = 0x10
        COUNT = 0x11

        # Determine which table to read
        # op 0x02 = MEMTABLE (ipa_regions), op 0x03 = PAGETABLE
        if op == 0x02:
            table_addr = self.ipa_regions
        else:  # op == 0x03
            # Read pagetable from current domain's control block
            table_addr = self.memory.read_word(self.domain_block_addr + OFFSET_PAGETABLE) if self.memory else 0

        if subop == QUERY:
            # Query entry at index arg1
            index = arg1
            regmask = arg2  # 8-bit bitmap for R0-R7

            # Decode registers from bitmap
            # Find set bits and assign: base→lowest, size→middle, attr→highest
            set_bits = []
            for i in range(8):
                if regmask & (1 << i):
                    set_bits.append(i)

            if len(set_bits) < 3:
                # Not enough registers specified, use defaults
                if len(set_bits) == 0:
                    set_bits = [0, 1, 2]  # Default to R0, R1, R2
                elif len(set_bits) == 1:
                    set_bits.extend([set_bits[0] + 1, set_bits[0] + 2])
                elif len(set_bits) == 2:
                    set_bits.append(max(set_bits) + 1)

            rb = set_bits[0]  # base
            rs = set_bits[1]  # size
            ra = set_bits[2]  # attr

            if self.memory and table_addr != 0:
                # Each entry is 12 bytes: base(4) + size(4) + attr(4)
                entry_addr = table_addr + index * 12
                base = self.memory.read_word(entry_addr + 0)
                size = self.memory.read_word(entry_addr + 4)
                attr = self.memory.read_word(entry_addr + 8)

                # Check for end marker (all zeros)
                if base == 0 and size == 0 and attr == 0:
                    # Index out of range, return zeros
                    base = 0
                    size = 0
                    attr = 0
            else:
                base = 0
                size = 0
                attr = 0

            self.state.set_reg(rb, base)
            self.state.set_reg(rs, size)
            self.state.set_reg(ra, attr)

        elif subop == COUNT:
            # Count entries in table
            count = 0
            if self.memory and table_addr != 0:
                # Count entries until end marker
                while True:
                    entry_addr = table_addr + count * 12
                    base = self.memory.read_word(entry_addr + 0)
                    size = self.memory.read_word(entry_addr + 4)
                    attr = self.memory.read_word(entry_addr + 8)
                    if base == 0 and size == 0 and attr == 0:
                        break
                    count += 1
                    # Safety limit
                    if count > 1000:
                        break

            self.state.set_reg(rd, count)

    def _execute_sysop_secdomain(self, subop: int, arg1: int, arg2: int, rd: int, rn: int) -> None:
        """执行 sysop secdomain 指令"""
        if not self.security_controller:
            return

        from .security_domain import SecurityDomainConfig

        # SecDomainSubOp 操作码
        SECDOMAIN_CREATE = 0x01
        SECDOMAIN_DESTROY = 0x02
        SECDOMAIN_BIND = 0x03
        SECDOMAIN_UNBIND = 0x04
        SECDOMAIN_GET_ID = 0x05
        SECDOMAIN_SET_ENCRYPTION = 0x06
        SECDOMAIN_ADD_ACCESSOR = 0x07
        SECDOMAIN_REMOVE_ACCESSOR = 0x08
        SECDOMAIN_FORCE_DESTROY = 0x09
        SECDOMAIN_GET_HANDLE = 0x0A

        if subop == SECDOMAIN_CREATE:
            # sysop secdomain, create, R0, R1
            # R0 = config flags (bit 0: isolated, bit 1: encrypted, bit 2: confidential)
            # R1 = 返回 handle
            flags = self.state.get_reg(0)
            config = SecurityDomainConfig(
                inherit_from_parent=False,
                create_new=True,
                isolated=bool(flags & 0x01),
                encrypted=bool(flags & 0x02),
                confidential=bool(flags & 0x04),
            )
            domain_id = self.rpa.current_domain.domain_id
            handle = self.security_controller.create(domain_id, config)
            self.state.set_reg(1, handle)

        elif subop == SECDOMAIN_DESTROY:
            # sysop secdomain, destroy, Rn
            handle = self.state.get_reg(rn) if rn else arg1
            success = self.security_controller.destroy(handle)
            self.state.set_reg(rd, 1 if success else 0)

        elif subop == SECDOMAIN_FORCE_DESTROY:
            # sysop secdomain, force_destroy, Rn
            # 仅 root 域可用
            handle = self.state.get_reg(rn) if rn else arg1
            if self.rpa.current_domain.domain_id == 0:
                success = self.security_controller.destroy_force(handle)
                self.state.set_reg(rd, 1 if success else 0)
            else:
                self.state.set_reg(rd, 0)  # 非根域无法强制销毁

        elif subop == SECDOMAIN_BIND:
            # sysop secdomain, bind, Rn, R1
            # Rn = handle, R1 = domain_id
            handle = self.state.get_reg(rn) if rn else arg1
            domain_id = self.state.get_reg(1)
            success = self.security_controller.bind_domain(handle, domain_id)
            self.state.set_reg(rd, 1 if success else 0)

        elif subop == SECDOMAIN_UNBIND:
            # sysop secdomain, unbind, Rn, R1
            # Rn = handle, R1 = domain_id
            handle = self.state.get_reg(rn) if rn else arg1
            domain_id = self.state.get_reg(1)
            success = self.security_controller.unbind_domain(handle, domain_id)
            self.state.set_reg(rd, 1 if success else 0)

        elif subop == SECDOMAIN_GET_ID:
            # sysop secdomain, get_id, Rn, Rd
            # Rn = handle, Rd = 返回 domain_id
            handle = self.state.get_reg(rn) if rn else arg1
            domain_id = self.security_controller.allocate_domain_id(handle)
            self.state.set_reg(rd, domain_id)

        elif subop == SECDOMAIN_SET_ENCRYPTION:
            # sysop secdomain, set_encryption, Rn, R1
            # Rn = handle, R1 = (start << 16) | size (高 16 位为起始地址低 16 位，低 16 位为大小)
            # 注意：简化版本，实际应使用两个寄存器
            handle = self.state.get_reg(rn) if rn else arg1
            params = self.state.get_reg(1)
            start = (params >> 16) & 0xFFFF
            start <<= 12  # 页对齐
            size = (params & 0xFFFF)
            size <<= 12  # 页对齐
            success = self.security_controller.set_encryption(handle, start, size)
            self.state.set_reg(rd, 1 if success else 0)

        elif subop == SECDOMAIN_ADD_ACCESSOR:
            # sysop secdomain, add_accessor, Rn, R1
            # Rn = handle, R1 = accessor_domain_id
            handle = self.state.get_reg(rn) if rn else arg1
            accessor_id = self.state.get_reg(1)
            success = self.security_controller.add_dma_accessor(handle, accessor_id)
            self.state.set_reg(rd, 1 if success else 0)

        elif subop == SECDOMAIN_REMOVE_ACCESSOR:
            # sysop secdomain, remove_accessor, Rn, R1
            # Rn = handle, R1 = accessor_domain_id
            handle = self.state.get_reg(rn) if rn else arg1
            accessor_id = self.state.get_reg(1)
            success = self.security_controller.remove_dma_accessor(handle, accessor_id)
            self.state.set_reg(rd, 1 if success else 0)

        elif subop == SECDOMAIN_GET_HANDLE:
            # sysop secdomain, get_handle, R0, Rd
            # R0 = domain_id, Rd = 返回 handle
            domain_id = self.state.get_reg(0)
            handle = self.security_controller.get_domain_security_handle(domain_id)
            self.state.set_reg(rd, handle)

    def _check_interrupt(self) -> None:
        """检查并处理中断"""
        if not self.interrupt_controller:
            return

        # 全局中断禁用时不检查
        if self.state.irq_disabled:
            return

        # 检查是否有待处理的中断
        current_domain_id = self.rpa.current_domain.domain_id
        result = self.interrupt_controller.check_interrupt(current_domain_id, {})

        if result:
            handle, vector = result
            if vector:
                # 保存中断现场
                self._save_irq_context()
                # 标记中断状态
                self.state.irq_disabled = True
                self.state.in_interrupt = True
                # 跳转到中断向量
                self.state.pc = vector

    def _save_irq_context(self) -> None:
        """保存中断现场到 DomainBlock（所有寄存器）"""
        if not self.memory:
            return

        block_addr = self.domain_block_addr

        # 保存 R0-R12
        for i in range(13):
            offset = IRQ_SAVE_R0 + i * 4
            self.memory.write_word(block_addr + offset, self.state.registers[i])

        # 保存 SP, LR, PC
        self.memory.write_word(block_addr + IRQ_SAVE_SP, self.state.sp)
        self.memory.write_word(block_addr + IRQ_SAVE_LR, self.state.lr)
        self.memory.write_word(block_addr + IRQ_SAVE_PC, self.state.pc)

        # 保存 PSR
        psr = (self.state.n << 3) | (self.state.z << 2) | (self.state.c << 1) | self.state.v
        self.memory.write_word(block_addr + IRQ_SAVE_PSR, psr)

    def _restore_irq_context(self) -> None:
        """从中断现场恢复所有寄存器"""
        if not self.memory:
            return

        block_addr = self.domain_block_addr

        # 恢复 R0-R12
        for i in range(13):
            offset = IRQ_SAVE_R0 + i * 4
            self.state.registers[i] = self.memory.read_word(block_addr + offset)

        # 恢复 SP, LR
        self.state.sp = self.memory.read_word(block_addr + IRQ_SAVE_SP)
        self.state.lr = self.memory.read_word(block_addr + IRQ_SAVE_LR)

        # PC 由返回指令设置
        saved_pc = self.memory.read_word(block_addr + IRQ_SAVE_PC)
        self.state.pc = saved_pc

        # 恢复 PSR
        psr = self.memory.read_word(block_addr + IRQ_SAVE_PSR)
        self.state.n = bool(psr & 0x08)
        self.state.z = bool(psr & 0x04)
        self.state.c = bool(psr & 0x02)
        self.state.v = bool(psr & 0x01)

        # 清除中断状态
        self.state.irq_disabled = False
        self.state.in_interrupt = False

    def _execute_descend(self, inst: Instruction) -> None:
        """
        执行 DESCEND 指令

        RTL 操作：
        1. 读取 DomainBlock 地址
        2. 调用 RPALogic.descend() 切换域（首次创建或后续复用）
        3. 调用 ISA.prepare_descend() 处理上下文
        4. 跳转到 saved_lr (统一入口)
           - 首次: 父域在 DESCEND 前写入入口地址到 saved_lr
           - 后续: ESCALATE 已保存返回地址到 saved_lr
        5. 更新 pagetable_chain 和 ipa_regions

        注意：首次和后续 DESCEND 统一使用 saved_lr 作为入口点
        """
        block_addr = self.state.get_reg(inst.rd)

        # 通过 RPALogic 切换域（首次创建或后续复用）
        result = self.rpa.descend(block_addr)
        pagetable = result.get("pagetable", 0)
        ipa_regions = result.get("ipa_regions", 0)

        # RTL 调用 ISA 接口（清空寄存器、恢复上下文）
        self.prepare_descend(block_addr)

        # 统一从 saved_lr 获取入口地址
        # 首次 DESCEND: 父域在执行 DESCEND 前写入入口到 saved_lr
        # 后续 DESCEND: ESCALATE 已保存返回地址到 saved_lr
        self.state.pc = self.state.lr

        # 更新页表链和 IPA 区域
        if pagetable != 0:
            self.pagetable_chain = [pagetable] + self.pagetable_chain
        self.ipa_regions = ipa_regions  # 当前域的 IPA 约束
        # 更新 domain_block_addr
        self.domain_block_addr = block_addr

    def _execute_escalate(self, inst: Instruction, release: bool = False) -> None:
        """
        执行 ESCALATE/EXIT 指令

        RTL 操作：
        1. 读取 service_type
        2. 调用 ISA.complete_escalate() 保存上下文
        3. 切换到父域，跳转到 exception_vector

        Args:
            inst: 指令
            release: True 表示 EXIT（释放子域），False 表示 ESCALATE
        """
        service_type = self.state.get_reg(inst.rd)
        block_addr = self.domain_block_addr

        # RTL 调用 ISA 接口保存上下文
        self.complete_escalate(block_addr, service_type)

        # 通过 RPALogic 切换域
        result = self.rpa.escalate(service_type, release=release)
        vector = result.get("vector", 0)
        if vector:
            self.state.pc = vector
        else:
            self.halted = True
        # 更新页表链（移除当前域的页表）
        if self.pagetable_chain:
            self.pagetable_chain = self.pagetable_chain[1:]
        # 恢复父域的 IPA 约束
        parent_block = self.rpa.current_domain.block
        self.ipa_regions = parent_block.ipa_regions if parent_block else 0
        # 更新 domain_block_addr 为父域
        self.domain_block_addr = self.rpa.current_domain.block_addr

    def _execute_exit(self, inst: Instruction) -> None:
        """
        执行 EXIT 指令

        EXIT = ESCALATE(release=True)
        子域终止，父域无法 RETURN，子域控制块可被重新使用。
        """
        self._execute_escalate(inst, release=True)

    def _execute_return(self, inst: Instruction) -> None:
        """
        执行 RETURN 指令

        RETURN 是 DESCEND 的别名，用于从父域返回子域。
        逻辑与后续 DESCEND 完全相同：恢复子域上下文并继续执行。
        """
        self._execute_descend(inst)

    def _save_context(self, block_addr: int) -> None:
        """保存当前域上下文到 DomainBlock"""
        if self.memory:
            self.memory.write_word(block_addr + SAVED_SP_OFFSET, self.state.sp)
            self.memory.write_word(block_addr + SAVED_LR_OFFSET, self.state.pc + 4)  # 返回地址
            # 保存 PSR (N, Z, C, V 标志位打包为一个字)
            psr = (self.state.n << 3) | (self.state.z << 2) | (self.state.c << 1) | self.state.v
            self.memory.write_word(block_addr + SAVED_PSR_OFFSET, psr)

    def _restore_context(self, block_addr: int) -> None:
        """从 DomainBlock 恢复域上下文（不含 PC）"""
        if self.memory:
            self.state.sp = self.memory.read_word(block_addr + SAVED_SP_OFFSET)
            self.state.lr = self.memory.read_word(block_addr + SAVED_LR_OFFSET)
            psr = self.memory.read_word(block_addr + SAVED_PSR_OFFSET)
            self.state.n = bool(psr & 0x08)
            self.state.z = bool(psr & 0x04)
            self.state.c = bool(psr & 0x02)
            self.state.v = bool(psr & 0x01)

    def prepare_descend(self, block_addr: int) -> None:
        """
        RPALogic pseudo-RTL 在 DESCEND 前自动调用

        第一次 DESCEND（创建线程）：
        - 子域没有上下文，清零 r4-r12
        - LR 从 DomainBlock.saved_lr 恢复（父域在 DESCEND 前设置入口地址）
        - SP 保持为 0（由父域软件通过 DomainBlock 设置）

        后续 DESCEND（RETURN 复用）：
        - 从 DomainBlock 恢复子域上下文（SP, LR, PSR）

        安全措施：清空 r4-r12 防止信息泄露

        Args:
            block_addr: 子域 DomainBlock 在内存中的地址
        """
        # 清空 callee-saved 寄存器（安全措施）
        for i in range(REG_CALLEE_SAVED_START, REG_CALLEE_SAVED_END + 1):
            self.state.set_reg(i, 0)

        # 恢复上下文（包括 LR）
        # 首次: saved_lr 由父域设置为入口地址
        # 后续: saved_lr 由 ESCALATE 保存返回地址
        self._restore_context(block_addr)

    def complete_escalate(self, block_addr: int, service_type: int) -> None:
        """
        RPALogic pseudo-RTL 在 ESCALATE 后自动调用

        保存子域上下文到子域 DomainBlock：
        - SP (r13)
        - LR (返回地址 = PC + 4)
        - PSR (N, Z, C, V 标志位)

        注意：r0-r3 不保存，用于传递参数/返回值

        Args:
            block_addr: 当前域 DomainBlock 在内存中的地址
            service_type: 服务类型（从 r0 寄存器读取）
        """
        self._save_context(block_addr)

    def reset(self) -> None:
        """重置核心状态"""
        self.state.reset()
        self.halted = False
        self.running = False
        self.execution_log.clear()

    def get_state_dump(self) -> Dict[str, Any]:
        """获取当前状态"""
        return {
            "registers": {f"R{i}": hex(self.state.registers[i]) for i in range(16)},
            "flags": {"N": self.state.n, "Z": self.state.z, "C": self.state.c, "V": self.state.v},
            "pc": hex(self.state.pc),
            "halted": self.halted,
            "pagetable_chain": [hex(m) for m in self.pagetable_chain],
            "ipa_regions": hex(self.ipa_regions),
        }

    def get_execution_log(self) -> List[Dict]:
        return self.execution_log.copy()

    def clear_execution_log(self) -> None:
        self.execution_log.clear()


def Asm(code: str, base_addr: int = 0, decoder: Optional['SimpleISA'] = None) -> int:
    """汇编代码快捷函数"""
    if decoder:
        return decoder.load_assembly(code, base_addr)
    else:
        assembler = Assembler()
        assembler.assemble(code, base_addr)
        return base_addr + len(assembler.instructions) * 4