# RPA Simulator 开发笔记

## 当前状态：代码重构完成

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

### 待论文修改的术语

以下术语已从代码中移除，论文中需要对应修改：

| 代码中已移除 | 论文中应使用 |
|-------------|-------------|
| Level | Domain |
| LevelConfig | DomainBlock |
| INHERIT | PageTableMode.INHERIT 或删除（概念上表示继承页表） |

### DomainBlock 字段

| 偏移 | 字段 | 说明 |
|------|------|------|
| 0x00 | execution_address | 执行地址 |
| 0x04 | exception_vector | 异常向量 |
| 0x08 | interrupt_vector | 中断向量 |
| 0x0C | interrupt_ctrl | 中断控制器 |
| 0x10 | memtable_address | 内存区域表地址 |
| 0x14 | status | 状态码 (Decoder上报) |
| 0x18 | reserved | 保留 |
| 0x1C | padding | 填充 (对齐到0x20) |

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

## 控制块设计

详见 `docs/CONTROL_BLOCK_SPEC.md`

## 已完成

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