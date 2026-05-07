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

DomainBlock (控制块) - RPA 通用定义:
====================================

RPA 是纯逻辑架构，不与特定 ISA 绑定。以下字段序号与位宽无关。

    ┌──────────┬────────────────────────────────────────────────────────┐
    │ 序号     │ 字段                                                   │
    ├──────────┼────────────────────────────────────────────────────────┤
    │ 0        │ ctrlblock_size      控制块大小                         │
    │ 1        │ exception_vector    异常向量 (ESCALATE 跳转地址)       │
    │ 2        │ reserved            保留                               │
    │ 3        │ interrupt_ctrl      中断控制器 handle                  │
    │ 4        │ memtable_address    内存翻译表地址                     │
    │ 5        │ domain_id           域ID (系统分配)                    │
    │ 6        │ reserved            保留                               │
    │ 7        │ child_block         子域控制块地址 (父域维护)          │
    │ 8        │ security_domain     安全域 handle                      │
    │ 9        │ access_id           访问 ID (DMA 用)                   │
    ├──────────┼────────────────────────────────────────────────────────┤
    │ ...      │ ISA Specific        ISA 特定控制字段                   │
    └──────────┴────────────────────────────────────────────────────────┘

    ctrlblock_size:
        - 必须设置，值不对时 DESCEND 会报错
        - 必须是对齐要求的倍数

    child_block:
        - 由父域维护，记录子域控制块地址
        - 用于 RETURN 指令返回子域

    interrupt_ctrl:
        - 中断控制器实例 handle
        - 通过 sysop irq, request 申请获得

DESCEND 流程:
=============

    父域执行 DESCEND R0 (R0 = 控制块地址):

    准备工作（父域负责）：
    1. 父域在控制块中设置必要字段
    2. 对于首次 DESCEND，父域必须将入口地址写入 saved_lr (0x24)

    ┌─────────────────────────────────────────────────────────────────┐
    │ RPALogic pseudo-RTL          │ Decoder (SimpleISA)             │
    ├──────────────────────────────┼──────────────────────────────────┤
    │                              │                                 │
    │ 1. 读取控制块:               │                                 │
    │    size = [R0 + 0x00]        │                                 │
    │    验证 size 对齐和范围      │                                 │
    │    exception = [R0 + 0x04]   │                                 │
    │    memtable = [R0 + 0x10]    │                                 │
    │                              │                                 │
    │ 2. 分配 domain_id:           │                                 │
    │    domain_id = next_id++     │                                 │
    │    [R0 + 0x14] = domain_id   │                                 │
    │                              │                                 │
    │ 3. 设置 parent_block:        │                                 │
    │    [R0 + 0x18] = parent_addr │                                 │
    │                              │                                 │
    │ 4. 切换到子域:               │                                 │
    │    current_domain = child    │                                 │
    │    PC = saved_lr ─────────────▶ Decoder 开始执行               │
    │                              │                                 │
    │                              │ 5. Decoder 执行代码             │
    │                              │    ...                          │
    │                              │    ESCALATE R0                  │
    │                              │                                 │
    └──────────────────────────────┴──────────────────────────────────┘

    注意：首次和后续 DESCEND 统一使用 saved_lr 作为入口点
    - 首次：父域在 DESCEND 前写入入口地址到 saved_lr
    - 后续：ESCALATE 已保存返回地址到 saved_lr

ESCALATE 流程:
==============

    子域执行 ESCALATE R0 (R0 = 服务类型):

    ┌─────────────────────────────────────────────────────────────────┐
    │ RPALogic pseudo-RTL          │ Decoder (SimpleISA)             │
    ├──────────────────────────────┼──────────────────────────────────┤
    │                              │                                 │
    │                              │ 1. Decoder 保存上下文           │
    │                              │    [block+0x20] = SP            │
    │                              │    [block+0x24] = PC+4 (返回)   │
    │                              │    [block+0x28] = PSR           │
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
from typing import Any, Optional, List, Dict, Callable, TYPE_CHECKING
from enum import Enum, auto

