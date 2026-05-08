# Domain Control Block 设计分析

## 设计原则

DCB 是硬件管理域状态的核心存储空间。硬件没有无限的动态分配能力，需要 DCB 提供固定位置存储关键信息。

**核心问题**：哪些项目必须存在 DCB 中？

**判断标准**：
1. 硬件需要快速访问，不能每次都动态分配/查找
2. 跨域切换时需要保存/恢复
3. 父域需要设置约束，子域只能读取或有限修改

---

## 子系统分析

### 1. 内存子系统 (Memory)

| 字段 | 设置者 | 权限 | 用途 |
|------|--------|------|------|
| `ipa_regions` | 父域 | 子域只读 | 定义可用的 IPA 范围约束 |
| `pagetable` | 子域 | 子域可写 | 子域创建的 VA→IPA 页表地址 |

**分析**：
- `ipa_regions`：硬件翻译时需要检查 IPA 边界，必须快速访问
- `pagetable`：硬件翻译时需要读取页表基址，必须快速访问
- 结论：**两个字段都必须在 DCB 中**

### 2. 异常子系统 (Exception)

| 字段 | 设置者 | 权限 | 用途 |
|------|--------|------|------|
| `exception_vector` | 子域 | 子域可写 | 异常处理入口地址 |

**设计决策**：**不需要 `exception_mask` 字段**

**理由**：
- 软件错误（page fault, illegal instruction）：默认由子域处理
- 硬件错误（bus error）：子域无法处理，自动传播到父域
- ESCALATE 请求：子域主动请求父域服务
- 结论：**只需 `exception_vector`，异常掩码不必要**

### 3. 中断子系统 (Interrupt)

当前设计：`interrupt_ctrl` 存储中断控制器实例的 handle

**中断控制器内部存储**：
- `vector`: 中断向量
- `irq_enable`: I-bit
- `pending`: 待处理位图
- `permissions`: 权限

**分析**：
- 中断控制器是独立模块，通过 handle 访问
- 实例内部有足够空间存储状态
- DCB 只需存储 handle 即可
- 结论：**现有 `interrupt_ctrl` 字段足够**

### 4. 域标识 (Domain Identity)

| 字段 | 设置者 | 用途 |
|------|--------|------|
| `domain_id` | 系统分配 | 全局唯一域标识符，用于 DMA 访问控制、安全域绑定 |
| `ctrlblock_size` | 父域设置 | 控制块大小（用于校验） |

**分析**：
- `domain_id`：用于 DMA 访问控制、安全域绑定等
- DMA 访问验证直接使用 `domain_id`，无需单独 `access_id`
- `ctrlblock_size`：用于验证控制块有效性
- 结论：**保留现有字段，移除 access_id**

### 5. 域关系 (Domain Relations)

| 字段 | 设置者 | 用途 |
|------|--------|------|
| `child_block` | 父域维护 | 子域控制块地址 |

**分析**：
- 用于 RETURN 指令返回子域
- 用于判断首次/后续 DESCEND（child_block == block_addr 表示已有子域）
- 实现一父一子约束（child_block 非零时不允许创建新子域）
- 结论：**必须保留**

### 6. 安全子系统 (Security)

当前设计：`security_domain` 存储安全域 handle

**决策**：
- 保留 `security_domain`：绑定安全域
- **移除 `access_id`**：DMA 访问使用 `domain_id` 验证
- 加密区域信息存储在内存管理器中，不需要 DCB 字段

### 7. Flags 字段

**决策**：**暂不实现**

**理由**：
- 部分状态（如 in_interrupt）由 ISA 维护
- 需要时可动态查询各模块接口
- 优先级较低，后续有需要再添加

---

## 最终布局（32 字节）

```
偏移    字段              设置者    用途
------  ---------------   --------  ------------------------------------------
0x00    ctrlblock_size    父域      控制块大小（校验用）
0x04    domain_id         系统      域ID（DMA 访问控制使用此 ID）

--- 异常子系统 ---
0x08    exception_vector  子域      异常向量（0 = 传播到父域）

--- 中断子系统 ---
0x0C    interrupt_ctrl    系统      中断控制器 handle

--- 内存子系统 ---
0x10    ipa_regions       父域      IPA 区域表地址（子域只读）
0x14    pagetable         子域      页表地址（子域可写）

--- 域关系 ---
0x18    child_block       父域      子域控制块地址（父域维护）

--- 安全子系统 ---
0x1C    security_domain   系统      安全域 handle
```

