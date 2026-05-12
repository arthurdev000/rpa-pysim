# RPA Simulator 开发笔记

## 当前状态：DomainBlock 重构完成

### 已完成的命名变更

| 旧名 | 新名 | 状态 |
|------|------|------|
| Level | Domain | ✅ 完成 |
| LevelConfig | DomainBlock | ✅ 完成 |
| root | root_domain | ✅ 完成 |
| current | current_domain | ✅ 完成 |
| ISADecoder | SimpleCore | ✅ 完成 |
| PhysicalMemory | Memory | ✅ 完成 |
| Emulator | ISADecoder | ✅ 完成 → SimpleCore |
| interrupt_ctrl_base | interrupt_ctrl | ✅ 完成 |
| pagetable_addr | (已删除) | ✅ 完成 |
| RPACore | RPALogic | ✅ 完成（别名已移除） |
| SimpleCore | SimpleISA | ✅ 完成 |
| emulator.py | isa_simple.py | ✅ 完成 |
| core.py | rpa_logic.py | ✅ 完成 |
| test_core.py | test_rpa.py | ✅ 完成 |

### 待论文修改的术语

以下术语已从代码中移除，论文中需要对应修改：

| 代码中已移除 | 论文中应使用 |
|-------------|-------------|
| Level | Domain |
| LevelConfig | DomainBlock |
| INHERIT | PageTableMode.INHERIT 或删除（概念上表示继承页表） |

### DomainBlock 字段 (32 字节, 32字节对齐)

| 偏移 | 字段 | 设置者 | 说明 |
|------|------|--------|------|
| 0x00 | ctrlblock_size | 父域 | 控制块大小（必须为32的倍数，DESCEND时验证） |
| 0x04 | domain_id | 系统 | 域ID（系统分配，DMA 访问控制使用此 ID） |
| 0x08 | exception_vector | 子域 | 异常向量（ASCEND/故障跳转地址，0=传播到父域） |
| 0x0C | interrupt_ctrl | 系统 | 中断控制器 handle |
| 0x10 | ipa_regions | 父域 | IPA 区域表地址（子域只读） |
| 0x14 | pagetable | 子域 | 页表地址（子域可写） |
| 0x18 | child_block | 父域 | 子域控制块地址（父域维护） |
| 0x1C | security_group | 系统 | 安全组 handle |

### ASCEND/RETURN 现场保存区域 (偏移 0x28 起，与安全组字段不冲突)

| 偏移 | 字段 | 说明 |
|------|------|------|
| 0x28 | saved_sp | ISA 保存的栈指针 (ASCEND) |
| 0x2C | saved_lr | ISA 保存的返回地址 (ASCEND) |
| 0x30 | saved_psr | ISA 保存的程序状态寄存器 |
| 0x34-0x3F | reserved | 保留 |

### 中断现场保存区域 (偏移 0x40 起)

| 偏移 | 字段 | 说明 |
|------|------|------|
| 0x40 | irq_saved_r0 | 中断保存 R0 |
| 0x44 | irq_saved_r1 | 中断保存 R1 |
| ... | ... | ... |
| 0x70 | irq_saved_r12 | 中断保存 R12 |
| 0x74 | irq_saved_sp | 中断保存 SP |
| 0x78 | irq_saved_lr | 中断保存 LR |
| 0x7C | irq_saved_pc | 中断保存 PC |
| 0x80 | irq_saved_psr | 中断保存 PSR |

### DESCEND 执行流程

**统一使用 saved_lr 作为入口点：**

1. **首次 DESCEND**：
   - 父域在执行 DESCEND 前将入口地址写入 saved_lr (0x24)
   - 子域从 saved_lr 开始执行
   - ISA 清零 callee-saved 寄存器（r4-r12）

2. **后续 DESCEND (RETURN)**：
   - 从 saved_lr 恢复返回地址（ASCEND 已保存）
   - 从 saved_sp 恢复栈指针
   - 从 saved_psr 恢复状态标志

### memtable_address 说明

