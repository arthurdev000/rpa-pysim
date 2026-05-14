"""
RPA Core - Domain management and privilege primitives

实现递归特权架构的核心原语：
- descend(): 进入子域
- ascend(): 请求父域服务
- Domain: 特权域管理
- DomainBlock: 内存控制块结构

Domain 层级结构与 DCB 关系:
============================

    ┌──────────────────────────────────────────────────────────────────────────┐
    │                           RPA Domain 层级                                 │
    │                                                                          │
    │   每个 Domain 有一个 DCB (Domain Control Block)，由父域在内存中创建。     │
    │   DCB 存储域的配置、状态和与子域的连接信息。                              │
    ├──────────────────────────────────────────────────────────────────────────┤
    │                                                                          │
    │  ┌─────────────────────────────────────────────────────────────────┐    │
    │  │ DCB 0 (根域控制块)              │ Domain 0 (根域)                │    │
    │  │ ┌─────────────────────────────┐ │  - 特权级: 0                   │    │
    │  │ │ ctrlblock_size = 8+         │ │  - 拥有物理内存                │    │
    │  │ │ domain_id     = 0           │ │  - 处理 Domain 1 的 ASCEND   │    │
    │  │ │ trap_vector   = handler0    │ │                                │    │
    │  │ │ ipa_regions   = 物理内存表   │ │  trap_vector → ASCEND 处理  │    │
    │  │ │ pagetable     = 根页表      │ │                                │    │
    │  │ │ child_block   ───────────────────────┐                       │    │
    │  │ │ security_group = ...       │ │     │ │                       │    │
    │  │ └─────────────────────────────┘ │     │ └────────────────────────┘    │
    │  └─────────────────────────────────│─────│───────────────────────────────┘
    │                                    │     │    child_block 指向子域 DCB
    │                                    ▼     │
    │  ┌─────────────────────────────────────────────────────────────────┐    │
    │  │ DCB 1 (子域控制块)              │ Domain 1 (子域)                │    │
    │  │ ┌─────────────────────────────┐ │  - 特权级: 1                   │    │
    │  │ │ ctrlblock_size = 8+         │ │  - 拥有虚拟内存 (IPA)          │    │
    │  │ │ domain_id     = 1           │ │  - 处理 Domain 2 的 ASCEND   │    │
    │  │ │ trap_vector   = handler1 ◀──│─│─── ASCEND 跳转目标          │    │
    │  │ │ ipa_regions   = IPA 约束表   │ │                                │    │
    │  │ │ pagetable     = 子域页表    │ │  ipa_regions ← 父域设置       │    │
    │  │ │ child_block   ───────────────────────┐                       │    │
    │  │ │ security_group = ...       │ │     │ │                       │    │
    │  │ └─────────────────────────────┘ │     │ └────────────────────────┘    │
    │  └─────────────────────────────────│─────│───────────────────────────────┘
    │                                    │     │
    │                                    ▼     │
    │  ┌─────────────────────────────────────────────────────────────────┐    │
    │  │ DCB 2 (孙域控制块)              │ Domain 2 (孙域)                │    │
    │  │ ┌─────────────────────────────┐ │  - 特权级: 2                   │    │
    │  │ │ ctrlblock_size = 8+         │ │  - 最受限的地址空间            │    │
    │  │ │ domain_id     = 2           │ │                                │    │
    │  │ │ trap_vector   = 0 ──────────│─│─── 0 表示 Trap 传播到父域      │    │
    │  │ │ ipa_regions   = IPA 约束表   │ │                                │    │
    │  │ │ pagetable     = 孙域页表    │ │  trap_vector=0 → 父域处理     │    │
    │  │ │ child_block   = 0           │ │  (无子域)                       │    │
    │  │ │ security_group = ...       │ │                                │    │
    │  │ └─────────────────────────────┘ │                                │    │
    │  └─────────────────────────────────┴────────────────────────────────┘    │
    │                                                                          │
    ├──────────────────────────────────────────────────────────────────────────┤
    │  指令流程:                                                               │
    │                                                                          │
    │  DESCEND: 父域 → 子域                                                    │
    │    - 父域准备 DCB，设置 ipa_regions, ctrlblock_size                     │
    │    - 父域写入入口地址到 saved_lr (ISA Context 字段)                      │
    │    - 硬件切换 current_domain，PC ← saved_lr                              │
    │                                                                          │
    │  ASCEND: 子域 → 父域 (请求服务)                                        │
    │    - 子域调用 ASCEND，ISA 保存 SP/LR/PSR 到 DCB                        │
    │    - 硬件切换到父域，PC ← 父域的 trap_vector                             │
    │    - 若 trap_vector=0，继续传播到更上层                                  │
    │                                                                          │
    │  RETURN: 父域 → 子域 (服务完成)                                          │
    │    - 父域调用 RETURN，从 child_block 定位子域 DCB                        │
    │    - 硬件切换到子域，恢复 SP/LR/PSR                                      │
    │                                                                          │
    └──────────────────────────────────────────────────────────────────────────┘

DCB 三段式布局:
===============

    ┌─────────────────────────────────────────────────────────────────┐
    │ RPA Spec Field (固定 8 words)                                   │
    │   由 RPA 架构规范定义，跨平台统一                               │
    │   偏移 0x00 - 0x1C                                              │
    ├─────────────────────────────────────────────────────────────────┤
    │ RPA Impdef Field (可变)                                         │
    │   大小：ctrlblock_size - 8 words                                │
    │   内容：平台特定扩展字段                                        │
    │   访问：软件用 SYSOP，RTL 直接访问                              │
    ├─────────────────────────────────────────────────────────────────┤
    │ ISA Context Field (可变)                                        │
    │   大小：由 ISA 规范定义                                         │
    │   内容：saved_sp, saved_lr, saved_psr, 中断现场等               │
    └─────────────────────────────────────────────────────────────────┘

RPA Spec Field 字段布局（32 位系统为 32 字节）：

    ┌──────────┬────────────────────────────────────────────────────────┐
    │ 偏移     │ 字段                                                   │
    ├──────────┼────────────────────────────────────────────────────────┤
    │ 0x00     │ ctrlblock_size      控制块大小 (单位: word, 父域设置)  │
    │ 0x04     │ domain_id           域ID (系统分配，用于 DMA 访问控制) │
    ├──────────┼────────────────────────────────────────────────────────┤
    │ 0x08     │ trap_vector         Trap 处理入口 (子域设置，0=传播)   │
    ├──────────┼────────────────────────────────────────────────────────┤
    │ 0x0C     │ interrupt_ctrl      中断控制器 handle (系统分配)       │
    ├──────────┼────────────────────────────────────────────────────────┤
    │ 0x10     │ ipa_regions         IPA 区域表地址 (父域设置，只读)    │
    │ 0x14     │ pagetable           页表地址 (子域设置，可写)          │
    ├──────────┼────────────────────────────────────────────────────────┤
    │ 0x18     │ child_block         子域控制块地址 (父域维护)          │
    ├──────────┼────────────────────────────────────────────────────────┤
    │ 0x1C     │ security_group     安全组 handle (系统分配)           │
    └──────────┴────────────────────────────────────────────────────────┘

字段设置者：
    父域设置：ctrlblock_size, ipa_regions, child_block
    子域设置：trap_vector, pagetable
    系统分配：domain_id, interrupt_ctrl, security_group

字段说明：
    ctrlblock_size:
        - 控制块大小，单位为 word
        - 最小值：8 words（RPA Spec Field）
        - 对齐：8 words
        - DESCEND 时硬件验证

    domain_id:
        - 系统分配的唯一标识符
        - DMA 访问控制使用此 ID

    trap_vector:
        - 子域设置的 Trap 处理入口
        - 为 0 时 Trap 传播到父域
        - 用于 ASCEND、FAULT 等同步事件

    interrupt_ctrl:
        - 中断控制器实例 handle
        - 通过 sysop irq, request 申请获得

    ipa_regions:
        - 父域设置的 IPA 范围约束
        - 子域只读，通过 SYSOP 查询
        - 定义子域可用的地址空间范围

    pagetable:
        - 子域创建的 VA→IPA 页表地址
        - 子域可写，用于建立自己的地址映射
        - 硬件翻译时检查 IPA 是否在 ipa_regions 范围内

    child_block:
        - 由父域维护，记录子域控制块地址
        - 用于首次/后续 DESCEND 判断
        - 用于 RETURN 指令返回子域

    security_group:
        - 安全组 handle，用于内存隔离和加密
        - 系统分配，绑定域到安全组

DESCEND 流程:
=============

    父域执行 DESCEND R0 (R0 = 子域控制块地址):

    准备工作（父域负责）：
    1. 父域在控制块中设置必要字段
    2. 对于首次 DESCEND，父域必须将入口地址写入 saved_lr (0x28)

    ┌──────────────────────────────────────────────────────────────────────────┐
    │                        DESCEND 执行流程                                  │
    ├──────────────────────────────────────────────────────────────────────────┤
    │                                                                          │
    │  父域 DCB (在父域地址空间)           子域 DCB (R0 指向，在父域地址空间)  │
    │  ┌─────────────────────┐            ┌─────────────────────┐             │
    │  │ child_block ────────│───────────▶│ 0x00 ctrlblock_size │← 父域设置   │
    │  │ ...                 │            │ 0x04 domain_id      │← 系统分配   │
    │  │ trap_vector = hdlr  │            │ 0x08 trap_vector    │← 子域设置   │
    │  │ ...                 │            │ 0x10 ipa_regions    │← 父域设置   │
    │  └─────────────────────┘            │ 0x14 pagetable      │← 子域设置   │
    │                                      │ 0x18 child_block    │← 父域维护   │
    │                                      │ 0x28 saved_lr       │← 入口地址   │
    │                                      └─────────────────────┘             │
    │                                                                          │
    │  RPALogic pseudo-RTL:                                                    │
    │  ────────────────────                                                    │
    │  1. 读取 DCB 验证：size = [R0+0x00], 检查对齐和范围                     │
    │  2. 分配 domain_id: [R0+0x04] = next_id++                               │
    │  3. 记录父子关系: 父域.child_block = R0                                 │
    │  4. 切换到子域: current_domain = child                                  │
    │  5. 跳转执行: PC = [R0+0x28] (saved_lr)                                 │
    │                                                                          │
    │  Decoder (SimpleISA):                                                    │
    │  ────────────────────                                                    │
    │  6. 从 saved_lr 开始执行子域代码                                        │
    │     ... 子域运行 ...                                                    │
    │     ASCEND R0  ← 子域请求父域服务                                     │
    │                                                                          │
    └──────────────────────────────────────────────────────────────────────────┘

    注意：首次和后续 DESCEND 统一使用 saved_lr 作为入口点
    - 首次：父域在 DESCEND 前写入入口地址到 saved_lr
    - 后续：ASCEND 已保存返回地址到 saved_lr

ASCEND 流程:
==============

    子域执行 ASCEND R0 (R0 = 服务类型):

    ┌──────────────────────────────────────────────────────────────────────────┐
    │                        ASCEND 执行流程                                 │
    ├──────────────────────────────────────────────────────────────────────────┤
    │                                                                          │
    │  子域 DCB                              父域 DCB                          │
    │  ┌─────────────────────┐             ┌─────────────────────┐            │
    │  │ 0x08 trap_vector = 0│──┐          │ 0x08 trap_vector    │            │
    │  │ ...                 │  │          │ ...                 │            │
    │  │ 0x28 saved_sp ◀─────│──│──┐       │ 0x18 child_block ───│──┐         │
    │  │ 0x2C saved_lr ◀─────│──│──│──┐    └─────────────────────┘  │         │
    │  │ 0x30 saved_psr ◀────│──│──│──│──┐                          │         │
    │  └─────────────────────┘  │  │  │  │                          │         │
    │                           │  │  │  │                          ▼         │
    │   保存上下文到子域 DCB ◀──┘  │  │  │             指向子域 DCB ─┘         │
    │                              │  │  │                                     │
    │   trap_vector = 0? ──────────┘  │  │                                     │
    │     是 → 传播到祖父域            │  │                                     │
    │     否 → 跳转到父域处理 ─────────┘  │                                     │
    │                                    ▼                                     │
    │                           PC ← trap_vector                               │
    │                                                                          │
    │  RPALogic pseudo-RTL:                                                    │
    │  ────────────────────                                                    │
    │  1. 保存子域上下文: [DCB+0x28]=SP, [DCB+0x2C]=PC+4, [DCB+0x30]=PSR      │
    │  2. 切换到父域: current_domain = parent                                  │
    │  3. 检查父域 trap_vector:                                                │
    │     - 若 = 0: 继续传播到祖父域（递归）                                   │
    │     - 若 ≠ 0: PC = trap_vector                                          │
    │                                                                          │
    │  Decoder (SimpleISA):                                                    │
    │  ────────────────────                                                    │
    │  4. 跳转到 trap_vector 处理程序                                         │
    │     ... 处理服务请求 ...                                                 │
    │     RETURN  ← 返回子域                                                   │
    │                                                                          │
    └──────────────────────────────────────────────────────────────────────────┘

Trap 传播机制:
==============

    子域触发 Trap (异常、ASCEND 等):

    ┌──────────────────────────────────────────────────────────────────────────┐
    │                        Trap 传播决策树                                   │
    ├──────────────────────────────────────────────────────────────────────────┤
    │                                                                          │
    │  子域发生 Trap                                                           │
    │       │                                                                  │
    │       ▼                                                                  │
    │  ┌─────────────────┐                                                    │
    │  │ 检查 trap_vector │                                                    │
    │  │ [DCB + 0x08]    │                                                    │
    │  └────────┬────────┘                                                    │
    │           │                                                              │
    │     ┌─────┴─────┐                                                       │
    │     ▼           ▼                                                       │
    │  = 0          ≠ 0                                                       │
    │     │           │                                                       │
    │     ▼           ▼                                                       │
    │ ┌───────────┐ ┌──────────────────┐                                     │
    │ │传播到父域 │ │跳转到 trap_vector│                                     │
    │ │(递归检查) │ │[DCB+0x08] → PC  │                                     │
    │ └───────────┘ └──────────────────┘                                     │
    │     │                                                                   │
    │     ▼                                                                   │
    │  父域 trap_vector = 0?                                                  │
    │     │                                                                   │
    │    ... 继续传播 ...                                                     │
    │     │                                                                   │
    │     ▼                                                                   │
    │  根域处理 (必须处理所有 Trap)                                           │
    │                                                                          │
    │  说明:                                                                   │
    │  - trap_vector = 0 表示子域不处理此 Trap，委托给父域                    │
    │  - 根域的 trap_vector 不能为 0，作为最终处理者                          │
    │  - ASCEND 也遵循此机制，但 R0 传递服务类型                            │
    │                                                                          │
    └──────────────────────────────────────────────────────────────────────────┘
"""

