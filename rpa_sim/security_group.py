"""
Security Group Controller - 安全组管理模块

提供安全组的创建、销毁和管理功能。

安全组是统一的安全隔离机制：
- CPU Domain 和外设（DMA、GPU、PCIe）统一为"访问者"(Accessor)
- 通过 MemoryManager 统一进行访问控制
- 同组访问者可以互相访问内存，组间默认隔离

设计原则：
- Handle-based 访问模式
- 与 MemoryManager 紧耦合
- 与顶层紧耦合，不隔其他层
"""

from dataclasses import dataclass, field
from typing import Dict, Set, Optional, Any, TYPE_CHECKING
from enum import IntEnum

if TYPE_CHECKING:
    from .memory import Memory, MemoryManager


class SecGroupPerm(IntEnum):
    """安全组权限位"""
    CREATE = 0x01      # 可创建子安全组
    DESTROY = 0x02     # 可销毁安全组
    ENCRYPT = 0x04     # 可设置加密
    ADD_ACCESSOR = 0x08  # 可添加访问者


@dataclass
class SecurityGroupConfig:
    """安全组配置参数"""
    inherit_from_parent: bool = True    # 是否继承父安全组
    create_new: bool = False            # 创建新安全组
    isolated: bool = True               # 内存隔离
    encrypted: bool = False             # 加密
    confidential: bool = False          # 机密计算域
    passphrase: int = 0                 # 密码（用于机密计算验证）


@dataclass
class SecurityGroup:
    """
    安全组实例

    每个安全组代表一个独立的隔离边界，包含：
    - 内存隔离属性
    - 加密密钥
    - 访问者成员列表
    """
    handle: int                         # 安全组句柄 (从 0x2000 开始)
    owner_domain_id: int                # 创建者域 ID
    domain_id: int                      # 安全组 ID (用于内存子系统)
    parent_handle: int = 0              # 父安全组 handle

    # 内存属性
    memory_isolated: bool = True        # 是否内存隔离
    encrypted: bool = False             # 是否加密
    encryption_key: int = 0             # 加密密钥

    # DMA 控制
    allowed_accessors: Set[int] = field(default_factory=set)  # 允许的访问者 domain_id

    # 机密计算属性
    is_confidential: bool = False       # 是否机密计算组
    passphrase_hash: int = 0            # 密码哈希

    # 统计
    ref_count: int = 0                  # 引用计数（关联的域数量）

    # 关联的域 ID 集合
    bound_domains: Set[int] = field(default_factory=set)


@dataclass
class EncryptedRegion:
    """加密内存区域"""
    start: int              # 起始地址
    size: int               # 大小
    security_handle: int    # 所属安全组 handle
    key: int                # 加密密钥

    def encrypt(self, data: bytes) -> bytes:
        """加密数据（XOR 模拟）"""
        key_bytes = self.key.to_bytes(8, 'little')
        return bytes(b ^ key_bytes[i % 8] for i, b in enumerate(data))

    def decrypt(self, data: bytes) -> bytes:
        """解密数据（XOR 模拟，对称）"""
        return self.encrypt(data)


