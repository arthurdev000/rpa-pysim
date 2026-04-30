"""
RPA Core - Core primitives implementation

Implements the recursive privilege architecture with descend() and escalate()
primitives, level management, and page table stacking.
"""

from dataclasses import dataclass, field
from typing import Any, Optional, List, Dict, Callable
from enum import Enum, auto


class PageTableMode(Enum):
    """Page table mode for sublayer"""
    INHERIT = auto()  # Share parent's page table (page_table = 0)
    INDEPENDENT = auto()  # Use independent page table


@dataclass
class LevelConfig:
    """
    Level configuration structure for descend/escalate.

    This is the core data structure passed during layer transitions.
    """
    execution_addr: int  # Entry point (descend) / return address (escalate)
    exception_vector: int = 0  # Exception handler entry (trap + fault)
    page_table: int = 0  # Page table base (0 = inherit parent)
    interrupt_controller: int = 0  # Interrupt controller base (0 = none)
    interrupt_vector: int = 0  # Interrupt entry (separate from exception)
    program: Dict[str, Any] = field(default_factory=dict)  # Arch-specific state (LR, SPSR, etc.)
    params: Dict[str, Any] = field(default_factory=dict)  # Additional parameters

    # For descend: which sublayer to enter (implementation-defined)
    sub_index: int = 0


@dataclass
class Level:
    """
    A privilege level in RPA.

    From the perspective of current level:
    - self = Level 0
    - sublayers = Level 1, 2, 3, ...
    - parent = Level -1
    """
    level_id: int  # Absolute level ID (for debugging)
    config: LevelConfig  # Configuration for this level

    # Sublayer configurations (managed by this level)
    sub_configs: List[LevelConfig] = field(default_factory=list)

    # Parent reference (None for root)
    parent: Optional['Level'] = None

    # Context (registers, etc.)
    context: Dict[str, Any] = field(default_factory=dict)

    def add_sublayer(self, config: LevelConfig) -> int:
        """Add a sublayer configuration, return index"""
        self.sub_configs.append(config)
        return len(self.sub_configs) - 1

    def get_sublayer(self, index: int) -> Optional[LevelConfig]:
        """Get sublayer configuration by index"""
        if 0 <= index < len(self.sub_configs):
            return self.sub_configs[index]
        return None


@dataclass
class FaultInfo:
    """Fault information structure"""
    fault_type: str  # "bus_error", "memory_exhausted", "hardware_error", etc.
    layer: int  # Layer where fault occurred
    address: int = 0  # Related address (if applicable)
    context: Dict[str, Any] = field(default_factory=dict)


