"""
Memory Manager - Physical memory and page table simulation

提供物理内存模拟和页表管理功能。

物理内存：
- 模拟一块连续的物理内存空间
- 支持字节、半字、字（32位）读写
- 无页表时 PA = VA

页表叠加：
- 每层的页表翻译上一层返回的"物理地址"
- 实现RPA的地址空间隔离机制
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum, auto
import struct


class PageTableMode(Enum):
    """页表模式"""
    INHERIT = "inherit"      # 继承父层页表
    INDEPENDENT = "independent"  # 独立页表


@dataclass
class PageTableEntry:
    """单个页表项"""
    virtual_page: int        # 虚拟页号
    physical_page: int       # 物理页号
    readable: bool = True    # 可读
    writable: bool = True    # 可写
    executable: bool = True  # 可执行


class PageTable:
    """单级页表"""

    def __init__(self, base_addr: int, page_size: int = 4096):
        """
        初始化页表。

        Args:
            base_addr: 页表基址（用于标识）
            page_size: 页大小，默认4KB
        """
        self.base_addr = base_addr
        self.page_size = page_size
        self.entries: Dict[int, PageTableEntry] = {}

    def map(self, va: int, pa: int,
            r: bool = True, w: bool = True, x: bool = True) -> None:
        """
        映射虚拟地址到物理地址。

        Args:
            va: 虚拟地址
            pa: 物理地址
            r, w, x: 读、写、执行权限
        """
        vpn = va // self.page_size
        ppn = pa // self.page_size
        self.entries[vpn] = PageTableEntry(
            virtual_page=vpn,
            physical_page=ppn,
            readable=r,
            writable=w,
            executable=x
        )

    def unmap(self, va: int) -> bool:
        """
        取消映射。

        Returns:
            是否成功取消映射
        """
        vpn = va // self.page_size
        if vpn in self.entries:
            del self.entries[vpn]
            return True
        return False

    def translate(self, addr: int) -> Optional[int]:
        """
        翻译地址。

        Args:
            addr: 虚拟地址

        Returns:
            物理地址，如果未映射则返回None
        """
        vpn = addr // self.page_size
        offset = addr % self.page_size

        entry = self.entries.get(vpn)
        if entry:
            return entry.physical_page * self.page_size + offset
        return None

    def get_permissions(self, addr: int) -> Optional[Tuple[bool, bool, bool]]:
        """
        获取地址的权限。

        Returns:
            (readable, writable, executable) 或 None
        """
        vpn = addr // self.page_size
        entry = self.entries.get(vpn)
        if entry:
            return (entry.readable, entry.writable, entry.executable)
        return None

    def get_page_count(self) -> int:
        """获取已映射页数"""
        return len(self.entries)


class PhysicalMemory:
    """
    物理内存模拟器。

    模拟一块连续的物理内存空间，支持：
    - 字节、半字（16位）、字（32位）读写
    - 内存区域权限设置
    - 地址边界检查
    """

    def __init__(self, size: int = 1024 * 1024):
        """
        初始化物理内存。

        Args:
            size: 内存大小（字节），默认1MB
        """
        self.size = size
        self.memory = bytearray(size)

        # 权限区域：{(start, end): (r, w, x)}
        self.permissions: Dict[Tuple[int, int], Tuple[bool, bool, bool]] = {}

        # 访问记录（用于测试验证）
        self.access_log: List[Dict] = []

    def _check_bounds(self, addr: int, size: int) -> None:
        """检查地址边界"""
        if addr < 0 or addr + size > self.size:
            raise MemoryError(
                f"地址越界: 访问 0x{addr:#x}+{size}, "
                f"但内存范围是 0x0-0x{self.size:#x}"
            )

    def read_byte(self, addr: int) -> int:
        """读取单字节"""
        self._check_bounds(addr, 1)
        value = self.memory[addr]
        self.access_log.append({
            "type": "read", "addr": addr, "size": 1, "value": value
        })
        return value

    def write_byte(self, addr: int, value: int) -> None:
        """写入单字节"""
        self._check_bounds(addr, 1)
        self.memory[addr] = value & 0xFF
        self.access_log.append({
            "type": "write", "addr": addr, "size": 1, "value": value
        })

    def read_halfword(self, addr: int) -> int:
        """读取半字（16位），小端序"""
        self._check_bounds(addr, 2)
        value = struct.unpack('<H', self.memory[addr:addr+2])[0]
        self.access_log.append({
            "type": "read", "addr": addr, "size": 2, "value": value
        })
        return value

    def write_halfword(self, addr: int, value: int) -> None:
        """写入半字（16位），小端序"""
        self._check_bounds(addr, 2)
        self.memory[addr:addr+2] = struct.pack('<H', value & 0xFFFF)
        self.access_log.append({
            "type": "write", "addr": addr, "size": 2, "value": value
        })

    def read_word(self, addr: int) -> int:
        """读取字（32位），小端序"""
        self._check_bounds(addr, 4)
        value = struct.unpack('<I', self.memory[addr:addr+4])[0]
        self.access_log.append({
            "type": "read", "addr": addr, "size": 4, "value": value
        })
        return value

    def write_word(self, addr: int, value: int) -> None:
        """写入字（32位），小端序"""
        self._check_bounds(addr, 4)
        self.memory[addr:addr+4] = struct.pack('<I', value & 0xFFFFFFFF)
        self.access_log.append({
            "type": "write", "addr": addr, "size": 4, "value": value
        })

    def read_bytes(self, addr: int, size: int) -> bytes:
        """读取多字节"""
        self._check_bounds(addr, size)
        data = bytes(self.memory[addr:addr+size])
        self.access_log.append({
            "type": "read", "addr": addr, "size": size, "value": data
        })
        return data

    def write_bytes(self, addr: int, data: bytes) -> None:
        """写入多字节"""
        self._check_bounds(addr, len(data))
        self.memory[addr:addr+len(data)] = data
        self.access_log.append({
            "type": "write", "addr": addr, "size": len(data), "value": data
        })

    def fill(self, addr: int, size: int, value: int = 0) -> None:
        """填充内存区域"""
        self._check_bounds(addr, size)
        for i in range(size):
            self.memory[addr + i] = value & 0xFF

    def set_permissions(self, start: int, end: int,
                        r: bool = True, w: bool = True, x: bool = True) -> None:
        """
        设置内存区域权限。

        Args:
            start: 起始地址
            end: 结束地址（不包含）
            r, w, x: 读、写、执行权限
        """
        self.permissions[(start, end)] = (r, w, x)

    def get_permissions(self, addr: int) -> Tuple[bool, bool, bool]:
        """
        获取地址的权限。

        Returns:
            (readable, writable, executable)
        """
        for (start, end), perms in self.permissions.items():
            if start <= addr < end:
                return perms
        # 默认：全部允许
        return (True, True, True)

    def check_permission(self, addr: int, access_type: str) -> bool:
        """
        检查访问权限。

        Args:
            addr: 地址
            access_type: 'r', 'w', 'x'

        Returns:
            是否允许访问
        """
        r, w, x = self.get_permissions(addr)
        if access_type == 'r':
            return r
        elif access_type == 'w':
            return w
        elif access_type == 'x':
            return x
        return False

    def clear_access_log(self) -> None:
        """清空访问日志"""
        self.access_log.clear()

    def dump(self, addr: int, size: int) -> str:
        """
        以十六进制格式转储内存内容。

        Args:
            addr: 起始地址
            size: 字节数

        Returns:
            十六进制转储字符串
        """
        self._check_bounds(addr, size)
        lines = []
        for offset in range(0, size, 16):
            line_addr = addr + offset
            line_data = self.memory[line_addr:line_addr+16]

            # 十六进制部分
            hex_part = ' '.join(f'{b:02x}' for b in line_data)

            # ASCII部分
            ascii_part = ''.join(
                chr(b) if 32 <= b < 127 else '.' for b in line_data
            )

            lines.append(f"{line_addr:08x}  {hex_part:<48}  {ascii_part}")

        return '\n'.join(lines)

    def load_binary(self, addr: int, data: bytes) -> None:
        """加载二进制数据到内存"""
        self.write_bytes(addr, data)


class MemoryManager:
    """
    内存管理器，支持页表叠加。

    实现RPA的页表叠加机制：
    - Level N+1 的 VA 由 PT_{N+1} 翻译为 Level N 的 PA
    - Level N 的 PA 由 PT_N 翻译为 Level N-1 的 PA
    - 依此类推直到真正的物理地址

    无页表时，PA = VA。
    """

    def __init__(self, physical_memory: Optional[PhysicalMemory] = None):
        """
        初始化内存管理器。

        Args:
            physical_memory: 物理内存实例，默认创建1MB内存
        """
        self.physical_memory = physical_memory or PhysicalMemory(1024 * 1024)
        self.page_tables: Dict[int, PageTable] = {}  # base_addr -> PageTable
        self.level_page_tables: Dict[int, int] = {}  # level_id -> page_table_base

    def create_page_table(self, base_addr: int, page_size: int = 4096) -> PageTable:
        """
        创建页表。

        Args:
            base_addr: 页表基址
            page_size: 页大小

        Returns:
            创建的页表
        """
        pt = PageTable(base_addr, page_size)
        self.page_tables[base_addr] = pt
        return pt

    def set_level_page_table(self, level_id: int,
                             pt_base: int | PageTableMode) -> None:
        """
        设置某层的页表。

        Args:
            level_id: 层级ID
            pt_base: 页表基址，或 PageTableMode.INHERIT 表示继承父层
        """
        if pt_base == PageTableMode.INHERIT:
            self.level_page_tables[level_id] = -1  # -1 表示继承
        else:
            self.level_page_tables[level_id] = pt_base

    def translate_stacked(self, va: int, level_stack: List[int]) -> int:
        """
        通过页表叠加翻译虚拟地址。

        Args:
            va: 最深层的虚拟地址
            level_stack: 从根到当前层的层级ID列表

        Returns:
            最终物理地址

        Raises:
            RuntimeError: 页表未找到或地址未映射
        """
        current_addr = va

        # 从最深层向根层遍历
        for level_id in reversed(level_stack):
            pt_base = self.level_page_tables.get(level_id)

            if pt_base is None or pt_base == -1:
                # INHERIT：跳过此层
                continue

            pt = self.page_tables.get(pt_base)
            if pt is None:
                raise RuntimeError(
                    f"页表未找到: base=0x{pt_base:#x}"
                )

            # 通过此层翻译
            translated = pt.translate(current_addr)
            if translated is None:
                raise RuntimeError(
                    f"缺页异常: VA=0x{current_addr:#x}, level={level_id}"
                )

            current_addr = translated

        return current_addr

    def read_word(self, va: int, level_stack: List[int]) -> int:
        """
        读取一个字（32位），自动进行地址翻译。

        Args:
            va: 虚拟地址
            level_stack: 层级栈

        Returns:
            读取的值
        """
        pa = self.translate_stacked(va, level_stack)
        return self.physical_memory.read_word(pa)

    def write_word(self, va: int, level_stack: List[int], value: int) -> None:
        """
        写入一个字（32位），自动进行地址翻译。

        Args:
            va: 虚拟地址
            level_stack: 层级栈
            value: 要写入的值
        """
        pa = self.translate_stacked(va, level_stack)
        self.physical_memory.write_word(pa, value)

    def dump_mappings(self, level_id: int) -> Dict:
        """
        转储某层的页表映射。

        Returns:
            映射信息字典
        """
        pt_base = self.level_page_tables.get(level_id)
        if pt_base is None or pt_base == -1:
            return {"mode": "inherit"}

        pt = self.page_tables.get(pt_base)
        if pt is None:
            return {}

        return {
            "page_size": pt.page_size,
            "mappings": {
                f"0x{vpn * pt.page_size:#x}": f"0x{entry.physical_page * pt.page_size:#x}"
                for vpn, entry in pt.entries.items()
            }
        }


# 便捷常量
INHERIT = PageTableMode.INHERIT
INDEPENDENT = PageTableMode.INDEPENDENT