"""
RPA Simulator - Recursive Privilege Architecture Concept Verification

Main components:
- RPALogic: Domain hierarchy management
- Domain, DomainBlock: Privilege domain structures
- Memory: Physical memory simulation
- MemoryManager: Page table chain translation
- PageTable, PageTableEntry: Page table structures
- TranslationError, BusError, PermissionError: Address translation exceptions
- SimpleISA: Simplified instruction set core (ARM-like)
- Machine: Complete machine integrating all components
- InterruptController: Interrupt management
- SecurityDomainController: Security domain management
"""

from .rpa_logic import (
    RPALogic, Domain, DomainBlock, FaultInfo,
    CTRLBLOCK_WORDS, CTRLBLOCK_ALIGN_WORDS, CTRLBLOCK_MIN_WORDS,
    WORD_SIZE, CTRLBLOCK_SIZE, CTRLBLOCK_ALIGN, CTRLBLOCK_MIN_SIZE, DomainBlockError,
    OFFSET_CTRLBLOCK_SIZE, OFFSET_DOMAIN_ID, OFFSET_TRAP_VECTOR,
    OFFSET_INTERRUPT_CTRL, OFFSET_IPA_REGIONS, OFFSET_PAGETABLE,
    OFFSET_CHILD_BLOCK, OFFSET_SECURITY_DOMAIN
)
from .memory import (
    MemoryManager, PageTable, PageTableEntry, Memory,
    TranslationError, BusError, PermissionError, TranslationResult,
    EncryptedRegion
)
from .isa_simple import SimpleISA, Assembler, CPUState, Instruction, OpCode, Asm
from .machine import Machine, STDIO_BASE
from .stdio import StdioDevice, StdioDeviceManager
from .interrupt import (
    InterruptController, InterruptInstance, IrqPerm, IrqSubOp
)
from .security_domain import (
    SecurityDomainController, SecurityDomain, SecurityDomainConfig,
    SecDomainPerm, EncryptedRegion as SecEncryptedRegion
)

__version__ = "0.7.0"
__all__ = [
    # Core
    "RPALogic", "Domain", "DomainBlock", "FaultInfo",
    "CTRLBLOCK_WORDS", "CTRLBLOCK_ALIGN_WORDS", "CTRLBLOCK_MIN_WORDS",
    "WORD_SIZE", "CTRLBLOCK_SIZE", "CTRLBLOCK_ALIGN", "CTRLBLOCK_MIN_SIZE",
    "DomainBlockError",
    "OFFSET_CTRLBLOCK_SIZE", "OFFSET_DOMAIN_ID", "OFFSET_TRAP_VECTOR",
    "OFFSET_INTERRUPT_CTRL", "OFFSET_IPA_REGIONS", "OFFSET_PAGETABLE",
    "OFFSET_CHILD_BLOCK", "OFFSET_SECURITY_DOMAIN",
    # Memory
    "MemoryManager", "PageTable", "PageTableEntry", "Memory",
    "TranslationError", "BusError", "PermissionError", "TranslationResult",
    "EncryptedRegion",
    # ISA
    "SimpleISA", "Assembler", "CPUState", "Instruction", "OpCode", "Asm",
    # Machine
    "Machine", "STDIO_BASE",
    # Stdio
    "StdioDevice", "StdioDeviceManager",
    # Interrupt
    "InterruptController", "InterruptInstance", "IrqPerm", "IrqSubOp",
    # Security Domain
    "SecurityDomainController", "SecurityDomain", "SecurityDomainConfig",
    "SecDomainPerm",
]