class SecurityGroupController:
    """
    全局安全组控制器

    统一管理 CPU Domain 和外设的安全组。
    与 MemoryManager 紧耦合，提供访问控制检查。
    """

    HANDLE_BASE = 0x2000          # 安全组 handle 起始值
    DOMAIN_ID_BASE = 0x0100       # 安全组 ID 起始值

    # 机密计算暗号基值（内置）
    CONFIDENTIAL_SEED = 0xDEADBEEFCAFEBABE

    # ============================================================
    # ATTESTATION: 安全组创建权限验证配置
    # ============================================================
    # 静态配置允许创建安全组的 domain_id 列表
    # 生产环境中应通过安全启动过程中的 measurement 验证
    # 当前为测试目的，允许 root domain (0) 及其直接子域 (1-3) 创建安全组
    # TODO: 替换为真正的 attestation 机制（measurement hash 验证）
    EXPECTED_ATTESTATION_IDS = {0, 1, 2, 3}

    def __init__(self, memory_manager: Optional['MemoryManager'] = None):
        """
        初始化安全组控制器。

        Args:
            memory_manager: 内存管理器引用
        """
        self.memory_manager = memory_manager

        # 实例映射
        self.instances: Dict[int, SecurityGroup] = {}

        # domain_id 到 handle 的映射
        self.domain_id_to_handle: Dict[int, int] = {}

        # 域 ID 到安全组 handle 的映射（普通域 ID -> 安全组 handle）
        self.domain_security_map: Dict[int, int] = {}

        # handle 分配器
        self._next_handle = self.HANDLE_BASE

        # 安全组 ID 分配器
        self._next_domain_id = self.DOMAIN_ID_BASE

        # 创建 root 安全组（域 ID 0 默认在 root 安全组）
        self.root_handle = self._create_root_domain()

        # 是否启用安全子系统（影响 domain_id 分配）
        self.enabled = True

    def _create_root_domain(self) -> int:
        """创建 root 安全组"""
        handle = self._next_handle
        self._next_handle += 1

        domain_id = self._next_domain_id
        self._next_domain_id += 1

        instance = SecurityGroup(
            handle=handle,
            owner_domain_id=0,
            domain_id=domain_id,
            parent_handle=0,
            memory_isolated=False,  # root 不隔离
            encrypted=False,
            ref_count=1,  # root 域默认关联
            bound_domains={0}
        )

        self.instances[handle] = instance
        self.domain_id_to_handle[domain_id] = handle
        self.domain_security_map[0] = handle

        return handle

    # ============================================================
    # ATTESTATION API: 安全组创建权限验证
    # ============================================================
    def verify_attestation(self, owner_id: int, measurement: int = 0) -> bool:
        """
        验证创建安全组的权限（Attestation 检查）

        在真实实现中，此方法应验证：
        1. 安全启动过程中的 measurement hash
        2. 与 root 系统的交互验证（trap 或 RTL 调用）
        3. 申请者是否在根信任认可的创建者列表中

        当前为测试目的，使用简单的 domain_id 静态列表验证。

        Args:
            owner_id: 申请者的 domain_id
            measurement: 安全启动测量值（当前未使用）

        Returns:
            True 表示验证通过，允许创建安全组
        """
        # 简单模拟：检查 owner_id 是否在预期列表中
        # 生产环境：替换为真正的 attestation 机制
        return owner_id in self.EXPECTED_ATTESTATION_IDS

    def create(self, owner_domain_id: int,
               config: Optional[SecurityGroupConfig] = None,
               parent_handle: int = 0) -> int:
        """
        创建安全组

        Args:
            owner_domain_id: 创建者域 ID
            config: 配置参数
            parent_handle: 父安全组 handle

        Returns:
            安全组 handle，失败返回 0
        """
        if config is None:
            config = SecurityGroupConfig()

        # 继承父安全组
        if config.inherit_from_parent and not config.create_new:
            # 查找父域的安全组
            if parent_handle == 0:
                parent_handle = self.domain_security_map.get(owner_domain_id, self.root_handle)
            if parent_handle in self.instances:
                parent_instance = self.instances[parent_handle]
                # 返回父安全组 handle
                return parent_handle

        # ============================================================
        # ATTESTATION CHECK: 验证创建安全组的权限
        # ============================================================
        # 必须通过 attestation 验证才能创建新的安全组
        # 生产环境应使用真正的 measurement 验证
        if not self.verify_attestation(owner_domain_id):
            # Attestation 验证失败，拒绝创建
            return 0

        # 创建新安全组
        handle = self._next_handle
        self._next_handle += 1

        domain_id = self._next_domain_id
        self._next_domain_id += 1

        # 计算加密密钥（如果需要）
        encryption_key = 0
        passphrase_hash = 0
        if config.encrypted:
            encryption_key = self._generate_encryption_key(config.passphrase)
            if config.confidential:
                passphrase_hash = self._compute_passphrase_hash(config.passphrase)

        instance = SecurityGroup(
            handle=handle,
            owner_domain_id=owner_domain_id,
            domain_id=domain_id,
            parent_handle=parent_handle,
            memory_isolated=config.isolated,
            encrypted=config.encrypted,
            encryption_key=encryption_key,
            is_confidential=config.confidential,
            passphrase_hash=passphrase_hash,
            ref_count=0,
            bound_domains=set()
        )

        self.instances[handle] = instance
        self.domain_id_to_handle[domain_id] = handle

        return handle

    def destroy(self, handle: int, caller_id: int = 0) -> bool:
        """
        销毁安全组（正常销毁 - 组织者自己解散）

        条件：
        1. 引用计数为 0
        2. 调用者必须是安全组的 owner

        Args:
            handle: 安全组 handle
            caller_id: 调用者 domain_id（验证是否为 owner）

        Returns:
            是否成功
        """
        instance = self.instances.get(handle)
        if not instance:
            return False

        # ============================================================
        # 权限检查：调用者必须是安全组的 owner
        # ============================================================
        if instance.owner_domain_id != caller_id:
            return False

        # 引用计数不为 0，无法销毁
        if instance.ref_count > 0:
            return False

        # root 安全组不能销毁
        if handle == self.root_handle:
            return False

        # 清理加密区域
        if self.memory_manager and instance.encrypted:
            self._clear_encrypted_regions(instance)

        # 从映射中移除
        domain_id = instance.domain_id
        del self.instances[handle]
        if domain_id in self.domain_id_to_handle:
            del self.domain_id_to_handle[domain_id]

        return True

    def destroy_force(self, handle: int, caller_id: int = 0) -> bool:
        """
        强制销毁安全组（仅 root 域可用）

        危险操作：不检查引用计数，直接销毁

        Args:
            handle: 安全组 handle
            caller_id: 调用者 domain_id（验证是否为 root）

        Returns:
            是否成功
        """
        instance = self.instances.get(handle)
        if not instance:
            return False

        # ============================================================
        # 权限检查：仅 root 域 (caller_id == 0) 可以强制销毁
        # ============================================================
        if caller_id != 0:
            return False

        # root 安全组不能销毁
        if handle == self.root_handle:
            return False

        # 清理所有关联的域
        for domain_id in instance.bound_domains.copy():
            self.domain_security_map.pop(domain_id, None)

        # 清理加密区域
        if self.memory_manager and instance.encrypted:
            self._clear_encrypted_regions(instance)

        # 从映射中移除
        domain_id = instance.domain_id
        del self.instances[handle]
        if domain_id in self.domain_id_to_handle:
            del self.domain_id_to_handle[domain_id]

        return True

    def bind_domain(self, handle: int, domain_id: int) -> bool:
        """
        绑定域到安全组

        Args:
            handle: 安全组 handle
            domain_id: 域 ID

        Returns:
            是否成功
        """
        instance = self.instances.get(handle)
        if not instance:
            return False

        instance.bound_domains.add(domain_id)
        instance.ref_count += 1
        self.domain_security_map[domain_id] = handle

        return True

    def unbind_domain(self, handle: int, domain_id: int) -> bool:
        """
        解绑域

        Args:
            handle: 安全组 handle
            domain_id: 域 ID

        Returns:
            是否成功
        """
        instance = self.instances.get(handle)
        if not instance:
            return False

        if domain_id in instance.bound_domains:
            instance.bound_domains.discard(domain_id)
            instance.ref_count = max(0, instance.ref_count - 1)

        if domain_id in self.domain_security_map:
            del self.domain_security_map[domain_id]

        # 引用计数为 0 时标记为可销毁，但不自动销毁
        # 需要显式调用 destroy() 销毁
        return True

    def get_instance(self, handle: int) -> Optional[SecurityGroup]:
        """获取安全组实例"""
        return self.instances.get(handle)

    def get_domain_security_handle(self, domain_id: int) -> int:
        """
        获取域所属的安全组 handle

        Args:
            domain_id: 域 ID

        Returns:
            安全组 handle，未找到返回 root_handle
        """
        return self.domain_security_map.get(domain_id, self.root_handle)

    def allocate_domain_id(self, handle: int) -> int:
        """
        为安全组分配 domain_id

        Args:
            handle: 安全组 handle

        Returns:
            domain_id，失败返回 0
        """
        instance = self.instances.get(handle)
        if not instance:
            return 0
        return instance.domain_id

    def check_dma_access(self, target_handle: int, accessor_domain_id: int,
                         operation: str = 'read') -> bool:
        """
        检查 DMA 访问权限

        DMA 访问规则：
        1. 同一安全组内允许
        2. 在 allowed_accessors 中允许
        3. 机密计算域禁止外部访问
        4. root 域不能访问机密计算域

        Args:
            target_handle: 目标安全组
            accessor_domain_id: 访问者域 ID
            operation: 'read' 或 'write'

        Returns:
            是否允许访问
        """
        target = self.instances.get(target_handle)
        if not target:
            return False

        # 获取访问者的安全组
        accessor_handle = self.domain_security_map.get(accessor_domain_id, self.root_handle)

        # 同一安全组内允许
        if accessor_handle == target_handle:
            return True

        # 机密计算域禁止外部访问
        if target.is_confidential:
            return False

        # 检查访问列表
        if accessor_domain_id in target.allowed_accessors:
            return True

        return False

    def add_dma_accessor(self, handle: int, accessor_domain_id: int) -> bool:
        """
        添加 DMA 访问者

        Args:
            handle: 安全组 handle
            accessor_domain_id: 访问者域 ID

        Returns:
            是否成功
        """
        instance = self.instances.get(handle)
        if not instance:
            return False

        # 机密计算域不允许添加访问者
        if instance.is_confidential:
            return False

        instance.allowed_accessors.add(accessor_domain_id)
        return True

    def remove_dma_accessor(self, handle: int, accessor_domain_id: int) -> bool:
        """
        移除 DMA 访问者

        Args:
            handle: 安全组 handle
            accessor_domain_id: 访问者域 ID

        Returns:
            是否成功
        """
        instance = self.instances.get(handle)
        if not instance:
            return False

        instance.allowed_accessors.discard(accessor_domain_id)
        return True

    def set_encryption(self, handle: int, start: int, size: int) -> bool:
        """
        设置加密区域

        Args:
            handle: 安全组 handle
            start: 起始地址
            size: 区域大小

        Returns:
            是否成功
        """
        instance = self.instances.get(handle)
        if not instance or not instance.encrypted:
            return False

        # 如果有内存管理器，注册加密区域
        if self.memory_manager:
            self.memory_manager.set_encryption(start, size, handle, instance.encryption_key)

        return True

    def get_encryption_key(self, handle: int) -> int:
        """
        获取加密密钥

        Args:
            handle: 安全组 handle

        Returns:
            加密密钥，失败返回 0
        """
        instance = self.instances.get(handle)
        if not instance or not instance.encrypted:
            return 0
        return instance.encryption_key

    def _generate_encryption_key(self, passphrase: int) -> int:
        """生成加密密钥"""
        # 简单的密钥生成（XOR 混淆）
        return (passphrase ^ self.CONFIDENTIAL_SEED) & 0xFFFFFFFFFFFFFFFF

    def _compute_passphrase_hash(self, passphrase: int) -> int:
        """计算密码哈希"""
        # 简单哈希（用于验证）
        return ((passphrase * 0x5851F42D4C957F2D) ^ self.CONFIDENTIAL_SEED) & 0xFFFFFFFFFFFFFFFF

    def _clear_encrypted_regions(self, instance: SecurityGroup) -> None:
        """清理加密区域"""
        if self.memory_manager:
            self.memory_manager.clear_encryption_by_handle(instance.handle)

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "total_instances": len(self.instances),
            "next_handle": self._next_handle,
            "next_domain_id": self._next_domain_id,
            "root_handle": self.root_handle,
            "instances": {
                handle: {
                    "owner_domain_id": inst.owner_domain_id,
                    "domain_id": inst.domain_id,
                    "ref_count": inst.ref_count,
                    "encrypted": inst.encrypted,
                    "is_confidential": inst.is_confidential,
                    "bound_domains": list(inst.bound_domains)
                }
                for handle, inst in self.instances.items()
            }
        }