**总大小**：32 字节（8 个 4 字节字段）

**ISA 上下文保存区**（DCB 之后）：
- 0x28: saved_sp（ESCALATE 保存的栈指针）
- 0x2C: saved_lr（ESCALATE 保存的返回地址）
- 0x30: saved_psr（ESCALATE 保存的程序状态寄存器）

---

## 字段设置者汇总

| 设置者 | 字段 |
|--------|------|
| 父域设置 | ctrlblock_size, ipa_regions, child_block |
| 子域设置 | exception_vector, pagetable |
| 系统分配 | domain_id, interrupt_ctrl, security_domain |

---

## SYSOP 操作对象总结

### 已实现的操作对象

| 对象 | 操作码 | 子操作 | 说明 |
|------|--------|--------|------|
| IRQ | 0x01 | READ, WRITE, ENABLE, DISABLE, SETVEC, GETPENDING, CLEAR, REQUEST, RELEASE, SGI | 中断控制 |
| MEMTABLE | 0x02 | QUERY, COUNT | IPA 区域表查询 |
| PAGETABLE | 0x03 | QUERY, COUNT | 页表查询 |
| SECDOMAIN | 0x04 | CREATE, DESTROY, BIND, UNBIND, GET_ID, SET_ENCRYPTION, ADD_ACCESSOR, REMOVE_ACCESSOR, FORCE_DESTROY, GET_HANDLE | 安全域管理 |

### 待实现操作对象

| 对象 | 建议操作码 | 子操作 | 说明 |
|------|------------|--------|------|
| DOMAIN | 0x06 | GET_ID, GET_DEPTH | 域信息查询 |

---

## 模块接口规范

### Memory 接口
```python
# 通过 DCB 字段访问
ipa_regions = dcb[0x10]  # 只读
pagetable = dcb[0x14]    # 可写

# SYSOP memtable, query, #index, #regmask
# SYSOP memtable, count, Rd
# SYSOP pagetable, query, #index, #regmask
# SYSOP pagetable, count, Rd
```

### Exception 接口
```python
# 通过 DCB 字段访问
exception_vector = dcb[0x08]  # 可写（子域设置）
# 为 0 时异常传播到父域
```

### Interrupt 接口
```python
# 通过 handle 访问中断控制器实例
interrupt_ctrl = dcb[0x0C]  # handle

# SYSOP irq, request, #perms, Rd    # 申请实例，返回 handle
# SYSOP irq, release, #handle
# SYSOP irq, enable, #handle
# SYSOP irq, disable, #handle
# SYSOP irq, setvec, #handle, #vec
# SYSOP irq, getpending, #handle, Rd
# SYSOP irq, clear, #handle, #irq_num
# SYSOP irq, sgi, #from_handle, #to_handle, #irq_num
```

### Security 接口
```python
# 通过 handle 访问安全域实例
security_domain = dcb[0x1C]  # handle

# SYSOP secdomain, create, #flags, Rd
# SYSOP secdomain, destroy, #handle
# SYSOP secdomain, bind, #handle
# SYSOP secdomain, unbind, #handle
# SYSOP secdomain, get_id, Rd
# SYSOP secdomain, set_encryption, #start, #size
# SYSOP secdomain, add_accessor, #handle, #domain_id
# SYSOP secdomain, remove_accessor, #handle, #domain_id
```

---

## 实现完成清单

### 已完成

- [x] 移除 `access_id` 字段：DMA 使用 `domain_id`
- [x] 移除 `reserved` 字段
- [x] 移除 `exception_mask` 字段：默认传播规则足够
- [x] 重新排列字段：按子系统组织（异常→中断→内存→域关系→安全）
- [x] 更新 `_read_domain_block` 和 `_write_domain_block` 方法
- [x] 更新 DomainBlock 数据类
- [x] 更新常量定义（偏移量）

### 待完成

- [ ] 更新测试用例适配新偏移量
- [ ] 实现 `SYSOP domain` 操作（获取域信息）

---

## 遗留问题

1. **ISA 上下文保存区位置**：当前在 0x28-0x30，是否需要保留扩展空间？
2. **中断现场保存区位置**：当前在 0x40-0x83，是否需要调整？
3. **安全子系统加密区域**：是否需要 DCB 字段还是完全通过内存管理器管理？