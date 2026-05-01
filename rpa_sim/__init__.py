"""
RPA Simulator - Recursive Privilege Architecture Concept Verification

This package provides a Python simulator for RPA (Recursive Privilege Architecture),
demonstrating the descend() and escalate() primitives.

Main components:
- RPACore: RPA core, manages Domain hierarchy
- Domain, DomainBlock: Privilege domain management
- Memory: Memory simulation (physical memory + page table management)
- MemoryManager: Page table stacking management
- SimpleCore: Simplified instruction set core (ARM-like)
- Machine: Complete machine integrating RPACore, Memory, SimpleCore
"""

from .core import RPACore, Domain, DomainBlock, MemtableEntry, PageTableMode, FaultInfo
from .memory import (
    MemoryManager, PageTable, PageTableEntry, PageTableMode,
    Memory, INHERIT, INDEPENDENT
)
from .emulator import (
    SimpleCore, Assembler, CPUState, Instruction, OpCode,
    Asm
)
from .machine import Machine

# Constants
INHERIT = 0  # page_table = 0 means inherit
INDEPENDENT = PageTableMode.INDEPENDENT

# Compatibility aliases (deprecated)
Level = Domain
LevelConfig = DomainBlock
ISADecoder = SimpleCore
SubConfig = DomainBlock

__version__ = "0.4.0"
__all__ = [
    # Core
    "RPACore", "Domain", "DomainBlock", "MemtableEntry", "PageTableMode", "FaultInfo",
    # Memory
    "MemoryManager", "PageTable", "PageTableEntry", "Memory",
    "INHERIT", "INDEPENDENT",
    # Core (SimpleCore)
    "SimpleCore", "Assembler", "CPUState", "Instruction", "OpCode", "Asm",
    # Machine
    "Machine",
    # Legacy (deprecated)
    "Level", "LevelConfig", "ISADecoder", "SubConfig",
]