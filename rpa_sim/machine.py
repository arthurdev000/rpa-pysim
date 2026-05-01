"""
RPA Machine - 集成 RPACore、内存和核心

Machine 类将 RPACore、Memory 和 SimpleCore 组合在一起，
提供完整的 RPA 执行环境。
"""

from typing import Any, Dict, Optional, Callable
from .core import RPACore, Domain, DomainBlock, FaultInfo
from .memory import Memory, MemoryManager, PageTable
from .emulator import SimpleCore, Assembler
from .stdio import StdioDevice, StdioDeviceManager


# 默认 STDIO 设备地址
STDIO_BASE = 0xFFFF0000


class Machine:
    """
    RPA 机器实例

    组合：
    - RPACore: Domain 管理
    - Memory: 内存单元模拟
    - MemoryManager: 页表管理
    - SimpleCore: 指令执行
    - StdioDevice: 控制台输出设备

    提供：
    - Domain 切换时的真实代码执行
    - 内存隔离验证
    - 页表翻译验证
    - 控制台输出
    """

    def __init__(self, memory_size: int = 1024 * 1024,
                 stdio_base: int = STDIO_BASE,
                 stdio_callback: Optional[Callable[[str], None]] = None):
        """
        初始化 RPA 机器

        Args:
            memory_size: 物理内存大小，默认1MB
            stdio_base: STDIO 设备基地址，默认 0xFFFF0000
            stdio_callback: 自定义输出回调，默认为 print
        """
        # 核心组件
        self.rpa = RPACore()
        self.memory = Memory(size=memory_size)
        self.mm = MemoryManager(physical_memory=self.memory)

        # STDIO 设备
        self.stdio = StdioDevice(base_addr=stdio_base, output_callback=stdio_callback)
        self.stdio_manager = StdioDeviceManager()
        self.stdio_manager.register(self.stdio)

        # Domain 对应的核心
        # 每个 Domain 可以有独立的核心实例
        self.cores: Dict[int, SimpleCore] = {}

        # 根域核心
        self.root_core = SimpleCore(memory=self.memory)
        self.cores[0] = self.root_core

        # 当前 Domain 的核心
        self.current_core: Optional[SimpleCore] = self.root_core

        # 代码加载地址记录
        self.code_segments: Dict[int, Dict] = {}  # domain_id -> {start, end, entry}

        # Domain 页表记录
        self.domain_page_tables: Dict[int, int] = {}  # domain_id -> page_table_base

    def load_code(self, code: str, base_addr: int,
                  domain_id: Optional[int] = None) -> int:
        """
        加载汇编代码到内存

        Args:
            code: 汇编代码字符串
            base_addr: 加载基地址
            domain_id: 目标 Domain ID，None表示当前 Domain

        Returns:
            代码结束地址
        """
        if domain_id is None:
            domain_id = self.rpa.get_depth()

        core = self.cores.get(domain_id)
        if core is None:
            core = SimpleCore(memory=self.memory)
            self.cores[domain_id] = core

        end_addr = core.load_assembly(code, base_addr=base_addr)

        # 记录代码段
        self.code_segments[domain_id] = {
            "start": base_addr,
            "end": end_addr,
            "entry": base_addr,
        }

        return end_addr

    def load_binary(self, data: bytes, base_addr: int) -> int:
        """
        加载二进制数据到内存

        Args:
            data: 二进制数据
            base_addr: 加载地址

        Returns:
            结束地址
        """
        self.memory.write_bytes(base_addr, data)
        return base_addr + len(data)

    def load_domain_block(self, addr: int, block: DomainBlock) -> None:
        """
        将 DomainBlock 写入内存

        Args:
            addr: 目标地址
            block: DomainBlock 实例
        """
        self.rpa.memory = self.memory
        self.rpa._write_domain_block(addr, block)

    def read_domain_block(self, addr: int) -> DomainBlock:
        """
        从内存读取 DomainBlock

        Args:
            addr: DomainBlock 地址

        Returns:
            DomainBlock 实例
        """
        self.rpa.memory = self.memory
        return self.rpa._read_domain_block(addr)

    def create_page_table(self, domain_id: int, base_addr: int) -> PageTable:
        """
        为指定 Domain 创建页表

        Args:
            domain_id: Domain ID
            base_addr: 页表基址

        Returns:
            创建的页表
        """
        pt = self.mm.create_page_table(base_addr)
        self.domain_page_tables[domain_id] = base_addr
        return pt

    def map_memory(self, domain_id: int, va: int, pa: int,
                   r: bool = True, w: bool = True, x: bool = True) -> None:
        """
        为指定 Domain 映射内存

        Args:
            domain_id: Domain ID
            va: 虚拟地址
            pa: 物理地址
            r, w, x: 读、写、执行权限
        """
        pt_base = self.domain_page_tables.get(domain_id)
        if pt_base is None:
            # 创建默认页表
            pt = self.create_page_table(domain_id, base_addr=0x10000 * (domain_id + 1))
        else:
            pt = self.mm.page_tables[pt_base]

        pt.map(va, pa, r, w, x)

    def configure_child(self, parent: Optional[Domain], block: DomainBlock,
                        code: Optional[str] = None) -> int:
        """
        配置子域并可选加载代码

        Args:
            parent: 父域，None表示根域
            block: Domain 配置
            code: 可选的汇编代码

        Returns:
            子域索引
        """
        if parent is None:
            parent = self.rpa.root_domain

        idx = self.rpa.configure_child(parent, block)

        # 如果有代码，加载到内存
        if code:
            domain_id = parent.domain_id * 16 + idx + 1
            self.load_code(code, block.execution_address, domain_id)

        return idx

    def descend(self, block_addr: int,
                setup_handler: Optional[Callable] = None) -> Any:
        """
        进入子域并执行

        Args:
            block_addr: DomainBlock 地址
            setup_handler: 可选的设置函数，在进入前调用

        Returns:
            执行结果
        """
        result = self.rpa.descend(block_addr)

        # 创建或获取该 Domain 的核心
        domain_id = result.get("domain_id", self.rpa.get_depth())
        core = self.cores.get(domain_id)
        if core is None:
            core = SimpleCore(memory=self.memory)
            self.cores[domain_id] = core

        if setup_handler:
            setup_handler(core, result)

        # 设置入口地址
        core.state.pc = result.get("execution_address", 0)

        # 更新当前核心
        self.current_core = core

        return result

    def escalate(self, service_type: int) -> Any:
        """
        从当前 Domain 请求父域服务

        Args:
            service_type: 服务类型

        Returns:
            处理结果
        """
        return self.rpa.escalate(service_type)

    def run_at_domain(self, domain_id: int, entry_addr: Optional[int] = None,
                      max_steps: int = 10000) -> int:
        """
        在指定 Domain 运行代码

        Args:
            domain_id: Domain ID
            entry_addr: 入口地址，None使用配置的入口
            max_steps: 最大执行步数

        Returns:
            执行步数
        """
        core = self.cores.get(domain_id)
        if core is None:
            raise ValueError(f"No core for domain {domain_id}")

        # 设置入口地址
        if entry_addr is None:
            segment = self.code_segments.get(domain_id)
            if segment:
                entry_addr = segment["entry"]
            else:
                raise ValueError(f"No entry address for domain {domain_id}")

        core.state.pc = entry_addr
        return core.run(max_steps=max_steps)

    def read_memory(self, addr: int, size: int = 4) -> int:
        """读取内存（字）"""
        if size == 1:
            return self.memory.read_byte(addr)
        elif size == 2:
            return self.memory.read_halfword(addr)
        else:
            return self.memory.read_word(addr)

    def write_memory(self, addr: int, value: int, size: int = 4) -> None:
        """写入内存"""
        if size == 1:
            self.memory.write_byte(addr, value)
        elif size == 2:
            self.memory.write_halfword(addr, value)
        else:
            self.memory.write_word(addr, value)

    def get_register(self, reg: int, domain_id: Optional[int] = None) -> int:
        """
        获取寄存器值

        Args:
            reg: 寄存器编号 (0-15)
            domain_id: Domain ID，None表示当前 Domain

        Returns:
            寄存器值
        """
        if domain_id is None:
            domain_id = self.rpa.get_depth()

        core = self.cores.get(domain_id)
        if core is None:
            return 0
        return core.state.get_reg(reg)

    def set_register(self, reg: int, value: int, domain_id: Optional[int] = None) -> None:
        """
        设置寄存器值

        Args:
            reg: 寄存器编号 (0-15)
            value: 值
            domain_id: Domain ID，None表示当前 Domain
        """
        if domain_id is None:
            domain_id = self.rpa.get_depth()

        core = self.cores.get(domain_id)
        if core is None:
            core = SimpleCore(memory=self.memory)
            self.cores[domain_id] = core

        core.state.set_reg(reg, value)

    def get_execution_log(self, domain_id: Optional[int] = None) -> list:
        """
        获取执行日志

        Args:
            domain_id: Domain ID，None表示当前 Domain

        Returns:
            执行日志列表
        """
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
        self.cores = {0: SimpleCore(memory=self.memory)}
        self.current_core = self.cores[0]
        self.code_segments.clear()
        self.domain_page_tables.clear()