if TYPE_CHECKING:
    from .security_domain import SecurityDomainController


# DomainBlock 常量
CTRLBLOCK_SIZE = 32  # 当前固定大小
CTRLBLOCK_ALIGN = 32  # 对齐要求
CTRLBLOCK_MIN_SIZE = 28  # 最小有效大小

# DomainBlock 字段偏移
OFFSET_CTRLBLOCK_SIZE = 0x00
OFFSET_EXCEPTION_VECTOR = 0x04
OFFSET_RESERVED_08 = 0x08           # 保留（原 interrupt_vector）
OFFSET_INTERRUPT_CTRL = 0x0C
OFFSET_MEMTABLE_ADDRESS = 0x10
OFFSET_DOMAIN_ID = 0x14
OFFSET_RESERVED_18 = 0x18           # 保留（原 parent_block）
OFFSET_CHILD_BLOCK = 0x1C
# 安全域扩展字段
OFFSET_SECURITY_DOMAIN = 0x20       # 安全域 handle
OFFSET_ACCESS_ID = 0x24             # 访问 ID (DMA 用)

# DomainBlock 大小常量
CTRLBLOCK_BASE_SIZE = 0x28          # 基本大小 40 字节（含安全域字段）
CTRLBLOCK_SECURITY_SIZE = 0x28      # 含安全域字段 40 字节
CTRLBLOCK_ISA_CONTEXT_SIZE = 0x10   # ISA 上下文保存区 16 字节 (SP+LR+PSR+reserved)


