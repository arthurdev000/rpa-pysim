"""
RPA Machine - 集成 RPALogic、内存和核心

Machine 类将 RPALogic、Memory、MemoryManager 和 SimpleISA 组合在一起，
提供完整的 RPA 执行环境。

架构说明：
- 每核心每特权层只有一个 DomainBlock
- 软件通过修改 DomainBlock 来切换进程/虚拟机
- Domain 对象在 DESCEND 时动态创建，用于错误归属
"""

from typing import Any, Dict, Optional, Callable, List
from .rpa_logic import RPALogic, Domain, DomainBlock
from .memory import Memory, MemoryManager, PageTable, TranslationError, BusError
from .isa_simple import SimpleISA
from .stdio import StdioDevice, StdioDeviceManager


STDIO_BASE = 0xFFFF0000


class Machine:
    """
    RPA 机器实例

    组件:
    - RPALogic: Domain 管理
    - Memory: 物理内存
    - MemoryManager: 页表管理和地址翻译
    - SimpleISA: 指令执行
    """

    def __init__(self, memory_size: int = 1024 * 1024,
                 stdio_base: int = STDIO_BASE,
                 stdio_callback: Optional[Callable[[str], None]] = None):
        # 核心组件
        self.rpa = RPALogic()
        self.memory = Memory(size=memory_size)
        self.mm = MemoryManager(physical_memory=self.memory)

        # 连接 RPALogic 和 Memory
        self.rpa.memory = self.memory

        # 单一核心
        self.core = SimpleISA(rpa=self.rpa, memory=self.memory, memory_manager=self.mm)

        # STDIO 设备
        self.stdio = StdioDevice(base_addr=stdio_base, output_callback=stdio_callback)
        self.stdio_manager = StdioDeviceManager()
        self.stdio_manager.register(self.stdio)

    def load_code(self, code: str, base_addr: int) -> int:
        """加载汇编代码到内存"""
        return self.core.load_assembly(code, base_addr=base_addr)

    def load_binary(self, data: bytes, base_addr: int) -> int:
        """加载二进制数据到内存"""
        self.memory.write_bytes(base_addr, data)
        return base_addr + len(data)

    def load_domain_block(self, addr: int, block: DomainBlock) -> None:
        """将 DomainBlock 写入内存"""
        self.rpa._write_domain_block(addr, block)

    def read_domain_block(self, addr: int) -> DomainBlock:
        """从内存读取 DomainBlock"""
        return self.rpa._read_domain_block(addr)

    def create_page_table(self, base_addr: int, owner_domain: int) -> PageTable:
        """
        创建页表

        Args:
            base_addr: 页表基址 (pagetable)
            owner_domain: 页表所属的域 ID（异常归属）
        """
        return self.mm.create_page_table(base_addr, owner_domain=owner_domain)

    def get_pagetable_chain(self) -> List[int]:
        """
        获取当前 Domain 的页表翻译链

        返回: [domain_n.pagetable, ..., domain_0.pagetable]
        """
        return self.rpa.get_pagetable_chain()

    def descend(self, block_addr: int) -> Any:
        """进入子域"""
        return self.rpa.descend(block_addr)

    def ascend(self, service_type: int) -> Any:
        """请求父域服务"""
        return self.rpa.ascend(service_type)

    def run(self, max_steps: int = 10000) -> int:
        """运行代码"""
        return self.core.run(max_steps=max_steps)

    def step(self) -> bool:
        """执行单步"""
        return self.core.step()

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

    def read_memory_va(self, va: int, size: int = 4) -> int:
        """通过虚拟地址读取内存"""
        chain = self.get_pagetable_chain()
        if chain:
            current_domain_id = self.rpa.current_domain.domain_id if self.rpa.current_domain else None
            ipa_regions = self.rpa.current_domain.block.ipa_regions if self.rpa.current_domain else 0
            value, fault_owner = self.mm.read_with_translation(
                va, chain, size, ipa_regions=ipa_regions, current_domain_id=current_domain_id
            )
            if fault_owner is not None:
                raise TranslationError(va, fault_owner, "Translation failed")
            return value
        else:
            return self.read_memory(va, size)

    def write_memory_va(self, va: int, value: int, size: int = 4) -> None:
        """通过虚拟地址写入内存"""
        chain = self.get_pagetable_chain()
        if chain:
            current_domain_id = self.rpa.current_domain.domain_id if self.rpa.current_domain else None
            ipa_regions = self.rpa.current_domain.block.ipa_regions if self.rpa.current_domain else 0
            fault_owner = self.mm.write_with_translation(
                va, value, chain, size, ipa_regions=ipa_regions, current_domain_id=current_domain_id
            )
            if fault_owner is not None:
                raise TranslationError(va, fault_owner, "Translation failed")
        else:
            self.write_memory(va, value, size)

    def get_register(self, reg: int) -> int:
        """获取寄存器值"""
        return self.core.state.get_reg(reg)

    def set_register(self, reg: int, value: int) -> None:
        """设置寄存器值"""
        self.core.state.set_reg(reg, value)

    def get_pc(self) -> int:
        """获取 PC"""
        return self.core.state.pc

    def set_pc(self, value: int) -> None:
        """设置 PC"""
        self.core.state.pc = value

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
        self.rpa = RPALogic()
        self.memory = Memory(size=self.memory.size)
        self.mm = MemoryManager(physical_memory=self.memory)
        self.core = SimpleISA(rpa=self.rpa, memory=self.memory, memory_manager=self.mm)
        self.rpa.memory = self.memory