from dataclasses import dataclass, field
from typing import Any, Optional, List, Dict, Callable, TYPE_CHECKING
from enum import Enum, auto

if TYPE_CHECKING:
    from .security_group import SecurityGroupController


# DomainBlock 常量
# 单位：word（目标平台的原生字长）
# 32 位系统：word = 4 字节，RPA Spec Field = 32 字节
CTRLBLOCK_WORDS = 8       # RPA Spec Field 字数（固定）
CTRLBLOCK_ALIGN_WORDS = 8 # 对齐要求（word 数量）
CTRLBLOCK_MIN_WORDS = 8   # 最小有效大小（word 数量）

# 字节单位常量（32 位系统，内部实现用）
WORD_SIZE = 4  # 32 位系统
CTRLBLOCK_SIZE = CTRLBLOCK_WORDS * WORD_SIZE
CTRLBLOCK_ALIGN = CTRLBLOCK_ALIGN_WORDS * WORD_SIZE
CTRLBLOCK_MIN_SIZE = CTRLBLOCK_MIN_WORDS * WORD_SIZE

# DomainBlock 字段偏移（新布局）
# 偏移  字段              设置者    用途
# 0x00  ctrlblock_size   父域     控制块大小（单位：word）
# 0x04  domain_id        系统     域标识（DMA 访问控制使用此 ID）
# 0x08  trap_vector      子域     Trap 处理入口（0 = 传播到父域）
# 0x0C  interrupt_ctrl   系统     中断控制器 handle
# 0x10  ipa_regions      父域     IPA 区域表地址（父域设置，子域只读）
# 0x14  pagetable        子域     页表地址（子域设置，可写）
# 0x18  child_block      父域     子域控制块地址（父域维护）
# 0x1C  security_group  系统     安全组 handle
OFFSET_CTRLBLOCK_SIZE = 0x00
OFFSET_DOMAIN_ID = 0x04
OFFSET_TRAP_VECTOR = 0x08
OFFSET_INTERRUPT_CTRL = 0x0C
OFFSET_IPA_REGIONS = 0x10
OFFSET_PAGETABLE = 0x14
OFFSET_CHILD_BLOCK = 0x18
OFFSET_SECURITY_GROUP = 0x1C

