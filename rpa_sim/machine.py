"""
RPA Machine - 集成 RPACore、内存和核心

Machine 类将 RPACore、Memory、MemoryManager 和 SimpleISA 组合在一起，
提供完整的 RPA 执行环境。
"""

from typing import Any, Dict, Optional, Callable, List
from .core import RPACore, Domain, DomainBlock
from .memory import Memory, MemoryManager, PageTable, TranslationError, BusError
from .isa_simple import SimpleISA
from .stdio import StdioDevice, StdioDeviceManager


STDIO_BASE = 0xFFFF0000


class Machine:
    """
    RPA 机器实例

    组件:
    - RPACore: Domain 管理
    - Memory: 物理内存
    - MemoryManager: 页表管理和地址翻译
    - SimpleISA: 指令执行
    """

    def __init__(self, memory_size: int = 1024 * 1024,
                 stdio_base: int = STDIO_BASE,
                 stdio_callback: Optional[Callable[[str], None]] = None):
        # 核心组件
        self.rpa = RPACore()
        self.memory = Memory(size=memory_size)
        self.mm = MemoryManager(physical_memory=self.memory)

        # STDIO 设备
        self.stdio = StdioDevice(base_addr=stdio_base, output_callback=stdio_callback)
        self.stdio_manager = StdioDeviceManager()
        self.stdio_manager.register(self.stdio)

        # Domain 核心
        self.cores: Dict[int, SimpleISA] = {}
        self.root_core = SimpleISA(memory=self.memory, memory_manager=self.mm)
        self.cores[0] = self.root_core

        # Domain 页表: domain_id -> memtable_addr
        self.domain_memtables: Dict[int, int] = {0: 0}  # root domain 无页表

        # 代码段记录
        self.code_segments: Dict[int, Dict] = {}

    def load_code(self, code: str, base_addr: int,
                  domain_id: Optional[int] = None) -> int:
        """加载汇编代码到内存"""
        if domain_id is None:
            domain_id = self.rpa.get_depth()

        core = self.cores.get(domain_id)
        if core is None:
            core = SimpleISA(memory=self.memory, memory_manager=self.mm)
            self.cores[domain_id] = core

        end_addr = core.load_assembly(code, base_addr=base_addr)

        self.code_segments[domain_id] = {
            "start": base_addr,
            "end": end_addr,
            "entry": base_addr,
        }

        return end_addr

    def load_binary(self, data: bytes, base_addr: int) -> int:
        """加载二进制数据到内存"""
        self.memory.write_bytes(base_addr, data)
        return base_addr + len(data)

    def load_domain_block(self, addr: int, block: DomainBlock) -> None:
        """将 DomainBlock 写入内存"""
        self.rpa.memory = self.memory
        self.rpa._write_domain_block(addr, block)

    def read_domain_block(self, addr: int) -> DomainBlock:
        """从内存读取 DomainBlock"""
        self.rpa.memory = self.memory
        return self.rpa._read_domain_block(addr)

    def create_page_table(self, domain_id: int, base_addr: int,
                          owner_domain: Optional[int] = None) -> PageTable:
        """
        为 Domain 创建页表

        Args:
            domain_id: Domain ID
            base_addr: 页表基址 (memtable_address)
            owner_domain: 页表所属的域（异常归属），默认为 domain_id
        """
        if owner_domain is None:
            owner_domain = domain_id

        pt = self.mm.create_page_table(base_addr, owner_domain=owner_domain)
        self.domain_memtables[domain_id] = base_addr
        return pt

    def map_memory(self, domain_id: int, va: int, pa: int,
                   r: bool = True, w: bool = True, x: bool = True,
                   control: bool = False) -> None:
        """
        为 Domain 映射内存

        Args:
            domain_id: Domain ID
            va: 虚拟地址
            pa: 物理地址
            r, w, x: 读、写、执行权限
            control: 是否为控制寄存器区域
        """
        memtable_addr = self.domain_memtables.get(domain_id, 0)
        if memtable_addr == 0:
            # 创建默认页表
            pt = self.create_page_table(domain_id, base_addr=0x10000 * (domain_id + 1))
            memtable_addr = pt.base_addr

        pt = self.mm.page_tables[memtable_addr]
        pt.map(va, pa, r, w, x, control)

    def get_memtable_chain(self, domain_id: int) -> List[int]:
        """
        获取 Domain 的 memtable 翻译链

        返回: [domain_n.memtable, ..., domain_0.memtable]
        """
        chain = []

        # 从当前 domain 向上遍历到 root
        domain = self._get_domain_by_id(domain_id)
        while domain:
            memtable = self.domain_memtables.get(domain.domain_id, 0)
            chain.append(memtable)
            domain = domain.parent

        return chain

    def _get_domain_by_id(self, domain_id: int) -> Optional[Domain]:
        """根据 ID 查找 Domain"""
        if domain_id == 0:
            return self.rpa.root_domain

        def find_domain(domain: Domain, target_id: int) -> Optional[Domain]:
            if domain.domain_id == target_id:
                return domain
            for child in domain.children:
                result = find_domain(child, target_id)
                if result:
                    return result
            return None

        return find_domain(self.rpa.root_domain, domain_id)

    def configure_child(self, parent: Optional[Domain], block: DomainBlock,
                        code: Optional[str] = None) -> int:
        """配置子域"""
        if parent is None:
            parent = self.rpa.root_domain

        idx = self.rpa.configure_child(parent, block)

        if code:
            domain_id = parent.domain_id * 16 + idx + 1
            self.load_code(code, block.execution_address, domain_id)

        return idx

    def descend(self, block_addr: int) -> Any:
        """进入子域"""
        result = self.rpa.descend(block_addr)

        domain_id = result.get("domain_id", self.rpa.get_depth())

        # 创建或获取核心
        core = self.cores.get(domain_id)
        if core is None:
            core = SimpleISA(memory=self.memory, memory_manager=self.mm)
            self.cores[domain_id] = core

        # 设置 memtable_chain
        core.memtable_chain = self.get_memtable_chain(domain_id)

        # 设置入口地址
        core.state.pc = result.get("execution_address", 0)
        core.halted = False

        return result

    def escalate(self, service_type: int) -> Any:
        """请求父域服务"""
        return self.rpa.escalate(service_type)

    def run_at_domain(self, domain_id: int, entry_addr: Optional[int] = None,
                      max_steps: int = 10000) -> int:
        """在指定 Domain 运行代码"""
        core = self.cores.get(domain_id)
        if core is None:
            raise ValueError(f"No core for domain {domain_id}")

        if entry_addr is None:
            segment = self.code_segments.get(domain_id)
            if segment:
                entry_addr = segment["entry"]
            else:
                raise ValueError(f"No entry address for domain {domain_id}")

        # 设置 memtable_chain
        core.memtable_chain = self.get_memtable_chain(domain_id)
        core.state.pc = entry_addr
        core.halted = False

        return core.run(max_steps=max_steps)

    def read_memory(self, addr: int, size: int = 4) -> int:
        """读取内存（物理地址）"""
        if size == 1:
            return self.memory.read_byte(addr)
        elif size == 2:
            return self.memory.read_halfword(addr)
        else:
            return self.memory.read_word(addr)

    def write_memory(self, addr: int, value: int, size: int = 4) -> None:
        """写入内存（物理地址）"""
        if size == 1:
            self.memory.write_byte(addr, value)
        elif size == 2:
            self.memory.write_halfword(addr, value)
        else:
            self.memory.write_word(addr, value)

    def read_memory_va(self, va: int, domain_id: int, size: int = 4) -> int:
        """通过虚拟地址读取内存"""
        chain = self.get_memtable_chain(domain_id)
        if chain:
            value, fault_owner = self.mm.read_with_translation(va, chain, size)
            if fault_owner is not None:
                raise TranslationError(va, fault_owner, "Translation failed")
            return value
        else:
            return self.read_memory(va, size)

    def write_memory_va(self, va: int, value: int, domain_id: int, size: int = 4) -> None:
        """通过虚拟地址写入内存"""
        chain = self.get_memtable_chain(domain_id)
        if chain:
            fault_owner = self.mm.write_with_translation(va, value, chain, size)
            if fault_owner is not None:
                raise TranslationError(va, fault_owner, "Translation failed")
        else:
            self.write_memory(va, value, size)

    def get_register(self, reg: int, domain_id: Optional[int] = None) -> int:
        """获取寄存器值"""
        if domain_id is None:
            domain_id = self.rpa.get_depth()

        core = self.cores.get(domain_id)
        if core is None:
            return 0
        return core.state.get_reg(reg)

    def set_register(self, reg: int, value: int, domain_id: Optional[int] = None) -> None:
        """设置寄存器值"""
        if domain_id is None:
            domain_id = self.rpa.get_depth()

        core = self.cores.get(domain_id)
        if core is None:
            core = SimpleISA(memory=self.memory, memory_manager=self.mm)
            self.cores[domain_id] = core

        core.state.set_reg(reg, value)

    def get_execution_log(self, domain_id: Optional[int] = None) -> list:
        """获取执行日志"""
        if domain_id is None:
            domain_id = self.rpa.get_depth()

        core = self.cores.get(domain_id)
        if core is None:
            return []
        return core.get_execution_log()

    def get_depth(self) -> int:
        """获取当前 Domain 深度"""
        return self.rpa.get_depth()

    def get_stats(self) -> Dict[str, int]:
        """获取统计信息"""
        return self.rpa.get_stats()

    def dump_memory(self, addr: int, size: int = 64) -> str:
        """转储内存内容"""
        return self.memory.dump(addr, size)

    def reset(self) -> None:
        """重置机器状态"""
        self.rpa = RPACore()
        self.memory = Memory(size=self.memory.size)
        self.mm = MemoryManager(physical_memory=self.memory)
        self.cores = {0: SimpleISA(memory=self.memory, memory_manager=self.mm)}
        self.domain_memtables = {0: 0}
        self.code_segments.clear()