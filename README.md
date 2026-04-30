# RPA Simulator

Recursive Privilege Architecture (RPA) 概念验证模拟器。

## 项目结构

```
rpa-sim/
├── .pyvenv/              # Python虚拟环境
├── rpa_sim/              # 核心模拟器
│   ├── __init__.py
│   ├── core.py           # RPA核心原语实现
│   ├── arm_emulator.py   # 简化ARM指令解释器
│   └── memory.py         # 内存管理
├── tests/                # 单元测试
│   └── test_core.py
├── examples/             # 演示案例
│   ├── nested_virtualization.py
│   ├── syscall_demo.py
│   └── try_catch_demo.py
├── requirements.txt
└── README.md
```

## 安装

```bash
# 激活虚拟环境
source .pyvenv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

## 快速开始

```python
from rpa_sim import RPACore

# 创建RPA核心
rpa = RPACore()

# 配置子层
rpa.configure_sublayer(0, entry=0x1000, exception_vector=0x2000)

# 进入子层
rpa.descend({"operation": "test"})

# 子层请求上层服务
rpa.escalate({"request": "read_file", "path": "/etc/config"})

# 返回结果
result = rpa.get_result()
```

## 测试案例

### 案例1：嵌套虚拟化
演示多层descend/escalate，模拟Host → Hypervisor → Guest OS → App的层级结构。

### 案例2：系统调用
演示共享页表的快速系统调用，escalate成本接近函数调用。

### 案例3：Try-Catch
演示使用子层实现try-catch机制，异常通过escalate上报。

## 运行测试

```bash
# 激活虚拟环境
source .pyvenv/bin/activate

# 运行所有测试
python -m pytest tests/

# 运行演示案例
python examples/nested_virtualization.py
python examples/syscall_demo.py
python examples/try_catch_demo.py
```

## RPA原语

| 原语 | 说明 |
|------|------|
| `descend(params)` | 进入子层，params传递给子层 |
| `escalate(params)` | 请求上层服务，params传递给上层 |

## 配置结构

```python
level_config = {
    "service_vector": addr,      # 服务请求入口
    "exception_vector": addr,    # 异常入口
    "sub": [
        {
            "entry": addr,
            "exception_vector": addr,
            "page_table": INHERIT | addr,
        },
    ],
}
```

## 参考

详见 `../TECHNICAL_SPEC.md` 完整技术规范。