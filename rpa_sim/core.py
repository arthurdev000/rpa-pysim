"""
RPA Core - Domain management and privilege primitives

实现递归特权架构的核心原语：
- descend(): 进入子域
- escalate(): 请求父域服务
- Domain: 特权域管理
- DomainBlock: 内存控制块结构

Domain 层级结构:
=================

    ┌─────────────────────────────────────────────────────────────────┐
    │                        RPA Domain 层级                          │
    ├─────────────────────────────────────────────────────────────────┤
    │                                                                 │
    │    ┌──────────────────┐                                         │
    │    │   Domain 0       │  ← 根域 (root_domain)                   │
    │    │   特权级: 0      │    - 拥有物理内存                       │
    │    │                  │    - 可创建子域                         │
    │    │  ┌────────────┐  │    - 处理子域的 ESCALATE               │
    │    │  │ Domain 1   │  │                                         │
    │    │  │ 特权级: 1  │  │  ← 子域                                 │
    │    │  │            │  │    - 拥有虚拟内存                       │
    │    │  │ ┌────────┐ │  │    - 可创建孙域                         │
    │    │  │ │Domain 2│ │  │    - 处理孙域的 ESCALATE               │
    │    │  │ │特权级:2│ │  │                                         │
    │    │  │ └────────┘ │  │  ← 孙域                                 │
    │    │  └────────────┘  │                                         │
    │    └──────────────────┘                                         │
    │                                                                 │
    │    DESCEND: Domain N → Domain N+1 (向下进入子域)                │
    │    ESCALATE: Domain N → Domain N-1 (向上请求服务)               │
    │                                                                 │
    └─────────────────────────────────────────────────────────────────┘

DomainBlock (控制块):
====================

    ┌────────────────────────────────────────────────────────────────┐
    │                    DomainBlock 内存布局                        │
    │                     (128 字节, 64字节对齐)                     │
    ├────────────┬───────────────────────────────────────────────────┤
    │ 偏移       │ 字段                                              │
    ├────────────┼───────────────────────────────────────────────────┤
    │ 0x00       │ execution_address   执行地址                      │
    │ 0x04       │ exception_vector    异常向量                      │
    │ 0x08       │ interrupt_vector    中断向量                      │
    │ 0x0C       │ interrupt_ctrl      中断控制器                    │
    │ 0x10       │ memtable_address    内存区域表地址                │
    │ 0x14       │ status              状态码 (Decoder上报)          │
    │ 0x18       │ reserved            保留                          │
    │ 0x1C       │ padding             填充 (对齐到0x20)             │
    └────────────┴───────────────────────────────────────────────────┘

DESCEND 流程:
=============

    父域执行 DESCEND R0 (R0 = 控制块地址):

    ┌─────────────────────────────────────────────────────────────────┐
    │ RTL (硬件)                   │ Decoder (SimpleCore)            │
    ├──────────────────────────────┼──────────────────────────────────┤
    │                              │                                 │
    │ 1. 读取控制块:               │                                 │
    │    entry = [R0 + 0x00]       │                                 │
    │    exception = [R0 + 0x04]   │                                 │
    │    memtable = [R0 + 0x10]    │                                 │
    │                              │                                 │
    │ 2. 切换到子域:               │                                 │
    │    current_domain = child    │                                 │
    │    PC = entry ────────────────▶ Decoder 开始执行               │
    │                              │                                 │
    │                              │ 3. Decoder 执行代码             │
    │                              │    ...                          │
    │                              │    ESCALATE R0                  │
    │                              │                                 │
    └──────────────────────────────┴──────────────────────────────────┘

ESCALATE 流程:
==============

    子域执行 ESCALATE R0 (R0 = 服务类型):

    ┌─────────────────────────────────────────────────────────────────┐
    │ RTL (硬件)                   │ Decoder (SimpleCore)            │
    ├──────────────────────────────┼──────────────────────────────────┤
    │                              │                                 │
    │                              │ 1. Decoder 保存自己的上下文     │
    │                              │    (寄存器状态由 Decoder 管理)  │
    │                              │                                 │
    │                              │ 2. Decoder 写入状态信息:        │
    │                              │    [block+0x80] = status        │
    │                              │    [block+0x84] = addr          │
    │                              │                                 │
    │ 3. RTL 读取状态:             │                                 │
    │    status = [block+0x80]     │                                 │
    │                              │                                 │
    │ 4. 切换到父域:               │                                 │
    │    current_domain = parent   │                                 │
    │    PC = parent.exception_vec ─▶ Decoder 跳转到处理程序         │
    │                              │                                 │
    │                              │ 5. Decoder 处理请求             │
    │                              │    读取状态、执行服务           │
    │                              │                                 │
    │                              │ 6. RETURN 返回                  │
    │                              │                                 │
    └──────────────────────────────┴──────────────────────────────────┘

异常传播:
=========

    子域触发异常:

    ┌─────────────────────────────────────────────────────────────────┐
    │ RTL (硬件)                   │ Decoder (SimpleCore)            │
    ├──────────────────────────────┼──────────────────────────────────┤
    │                              │                                 │
    │                              │ 1. Decoder 检测到异常           │
    │                              │    (缺页、非法指令等)           │
    │                              │                                 │
    │                              │ 2. Decoder 保存上下文           │
    │                              │    写入状态信息到控制块         │
    │                              │    [block+0x80] = status        │
    │                              │                                 │
    │ 3. RTL 检查 exception_vector │                                 │
    │    if (== 0) → 传播到父域    │                                 │
    │    else → 跳转处理           │                                 │
    │                              │                                 │
    │ 4. RTL 切换到父域            │                                 │
    │    ───────────────────────────▶ 5. Decoder 异常处理            │
    │                              │                                 │
    └──────────────────────────────┴──────────────────────────────────┘
"""

