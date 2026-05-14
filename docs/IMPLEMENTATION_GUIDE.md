# RPA-Sim 项目实现解读文档

## 项目概述

RPA-Sim 是 **递归特权架构** 的 Python 概念验证模拟器。该模拟器实现了 RPA 的核心机制：递归域管理、多层页表翻译、安全组隔离和中断控制。

---

## 一、模块分析

### 1.1 rpa_logic.py - RPA 核心逻辑模块

**核心职责**：域管理与特权原语实现

**关键数据结构**：

```python
# 文件：rpa_logic.py，行 346-398
@dataclass
class DomainBlock:
    """域控制块 - 内存中的域配置结构"""
    ctrlblock_size: int = 8      # 0x00: 控制块大小（单位：word）
    domain_id: int = 0           # 0x04: 域ID（系统分配）
    trap_vector: int = 0         # 0x08: Trap 处理入口（子域设置，0=传播）
    interrupt_ctrl: int = 0      # 0x0C: 中断控制器 handle
    ipa_regions: int = 0         # 0x10: IPA 区域表地址（父域设置）
    pagetable: int = 0           # 0x14: 页表地址（子域设置）
    child_block: int = 0         # 0x18: 子域控制块地址（父域维护）
    security_group: int = 0      # 0x1C: 安全组 handle
```

```python
# 文件：rpa_logic.py，行 399-413
@dataclass
class Domain:
    """特权域对象"""
    domain_id: int
    block: DomainBlock
    parent: Optional['Domain'] = None  # 父域引用（用于错误归属）
    block_addr: int = 0                # DomainBlock 在内存中的地址
```

**核心类 RPALogic**：

- `descend(block_addr)`: 进入子域（见后文详细分析）
- `ascend(service_type, release)`: 返回父域请求服务
- `fault(fault_type, address)`: 触发异常处理
- `get_depth()`: 获取当前域深度

**依赖关系**：
- 被 `SimpleISA` 调用执行特权指令
- 引用 `SecurityGroupController` 进行安全组绑定
- 引用 `Memory` 读写 DomainBlock

---

### 1.2 memory.py - 内存与页表管理模块

**核心职责**：物理内存模拟、页表管理、多层地址翻译

**关键数据结构**：

```python
# 文件：memory.py，行 93-101
@dataclass
class PageTableEntry:
    """单个页表项"""
    virtual_page: int        # 虚拟页号
    physical_page: int       # 物理页号
    r: bool = True           # 可读
    w: bool = True           # 可写
    x: bool = True           # 可执行
    c: bool = False          # 控制区域（必须用 sysop 访问）
```

```python
# 文件：memory.py，行 37-46
@dataclass
class TranslationResult:
    """翻译结果"""
    pa: int                    # 物理地址
    r: bool = True             # 可读
    w: bool = True             # 可写
    x: bool = True             # 可执行
    c: bool = False            # 控制区域
    fault_owner: Optional[int] = None  # 异常归属域
```

**核心类 MemoryManager**：

- `translate_chain(va, pagetable_chain, ipa_regions)`: 沿页表链翻译地址
- `read_with_translation()`: 带翻译的读取
- `write_with_translation()`: 带翻译的写入
- `_check_ipa_bounds()`: IPA 边界检查

**依赖关系**：
- 被 `SimpleISA` 用于 LDR/STR 地址翻译
- 引用 `SecurityGroupController` 进行加密管理

---

### 1.3 isa_simple.py - 简化指令集核心

**核心职责**：指令解码与执行、RPA 特权指令实现

**关键数据结构**：

```python
# 文件：isa_simple.py，行 185-218
class OpCode(Enum):
    """操作码"""
    MOV, ADD, SUB, CMP, AND, ORR = ...  # 数据处理
    LDR, STR = ...                        # 加载存储
    B, BEQ, BNE, BL, BX = ...             # 分支
    DESCEND, ASCEND, RETURN, EXIT = ...   # RPA 特权指令
    SYSOP = ...                            # 系统操作
    NOP, HALT = ...                        # 特殊指令
```

