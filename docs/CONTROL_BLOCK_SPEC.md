# RPA 控制块设计规范 v3

## 核心概念

### Domain（特权域）

Domain 是 RPA 架构中的执行单元，每个 Domain 有：
- 独立的地址空间（可选，可继承父域）
- 独立的异常处理入口
- 独立的执行状态（寄存器、标志位）
- 明确的权限边界

Domain 之间形成树状层级关系：
```
root_domain (最高特权，系统启动时创建)
    └── child_domain_1
        └── child_domain_2
            └── ...
```

### 控制块（DomainBlock）

控制块是内存中的数据结构，用于配置和切换 Domain。

**关键设计原则**：
1. 控制块位于内存中，通过普通读写指令操作
2. 控制块大小固定，便于硬件解析
3. DESCEND 指令使控制块配置生效

---

## 控制块结构

控制块大小：128 字节（对齐要求：64字节边界）

```
偏移    字段名                大小    说明
────    ──────                ────    ────
0x00    ctrlblock_size        4       控制块大小（必须为32的倍数）
0x04    exception_vector      4       异常向量
0x08    reserved_08           4       保留（原 interrupt_vector）
0x0C    interrupt_ctrl        4       中断控制器
0x10    ipa_regions           4       IPA 区域表地址（父域设置，子域只读）
0x14    domain_id             4       域ID（系统分配）
0x18    pagetable             4       页表地址（子域设置，子域可写）
0x1C    child_block           4       子域控制块地址（父域维护）
0x20    security_domain       4       安全域 handle
0x24    access_id             4       访问 ID (DMA 用)
0x28    saved_sp              4       保存的栈指针（ISA扩展）
0x2C    saved_lr              4       保存的返回地址（ISA扩展）
0x30    saved_psr             4       保存的程序状态（ISA扩展）
0x34-0x3F reserved             12     保留
```

### 字段详解

#### ctrlblock_size (0x00)
- 控制块大小，必须为32的倍数
- DESCEND 时硬件验证对齐

#### exception_vector (0x04)
- 异常处理入口地址
- 所有非中断异常（包括 ESCALATE）跳转到此地址
- 值为 0 表示禁用异常处理，异常直接传播到父域

#### reserved_08 (0x08)
- 保留字段（原 interrupt_vector）

#### interrupt_ctrl (0x0C)
- 中断控制器 handle
- 值为 0：子域不能操作中断控制器
- 值为 非0：子域可以通过 `sysop irq` 操作中断

#### ipa_regions (0x10)
- IPA 区域表地址
- **父域设置，子域只读**
- 定义子域可用的 IPA 范围约束
- 值为 0：不建立新映射（try-catch 场合）

#### domain_id (0x14)
- 域 ID，由系统分配
- 用于调试和安全子系统

#### pagetable (0x18)
- 页表地址
- **子域设置，子域可写**
- 定义 VA → IPA 的映射
- 子域创建页表后更新此字段

#### child_block (0x1C)
- 子域控制块地址
- 由父域维护
- 用于 RETURN 指令返回子域

#### security_domain (0x20)
- 安全域 handle
- 用于内存加密和 DMA 访问控制

#### access_id (0x24)
- 访问 ID
- 用于 DMA 访问控制

#### saved_sp (0x28)
- ISA 保存的栈指针
- ESCALATE 时保存，RETURN 时恢复

#### saved_lr (0x2C)
- ISA 保存的返回地址
- 首次 DESCEND：父域写入入口地址
- ESCALATE：保存返回地址
- RETURN：从该地址恢复执行

#### saved_psr (0x30)
- ISA 保存的程序状态寄存器
- 保存 N, Z, C, V 标志

---

## IPA 区域表与页表

控制块使用两个独立字段管理地址翻译，实现安全隔离：

| 字段 | 设置者 | 权限 | 用途 |
|------|--------|------|------|
| ipa_regions | 父域 | 子域只读 | 定义可用的 IPA 范围约束 |
| pagetable | 子域 | 子域可写 | 子域创建的 VA→IPA 页表 |

### IPA 区域表（ipa_regions）

描述父域分配给子域的 IPA 空间范围约束。

```
偏移    字段名          大小    说明
────    ──────          ────    ────
0x00    base            4       基地址
0x04    size            4       大小
0x08    attr            4       属性
...     ...             ...     更多条目
以全零条目结束
```

### 页表（pagetable）

描述子域的 VA → IPA 映射。

```
偏移    字段名          大小    说明
────    ──────          ────    ────
0x00    base            4       虚拟页基址
0x04    size            4       页大小
0x08    attr            4       属性（rwx c）
...     ...             ...     更多条目
以全零条目结束
```

### 属性字段 (attr)

| 位 | 名称 | 说明 |
|----|------|------|
| 0 | READ | 可读 |
| 1 | WRITE | 可写 |
| 2 | EXEC | 可执行 |
| 3 | DEVICE | 设备内存（非缓存） |
| 4-7 | type | 内存类型 |
| 8-31 | reserved | 保留 |

### 自洽性要求

控制块本身必须位于 ipa_regions 表中某个条目描述的区域内：

```
ipa_regions 指向的表中，
至少有一个条目满足：
  entry.base <= control_block_addr < entry.base + entry.size
```

---

## 系统操作指令（sysop）

### 指令编码

```
sysop <op>, <subop>, <arg1>, <arg2>

op:     操作类型
subop:  子操作
arg1:   操作数1
arg2:   操作数2
```

