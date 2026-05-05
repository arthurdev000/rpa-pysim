"""
Memory Manager - Physical memory and page table simulation

提供物理内存模拟和页表管理功能。

物理内存：
- 模拟一块连续的物理内存空间
- 支持字节、半字、字（32位）读写
- 无页表时 PA = VA

页表叠加：
- 每层的页表翻译上一层返回的"物理地址"
- 翻译失败时，异常归属 memtable_address 所属的域
- 实现 RPA 的地址空间隔离机制

翻译链示例：
    Domain 2 访问 VA2:
      ipa2 = translate(domain2.memtable_addr, va2)
           - 访问页表数据需要用 domain1.memtable_addr 翻译
           - 失败 → 报给 domain2
      ipa1 = translate(domain1.memtable_addr, ipa2)
           - 失败 → 报给 domain1
      pa = translate(domain0.memtable_addr, ipa1)
           - 失败 → 报给 domain0 (root)
      访问 pa → 总线错误
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum, auto
import struct


@dataclass
class TranslationResult:
    """翻译结果"""
    pa: int                    # 物理地址
    r: bool = True             # 可读
    w: bool = True             # 可写
    x: bool = True             # 可执行
    c: bool = False            # 控制区域（必须用 sysop 访问）
    fault_owner: Optional[int] = None  # 异常归属域，None 表示成功


class TranslationError(Exception):
    """地址翻译错误，包含归属信息"""
    def __init__(self, va: int, memtable_owner: int, reason: str):
        self.va = va
        self.memtable_owner = memtable_owner  # memtable 所属的域 ID
        self.reason = reason
        super().__init__(f"Translation error: VA=0x{va:#x}, owner={memtable_owner}, {reason}")


class BusError(Exception):
    """总线错误 - 物理地址访问失败"""
    def __init__(self, pa: int):
        self.pa = pa
        super().__init__(f"Bus error: PA=0x{pa:#x}")


class PermissionError(Exception):
    """权限错误 - 访问权限不足"""
    def __init__(self, va: int, owner_domain: int, access_type: str, reason: str):
        self.va = va
        self.owner_domain = owner_domain
        self.access_type = access_type  # 'read', 'write', 'execute'
        self.reason = reason
        super().__init__(f"Permission error: VA=0x{va:#x}, owner={owner_domain}, {access_type}: {reason}")


@dataclass
class PageTableEntry:
    """单个页表项"""
    virtual_page: int        # 虚拟页号
    physical_page: int       # 物理页号
    r: bool = True           # 可读
    w: bool = True           # 可写
    x: bool = True           # 可执行
    c: bool = False          # 硬件控制寄存器（必须用 sysop 访问）


class PageTable:
    """单级页表"""

    def __init__(self, base_addr: int, page_size: int = 4096, owner_domain: int = 0):
        """
        初始化页表。

        Args:
            base_addr: 页表基址（用于标识）
            page_size: 页大小，默认4KB
            owner_domain: 页表所属的域 ID
        """
        self.base_addr = base_addr
        self.page_size = page_size
        self.owner_domain = owner_domain
        self.entries: Dict[int, PageTableEntry] = {}

    def map(self, va: int, pa: int,
            r: bool = True, w: bool = True, x: bool = True,
            control: bool = False) -> None:
        """
        映射虚拟地址到物理地址。

        Args:
            va: 虚拟地址
            pa: 物理地址
            r, w, x: 读、写、执行权限
            control: 是否为硬件控制寄存器区域
                     control 区域必须用 sysop 指令访问，
                     常规 ldr/str 会触发异常
        """
        vpn = va // self.page_size
        ppn = pa // self.page_size
        self.entries[vpn] = PageTableEntry(
            virtual_page=vpn,
            physical_page=ppn,
            r=r,
            w=w,
            x=x,
            c=control
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

    def get_permissions(self, addr: int) -> Optional[Tuple[bool, bool, bool, bool]]:
        """
        获取地址的权限。

        Returns:
            (r, w, x, c) 或 None
        """
        vpn = addr // self.page_size
        entry = self.entries.get(vpn)
        if entry:
            return (entry.r, entry.w, entry.x, entry.c)
        return None

    def is_control(self, addr: int) -> bool:
        """
        检查地址是否在 control 区域。

        control 区域必须用 sysop 指令访问。
        """
        vpn = addr // self.page_size
        entry = self.entries.get(vpn)
        return entry.c if entry else False

    def get_page_count(self) -> int:
        """获取已映射页数"""
        return len(self.entries)


class Memory:
    """
    内存单元 - 物理内存模拟与页表管理。

    模拟一块连续的物理内存空间，支持：
    - 字节、半字（16位）、字（32位）读写
    - 内存区域权限设置
    - 地址边界检查

    无页表时 PA = VA。
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

    翻译规则：
    - memtable_address = 0：跳过本层，继承父域地址空间
    - memtable_address != 0：用该页表翻译，失败报给本域

    翻译链示例：
        Domain 2 访问 VA:
        1. 用 domain2.memtable_addr 的页表翻译 → 失败报给 domain2
        2. 用 domain1.memtable_addr 的页表翻译 → 失败报给 domain1
        3. 用 domain0.memtable_addr 的页表翻译 → 失败报给 domain0
        4. 访问最终物理地址 → 失败报总线错误
    """

    def __init__(self, physical_memory: Optional['Memory'] = None):
        """
        初始化内存管理器。

        Args:
            physical_memory: 物理内存实例，默认创建1MB内存
        """
        self.physical_memory = physical_memory or Memory(1024 * 1024)
        # memtable_addr -> PageTable
        self.page_tables: Dict[int, PageTable] = {}

    def create_page_table(self, base_addr: int, page_size: int = 4096,
                          owner_domain: int = 0) -> PageTable:
        """
        创建页表。

        Args:
            base_addr: 页表基址（memtable_address）
            page_size: 页大小
            owner_domain: 页表所属的域 ID

        Returns:
            创建的页表
        """
        pt = PageTable(base_addr, page_size, owner_domain)
        self.page_tables[base_addr] = pt
        return pt

    def get_page_table(self, memtable_addr: int) -> Optional[PageTable]:
        """获取页表"""
        return self.page_tables.get(memtable_addr)

    def translate_chain(self, va: int, memtable_chain: List[int]) -> TranslationResult:
        """
        沿着 memtable 链翻译地址。

        Args:
            va: 虚拟地址
            memtable_chain: 从当前域到根域的 memtable_address 列表
                           [domain_n.memtable_addr, domain_n-1.memtable_addr, ..., domain_0.memtable_addr]

        Returns:
            TranslationResult 包含物理地址、权限和异常信息
        """
        current_addr = va
        # 权限从最宽松开始，每层翻译可能会限制
        r, w, x, c = True, True, True, False

        for memtable_addr in memtable_chain:
            # memtable_addr = 0 表示跳过本层翻译
            if memtable_addr == 0:
                continue

            pt = self.page_tables.get(memtable_addr)
            if pt is None:
                # 页表不存在，返回异常
                return TranslationResult(
                    pa=current_addr,
                    fault_owner=memtable_addr  # 用 memtable_addr 作为临时标识
                )

            # 翻译
            translated = pt.translate(current_addr)
            if translated is None:
                # 翻译失败，报给该页表的拥有者
                return TranslationResult(
                    pa=current_addr,
                    fault_owner=pt.owner_domain
                )

            # 获取本层权限并合并（取交集，越内层越严格）
            perms = pt.get_permissions(current_addr)
            if perms:
                layer_r, layer_w, layer_x, layer_c = perms
                r = r and layer_r
                w = w and layer_w
                x = x and layer_x
                c = c or layer_c  # 控制属性是累加的

            current_addr = translated

        return TranslationResult(
            pa=current_addr,
            r=r,
            w=w,
            x=x,
            c=c,
            fault_owner=None
        )

    def read_with_translation(self, va: int, memtable_chain: List[int],
                              size: int = 4) -> Tuple[int, Optional[int]]:
        """
        带翻译和权限检查的读取。

        Args:
            va: 虚拟地址
            memtable_chain: memtable 地址链
            size: 读取大小（1/2/4 字节）

        Returns:
            (value, fault_owner) - 读取的值和异常归属

        Raises:
            PermissionError: 权限不足（不可读或访问控制区域）
            BusError: 物理地址访问失败
        """
        result = self.translate_chain(va, memtable_chain)
        if result.fault_owner is not None:
            return (0, result.fault_owner)

        # 检查读权限
        if not result.r:
            raise PermissionError(va, result.fault_owner or 0, 'read', 'page not readable')

        # 检查控制区域（必须用 sysop 访问）
        if result.c:
            raise PermissionError(va, result.fault_owner or 0, 'read',
                                  'control area requires sysop access')

        try:
            if size == 1:
                return (self.physical_memory.read_byte(result.pa), None)
            elif size == 2:
                return (self.physical_memory.read_halfword(result.pa), None)
            else:
                return (self.physical_memory.read_word(result.pa), None)
        except MemoryError:
            raise BusError(result.pa)

    def write_with_translation(self, va: int, value: int,
                               memtable_chain: List[int], size: int = 4) -> Optional[int]:
        """
        带翻译和权限检查的写入。

        Args:
            va: 虚拟地址
            value: 要写入的值
            memtable_chain: memtable 地址链
            size: 写入大小（1/2/4 字节）

        Returns:
            fault_owner 如果翻译失败，否则 None

        Raises:
            PermissionError: 权限不足（不可写或访问控制区域）
            BusError: 物理地址访问失败
        """
        result = self.translate_chain(va, memtable_chain)
        if result.fault_owner is not None:
            return result.fault_owner

        # 检查写权限
        if not result.w:
            raise PermissionError(va, result.fault_owner or 0, 'write', 'page not writable')

        # 检查控制区域（必须用 sysop 访问）
        if result.c:
            raise PermissionError(va, result.fault_owner or 0, 'write',
                                  'control area requires sysop access')

        try:
            if size == 1:
                self.physical_memory.write_byte(result.pa, value)
            elif size == 2:
                self.physical_memory.write_halfword(result.pa, value)
            else:
                self.physical_memory.write_word(result.pa, value)
            return None
        except MemoryError:
            raise BusError(result.pa)

    def dump_mappings(self, memtable_addr: int) -> Dict:
        """
        转储页表映射。

        Returns:
            映射信息字典
        """
        if memtable_addr == 0:
            return {"mode": "inherit"}

        pt = self.page_tables.get(memtable_addr)
        if pt is None:
            return {}

        return {
            "page_size":     pt.page_size,
            "owner_domain":  pt.owner_domain,
            "mappings": {
                f"0x{vpn * pt.page_size:#x}": f"0x{entry.physical_page * pt.page_size:#x}"
                for vpn, entry in pt.entries.items()
            }
        }