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
- StdioDevice: Console output device for debugging
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
from .machine import Machine, STDIO_BASE
from .stdio import StdioDevice, StdioDeviceManager

__version__ = "0.5.0"
__all__ = [
    # Core
    "RPACore", "Domain", "DomainBlock", "MemtableEntry", "PageTableMode", "FaultInfo",
    # Memory
    "MemoryManager", "PageTable", "PageTableEntry", "Memory",
    "INHERIT", "INDEPENDENT",
    # Core (SimpleCore)
    "SimpleCore", "Assembler", "CPUState", "Instruction", "OpCode", "Asm",
    # Machine
    "Machine", "STDIO_BASE",
    # Stdio
    "StdioDevice", "StdioDeviceManager",
]