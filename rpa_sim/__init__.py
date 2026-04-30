"""
RPA Simulator - Recursive Privilege Architecture Concept Verification

本包提供 RPA（递归特权架构）的 Python 模拟器，
演示核心原语 descend() 和 escalate()。

主要组件：
- RPACore: RPA 核心模拟器
- Level, LevelConfig: 特权层管理
- PhysicalMemory: 物理内存模拟
- MemoryManager: 页表叠加管理
- Emulator: 简化指令集模拟器
"""

from .core import RPACore, Level, LevelConfig, PageTableMode, FaultInfo
from .memory import (
    MemoryManager, PageTable, PageTableEntry, PageTableMode,
    PhysicalMemory, INHERIT, INDEPENDENT
)
from .emulator import (
    Emulator, Assembler, CPUState, Instruction, OpCode,
    Asm
)

# 常量
INHERIT = PageTableMode.INHERIT
INDEPENDENT = PageTableMode.INDEPENDENT

# 兼容性别名
SubConfig = LevelConfig

__version__ = "0.3.0"
__all__ = [
    # Core
    "RPACore", "Level", "LevelConfig", "PageTableMode", "FaultInfo",
    # Memory
    "MemoryManager", "PageTable", "PageTableEntry", "PhysicalMemory",
    "INHERIT", "INDEPENDENT",
    # Emulator
    "Emulator", "Assembler", "CPUState", "Instruction", "OpCode", "asm",
    # Legacy
    "SubConfig",
]