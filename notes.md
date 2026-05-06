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

### DomainBlock 字段 (28 字节 + 4 字节填充 = 32 字节, 32字节对齐)

| 偏移 | 字段 | 说明 |
|------|------|------|
| 0x00 | ctrlblock_size | 控制块大小（必须为32的倍数，DESCEND时验证） |
| 0x04 | exception_vector | 异常向量（ESCALATE/故障跳转地址） |
| 0x08 | reserved_08 | 保留（原 interrupt_vector） |
| 0x0C | interrupt_ctrl | 中断控制器 handle |
| 0x10 | memtable_address | 内存翻译表地址 |
| 0x14 | domain_id | 域ID（系统分配，调试用） |
| 0x18 | parent_block | 父域控制块地址（系统写入） |
| 0x1C | child_block | 子域控制块地址（父域维护） |

### ISA 扩展区域 (偏移 0x20 起)

| 偏移 | 字段 | 说明 |
|------|------|------|
| 0x20 | saved_sp | ISA 保存的栈指针 |
| 0x24 | saved_lr | ISA 保存的返回地址（首次DESCEND父域写入入口，ESCALATE保存返回地址） |
| 0x28 | saved_psr | ISA 保存的程序状态寄存器 |
| 0x2C-0x3F | reserved | 保留 |

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
   - 从 saved_lr 恢复返回地址（ESCALATE 已保存）
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

2. **ESCALATE 向量跳转测试**
   - ESCALATE 跳转到父域 exception_vector
   - 父域处理服务请求

3. **异常传播测试**
   - 子域异常传播到父域
   - 异常信息保存到控制块

4. **SYSOP 指令测试**
   - sysop irq, read/write
   - sysop memtable, read/write

5. **真实执行场景测试**
   - 完整的 descend → 执行 → escalate → 返回 流程
   - 多层嵌套执行

## 待办事项

### 参数传递检查 ✅ 已完成

检查 DomainBlock 参数传递是否正确：

1. **DESCEND 参数传递** ✅
   - ctrlblock_size 验证逻辑正确
   - 对齐检查正确（32字节）
   - 各字段读取顺序正确

2. **ESCALATE 返回值** ⚠️ 需要设计
   - service_type 通过 R0 寄存器传递给父域
   - 父域 exception_vector 处理程序需要从寄存器读取
   - 当前没有机制让父域获取子域其他状态（如错误码）
   - 建议：子域可将状态写入控制块扩展区域，父域通过控制块地址读取

3. **跨域数据传递**
   - 寄存器传递：R0-R12, LR, SP 由 ISA 软件保存/恢复
   - 控制块传递：exception_vector, memtable_address 等
   - 输入字段：ctrlblock_size, exception_vector, interrupt_vector, interrupt_ctrl, memtable_address
   - 输出字段：domain_id (系统分配), parent_block (系统写入), child_block (父域维护)

4. **domain_id 分配** ✅
   - 自动递增分配（_next_domain_id）
   - 唯一性保证（每个新域分配新ID）
   - 写入控制块 0x14 偏移

5. **child_block 维护** ✅
   - DESCEND 时自动更新父域的 child_block 字段
   - 同时更新子域的 parent_block 字段

## 控制块设计

详见 `docs/CONTROL_BLOCK_SPEC.md`

## 安全域设计讨论

### 概念区分

- **安全 (Security)**: 访问控制、隔离、权限管理
- **机密 (Confidential)**: 数据加密、密钥保护、防泄露

### 通用安全设置

1. **DESCEND 首次启动**
   - 父域清空不用于传递参数的寄存器（当前默认操作：清空 r4-r12）

2. **RETURN 返回子域**
   - 清除已使用且未作为返回值使用的 a0-a3 (R0-R3) 的痕迹

### 安全子系统架构

**核心原则**: memory 模块与域不是一对一关系，类似 interrupt 模块

**机密计算层设定**:
- root 域或硬件配置层可指定哪一层是机密计算层
- 当某层为子域设定机密计算层时，memory 模块比对 domain_id
- 应用内存加密机制

