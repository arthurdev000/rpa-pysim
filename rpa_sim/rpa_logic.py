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
    │                     (32 字节, 32字节对齐)                      │
    ├────────────┬───────────────────────────────────────────────────┤
    │ 偏移       │ 字段                                              │
    ├────────────┼───────────────────────────────────────────────────┤
    │ 0x00       │ ctrlblock_size      控制块大小 (含自身)           │
    │ 0x04       │ execution_address   执行地址                      │
    │ 0x08       │ exception_vector    异常向量                      │
    │ 0x0C       │ interrupt_vector    中断向量                      │
    │ 0x10       │ interrupt_ctrl      中断控制器                    │
    │ 0x14       │ memtable_address    内存区域表地址                │
    │ 0x18       │ domain_id           域ID (系统分配，调试用)       │
    │ 0x1C       │ parent_block        父域控制块地址 (可选)         │
    └────────────┴───────────────────────────────────────────────────┘

    ctrlblock_size 说明:
    - 必须设置，值不对时 DESCEND 会报错
    - 最小值: 28 bytes (所有 RPA 字段)
    - 当前实现固定为 32 bytes
    - 必须是 32 的倍数

DESCEND 流程:
=============

    父域执行 DESCEND R0 (R0 = 控制块地址):

    ┌─────────────────────────────────────────────────────────────────┐
    │ RPALogic pseudo-RTL          │ Decoder (SimpleISA)             │
    ├──────────────────────────────┼──────────────────────────────────┤
    │                              │                                 │
    │ 1. 读取控制块:               │                                 │
    │    size = [R0 + 0x00]        │                                 │
    │    验证 size 对齐和范围      │                                 │
    │    entry = [R0 + 0x04]       │                                 │
    │    exception = [R0 + 0x08]   │                                 │
    │    memtable = [R0 + 0x14]    │                                 │
    │                              │                                 │
    │ 2. 分配 domain_id:           │                                 │
    │    domain_id = next_id++     │                                 │
    │    [R0 + 0x18] = domain_id   │                                 │
    │                              │                                 │
    │ 3. 切换到子域:               │                                 │
    │    current_domain = child    │                                 │
    │    PC = entry ────────────────▶ Decoder 开始执行               │
    │                              │                                 │
    │                              │ 4. Decoder 执行代码             │
    │                              │    ...                          │
    │                              │    ESCALATE R0                  │
    │                              │                                 │
    └──────────────────────────────┴──────────────────────────────────┘

ESCALATE 流程:
==============

    子域执行 ESCALATE R0 (R0 = 服务类型):

    ┌─────────────────────────────────────────────────────────────────┐
    │ RPALogic pseudo-RTL          │ Decoder (SimpleISA)             │
    ├──────────────────────────────┼──────────────────────────────────┤
    │                              │                                 │
    │                              │ 1. Decoder 保存上下文           │
    │                              │    (寄存器状态由 Decoder 管理)  │
    │                              │                                 │
    │ 2. 切换到父域:               │                                 │
    │    current_domain = parent   │                                 │
    │    PC = parent.exception_vec ─▶ Decoder 跳转到处理程序         │
    │                              │                                 │
    │                              │ 3. Decoder 处理请求             │
    │                              │    读取状态、执行服务           │
    │                              │                                 │
    │                              │ 4. RETURN 返回                  │
    │                              │                                 │
    └──────────────────────────────┴──────────────────────────────────┘

异常传播:
=========

    子域触发异常:

    ┌─────────────────────────────────────────────────────────────────┐
    │ RPALogic pseudo-RTL          │ Decoder (SimpleISA)             │
    ├──────────────────────────────┼──────────────────────────────────┤
    │                              │                                 │
    │                              │ 1. Decoder 检测到异常           │
    │                              │    (缺页、非法指令等)           │
    │                              │                                 │
    │ 2. 检查 exception_vector     │                                 │
    │    if (== 0) → 传播到父域    │                                 │
    │    else → 跳转处理           │                                 │
    │                              │                                 │
    │ 3. 切换到父域                │                                 │
    │    ───────────────────────────▶ 4. Decoder 异常处理            │
    │                              │                                 │
    └──────────────────────────────┴──────────────────────────────────┘
