"""
RPA ISA Module - ISA abstraction layer for heterogeneous domain support

Each ISA implementation defines:
- Register set and context save area layout
- Privilege level mapping
- Page table format
- Calling convention (parameter passing)

ISA Tag Values:
    0x0000: INHERIT (inherit from parent, resolved at descend time)
    0x0001: ARM/AArch64
    0x0002: RISC-V
    0x0003: x86-64
    0x0004: IBM Z
"""

from .base import ISABase, ISAContext, RegisterInfo, CallingConvention
from .arm import ARMISA
from .x86 import X86ISA

__all__ = [
    "ISABase", "ISAContext", "RegisterInfo", "CallingConvention",
    "ARMISA", "X86ISA",
    "ISA_TAG_INHERIT", "ISA_TAG_ARM", "ISA_TAG_RISCV", "ISA_TAG_X86", "ISA_TAG_IBMZ",
    "get_isa_by_tag",
]

# ISA Tag definitions
ISA_TAG_INHERIT = 0x0000  # Inherit from parent (resolved at descend)
ISA_TAG_ARM     = 0x0001  # ARM/AArch64
ISA_TAG_RISCV   = 0x0002  # RISC-V
ISA_TAG_X86     = 0x0003  # x86-64
ISA_TAG_IBMZ    = 0x0004  # IBM Z

# ISA registry
_ISA_REGISTRY = {
    ISA_TAG_ARM: ARMISA,
    ISA_TAG_X86: X86ISA,
    # ISA_TAG_RISCV: RISCVISA,  # TODO
    # ISA_TAG_IBMZ: IBMZISA,    # TODO
}


def get_isa_by_tag(tag: int):
    """Get ISA implementation by tag value."""
    if tag == ISA_TAG_INHERIT:
        raise ValueError("ISA_TAG_INHERIT (0) must be resolved to actual ISA before use")
    isa_class = _ISA_REGISTRY.get(tag)
    if isa_class is None:
        raise ValueError(f"Unknown ISA tag: 0x{tag:04x}")
    return isa_class()