**domain_id 生成**:
- 由内存子系统生成（支持安全子系统时）
- 传入现有的 domain_id base，传出产生的值
- 本质仍是 +1，但确保不与已有安全域 id 重复
- root 域能够正确设计暗号机制

### 安全域生命周期

**创建**:
- 子域可与父域在同一安全域内
- 也可创建新的安全域
- 由内存系统决定

**销毁 (EXIT)**:
- 触发内存子系统的安全域销毁方法
- 彻底清零安全子域数据
- 共享内存段不清除（父域本就可访问）

**回收约束**:
- 安全域创建后，必须经过正常回收才能释放
- 父域释放时需等待安全子域退出完成
- 安全子系统故障时，只能由 root 域调用 memory 接口强制销毁该区域

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

- [x] memory 模块扩展支持安全域
- [x] domain_id 生成机制
- [x] 安全域创建/销毁接口
- [x] DMA 访问控制
- [x] 内存加密模拟

## 2026-05-06: 安全域系统实现

### 新增文件
- `rpa_sim/security_domain.py`: 安全域控制器模块

### 新增数据结构
- `SecurityDomainConfig`: 安全域配置参数
- `SecurityDomain`: 安全域实例
- `SecurityDomainController`: 全局安全域控制器

### DomainBlock 扩展字段
| 偏移 | 字段 | 说明 |
|------|------|------|
| 0x20 | security_domain | 安全域 handle |
| 0x24 | access_id | 访问 ID (DMA 用) |

### sysop secdomain 子操作
| 操作码 | 名称 | 说明 |
|--------|------|------|
| 0x01 | CREATE | 创建安全域 |
| 0x02 | DESTROY | 销毁安全域 |
| 0x03 | BIND | 绑定域到安全域 |
| 0x04 | UNBIND | 解绑 |
| 0x05 | GET_ID | 获取 domain_id |
| 0x06 | SET_ENCRYPTION | 设置加密 |
| 0x07 | ADD_ACCESSOR | 添加 DMA 访问者 |
| 0x08 | REMOVE_ACCESSOR | 移除访问者 |
| 0x09 | FORCE_DESTROY | 强制销毁（root only） |
| 0x0A | GET_HANDLE | 获取域的安全域 handle |

### 安全域特性
1. **Handle-based 访问**: 安全域 handle 从 0x2000 开始分配
2. **引用计数管理**: 绑定域时增加，解绑时减少
3. **回收约束**: 引用计数为 0 才能销毁；root 可强制销毁
4. **DMA 访问控制**: 同一安全域内允许；机密计算域禁止外部访问
5. **内存加密**: XOR 模拟加密，支持设置加密区域

### domain_id 分配
- 无安全子系统: RPALogic 分配 (1, 2, 3...)
- 有安全子系统: SecurityDomainController 分配 (0x0100 起)

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

### 2026-05-06: 代码清理
- 移除 `RPACore` 向后兼容别名（统一使用 `RPALogic`）
- 移除未使用的 `complete_return` 方法
- 删除过时的示例文件（examples/ 目录，使用已废弃API）
- 更新 README.md 使用当前 API
- 版本保持 0.7.0

### 2026-05-05: EXIT 指令实现
- 新增 EXIT 指令：ESCALATE + 释放子域
- EXIT 清空父子关系：parent.child_block = 0, child.parent_block = 0
- EXIT 清空子域 domain_id
- child_block 冲突检测：父域已有不同子域时报错
- 测试覆盖 EXIT 场景

### 2026-05-05: DomainBlock 重构
- 移除 status 字段（旧残留）
- 移除 reserved/padding 字段
- 添加 ctrlblock_size（必须设置，DESCEND时验证）
- 添加 domain_id（系统分配）
- 添加 parent_block（可选）
- 大小从 128 字节改为 32 字节
- 对齐从 64 字节改为 32 字节
- 移除 ISA 上下文保存（ISA自行管理）
- 版本更新到 0.7.0

### 2026-05-05: SimpleISA 简化
- rpa 参数变为必需
- 移除 descend_handler, escalate_handler, return_handler 回调
- 保留 sysop_handler, fault_handler 用于扩展

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