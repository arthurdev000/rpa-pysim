"""
x86-64 ISA Implementation

Context save area layout (64-bit):
    Offset 0x00: saved_rsp  (Stack Pointer)
    Offset 0x08: saved_rip  (Instruction Pointer)
    Offset 0x10: saved_rflags (RFLAGS register)

Calling Convention (System V AMD64 ABI):
    - Arguments: RDI, RSI, RDX, RCX, R8, R9
    - Return: RAX, RDX
    - Caller-saved: RAX, RCX, RDX, RSI, RDI, R8-R11
    - Callee-saved: RBX, RBP, R12-R15
    - Stack alignment: 16 bytes

Note: This is a CISC architecture with variable-length instructions.
For RPA simulation, we simplify to a fixed-length instruction model.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
import struct

from .base import (
    ISABase, ISAContext, RegisterInfo, CallingConvention, PrivilegeLevel
)
from .. import ISA_TAG_X86


# x86-64 specific offsets (for DCB ISA Context Field)
X86_SAVED_RSP_OFFSET = 0x00     # 8 bytes
X86_SAVED_RIP_OFFSET = 0x08     # 8 bytes
X86_SAVED_RFLAGS_OFFSET = 0x10  # 8 bytes
X86_CONTEXT_SIZE = 0x18         # 24 bytes total

# IRQ context save area (full register state)
X86_IRQ_SAVE_RAX = 0x20
X86_IRQ_SAVE_RBX = 0x28
X86_IRQ_SAVE_RCX = 0x30
X86_IRQ_SAVE_RDX = 0x38
X86_IRQ_SAVE_RSI = 0x40
X86_IRQ_SAVE_RDI = 0x48
X86_IRQ_SAVE_RBP = 0x50
X86_IRQ_SAVE_R8 = 0x58
X86_IRQ_SAVE_R9 = 0x60
X86_IRQ_SAVE_R10 = 0x68
X86_IRQ_SAVE_R11 = 0x70
X86_IRQ_SAVE_R12 = 0x78
X86_IRQ_SAVE_R13 = 0x80
X86_IRQ_SAVE_R14 = 0x88
X86_IRQ_SAVE_R15 = 0x90
X86_IRQ_SAVE_SIZE = 0x80  # 128 bytes


class X86ISA(ISABase):
    """x86-64 ISA implementation"""

    @property
    def name(self) -> str:
        return "x86-64"

    @property
    def isa_tag(self) -> int:
        return ISA_TAG_X86

    @property
    def word_size(self) -> int:
        return 8  # 64-bit

    @property
    def registers(self) -> List[RegisterInfo]:
        """x86-64 register set (RAX-R15)"""
        regs = []

        # RAX: Return value
        regs.append(RegisterInfo(
            name="rax", index=0,
            is_argument=False,
            is_callee_saved=False
        ))

        # RBX: Callee-saved
        regs.append(RegisterInfo(
            name="rbx", index=1,
            is_callee_saved=True
        ))

        # RCX: Argument 4 / Caller-saved
        regs.append(RegisterInfo(
            name="rcx", index=2,
            is_argument=True, arg_position=3,
            is_callee_saved=False
        ))

        # RDX: Argument 3 / Return value 2 / Caller-saved
        regs.append(RegisterInfo(
            name="rdx", index=3,
            is_argument=True, arg_position=2,
            is_callee_saved=False
        ))

        # RSI: Argument 2 / Caller-saved
        regs.append(RegisterInfo(
            name="rsi", index=4,
            is_argument=True, arg_position=1,
            is_callee_saved=False
        ))

        # RDI: Argument 1 / Caller-saved
        regs.append(RegisterInfo(
            name="rdi", index=5,
            is_argument=True, arg_position=0,
            is_callee_saved=False
        ))

        # RBP: Callee-saved (frame pointer)
        regs.append(RegisterInfo(
            name="rbp", index=6,
            is_callee_saved=True
        ))

        # RSP: Stack pointer
        regs.append(RegisterInfo(
            name="rsp", index=7,
            is_callee_saved=True
        ))

        # R8-R9: Arguments 5-6
        regs.append(RegisterInfo(
            name="r8", index=8,
            is_argument=True, arg_position=4,
            is_callee_saved=False
        ))
        regs.append(RegisterInfo(
            name="r9", index=9,
            is_argument=True, arg_position=5,
            is_callee_saved=False
        ))

        # R10-R11: Caller-saved
        for i in range(10, 12):
            regs.append(RegisterInfo(
                name=f"r{i}", index=i,
                is_callee_saved=False
            ))

        # R12-R15: Callee-saved
        for i in range(12, 16):
            regs.append(RegisterInfo(
                name=f"r{i}", index=i,
                is_callee_saved=True
            ))

        # RIP: Instruction pointer (not directly accessible as GPR)
        regs.append(RegisterInfo(
            name="rip", index=16,
            is_callee_saved=False
        ))

        return regs

    @property
    def calling_convention(self) -> CallingConvention:
        """System V AMD64 ABI calling convention"""
        return CallingConvention(
            arg_registers=["rdi", "rsi", "rdx", "rcx", "r8", "r9"],
            return_registers=["rax", "rdx"],
            caller_saved=["rax", "rcx", "rdx", "rsi", "rdi", "r8", "r9", "r10", "r11"],
            callee_saved=["rbx", "rbp", "r12", "r13", "r14", "r15"],
            stack_alignment=16
        )

    def get_context_save_size(self) -> int:
        """Context save area size: RSP + RIP + RFLAGS = 24 bytes"""
        return X86_CONTEXT_SIZE

    def get_context_save_layout(self) -> Dict[str, Tuple[int, int]]:
        """Context save area layout"""
        return {
            'rsp': (X86_SAVED_RSP_OFFSET, 8),
            'rip': (X86_SAVED_RIP_OFFSET, 8),
            'rflags': (X86_SAVED_RFLAGS_OFFSET, 8),
        }

    def serialize_context(self, context: ISAContext) -> bytes:
        """Serialize context to bytes"""
        rsp = context.registers.get('rsp', context.sp)
        rip = context.registers.get('rip', context.pc + 8)  # Return address (8 bytes for 64-bit)

        # Pack RFLAGS
        rflags = 0
        # Basic flags
        rflags |= (1 << 0) if context.flags.get('c', False) else 0   # CF
        rflags |= (1 << 6) if context.flags.get('z', False) else 0   # ZF
        rflags |= (1 << 7) if context.flags.get('s', False) else 0   # SF
        rflags |= (1 << 11) if context.flags.get('o', False) else 0  # OF

        return struct.pack('<QQQ', rsp, rip, rflags)

    def deserialize_context(self, data: bytes) -> ISAContext:
        """Deserialize context from bytes"""
        rsp, rip, rflags = struct.unpack('<QQQ', data[:24])

        flags = {
            'c': bool(rflags & (1 << 0)),   # CF
            'z': bool(rflags & (1 << 6)),   # ZF
            's': bool(rflags & (1 << 7)),   # SF
            'o': bool(rflags & (1 << 11)),  # OF
        }

        return ISAContext(
            registers={'rsp': rsp, 'rip': rip},
            pc=rip,
            sp=rsp,
            flags=flags,
            isa_tag=self.isa_tag
        )

    def map_privilege_level(self, isa_level: int) -> PrivilegeLevel:
        """
        Map x86 Ring to RPA privilege level.

        Ring 3 (3) -> USER
        Ring 2 (2) -> SUPERVISOR (rarely used)
        Ring 1 (1) -> HYPERVISOR (rarely used)
        Ring 0 (0) -> ROOT

        Note: x86 rings are inverted (lower = more privileged)
        """
        mapping = {
            3: PrivilegeLevel.USER,
            2: PrivilegeLevel.SUPERVISOR,
            1: PrivilegeLevel.HYPERVISOR,
            0: PrivilegeLevel.ROOT,
        }
        return mapping.get(isa_level, PrivilegeLevel.USER)

    def get_irq_save_size(self) -> int:
        """Get size of IRQ context save area"""
        return X86_IRQ_SAVE_SIZE

    def get_irq_save_layout(self) -> Dict[str, Tuple[int, int]]:
        """Get IRQ context save area layout"""
        return {
            'rax': (X86_IRQ_SAVE_RAX, 8),
            'rbx': (X86_IRQ_SAVE_RBX, 8),
            'rcx': (X86_IRQ_SAVE_RCX, 8),
            'rdx': (X86_IRQ_SAVE_RDX, 8),
            'rsi': (X86_IRQ_SAVE_RSI, 8),
            'rdi': (X86_IRQ_SAVE_RDI, 8),
            'rbp': (X86_IRQ_SAVE_RBP, 8),
            'r8': (X86_IRQ_SAVE_R8, 8),
            'r9': (X86_IRQ_SAVE_R9, 8),
            'r10': (X86_IRQ_SAVE_R10, 8),
            'r11': (X86_IRQ_SAVE_R11, 8),
            'r12': (X86_IRQ_SAVE_R12, 8),
            'r13': (X86_IRQ_SAVE_R13, 8),
            'r14': (X86_IRQ_SAVE_R14, 8),
            'r15': (X86_IRQ_SAVE_R15, 8),
        }
