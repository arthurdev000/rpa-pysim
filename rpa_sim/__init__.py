"""
RPA Simulator - Recursive Privilege Architecture Concept Verification

Main components:
- RPACore: Domain hierarchy management
- Domain, DomainBlock: Privilege domain structures
- Memory: Physical memory simulation
- MemoryManager: Page table chain translation
- PageTable, PageTableEntry: Page table structures
- TranslationError, BusError, PermissionError: Address translation exceptions
- SimpleISA: Simplified instruction set core (ARM-like)
- Machine: Complete machine integrating all components
"""

from .core import RPACore, Domain, DomainBlock, MemtableEntry, FaultInfo
from .memory import (
    MemoryManager, PageTable, PageTableEntry, Memory,
    TranslationError, BusError, PermissionError, TranslationResult
)
from .isa_simple import SimpleISA, Assembler, CPUState, Instruction, OpCode, Asm
from .machine import Machine, STDIO_BASE
from .stdio import StdioDevice, StdioDeviceManager

__version__ = "0.6.0"
__all__ = [
    # Core
    "RPACore", "Domain", "DomainBlock", "MemtableEntry", "FaultInfo",
    # Memory
    "MemoryManager", "PageTable", "PageTableEntry", "Memory",
    "TranslationError", "BusError", "PermissionError", "TranslationResult",
    # ISA
    "SimpleISA", "Assembler", "CPUState", "Instruction", "OpCode", "Asm",
    # Machine
    "Machine", "STDIO_BASE",
    # Stdio
    "StdioDevice", "StdioDeviceManager",
]