from dataclasses import dataclass, field
from typing import Any, Optional, List, Dict, Callable
from enum import Enum, auto


class PageTableMode(Enum):
    """页表模式"""
    INHERIT = auto()      # 继承父层页表
    INDEPENDENT = auto()  # 独立页表


@dataclass
class MemtableEntry:
    """
    内存区域表条目

    描述一个可用的内存区域：
    ┌────────────────────────────────────────┐
    │ base   : 区域起始地址                 │
    │ size   : 区域大小                     │
    │ attr   : 属性 (READ|WRITE|EXEC|...)   │
    └────────────────────────────────────────┘
    """
    base: int
    size: int
    attr: int = 0

    READ = 1 << 0
    WRITE = 1 << 1
    EXEC = 1 << 2
    DEVICE = 1 << 3


@dataclass
class DomainBlock:
    """
    Domain 配置块 (内存结构)

    父域在内存中分配此结构，然后执行 DESCEND 使配置生效。

    大小: 128 字节
    对齐: 64 字节边界

    见文件头部 ASCII 图解
    """
    # 配置字段 (父域在 DESCEND 前写入)
    execution_address: int = 0      # 0x00: 执行地址
    exception_vector: int = 0      # 0x04: 异常向量
    interrupt_vector: int = 0      # 0x08: 中断向量
    interrupt_ctrl: int = 0        # 0x0C: 中断控制器
    memtable_address: int = 0      # 0x10: 内存区域表地址
    status: int = 0                # 0x14: 状态码 (Decoder上报)
    reserved: int = 0              # 0x18: 保留
    padding: int = 0               # 0x1C: 填充 (对齐到0x20)

    # 向后兼容字段
    params: Dict[str, Any] = field(default_factory=dict)
    program: Dict[str, Any] = field(default_factory=dict)
    sub_index: int = 0


@dataclass
class Domain:
    """
    特权域

    每个域有：
    - 配置块 (DomainBlock)
    - 可选的子域列表
    - 执行上下文
    """
    domain_id: int
    block: DomainBlock
    parent: Optional['Domain'] = None
    children: List['Domain'] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)

    def add_child(self, child: 'Domain') -> int:
        """添加子域，返回索引"""
        child.parent = self
        self.children.append(child)
        return len(self.children) - 1

    def get_child(self, index: int) -> Optional['Domain']:
        """获取子域"""
        if 0 <= index < len(self.children):
            return self.children[index]
        return None


@dataclass
class FaultInfo:
    """异常信息"""
    fault_type: str
    domain: int
    address: int = 0
    context: Dict[str, Any] = field(default_factory=dict)


