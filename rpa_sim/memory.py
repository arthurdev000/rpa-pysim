"""
Memory Manager - Page table stacking simulation

Implements the page table stacking mechanism where each level's
page table translates the "physical address" from the level above.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
from enum import Enum


class PageTableMode(Enum):
    INHERIT = "inherit"
    INDEPENDENT = "independent"


@dataclass
class PageTableEntry:
    """Single page table entry"""
    virtual_page: int
    physical_page: int
    readable: bool = True
    writable: bool = True
    executable: bool = True


class PageTable:
    """Single level page table"""

    def __init__(self, base_addr: int):
        self.base_addr = base_addr
        self.entries: Dict[int, PageTableEntry] = {}
        self.page_size = 4096  # 4KB pages

    def map(self, va: int, pa: int, r: bool = True, w: bool = True, x: bool = True) -> None:
        """Map virtual address to physical address"""
        vpn = va // self.page_size
        ppn = pa // self.page_size
        self.entries[vpn] = PageTableEntry(
            virtual_page=vpn,
            physical_page=ppn,
            readable=r,
            writable=w,
            executable=x
        )

    def translate(self, addr: int) -> Optional[int]:
        """Translate address, return None if not mapped"""
        vpn = addr // self.page_size
        offset = addr % self.page_size

        entry = self.entries.get(vpn)
        if entry:
            return entry.physical_page * self.page_size + offset
        return None

    def get_permissions(self, addr: int) -> Optional[tuple]:
        """Get permissions for address"""
        vpn = addr // self.page_size
        entry = self.entries.get(vpn)
        if entry:
            return (entry.readable, entry.writable, entry.executable)
        return None


class MemoryManager:
    """
    Memory manager with page table stacking.

    Implements the RPA page table stacking mechanism where:
    - Level N+1's VA is translated by PT_{N+1} to Level N's PA
    - Level N's PA is translated by PT_N to Level N-1's PA
    - And so on until reaching real physical address
    """

    def __init__(self):
        self.page_tables: Dict[int, PageTable] = {}  # base_addr -> PageTable
        self.level_page_tables: Dict[int, int] = {}  # level_id -> page_table_base

        # Physical memory simulation
        self.physical_memory: Dict[int, bytes] = {}

        # INHERIT marker
        self.INHERIT = PageTableMode.INHERIT

    def create_page_table(self, base_addr: int) -> PageTable:
        """Create a new page table"""
        pt = PageTable(base_addr)
        self.page_tables[base_addr] = pt
        return pt

    def set_level_page_table(self, level_id: int, pt_base: int | PageTableMode) -> None:
        """Set page table for a level"""
        if pt_base == PageTableMode.INHERIT:
            # Mark as inheriting from parent
            self.level_page_tables[level_id] = -1  # -1 means inherit
        else:
            self.level_page_tables[level_id] = pt_base

    def translate_stacked(self, va: int, level_stack: List[int]) -> int:
        """
        Translate virtual address through stacked page tables.

        Args:
            va: Virtual address at the deepest level
            level_stack: List of level IDs from root to current

        Returns:
            Final physical address
        """
        current_addr = va

        # Walk from deepest level to root
        for level_id in reversed(level_stack):
            pt_base = self.level_page_tables.get(level_id)

            if pt_base is None or pt_base == -1:
                # INHERIT: skip this level
                continue

            pt = self.page_tables.get(pt_base)
            if pt is None:
                raise RuntimeError(f"Page table not found at {pt_base:#x}")

            # Translate through this level
            translated = pt.translate(current_addr)
            if translated is None:
                raise RuntimeError(
                    f"Page fault: VA {current_addr:#x} not mapped at level {level_id}"
                )

            current_addr = translated

        return current_addr

    def read_memory(self, va: int, level_stack: List[int], size: int) -> bytes:
        """Read memory through stacked translation"""
        pa = self.translate_stacked(va, level_stack)
        return self.physical_memory.get(pa, b'\x00' * size)

    def write_memory(self, va: int, level_stack: List[int], data: bytes) -> None:
        """Write memory through stacked translation"""
        pa = self.translate_stacked(va, level_stack)
        self.physical_memory[pa] = data

    def allocate_physical(self, size: int) -> int:
        """Allocate physical memory, return base address"""
        # Simple bump allocator for simulation
        base = max(self.physical_memory.keys(), default=0) + 4096
        self.physical_memory[base] = b'\x00' * size
        return base

    def dump_mappings(self, level_id: int) -> Dict[int, int]:
        """Dump page table mappings for a level"""
        pt_base = self.level_page_tables.get(level_id)
        if pt_base is None or pt_base == -1:
            return {"mode": "inherit"}

        pt = self.page_tables.get(pt_base)
        if pt is None:
            return {}

        return {vpn * pt.page_size: entry.physical_page * pt.page_size
                for vpn, entry in pt.entries.items()}


# Convenience constant
INHERIT = PageTableMode.INHERIT