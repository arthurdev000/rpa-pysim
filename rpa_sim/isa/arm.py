"""
ARM/AArch64 ISA Implementation

Context save area layout (32-bit, matches SimpleISA):
    Offset 0x00: saved_sp  (Stack Pointer, r13)
    Offset 0x04: saved_lr  (Link Register, r14)
    Offset 0x08: saved_psr (Program Status Register: N, Z, C, V flags)

Calling Convention (AAPCS):
    - Arguments: r0-r3
    - Return: r0-r1
    - Caller-saved: r0-r3, r12, lr
    - Callee-saved: r4-r11
    - Stack alignment: 8 bytes (32-bit) / 16 bytes (64-bit)
"""

from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
import struct

from .base import (
    ISABase, ISAContext, RegisterInfo, CallingConvention, PrivilegeLevel
)
from ..isa_simple import (
    SAVED_SP_OFFSET, SAVED_LR_OFFSET, SAVED_PSR_OFFSET,
    IRQ_SAVE_R0, IRQ_SAVE_SIZE
)
from .. import ISA_TAG_ARM


class ARMISA(ISABase):
    """ARM/AArch64 ISA implementation (matches existing SimpleISA)"""

    @property
    def name(self) -> str:
        return "ARM"

    @property
    def isa_tag(self) -> int:
        return ISA_TAG_ARM

    @property
    def word_size(self) -> int:
        return 4  # 32-bit

    @property
    def registers(self) -> List[RegisterInfo]:
        """ARM register set (r0-r15)"""
        regs = []
        # r0-r3: Arguments / Return values
        for i in range(4):
            regs.append(RegisterInfo(
                name=f"r{i}",
                index=i,
                is_argument=True,
                arg_position=i,
                is_callee_saved=False
            ))
        # r4-r11: Callee-saved
        for i in range(4, 12):
            regs.append(RegisterInfo(
                name=f"r{i}",
                index=i,
                is_callee_saved=True
            ))
        # r12: IP (scratch)
        regs.append(RegisterInfo(name="r12", index=12, is_callee_saved=False))
        # r13: SP
        regs.append(RegisterInfo(name="sp", index=13, is_callee_saved=True))
        # r14: LR
        regs.append(RegisterInfo(name="lr", index=14, is_callee_saved=True))
        # r15: PC
        regs.append(RegisterInfo(name="pc", index=15, is_callee_saved=False))

        return regs

    @property
    def calling_convention(self) -> CallingConvention:
        """AAPCS calling convention"""
        return CallingConvention(
            arg_registers=["r0", "r1", "r2", "r3"],
            return_registers=["r0", "r1"],
            caller_saved=["r0", "r1", "r2", "r3", "r12", "lr"],
            callee_saved=["r4", "r5", "r6", "r7", "r8", "r9", "r10", "r11", "sp", "lr"],
            stack_alignment=8
        )

    def get_context_save_size(self) -> int:
        """Context save area size: SP + LR + PSR = 12 bytes"""
        return 12

    def get_context_save_layout(self) -> Dict[str, Tuple[int, int]]:
        """Context save area layout"""
        return {
            'sp': (0, 4),
            'lr': (4, 4),
            'psr': (8, 4),
        }

    def serialize_context(self, context: ISAContext) -> bytes:
        """Serialize context to bytes"""
        sp = context.registers.get('sp', context.sp)
        lr = context.registers.get('lr', context.pc + 4)  # Return address

        # Pack PSR flags
        psr = 0
        psr |= (1 << 3) if context.flags.get('n', False) else 0
        psr |= (1 << 2) if context.flags.get('z', False) else 0
        psr |= (1 << 1) if context.flags.get('c', False) else 0
        psr |= (1 << 0) if context.flags.get('v', False) else 0

        return struct.pack('<III', sp, lr, psr)

    def deserialize_context(self, data: bytes) -> ISAContext:
        """Deserialize context from bytes"""
        sp, lr, psr = struct.unpack('<III', data[:12])

        flags = {
            'n': bool(psr & 0x08),
            'z': bool(psr & 0x04),
            'c': bool(psr & 0x02),
            'v': bool(psr & 0x01),
        }

        return ISAContext(
            registers={'sp': sp, 'lr': lr},
            pc=0,  # PC comes from lr
            sp=sp,
            flags=flags,
            isa_tag=self.isa_tag
        )

    def map_privilege_level(self, isa_level: int) -> PrivilegeLevel:
        """
        Map ARM EL to RPA privilege level.

        EL0 (0) -> USER
        EL1 (1) -> SUPERVISOR
        EL2 (2) -> HYPERVISOR
        EL3 (3) -> ROOT
        """
        mapping = {
            0: PrivilegeLevel.USER,
            1: PrivilegeLevel.SUPERVISOR,
            2: PrivilegeLevel.HYPERVISOR,
            3: PrivilegeLevel.ROOT,
        }
        return mapping.get(isa_level, PrivilegeLevel.USER)

    def get_irq_save_size(self) -> int:
        """Get size of IRQ context save area"""
        return IRQ_SAVE_SIZE  # 68 bytes (17 * 4)

    def get_irq_save_layout(self) -> Dict[str, Tuple[int, int]]:
        """Get IRQ context save area layout"""
        layout = {}
        # r0-r12
        for i in range(13):
            layout[f'r{i}'] = (IRQ_SAVE_R0 + i * 4, 4)
        # sp, lr, pc, psr
        from ..isa_simple import IRQ_SAVE_SP, IRQ_SAVE_LR, IRQ_SAVE_PC, IRQ_SAVE_PSR
        layout['sp'] = (IRQ_SAVE_SP, 4)
        layout['lr'] = (IRQ_SAVE_LR, 4)
        layout['pc'] = (IRQ_SAVE_PC, 4)
        layout['psr'] = (IRQ_SAVE_PSR, 4)
        return layout
