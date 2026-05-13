# Security Group 设计规范

## 概述

Security Group（安全组）是 RPA 架构中的统一安全隔离机制，将 CPU Domain 和各类外设（DMA、GPU、PCIe 设备等）统一为"访问者"(Accessor)，通过内存管理器进行统一的访问控制。

## 核心概念

### 访问者 (Accessor)

所有访问内存的实体统一抽象为"访问者"：

| 访问者类型 | ID 类型 | 说明 |
|-----------|---------|------|
| CPU Domain | domain_id | 由 RPA 分配，DESCEND 时自动生成 |
| DMA 设备 | device_id | 由系统分配，外设初始化时注册 |
| GPU | device_id | 由系统分配，GPU 初始化时注册 |
| PCIe 设备 | device_id | 由系统分配，设备枚举时注册 |

**统一接口**：所有访问者通过 `accessor_id` 标识，内存管理器统一检查权限。

### 安全组 (Security Group)

安全组是一组可以互相访问内存的访问者集合：

```
Security Group A                    Security Group B
┌─────────────────────┐            ┌─────────────────────┐
│ Domain 1 (CPU)      │            │ Domain 3 (CPU)      │
│ DMA Controller 0    │            │ GPU 0               │
│ PCIe Device 2       │            │ PCIe Device 5       │
└─────────────────────┘            └─────────────────────┘
        │                                  │
        │ 组内可互相访问                    │ 组内可互相访问
        │                                  │
        └──────────── X ──────────────────┘
              组间默认隔离
              需显式授权才能访问
```

### 内存访问控制

```
访问流程：
1. 访问者发起内存访问请求 (accessor_id, target_addr, access_type)
2. MemoryManager 查询 target_addr 所属的内存区域
3. SecuritySubsystem 检查 accessor_id 是否有权限访问该区域
4. 权限检查通过 → 执行访问
5. 权限检查失败 → 触发安全异常
```

## 架构设计

### 组件关系

```
┌─────────────────────────────────────────────────────────────────┐
│                          Machine                                 │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │   RPALogic   │  │    Memory    │  │   MemoryManager      │  │
│  │              │  │              │  │                      │  │
│  │ domains[]    │  │ data[]       │  │ translate()          │  │
│  │ current_id   │  │ regions[]    │  │ check_access() ◄─────┼──┤
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘  │
│         │                 │                     │              │
│         │                 │                     │              │
│         │         ┌───────┴─────────────────────┘              │
│         │         │                                           │
│         │         ▼                                           │
│         │  ┌─────────────────────────────────────────────┐    │
│         │  │         SecuritySubsystem                    │    │
│         │  │                                              │    │
│         └──┤  groups: Map<group_id, SecurityGroup>        │    │
│            │  accessors: Map<accessor_id, group_id>       │    │
│            │  regions: Map<addr, MemoryRegion>            │    │
│            │                                              │    │
│            │  check_access(accessor_id, addr, type)       │    │
│            │  create_group(owner_id, config)              │    │
│            │  add_accessor(group_id, accessor_id)         │    │
│            │  set_region_encryption(group_id, addr, size) │    │
│            └─────────────────────────────────────────────┘    │
│                          ▲                                     │
│                          │                                     │
│  ┌───────────────────────┴────────────────────────────────┐   │
│  │                    External Devices                      │   │
│  │                                                          │   │
│  │  DMA Controller ──── device_id ────┐                    │   │
│  │  GPU              ──── device_id ───┼──► MemoryManager   │   │
│  │  PCIe Device      ──── device_id ───┘                    │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 关键约束

1. **安全子系统与内存管理器紧耦合**：安全检查在内存访问时进行
2. **安全子系统与顶层紧耦合**：不隔其他层，从顶层进行安全管理
3. **统一访问者模型**：CPU Domain 和外设使用相同的 ID 和检查机制

## 数据结构

### SecurityGroup

```python
@dataclass
class SecurityGroup:
    group_id: int                    # 安全组 ID
    owner_id: int                    # 创建者 accessor_id
    members: Set[int]                # 成员 accessor_id 集合
    encrypted_regions: List[Range]   # 加密内存区域
    encryption_key: int              # 加密密钥
    is_confidential: bool            # 是否机密计算组
