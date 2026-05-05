"""
SimpleISA - 简化指令集核心

这是 RPA 架构的指令执行核心。每个 Domain 可以有不同的 ISA 实现，
SimpleISA 是一个简化版的类 ARM 指令集，用于演示 RPA 的核心机制。

支持的指令:
============

数据处理：MOV, ADD, SUB, CMP, AND, ORR
加载存储：LDR, STR
分支：B, BEQ, BNE, BL, BX
RPA 指令：DESCEND, ESCALATE, RETURN, SYSOP
特殊：NOP, HALT

地址翻译:
============

    LDR/STR 通过 MemoryManager 进行地址翻译:

    ┌─────────────┐      ┌─────────────┐      ┌─────────────┐
    │   Core      │ VA   │ MemoryManager│ PA   │   Memory    │
    │             │─────▶│ translate    │─────▶│             │
    │  LDR/STR    │      │ chain        │      │  read/write │
    └─────────────┘      └─────────────┘      └─────────────┘

    memtable_chain = [domain_n.memtable, ..., domain_0.memtable]
    翻译失败 → TranslationError(memtable_owner)
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any, Tuple
from enum import Enum, auto
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
    DESCEND = auto()
    ESCALATE = auto()
    RETURN = auto()

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

        elif opcode in (OpCode.DESCEND, OpCode.ESCALATE):
            rd = self.parse_register(operands.strip())
            return Instruction(opcode=opcode, rd=rd)

        elif opcode == OpCode.SYSOP:
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


class SimpleISA:
    """
    简化指令集核心。

    LDR/STR 通过 MemoryManager 进行地址翻译:
    - memtable_chain 保存当前域的页表链
    - 翻译失败触发 TranslationError (包含 fault_owner)

    DESCEND/ESCALATE/RETURN 指令:
    - DESCEND: 读取 DomainBlock，跳转到 execution_address
    - ESCALATE: 保存上下文，触发 escalate_handler
    - RETURN: 恢复上下文，继续执行
    """

    def __init__(self, rpa=None, memory=None, memory_manager=None):
        """
        初始化核心。

        Args:
            rpa: RPALogic 实例（管理域状态）
            memory: Memory 实例（物理内存）
            memory_manager: MemoryManager 实例（带翻译的读写）
        """
        self.state = CPUState()
        self.rpa = rpa
        self.memory = memory
        self.memory_manager = memory_manager

        # 当前 Domain 的 memtable 翻译链
        # [domain_n.memtable, ..., domain_0.memtable]
        self.memtable_chain: List[int] = []

        # 当前 Domain 的控制块地址
        self.domain_block_addr: int = 0

        # 指令存储
        self.instructions: Dict[int, Instruction] = {}
        self.labels: Dict[str, int] = {}
        self.assembler = Assembler()

        # 回调处理器（可选，用于高层模拟）
        self.descend_handler: Optional[Callable] = None
        self.escalate_handler: Optional[Callable] = None
        self.return_handler: Optional[Callable] = None
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
            if self.memory_manager and len(self.memtable_chain) > 0:
                value, fault_owner = self.memory_manager.read_with_translation(
                    va, self.memtable_chain, size=4
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
            if self.memory_manager and len(self.memtable_chain) > 0:
                fault_owner = self.memory_manager.write_with_translation(
                    va, value, self.memtable_chain, size=4
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

        if self.sysop_handler:
            result = self.sysop_handler(op, subop, arg1, arg2, inst.rd, inst.rn)
            if result is not None:
                self.state.set_reg(inst.rd, result)

    def _execute_descend(self, inst: Instruction) -> None:
        """
        执行 DESCEND 指令

        RTL 操作：
        1. 读取 DomainBlock 地址
        2. 调用 ISA.prepare_descend() 保存上下文
        3. 更新当前域状态
        4. 跳转到 execution_address
        """
        block_addr = self.state.get_reg(inst.rd)

        # RTL 调用 ISA 接口
        self.prepare_descend(block_addr)

        if self.rpa:
            # 模式1: 通过 RPALogic 切换域
            result = self.rpa.descend(block_addr)
            execution_addr = result.get("execution_address", 0)
            memtable = result.get("memtable", 0)
            if execution_addr:
                self.state.pc = execution_addr
            else:
                self.halted = True
            # 更新 memtable_chain
            if memtable != 0:
                self.memtable_chain = [memtable] + self.memtable_chain
            # 更新 domain_block_addr
            self.domain_block_addr = block_addr
        else:
            # 模式2: 使用回调（向后兼容）
            if self.memory:
                execution_addr = self.memory.read_word(block_addr + 0x00)
                memtable_addr = self.memory.read_word(block_addr + 0x10)
                # 更新 memtable_chain
                if memtable_addr != 0:
                    self.memtable_chain = [memtable_addr] + self.memtable_chain
                # 更新 domain_block_addr
                self.domain_block_addr = block_addr
                # 跳转到执行地址
                if execution_addr != 0:
                    self.state.pc = execution_addr
                else:
                    self.halted = True

            # 回调
            if self.descend_handler:
                result = self.descend_handler(block_addr)
                if result is not None:
                    self.state.set_reg(0, result)

    def _execute_escalate(self, inst: Instruction) -> None:
        """
        执行 ESCALATE 指令

        RTL 操作：
        1. 读取 service_type
        2. 调用 ISA.complete_escalate() 保存上下文
        3. 切换到父域，跳转到 exception_vector
        """
        service_type = self.state.get_reg(inst.rd)
        block_addr = self.domain_block_addr

        # RTL 调用 ISA 接口
        self.complete_escalate(block_addr, service_type)

        if self.rpa:
            # 模式1: 通过 RPALogic 切换域
            result = self.rpa.escalate(service_type)
            vector = result.get("vector", 0)
            if vector:
                self.state.pc = vector
            else:
                self.halted = True
            # 更新 memtable_chain（移除当前域的页表）
            if self.memtable_chain:
                self.memtable_chain = self.memtable_chain[1:]
        else:
            # 模式2: 使用回调（向后兼容）
            if self.memory and block_addr != 0:
                exception_vec = self.memory.read_word(block_addr + 0x04)
                if exception_vec != 0:
                    self.state.pc = exception_vec
                    if self.escalate_handler:
                        self.escalate_handler(service_type)
                    return

            # 没有异常向量，halt
            self.halted = True

            # 回调
            if self.escalate_handler:
                result = self.escalate_handler(service_type)
                if result is not None:
                    self.state.set_reg(0, result)

    def _execute_return(self, inst: Instruction) -> None:
        """
        执行 RETURN 指令

        RTL 操作：
        1. 从控制块恢复 PC

        这是软件可用的原语，具体语义由软件定义
        """
        if self.memory and self.domain_block_addr != 0:
            saved_pc = self.memory.read_word(self.domain_block_addr + 0x3C)
            if saved_pc != 0:
                self.state.pc = saved_pc
                self.halted = False

        # 回调
        if self.return_handler:
            self.return_handler(self.state.get_reg(0))

    def _save_context(self, block_addr: int, return_pc: int = None) -> None:
        """保存上下文到控制块"""
        if not self.memory:
            return

        # 保存返回地址
        if return_pc is None:
            return_pc = self.state.pc + 4
        self.memory.write_word(block_addr + 0x3C, return_pc)
        self.memory.write_word(block_addr + 0x40, self.state.lr)
        self.memory.write_word(block_addr + 0x44, self.state.sp)

        # 保存 R0-R12 (0x48-0x78)
        for i in range(13):
            self.memory.write_word(block_addr + 0x48 + i * 4, self.state.get_reg(i))

        # 保存标志位到 0x7C (N/Z/C/V)
        flags = 0
        if self.state.n:
            flags |= 1 << 31
        if self.state.z:
            flags |= 1 << 30
        if self.state.c:
            flags |= 1 << 29
        if self.state.v:
            flags |= 1 << 28
        self.memory.write_word(block_addr + 0x7C, flags)

    def _restore_context(self, block_addr: int) -> None:
        """从控制块恢复上下文"""
        if not self.memory:
            return

        self.state.pc = self.memory.read_word(block_addr + 0x3C)
        self.state.lr = self.memory.read_word(block_addr + 0x40)
        self.state.sp = self.memory.read_word(block_addr + 0x44)

        # 恢复 R0-R12 (0x48-0x78)
        for i in range(13):
            self.state.set_reg(i, self.memory.read_word(block_addr + 0x48 + i * 4))

        # 恢复标志位从 0x7C (N/Z/C/V)
        flags = self.memory.read_word(block_addr + 0x7C)
        self.state.n = bool(flags & (1 << 31))
        self.state.z = bool(flags & (1 << 30))
        self.state.c = bool(flags & (1 << 29))
        self.state.v = bool(flags & (1 << 28))

    def prepare_descend(self, block_addr: int) -> None:
        """
        RTL 在 DESCEND 前自动调用

        ISA 可在此：
        - 保存当前上下文到 DomainBlock 扩展区
        - 修改 DomainBlock 参数（如切换线程）

        Args:
            block_addr: DomainBlock 在内存中的地址
        """
        # 默认实现：保存返回地址
        if self.memory:
            self.memory.write_word(block_addr + 0x3C, self.state.pc + 4)

    def complete_escalate(self, block_addr: int, service_type: int) -> None:
        """
        RTL 在 ESCALATE 后自动调用

        ISA 可在此：
        - 保存上下文到 DomainBlock 扩展区
        - 决定返回地址（PC+4 或其他）

        Args:
            block_addr: 当前域 DomainBlock 在内存中的地址
            service_type: 服务类型（从 rd 寄存器读取）
        """
        # 默认实现：保存上下文
        self._save_context(block_addr, return_pc=self.state.pc + 4)

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
            "memtable_chain": [hex(m) for m in self.memtable_chain],
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