```python
# 文件：isa_simple.py，行 234-291
@dataclass
class CPUState:
    """CPU 状态"""
    registers: List[int] = field(default_factory=lambda: [0] * 16)
    n, z, c, v: bool = False  # 标志位
    irq_disabled: bool = False
    in_interrupt: bool = False
    current_priority: int = PRIORITY_NORMAL
```

**核心类 SimpleISA**：

- `step()`: 执行单条指令
- `run()`: 运行直到停机
- `_execute_descend()`: 执行 DESCEND 指令
- `_execute_ascend()`: 执行 ASCEND/EXIT 指令
- `_execute_return()`: 执行 RETURN 指令
- `_check_interrupt()`: 中断检查

**依赖关系**：
- 依赖 `RPALogic` 进行域切换
- 依赖 `MemoryManager` 进行地址翻译
- 依赖 `InterruptController` 进行中断管理
- 依赖 `SecurityGroupController` 进行安全组操作

---

### 1.4 security_group.py - 安全组管理模块

**核心职责**：安全隔离、内存加密、DMA 访问控制

**关键数据结构**：

```python
# 文件：security_group.py，行 44-76
@dataclass
class SecurityGroup:
    """安全组实例"""
    handle: int                         # 安全组句柄
    owner_domain_id: int                # 创建者域 ID
    domain_id: int                      # 安全组 ID（内存子系统用）
    parent_handle: int = 0              # 父安全组
    memory_isolated: bool = True        # 内存隔离
    encrypted: bool = False             # 是否加密
    encryption_key: int = 0             # 加密密钥
    allowed_accessors: Set[int] = ...   # 允许的访问者
    is_confidential: bool = False       # 机密计算域
    bound_domains: Set[int] = ...       # 关联的域
```

**核心类 SecurityGroupController**：

- `create()`: 创建安全组（需 attestation 验证）
- `destroy()`: 销毁安全组（仅 owner 可调用）
- `destroy_force()`: 强制销毁（仅 root 域可用）
- `bind_domain()`: 绑定域到安全组
- `check_dma_access()`: DMA 访问权限检查
- `set_encryption()`: 设置加密区域

**依赖关系**：
- 被 `RPALogic` 在 DESCEND 时绑定
- 与 `MemoryManager` 协同管理加密内存

---

### 1.5 interrupt.py - 中断控制器模块

**核心职责**：中断实例管理、优先级控制、多级传递

**关键数据结构**：

```python
# 文件：interrupt.py，行 161-177
@dataclass
class InterruptInstance:
    """中断控制器实例"""
    handle: int                  # 实例句柄
    owner_domain_id: int         # 申请者域 ID
    permissions: int             # 权限位图
    irq_enable: bool = False     # I-bit
    vector: int = 0              # 中断向量
    pending: int = 0             # 待处理中断位图
    parent_handle: int = 0       # 父域实例 handle
    child_handle: int = 0        # 子域实例 handle
    permission_mask: int = 0xFFFFFFFF  # 可委托的 IRQ 权限位图
```

**优先级系统**：

```python
# 文件：interrupt.py，行 51-57
PRIORITY_DATA_ABORT = 4         # 最高 - 数据异常
PRIORITY_INSTRUCTION_ABORT = 4  # 指令异常
PRIORITY_INVALID_INSTRUCTION = 4
PRIORITY_ASCEND = 3             # ASCEND trap
PRIORITY_IRQ = 2                # 正常中断
PRIORITY_NORMAL = 1             # 最低
```

**依赖关系**：
- 被 `SimpleISA` 查询中断状态
- 使用 `PriorityController` 进行优先级判断

---

### 1.6 machine.py - 机器集成模块

**核心职责**：组装所有组件提供完整 RPA 环境