# DomainBlock 大小常量
CTRLBLOCK_BASE_SIZE = 0x20          # 基本大小 32 字节
CTRLBLOCK_ISA_CONTEXT_SIZE = 0x10   # ISA 上下文保存区 16 字节 (SP+LR+PSR+reserved)

# IPA 区域表 / 页表条目格式
# 每个条目 12 字节: base(4) + size(4) + attr(4)
# 结束标记: base=0, size=0, attr=0 (全零条目)
TABLE_ENTRY_SIZE = 12
TABLE_ENTRY_BASE_OFFSET = 0
TABLE_ENTRY_SIZE_OFFSET = 4
TABLE_ENTRY_ATTR_OFFSET = 8
TABLE_END_MARKER = (0, 0, 0)        # (base=0, size=0, attr=0)


@dataclass
class DomainBlock:
    """
    Domain 配置块 (内存结构)

    父域在内存中分配此结构，然后执行 DESCEND 使配置生效。

    结构布局（三段式）：
    ┌─────────────────────────────────────────────────────────────┐
    │ RPA Spec Field (固定 8 words)                              │
    │   由 RPA 架构规范定义，跨平台统一                           │
    │   字段：ctrlblock_size, domain_id, trap_vector,            │
    │         interrupt_ctrl, ipa_regions, pagetable,            │
    │         child_block, security_group                       │
    ├─────────────────────────────────────────────────────────────┤
    │ RPA Impdef Field (可变)                                    │
    │   大小：ctrlblock_size - 8 words                           │
    │   内容：trap_delegate、中断控制器状态、平台扩展             │
    │   访问：软件用 SYSOP，RTL 直接访问                          │
    ├─────────────────────────────────────────────────────────────┤
    │ ISA Context Field (可变)                                   │
    │   大小：由 ISA 规范定义                                     │
    │   内容：通用寄存器、状态寄存器、扩展寄存器                   │
    └─────────────────────────────────────────────────────────────┘

    字段布局（RPA Spec Field）：
    偏移  字段              设置者    用途
    0x00  ctrlblock_size   父域     控制块大小（单位：word）
    0x04  domain_id        系统     域标识
    0x08  trap_vector      子域     Trap 处理入口（0 = 传播到父域）
    0x0C  interrupt_ctrl   系统     中断控制器 handle
    0x10  ipa_regions      父域     IPA 区域表地址（只读）
    0x14  pagetable        子域     页表地址（可写）
    0x18  child_block      父域     子域控制块地址
    0x1C  security_group  系统     安全组 handle

    见文件头部 ASCII 图解
    """
    # 基本字段
    ctrlblock_size: int = CTRLBLOCK_WORDS  # 0x00: 控制块大小（单位：word，默认 8）
    domain_id: int = 0                      # 0x04: 域ID（系统分配，DMA 访问控制使用此 ID）
    trap_vector: int = 0                    # 0x08: Trap 处理入口（子域设置，0 = 传播到父域）
    interrupt_ctrl: int = 0                 # 0x0C: 中断控制器 handle（系统分配）
    ipa_regions: int = 0                    # 0x10: IPA 区域表地址（父域设置，子域只读）
    pagetable: int = 0                      # 0x14: 页表地址（子域设置，可写）
    child_block: int = 0                    # 0x18: 子域控制块地址（父域维护）
    security_group: int = 0                # 0x1C: 安全组 handle（系统分配）

    # 向后兼容字段（不存储在内存中）
    params: Dict[str, Any] = field(default_factory=dict)
    program: Dict[str, Any] = field(default_factory=dict)
    sub_index: int = 0