- 父域告知子域可用的内存区域
- 子域如需建立映射：保存旧表 → 创建新表 → 更新此字段
- 更新动作表示新页表生效
- 值为 0 表示不建立新映射（try-catch 场合）

### child_block 说明

- 由父域维护，记录子域控制块地址
- 用于 RETURN 指令返回子域
- DESCEND 时自动写入父域的 child_block 字段
- **首次/后续 DESCEND 判断**：通过检查父域的 child_block 是否等于目标 block_addr 来判断
  - child_block == block_addr → 已有子域，RETURN 语义
  - child_block != block_addr → 首次 DESCEND，创建新域

### 页表属性 (rwx c)

页表项属性：
- r: 可读
- w: 可写
- x: 可执行
- c: control，硬件控制寄存器区域

**control 属性说明**：
- c=1 表示该内存区域是硬件控制寄存器
- control 区域必须使用 sysop 指令访问
- 常规 ldr/str 访问 control 区域会触发异常
- STDIO 设备的控制寄存器地址就是 control 类型

### 待补充测试

根据新设计，需要补充以下测试场景：

1. **控制块加载测试**
   - 父域在内存写入 DomainBlock
   - DESCEND 从内存读取配置
   - ctrlblock_size 验证测试

2. **ASCEND 向量跳转测试**
   - ASCEND 跳转到父域 exception_vector
   - 父域处理服务请求

3. **异常传播测试**
   - 子域异常传播到父域
   - 异常信息保存到控制块

4. **SYSOP 指令测试**
   - sysop irq, read/write
   - sysop memtable, read/write

5. **真实执行场景测试**
   - 完整的 descend → 执行 → ascend → 返回 流程
   - 多层嵌套执行

## 待办事项

### 参数传递检查 ✅ 已完成

检查 DomainBlock 参数传递是否正确：

1. **DESCEND 参数传递** ✅
   - ctrlblock_size 验证逻辑正确
   - 对齐检查正确（32字节）
   - 各字段读取顺序正确

2. **ASCEND/RETURN 调用约定** ✅
   - 子域 ASCEND：R0=service_type, R1-R3=参数
   - 父域 RETURN：R0-R3=返回值（含错误码）
   - 四个寄存器已足够，大数据用指针传递
   - 父域可通过子域控制块地址读取指针指向的数据

3. **跨域数据传递**
   - 寄存器传递：R0-R12, LR, SP 由 ISA 软件保存/恢复
   - 控制块传递：exception_vector, memtable_address 等
   - 输入字段：ctrlblock_size, exception_vector, interrupt_ctrl, memtable_address
   - 输出字段：domain_id (系统分配), child_block (父域维护)

4. **domain_id 分配** ✅
   - 自动递增分配（_next_domain_id）
   - 唯一性保证（每个新域分配新ID）
   - 写入控制块 0x14 偏移

5. **child_block 维护** ✅
   - DESCEND 时自动更新父域的 child_block 字段

## 控制块设计

详见 `docs/CONTROL_BLOCK_SPEC.md`

## 安全组设计讨论

### 概念区分

- **安全 (Security)**: 访问控制、隔离、权限管理
- **机密 (Confidential)**: 数据加密、密钥保护、防泄露

### 通用安全设置

1. **DESCEND 首次启动**
   - 父域清空不用于传递参数的寄存器（当前默认操作：清空 r4-r12）

2. **RETURN 返回子域**
   - 清除已使用且未作为返回值使用的 a0-a3 (R0-R3) 的痕迹

### 安全组系统架构

**核心原则**: memory 模块与域不是一对一关系，类似 interrupt 模块

**机密计算层设定**:
- root 域或硬件配置层可指定哪一层是机密计算层
- 当某层为子域设定机密计算层时，memory 模块比对 domain_id
- 应用内存加密机制

**domain_id 生成**:
- 由内存子系统生成（支持安全组系统时）
- 传入现有的 domain_id base，传出产生的值
- 本质仍是 +1，但确保不与已有安全组 id 重复
- root 域能够正确设计暗号机制