```python
# 文件：machine.py，行 23-99
class Machine:
    def __init__(self, memory_size, stdio_base, stdio_callback):
        self.rpa = RPALogic()
        self.memory = Memory(size=memory_size)
        self.mm = MemoryManager(physical_memory=self.memory)
        self.core = SimpleISA(rpa=self.rpa, memory=self.memory, memory_manager=self.mm)
        self.stdio = StdioDevice(base_addr=stdio_base)
```

**依赖关系**：组合所有其他模块

---

### 1.7 stdio.py - 控制台设备模块

**核心职责**：内存映射 I/O 模拟，字符输出

**核心类 StdioDevice**：
- `base_addr`: 设备基地址（默认 0xFFFF0000）
- `write_byte()`: 写入字符输出
- `read_byte()`: 读取返回 0（只写设备）

---

## 二、RPA 核心原语实现

### 2.1 DESCEND 语义与实现

**语义**：父域进入子域执行

**完整实现逻辑**：

```python
# 文件：rpa_logic.py，行 510-639
def descend(self, block_addr: int, domain_id: Optional[int] = None) -> Any:
    """
    进入子域

    1. 验证控制块（对齐和大小）
    2. 检查 child_block 判断首次/后续 DESCEND
    3. 首次：创建新域对象，分配 domain_id，绑定安全组
    4. 后续：复用已存在的域对象
    5. 切换 current_domain
    6. 返回 pagetable, ipa_regions, domain_id, is_first
    """
```

**ISA 层实现**：

```python
# 文件：isa_simple.py，行 1282-1318
def _execute_descend(self, inst: Instruction) -> None:
    """
    1. 从寄存器读取 DomainBlock 地址
    2. 调用 RPALogic.descend() 切换域
    3. 调用 prepare_descend() 恢复上下文
    4. 跳转到 saved_lr（统一入口）
    5. 更新 pagetable_chain 和 ipa_regions
    """
```

**关键细节**：
- 首次 DESCEND：父域预先写入入口地址到 `saved_lr` (0x2C)
- 后续 DESCEND：ASCEND 已保存返回地址到 `saved_lr`
- 安全程措：清空 r4-r12 防止信息泄露

---

### 2.2 ASCEND (escalate) 语义与实现

**语义**：子域请求父域服务

**完整实现逻辑**：

```python
# 文件：rpa_logic.py，行 641-692
def ascend(self, service_type: int, release: bool = False) -> Any:
    """
    请求父域服务

    1. 检查是否在根域（不能 ascend）
    2. 如果 release=True（EXIT 语义）：清空父子关系
    3. 切换到父域
    4. 返回 trap_vector, domain_id 等
    """
```

**ISA 层实现**：

```python
# 文件：isa_simple.py，行 1319-1358
def _execute_ascend(self, inst: Instruction, release: bool = False) -> None:
    """
    1. 读取 service_type
    2. 进入 ASCEND 优先级（高于 IRQ）
    3. 调用 complete_ascend() 保存上下文
    4. 切换到父域，跳转到 trap_vector
    5. 更新页表链（移除当前域页表）
    """
```

**Trap 传播机制**：
- 若 `trap_vector == 0`，继续传播到祖父域
- 根域必须处理所有 Trap

---

### 2.3 RETURN 语义与实现

**语义**：父域返回子域继续执行

**实现**：

```python
# 文件：isa_simple.py，行 1369-1376
def _execute_return(self, inst: Instruction) -> None:
    """
    RETURN 是 DESCEND 的别名，用于从父域返回子域。
    逻辑与后续 DESCEND 完全相同。
    """
    self._execute_descend(inst)
```

**关键点**：
- 通过 `child_block` 字段定位子域控制块
- 从 `saved_lr` 恢复执行位置

---

### 2.4 EXIT 语义与实现

**语义**：子域终止执行，释放资源

**实现**：

```python
# 文件：isa_simple.py，行 1360-1367
def _execute_exit(self, inst: Instruction) -> None:
    """
    EXIT = ASCEND(release=True)
    子域终止，父域无法 RETURN，控制块可被重新使用。
    """
    self._execute_ascend(inst, release=True)
```

**与 ASCEND 的区别**：