### 操作码定义

| 操作 | 操作码 | 说明 |
|-----|-------|------|
| IRQ | 0x01 | 中断操作 |
| MEMTABLE | 0x02 | IPA 区域表操作 |
| PAGETABLE | 0x03 | 页表操作 |
| SECDOMAIN | 0x04 | 安全域操作 |

### 子操作码定义

| 子操作 | 操作码 | 适用操作 |
|-------|-------|---------|
| QUERY | 0x10 | MEMTABLE, PAGETABLE |
| COUNT | 0x11 | MEMTABLE, PAGETABLE |

### irq - 中断操作

```
sysop irq, read, #irq_id, Rd      ; 读取中断 irq_id 的信息
sysop irq, write, #irq_id, Rs     ; 写入中断 irq_id 的设置
```

权限检查：
- 如果 interrupt_ctrl == 0，触发异常

### memtable - IPA 区域表操作

子域查询父域分配的 IPA 地址范围。

```
sysop memtable, query, #index, #regmask
    ; 读取 ipa_regions 表的第 index 个条目
    ; regmask: 8 位位图，指定 R0-R7
    ; 结果: base→最低位寄存器, size→中间, attr→最高位
    ; 示例: #0x07 表示 R0=base, R1=size, R2=attr

sysop memtable, count, Rd
    ; 返回 ipa_regions 表的条目数到 Rd
```

寄存器掩码编码示例：

| regmask | 二进制 | 寄存器分配 |
|---------|-------|-----------|
| 0x07 | 0b00000111 | R0=base, R1=size, R2=attr |
| 0x0E | 0b00001110 | R1=base, R2=size, R3=attr |
| 0x38 | 0b00111000 | R3=base, R4=size, R5=attr |

返回值：
- 如果 index 超出范围或 ipa_regions == 0，返回全零
- 条目格式：base(4字节) + size(4字节) + attr(4字节) = 12字节
- 表以全零条目结尾

### pagetable - 页表操作

子域查询自己的 VA→IPA 映射表。

```
sysop pagetable, query, #index, #regmask
    ; 读取 pagetable 表的第 index 个条目
    ; regmask 格式同 memtable

sysop pagetable, count, Rd
    ; 返回 pagetable 表的条目数到 Rd
```

---

## 指令行为

### DESCEND

```
DESCEND Rd    ; Rd = 控制块地址
```

执行流程：
1. 从 Rd 读取控制块地址
2. 验证控制块有效性：
   - 地址对齐到 32 字节
   - ctrlblock_size 有效
   - 父域无其他子域（child_block == 0 或 child_block == Rd）
3. 硬件操作：
   - 如果 child_block == Rd：RETURN 语义，恢复子域上下文
   - 否则：首次 DESCEND
     - 分配 domain_id
     - 保存父域 PC 到父域控制块
     - 设置父域 child_block = Rd
     - 跳转到 saved_lr（由父域预先设置）
4. 清除流水线（上下文同步）

### ESCALATE

```
ESCALATE Rd    ; Rd = 服务类型/参数
```

执行流程：
1. 将 Rd 值写入当前域控制块的 return_value
2. 保存当前上下文到控制块（saved_pc, saved_lr, saved_sp, ...）
3. 切换到父域
4. 跳转到父域的 exception_vector（异常类型 = ESCALATE）
5. 清除流水线（上下文同步）

### RETURN

```
RETURN        ; 返回子域
```

执行流程：
1. 从父域控制块读取子域控制块地址
2. 切换到子域
3. 从控制块恢复上下文（saved_pc, saved_lr, ...）
4. 跳转到 saved_pc 继续执行

---

## 异常处理

### 异常类型

| 类型 | 编码 | 跳转目标 |
|------|------|----------|
| ESCALATE | 0x00 | exception_vector |
| PAGE_FAULT | 0x01 | exception_vector |
| ILLEGAL_INSTRUCTION | 0x02 | exception_vector |
| PRIVILEGE_VIOLATION | 0x03 | exception_vector |
| IRQ | 0x10+ | interrupt_vector |

### 异常处理流程

```
子域触发异常
    ↓
硬件检查当前域的 exception_vector
    ↓
如果 exception_vector == 0
    ↓
异常传播到父域（递归）
    ↓
否则，跳转到 exception_vector
    ↓
父域从控制块读取异常信息
    ↓
父域处理异常
    ↓
父域执行 RETURN 返回子域
```

### 异常信息结构

当异常发生时，硬件在控制块中记录异常信息：

```
偏移    字段                说明
────    ─────               ────
0x80    exception_type      异常类型
0x84    exception_addr      触发异常的地址
0x88    exception_info      异常详情
```

---

## 与现有实现的差异

### 需要新增

1. **DomainBlock 结构** - 内存中的控制块
2. **sysop 指令** - 系统操作指令（按需添加）
3. **DESCEND 参数** - 从寄存器读取控制块地址
4. **异常传播机制** - 自动传播到父域

### 需要修改

1. **Level → Domain** - 重命名
2. **LevelConfig → DomainBlock** - 从 Python 对象改为内存结构
3. **ESCALATE 行为** - 跳转到父域 exception_vector，而非查找 handler
4. **上下文保存** - 硬件自动保存/恢复

### 需要删除

1. **service_handler 查找** - 不再需要，改为向量跳转
2. **Python 对象传递配置** - 改为内存控制块