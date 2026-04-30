"""
RPA Machine - 集成 RPACore、内存和解码器

Machine 类将 RPACore、Memory 和 ISADecoder 组合在一起，
提供完整的 RPA 执行环境。
"""

from typing import Any, Dict, Optional, Callable
from .core import RPACore, Level, LevelConfig, FaultInfo
from .memory import Memory, MemoryManager, PageTable
from .emulator import ISADecoder, Assembler


class Machine:
    """
    RPA 机器实例

    组合：
    - RPACore: 特权层级管理
    - Memory: 内存单元模拟
    - MemoryManager: 页表管理
    - ISADecoder: 指令执行

    提供：
    - 层级切换时的真实代码执行
    - 内存隔离验证
    - 页表翻译验证
    """

    def __init__(self, memory_size: int = 1024 * 1024):
        """
        初始化 RPA 机器

        Args:
            memory_size: 物理内存大小，默认1MB
        """
        # 核心组件
        self.rpa = RPACore()
        self.memory = Memory(size=memory_size)
        self.mm = MemoryManager(physical_memory=self.memory)

        # 层级对应的解码器
        # 每个层级可以有独立的解码器实例
        self.decoders: Dict[int, ISADecoder] = {}

        # 根层解码器
        self.root_decoder = ISADecoder(memory=self.memory)
        self.decoders[0] = self.root_decoder

        # 当前层级的解码器
        self.current_decoder: Optional[ISADecoder] = self.root_decoder

        # 代码加载地址记录
        self.code_segments: Dict[int, Dict] = {}  # level_id -> {start, end, entry}

        # 层级页表记录
        self.level_page_tables: Dict[int, int] = {}  # level_id -> page_table_base

    def load_code(self, code: str, base_addr: int,
                  level_id: Optional[int] = None) -> int:
        """
        加载汇编代码到内存

        Args:
            code: 汇编代码字符串
            base_addr: 加载基地址
            level_id: 目标层级ID，None表示当前层级

        Returns:
            代码结束地址
        """
        if level_id is None:
            level_id = self.rpa.get_level_depth()

        emu = self.decoders.get(level_id)
        if emu is None:
            emu = ISADecoder(memory=self.memory)
            self.decoders[level_id] = emu

        end_addr = emu.load_assembly(code, base_addr=base_addr)

        # 记录代码段
        self.code_segments[level_id] = {
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

    def create_page_table(self, level_id: int, base_addr: int) -> PageTable:
        """
        为指定层级创建页表

        Args:
            level_id: 层级ID
            base_addr: 页表基址

        Returns:
            创建的页表
        """
        pt = self.mm.create_page_table(base_addr)
        self.level_page_tables[level_id] = base_addr
        return pt

    def map_memory(self, level_id: int, va: int, pa: int,
                   r: bool = True, w: bool = True, x: bool = True) -> None:
        """
        为指定层级映射内存

        Args:
            level_id: 层级ID
            va: 虚拟地址
            pa: 物理地址
            r, w, x: 读、写、执行权限
        """
        pt_base = self.level_page_tables.get(level_id)
        if pt_base is None:
            # 创建默认页表
            pt = self.create_page_table(level_id, base_addr=0x10000 * (level_id + 1))
        else:
            pt = self.mm.page_tables[pt_base]

        pt.map(va, pa, r, w, x)

    def configure_sublayer(self, parent: Optional[Level], config: LevelConfig,
                          code: Optional[str] = None) -> int:
        """
        配置子层并可选加载代码

        Args:
            parent: 父层级，None表示根层
            config: 层级配置
            code: 可选的汇编代码

        Returns:
            子层索引
        """
        if parent is None:
            parent = self.rpa.root

        idx = self.rpa.configure_sublayer(parent, config)

        # 如果有代码，加载到内存
        if code:
            level_id = parent.level_id + 1  # 新层级的ID
            self.load_code(code, config.execution_addr, level_id)

        return idx

    def descend(self, config: LevelConfig,
                setup_handler: Optional[Callable] = None) -> Any:
        """
        进入子层并执行

        Args:
            config: 层级配置
            setup_handler: 可选的设置函数，在进入前调用

        Returns:
            执行结果
        """
        # 获取子层配置
        sub_index = config.sub_index
        sub_config = self.rpa.current.get_sublayer(sub_index)
        if sub_config is None:
            raise ValueError(f"No sublayer at index {sub_index}")

        # 创建或获取该层级的解码器
        level_id = self.rpa.get_level_depth() + 1
        emu = self.decoders.get(level_id)
        if emu is None:
            emu = ISADecoder(memory=self.memory)
            self.decoders[level_id] = emu

        # 设置 descend 处理器
        def descend_handler(params):
            if setup_handler:
                setup_handler(emu, params)

            # 设置入口地址
            emu.state.pc = sub_config.execution_addr

            # 执行直到 HALT 或 ESCALATE
            emu.run()

            # 返回结果
            return emu.state.get_reg(0)

        # 获取当前层级的解码器并设置处理器
        current_level = self.rpa.get_level_depth()
        current_emu = self.decoders.get(current_level, self.root_decoder)
        current_emu.descend_handler = descend_handler

        # 执行 descend
        result = self.rpa.descend(config)

        # 更新当前解码器
        self.current_decoder = self.decoders.get(self.rpa.get_level_depth())

        return result

    def escalate(self, config: LevelConfig,
                 handler: Optional[Callable] = None) -> Any:
        """
        从当前层请求父层服务

        Args:
            config: 配置
            handler: 父层处理器

        Returns:
            处理结果
        """
        if handler:
            self.rpa.current.context["service_handler"] = handler

        return self.rpa.escalate(config)

    def run_at_level(self, level_id: int, entry_addr: Optional[int] = None,
                     max_steps: int = 10000) -> int:
        """
        在指定层级运行代码

        Args:
            level_id: 层级ID
            entry_addr: 入口地址，None使用配置的入口
            max_steps: 最大执行步数

        Returns:
            执行步数
        """
        emu = self.decoders.get(level_id)
        if emu is None:
            raise ValueError(f"No emulator for level {level_id}")

        # 设置入口地址
        if entry_addr is None:
            segment = self.code_segments.get(level_id)
            if segment:
                entry_addr = segment["entry"]
            else:
                raise ValueError(f"No entry address for level {level_id}")

        emu.state.pc = entry_addr
        return emu.run(max_steps=max_steps)

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

    def get_register(self, reg: int, level_id: Optional[int] = None) -> int:
        """
        获取寄存器值

        Args:
            reg: 寄存器编号 (0-15)
            level_id: 层级ID，None表示当前层级

        Returns:
            寄存器值
        """
        if level_id is None:
            level_id = self.rpa.get_level_depth()

        emu = self.decoders.get(level_id)
        if emu is None:
            return 0
        return emu.state.get_reg(reg)

    def set_register(self, reg: int, value: int, level_id: Optional[int] = None) -> None:
        """
        设置寄存器值

        Args:
            reg: 寄存器编号 (0-15)
            value: 值
            level_id: 层级ID，None表示当前层级
        """
        if level_id is None:
            level_id = self.rpa.get_level_depth()

        emu = self.decoders.get(level_id)
        if emu is None:
            emu = ISADecoder(memory=self.memory)
            self.decoders[level_id] = emu

        emu.state.set_reg(reg, value)

    def get_execution_log(self, level_id: Optional[int] = None) -> list:
        """
        获取执行日志

        Args:
            level_id: 层级ID，None表示当前层级

        Returns:
            执行日志列表
        """
        if level_id is None:
            level_id = self.rpa.get_level_depth()

        emu = self.decoders.get(level_id)
        if emu is None:
            return []
        return emu.get_execution_log()

    def get_level_depth(self) -> int:
        """获取当前层级深度"""
        return self.rpa.get_level_depth()

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
        self.decoders = {0: ISADecoder(memory=self.memory)}
        self.current_decoder = self.decoders[0]
        self.code_segments.clear()
        self.level_page_tables.clear()