| 操作 | ASCEND | EXIT |
|------|--------|------|
| 子域状态 | 保留 | 释放 |
| child_block | 保留 | 清零 |
| domain_id | 保留 | 清零 |
| 可 RETURN | 是 | 否 |

---

## 三、DomainBlock 内存布局

```
DCB 三段式布局 (32 位系统):
┌─────────────────────────────────────────────────────────────────┐
│ RPA Spec Field (固定 8 words, 32 字节)                          │
│   由 RPA 架构规范定义，跨平台统一                                │
├─────────────────────────────────────────────────────────────────┤
│ RPA Impdef Field (可变)                                         │
│   大小：ctrlblock_size - 8 words                                │
│   内容：trap_delegate、中断控制器状态、平台扩展                  │
├─────────────────────────────────────────────────────────────────┤
│ ISA Context Field (可变)                                        │
│   大小：由 ISA 规范定义                                          │
│   内容：通用寄存器、状态寄存器、扩展寄存器                       │
└─────────────────────────────────────────────────────────────────┘
```

**RPA Spec Field 详细布局**：

| 偏移 | 字段 | 设置者 | 用途 |
|------|------|--------|------|
| 0x00 | ctrlblock_size | 父域 | 控制块大小（单位：word） |
| 0x04 | domain_id | 系统 | 域标识（DMA 访问控制） |
| 0x08 | trap_vector | 子域 | Trap 处理入口（0=传播） |
| 0x0C | interrupt_ctrl | 系统 | 中断控制器 handle |
| 0x10 | ipa_regions | 父域 | IPA 区域表地址（只读） |
| 0x14 | pagetable | 子域 | 页表地址（可写） |
| 0x18 | child_block | 父域 | 子域控制块地址 |
| 0x1C | security_group | 系统 | 安全组 handle |

**ISA Context Field（SimpleISA 扩展）**：

| 偏移 | 字段 | 用途 |
|------|------|------|
| 0x28 | saved_sp | ASCEND 保存的栈指针 |
| 0x2C | saved_lr | ASCEND 保存的返回地址 |
| 0x30 | saved_psr | ASCEND 保存的程序状态 |
| 0x40-0x80 | irq_saved_* | 中断现场保存区 |

---

## 四、页表翻译机制

### 4.1 多层翻译

```
Domain 2 访问 VA2:
  ipa2 = translate(domain2.pagetable, va2)
       - 访问页表数据需要用 domain1.pagetable 翻译
       - 失败 -> 报给 domain2
  ipa1 = translate(domain1.pagetable, ipa2)
       - 失败 -> 报给 domain1
  pa = translate(domain0.pagetable, ipa1)
       - 失败 -> 报给 domain0 (root)
  访问 pa -> 总线错误
```

### 4.2 核心翻译函数

```python
# 文件：memory.py，行 597-666
def translate_chain(self, va: int, pagetable_chain: List[int],
                    ipa_regions: int = 0,
                    memory: Optional['Memory'] = None) -> TranslationResult:
    """
    沿着页表链翻译地址

    - pagetable_chain = [domain_n.pagetable, ..., domain_0.pagetable]
    - 每层翻译可能限制权限（取交集）
    - 第一层翻译后检查 IPA 边界
    - 返回物理地址、权限、异常归属
    """
```

### 4.3 IPA 边界检查

```python
# 文件：memory.py，行 668-698
def _check_ipa_bounds(self, ipa: int, ipa_regions: int, memory: 'Memory') -> bool:
    """
    检查 IPA 是否在 ipa_regions 定义的范围内

    - ipa_regions 是一个表，每个条目 12 字节
    - 条目格式：base(4) + size(4) + attr(4)
    - 全零条目表示结束
    """
```

---

## 五、安全组机制

### 5.1 核心功能

**创建流程**：

```python
# 文件：security_group.py，行 199-267
def create(self, owner_domain_id: int, config: SecurityGroupConfig,
           parent_handle: int = 0) -> int:
    """
    1. 检查是否继承父安全组
    2. Attestation 验证（检查 domain_id 是否在 EXPECTED_ATTESTATION_IDS）
    3. 分配 handle 和 domain_id
    4. 如果需要加密，生成密钥
    5. 创建 SecurityGroup 实例
    """
```

