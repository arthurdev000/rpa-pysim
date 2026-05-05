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
| RPACore | RPALogic | ✅ 完成 |
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

| 偏移 | 字段 | 说明 |
|------|------|------|
| 0x00 | ctrlblock_size | 控制块大小（必须为32的倍数，DESCEND时验证） |
| 0x04 | execution_address | 执行入口地址 |
| 0x08 | exception_vector | 异常向量（ESCALATE/故障跳转地址） |
| 0x0C | interrupt_vector | 中断向量 |
| 0x10 | interrupt_ctrl | 中断控制器 |
| 0x14 | memtable_address | 内存翻译表地址 |
| 0x18 | domain_id | 域ID（系统分配，调试用） |
| 0x1C | parent_block | 父域控制块地址（可选） |

### memtable_address 说明

- 父域告知子域可用的内存区域
- 子域如需建立映射：保存旧表 → 创建新表 → 更新此字段
- 更新动作表示新页表生效
- 值为 0 表示不建立新映射（try-catch 场合）

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

### 参数传递检查

检查 DomainBlock 参数传递是否正确：

1. **DESCEND 参数传递**
   - ctrlblock_size 验证逻辑
   - 对齐检查
   - 各字段读取顺序

2. **ESCALATE 返回值**
   - 确认 ESCALATE 后父域如何获取子域状态
   - service_type 传递机制

3. **跨域数据传递**
   - 寄存器传递 vs 内存传递
   - 控制块中哪些字段是输入/输出

4. **domain_id 分配**
   - 自动分配逻辑
   - 唯一性保证

## 控制块设计

详见 `docs/CONTROL_BLOCK_SPEC.md`

## 已完成

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