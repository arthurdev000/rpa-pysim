"""
RPA Simulator - Recursive Privilege Architecture Concept Verification

本包提供 RPA（递归特权架构）的 Python 模拟器，
演示核心原语 descend() 和 escalate()。

主要组件：
- RPACore: RPA 核心模拟器
- Level, LevelConfig: 特权层管理
- Memory: 内存单元模拟（物理内存 + 页表管理）
- MemoryManager: 页表叠加管理
- ISADecoder: 简化指令集解码器
- Machine: 集成 RPACore、Memory、ISADecoder 的完整机器
"""

from .core import RPACore, Level, LevelConfig, PageTableMode, FaultInfo
from .memory import (
    MemoryManager, PageTable, PageTableEntry, PageTableMode,
    Memory, INHERIT, INDEPENDENT
)
from .emulator import (
    ISADecoder, Assembler, CPUState, Instruction, OpCode,
    Asm
)
from .machine import Machine

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
    "MemoryManager", "PageTable", "PageTableEntry", "Memory",
    "INHERIT", "INDEPENDENT",
    # ISA Decoder
    "ISADecoder", "Assembler", "CPUState", "Instruction", "OpCode", "Asm",
    # Machine
    "Machine",
    # Legacy
    "SubConfig",
]