### 安全组生命周期

**创建**:
- 子域可与父域在同一安全组内
- 也可创建新的安全组
- 由内存系统决定

**销毁 (EXIT)**:
- 触发内存子系统的安全组销毁方法
- 彻底清零安全子域数据
- 共享内存段不清除（父域本就可访问）

**回收约束**:
- 安全组创建后，必须经过正常回收才能释放
- 父域释放时需等待安全子域退出完成
- 安全组系统故障时，只能由 root 域调用 memory 接口强制销毁该区域

**信息上报**:
- 父域程序通过寄存器上报
- 共享内存段传递数据

### 机密计算域

**加密机制**:
- 对内存进行加密
- 密钥由内建暗号机制确认
- root 域知道哪一层是机密域，但无法设置密钥

**DMA 访问控制**:
- sysops 操作 memory mapped register 时需检查权限
- DMA 等设备读取内存时比对 access id 或加解密密钥
- DMA 需要知道密钥并自行解密，避免总线上出现明文数据

### 待实现

- [x] memory 模块扩展支持安全组
- [x] domain_id 生成机制
- [x] 安全组创建/销毁接口
- [x] DMA 访问控制
- [x] 内存加密模拟
- [x] 解决 security_group 与 saved_sp 偏移冲突（ISA 保存区移至 0x28）
- [x] ~~实现中断返回指令 (IRET)~~ → 使用 bx lr 带标志位返回（更安全的编程模型）
- [ ] 实现中断嵌套优先级检查

## 2026-05-06: 安全组系统实现

### 新增文件
- `rpa_sim/security_group.py`: 安全组控制器模块
- `rpa_sim/encrpted_memory.py`: 加密内存区域（XOR 模拟）
- `tests/test_security_group.py`: 安全组测试（19 个测试用例）

### 新增数据结构
- `SecurityGroupConfig`: 安全组配置参数
- `SecurityGroup`: 安全组实例
- `SecurityGroupController`: 全局安全组控制器
- `EncryptedRegion`: 加密内存区域

### DomainBlock 扩展字段
| 偏移 | 字段 | 说明 |
|------|------|------|
| 0x20 | security_group | 安全组 handle |
| 0x24 | access_id | 访问 ID (DMA 用) |

**待解决问题**: 安全组字段 (0x20-0x27) 与 ISA saved_sp/saved_lr 偏移冲突。
建议调整方案：
1. 将 ISA 现场保存区移至 0x28 之后，或
2. 将 security_group/access_id 移至 DomainBlock 基本区域之后的扩展区

### sysop secdomain 子操作
| 操作码 | 名称 | 说明 |
|--------|------|------|
| 0x01 | CREATE | 创建安全组（flags: isolated/encrypted/confidential） |
| 0x02 | DESTROY | 销毁安全组（引用计数为 0） |
| 0x03 | BIND | 绑定域到安全组 |
| 0x04 | UNBIND | 解绑域 |
| 0x05 | GET_ID | 获取安全组的 domain_id |
| 0x06 | SET_ENCRYPTION | 设置加密区域 |
| 0x07 | ADD_ACCESSOR | 添加 DMA 访问者 |
| 0x08 | REMOVE_ACCESSOR | 移除访问者 |
| 0x09 | FORCE_DESTROY | 强制销毁（仅 root 域） |
| 0x0A | GET_HANDLE | 获取域的安全组 handle |

### 安全组特性
1. **Handle-based 访问**: 安全组 handle 从 0x2000 开始分配
2. **引用计数管理**: 绑定域时增加，解绑时减少
3. **回收约束**: 引用计数为 0 才能销毁；root 可强制销毁
4. **DMA 访问控制**:
   - 同一安全组内允许访问
   - 在 allowed_accessors 列表中允许
   - 机密计算域禁止外部访问
   - root 域不能访问机密计算域