"""

from dataclasses import dataclass, field
from typing import Any, Optional, List, Dict, Callable
from enum import Enum, auto


# DomainBlock 常量
CTRLBLOCK_SIZE = 32  # 当前固定大小
CTRLBLOCK_ALIGN = 32  # 对齐要求
CTRLBLOCK_MIN_SIZE = 28  # 最小有效大小


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

    大小: 32 字节
    对齐: 32 字节边界

    见文件头部 ASCII 图解
    """
    # 配置字段 (父域在 DESCEND 前写入)
    ctrlblock_size: int = CTRLBLOCK_SIZE   # 0x00: 控制块大小
    execution_address: int = 0              # 0x04: 执行地址
    exception_vector: int = 0               # 0x08: 异常向量
    interrupt_vector: int = 0               # 0x0C: 中断向量
    interrupt_ctrl: int = 0                 # 0x10: 中断控制器
    memtable_address: int = 0               # 0x14: 内存区域表地址
    domain_id: int = 0                      # 0x18: 域ID (系统分配)
    parent_block: int = 0                   # 0x1C: 父域控制块地址 (可选)

    # 向后兼容字段
    params: Dict[str, Any] = field(default_factory=dict)
    program: Dict[str, Any] = field(default_factory=dict)
    sub_index: int = 0


@dataclass
class Domain:
    """
    特权域

    每核心每特权层只有一个 DomainBlock。
    parent 用于错误归属（查找哪层页表出错）。

    Domain 对象在 DESCEND 时动态创建，ESCALATE 时切换回 parent。
    """
    domain_id: int
    block: DomainBlock
    parent: Optional['Domain'] = None
    block_addr: int = 0  # DomainBlock 在内存中的地址


@dataclass
class FaultInfo:
    """异常信息"""
    fault_type: str
    domain: int
    address: int = 0


class DomainBlockError(Exception):
    """DomainBlock 验证错误"""
    pass


