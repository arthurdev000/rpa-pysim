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
0x00    entry_addr            4       入口地址
0x04    exception_vector      4       异常向量
0x08    interrupt_vector      4       中断向量
0x0C    interrupt_ctrl        4       中断控制器
0x10    memtable_addr         4       内存区域表地址
0x14    reserved              4       保留
0x18    reserved_0[8]         36      保留

────── 子域可写区域 ──────
0x3C    saved_pc              4       保存的 PC
0x40    saved_lr              4       保存的 LR
0x44    saved_sp              4       保存的 SP
0x48    saved_r0              4       保存的 R0
0x4C    saved_r1              4       保存的 R1
...     saved_r2-r12          44      保存的 R2-R12
0x78    saved_flags           4       保存的条件标志
0x7C    return_value          4       返回值
```

### 字段详解

#### entry_addr (0x00)
- 子域开始执行的地址
- DESCEND 后硬件跳转到此地址
- 必须是有效的代码地址

#### exception_vector (0x04)
- 异常处理入口地址
- 所有非中断异常（包括 ESCALATE）跳转到此地址
- 值为 0 表示禁用异常处理，异常直接传播到父域

#### interrupt_vector (0x08)
- 中断处理入口地址
- 外部中断发生时跳转到此地址
- 仅当 interrupt_ctrl != 0 时有效

#### interrupt_ctrl (0x0C)
- 中断控制器
- 值为 0：子域不能操作中断控制器
- 值为 非0：子域可以通过 `sysop irq` 操作中断

#### memtable_addr (0x10)
- 内存区域表地址
- 父域告知子域可用的内存区域
- 子域如需建立映射：保存旧表 → 创建新表 → 更新此字段（更新动作表示生效）
- 值为 0：不建立新映射（try-catch 场合）

#### reserved (0x14)
- 保留字段

#### 保存区域 (0x3C - 0x78)
- ESCALATE/异常发生时，硬件自动保存当前 Domain 的寄存器
- 父域可以读写此区域
- DESCEND 返回时自动恢复

#### return_value (0x7C)
- ESCALATE 时存放服务请求类型
- 父域处理完成后存放返回值

---

## 内存区域表（Memtable）

描述 Domain 可用的地址空间。

```
偏移    字段名          大小    说明
────    ──────          ────    ────
0x00    count           4       条目数量
0x04    reserved        4       保留
0x08    entry_0         12      第一个条目
0x14    entry_1         12      第二个条目
...     ...             ...     ...
```

每个条目（12 字节）：

```
偏移    字段名          大小    说明
────    ──────          ────    ────
0x00    base            4       基地址
0x04    size            4       大小
0x08    attr            4       属性
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

控制块本身必须位于某个 memtable 条目描述的区域内：

```
memtable_addr 指向的表中，
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

### 已定义操作

#### irq - 中断操作

```
sysop irq, read, #irq_id, Rd      ; 读取中断 irq_id 的信息
sysop irq, write, #irq_id, Rs     ; 写入中断 irq_id 的设置
```

权限检查：
- 如果 interrupt_ctrl == 0，触发异常

#### memtable - 内存区域操作

```
sysop memtable, read, #index, Rd   ; 读取第 index 个内存区域
sysop memtable, write, #index, Rs  ; 写入第 index 个内存区域
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
   - 地址对齐到 64 字节
   - entry_addr 有效
3. 硬件操作：
   - 保存当前 PC 到父域控制块的 saved_pc
   - 设置当前 Domain 为新 Domain
   - 跳转到 entry_addr
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