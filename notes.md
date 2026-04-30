# RPA Simulator 开发笔记

## 待办事项

### 测试文件更新
- `tests/test_emulator.py` 仍引用旧名称 `PhysicalMemory`，需要更新为 `Memory`
- 运行测试前需更新所有测试文件的 import 语句

## 已完成

### 2026-04-30: 重命名和新类
- `PhysicalMemory` → `Memory` (更准确，因为包含 MMU 页表管理)
- `Emulator` → `ISADecoder` (反映其作为指令解码器的角色)
- 新增 `Machine` 类，集成 `RPACore`、`Memory`、`ISADecoder`
- 无向后兼容别名（干净的重命名）