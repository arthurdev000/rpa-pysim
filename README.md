# RPA Simulator

Recursive Privilege Architecture (RPA) 概念验证模拟器。

## 项目结构

```
rpa-sim/
├── rpa_sim/              # 核心模拟器
│   ├── __init__.py       # 包导出
│   ├── rpa_logic.py      # RPA核心原语实现
│   ├── isa_simple.py     # 简化ISA解释器
│   ├── memory.py         # 内存和页表管理
│   ├── machine.py        # 完整机器集成
│   └── stdio.py          # 标准IO设备
├── tests/                # 单元测试
│   ├── test_rpa.py       # RPA核心测试
│   ├── test_isa_simple.py # ISA测试
│   └── test_thread_exception.py # 线程异常测试
├── docs/                 # 文档
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
mem.write_word(block_addr + 0x04, 0x3000)  # exception_vector
mem.write_word(block_addr + 0x10, 0)       # memtable_address
mem.write_word(block_addr + 0x24, 0x2000)  # saved_lr (入口地址)

# 创建ISA核心并执行
core = SimpleISA(rpa=rpa, memory=mem)
core.load_assembly("MOV R0, #0x1000\nDESCEND R0", base_addr=0)
core.run()
```

## RPA原语

| 指令 | 说明 |
|------|------|
| `DESCEND Rn` | 进入子域，Rn为子域控制块地址 |
| `ESCALATE Rn` | 请求父域服务，Rn为服务类型 |
| `RETURN Rn` | 从父域返回子域，Rn为子域控制块地址 |
| `EXIT Rn` | 退出子域并释放资源，Rn=0 |

## DomainBlock 内存布局

| 偏移 | 字段 | 说明 |
|------|------|------|
| 0x00 | ctrlblock_size | 控制块大小（必须为32的倍数） |
| 0x04 | exception_vector | 异常向量 |
| 0x08 | reserved_08 | 保留 |
| 0x0C | interrupt_ctrl | 中断控制器 |
| 0x10 | memtable_address | 内存翻译表地址 |
| 0x14 | domain_id | 域ID（系统分配） |
| 0x18 | reserved_18 | 保留（原 parent_block） |
| 0x1C | child_block | 子域控制块地址（父域维护） |
| 0x20 | security_domain | 安全域 handle |
| 0x24 | access_id | 访问 ID (DMA 用) |
| 0x28 | saved_sp | 保存的栈指针（ISA扩展） |
| 0x2C | saved_lr | 保存的返回地址（ISA扩展） |
| 0x30 | saved_psr | 保存的程序状态（ISA扩展） |

## 运行测试

```bash
python -m pytest tests/ -v
```

## 参考

详见 `docs/CONTROL_BLOCK_SPEC.md` 和 `notes.md`。