**Attestation 机制**：

```python
# 文件：security_group.py，行 117
EXPECTED_ATTESTATION_IDS = {0, 1, 2, 3}  # 允许创建安全组的域

def verify_attestation(self, owner_id: int, measurement: int = 0) -> bool:
    """验证创建安全组的权限"""
    return owner_id in self.EXPECTED_ATTESTATION_IDS
```

### 5.2 DMA 访问控制

```python
# 文件：security_group.py，行 435-473
def check_dma_access(self, target_handle: int, accessor_domain_id: int,
                     operation: str = 'read') -> bool:
    """
    DMA 访问规则：
    1. 同一安全组内允许
    2. 在 allowed_accessors 中允许
    3. 机密计算域禁止外部访问
    4. root 域不能访问机密计算域
    """
```

### 5.3 内存加密

```python
# 文件：memory.py，行 74-89
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
```

---

## 六、模块依赖关系图

```
                    ┌──────────────────┐
                    │     Machine      │
                    │  (machine.py)    │
                    └────────┬─────────┘
                             │
         ┌───────────────────┼───────────────────┐
         │                   │                   │
         ▼                   ▼                   ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│    SimpleISA    │ │    RPALogic     │ │ MemoryManager   │
│ (isa_simple.py) │ │  (rpa_logic.py) │ │   (memory.py)   │
└────────┬────────┘ └────────┬────────┘ └────────┬────────┘
         │                   │                   │
         │                   │                   │
         │         ┌─────────┴─────────┐         │
         │         │                   │         │
         │         ▼                   ▼         │
         │ ┌─────────────────┐ ┌─────────────────┐
         │ │SecurityGroupCtrl│ │InterruptCtrl    │
         │ │(security_group) │ │(interrupt.py)   │
         │ └─────────────────┘ └─────────────────┘
         │
         ▼
┌─────────────────┐
│ StdioDevice     │
│  (stdio.py)     │
└─────────────────┘
```

---

## 七、机密域销毁例程

### 7.1 设计理念

RPA 架构采用"安全子系统作为安全请求第一入口"模式：

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Security Request Flow                             │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│   Caller Domain (P)                Security Subsystem                │
│   ┌─────────────┐                  ┌─────────────────┐              │
│   │             │  1. Request      │                 │              │
│   │  Parent of  │ ──────────────▶  │  SecurityGroup  │              │
│   │  Confidential│                 │  Controller     │              │
│   │  Child (C)  │                  │                 │              │
│   │             │                  └────────┬────────┘              │
│   └─────────────┘                           │                       │
│                                             │ 2. Query hierarchy     │
│                                             ▼                       │
│   ┌─────────────┐                  ┌─────────────────┐              │
│   │   Root      │  3. Return info  │                 │              │
│   │   Domain    │ ◀─────────────── │   RPALogic      │              │
│   │   (id=0)    │                  │   (root layer)  │              │
│   └─────────────┘                  └─────────────────┘              │
│                                                                      │
│   Root holds: core context, root trust, domain hierarchy             │
│   Security subsystem observes chip actions with root layer support   │
│   (unlike separated TPM which lacks this coordination capability)    │
└─────────────────────────────────────────────────────────────────────┘
```

**为什么安全子系统作为入口？**
1. RPA 架构层数多，层层上报效率低
2. 安全子系统统一处理安全策略
3. 相比分离式 TPM，安全子系统可洞察芯片动作

**为什么只需验证父子关系？**
1. 概念验证模拟器，无需真正加解密
2. 父子关系是 RPA 特权委托的核心
3. Root 层维护权威的域层次信息

### 7.2 Root Layer 接口 (rpa_logic.py)

```python
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