class RPACore:
    """
    RPA Core Simulator

    Implements the recursive privilege architecture with:
    - descend(context): Enter sublayer
    - escalate(context): Request service from parent layer
    - Level management
    - Page table stacking
    """

    def __init__(self):
        # Root level (Level 0 in absolute terms)
        root_config = LevelConfig(
            execution_addr=0x8000,  # Root entry point
            exception_vector=0x8004,
            page_table=0x10000,  # Root has its own page table
        )
        self.root: Level = Level(level_id=0, config=root_config)

        # Current execution level
        self.current: Level = self.root

        # Level stack (for tracking descent path)
        self.level_stack: List[Level] = [self.root]

        # Memory manager (injected or created)
        self.memory: Any = None

        # ARM emulator (for instruction execution)
        self.arm: Any = None

        # Exception handlers
        self.exception_handlers: Dict[str, Callable] = {}

        # Statistics
        self.stats = {
            "descend_count": 0,
            "escalate_count": 0,
            "fault_count": 0,
        }

    def configure_sublayer(self, parent: Level, config: LevelConfig) -> int:
        """
        Configure a sublayer for a parent level.

        Returns the sublayer index.
        """
        return parent.add_sublayer(config)

    def descend(self, context: LevelConfig) -> Any:
        """
        Enter sublayer.

        Args:
            context: LevelConfig containing execution_addr, exception_vector, etc.
                     context.execution_addr = sublayer entry point
                     context.sub_index = which sublayer to enter (default 0)

        Returns:
            Result from sublayer (when it returns)

        Raises:
            ValueError: If no sublayer configured
            RuntimeError: If no control block available
        """
        # Get sublayer configuration
        sub_index = context.sub_index
        sub_config = self.current.get_sublayer(sub_index)
        if sub_config is None:
            raise ValueError(f"No sublayer at index {sub_index}")

        # Use sub_config if it has execution_addr, otherwise use context
        entry_addr = sub_config.execution_addr if sub_config.execution_addr else context.execution_addr

        # Create new level with the context
        new_config = LevelConfig(
            execution_addr=entry_addr,
            exception_vector=sub_config.exception_vector,
            page_table=sub_config.page_table,
            interrupt_controller=sub_config.interrupt_controller,
            interrupt_vector=sub_config.interrupt_vector,
            program=context.program.copy(),
            params=context.params.copy(),
        )
        new_level = Level(
            level_id=self.current.level_id + 1,
            config=new_config,
            parent=self.current,
            context={"params": context.params}
        )

        # Update current level
        self.current = new_level
        self.level_stack.append(new_level)

        # Update statistics
        self.stats["descend_count"] += 1

        # Simulate execution at sublayer entry
        # In real implementation, this would jump to entry_addr
        result = self._execute_sublayer(new_level, entry_addr, context.params)

        return result

    def escalate(self, context: LevelConfig) -> Any:
        """
        Request service from parent layer.

        Args:
            context: LevelConfig containing params and program state
                     context.execution_addr will be updated by parent as return address

        Returns:
            Result from parent handler

        Raises:
            RuntimeError: If at root level (no parent)
        """
        if self.current.parent is None:
            raise RuntimeError("Cannot escalate from root level")

        parent = self.current.parent

        # Update statistics
        self.stats["escalate_count"] += 1

        # In real implementation, this would jump to parent's handler
        # The parent updates context.execution_addr with return address
        # For simulation, we call a handler if registered
        handler = self.current.context.get("service_handler")
        if handler:
            return handler(context.params)

        # Default: just return params for demonstration
        return {"escalated": True, "params": context.params, "from_level": self.current.level_id}

    def fault(self, fault_type: str, address: int = 0) -> None:
        """
        Trigger a fault (which is a type of exception).

        Args:
            fault_type: Type of fault
            address: Related address (if applicable)
        """
        fault_info = FaultInfo(
            fault_type=fault_type,
            layer=self.current.level_id,
            address=address,
            context=self.current.context.copy()
        )

        self.stats["fault_count"] += 1

        # All exceptions go through exception_vector
        # The handler determines if it's a trap or fault
        if self.current.config.exception_vector != 0:
            self._handle_exception(fault_info)
        else:
            # Escalate to parent
            self._propagate_fault(fault_info)

    def return_to_parent(self, result: Any = None) -> None:
        """
        Return from current level to parent.

        Args:
            result: Result to pass back to parent
        """
        if self.current.parent is None:
            raise RuntimeError("Cannot return from root level")

        # Pop from stack
        self.level_stack.pop()
        self.current = self.current.parent

        # Store result in parent's context
        self.current.context["sublayer_result"] = result

    def _execute_sublayer(self, level: Level, entry: int, params: Dict[str, Any]) -> Any:
        """
        Simulate sublayer execution.

        In real implementation, this would execute instructions at entry point.
        For simulation, we just return a placeholder.
        """
        return {"executed": True, "entry": entry, "params": params}

    def _handle_exception(self, fault_info: FaultInfo) -> None:
        """Handle exception at current level's exception_vector"""
        handler = self.exception_handlers.get(fault_info.fault_type)
        if handler:
            handler(fault_info)
        else:
            # Default: propagate to parent
            self._propagate_fault(fault_info)

    def _propagate_fault(self, fault_info: FaultInfo) -> None:
        """Propagate fault to parent level"""
        if self.current.parent is None:
            # Root level cannot handle, system crash
            raise RuntimeError(f"Unhandled fault at root: {fault_info}")

        # Escalate to parent via exception
        old_current = self.current
        self.current = self.current.parent

        # Parent handles fault
        self.escalate(LevelConfig(
            execution_addr=0,  # Will be updated by parent
            params={"type": "fault", "info": fault_info.__dict__}
        ))

        # Restore current level (if parent didn't kill the sublayer)
        self.current = old_current

    def get_level_depth(self) -> int:
        """Get current level depth (0 = root)"""
        return len(self.level_stack) - 1

    def get_stats(self) -> Dict[str, int]:
        """Get statistics"""
        return self.stats.copy()


# Legacy compatibility alias
SubConfig = LevelConfig

# Constants
INHERIT = 0  # page_table = 0 means inherit
INDEPENDENT = PageTableMode.INDEPENDENT