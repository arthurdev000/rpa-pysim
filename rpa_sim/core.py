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
    │ 0x00       │ entry_addr          子域入口地址                  │
    │ 0x04       │ exception_vector    异常向量                      │
    │ 0x08       │ interrupt_vector    中断向量                      │
    │ 0x0C       │ interrupt_ctrl      中断控制器                    │
    │ 0x10       │ memtable_addr       内存区域表地址                │
    │ 0x14-0x3B  │ reserved            保留                          │
    │ 0x1C-0x3B  │ reserved            保留                          │
    ├────────────┼───────────────────────────────────────────────────┤
    │ 0x3C       │ saved_pc            保存的 PC                     │
    │ 0x40       │ saved_lr            保存的 LR                     │
    │ 0x44       │ saved_sp            保存的 SP                     │
    │ 0x48-0x78  │ saved_regs[13]      保存的 R0-R12                 │
    │ 0x78       │ saved_flags         保存的条件标志                │
    │ 0x7C       │ return_value        返回值                        │
    ├────────────┼───────────────────────────────────────────────────┤
    │ 0x80       │ exception_type      异常类型                      │
    │ 0x84       │ exception_addr      异常地址                      │
    │ 0x88       │ exception_info      异常详情                      │
    └────────────┴───────────────────────────────────────────────────┘

DESCEND 流程:
=============

    父域执行 DESCEND R0 (R0 = 控制块地址):

    ┌─────────────────────────────────────────────────────────────────┐
    │ 父域 (Domain N)              │ 子域 (Domain N+1)               │
    ├──────────────────────────────┼──────────────────────────────────┤
    │                              │                                 │
    │ 1. 保存上下文:               │                                 │
    │    saved_pc = PC             │                                 │
    │    saved_lr = LR             │                                 │
    │    saved_sp = SP             │                                 │
    │    saved_regs = R0-R12       │                                 │
    │                              │                                 │
    │ 2. 读取子域控制块:           │                                 │
    │    entry = [R0 + 0x00]       │                                 │
    │    exception = [R0 + 0x04]   │                                 │
    │                              │                                 │
    │ 3. 切换到子域:               │                                 │
    │    PC = entry ────────────────▶ 开始执行                       │
    │                              │                                 │
    │                              │ 4. 子域执行代码                 │
    │                              │    ...                          │
    │                              │    ESCALATE R0 或 RETURN        │
    │                              │                                 │
    └──────────────────────────────┴──────────────────────────────────┘

ESCALATE 流程:
==============

    子域执行 ESCALATE R0 (R0 = 服务类型):

    ┌─────────────────────────────────────────────────────────────────┐
    │ 子域 (Domain N+1)            │ 父域 (Domain N)                 │
    ├──────────────────────────────┼──────────────────────────────────┤
    │                              │                                 │
    │ 1. 保存上下文到控制块        │                                 │
    │ 2. 写入服务类型:             │                                 │
    │    [block+0x7C] = R0        │                                 │
    │ 3. 写入异常信息:             │                                 │
    │    [block+0x80] = 0x00      │ (ESCALATE 类型)                 │
    │    [block+0x84] = PC        │                                 │
    │                              │                                 │
    │ 4. 切换到父域                │                                 │
    │    ──────────────────────────▶ 5. 跳转到 exception_vector      │
    │                              │                                 │
    │                              │ 6. 处理服务请求                 │
    │                              │    读取 [child_block+0x7C]     │
    │                              │                                 │
    │                              │ 7. RETURN 返回 ────────────────┐│
    │                              │                                ││
    │ 8. 恢复上下文 ◀───────────────────────────────────────────────┘│
    │    从控制块恢复 PC, LR, SP   │                                 │
    │    继续执行                  │                                 │
    │                              │                                 │
    └──────────────────────────────┴──────────────────────────────────┘