@dataclass
class DomainBlock:
    """
    Domain 配置块 (内存结构)

    父域在内存中分配此结构，然后执行 DESCEND 使配置生效。

    大小: 40 字节 (含安全域扩展)
    对齐: 32 字节边界

    见文件头部 ASCII 图解
    """
    # 配置字段 (父域在 DESCEND 前写入)
    ctrlblock_size: int = CTRLBLOCK_SIZE   # 0x00: 控制块大小
    exception_vector: int = 0               # 0x04: 异常向量
    # 0x08: 保留（原 interrupt_vector）
    interrupt_ctrl: int = 0                 # 0x0C: 中断控制器 handle
    memtable_address: int = 0               # 0x10: 内存区域表地址
    domain_id: int = 0                      # 0x14: 域ID (系统分配)
    # 0x18: 保留（原 parent_block）
    child_block: int = 0                    # 0x1C: 子域控制块地址 (父域维护)

    # 安全域扩展字段
    security_domain: int = 0                # 0x20: 安全域 handle
    access_id: int = 0                      # 0x24: 访问 ID (DMA 用)

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

        # 安全域控制器引用
        self.security_controller: Optional['SecurityDomainController'] = None

        # 根域 (domain_id = 0)
        root_block = DomainBlock(
            ctrlblock_size=CTRLBLOCK_SIZE,
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

        # 域注册表：block_addr -> Domain（debug 用，显示域数量）
        # 注意：首次/后续 DESCEND 判断通过 child_block 字段，不依赖注册表
        self._domain_registry: Dict[int, Domain] = {0: self.root_domain}

        # 统计
        self.stats = {
            "descend_count": 0,
            "escalate_count": 0,
            "fault_count": 0,
        }

    def set_security_controller(self, controller: 'SecurityDomainController') -> None:
        """设置安全域控制器"""
        self.security_controller = controller
        # 设置 root 域的安全域
        if controller:
            self.root_domain.block.security_domain = controller.root_handle

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

        通过检查父域的 child_block 判断是否首次 DESCEND：
        - child_block == block_addr: 已有子域，RETURN 语义
        - child_block != block_addr: 首次 DESCEND，创建新域

        RPALogic pseudo-RTL 层负责:
        1. 验证 ctrlblock_size
        2. 检查 child_block 判断是否首次
        3. 首次：从内存读取 DomainBlock，创建新域对象
        4. 后续：复用已存在的域对象
        5. 切换到子域
        6. 返回入口信息

        寄存器保存由 ISA 负责（prepare_descend）

        注意：入口地址统一使用 saved_lr (0x24)
        - 首次 DESCEND：父域在 DESCEND 前写入入口地址到 saved_lr
        - 后续 DESCEND：ESCALATE 已保存返回地址到 saved_lr

        Args:
            block_addr: DomainBlock 在内存中的地址
            domain_id: 可选的域 ID（仅首次有效，用于错误归属）

        Returns:
            dict: 包含 memtable, domain_id, is_first 字段
        """
        # 验证控制块
        self._validate_ctrlblock(block_addr)

        # 通过父域的 child_block 判断是否首次 DESCEND
        # child_block 指向 block_addr 表示这是 RETURN 场景
        current_child_block = self.current_domain.block.child_block
        if current_child_block == block_addr:
            # RETURN 语义：子域已存在
            existing_domain = self._domain_registry.get(block_addr)
            if existing_domain is None:
                # 注册表中没有，但从 child_block 判断是 RETURN
                # 这种情况可能是从其他上下文恢复，需要重建 Domain 对象
                block = self._read_domain_block(block_addr)
                existing_domain = Domain(
                    domain_id=block.domain_id,
                    block=block,
                    parent=self.current_domain,
                    block_addr=block_addr,
                )
                self._domain_registry[block_addr] = existing_domain

            self.current_domain = existing_domain
            self.stats["descend_count"] += 1
            return {
                "memtable": existing_domain.block.memtable_address,
                "domain_id": existing_domain.domain_id,
                "is_first": False,  # 标记为非首次
            }

        # 检查父域是否已有其他子域（child_block 非零且不匹配）
        if current_child_block != 0 and current_child_block != block_addr:
            raise DomainBlockError(
                f"Parent domain already has child at 0x{current_child_block:x}, "
                f"cannot create new child at 0x{block_addr:x}. "
                f"Previous child domain may not have been properly released."
            )

        # 首次 DESCEND：创建新域
        block = self._read_domain_block(block_addr)

        # 读取安全域配置
        sec_domain_handle = block.security_domain

        # 分配 domain_id
        # 如果有安全域控制器，可以从安全子系统分配
        if self.security_controller and self.security_controller.enabled:
            # 从安全域获取 domain_id
            if sec_domain_handle == 0:
                # 继承父域的安全域
                sec_domain_handle = self.current_domain.block.security_domain
                # 如果父域也没有安全域，使用 root_handle
                if sec_domain_handle == 0:
                    sec_domain_handle = self.security_controller.root_handle
            # 绑定域到安全域
            if sec_domain_handle:
                self.security_controller.bind_domain(sec_domain_handle, domain_id if domain_id else self._next_domain_id)

        # 如果还没分配 domain_id，使用默认分配
        if domain_id is None:
            domain_id = self._next_domain_id
            self._next_domain_id += 1

        # 更新 Python 对象
        block.domain_id = domain_id
        block.security_domain = sec_domain_handle

        self.current_domain.block.child_block = block_addr

        # 写入内存
        if self.memory:
            self.memory.write_word(block_addr + OFFSET_DOMAIN_ID, domain_id)
            self.memory.write_word(block_addr + OFFSET_SECURITY_DOMAIN, sec_domain_handle)
            self.memory.write_word(self.current_domain.block_addr + OFFSET_CHILD_BLOCK, block_addr)

        # 绑定到安全域
        if self.security_controller and sec_domain_handle:
            self.security_controller.bind_domain(sec_domain_handle, domain_id)

        # 创建新域对象（用于错误归属）
        new_domain = Domain(
            domain_id=domain_id,
            block=block,
            parent=self.current_domain,
            block_addr=block_addr,
        )

        # 切换
        self.current_domain = new_domain

        # 注册到域注册表（debug 用）
        self._domain_registry[block_addr] = new_domain

        self.stats["descend_count"] += 1

        return {
            "memtable": block.memtable_address,
            "domain_id": domain_id,
            "is_first": True,  # 标记为首次
        }

    def escalate(self, service_type: int, release: bool = False) -> Any:
        """
        请求父域服务

        RPALogic pseudo-RTL 层只负责:
        1. 切换到父域
        2. 返回 exception_vector

        寄存器保存由 ISA 负责（complete_escalate）

        Args:
            service_type: 服务类型
            release: 是否释放子域（EXIT 语义）
        """
        if self.current_domain.parent is None:
            raise RuntimeError("Cannot escalate from root domain")

        parent = self.current_domain.parent
        child_block_addr = self.current_domain.block_addr
        child_domain_id = self.current_domain.domain_id
        child_sec_domain = self.current_domain.block.security_domain

        self.stats["escalate_count"] += 1

        if release:
            # EXIT 语义：清空父子关系
            # 更新 Python 对象
            parent.block.child_block = 0
            self.current_domain.block.domain_id = 0

            # 写入内存
            if self.memory:
                self.memory.write_word(parent.block_addr + OFFSET_CHILD_BLOCK, 0)
                self.memory.write_word(child_block_addr + OFFSET_DOMAIN_ID, 0)

            # 解绑安全域
            if self.security_controller and child_sec_domain:
                self.security_controller.unbind_domain(child_sec_domain, child_domain_id)

            # 从注册表移除子域
            if child_block_addr in self._domain_registry:
                del self._domain_registry[child_block_addr]

        # 切换到父域
        self.current_domain = parent

        return {
            "vector": parent.block.exception_vector,
            "domain_id": parent.domain_id,
            "child_block_addr": 0 if release else child_block_addr,
            "released": release,
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
                ctrlblock_size=self.memory.read_word(addr + OFFSET_CTRLBLOCK_SIZE),
                exception_vector=self.memory.read_word(addr + OFFSET_EXCEPTION_VECTOR),
                # 0x08 保留
                interrupt_ctrl=self.memory.read_word(addr + OFFSET_INTERRUPT_CTRL),
                memtable_address=self.memory.read_word(addr + OFFSET_MEMTABLE_ADDRESS),
                domain_id=self.memory.read_word(addr + OFFSET_DOMAIN_ID),
                # 0x18 保留（原 parent_block）
                child_block=self.memory.read_word(addr + OFFSET_CHILD_BLOCK),
                security_domain=self.memory.read_word(addr + OFFSET_SECURITY_DOMAIN),
                access_id=self.memory.read_word(addr + OFFSET_ACCESS_ID),
            )
        return DomainBlock()

    def _write_domain_block(self, addr: int, block: DomainBlock) -> None:
        """写入 DomainBlock 到内存"""
        if self.memory:
            self.memory.write_word(addr + OFFSET_CTRLBLOCK_SIZE, block.ctrlblock_size)
            self.memory.write_word(addr + OFFSET_EXCEPTION_VECTOR, block.exception_vector)
            # 0x08 保留
            self.memory.write_word(addr + OFFSET_INTERRUPT_CTRL, block.interrupt_ctrl)
            self.memory.write_word(addr + OFFSET_MEMTABLE_ADDRESS, block.memtable_address)
            self.memory.write_word(addr + OFFSET_DOMAIN_ID, block.domain_id)
            # 0x18 保留（原 parent_block）
            self.memory.write_word(addr + OFFSET_CHILD_BLOCK, block.child_block)
            self.memory.write_word(addr + OFFSET_SECURITY_DOMAIN, block.security_domain)
            self.memory.write_word(addr + OFFSET_ACCESS_ID, block.access_id)

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