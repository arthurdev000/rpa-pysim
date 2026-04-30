"""
Simple ARM Emulator - Minimal instruction set for RPA demonstration

This is a simplified ARM emulator that supports basic instructions needed
for demonstrating RPA's try-catch mechanism. It is NOT a full ARM emulator.

Supported instructions:
- LDR, STR (load/store)
- MOV, ADD, SUB, CMP
- B, BEQ, BNE, BL, BX (branches)
- DESCEND, ESCALATE, DESCEND_RETURN (RPA pseudo-instructions)
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any
from enum import Enum, auto
import struct


class OpCode(Enum):
    """Supported opcodes"""
    # Data processing
    MOV = auto()
    ADD = auto()
    SUB = auto()
    CMP = auto()
    AND = auto()
    ORR = auto()

    # Load/Store
    LDR = auto()
    STR = auto()

    # Branch
    B = auto()
    BEQ = auto()
    BNE = auto()
    BL = auto()
    BX = auto()

    # RPA pseudo-instructions
    DESCEND = auto()
    ESCALATE = auto()
    DESCEND_RETURN = auto()

    # Special
    NOP = auto()
    HALT = auto()


@dataclass
class Instruction:
    """A single instruction"""
    opcode: OpCode
    rd: int = 0  # Destination register
    rn: int = 0  # First operand register
    rm: int = 0  # Second operand register
    imm: int = 0  # Immediate value
    addr: int = 0  # Address for LDR/STR/Branch
    label: str = ""  # Label for branches


@dataclass
class CPUState:
    """CPU state"""
    # General purpose registers R0-R15
    # R13 = SP, R14 = LR, R15 = PC
    registers: List[int] = field(default_factory=lambda: [0] * 16)

    # Condition flags
    n: bool = False  # Negative
    z: bool = False  # Zero
    c: bool = False  # Carry
    v: bool = False  # Overflow

    # Current instruction
    pc: int = 0

    # RPA state
    current_level: int = 0
    in_sublayer: bool = False

    def get_reg(self, idx: int) -> int:
        return self.registers[idx]

    def set_reg(self, idx: int, value: int) -> None:
        if idx == 15:  # PC
            self.pc = value
        self.registers[idx] = value & 0xFFFFFFFF

    def update_flags(self, result: int) -> None:
        """Update condition flags based on result"""
        result_32 = result & 0xFFFFFFFF
        self.n = (result_32 & 0x80000000) != 0
        self.z = result_32 == 0
        # Carry and Overflow not implemented in this simple version


class ARMEmulator:
    """
    Simple ARM emulator for RPA demonstration.

    This is NOT a full ARM emulator. It supports only the instructions
    needed to demonstrate RPA's descend/escalate mechanism.
    """

    def __init__(self, rpa_core=None):
        self.state = CPUState()
        self.memory: Dict[int, bytes] = {}
        self.instructions: Dict[int, Instruction] = {}
        self.labels: Dict[str, int] = {}
        self.rpa_core = rpa_core  # Reference to RPA core

        # RPA handlers
        self.descend_handler: Optional[Callable] = None
        self.escalate_handler: Optional[Callable] = None

        # Execution control
        self.running = False
        self.halted = False

    def load_program(self, instructions: List[tuple], base_addr: int = 0x1000) -> None:
        """
        Load a program into memory.

        Args:
            instructions: List of (opcode_str, rd, rn, rm, imm, label) tuples
            base_addr: Base address for loading
        """
        addr = base_addr
        for inst_tuple in instructions:
            opcode_str = inst_tuple[0]

            # Parse opcode
            opcode = self._parse_opcode(opcode_str)

            # Create instruction
            inst = Instruction(
                opcode=opcode,
                rd=inst_tuple[1] if len(inst_tuple) > 1 else 0,
                rn=inst_tuple[2] if len(inst_tuple) > 2 else 0,
                rm=inst_tuple[3] if len(inst_tuple) > 3 else 0,
                imm=inst_tuple[4] if len(inst_tuple) > 4 else 0,
                label=inst_tuple[5] if len(inst_tuple) > 5 else "",
            )

            self.instructions[addr] = inst

            # Handle labels
            if inst.label and opcode in (OpCode.B, OpCode.BEQ, OpCode.BNE, OpCode.BL):
                self.labels[inst.label] = inst.imm  # Store target address

            addr += 4  # ARM instructions are 4 bytes

    def _parse_opcode(self, opcode_str: str) -> OpCode:
        """Parse opcode string to enum"""
        opcodes = {
            "MOV": OpCode.MOV,
            "ADD": OpCode.ADD,
            "SUB": OpCode.SUB,
            "CMP": OpCode.CMP,
            "AND": OpCode.AND,
            "ORR": OpCode.ORR,
            "LDR": OpCode.LDR,
            "STR": OpCode.STR,
            "B": OpCode.B,
            "BEQ": OpCode.BEQ,
            "BNE": OpCode.BNE,
            "BL": OpCode.BL,
            "BX": OpCode.BX,
            "DESCEND": OpCode.DESCEND,
            "ESCALATE": OpCode.ESCALATE,
            "DESCEND_RETURN": OpCode.DESCEND_RETURN,
            "NOP": OpCode.NOP,
            "HALT": OpCode.HALT,
        }
        return opcodes.get(opcode_str.upper(), OpCode.NOP)

    def write_memory(self, addr: int, data: bytes) -> None:
        """Write data to memory"""
        self.memory[addr] = data

    def read_memory(self, addr: int, size: int) -> bytes:
        """Read data from memory"""
        return self.memory.get(addr, b'\x00' * size)

    def write_word(self, addr: int, value: int) -> None:
        """Write a 32-bit word to memory"""
        self.memory[addr] = struct.pack('<I', value & 0xFFFFFFFF)

    def read_word(self, addr: int) -> int:
        """Read a 32-bit word from memory"""
        data = self.memory.get(addr, b'\x00\x00\x00\x00')
        return struct.unpack('<I', data)[0]

    def step(self) -> bool:
        """
        Execute one instruction.

        Returns:
            True if execution should continue, False if halted
        """
        if self.halted:
            return False

        pc = self.state.pc
        inst = self.instructions.get(pc)

        if inst is None:
            # No instruction at PC, halt
            self.halted = True
            return False

        # Execute instruction
        self._execute(inst)

        # Update PC (if not modified by instruction)
        if self.state.pc == pc:
            self.state.pc = pc + 4

        return not self.halted

    def run(self, max_steps: int = 10000) -> None:
        """Run until halt or max_steps"""
        self.running = True
        steps = 0
        while self.running and steps < max_steps:
            if not self.step():
                break
            steps += 1
        self.running = False

    def _execute(self, inst: Instruction) -> None:
        """Execute a single instruction"""
        opcode = inst.opcode

        if opcode == OpCode.MOV:
            self.state.set_reg(inst.rd, inst.imm)

        elif opcode == OpCode.ADD:
            result = self.state.get_reg(inst.rn) + self.state.get_reg(inst.rm)
            self.state.set_reg(inst.rd, result)
            self.state.update_flags(result)

        elif opcode == OpCode.SUB:
            result = self.state.get_reg(inst.rn) - self.state.get_reg(inst.rm)
            self.state.set_reg(inst.rd, result)
            self.state.update_flags(result)

        elif opcode == OpCode.CMP:
            result = self.state.get_reg(inst.rn) - inst.imm
            self.state.update_flags(result)

        elif opcode == OpCode.AND:
            result = self.state.get_reg(inst.rn) & self.state.get_reg(inst.rm)
            self.state.set_reg(inst.rd, result)

        elif opcode == OpCode.ORR:
            result = self.state.get_reg(inst.rn) | self.state.get_reg(inst.rm)
            self.state.set_reg(inst.rd, result)

        elif opcode == OpCode.LDR:
            addr = inst.addr if inst.addr != 0 else self.state.get_reg(inst.rn)
            value = self.read_word(addr)
            self.state.set_reg(inst.rd, value)

        elif opcode == OpCode.STR:
            addr = inst.addr if inst.addr != 0 else self.state.get_reg(inst.rn)
            value = self.state.get_reg(inst.rd)
            self.write_word(addr, value)

        elif opcode == OpCode.B:
            self.state.pc = inst.imm

        elif opcode == OpCode.BEQ:
            if self.state.z:
                self.state.pc = inst.imm

        elif opcode == OpCode.BNE:
            if not self.state.z:
                self.state.pc = inst.imm

        elif opcode == OpCode.BL:
            # Branch with link
            self.state.set_reg(14, self.state.pc + 4)  # LR = PC + 4
            self.state.pc = inst.imm

        elif opcode == OpCode.BX:
            # Branch and exchange
            target = self.state.get_reg(inst.rm)
            self.state.pc = target

        elif opcode == OpCode.DESCEND:
            # RPA: Enter sublayer
            if self.descend_handler:
                params_addr = self.state.get_reg(inst.rd)
                result = self.descend_handler(params_addr)
                self.state.set_reg(0, result)  # R0 = result

        elif opcode == OpCode.ESCALATE:
            # RPA: Request service from parent
            if self.escalate_handler:
                params_addr = self.state.get_reg(inst.rd)
                result = self.escalate_handler(params_addr)
                self.state.set_reg(0, result)  # R0 = result

        elif opcode == OpCode.DESCEND_RETURN:
            # RPA: Return from sublayer
            result = self.state.get_reg(0)  # R0 = return value
            # In real implementation, this would return to parent
            self.halted = True

        elif opcode == OpCode.HALT:
            self.halted = True

        elif opcode == OpCode.NOP:
            pass

    def reset(self) -> None:
        """Reset CPU state"""
        self.state = CPUState()
        self.halted = False
        self.running = False

    def get_state_dump(self) -> Dict[str, Any]:
        """Get current CPU state for debugging"""
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
            "current_level": self.state.current_level,
        }