class RPACore:
    """
    RPA 核心 - 域管理

    管理 Domain 层级和特权切换：
    - descend(): 进入子域
    - escalate(): 请求父域服务
    - return_to_child(): 返回子域
    - fault(): 触发异常
    """

    def __init__(self):
        # 根域 (domain_id = 0)
        root_block = DomainBlock(
            execution_address=0x8000,
            exception_vector=0x8004,
        )
        self.root_domain: Domain = Domain(domain_id=0, block=root_block)

        # 当前执行域
        self.current_domain: Domain = self.root_domain

        # 域栈
        self.domain_stack: List[Domain] = [self.root_domain]

        # 内存引用 (用于读写 DomainBlock)
        self.memory: Any = None

        # 核心引用 (用于指令执行)
        self.core: Any = None

        # 异常处理器 (根域)
        self.exception_handlers: Dict[str, Callable] = {}

        # 统计
        self.stats = {
            "descend_count": 0,
            "escalate_count": 0,
            "fault_count": 0,
        }

    def configure_child(self, parent: Domain, block: DomainBlock) -> int:
        """
        配置子域

        Args:
            parent: 父域
            block: 配置块

        Returns:
            子域索引
        """
        child_id = parent.domain_id * 16 + len(parent.children) + 1
        child = Domain(domain_id=child_id, block=block)
        return parent.add_child(child)

    def descend(self, block_addr: int) -> Any:
        """
        进入子域

        RTL层只负责:
        1. 从内存读取 DomainBlock
        2. 创建新域
        3. 切换到子域
        4. 返回入口信息

        寄存器保存由 Decoder 负责
        """
        if self.memory is None:
            raise RuntimeError("Memory not set")

        block = self._read_domain_block(block_addr)

        # 创建新域
        new_id = self.current_domain.domain_id * 16 + len(self.current_domain.children) + 1
        new_domain = Domain(
            domain_id=new_id,
            block=block,
            parent=self.current_domain,
        )

        # 切换
        self.current_domain = new_domain
        self.domain_stack.append(new_domain)

        self.stats["descend_count"] += 1

        return {
            "execution_address": block.execution_address,
            "memtable": block.memtable_address,
            "domain_id": new_id,
        }

    def escalate(self, service_type: int) -> Any:
        """
        请求父域服务

        RTL层只负责:
        1. 切换到父域
        2. 返回 exception_vector

        状态保存由 Decoder 负责
        """
        if self.current_domain.parent is None:
            raise RuntimeError("Cannot escalate from root domain")

        parent = self.current_domain.parent

        self.stats["escalate_count"] += 1

        # 切换到父域
        self.current_domain = parent

        return {
            "vector": parent.block.exception_vector,
            "domain_id": parent.domain_id,
        }

    def return_to_child(self, child: Domain) -> Any:
        """返回子域 (由 Decoder 调用)"""
        self.current_domain = child
        return {
            "domain_id": child.domain_id,
        }

    def fault(self, fault_type: str, address: int = 0) -> None:
        """触发异常"""
        fault_info = FaultInfo(
            fault_type=fault_type,
            domain=self.current_domain.domain_id,
            address=address,
            context=self.current_domain.context.copy(),
        )

        self.stats["fault_count"] += 1

        if self.current_domain.block.exception_vector != 0:
            self._handle_fault(fault_info)
        else:
            self._propagate_fault(fault_info)

    def get_depth(self) -> int:
        """获取当前域深度"""
        return len(self.domain_stack) - 1

    def get_stats(self) -> Dict[str, int]:
        """获取统计信息"""
        return self.stats.copy()

    def _read_domain_block(self, addr: int) -> DomainBlock:
        """从内存读取 DomainBlock"""
        if self.memory:
            return DomainBlock(
                execution_address=self.memory.read_word(addr + 0x00),
                exception_vector=self.memory.read_word(addr + 0x04),
                interrupt_vector=self.memory.read_word(addr + 0x08),
                interrupt_ctrl=self.memory.read_word(addr + 0x0C),
                memtable_address=self.memory.read_word(addr + 0x10),
                status=self.memory.read_word(addr + 0x14),
            )
        return DomainBlock()

    def _write_domain_block(self, addr: int, block: DomainBlock) -> None:
        """写入 DomainBlock 到内存"""
        if self.memory:
            self.memory.write_word(addr + 0x00, block.execution_address)
            self.memory.write_word(addr + 0x04, block.exception_vector)
            self.memory.write_word(addr + 0x08, block.interrupt_vector)
            self.memory.write_word(addr + 0x0C, block.interrupt_ctrl)
            self.memory.write_word(addr + 0x10, block.memtable_address)
            self.memory.write_word(addr + 0x14, block.status)

    def _get_pc(self) -> int:
        """获取当前 PC"""
        if self.core:
            return self.core.state.pc
        return 0

    def _handle_fault(self, fault_info: FaultInfo) -> None:
        """处理异常"""
        self.current_domain.block.status = self._fault_type_to_code(fault_info.fault_type)
        self.current_domain.block.status_addr = fault_info.address

        handler = self.exception_handlers.get(fault_info.fault_type)
        if handler:
            handler(fault_info)
        else:
            self._propagate_fault(fault_info)

    def _propagate_fault(self, fault_info: FaultInfo) -> None:
        """传播异常到父域"""
        if self.current_domain.parent is None:
            raise RuntimeError(f"Unhandled fault at root: {fault_info}")

        old_domain = self.current_domain
        self.current_domain = self.current_domain.parent
        self.escalate(0x01)  # FAULT 类型
        self.current_domain = old_domain

    def _fault_type_to_code(self, fault_type: str) -> int:
        """转换异常类型到代码"""
        codes = {
            "escalate": 0x00,
            "page_fault": 0x01,
            "illegal_instruction": 0x02,
            "privilege_violation": 0x03,
        }
        return codes.get(fault_type, 0xFF)