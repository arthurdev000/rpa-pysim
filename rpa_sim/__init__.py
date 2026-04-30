"""
RPA Simulator - Recursive Privilege Architecture Concept Verification

This package provides a Python-based simulator for the Recursive Privilege
Architecture (RPA), demonstrating the core primitives descend() and escalate().
"""

from .core import RPACore, Level, LevelConfig, PageTableMode, FaultInfo
from .memory import MemoryManager, PageTable

# Constants
INHERIT = 0  # page_table = 0 means inherit parent's page table
INDEPENDENT = PageTableMode.INDEPENDENT

# Legacy compatibility
SubConfig = LevelConfig

__version__ = "0.2.0"
__all__ = [
    "RPACore", "Level", "LevelConfig", "PageTableMode", "FaultInfo",
    "MemoryManager", "PageTable", "INHERIT", "INDEPENDENT",
    "SubConfig"
]