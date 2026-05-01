"""
SimpleCore - 简化指令集核心

这是 RPA 架构的指令执行核心。每个 Domain 可以有不同的 ISA 实现，
SimpleCore 是一个简化版的类 ARM 指令集，用于演示 RPA 的核心机制。

核心概念：
============

        ┌─────────────────────────────────────────────────────────────────┐
        │                        Domain 层级结构                           │
        ├─────────────────────────────────────────────────────────────────┤
        │                                                                 │
        │    ┌──────────────────┐                                         │
        │    │   Domain 0       │  ← 根域 (root_domain)                   │
        │    │   (最高特权)      │                                         │
        │    │                  │                                         │
        │    │  ┌────────────┐  │                                         │
        │    │  │ Domain 1   │  │  ← 子域                                 │
        │    │  │            │  │                                         │
        │    │  │ ┌────────┐ │  │                                         │
        │    │  │ │Domain 2│ │  │  ← 孙域                                 │
        │    │  │ └────────┘ │  │                                         │
        │    │  └────────────┘  │                                         │
        │    └──────────────────┘                                         │
        │                                                                 │
        └─────────────────────────────────────────────────────────────────┘

        DESCEND: Domain 0 → Domain 1 → Domain 2 (向下进入子域)
        ESCALATE: Domain 2 → Domain 1 → Domain 0 (向上请求服务)

DomainBlock (控制块):
====================

        ┌────────────────────────────────────────────────────────────────┐
        │                    DomainBlock 内存布局                         │
        │                      (128 字节, 64字节对齐)                      │
        ├────────────┬───────────────────────────────────────────────────┤
        │ 偏移       │ 字段名                    │ 说明                  │
        ├────────────┼───────────────────────────┼───────────────────────┤
        │ 0x00       │ entry_addr                │ 入口地址              │
        │ 0x04       │ exception_vector          │ 异常向量              │
        │ 0x08       │ interrupt_vector          │ 中断向量              │
        │ 0x0C       │ interrupt_ctrl_base       │ 中断控制器基址        │
        │ 0x10       │ memtable_addr             │ 内存区域表地址        │
        │ 0x14       │ pagetable_addr            │ 页表基址              │
        │ 0x18       │ flags                     │ 控制标志              │
        │ 0x1C-0x3B  │ reserved                  │ 保留                  │
        ├────────────┼───────────────────────────┼───────────────────────┤
        │ 0x3C       │ saved_pc                  │ 保存的 PC             │
        │ 0x40       │ saved_lr                  │ 保存的 LR             │
        │ 0x44       │ saved_sp                  │ 保存的 SP             │
        │ 0x48-0x78  │ saved_regs[13]            │ 保存的 R0-R12         │
        │ 0x78       │ saved_flags               │ 保存的条件标志        │
        │ 0x7C       │ return_value              │ 返回值                │
        ├────────────┼───────────────────────────┼───────────────────────┤
        │ 0x80       │ exception_type            │ 异常类型              │
        │ 0x84       │ exception_addr            │ 异常地址              │
        │ 0x88       │ exception_info            │ 异常详情              │
        └────────────┴───────────────────────────┴───────────────────────┘

地址翻译流程:
=============

        ┌─────────────────────────────────────────────────────────────────┐
        │                     地址翻译 (多级页表)                          │
        ├─────────────────────────────────────────────────────────────────┤
        │                                                                 │
        │   Domain 2 的 VA                                                │
        │        │                                                        │
        │        ▼                                                        │
        │   ┌─────────┐                                                   │
        │   │ PT 2    │  ← Domain 2 的页表                                │
        │   └────┬────┘                                                   │
        │        │ 翻译                                                   │
        │        ▼                                                        │
        │   Domain 1 的 VA (实际上是 Domain 2 的 "PA")                    │
        │        │                                                        │
        │        ▼                                                        │
        │   ┌─────────┐                                                   │
        │   │ PT 1    │  ← Domain 1 的页表                                │
        │   └────┬────┘                                                   │
        │        │ 翻译                                                   │
        │        ▼                                                        │
        │   Domain 0 的 VA (实际上是 Domain 1 的 "PA")                    │
        │        │                                                        │
        │        ▼                                                        │
        │   ┌─────────┐                                                   │
        │   │ PT 0    │  ← Domain 0 的页表 (根页表)                       │
        │   └────┬────┘                                                   │
        │        │ 翻译                                                   │
        │        ▼                                                        │
        │   真正的物理地址 (PA)                                           │
        │                                                                 │
        │   如果任何一步翻译失败 → 触发缺页异常                           │
        └─────────────────────────────────────────────────────────────────┘

DESCEND/ESCALATE 流程:
======================

        DESCEND R0 (R0 = 控制块地址):

        ┌──────────────┐                    ┌──────────────┐
        │   父域       │                    │   子域       │
        │              │                    │              │
        │  1. 保存上下文到控制块            │              │
        │  2. 读取子域 entry_addr ──────────▶ 开始执行    │
        │              │                    │              │
        │              │                    │  ...执行...  │
        │              │                    │              │
        └──────────────┘                    └──────────────┘


        ESCALATE R0 (R0 = 服务类型):

        ┌──────────────┐                    ┌──────────────┐
        │   父域       │                    │   子域       │
        │              │                    │              │
        │              │  1. 保存上下文到控制块            │
        │              │  2. 写入服务类型到 return_value   │
        │  跳转到      │◀───── 3. 切换到父域 ─────────────│
        │  exception_  │                    │              │
        │  vector      │                    │  (等待返回)  │
        │              │                    │              │
        │  4. 处理服务请求                   │              │
        │  5. RETURN 返回 ──────────────────▶ 恢复执行    │
        │              │                    │              │
        └──────────────┘                    └──────────────┘

支持的指令:
===========

数据处理：MOV, ADD, SUB, CMP, AND, ORR
加载存储：LDR, STR
分支：B, BEQ, BNE, BL, BX
RPA 指令：DESCEND, ESCALATE, RETURN, SYSOP
特殊：NOP, HALT

注意：这些指令是简化的示例指令，与真实架构指令相似但不完全相同。
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any, Tuple
from enum import Enum, auto
import struct
import re


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
    DESCEND = auto()    # 进入子域
    ESCALATE = auto()   # 请求父域服务
    RETURN = auto()     # 返回子域

    # 系统操作
    SYSOP = auto()

    # 特殊
    NOP = auto()
    HALT = auto()


@dataclass
class Instruction:
    """单条指令"""
    opcode: OpCode
    rd: int = 0       # 目标寄存器
    rn: int = 0       # 第一个操作数寄存器
    rm: int = 0       # 第二个操作数寄存器
    imm: int = 0      # 立即数
    addr: int = 0     # 地址（用于LDR/STR/分支）
    label: str = ""   # 标签
    is_immediate: bool = False  # 是否为立即数形式
    asm_text: str = ""  # 原始汇编文本（用于调试）


@dataclass
class CPUState:
    """
    CPU 状态

    寄存器布局：
    ┌─────────────────────────────────────┐
    │ R0-R12: 通用寄存器                  │
    │ R13 (SP): 栈指针                    │
    │ R14 (LR): 链接寄存器                │
    │ R15 (PC): 程序计数器                │
    ├─────────────────────────────────────┤
    │ N: 负数标志                         │
    │ Z: 零标志                           │
    │ C: 进位标志                         │
    │ V: 溢出标志                         │
    └─────────────────────────────────────┘
    """
    registers: List[int] = field(default_factory=lambda: [0] * 16)
    n: bool = False   # 负数
    z: bool = False   # 零
    c: bool = False   # 进位
    v: bool = False   # 溢出
    privilege_level: int = 0

    def get_reg(self, idx: int) -> int:
        """获取寄存器值"""
        return self.registers[idx]

    def set_reg(self, idx: int, value: int) -> None:
        """设置寄存器值"""
        self.registers[idx] = value & 0xFFFFFFFF

    @property
    def pc(self) -> int:
        """程序计数器 (R15)"""
        return self.registers[15]

    @pc.setter
    def pc(self, value: int) -> None:
        self.registers[15] = value & 0xFFFFFFFF

    @property
    def sp(self) -> int:
        """栈指针 (R13)"""
        return self.registers[13]

    @sp.setter
    def sp(self, value: int) -> None:
        self.registers[13] = value & 0xFFFFFFFF

    @property
    def lr(self) -> int:
        """链接寄存器 (R14)"""
        return self.registers[14]

    @lr.setter
    def lr(self, value: int) -> None:
        self.registers[14] = value & 0xFFFFFFFF

    def update_flags(self, result: int) -> None:
        """根据结果更新条件标志"""
        result_32 = result & 0xFFFFFFFF
        self.n = (result_32 & 0x80000000) != 0
        self.z = result_32 == 0

    def reset(self) -> None:
        """重置状态"""
        self.registers = [0] * 16
        self.n = False
        self.z = False
        self.c = False
        self.v = False
        self.privilege_level = 0


class Assembler:
    """
    汇编器 - 将汇编代码转换为指令。

    支持的语法：
        MOV Rd, #imm          ; 立即数传送
        MOV Rd, Rn            ; 寄存器传送
        ADD Rd, Rn, Rm        ; 加法
        ADD Rd, Rn, #imm      ; 加立即数
        SUB Rd, Rn, Rm        ; 减法
        SUB Rd, Rn, #imm      ; 减立即数
        CMP Rn, Rm            ; 比较寄存器
        CMP Rn, #imm          ; 比较立即数
        AND Rd, Rn, Rm        ; 与
        ORR Rd, Rn, Rm        ; 或
        LDR Rd, [Rn]          ; 加载
        LDR Rd, [Rn, #offset] ; 带偏移加载
        LDR Rd, =addr         ; 加载地址
        STR Rd, [Rn]          ; 存储
        STR Rd, [Rn, #offset] ; 带偏移存储
        B label               ; 无条件分支
        BEQ label             ; 相等时分支
        BNE label             ; 不等时分支
        BL label              ; 带链接分支
        BX Rm                 ; 寄存器分支
        DESCEND Rd            ; RPA: 进入子域（Rd = 控制块地址）
        ESCALATE Rd           ; RPA: 请求父域服务（Rd = 服务类型）
        RETURN                ; RPA: 返回子域
        SYSOP op, subop, a1, a2 ; 系统操作
        NOP                   ; 空操作
        HALT                  ; 停机

    标签定义：
        label: MOV R0, #1      ; 标签后跟冒号
    """

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
        """解析寄存器名称"""
        s = s.strip().upper()
        if s in self.REG_NAMES:
            return self.REG_NAMES[s]
        raise ValueError(f"未知寄存器: {s}")

    def parse_immediate(self, s: str) -> int:
        """解析立即数"""
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
        """解析地址模式，返回 (mode, base_reg, offset)"""
        s = s.strip()

        # [Rn] 模式
        match = re.match(r'\[(\w+)\]', s)
        if match:
            reg = self.parse_register(match.group(1))
            return ('reg', reg, 0)

        # [Rn, #offset] 模式
        match = re.match(r'\[(\w+),\s*#([^\]]+)\]', s)
        if match:
            reg = self.parse_register(match.group(1))
            offset = self.parse_immediate(match.group(2))
            return ('reg_offset', reg, offset)

        # =addr 模式（伪指令）
        if s.startswith('='):
            addr = self.parse_immediate(s[1:])
            return ('absolute', 0, addr)

        raise ValueError(f"无法解析地址: {s}")

    def assemble(self, code: str, base_addr: int = 0) -> List[Tuple[int, Instruction]]:
        """汇编代码"""
        self.labels = {}
        self.instructions = []

        # 预处理：移除注释，提取标签
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

        # 第二遍：解析指令
        for addr, line in lines:
            inst = self._parse_instruction(line, addr)
            if inst:
                inst.asm_text = line
                self.instructions.append((addr, inst))

        return self.instructions

    def _parse_instruction(self, line: str, addr: int) -> Optional[Instruction]:
        """解析单条指令"""
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
            'SYSOP': OpCode.SYSOP,
            'NOP': OpCode.NOP,
            'HALT': OpCode.HALT,
        }

        opcode = opcode_map.get(opcode_str)
        if opcode is None:
            raise ValueError(f"未知操作码: {opcode_str}")

        return self._parse_operands(opcode, operands, addr)

    def _parse_operands(self, opcode: OpCode, operands: str, addr: int) -> Instruction:
        """解析操作数"""
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

        elif opcode in (OpCode.DESCEND, OpCode.ESCALATE):
            rd = self.parse_register(operands.strip())
            return Instruction(opcode=opcode, rd=rd)

        elif opcode == OpCode.SYSOP:
            # SYSOP op, subop, arg1, arg2
            parts = [p.strip() for p in operands.split(',')]
            if len(parts) < 2:
                raise ValueError(f"SYSOP 需要至少 2 个操作数: {operands}")

            op_str = parts[0].upper()
            subop_str = parts[1].upper()

            op_codes = {'IRQ': 0x01, 'MEMTABLE': 0x02}
            subop_codes = {'READ': 0x01, 'WRITE': 0x02, 'ENABLE': 0x03, 'DISABLE': 0x04}

            op_code = op_codes.get(op_str, 0)
            subop_code = subop_codes.get(subop_str, 0)

            arg1, arg2, rd, rn = 0, 0, 0, 0

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
            return Instruction(opcode=opcode, rd=rd, rn=rn, imm=imm)

        elif opcode in (OpCode.RETURN, OpCode.NOP, OpCode.HALT):
            return Instruction(opcode=opcode)

        return Instruction(opcode=opcode)


class SimpleCore:
    """
    简化指令集核心。

    每个Domain可以有不同的ISA实现，这是简化版的类ARM指令集。
    用于演示 RPA 的 descend/escalate 机制。

    关键行为：
    ===========

    DESCEND R0 (R0 = 控制块地址):
        1. 保存当前上下文到控制块
        2. 读取子域控制块的 entry_addr
        3. 跳转到 entry_addr 开始执行子域代码

    ESCALATE R0 (R0 = 服务类型):
        1. 保存当前上下文到控制块
        2. 写入服务类型到 return_value
        3. 写入异常类型 (0x00 = ESCALATE)
        4. 切换到父域
        5. 跳转到父域的 exception_vector

    RETURN:
        1. 从控制块恢复子域上下文
        2. 继续执行子域代码

    地址翻译:
    =========
        当前层 VA → 页表翻译 → 上一层 VA → ... → 真正 PA
        翻译失败 → 触发缺页异常
    """

    def __init__(self, memory=None, rpa_core=None, domain_block_addr: int = 0):
        """
        初始化核心。

        Args:
            memory: Memory 实例（物理内存）
            rpa_core: RPACore 实例（用于异常处理）
            domain_block_addr: 当前域的控制块地址
        """
        self.state = CPUState()
        self.memory = memory
        self.rpa_core = rpa_core

        # 当前域的控制块地址
        self.domain_block_addr = domain_block_addr

        # 页表（用于地址翻译）
        self.page_table: Optional[Any] = None

        # 父域的核心（用于 ESCALATE 切换）
        self.parent_core: Optional['SimpleCore'] = None

        # 指令存储：地址 -> 指令
        self.instructions: Dict[int, Instruction] = {}

        # 标签：名称 -> 地址
        self.labels: Dict[str, int] = {}

        # 汇编器
        self.assembler = Assembler()

        # 回调式处理器（向后兼容，逐步废弃）
        self.descend_handler: Optional[Callable] = None
        self.escalate_handler: Optional[Callable] = None
        self.return_handler: Optional[Callable] = None

        # 系统操作处理器
        self.sysop_handler: Optional[Callable] = None

        # 执行控制
        self.running = False
        self.halted = False

        # 执行历史
        self.execution_log: List[Dict] = []

    def load_assembly(self, code: str, base_addr: int = 0) -> int:
        """加载汇编代码到内存，返回结束地址"""
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
        encoded = (opcode_val << 24) | (inst.rd << 16) | (inst.rn << 12) | (inst.rm << 8) | (inst.imm & 0xFF)
        return encoded

    def decode_instruction(self, word: int) -> Optional[Instruction]:
        """从内存字解码指令"""
        opcode_val = (word >> 24) & 0xFF
        rd = (word >> 16) & 0xF
        rn = (word >> 12) & 0xF
        rm = (word >> 8) & 0xF
        imm = word & 0xFF

        try:
            opcode = OpCode(opcode_val)
            return Instruction(opcode=opcode, rd=rd, rn=rn, rm=rm, imm=imm)
        except ValueError:
            return None

    def step(self) -> bool:
        """执行单条指令，返回是否应该继续执行"""
        if self.halted:
            return False

        pc = self.state.pc
        inst = self.instructions.get(pc)

        if inst is None:
            self.halted = True
            return False

        # 记录执行历史
        log_entry = {
            "pc": pc,
            "instruction": inst.asm_text or f"{inst.opcode.name}",
            "opcode": inst.opcode.name,
            "rd": inst.rd,
            "rn": inst.rn,
            "rm": inst.rm,
            "imm": inst.imm,
            "registers_before": self.state.registers.copy(),
        }

        self._execute(inst)

        log_entry["registers_after"] = self.state.registers.copy()
        log_entry["flags"] = {"N": self.state.n, "Z": self.state.z}
        self.execution_log.append(log_entry)

        if self.state.pc == pc and not self.halted:
            self.state.pc = pc + 4

        return not self.halted

    def run(self, max_steps: int = 10000) -> int:
        """运行直到停机或达到最大步数"""
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

        # ===== 数据处理指令 =====
        if opcode == OpCode.MOV:
            if inst.is_immediate:
                self.state.set_reg(inst.rd, inst.imm)
            else:
                self.state.set_reg(inst.rd, self.state.get_reg(inst.rn))

        elif opcode == OpCode.ADD:
            val_n = self.state.get_reg(inst.rn)
            if inst.is_immediate:
                result = val_n + inst.imm
            else:
                result = val_n + self.state.get_reg(inst.rm)
            self.state.set_reg(inst.rd, result)
            self.state.update_flags(result)

        elif opcode == OpCode.SUB:
            val_n = self.state.get_reg(inst.rn)
            if inst.is_immediate:
                result = val_n - inst.imm
            else:
                result = val_n - self.state.get_reg(inst.rm)
            self.state.set_reg(inst.rd, result)
            self.state.update_flags(result)

        elif opcode == OpCode.CMP:
            val_n = self.state.get_reg(inst.rn)
            if inst.is_immediate:
                result = val_n - inst.imm
            else:
                result = val_n - self.state.get_reg(inst.rm)
            self.state.update_flags(result)

        elif opcode == OpCode.AND:
            val_n = self.state.get_reg(inst.rn)
            if inst.is_immediate:
                result = val_n & inst.imm
            else:
                result = val_n & self.state.get_reg(inst.rm)
            self.state.set_reg(inst.rd, result)
            self.state.update_flags(result)

        elif opcode == OpCode.ORR:
            val_n = self.state.get_reg(inst.rn)
            if inst.is_immediate:
                result = val_n | inst.imm
            else:
                result = val_n | self.state.get_reg(inst.rm)
            self.state.set_reg(inst.rd, result)
            self.state.update_flags(result)

        # ===== 加载/存储指令 =====
        elif opcode == OpCode.LDR:
            if inst.addr != 0:
                addr = inst.addr
            elif inst.imm != 0:
                addr = self.state.get_reg(inst.rn) + inst.imm
            else:
                addr = self.state.get_reg(inst.rn)

            # 地址翻译
            try:
                pa = self.translate_address(addr)
            except MemoryError:
                return

            if self.memory:
                value = self.memory.read_word(pa)
            else:
                value = 0
            self.state.set_reg(inst.rd, value)

        elif opcode == OpCode.STR:
            if inst.addr != 0:
                addr = inst.addr
            elif inst.imm != 0:
                addr = self.state.get_reg(inst.rn) + inst.imm
            else:
                addr = self.state.get_reg(inst.rn)

            # 地址翻译
            try:
                pa = self.translate_address(addr)
            except MemoryError:
                return

            value = self.state.get_reg(inst.rd)
            if self.memory:
                self.memory.write_word(pa, value)

        # ===== 分支指令 =====
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
            target = self.state.get_reg(inst.rm)
            self.state.pc = target

        # ===== RPA 指令 =====
        elif opcode == OpCode.DESCEND:
            self._execute_descend(inst)

        elif opcode == OpCode.ESCALATE:
            self._execute_escalate(inst)

        elif opcode == OpCode.RETURN:
            self._execute_return(inst)

        elif opcode == OpCode.SYSOP:
            self._execute_sysop(inst)

        elif opcode == OpCode.HALT:
            self.halted = True

        elif opcode == OpCode.NOP:
            pass

    def _execute_descend(self, inst: Instruction) -> None:
        """
        执行 DESCEND 指令

        流程：
        ┌─────────────────────────────────────────────────┐
        │ 1. 从 Rd 读取控制块地址                          │
        │ 2. 保存当前上下文到当前域的控制块                 │
        │ 3. 读取子域控制块的 entry_addr                   │
        │ 4. 跳转到 entry_addr                             │
        └─────────────────────────────────────────────────┘
        """
        block_addr = self.state.get_reg(inst.rd)

        # 保存当前上下文
        if self.memory and self.domain_block_addr != 0:
            self._save_context_to_block(self.domain_block_addr)

        # 读取子域入口地址
        if self.memory:
            child_entry = self.memory.read_word(block_addr + 0x00)
        else:
            child_entry = 0

        # 回调式处理器（向后兼容）
        if self.descend_handler:
            result = self.descend_handler(block_addr)
            self.state.set_reg(0, result)
        else:
            # 跳转到子域入口
            self.state.pc = child_entry
            self.domain_block_addr = block_addr

    def _execute_escalate(self, inst: Instruction) -> None:
        """
        执行 ESCALATE 指令

        流程：
        ┌─────────────────────────────────────────────────┐
        │ 1. 从 Rd 读取服务类型                            │
        │ 2. 保存当前上下文到控制块                         │
        │ 3. 写入服务类型到 return_value (0x7C)            │
        │ 4. 写入异常类型 = 0x00 (ESCALATE)                │
        │ 5. 写入异常地址 = 当前 PC                        │
        │ 6. 切换到父域                                    │
        │ 7. 跳转到父域的 exception_vector                 │
        └─────────────────────────────────────────────────┘
        """
        service_type = self.state.get_reg(inst.rd)

        # 保存上下文
        if self.memory and self.domain_block_addr != 0:
            self._save_context_to_block(self.domain_block_addr)
            self.memory.write_word(self.domain_block_addr + 0x7C, service_type)
            self.memory.write_word(self.domain_block_addr + 0x80, 0x00)  # ESCALATE
            self.memory.write_word(self.domain_block_addr + 0x84, self.state.pc)

        # 回调式处理器（向后兼容）
        if self.escalate_handler:
            result = self.escalate_handler(service_type)
            self.state.set_reg(0, result)
        elif self.parent_core:
            # 切换到父域
            parent_block = self.parent_core.domain_block_addr
            if self.memory and parent_block != 0:
                exception_vector = self.memory.read_word(parent_block + 0x04)
                self.parent_core.state.pc = exception_vector
            self.halted = True
        else:
            self.halted = True

    def _execute_return(self, inst: Instruction) -> None:
        """
        执行 RETURN 指令

        流程：
        ┌─────────────────────────────────────────────────┐
        │ 1. 从控制块恢复上下文                             │
        │ 2. 从 saved_pc 恢复执行                          │
        └─────────────────────────────────────────────────┘
        """
        if self.memory and self.domain_block_addr != 0:
            self._restore_context_from_block(self.domain_block_addr)

        if self.return_handler:
            result = self.state.get_reg(0)
            self.return_handler(result)
        else:
            self.halted = False

    def _execute_sysop(self, inst: Instruction) -> None:
        """执行 SYSOP 指令"""
        op = (inst.imm >> 24) & 0xFF
        subop = (inst.imm >> 16) & 0xFF
        arg1 = (inst.imm >> 8) & 0xFF
        arg2 = inst.imm & 0xFF

        if self.sysop_handler:
            result = self.sysop_handler(op, subop, arg1, arg2, inst.rd, inst.rn)
            if result is not None:
                self.state.set_reg(inst.rd, result)
        else:
            if self.rpa_core:
                self.rpa_core.fault("privilege_violation", self.state.pc)

    def _save_context_to_block(self, block_addr: int) -> None:
        """
        保存上下文到控制块

        控制块布局：
        0x3C: saved_pc
        0x40: saved_lr
        0x44: saved_sp
        0x48-0x78: saved_regs (R0-R12)
        0x78: saved_flags
        """
        if not self.memory:
            return

        self.memory.write_word(block_addr + 0x3C, self.state.pc)
        self.memory.write_word(block_addr + 0x40, self.state.lr)
        self.memory.write_word(block_addr + 0x44, self.state.sp)

        for i in range(13):
            self.memory.write_word(block_addr + 0x48 + i * 4, self.state.get_reg(i))

        flags = 0
        if self.state.n:
            flags |= 1 << 31
        if self.state.z:
            flags |= 1 << 30
        if self.state.c:
            flags |= 1 << 29
        if self.state.v:
            flags |= 1 << 28
        self.memory.write_word(block_addr + 0x78, flags)

    def _restore_context_from_block(self, block_addr: int) -> None:
        """从控制块恢复上下文"""
        if not self.memory:
            return

        self.state.pc = self.memory.read_word(block_addr + 0x3C)
        self.state.lr = self.memory.read_word(block_addr + 0x40)
        self.state.sp = self.memory.read_word(block_addr + 0x44)

        for i in range(13):
            self.state.set_reg(i, self.memory.read_word(block_addr + 0x48 + i * 4))

        flags = self.memory.read_word(block_addr + 0x78)
        self.state.n = bool(flags & (1 << 31))
        self.state.z = bool(flags & (1 << 30))
        self.state.c = bool(flags & (1 << 29))
        self.state.v = bool(flags & (1 << 28))

    def translate_address(self, va: int) -> int:
        """
        翻译虚拟地址到物理地址

        地址翻译流程：
        ┌─────────────────────────────────────────────────┐
        │ 当前层 VA                                       │
        │     │                                           │
        │     ▼                                           │
        │ 当前层页表翻译                                   │
        │     │                                           │
        │     ▼                                           │
        │ 父层 VA (如果有父层)                            │
        │     │                                           │
        │     ▼                                           │
        │ 父层页表翻译                                     │
        │     │                                           │
        │     ▼                                           │
        │ ... 递归翻译 ...                                │
        │     │                                           │
        │     ▼                                           │
        │ 物理地址 PA                                     │
        │                                                 │
        │ 翻译失败 → MemoryError (缺页异常)               │
        └─────────────────────────────────────────────────┘
        """
        # 无页表时 VA = PA
        if self.page_table is None:
            pa = va
        else:
            pa = self.page_table.translate(va)
            if pa is None:
                if self.rpa_core:
                    self.rpa_core.fault("page_fault", va)
                raise MemoryError(f"Page fault: VA=0x{va:#x}")

        # 递归翻译到父层
        if self.parent_core:
            return self.parent_core.translate_address(pa)

        return pa

    def read_memory_va(self, va: int, size: int = 4) -> int:
        """通过地址翻译读取内存"""
        pa = self.translate_address(va)
        if not self.memory:
            return 0
        if size == 1:
            return self.memory.read_byte(pa)
        elif size == 2:
            return self.memory.read_halfword(pa)
        else:
            return self.memory.read_word(pa)

    def write_memory_va(self, va: int, value: int, size: int = 4) -> None:
        """通过地址翻译写入内存"""
        pa = self.translate_address(va)
        if not self.memory:
            return
        if size == 1:
            self.memory.write_byte(pa, value)
        elif size == 2:
            self.memory.write_halfword(pa, value)
        else:
            self.memory.write_word(pa, value)

    def reset(self) -> None:
        """重置核心状态"""
        self.state.reset()
        self.halted = False
        self.running = False
        self.execution_log.clear()

    def get_state_dump(self) -> Dict[str, Any]:
        """获取当前状态转储"""
        return {
            "registers": {f"R{i}": hex(self.state.registers[i]) for i in range(16)},
            "flags": {"N": self.state.n, "Z": self.state.z, "C": self.state.c, "V": self.state.v},
            "pc": hex(self.state.pc),
            "domain_block": hex(self.domain_block_addr) if self.domain_block_addr else "None",
            "halted": self.halted,
        }

    def get_execution_log(self) -> List[Dict]:
        """获取执行历史"""
        return self.execution_log.copy()

    def clear_execution_log(self) -> None:
        """清空执行历史"""
        self.execution_log.clear()


def Asm(code: str, base_addr: int = 0, decoder: Optional['SimpleCore'] = None) -> int:
    """
    汇编代码快捷函数

    Args:
        code: 汇编代码
        base_addr: 基地址
        decoder: SimpleCore 实例（可选）

    Returns:
        结束地址
    """
    if decoder:
        return decoder.load_assembly(code, base_addr)
    else:
        assembler = Assembler()
        instructions = assembler.assemble(code, base_addr)
        return base_addr + len(instructions) * 4