5. **内存加密**: XOR 模拟加密，支持设置加密区域
6. **机密计算**: 密钥由内建暗号机制生成，root 域知道哪层是机密域但无法设置密钥

### domain_id 分配
- 无安全组系统: RPALogic 分配 (1, 2, 3...)
- 有安全组系统: SecurityGroupController 分配 (0x0100 起)
- 安全组 ID 与普通域 ID 分开管理，避免冲突

### Memory 扩展
- `Memory.set_encryption()`: 设置加密区域
- `Memory.clear_encryption_by_handle()`: 清除安全组的所有加密区域
- `Memory.get_encryption_region()`: 查询地址所属加密区域
- `MemoryManager` 转发加密相关调用

### DESCEND 集成
- RPALogic.set_security_controller(): 设置安全组控制器
- DESCEND 时自动绑定安全组
- 支持继承父域安全组或创建新安全组
- EXIT 时自动解绑安全组

## 已完成

### 2026-05-06: 中断控制器模块实现
- 新增 `interrupt.py` 模块
- `InterruptController`: 全局中断控制器
- `InterruptInstance`: 中断实例（通过 handle 访问）
- 权限控制: CONFIG, ENABLE, SGI
- sysop irq 指令: request, release, enable, disable, setvec, getpending, clear, sgi
- 中断现场保存区域 (0x40-0x83): R0-R15 + PSR
- ISA 每条指令后检查中断
- 从 DomainBlock 移除 `interrupt_vector`（改为保留字段）

### 2026-05-08: 中断返回机制设计

**设计决策：不使用特殊 IRET 指令**

原因：
- 程序员容易忘记在 ISR 中使用特殊指令导致编程错误
- ARM 等架构使用带标志位的返回地址，程序员无需关心

**实现方案：LR 带标志位**

```
中断进入时 RTL 操作：
1. 保存所有寄存器到 IRQ_SAVE_* 区域 (R0-R12, SP, LR, PC, PSR)
2. 清除 pending 位（中断被响应）
3. LR = saved_pc | IRQ_RETURN_FLAG (bit 31 = 0x80000000)
4. irq_disabled = True, in_interrupt = True
5. PC = vector

bx lr 执行时：
1. 检查 LR 是否有 IRQ_RETURN_FLAG
2. 如果有且 in_interrupt == True：
   - 调用 _restore_irq_context() 恢复所有寄存器
   - PC 从 saved_pc 恢复
   - irq_disabled = False, in_interrupt = False
3. 如果有但不在中断上下文：
   - PC = LR & ~IRQ_RETURN_FLAG
4. 如果没有标志：
   - 普通跳转 PC = LR
```

**优点**：
- ISR 直接使用 `bx lr` 返回，无需特殊指令
- 硬件自动恢复上下文，程序员无需手动处理
- 标志位防止误用（非中断上下文也能正确处理）

### 2026-05-06: 代码清理
- 移除 `RPACore` 向后兼容别名（统一使用 `RPALogic`）
- 移除未使用的 `complete_return` 方法
- 删除过时的示例文件（examples/ 目录，使用已废弃API）
- 更新 README.md 使用当前 API
- 版本保持 0.7.0

### 2026-05-05: EXIT 指令实现
- 新增 EXIT 指令：ASCEND + 释放子域
- EXIT 清空父子关系：parent.child_block = 0
- EXIT 清空子域 domain_id
- child_block 冲突检测：父域已有不同子域时报错
- 测试覆盖 EXIT 场景

### 2026-05-05: DomainBlock 重构
- 移除 status 字段（旧残留）
- 移除 reserved/padding 字段
- 添加 ctrlblock_size（必须设置，DESCEND时验证）
- 添加 domain_id（系统分配）
- 大小从 128 字节改为 32 字节
- 对齐从 64 字节改为 32 字节
- 移除 ISA 上下文保存（ISA自行管理）
- 版本更新到 0.7.0

### 2026-05-05: SimpleISA 简化
- rpa 参数变为必需
- 移除 descend_handler, ascend_handler, return_handler 回调
- 保留 sysop_handler, fault_handler 用于扩展

