"""
Memory Manager - Physical memory and page table simulation

提供物理内存模拟和页表管理功能。

物理内存：
- 模拟一块连续的物理内存空间
- 支持字节、半字、字（32位）读写
- 无页表时 PA = VA

页表叠加：
- 每层的页表翻译上一层返回的"物理地址"
- 翻译失败时，异常归属 pagetable 所属的域
- 实现 RPA 的地址空间隔离机制

翻译链示例：
    Domain 2 访问 VA2:
      ipa2 = translate(domain2.pagetable, va2)
           - 访问页表数据需要用 domain1.pagetable 翻译
           - 失败 → 报给 domain2
      ipa1 = translate(domain1.pagetable, ipa2)
           - 失败 → 报给 domain1
      pa = translate(domain0.pagetable, ipa1)
           - 失败 → 报给 domain0 (root)
      访问 pa → 总线错误
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Set, TYPE_CHECKING
from enum import Enum, auto
import struct

if TYPE_CHECKING:
    from .security_group import SecurityGroupController


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
class EncryptedRegion:
    """加密内存区域"""
    start: int              # 起始地址
    size: int               # 大小
    security_handle: int    # 所属安全组 handle
    key: int                # 加密密钥

    def encrypt(self, data: bytes) -> bytes:
        """加密数据（XOR 模拟）"""
        key_bytes = self.key.to_bytes(8, 'little')
        return bytes(b ^ key_bytes[i % 8] for i, b in enumerate(data))

    def decrypt(self, data: bytes) -> bytes:
        """解密数据（XOR 模拟，对称）"""
        return self.encrypt(data)


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
    - 加密内存区域

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

        # 加密区域：{start: EncryptedRegion}
        self.encrypted_regions: Dict[int, 'EncryptedRegion'] = {}

    def set_encryption(self, start: int, size: int, security_handle: int, key: int) -> None:
        """
        设置内存区域加密。

        Args:
            start: 起始地址
            size: 区域大小
            security_handle: 安全组 handle
            key: 加密密钥
        """
        region = EncryptedRegion(
            start=start,
            size=size,
            security_handle=security_handle,
            key=key
        )
        self.encrypted_regions[start] = region

    def clear_encryption(self, start: int) -> bool:
        """
        清除加密区域。

        Args:
            start: 起始地址

        Returns:
            是否成功
        """
        if start in self.encrypted_regions:
            del self.encrypted_regions[start]
            return True
        return False

    def clear_encryption_by_handle(self, security_handle: int) -> int:
        """
        清除指定安全组的所有加密区域。

        Args:
            security_handle: 安全组 handle

        Returns:
            清除的区域数量
        """
        to_remove = [
            start for start, region in self.encrypted_regions.items()
            if region.security_handle == security_handle
        ]
        for start in to_remove:
            del self.encrypted_regions[start]
        return len(to_remove)

    def get_encryption_region(self, addr: int) -> Optional['EncryptedRegion']:
        """
        获取地址所属的加密区域。

        Args:
            addr: 地址

        Returns:
            加密区域，如果不在加密区域返回 None
        """
        for region in self.encrypted_regions.values():
            if region.start <= addr < region.start + region.size:
                return region
        return None

    def _encrypt_if_needed(self, addr: int, data: bytes) -> bytes:
        """如果需要则加密数据"""
        region = self.get_encryption_region(addr)
        if region:
            return region.encrypt(data)
        return data

    def _decrypt_if_needed(self, addr: int, data: bytes) -> bytes:
        """如果需要则解密数据"""
        region = self.get_encryption_region(addr)
        if region:
            return region.decrypt(data)
        return data

    def _check_bounds(self, addr: int, size: int) -> None:
        """检查地址边界"""
        if addr < 0 or addr + size > self.size:
            raise MemoryError(
                f"地址越界: 访问 0x{addr:#x}+{size}, "
                f"但内存范围是 0x0-0x{self.size:#x}"
            )

    def read_byte(self, addr: int, decrypt: bool = True) -> int:
        """读取单字节"""
        self._check_bounds(addr, 1)
        value = self.memory[addr]
        if decrypt:
            value = self._decrypt_if_needed(addr, bytes([value]))[0]
        self.access_log.append({
            "type": "read", "addr": addr, "size": 1, "value": value
        })
        return value

    def write_byte(self, addr: int, value: int, encrypt: bool = True) -> None:
        """写入单字节"""
        self._check_bounds(addr, 1)
        if encrypt:
            value = self._encrypt_if_needed(addr, bytes([value & 0xFF]))[0]
        self.memory[addr] = value & 0xFF
        self.access_log.append({
            "type": "write", "addr": addr, "size": 1, "value": value
        })

    def read_halfword(self, addr: int, decrypt: bool = True) -> int:
        """读取半字（16位），小端序"""
        self._check_bounds(addr, 2)
        data = self.memory[addr:addr+2]
        if decrypt:
            data = self._decrypt_if_needed(addr, data)
        value = struct.unpack('<H', data)[0]
        self.access_log.append({
            "type": "read", "addr": addr, "size": 2, "value": value
        })
        return value

    def write_halfword(self, addr: int, value: int, encrypt: bool = True) -> None:
        """写入半字（16位），小端序"""
        self._check_bounds(addr, 2)
        data = struct.pack('<H', value & 0xFFFF)
        if encrypt:
            data = self._encrypt_if_needed(addr, data)
        self.memory[addr:addr+2] = data
        self.access_log.append({
            "type": "write", "addr": addr, "size": 2, "value": value
        })

    def read_word(self, addr: int, decrypt: bool = True) -> int:
        """读取字（32位），小端序"""
        self._check_bounds(addr, 4)
        data = self.memory[addr:addr+4]
        if decrypt:
            data = self._decrypt_if_needed(addr, data)
        value = struct.unpack('<I', data)[0]
        self.access_log.append({
            "type": "read", "addr": addr, "size": 4, "value": value
        })
        return value

    def write_word(self, addr: int, value: int, encrypt: bool = True) -> None:
        """写入字（32位），小端序"""
        self._check_bounds(addr, 4)
        data = struct.pack('<I', value & 0xFFFFFFFF)
        if encrypt:
            data = self._encrypt_if_needed(addr, data)
        self.memory[addr:addr+4] = data
        self.access_log.append({
            "type": "write", "addr": addr, "size": 4, "value": value
        })

    def read_bytes(self, addr: int, size: int, decrypt: bool = True) -> bytes:
        """读取多字节"""
        self._check_bounds(addr, size)
        data = bytes(self.memory[addr:addr+size])
        if decrypt:
            data = self._decrypt_if_needed(addr, data)
        self.access_log.append({
            "type": "read", "addr": addr, "size": size, "value": data
        })
        return data

    def write_bytes(self, addr: int, data: bytes, encrypt: bool = True) -> None:
        """写入多字节"""
        self._check_bounds(addr, len(data))
        write_data = data
        if encrypt:
            write_data = self._encrypt_if_needed(addr, data)
        self.memory[addr:addr+len(data)] = write_data
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
    - pagetable = 0：跳过本层，继承父域地址空间
    - pagetable != 0：用该页表翻译，失败报给本域

    翻译链示例：
        Domain 2 访问 VA:
        1. 用 domain2.pagetable 的页表翻译 → 失败报给 domain2
        2. 用 domain1.pagetable 的页表翻译 → 失败报给 domain1
        3. 用 domain0.pagetable 的页表翻译 → 失败报给 domain0
        4. 访问最终物理地址 → 失败报总线错误
    """

    def __init__(self, physical_memory: Optional['Memory'] = None):
        """
        初始化内存管理器。

        Args:
            physical_memory: 物理内存实例，默认创建1MB内存
        """
        self.physical_memory = physical_memory or Memory(1024 * 1024)
        # pagetable_addr -> PageTable
        self.page_tables: Dict[int, PageTable] = {}

        # 安全组控制器引用
        self.security_controller: Optional['SecurityGroupController'] = None

        # 页表到安全组的映射: pagetable_addr -> security_handle
        self.page_table_security: Dict[int, int] = {}

    def set_security_controller(self, controller: 'SecurityGroupController') -> None:
        """设置安全组控制器"""
        self.security_controller = controller
        # 同时设置到物理内存
        if controller:
            controller.memory_manager = self

    def bind_page_table_to_security(self, pagetable_addr: int, security_handle: int) -> None:
        """
        将页表绑定到安全组。

        Args:
            pagetable_addr: 页表基址
            security_handle: 安全组 handle
        """
        self.page_table_security[pagetable_addr] = security_handle

    def set_encryption(self, start: int, size: int, security_handle: int, key: int) -> None:
        """
        设置加密区域。

        Args:
            start: 起始地址
            size: 区域大小
            security_handle: 安全组 handle
            key: 加密密钥
        """
        self.physical_memory.set_encryption(start, size, security_handle, key)

    def clear_encryption_by_handle(self, security_handle: int) -> int:
        """
        清除指定安全组的所有加密区域。

        Args:
            security_handle: 安全组 handle

        Returns:
            清除的区域数量
        """
        return self.physical_memory.clear_encryption_by_handle(security_handle)

    def create_page_table(self, base_addr: int, page_size: int = 4096,
                          owner_domain: int = 0) -> PageTable:
        """
        创建页表。

        Args:
            base_addr: 页表基址（pagetable）
            page_size: 页大小
            owner_domain: 页表所属的域 ID

        Returns:
            创建的页表
        """
        pt = PageTable(base_addr, page_size, owner_domain)
        self.page_tables[base_addr] = pt
        return pt

    def get_page_table(self, pagetable_addr: int) -> Optional[PageTable]:
        """获取页表"""
        return self.page_tables.get(pagetable_addr)

    def translate_chain(self, va: int, pagetable_chain: List[int],
                        ipa_regions: int = 0,
                        memory: Optional['Memory'] = None) -> TranslationResult:
        """
        沿着页表链翻译地址。

        Args:
            va: 虚拟地址
            pagetable_chain: 从当前域到根域的 pagetable 地址列表
                           [domain_n.pagetable, domain_n-1.pagetable, ..., domain_0.pagetable]
            ipa_regions: IPA 区域表地址（父域设置，用于边界检查）
            memory: 内存实例（用于读取 ipa_regions 表）

        Returns:
            TranslationResult 包含物理地址、权限和异常信息
        """
        current_addr = va
        # 权限从最宽松开始，每层翻译可能会限制
        r, w, x, c = True, True, True, False

        for i, pagetable_addr in enumerate(pagetable_chain):
            # pagetable_addr = 0 表示跳过本层翻译
            if pagetable_addr == 0:
                continue

            pt = self.page_tables.get(pagetable_addr)
            if pt is None:
                # 页表不存在，返回异常
                return TranslationResult(
                    pa=current_addr,
                    fault_owner=pagetable_addr  # 用 pagetable_addr 作为临时标识
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

            # IPA 边界检查：在第一层翻译后检查
            # 第一层翻译后得到 IPA，需要检查是否在 ipa_regions 范围内
            if i == 0 and ipa_regions != 0 and memory is not None:
                if not self._check_ipa_bounds(current_addr, ipa_regions, memory):
                    return TranslationResult(
                        pa=current_addr,
                        fault_owner=pt.owner_domain  # 报给当前域
                    )

        return TranslationResult(
            pa=current_addr,
            r=r,
            w=w,
            x=x,
            c=c,
            fault_owner=None
        )

    def _check_ipa_bounds(self, ipa: int, ipa_regions: int, memory: 'Memory') -> bool:
        """
        检查 IPA 是否在 ipa_regions 定义的范围内。

        Args:
            ipa: 中间物理地址
            ipa_regions: IPA 区域表地址
            memory: 内存实例

        Returns:
            True 如果 IPA 在有效范围内，False 否则
        """
        # 遍历 IPA 区域表
        entry_addr = ipa_regions
        while True:
            base = memory.read_word(entry_addr + 0)
            size = memory.read_word(entry_addr + 4)
            attr = memory.read_word(entry_addr + 8)

            # 结束标记
            if base == 0 and size == 0 and attr == 0:
                break

            # 检查 IPA 是否在范围内
            if base <= ipa < base + size:
                return True

            entry_addr += 12  # 每个条目 12 字节

        # 没有找到匹配的区域
        return False

    def read_with_translation(self, va: int, pagetable_chain: List[int],
                              size: int = 4,
                              ipa_regions: int = 0) -> Tuple[int, Optional[int]]:
        """
        带翻译和权限检查的读取。

        Args:
            va: 虚拟地址
            pagetable_chain: 页表地址链
            size: 读取大小（1/2/4 字节）
            ipa_regions: IPA 区域表地址（用于边界检查）

        Returns:
            (value, fault_owner) - 读取的值和异常归属

        Raises:
            PermissionError: 权限不足（不可读或访问控制区域）
            BusError: 物理地址访问失败
        """
        result = self.translate_chain(va, pagetable_chain, ipa_regions, self.physical_memory)
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
                               pagetable_chain: List[int], size: int = 4,
                               ipa_regions: int = 0) -> Optional[int]:
        """
        带翻译和权限检查的写入。

        Args:
            va: 虚拟地址
            value: 要写入的值
            pagetable_chain: 页表地址链
            size: 写入大小（1/2/4 字节）
            ipa_regions: IPA 区域表地址（用于边界检查）

        Returns:
            fault_owner 如果翻译失败，否则 None

        Raises:
            PermissionError: 权限不足（不可写或访问控制区域）
            BusError: 物理地址访问失败
        """
        result = self.translate_chain(va, pagetable_chain, ipa_regions, self.physical_memory)
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

    def dump_mappings(self, pagetable_addr: int) -> Dict:
        """
        转储页表映射。

        Returns:
            映射信息字典
        """
        if pagetable_addr == 0:
            return {"mode": "inherit"}

        pt = self.page_tables.get(pagetable_addr)
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