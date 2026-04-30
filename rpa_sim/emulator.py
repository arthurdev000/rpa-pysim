"""
Instruction Emulator - Simplified instruction set for RPA demonstration

简化的指令集模拟器，用于演示 RPA 的 descend/escalate 机制。

注意：这些指令是简化的示例指令，与真实架构指令相似但不完全相同。
它们不是任何特定架构的标准指令集。

支持的指令：
- 数据处理：MOV, ADD, SUB, CMP, AND, ORR
- 加载/存储：LDR, STR
- 分支：B, BEQ, BNE, BL, BX
- RPA伪指令：DESCEND, ESCALATE, RETURN
- 特殊：NOP, HALT
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

    # RPA 伪指令
    DESCEND = auto()
    ESCALATE = auto()
    RETURN = auto()

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

    # 原始汇编文本（用于调试）
    asm_text: str = ""


@dataclass
class CPUState:
    """CPU状态"""
    # 通用寄存器 R0-R15
    # R13 = SP (栈指针), R14 = LR (链接寄存器), R15 = PC (程序计数器)
    registers: List[int] = field(default_factory=lambda: [0] * 16)

    # 条件标志
    n: bool = False   # 负数
    z: bool = False   # 零
    c: bool = False   # 进位
    v: bool = False   # 溢出

    # 当前特权级别
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
        # 进位和溢出在此简化版本中未实现

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
        DESCEND Rd            ; RPA: 进入子层
        ESCALATE Rd           ; RPA: 请求父层服务
        RETURN                ; RPA: 返回父层
        NOP                   ; 空操作
        HALT                  ; 停机

    标签定义：
        label: MOV R0, #1      ; 标签后跟冒号
    """

    # 寄存器名称映射
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
        """
        解析地址模式。

        Returns:
            (mode, base_reg, offset)
            mode: 'reg', 'reg_offset', 'absolute'
        """
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
        """
        汇编代码。

        Args:
            code: 汇编代码字符串
            base_addr: 基地址

        Returns:
            [(地址, 指令), ...] 列表
        """
        self.labels = {}
        self.instructions = []

        # 预处理：移除注释，提取标签
        lines = []
        addr = base_addr

        for line in code.split('\n'):
            # 移除注释
            if ';' in line:
                line = line[:line.index(';')]
            line = line.strip()

            if not line:
                continue

            # 检查标签
            if ':' in line:
                parts = line.split(':', 1)
                label = parts[0].strip()
                self.labels[label] = addr
                line = parts[1].strip() if len(parts) > 1 else ''

                if not line:
                    continue

            lines.append((addr, line))
            addr += 4  # 每条指令4字节

        # 第二遍：解析指令
        for addr, line in lines:
            inst = self._parse_instruction(line, addr)
            if inst:
                inst.asm_text = line
                self.instructions.append((addr, inst))

        return self.instructions

    def _parse_instruction(self, line: str, addr: int) -> Optional[Instruction]:
        """解析单条指令"""
        # 分割操作码和操作数
        parts = line.split(None, 1)
        if not parts:
            return None

        opcode_str = parts[0].upper()
        operands = parts[1] if len(parts) > 1 else ''

        # 解析操作码
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
            'NOP': OpCode.NOP,
            'HALT': OpCode.HALT,
        }

        opcode = opcode_map.get(opcode_str)
        if opcode is None:
            raise ValueError(f"未知操作码: {opcode_str}")

        # 根据操作码解析操作数
        return self._parse_operands(opcode, operands, addr)

    def _parse_operands(self, opcode: OpCode, operands: str,
                        addr: int) -> Instruction:
        """解析操作数"""
        if opcode == OpCode.MOV:
            # MOV Rd, Rn 或 MOV Rd, #imm
            parts = [p.strip() for p in operands.split(',')]
            rd = self.parse_register(parts[0])
            if parts[1].startswith('#'):
                imm = self.parse_immediate(parts[1])
                return Instruction(opcode=opcode, rd=rd, imm=imm, is_immediate=True)
            else:
                rn = self.parse_register(parts[1])
                return Instruction(opcode=opcode, rd=rd, rn=rn)

        elif opcode in (OpCode.ADD, OpCode.SUB, OpCode.AND, OpCode.ORR):
            # OP Rd, Rn, Rm 或 OP Rd, Rn, #imm
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
            # CMP Rn, Rm 或 CMP Rn, #imm
            parts = [p.strip() for p in operands.split(',')]
            rn = self.parse_register(parts[0])
            if parts[1].startswith('#'):
                imm = self.parse_immediate(parts[1])
                return Instruction(opcode=opcode, rn=rn, imm=imm, is_immediate=True)
            else:
                rm = self.parse_register(parts[1])
                return Instruction(opcode=opcode, rn=rn, rm=rm)

        elif opcode in (OpCode.LDR, OpCode.STR):
            # LDR Rd, [Rn] 或 LDR Rd, [Rn, #offset] 或 LDR Rd, =addr
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
            # B label
            label = operands.strip()
            if label in self.labels:
                target = self.labels[label]
            else:
                # 可能是数值地址
                target = self.parse_immediate(label)
            return Instruction(opcode=opcode, addr=target, label=label)

        elif opcode == OpCode.BX:
            # BX Rm
            rm = self.parse_register(operands.strip())
            return Instruction(opcode=opcode, rm=rm)

        elif opcode in (OpCode.DESCEND, OpCode.ESCALATE):
            # DESCEND Rd 或 ESCALATE Rd
            rd = self.parse_register(operands.strip())
            return Instruction(opcode=opcode, rd=rd)

        elif opcode in (OpCode.RETURN, OpCode.NOP, OpCode.HALT):
            return Instruction(opcode=opcode)

        return Instruction(opcode=opcode)


