"""
Security Domain Controller - 安全域管理模块

提供安全域的创建、销毁和管理功能。

安全域是比域更粗粒度的隔离单位：
- 多个域可以共享同一个安全域
- 安全域提供独立的内存隔离属性
- 支持内存加密和 DMA 访问控制

设计参考 InterruptController：
- Handle-based 访问模式
- 权限控制
- 与 DomainBlock 集成
"""

from dataclasses import dataclass, field
from typing import Dict, Set, Optional, Any, TYPE_CHECKING
from enum import IntEnum

if TYPE_CHECKING:
    from .memory import Memory, MemoryManager


class SecGroupPerm(IntEnum):
    """安全域权限位"""
    CREATE = 0x01      # 可创建子安全域
    DESTROY = 0x02     # 可销毁安全域
    ENCRYPT = 0x04     # 可设置加密
    DMA_CTRL = 0x08    # 可控制 DMA 访问


@dataclass
class SecurityGroupConfig:
    """安全域配置参数"""
    inherit_from_parent: bool = True    # 是否继承父安全域
    create_new: bool = False            # 创建新安全域
    isolated: bool = True               # 内存隔离
    encrypted: bool = False             # 加密
    confidential: bool = False          # 机密计算域
    passphrase: int = 0                 # 密码（用于机密计算验证）


@dataclass
class SecurityGroup:
    """
    安全域实例

    每个安全域代表一个独立的隔离边界，包含：
    - 内存隔离属性
    - 加密密钥
    - DMA 访问控制列表
    """
    handle: int                         # 安全域句柄 (从 0x2000 开始)
    owner_domain_id: int                # 创建者域 ID
    domain_id: int                      # 安全域 ID (用于内存子系统)
    parent_handle: int = 0              # 父安全域 handle

    # 内存属性
    memory_isolated: bool = True        # 是否内存隔离
    encrypted: bool = False             # 是否加密
    encryption_key: int = 0             # 加密密钥

    # DMA 控制
    allowed_accessors: Set[int] = field(default_factory=set)  # 允许的访问者 domain_id

    # 机密计算属性
    is_confidential: bool = False       # 是否机密计算域
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
    security_handle: int    # 所属安全域 handle
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
    全局安全域控制器

    参考 InterruptController 的设计模式：
    - Handle-based 访问
    - 全局单例管理
    - 权限控制
    """

    HANDLE_BASE = 0x2000          # 安全域 handle 起始值
    DOMAIN_ID_BASE = 0x0100       # 安全域 ID 起始值

    # 机密计算暗号基值（内置）
    CONFIDENTIAL_SEED = 0xDEADBEEFCAFEBABE

    def __init__(self, memory_manager: Optional['MemoryManager'] = None):
        """
        初始化安全域控制器。

        Args:
            memory_manager: 内存管理器引用
        """
        self.memory_manager = memory_manager

        # 实例映射
        self.instances: Dict[int, SecurityGroup] = {}

        # domain_id 到 handle 的映射
        self.domain_id_to_handle: Dict[int, int] = {}

        # 域 ID 到安全域 handle 的映射（普通域 ID -> 安全域 handle）
        self.domain_security_map: Dict[int, int] = {}

        # handle 分配器
        self._next_handle = self.HANDLE_BASE

        # 安全域 ID 分配器
        self._next_domain_id = self.DOMAIN_ID_BASE

        # 创建 root 安全域（域 ID 0 默认在 root 安全域）
        self.root_handle = self._create_root_domain()

        # 是否启用安全子系统（影响 domain_id 分配）
        self.enabled = True

    def _create_root_domain(self) -> int:
        """创建 root 安全域"""
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

    def create(self, owner_domain_id: int,
               config: Optional[SecurityGroupConfig] = None,
               parent_handle: int = 0) -> int:
        """
        创建安全域

        Args:
            owner_domain_id: 创建者域 ID
            config: 配置参数
            parent_handle: 父安全域 handle

        Returns:
            安全域 handle，失败返回 0
        """
        if config is None:
            config = SecurityGroupConfig()

        # 继承父安全域
        if config.inherit_from_parent and not config.create_new:
            # 查找父域的安全域
            if parent_handle == 0:
                parent_handle = self.domain_security_map.get(owner_domain_id, self.root_handle)
            if parent_handle in self.instances:
                parent_instance = self.instances[parent_handle]
                # 返回父安全域 handle
                return parent_handle

        # 创建新安全域
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

    def destroy(self, handle: int) -> bool:
        """
        销毁安全域（正常销毁）

        条件：引用计数为 0

        Args:
            handle: 安全域 handle

        Returns:
            是否成功
        """
        instance = self.instances.get(handle)
        if not instance:
            return False

        # 引用计数不为 0，无法销毁
        if instance.ref_count > 0:
            return False

        # root 安全域不能销毁
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

    def destroy_force(self, handle: int) -> bool:
        """
        强制销毁安全域（仅 root 域可用）

        危险操作：不检查引用计数，直接销毁

        Args:
            handle: 安全域 handle

        Returns:
            是否成功
        """
        instance = self.instances.get(handle)
        if not instance:
            return False

        # root 安全域不能销毁
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
        绑定域到安全域

        Args:
            handle: 安全域 handle
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
            handle: 安全域 handle
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
        """获取安全域实例"""
        return self.instances.get(handle)

    def get_domain_security_handle(self, domain_id: int) -> int:
        """
        获取域所属的安全域 handle

        Args:
            domain_id: 域 ID

        Returns:
            安全域 handle，未找到返回 root_handle
        """
        return self.domain_security_map.get(domain_id, self.root_handle)

    def allocate_domain_id(self, handle: int) -> int:
        """
        为安全域分配 domain_id

        Args:
            handle: 安全域 handle

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
        1. 同一安全域内允许
        2. 在 allowed_accessors 中允许
        3. 机密计算域禁止外部访问
        4. root 域不能访问机密计算域

        Args:
            target_handle: 目标安全域
            accessor_domain_id: 访问者域 ID
            operation: 'read' 或 'write'

        Returns:
            是否允许访问
        """
        target = self.instances.get(target_handle)
        if not target:
            return False

        # 获取访问者的安全域
        accessor_handle = self.domain_security_map.get(accessor_domain_id, self.root_handle)

        # 同一安全域内允许
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
            handle: 安全域 handle
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
            handle: 安全域 handle
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
            handle: 安全域 handle
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
            handle: 安全域 handle

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