def verify_parent_child(self, parent_id: int, child_id: int) -> bool:
    """
    验证父子关系（Root Layer 接口）

    安全子系统调用此接口验证调用者是否为目标域的父域。
    特殊情况：root (id=0) 可以操作任何域。
    """

def get_domain_by_id(self, domain_id: int) -> Optional[Domain]:
    """根据ID获取域对象"""

def get_domain_path_to_root(self, domain_id: int) -> List[int]:
    """获取从指定域到root的路径 [domain_id, parent_id, ..., 0]"""
```

### 7.3 Security Subsystem 接口 (security_group.py)

```python
def request_destroy_confidential(
    self,
    handle: int,
    caller_domain_id: int,
    rpa_logic: Any
) -> Tuple[bool, str]:
    """
    请求销毁机密域（安全子系统入口点）

    流程：
    1. 检查安全组存在且为机密域
    2. 通过 Root 层验证父子关系
    3. 授权则执行销毁

    Returns:
        (success, message) 元组
    """

def is_confidential_handle(self, handle: int) -> bool:
    """检查安全组是否为机密域"""

def get_bound_domains(self, handle: int) -> Set[int]:
    """获取安全组绑定的所有域ID"""
```

### 7.4 典型使用场景

```python
# 设置环境
mem = Memory(1024 * 1024)
mem_mgr = MemoryManager(mem)
controller = SecurityGroupController(mem_mgr)
rpa = RPALogic()
rpa.memory = mem
rpa.set_security_controller(controller)

# 创建父域和机密子域
parent_config = SecurityGroupConfig(create_new=True, isolated=True)
parent_handle = controller.create(owner_domain_id=1, config=parent_config)

child_config = SecurityGroupConfig(
    create_new=True,
    isolated=True,
    confidential=True  # 机密域
)
child_handle = controller.create(owner_domain_id=2, config=child_config)

# 建立 DESCEND 创建父子关系
# ... (通过 DESCEND 指令)

# 验证父子关系
assert rpa.verify_parent_child(1, 2)  # True: domain 1 是 domain 2 的父域

# 父域请求销毁机密子域
success, message = controller.request_destroy_confidential(
    handle=child_handle,
    caller_domain_id=1,  # 父域ID
    rpa_logic=rpa
)

# 非父域尝试销毁（被拒绝）
success, message = controller.request_destroy_confidential(
    handle=child_handle,
    caller_domain_id=3,  # 恶意域
    rpa_logic=rpa
)
# success = False, message = "Authorization denied..."
```

---

## 八、关键代码位置索引

| 功能 | 文件 | 行号范围 |
|------|------|----------|
| DomainBlock 定义 | rpa_logic.py | 346-398 |
| DESCEND 实现 | rpa_logic.py | 510-639 |
| ASCEND 实现 | rpa_logic.py | 641-692 |
| Root Layer 接口 | rpa_logic.py | 720-785 |
| 页表翻译 | memory.py | 597-666 |
| IPA 边界检查 | memory.py | 668-698 |
| DESCEND 指令 | isa_simple.py | 1282-1318 |
| ASCEND 指令 | isa_simple.py | 1319-1358 |
| RETURN 指令 | isa_simple.py | 1369-1376 |
| EXIT 指令 | isa_simple.py | 1360-1367 |
| 安全组创建 | security_group.py | 199-267 |
| 机密域销毁 | security_group.py | 357-435 |
| DMA 访问检查 | security_group.py | 535-573 |
| 中断优先级 | interrupt.py | 51-57 |
| 中断检查 | isa_simple.py | 1181-1226 |

---

## 九、总结

RPA-Sim 项目完整实现了 RPA 架构的核心概念：

1. **递归域管理**：通过 DESCEND/ASCEND/RETURN/EXIT 四条特权原语实现域切换
2. **多层地址翻译**：页表链叠加翻译，每层可独立设置权限
3. **安全组隔离**：统一的内存隔离机制，支持加密和 DMA 访问控制
4. **中断管理**：支持优先级抢占和多级传递
5. **机密域销毁**：安全子系统入口 + Root 层验证的授权机制