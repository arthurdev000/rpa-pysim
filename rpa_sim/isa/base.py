"""
ISA Base Class - Abstract interface for ISA implementations

Defines the contract for ISA-specific behavior in RPA:
- Context save area layout
- Register set
- Privilege level mapping
- Calling convention for cross-ISA communication
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Any
from enum import Enum


@dataclass
class RegisterInfo:
    """Information about a single register"""
    name: str
    index: int           # Index in register array
    size: int = 4        # Size in bytes (4 for 32-bit, 8 for 64-bit)
    is_callee_saved: bool = False
    is_argument: bool = False
    arg_position: int = -1  # Position in argument list (0, 1, 2...)


@dataclass
class CallingConvention:
    """
    Calling convention for cross-ISA parameter passing.

    When descending from one ISA to another, parameters must be mapped
    according to each ISA's calling convention.
    """
    arg_registers: List[str] = field(default_factory=list)  # Registers for args
    return_registers: List[str] = field(default_factory=list)  # Registers for return values
    caller_saved: List[str] = field(default_factory=list)   # Caller-saved registers
    callee_saved: List[str] = field(default_factory=list)   # Callee-saved registers
    stack_alignment: int = 16  # Stack alignment requirement


class PrivilegeLevel(Enum):
    """Standard privilege levels (mapped from ISA-specific levels)"""
    USER = 0       # Lowest privilege (Ring 3 / EL0 / U-mode)
    SUPERVISOR = 1 # OS kernel (Ring 0 / EL1 / S-mode)
    HYPERVISOR = 2 # Virtualization (EL2 / HS-mode)
    ROOT = 3       # Highest privilege (EL3 / M-mode)


@dataclass
class ISAContext:
    """
    ISA-specific execution context.

    This is saved/restored during cross-ISA domain switches.
    The layout is ISA-specific but this class provides a unified interface.
    """
    registers: Dict[str, int] = field(default_factory=dict)
    pc: int = 0
    sp: int = 0
    flags: Dict[str, bool] = field(default_factory=dict)

    # ISA tag for this context
    isa_tag: int = 0


class ISABase(ABC):
    """
    Abstract base class for ISA implementations.

    Each ISA must implement:
    - Register set definition
    - Context save area layout
    - Privilege level mapping
    - Calling convention
    - Context serialization/deserialization
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """ISA name (e.g., 'ARM', 'x86-64', 'RISC-V')"""
        pass

    @property
    @abstractmethod
    def isa_tag(self) -> int:
        """ISA tag value (ISA_TAG_ARM, ISA_TAG_X86, etc.)"""
        pass

    @property
    @abstractmethod
    def word_size(self) -> int:
        """Word size in bytes (4 for 32-bit, 8 for 64-bit)"""
        pass

    @property
    @abstractmethod
    def registers(self) -> List[RegisterInfo]:
        """List of registers for this ISA"""
        pass

    @property
    @abstractmethod
    def calling_convention(self) -> CallingConvention:
        """Calling convention for parameter passing"""
        pass

    @abstractmethod
    def get_context_save_size(self) -> int:
        """Size of context save area in bytes"""
        pass

    @abstractmethod
    def get_context_save_layout(self) -> Dict[str, Tuple[int, int]]:
        """
        Get context save area layout.

        Returns:
            Dict mapping field name to (offset, size) tuple
            Example: {'sp': (0, 4), 'lr': (4, 4), 'psr': (8, 4)}
        """
        pass

    @abstractmethod
    def serialize_context(self, context: ISAContext) -> bytes:
        """Serialize context to bytes for storing in DCB"""
        pass

    @abstractmethod
    def deserialize_context(self, data: bytes) -> ISAContext:
        """Deserialize context from DCB data"""
        pass

    def map_privilege_level(self, isa_level: int) -> PrivilegeLevel:
        """
        Map ISA-specific privilege level to RPA standard level.

        Args:
            isa_level: ISA-specific privilege level
                - ARM: EL0-EL3
                - x86: Ring 0-3
                - RISC-V: U/S/M mode (mapped as 0/1/3)

        Returns:
            Standard PrivilegeLevel enum value
        """
        raise NotImplementedError

    def get_arg_register(self, position: int) -> Optional[str]:
        """Get the register used for argument at given position"""
        cc = self.calling_convention
        if position < len(cc.arg_registers):
            return cc.arg_registers[position]
        return None

    def get_return_register(self, position: int = 0) -> Optional[str]:
        """Get the register used for return value at given position"""
        cc = self.calling_convention
        if position < len(cc.return_registers):
            return cc.return_registers[position]
        return None

    def get_register_by_name(self, name: str) -> Optional[RegisterInfo]:
        """Get register info by name"""
        for reg in self.registers:
            if reg.name.lower() == name.lower():
                return reg
        return None

    def get_register_by_index(self, index: int) -> Optional[RegisterInfo]:
        """Get register info by index"""
        for reg in self.registers:
            if reg.index == index:
                return reg
        return None
