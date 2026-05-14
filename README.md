# RPA Simulator

Recursive Privilege Architecture (RPA) 可执行规范与概念验证模拟器。

## 项目定位

本项目是 RPA 架构的**可执行规范 (executable specification)**，用于：

1. **语义验证**：84 个测试用例证明 RPA 原语语义正确性
2. **设计文档**：代码即规范，精确描述 RPA 原语行为
3. **可复现研究**：支持独立验证和后续研究

本项目**不是**周期精确模拟器。性能评估请参考 gem5 等专业工具。

## 项目结构

```
rpa-sim/
├── rpa_sim/              # 核心模拟器
│   ├── __init__.py       # 包导出
│   ├── rpa_logic.py      # RPA核心原语实现
│   ├── isa_simple.py     # 简化ISA解释器
│   ├── memory.py         # 内存和页表管理
│   ├── machine.py        # 完整机器集成
│   ├── security_group.py # 安全组机制
│   ├── interrupt.py      # 中断控制器
│   └── stdio.py          # 标准IO设备
├── tests/                # 单元测试 (84个测试用例)
│   ├── test_rpa.py       # RPA核心测试
│   ├── test_isa_simple.py # ISA测试
│   ├── test_security_group.py # 安全组测试
│   └── test_thread_exception.py # 线程异常测试
├── docs/                 # 文档
│   ├── CONTROL_BLOCK_SPEC.md # 控制块规范
│   ├── SECURITY_GROUP_SPEC.md # 安全组规范
│   └── DCB_DESIGN_ANALYSIS.md # 设计分析
├── LICENSE               # MIT License
├── requirements.txt
└── README.md
```

## 安装

```bash
pip install -r requirements.txt
```

## 快速开始

```python
from rpa_sim import RPALogic, DomainBlock, Memory, SimpleISA

# 创建RPA核心和内存
mem = Memory(size=64 * 1024)
rpa = RPALogic()
rpa.memory = mem

# 设置子域控制块
block_addr = 0x1000
mem.write_word(block_addr + 0x00, 32)      # ctrlblock_size
mem.write_word(block_addr + 0x10, 0)       # ipa_regions
mem.write_word(block_addr + 0x2C, 0x2000)  # saved_lr (入口地址)

# 创建ISA核心并执行
core = SimpleISA(rpa=rpa, memory=mem)
core.load_assembly("MOV R0, #0x1000\nDESCEND R0", base_addr=0)
core.run()
```

## RPA 核心原语

| 指令 | 说明 |
|------|------|
| `DESCEND Rn` | 进入子域，Rn 为子域控制块地址 |
| `ASCEND Rn` | 请求父域服务，Rn 为服务类型 |
| `RETURN Rn` | 从父域返回子域，Rn 为子域控制块地址 |
| `EXIT Rn` | 退出子域并释放资源，Rn=0 |

## DomainBlock 内存布局

| 偏移 | 字段 | 设置者 | 说明 |
|------|------|--------|------|
| 0x00 | ctrlblock_size | 父域 | 控制块大小（必须为32的倍数） |
| 0x04 | domain_id | 系统 | 域ID（系统分配） |
| 0x08 | trap_vector | 子域 | 异常向量（子域设置） |
| 0x0C | interrupt_ctrl | 系统 | 中断控制器 handle |
| 0x10 | ipa_regions | 父域 | IPA 区域表地址（子域只读） |
| 0x14 | pagetable | 子域 | 页表地址（子域可写） |
| 0x18 | child_block | 父域 | 子域控制块地址（父域维护） |
| 0x1C | security_group | 系统 | 安全组 handle |
| 0x20 | access_id | 系统 | 访问 ID (DMA 用) |
| 0x24 | saved_sp | ISA | 保存的栈指针 |
| 0x28 | saved_lr | ISA | 保存的返回地址 |
| 0x2C | saved_psr | ISA | 保存的程序状态 |

## 测试覆盖

```bash
# 运行所有测试
python -m pytest tests/ -v

# 生成覆盖率报告
python -m pytest tests/ --cov=rpa_sim --cov-report=html
```

### 测试覆盖范围

| 模块 | 测试内容 |
|------|----------|
| `test_rpa.py` | 域操作 (descend/ascend/return/exit)、页表翻译、IPA边界检查 |
| `test_isa_simple.py` | ISA指令执行、内存翻译、中断处理 |
| `test_security_group.py` | 安全组创建、证明验证、加密内存、DMA访问控制 |
| `test_thread_exception.py` | 线程异常处理 |

## 学术引用

如果您在学术研究中使用本项目，请引用：

```bibtex
@software{rpa-sim2025,
  author = {Liu, Yongkang},
  title = {RPA Simulator: Executable Specification for Recursive Privilege Architecture},
  year = {2025},
  publisher = {GitHub},
  url = {https://github.com/TODO/rpa-sim}
}
```

DOI 将在正式发布后通过 Zenodo 分配。

## 相关文档

- `docs/CONTROL_BLOCK_SPEC.md` - DomainBlock 详细规范
- `docs/SECURITY_GROUP_SPEC.md` - 安全组机制规范
- `notes.md` - 设计笔记

## 许可证

MIT License - 详见 [LICENSE](LICENSE)

## 参考

本实现基于 RPA 技术规范，详见相关论文。