class RPALogic:
    """
    RPA 逻辑控制器 - 域管理

    每核心每特权层只有一个 DomainBlock。
    硬件只维护 current_domain，通过 parent 链向上查找。

    - descend(): 进入子域（创建新的 Domain 对象）
    - escalate(): 返回父域
    - fault(): 触发异常
    """

    def __init__(self):
        # 域ID分配器
        self._next_domain_id = 1

        # 根域 (domain_id = 0)
        root_block = DomainBlock(
            ctrlblock_size=CTRLBLOCK_SIZE,
            execution_address=0x8000,
            exception_vector=0x8004,
            domain_id=0,
        )
        self.root_domain: Domain = Domain(domain_id=0, block=root_block)

        # 当前执行域
        self.current_domain: Domain = self.root_domain

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

    def _validate_ctrlblock(self, addr: int) -> None:
        """验证控制块大小和对齐"""
        if self.memory is None:
            raise RuntimeError("Memory not set")

        # 检查对齐
        if addr % CTRLBLOCK_ALIGN != 0:
            raise DomainBlockError(
                f"DomainBlock at 0x{addr:x} not aligned to {CTRLBLOCK_ALIGN} bytes"
            )

        # 读取大小字段
        size = self.memory.read_word(addr + 0x00)

        # 检查大小有效性
        if size < CTRLBLOCK_MIN_SIZE:
            raise DomainBlockError(
                f"DomainBlock size {size} too small (minimum {CTRLBLOCK_MIN_SIZE})"
            )

        if size % CTRLBLOCK_ALIGN != 0:
            raise DomainBlockError(
                f"DomainBlock size {size} not aligned to {CTRLBLOCK_ALIGN} bytes"
            )

    def descend(self, block_addr: int, domain_id: Optional[int] = None) -> Any:
        """
        进入子域

        RPALogic pseudo-RTL 层负责:
        1. 验证 ctrlblock_size
        2. 从内存读取 DomainBlock
        3. 分配 domain_id
        4. 创建新域对象（用于错误归属）
        5. 切换到子域
        6. 返回入口信息

        寄存器保存由 ISA 负责（prepare_descend）

        Args:
            block_addr: DomainBlock 在内存中的地址
            domain_id: 可选的域 ID（由软件指定，用于错误归属）
        """
        # 验证控制块
        self._validate_ctrlblock(block_addr)

        block = self._read_domain_block(block_addr)

        # 分配 domain_id
        if domain_id is None:
            domain_id = self._next_domain_id
            self._next_domain_id += 1

        # 写入 domain_id 到控制块
        block.domain_id = domain_id
        if self.memory:
            self.memory.write_word(block_addr + 0x18, domain_id)

        # 创建新域对象（用于错误归属）
        new_domain = Domain(
            domain_id=domain_id,
            block=block,
            parent=self.current_domain,
            block_addr=block_addr,
        )

        # 切换
        self.current_domain = new_domain

        self.stats["descend_count"] += 1

        return {
            "execution_address": block.execution_address,
            "memtable": block.memtable_address,
            "domain_id": domain_id,
        }

    def escalate(self, service_type: int) -> Any:
        """
        请求父域服务

        RPALogic pseudo-RTL 层只负责:
        1. 切换到父域
        2. 返回 exception_vector

        寄存器保存由 ISA 负责（complete_escalate）
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

    def fault(self, fault_type: str, address: int = 0) -> None:
        """触发异常"""
        fault_info = FaultInfo(
            fault_type=fault_type,
            domain=self.current_domain.domain_id,
            address=address,
        )

        self.stats["fault_count"] += 1

        if self.current_domain.block.exception_vector != 0:
            self._handle_fault(fault_info)
        else:
            self._propagate_fault(fault_info)

    def get_depth(self) -> int:
        """获取当前域深度（通过 parent 链计算）"""
        depth = 0
        domain = self.current_domain
        while domain.parent is not None:
            depth += 1
            domain = domain.parent
        return depth

    def get_stats(self) -> Dict[str, int]:
        """获取统计信息"""
        return self.stats.copy()

    def _read_domain_block(self, addr: int) -> DomainBlock:
        """从内存读取 DomainBlock"""
        if self.memory:
            return DomainBlock(
                ctrlblock_size=self.memory.read_word(addr + 0x00),
                execution_address=self.memory.read_word(addr + 0x04),
                exception_vector=self.memory.read_word(addr + 0x08),
                interrupt_vector=self.memory.read_word(addr + 0x0C),
                interrupt_ctrl=self.memory.read_word(addr + 0x10),
                memtable_address=self.memory.read_word(addr + 0x14),
                domain_id=self.memory.read_word(addr + 0x18),
                parent_block=self.memory.read_word(addr + 0x1C),
            )
        return DomainBlock()

    def _write_domain_block(self, addr: int, block: DomainBlock) -> None:
        """写入 DomainBlock 到内存"""
        if self.memory:
            self.memory.write_word(addr + 0x00, block.ctrlblock_size)
            self.memory.write_word(addr + 0x04, block.execution_address)
            self.memory.write_word(addr + 0x08, block.exception_vector)
            self.memory.write_word(addr + 0x0C, block.interrupt_vector)
            self.memory.write_word(addr + 0x10, block.interrupt_ctrl)
            self.memory.write_word(addr + 0x14, block.memtable_address)
            self.memory.write_word(addr + 0x18, block.domain_id)
            self.memory.write_word(addr + 0x1C, block.parent_block)

    def _get_pc(self) -> int:
        """获取当前 PC"""
        if self.core:
            return self.core.state.pc
        return 0

    def _handle_fault(self, fault_info: FaultInfo) -> None:
        """处理异常"""
        handler = self.exception_handlers.get(fault_info.fault_type)
        if handler:
            handler(fault_info)
        else:
            self._propagate_fault(fault_info)

    def _propagate_fault(self, fault_info: FaultInfo) -> None:
        """传播异常到父域"""
        if self.current_domain.parent is None:
            raise RuntimeError(f"Unhandled fault at root: {fault_info}")

        # escalate() 会切换到父域并返回 exception_vector
        # 由 Decoder 负责跳转到 exception_vector 执行处理程序
        self.escalate(0x01)  # FAULT 类型

    def _fault_type_to_code(self, fault_type: str) -> int:
        """转换异常类型到代码"""
        codes = {
            "escalate": 0x00,
            "page_fault": 0x01,
            "illegal_instruction": 0x02,
            "privilege_violation": 0x03,
        }
        return codes.get(fault_type, 0xFF)