```

### MemoryRegion

```python
@dataclass
class MemoryRegion:
    start: int                       # 起始地址
    size: int                        # 大小
    owner_group: int                 # 所属安全组
    permissions: Dict[int, Perm]     # 访问者权限映射
```

### Accessor

```python
@dataclass
class Accessor:
    accessor_id: int                 # 唯一标识
    accessor_type: str               # "domain" | "dma" | "gpu" | "pcie"
    group_id: int                    # 所属安全组
    parent_id: Optional[int]         # 父访问者（用于继承）
```

## 访问控制规则

### 基本规则

1. **同组访问**：同一安全组内的访问者可以互相访问内存
2. **组间隔离**：不同安全组默认不能访问对方的内存
3. **显式授权**：可以显式授予其他访问者访问权限
4. **机密计算组**：特殊的安全组，即使 root 也无法访问

### 权限检查流程

```python
def check_access(accessor_id, target_addr, access_type):
    # 1. 获取访问者所属的安全组
    accessor_group = get_accessor_group(accessor_id)

    # 2. 获取目标地址所属的安全组
    region = find_memory_region(target_addr)
    target_group = region.owner_group

    # 3. 同组访问允许
    if accessor_group == target_group:
        return True

    # 4. 检查显式授权
    if accessor_id in region.permissions:
        return check_permission(region.permissions[accessor_id], access_type)

    # 5. 机密计算组禁止外部访问
    if get_group(target_group).is_confidential:
        return False

    # 6. root 域特殊处理
    if accessor_id == 0:  # root domain
        return not get_group(target_group).is_confidential

    return False
```

## 指令接口

### sysop secgroup

| 子操作 | 操作码 | 说明 |
|--------|--------|------|
| CREATE | 0x01 | 创建安全组 |
| DESTROY | 0x02 | 销毁安全组 |
| JOIN | 0x03 | 加入安全组 |
| LEAVE | 0x04 | 离开安全组 |
| ADD_ACCESSOR | 0x05 | 添加外设访问者 |
| REMOVE_ACCESSOR | 0x06 | 移除访问者 |
| SET_ENCRYPTION | 0x07 | 设置加密区域 |
| GET_ID | 0x08 | 获取当前安全组 ID |

### DomainBlock 字段更新

| 偏移 | 字段 | 说明 |
|------|------|------|
| 0x1C | security_group | 安全组 ID（原 security_domain） |

## 威胁建模

### 数据流保护对象

| 保护对象 | 威胁 | 保护机制 |
|---------|------|---------|
| 内存数据 | 未授权读取 | 安全组隔离 + 加密 |
| 内存数据 | 未授权写入 | 安全组隔离 |
| DMA 传输 | 数据泄露 | DMA 加入安全组 |
| GPU 计算 | 数据泄露 | GPU 加入安全组 |

### 侧信道威胁（未来工作）

| 威胁类型 | 说明 | 可能的缓解措施 |
|---------|------|---------------|
| Cache 侧信道 | 通过 cache timing 推断数据 | Cache 分区/刷新 |
| 寄存器残留 | 域切换时寄存器数据泄露 | DESCEND/RETURN 时清零 |
| TLB 泄露 | 地址翻译信息泄露 | TLB 刷新 |

## 与 IOMMU 的集成

```
外设访问流程：
1. 外设发起 DMA 请求 (device_id, device_addr)
2. IOMMU 翻译 device_addr → system_addr
3. MemoryManager 检查 device_id 是否有权访问 system_addr
4. SecuritySubsystem 验证访问权限
5. 执行访问或拒绝
```

**设计优势**：
- 统一的访问控制模型
- 外设与 CPU Domain 使用相同的权限检查
- 便于形式化验证和审计

## 实现计划

### Phase 1: 重命名和基础结构
- [x] security_domain → security_group
- [ ] Accessor 抽象
- [ ] 统一的 accessor_id 分配

### Phase 2: 内存管理器集成
- [ ] MemoryManager 添加 accessor_id 参数
- [ ] 实现 check_access 检查
- [ ] 权限失败触发安全异常

### Phase 3: 外设接口
- [ ] DMA 访问接口
- [ ] GPU 访问接口
- [ ] PCIe 设备访问接口

### Phase 4: 威胁缓解
- [ ] 寄存器清零
- [ ] Cache 管理接口
- [ ] TLB 刷新接口