### 2026-05-07: 移除 parent_block 字段
- parent_block 字段未被实际使用（域导航通过 Python 对象引用）
- OFFSET_PARENT_BLOCK 改为 OFFSET_RESERVED_18（保留）
- DomainBlock.parent_block 字段移除
- 简化 descend/ascend 中的内存写入逻辑

### 2026-05-07: ISA 上下文保存区偏移调整
- 解决 security_group/access_id (0x20-0x27) 与 ISA 保存区冲突
- ISA 保存区从 0x20 移至 0x28
- SAVED_SP_OFFSET: 0x20 → 0x28
- SAVED_LR_OFFSET: 0x24 → 0x2C
- SAVED_PSR_OFFSET: 0x28 → 0x30

### 2026-05-01: 清理别名和冗余字段
- 删除 pagetable_addr 字段（与 memtable_addr 重复）
- 删除所有向后兼容别名（execution_addr, page_table, interrupt_controller）
- interrupt_ctrl_base 改名为 interrupt_ctrl
- 版本更新到 0.5.0

### 2026-04-30: 代码重构
- Level → Domain
- LevelConfig → DomainBlock
- ISADecoder → SimpleCore
- 新增 SYSOP 指令
- 精简测试，35个测试全部通过

### 2026-04-30: 控制块设计
- 完成 DomainBlock 结构定义（128字节）
- 定义 memtable 结构
- 定义 sysop irq/memtable 指令

## 2026-05-07: 地址空间与控制块语义澄清

### 控制块位置与所有权

**关键原则**：控制块 (Control Block) 由父域创建，存放在父域地址空间。

```
父域地址空间
├── control_block_A (为子域A创建)
│   ├── exception_vector    ← 子域可通过 SYSOP 修改
│   ├── interrupt_ctrl      ← 子域可通过 SYSOP 操作
│   ├── memtable_address    ← 定义子域可见的地址范围
│   ├── saved_sp/lr/psr     ← 硬件自动保存上下文
│   └── ...
├── control_block_B (为子域B创建)
└── 父域代码/数据

子域地址空间 (通过 memtable 映射的父域空间子集)
├── 子域代码
├── 子域数据
└── 子域页表 (存放在 IPA 空间)
```

**子域无法直接访问控制块**：
- 控制块在父域地址空间
- 子域通过 SYSOP 让硬件代理操作
- SYSOP 操作结果直接写入父域空间（通过 current_block 寄存器定位）

### 地址空间层次

```
┌─────────────────────────────────────────────────────────────┐
│ 真实物理地址 (PA)                                           │
│   ← 根域页表翻译                                            │
├─────────────────────────────────────────────────────────────┤
│ 父域地址空间 (父域视角的"物理地址")                          │
│   ← 父域页表翻译（如果有）                                   │
│   ← 子域 memtable 定义的子集                                │
├─────────────────────────────────────────────────────────────┤
│ 子域"物理地址" (IPA = Intermediate Physical Address)         │
│   ← 子域页表翻译                                            │
├─────────────────────────────────────────────────────────────┤
│ 子域虚拟地址 (VA)                                           │
└─────────────────────────────────────────────────────────────┘
```

**翻译链**：VA → IPA（子域页表）→ PA（父域 memtable）

**页表位置**：
- 子域页表存放在 IPA 空间（父域暴露给子域的区域）
- 子域写入页表基址寄存器的是 IPA 地址
- 父域 memtable 将 IPA 翻译为 PA

### IPA 边界检查

**问题**：子域需要知道可用地址范围，硬件需要检查访问是否越界。

**memtable 结构**：
- memtable 存放在**父域地址空间**
- 是一个**动态表**，可以有多个条目
- 控制块的 `memtable_address` 字段保存表首地址
- 每个条目定义一段可访问的地址范围

**字段分离**（安全设计）：

为防止子域绕过约束，控制块使用两个独立字段：