@dataclass
class Domain:
    """
    特权域

    每核心每特权层只有一个 DomainBlock。
    parent 用于错误归属（查找哪层页表出错）。

    Domain 对象在 DESCEND 时动态创建，ASCEND 时切换回 parent。
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
    - ascend(): 返回父域
    - fault(): 触发异常
    """

    def __init__(self):
        # 域ID分配器
        self._next_domain_id = 1

        # 安全组控制器引用
        self.security_controller: Optional['SecurityGroupController'] = None

        # 根域 (domain_id = 0)
        root_block = DomainBlock(
            ctrlblock_size=CTRLBLOCK_WORDS,
            trap_vector=0x8004,
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
            "ascend_count": 0,
            "fault_count": 0,
        }

    def set_security_controller(self, controller: 'SecurityGroupController') -> None:
        """设置安全组控制器"""
        self.security_controller = controller
        # 设置 root 域的安全组
        if controller:
            self.root_domain.block.security_group = controller.root_handle

    def _validate_ctrlblock(self, addr: int) -> None:
        """验证控制块大小和对齐

        ctrlblock_size 单位为 word：
        - 最小值：8 words（RPA Spec Field）
        - 对齐：8 words（目标平台）
        """
        if self.memory is None:
            raise RuntimeError("Memory not set")

        # 检查地址对齐（8 words = 32 字节在 32 位系统）
        if addr % CTRLBLOCK_ALIGN != 0:
            raise DomainBlockError(
                f"DomainBlock at 0x{addr:x} not aligned to {CTRLBLOCK_ALIGN_WORDS} words"
            )

        # 读取大小字段（单位：word）
        size_words = self.memory.read_word(addr + 0x00)

        # 检查大小有效性（最小 8 words）
        if size_words < CTRLBLOCK_MIN_WORDS:
            raise DomainBlockError(
                f"DomainBlock size {size_words} words too small (minimum {CTRLBLOCK_MIN_WORDS} words)"
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
        - 后续 DESCEND：ASCEND 已保存返回地址到 saved_lr

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
                "pagetable": existing_domain.block.pagetable,
                "ipa_regions": existing_domain.block.ipa_regions,
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

        # 读取安全组配置
        sec_domain_handle = block.security_group

        # 分配 domain_id
        # 如果有安全组控制器，可以从安全子系统分配
        if self.security_controller and self.security_controller.enabled:
            # 从安全组获取 domain_id
            if sec_domain_handle == 0:
                # 继承父域的安全组
                sec_domain_handle = self.current_domain.block.security_group
                # 如果父域也没有安全组，使用 root_handle
                if sec_domain_handle == 0:
                    sec_domain_handle = self.security_controller.root_handle
            # 绑定域到安全组
            if sec_domain_handle:
                self.security_controller.bind_domain(sec_domain_handle, domain_id if domain_id else self._next_domain_id)

        # 如果还没分配 domain_id，使用默认分配
        if domain_id is None:
            domain_id = self._next_domain_id
            self._next_domain_id += 1

        # 更新 Python 对象
        block.domain_id = domain_id
        block.security_group = sec_domain_handle

        self.current_domain.block.child_block = block_addr

        # 写入内存
        if self.memory:
            self.memory.write_word(block_addr + OFFSET_DOMAIN_ID, domain_id)
            self.memory.write_word(block_addr + OFFSET_SECURITY_GROUP, sec_domain_handle)
            self.memory.write_word(self.current_domain.block_addr + OFFSET_CHILD_BLOCK, block_addr)

        # 绑定到安全组
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
            "pagetable": block.pagetable,
            "ipa_regions": block.ipa_regions,
            "domain_id": domain_id,
            "is_first": True,  # 标记为首次
        }

    def ascend(self, service_type: int, release: bool = False) -> Any:
        """
        请求父域服务

        RPALogic pseudo-RTL 层只负责:
        1. 切换到父域
        2. 返回 trap_vector

        寄存器保存由 ISA 负责（complete_ascend）

        Args:
            service_type: 服务类型
            release: 是否释放子域（EXIT 语义）
        """
        if self.current_domain.parent is None:
            raise RuntimeError("Cannot ascend from root domain")

        parent = self.current_domain.parent
        child_block_addr = self.current_domain.block_addr
        child_domain_id = self.current_domain.domain_id
        child_sec_domain = self.current_domain.block.security_group

        self.stats["ascend_count"] += 1

        if release:
            # EXIT 语义：清空父子关系
            # 更新 Python 对象
            parent.block.child_block = 0
            self.current_domain.block.domain_id = 0

            # 写入内存
            if self.memory:
                self.memory.write_word(parent.block_addr + OFFSET_CHILD_BLOCK, 0)
                self.memory.write_word(child_block_addr + OFFSET_DOMAIN_ID, 0)

            # 解绑安全组
            if self.security_controller and child_sec_domain:
                self.security_controller.unbind_domain(child_sec_domain, child_domain_id)

            # 从注册表移除子域
            if child_block_addr in self._domain_registry:
                del self._domain_registry[child_block_addr]

        # 切换到父域
        self.current_domain = parent

        return {
            "vector": parent.block.trap_vector,
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

        if self.current_domain.block.trap_vector != 0:
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

    # ============================================================
    # Root Layer Interface - Domain Hierarchy Query
    # ============================================================

    def get_domain_hierarchy(self) -> Dict[int, Dict[str, Any]]:
        """
        获取域层次信息（Root Layer 接口）

        安全子系统调用此接口获取权威的域层次信息。

        Returns:
            Dict mapping domain_id to:
            - "parent_id": 父域ID (root为None)
            - "block_addr": DomainBlock地址
            - "security_group": 绑定的安全组handle
        """
        hierarchy = {}

        # 从注册表遍历所有域
        for block_addr, domain in self._domain_registry.items():
            parent_id = domain.parent.domain_id if domain.parent else None
            hierarchy[domain.domain_id] = {
                "parent_id": parent_id,
                "block_addr": block_addr,
                "security_group": domain.block.security_group,
            }

        return hierarchy

    def verify_parent_child(self, parent_id: int, child_id: int) -> bool:
        """
        验证父子关系（Root Layer 接口）

        安全子系统调用此接口验证调用者是否为目标域的父域。

        Args:
            parent_id: 声称的父域ID
            child_id: 目标子域ID

        Returns:
            True 如果 parent_id 是 child_id 的直接父域
        """
        # 特殊情况：root可以操作任何域
        if parent_id == 0:
            return True

        # 查找子域
        child_domain = self.get_domain_by_id(child_id)
        if child_domain is None:
            return False

        # 验证父域
        if child_domain.parent is None:
            # child是root，没有父域
            return False

        return child_domain.parent.domain_id == parent_id

    def get_domain_by_id(self, domain_id: int) -> Optional[Domain]:
        """
        根据ID获取域对象

        Args:
            domain_id: 域ID

        Returns:
            Domain对象，如果不存在则返回None
        """
        for domain in self._domain_registry.values():
            if domain.domain_id == domain_id:
                return domain
        return None

    def get_domain_path_to_root(self, domain_id: int) -> List[int]:
        """
        获取从指定域到root的路径（Root Layer 接口）

        Args:
            domain_id: 起始域ID

        Returns:
            域ID列表，从指定域到root [domain_id, parent_id, ..., 0]
        """
        path = []
        domain = self.get_domain_by_id(domain_id)

        while domain is not None:
            path.append(domain.domain_id)
            domain = domain.parent

        return path

    def _read_domain_block(self, addr: int) -> DomainBlock:
        """从内存读取 DomainBlock"""
        if self.memory:
            return DomainBlock(
                ctrlblock_size=self.memory.read_word(addr + OFFSET_CTRLBLOCK_SIZE),
                domain_id=self.memory.read_word(addr + OFFSET_DOMAIN_ID),
                trap_vector=self.memory.read_word(addr + OFFSET_TRAP_VECTOR),
                interrupt_ctrl=self.memory.read_word(addr + OFFSET_INTERRUPT_CTRL),
                ipa_regions=self.memory.read_word(addr + OFFSET_IPA_REGIONS),
                pagetable=self.memory.read_word(addr + OFFSET_PAGETABLE),
                child_block=self.memory.read_word(addr + OFFSET_CHILD_BLOCK),
                security_group=self.memory.read_word(addr + OFFSET_SECURITY_GROUP),
            )
        return DomainBlock()

    def _write_domain_block(self, addr: int, block: DomainBlock) -> None:
        """写入 DomainBlock 到内存"""
        if self.memory:
            self.memory.write_word(addr + OFFSET_CTRLBLOCK_SIZE, block.ctrlblock_size)
            self.memory.write_word(addr + OFFSET_DOMAIN_ID, block.domain_id)
            self.memory.write_word(addr + OFFSET_TRAP_VECTOR, block.trap_vector)
            self.memory.write_word(addr + OFFSET_INTERRUPT_CTRL, block.interrupt_ctrl)
            self.memory.write_word(addr + OFFSET_IPA_REGIONS, block.ipa_regions)
            self.memory.write_word(addr + OFFSET_PAGETABLE, block.pagetable)
            self.memory.write_word(addr + OFFSET_CHILD_BLOCK, block.child_block)
            self.memory.write_word(addr + OFFSET_SECURITY_GROUP, block.security_group)

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

        # ascend() 会切换到父域并返回 trap_vector
        # 由 Decoder 负责跳转到 trap_vector 执行处理程序
        self.ascend(0x01)  # FAULT 类型

    def _fault_type_to_code(self, fault_type: str) -> int:
        """转换异常类型到代码"""
        codes = {
            "ascend": 0x00,
            "page_fault": 0x01,
            "illegal_instruction": 0x02,
            "privilege_violation": 0x03,
        }
        return codes.get(fault_type, 0xFF)