异常传播:
=========

    子域触发异常:

    ┌─────────────────────────────────────────────────────────────────┐
    │ 子域                          │ 父域                          │
    ├───────────────────────────────┼───────────────────────────────┤
    │                               │                               │
    │ 1. 触发异常                   │                               │
    │    (缺页、非法指令等)         │                               │
    │                               │                               │
    │ 2. 检查 exception_vector      │                               │
    │    if (exception_vector == 0) │                               │
    │       → 传播到父域            │                               │
    │    else                       │                               │
    │       → 跳转到 exception_vect │                               │
    │                               │                               │
    │ 3. 保存异常信息:              │                               │
    │    [block+0x80] = 异常类型    │                               │
    │    [block+0x84] = 异常地址    │                               │
    │                               │                               │
    │ 4. ESCALATE 到父域 ───────────▶ 5. exception_vector 处理      │
    │                               │                               │
    │                               │ 6. 处理异常                   │
    │                               │    读取异常信息               │
    │                               │    执行恢复或终止             │
    │                               │                               │
    └───────────────────────────────┴───────────────────────────────┘
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
    entry_addr: int = 0            # 0x00: 入口地址
    exception_vector: int = 0      # 0x04: 异常向量
    interrupt_vector: int = 0      # 0x08: 中断向量
    interrupt_ctrl: int = 0        # 0x0C: 中断控制器
    memtable_addr: int = 0         # 0x10: 内存区域表地址

    # 保存的上下文 (硬件在 ESCALATE/异常时保存)
    saved_pc: int = 0              # 0x3C
    saved_lr: int = 0              # 0x40
    saved_sp: int = 0              # 0x44
    saved_regs: List[int] = field(default_factory=lambda: [0] * 13)
    saved_flags: int = 0           # 0x78: 保存的 CPU 条件标志 (N/Z/C/V)

    # 返回值
    return_value: int = 0          # 0x7C

    # 异常信息 (硬件在异常时写入)
    exception_type: int = 0        # 0x80
    exception_addr: int = 0        # 0x84
    exception_info: int = 0        # 0x88

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
            entry_addr=0x8000,
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

        流程:
        1. 从内存读取 DomainBlock
        2. 验证权限
        3. 创建新域
        4. 保存当前上下文
        5. 切换到子域
        6. 返回入口信息
        """
        if self.memory is None:
            raise RuntimeError("Memory not set")

        block = self._read_domain_block(block_addr)

        if not self.current_domain.block.can_descend:
            raise ValueError("Current domain cannot create child domains")

        # 创建新域
        new_id = self.current_domain.domain_id * 16 + len(self.current_domain.children) + 1
        new_domain = Domain(
            domain_id=new_id,
            block=block,
            parent=self.current_domain,
        )

        # 保存上下文
        self._save_context(self.current_domain.block)

        # 切换
        self.current_domain = new_domain
        self.domain_stack.append(new_domain)

        self.stats["descend_count"] += 1

        return {
            "entry": block.entry_addr,
            "memtable": block.memtable_addr,
            "domain_id": new_id,
        }

    def escalate(self, service_type: int) -> Any:
        """
        请求父域服务

        流程:
        1. 保存上下文到控制块
        2. 写入服务类型
        3. 切换到父域
        4. 返回父域 exception_vector
        """
        if self.current_domain.parent is None:
            raise RuntimeError("Cannot escalate from root domain")

        parent = self.current_domain.parent

        # 保存上下文
        block = self.current_domain.block
        block.return_value = service_type
        self._save_context(block)

        # 写入异常信息
        block.exception_type = 0x00  # ESCALATE
        block.exception_addr = self._get_pc()

        self.stats["escalate_count"] += 1

        # 切换到父域
        self.current_domain = parent

        return {
            "vector": parent.block.exception_vector,
            "domain_id": parent.domain_id,
            "exception_type": 0x00,
            "service_type": service_type,
        }

    def return_to_child(self, child: Domain) -> Any:
        """返回子域"""
        self._restore_context(child.block)
        self.current_domain = child
        return {
            "entry": child.block.saved_pc,
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
                entry_addr=self.memory.read_word(addr + 0x00),
                exception_vector=self.memory.read_word(addr + 0x04),
                interrupt_vector=self.memory.read_word(addr + 0x08),
                interrupt_ctrl=self.memory.read_word(addr + 0x0C),
                memtable_addr=self.memory.read_word(addr + 0x10),
            )
        return DomainBlock()

    def _write_domain_block(self, addr: int, block: DomainBlock) -> None:
        """写入 DomainBlock 到内存"""
        if self.memory:
            self.memory.write_word(addr + 0x00, block.entry_addr)
            self.memory.write_word(addr + 0x04, block.exception_vector)
            self.memory.write_word(addr + 0x08, block.interrupt_vector)
            self.memory.write_word(addr + 0x0C, block.interrupt_ctrl)
            self.memory.write_word(addr + 0x10, block.memtable_addr)

            self.memory.write_word(addr + 0x3C, block.saved_pc)
            self.memory.write_word(addr + 0x40, block.saved_lr)
            self.memory.write_word(addr + 0x44, block.saved_sp)
            for i, reg in enumerate(block.saved_regs):
                self.memory.write_word(addr + 0x48 + i * 4, reg)
            self.memory.write_word(addr + 0x78, block.saved_flags)
            self.memory.write_word(addr + 0x7C, block.return_value)

    def _save_context(self, block: DomainBlock) -> None:
        """保存执行上下文到控制块"""
        if self.core:
            block.saved_pc = self.core.state.pc
            block.saved_lr = self.core.state.lr
            block.saved_sp = self.core.state.sp
            for i in range(13):
                block.saved_regs[i] = self.core.state.get_reg(i)
            flags = 0
            if self.core.state.n:
                flags |= 1 << 31
            if self.core.state.z:
                flags |= 1 << 30
            if self.core.state.c:
                flags |= 1 << 29
            if self.core.state.v:
                flags |= 1 << 28
            block.saved_flags = flags

    def _restore_context(self, block: DomainBlock) -> None:
        """从控制块恢复执行上下文"""
        if self.core:
            self.core.state.pc = block.saved_pc
            self.core.state.lr = block.saved_lr
            self.core.state.sp = block.saved_sp
            for i in range(13):
                self.core.state.set_reg(i, block.saved_regs[i])
            flags = block.saved_flags
            self.core.state.n = bool(flags & (1 << 31))
            self.core.state.z = bool(flags & (1 << 30))
            self.core.state.c = bool(flags & (1 << 29))
            self.core.state.v = bool(flags & (1 << 28))

    def _get_pc(self) -> int:
        """获取当前 PC"""
        if self.core:
            return self.core.state.pc
        return 0

    def _handle_fault(self, fault_info: FaultInfo) -> None:
        """处理异常"""
        self.current_domain.block.exception_type = self._fault_type_to_code(fault_info.fault_type)
        self.current_domain.block.exception_addr = fault_info.address

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


# 向后兼容别名
Level = Domain
LevelConfig = DomainBlock
INHERIT = 0