| 字段 | 设置者 | 权限 | 用途 |
|------|--------|------|------|
| ipa_regions | 父域 | 子域只读 | 定义可用的 IPA 范围约束 |
| pagetable | 子域 | 子域可写 | 子域创建的 VA→IPA 页表 |

子域创建页表时，硬件检查 IPA 是否在 ipa_regions 范围内。

**硬件检查**：翻译时检查 IPA 是否在 memtable 定义的范围内
- 在范围内：继续翻译
- 超出范围：触发 fault

**软件查询**：子域通过 SYSOP 遍历/查询 memtable
- `SYSOP memtable, query` 获取可用地址范围信息
- 用于显示可用内存、规划页表布局等

**注意**：不需要在控制块中新增 ipa_base/ipa_size 字段，因为 memtable 是动态多条目表。

### 硬件控制块模型

**原设想（已废弃）**：
- 硬件维护控制块栈，每个域占用固定位置
- 软件切换时复制数据到硬件控制块

**现在设计**：
- 硬件只维护 `current_block` 指针寄存器
- 控制块数据完全在内存
- DESCEND 时更新指针，硬件按指针访问控制块

**优势**：
- 简化硬件设计
- 软件灵活控制控制块位置
- 父域可以预先创建多个控制块

### 上下文保存策略

| 层面 | 策略 |
|------|------|
| 论文 | ISA + 调用标准决定（规范层面） |
| 实现 | 硬件自动备份 R0-R15, SP, LR, PSR（简化软件） |

**实现细节**：
- DESCEND：硬件保存父域上下文到父域控制块
- ASCEND：硬件保存子域上下文到子域控制块
- RETURN：硬件恢复子域上下文
- 中断：硬件保存上下文到中断保存区

### 待调整

- [x] 实现 `SYSOP memtable, query` 指令（子域查询可用地址范围）
- [x] 实现翻译时的 IPA 边界检查（超出 memtable 范围触发 fault）
- [ ] 完善内存区域表的数据结构（docs/CONTROL_BLOCK_SPEC.md 已定义格式）
- [ ] 更新测试覆盖新功能

## 2026-05-07: 实现 IPA 边界检查

### 设计背景

子域通过页表将 VA 翻译为 IPA，但 IPA 必须在父域分配的地址范围内。
如果 IPA 超出范围，应触发翻译错误。

### 实现方案

在 `MemoryManager.translate_chain()` 中，第一层翻译（VA→IPA）后检查 IPA 边界：
1. 如果 `ipa_regions == 0`，跳过边界检查（共享内存模式）
2. 遍历 IPA 区域表，检查 IPA 是否在任一区域内
3. 如果不在任何区域内，返回翻译错误

### 已修改文件

- `rpa_sim/memory.py`:
  - `translate_chain()`: 增加 `ipa_regions` 和 `memory` 参数
  - 新增 `_check_ipa_bounds()`: 遍历区域表检查边界
  - `read_with_translation()`: 传递 `ipa_regions` 参数
  - `write_with_translation()`: 传递 `ipa_regions` 参数

- `rpa_sim/isa_simple.py`:
  - `_execute_ldr()`: 传递 `ipa_regions` 到翻译函数
  - `_execute_str()`: 传递 `ipa_regions` 到翻译函数

### 测试覆盖

- `test_ipa_within_bounds`: IPA 在允许范围内，访问成功
- `test_ipa_out_of_bounds`: IPA 超出范围，触发 fault
- `test_ipa_no_regions_table`: 无区域表时不检查边界
- `test_ipa_multiple_regions`: 多区域场景

### IPA 区域表格式

每个条目 12 字节：
- offset 0x00: base (4 字节) - 区域起始地址
- offset 0x04: size (4 字节) - 区域大小
- offset 0x08: attr (4 字节) - 区域属性
- 以全零条目结尾

## 2026-05-07: 实现 SYSOP memtable/pagetable 指令

### 指令设计