class Emulator:
    """
    简化的指令集模拟器。

    注意：此模拟器使用简化的示例指令，与真实架构指令相似但不完全相同。
    它们不是任何特定架构的标准指令集。
    """

    def __init__(self, memory=None, rpa_core=None):
        """
        初始化模拟器。

        Args:
            memory: PhysicalMemory 实例（可选）
            rpa_core: RPACore 实例（可选，用于 RPA 指令）
        """
        self.state = CPUState()
        self.memory = memory
        self.rpa_core = rpa_core

        # 指令存储：地址 -> 指令
        self.instructions: Dict[int, Instruction] = {}

        # 标签：名称 -> 地址
        self.labels: Dict[str, int] = {}

        # 汇编器
        self.assembler = Assembler()

        # RPA 处理器
        self.descend_handler: Optional[Callable] = None
        self.escalate_handler: Optional[Callable] = None
        self.return_handler: Optional[Callable] = None

        # 执行控制
        self.running = False
        self.halted = False

        # 执行历史（用于测试验证）
        self.execution_log: List[Dict] = []

    def load_assembly(self, code: str, base_addr: int = 0) -> int:
        """
        加载汇编代码到内存。

        Args:
            code: 汇编代码字符串
            base_addr: 基地址

        Returns:
            结束地址（最后一条指令的地址 + 4）
        """
        instructions = self.assembler.assemble(code, base_addr)

        for addr, inst in instructions:
            self.instructions[addr] = inst

        # 复制标签
        self.labels.update(self.assembler.labels)

        # 如果有内存，将指令编码写入内存
        if self.memory:
            for addr, inst in instructions:
                # 简化编码：将操作码编码为32位值
                encoded = self._encode_instruction(inst)
                self.memory.write_word(addr, encoded)

        return base_addr + len(instructions) * 4

    def _encode_instruction(self, inst: Instruction) -> int:
        """
        简化的指令编码。

        编码格式（简化版）：
        [31:24] 操作码
        [23:20] 保留
        [19:16] Rd
        [15:12] Rn
        [11:8]  Rm
        [7:0]   立即数（低8位）
        """
        opcode_val = inst.opcode.value
        encoded = (opcode_val << 24) | (inst.rd << 16) | (inst.rn << 12) | (inst.rm << 8) | (inst.imm & 0xFF)
        return encoded

    def decode_instruction(self, word: int) -> Optional[Instruction]:
        """
        从内存字解码指令。
        """
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

    def write_memory(self, addr: int, data: bytes) -> None:
        """写入数据到内存"""
        if self.memory:
            self.memory.write_bytes(addr, data)

    def read_memory(self, addr: int, size: int) -> bytes:
        """从内存读取数据"""
        if self.memory:
            return self.memory.read_bytes(addr, size)
        return b'\x00' * size

    def step(self) -> bool:
        """
        执行单条指令。

        Returns:
            是否应该继续执行
        """
        if self.halted:
            return False

        pc = self.state.pc
        inst = self.instructions.get(pc)

        if inst is None:
            # 没有指令，停机
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

        # 执行指令
        self._execute(inst)

        # 记录执行后状态
        log_entry["registers_after"] = self.state.registers.copy()
        log_entry["flags"] = {"N": self.state.n, "Z": self.state.z}
        self.execution_log.append(log_entry)

        # 更新PC（如果指令没有修改）
        if self.state.pc == pc and not self.halted:
            self.state.pc = pc + 4

        return not self.halted

    def run(self, max_steps: int = 10000) -> int:
        """
        运行直到停机或达到最大步数。

        Args:
            max_steps: 最大执行步数

        Returns:
            实际执行的步数
        """
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

        elif opcode == OpCode.LDR:
            if inst.addr != 0:
                # 绝对地址
                addr = inst.addr
            elif inst.imm != 0:
                # [Rn, #offset]
                addr = self.state.get_reg(inst.rn) + inst.imm
            else:
                # [Rn]
                addr = self.state.get_reg(inst.rn)

            if self.memory:
                value = self.memory.read_word(addr)
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

            value = self.state.get_reg(inst.rd)
            if self.memory:
                self.memory.write_word(addr, value)

        elif opcode == OpCode.B:
            self.state.pc = inst.addr

        elif opcode == OpCode.BEQ:
            if self.state.z:
                self.state.pc = inst.addr

        elif opcode == OpCode.BNE:
            if not self.state.z:
                self.state.pc = inst.addr

        elif opcode == OpCode.BL:
            # 带链接分支
            self.state.lr = self.state.pc + 4
            self.state.pc = inst.addr

        elif opcode == OpCode.BX:
            # 寄存器分支
            target = self.state.get_reg(inst.rm)
            self.state.pc = target

        elif opcode == OpCode.DESCEND:
            # RPA: 进入子层
            if self.descend_handler:
                params = self.state.get_reg(inst.rd)
                result = self.descend_handler(params)
                self.state.set_reg(0, result)

        elif opcode == OpCode.ESCALATE:
            # RPA: 请求父层服务
            if self.escalate_handler:
                params = self.state.get_reg(inst.rd)
                result = self.escalate_handler(params)
                self.state.set_reg(0, result)

        elif opcode == OpCode.RETURN:
            # RPA: 返回父层
            if self.return_handler:
                result = self.state.get_reg(0)
                self.return_handler(result)
            self.halted = True

        elif opcode == OpCode.HALT:
            self.halted = True

        elif opcode == OpCode.NOP:
            pass

    def reset(self) -> None:
        """重置模拟器状态"""
        self.state.reset()
        self.halted = False
        self.running = False
        self.execution_log.clear()

    def get_state_dump(self) -> Dict[str, Any]:
        """获取当前状态转储"""
        return {
            "registers": {
                f"R{i}": hex(self.state.registers[i])
                for i in range(16)
            },
            "flags": {
                "N": self.state.n,
                "Z": self.state.z,
                "C": self.state.c,
                "V": self.state.v,
            },
            "pc": hex(self.state.pc),
            "privilege_level": self.state.privilege_level,
            "halted": self.halted,
        }

    def get_execution_log(self) -> List[Dict]:
        """获取执行历史"""
        return self.execution_log.copy()

    def clear_execution_log(self) -> None:
        """清空执行历史"""
        self.execution_log.clear()


# 便捷函数
def Asm(code: str, base_addr: int = 0, emulator: Optional[Emulator] = None) -> int:
    """
    汇编代码快捷函数。

    Args:
        code: 汇编代码
        base_addr: 基地址
        emulator: 模拟器实例（可选）

    Returns:
        结束地址
    """
    if emulator:
        return emulator.load_assembly(code, base_addr)
    else:
        assembler = Assembler()
        instructions = assembler.assemble(code, base_addr)
        return base_addr + len(instructions) * 4