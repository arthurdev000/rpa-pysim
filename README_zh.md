# RPA Simulator

Recursive Privilege Architecture (RPA) 可执行规范与概念验证模拟器。

[English Documentation](README.md)

## 项目定位

本项目是 RPA 架构的**可执行规范 (executable specification)**，用于：

1. **语义验证**：90+ 个测试用例证明 RPA 原语语义正确性
2. **设计文档**：代码即规范，精确描述 RPA 原语行为
3. **可复现研究**：支持独立验证和后续研究

本项目**不是**周期精确模拟器。性能评估请参考 gem5 等专业工具。

## 核心特性

- **RPA 原语**：`DESCEND`、`ASCEND`、`RETURN`、`EXIT`
- **DomainBlock**：32 字节控制结构，父子域所有权模型
- **页表叠加**：多级地址翻译与链式遍历
- **IPA 边界检查**：硬件强制的域间内存隔离
- **安全组**：加密、DMA 访问控制、机密域支持
- **中断控制器**：优先级中断处理与域隔离

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

RPA Spec Field（固定 8 words，32 字节）：

| 偏移 | 字段 | 设置者 | 说明 |
|------|------|--------|------|
| 0x00 | ctrlblock_size | 父域 | 控制块大小（单位：word，最小8） |
| 0x04 | domain_id | 系统 | 域ID（DMA访问控制使用） |
| 0x08 | trap_vector | 子域 | Trap处理入口（0=传播到父域） |
| 0x0C | interrupt_ctrl | 系统 | 中断控制器 handle |
| 0x10 | ipa_regions | 父域 | IPA区域表地址（子域只读） |
| 0x14 | pagetable | 子域 | 页表地址（子域可写） |
| 0x18 | child_block | 父域 | 子域控制块地址（父域维护） |
| 0x1C | security_group | 系统 | 安全组 handle |

ISA Context Field（平台相关，紧随 RPA Spec Field 之后）：由具体 ISA 实现定义。

## 项目结构

```
rpa-pysim/
├── rpa_sim/              # 核心模拟器
│   ├── __init__.py       # 包导出
│   ├── rpa_logic.py      # RPA核心原语实现
│   ├── isa_simple.py     # 简化ISA解释器
│   ├── memory.py         # 内存和页表管理
│   ├── machine.py        # 完整机器集成
│   ├── security_group.py # 安全组机制
│   ├── interrupt.py      # 中断控制器
│   └── stdio.py          # 标准IO设备
├── tests/                # 单元测试 (90+个测试用例)
│   ├── test_rpa.py       # RPA核心测试
│   ├── test_isa_simple.py # ISA测试
│   ├── test_security_group.py # 安全组测试
│   └── test_thread_exception.py # 线程异常测试
├── docs/                 # 文档
│   ├── CONTROL_BLOCK_SPEC.md # 控制块规范
│   ├── SECURITY_GROUP_SPEC.md # 安全组规范
│   ├── IMPLEMENTATION_GUIDE.md # 实现解读
│   └── CONFIDENTIAL_DESTROY_DESIGN.md # 机密域销毁设计
├── LICENSE               # MIT License
├── pyproject.toml        # 项目配置
├── requirements.txt
└── README.md
```

## 测试

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
| `test_thread_exception.py` | 线程异常处理、多级翻译、故障处理 |

## 学术引用

如果您在学术研究中使用本项目，请引用：

```bibtex
@software{rpa-pysim2025,
  author = {Liu, Yongkang},
  title = {RPA-PySim: Executable Specification for Recursive Privilege Architecture},
  year = {2025},
  publisher = {GitHub},
  url = {https://github.com/arthurdev000/rpa-pysim}
}
```

## 相关文档

- `docs/CONTROL_BLOCK_SPEC.md` - DomainBlock 详细规范
- `docs/SECURITY_GROUP_SPEC.md` - 安全组机制规范
- `docs/IMPLEMENTATION_GUIDE.md` - 实现解读
- `docs/CONFIDENTIAL_DESTROY_DESIGN.md` - 机密域销毁设计
- `notes.md` - 设计笔记

## License

MIT License - 详见 [LICENSE](LICENSE)

## 致谢

AI assisted by GLM5.