```
sysop memtable, query, #index, #regmask
    - 读取 ipa_regions 表的第 index 个条目
    - regmask: 8-bit 位图，每位对应 R0-R7
    - 结果分配: base→最低位寄存器, size→中间, attr→最高位
    - 示例: regmask=0x07 (0b0111) → R0=base, R1=size, R2=attr
    - 示例: regmask=0x38 (0b00111000) → R3=base, R4=size, R5=attr

sysop memtable, count, Rd
    - 返回 ipa_regions 表的条目数到 Rd

sysop pagetable, query, #index, #regmask
    - 读取 pagetable 表的第 index 个条目（同上格式）

sysop pagetable, count, Rd
    - 返回 pagetable 表的条目数到 Rd
```

### 寄存器掩码编码

使用 8 位位图指定最多 3 个寄存器（R0-R7）：

| regmask | 二进制    | 寄存器分配 |
|---------|----------|-----------|
| 0x07    | 0b0111   | R0, R1, R2 |
| 0x0E    | 0b1110   | R1, R2, R3 |
| 0x38    | 0b111000 | R3, R4, R5 |
| 0x1C    | 0b11100  | R2, R3, R4 |

位图解析：找到置位位，按升序分配 base、size、attr。

### 操作码分配

| 操作 | 操作码 |
|-----|-------|
| IRQ | 0x01 |
| MEMTABLE | 0x02 |
| PAGETABLE | 0x03 |
| SECDOMAIN | 0x04 |

| 子操作 | 操作码 |
|-------|-------|
| QUERY | 0x10 |
| COUNT | 0x11 |

### 已修改文件

- `rpa_sim/isa_simple.py`:
  - 更新 op_codes 增加 MEMTABLE, PAGETABLE, SECDOMAIN
  - 更新 subop_codes 增加 QUERY, COUNT
  - 新增 `_execute_sysop_table()` 方法
  - 解析 regmask 位图编码
  - 从 ipa_regions 或 pagetable 读取条目

### 测试覆盖

- `test_sysop_memtable_query`: 基本查询功能
- `test_sysop_memtable_query_different_regs`: 不同寄存器掩码
- `test_sysop_memtable_count`: 条目计数
- `test_sysop_memtable_query_out_of_range`: 超出范围返回零
- `test_sysop_memtable_query_no_table`: 无表时返回零

## 2026-05-07: 命名重构 memtable_address → ipa_regions, memtable_chain → pagetable_chain

### 安全设计背景

原设计中 `memtable_address` 字段存在安全隐患：
- 子域可以修改该字段绕过父域设置的 IPA 约束
- 需要分离为两个字段：父域设置（只读）+ 子域设置（可写）

### 已完成的命名变更

| 旧名 | 新名 | 位置 | 说明 |
|------|------|------|------|
| memtable_address | ipa_regions | DomainBlock offset 0x10 | 父域设置，子域只读 |
| memtable_chain | pagetable_chain | SimpleISA 变量 | 页表翻译链 |
| (新增) | pagetable | DomainBlock offset 0x18 | 子域设置，子域可写 |

### 已修改文件

- `rpa_sim/memory.py`: 函数参数名 memtable_chain → pagetable_chain
- `rpa_sim/isa_simple.py`: 变量名和注释
- `rpa_sim/machine.py`: 方法名 get_memtable_chain → get_pagetable_chain
- `tests/test_rpa.py`: 所有引用
- `tests/test_isa_simple.py`: 所有引用
- `tests/test_thread_exception.py`: 大部分引用
- `README.md`: DomainBlock 字段表
- `docs/CONTROL_BLOCK_SPEC.md`: 字段定义和说明

### 测试修复 (2026-05-07)

`tests/test_thread_exception.py::TestMemoryTranslation::test_descend_with_memtable` 已修复：
- 重命名为 `test_descend_with_pagetable`
- 修正测试逻辑：`pagetable` 字段 (offset 0x18) 用于子域页表地址
- `ipa_regions` 字段 (offset 0x10) 用于父域设置的 IPA 约束
- 测试通过，所有 71 个测试全部通过