"""
Interrupt Controller - 中断控制器模块

实现 RPA 架构的中断管理：
- 独立的中断控制器实例（通过 handle 访问）
- 权限控制（配置、使能、软中断）
- 多级传递机制
- 软中断支持

设计原则：
- 中断控制器与域不是一对一关系
- 域需要申请实例获得 handle
- handle 设置在 DomainBlock.interrupt_ctrl
- 中断向量保存在实例中，不在 block 中

实例结构：
============
    owner_domain_id: 申请者域 ID
    permissions: 权限位图
    irq_enable: I-bit
    vector: 中断向量
    pending: 待处理中断位图

权限位：
========
    PERM_CONFIG:  可配置中断（设置向量）
    PERM_ENABLE:  可使能/禁用中断
    PERM_SGI:     可触发软中断

sysop irq 指令：
===============
    request:  申请实例（父域操作）
    release:  释放实例
    enable:   启用中断
    disable:  禁用中断
    setvec:   设置向量
    getpending: 读取 pending
    clear:    清除 pending
    sgi:      触发软中断
"""

from dataclasses import dataclass, field
from typing import Optional, Tuple, List, Dict
from enum import IntEnum


# 权限位定义
class IrqPerm(IntEnum):
    """中断权限位"""
    CONFIG = 0x01   # 可配置中断（设置向量）
    ENABLE = 0x02   # 可使能/禁用中断
    SGI = 0x04      # 可触发软中断


# sysop irq 子操作码
class IrqSubOp(IntEnum):
    """sysop irq 子操作"""
    READ = 0x01       # 读取（保留）
    WRITE = 0x02      # 写入（保留）
    ENABLE = 0x03     # 启用中断
    DISABLE = 0x04    # 禁用中断
    SETVEC = 0x05     # 设置向量
    GETPENDING = 0x06 # 读取 pending
    CLEAR = 0x07      # 清除 pending
    REQUEST = 0x08    # 申请实例
    RELEASE = 0x09    # 释放实例
    SGI = 0x0A        # 触发软中断


@dataclass
class InterruptInstance:
    """
    中断控制器实例

    每个实例由域申请，保存该域的中断状态。
    """
    handle: int                  # 实例句柄
    owner_domain_id: int         # 申请者域 ID
    permissions: int             # 权限位图
    irq_enable: bool = False     # I-bit（中断使能）
    vector: int = 0              # 中断向量（所有中断共用）
    pending: int = 0             # 待处理中断位图（最多 32 个中断）
    parent_handle: int = 0       # 父域实例 handle（用于多级传递）
    child_handle: int = 0        # 子域实例 handle（用于多级传递）


@dataclass
class IrqConfig:
    """
    中断配置

    用于 trigger_irq 时传递配置信息
    """
    irq_num: int = 0             # 中断号
    target_handle: int = 0       # 目标实例


class InterruptController:
    """
    全局中断控制器

    管理所有中断实例，提供申请、操作、查询接口。
    """

    # handle 起始值（避免与 0 混淆）
    HANDLE_BASE = 0x1000

    def __init__(self):
        # 实例映射：handle -> Instance
        self.instances: Dict[int, InterruptInstance] = {}

        # 域到实例的映射：domain_id -> handle（一个域可以有多个实例）
        self.domain_instances: Dict[int, List[int]] = {}

        # handle 分配器
        self._next_handle = self.HANDLE_BASE

        # 全局中断待处理标志（供 ISA 快速检查）
        self.global_pending: bool = False

    def request(self, owner_domain_id: int, permissions: int,
                parent_handle: int = 0) -> int:
        """
        申请中断控制器实例

        Args:
            owner_domain_id: 申请者域 ID
            permissions: 权限位图
            parent_handle: 父域实例 handle（用于多级传递）

        Returns:
            handle: 实例句柄
        """
        handle = self._next_handle
        self._next_handle += 1

        instance = InterruptInstance(
            handle=handle,
            owner_domain_id=owner_domain_id,
            permissions=permissions,
            parent_handle=parent_handle,
        )
        self.instances[handle] = instance

        # 更新域映射
        if owner_domain_id not in self.domain_instances:
            self.domain_instances[owner_domain_id] = []
        self.domain_instances[owner_domain_id].append(handle)

        # 更新父实例的 child_handle
        if parent_handle and parent_handle in self.instances:
            self.instances[parent_handle].child_handle = handle

        return handle

    def release(self, handle: int) -> bool:
        """
        释放中断控制器实例

        Args:
            handle: 实例句柄

        Returns:
            bool: 是否成功
        """
        if handle not in self.instances:
            return False

        instance = self.instances[handle]

        # 清除父实例的 child_handle
        if instance.parent_handle and instance.parent_handle in self.instances:
            self.instances[instance.parent_handle].child_handle = 0

        # 从域映射中移除
        domain_id = instance.owner_domain_id
        if domain_id in self.domain_instances:
            if handle in self.domain_instances[domain_id]:
                self.domain_instances[domain_id].remove(handle)

        # 删除实例
        del self.instances[handle]

        return True

    def enable(self, handle: int) -> bool:
        """启用中断（I-bit = 1）"""
        if handle not in self.instances:
            return False
        instance = self.instances[handle]
        if not (instance.permissions & IrqPerm.ENABLE):
            return False
        instance.irq_enable = True
        return True

    def disable(self, handle: int) -> bool:
        """禁用中断（I-bit = 0）"""
        if handle not in self.instances:
            return False
        instance = self.instances[handle]
        if not (instance.permissions & IrqPerm.ENABLE):
            return False
        instance.irq_enable = False
        return True

    def set_vector(self, handle: int, vector: int) -> bool:
        """设置中断向量"""
        if handle not in self.instances:
            return False
        instance = self.instances[handle]
        if not (instance.permissions & IrqPerm.CONFIG):
            return False
        instance.vector = vector
        return True

    def get_pending(self, handle: int) -> int:
        """读取 pending 位图"""
        if handle not in self.instances:
            return 0
        return self.instances[handle].pending

    def clear_pending(self, handle: int, irq_num: int) -> bool:
        """清除指定中断的 pending"""
        if handle not in self.instances:
            return False
        instance = self.instances[handle]
        instance.pending &= ~(1 << irq_num)

        # 更新全局标志
        self._update_global_pending()

        return True

    def trigger_irq(self, target_handle: int, irq_num: int,
                    from_handle: int = 0) -> bool:
        """
        触发中断（硬件或软件）

        Args:
            target_handle: 目标实例
            irq_num: 中断号
            from_handle: 来源实例（软中断时使用）

        Returns:
            bool: 是否成功触发
        """
        if target_handle not in self.instances:
            return False

        instance = self.instances[target_handle]

        # 设置 pending 位
        instance.pending |= (1 << irq_num)

        # 更新全局标志
        self.global_pending = True

        return True

    def sgi(self, from_handle: int, target_handle: int, irq_num: int) -> bool:
        """
        触发软中断

        Args:
            from_handle: 发送者实例
            target_handle: 目标实例
            irq_num: 中断号

        Returns:
            bool: 是否成功
        """
        # 检查发送者权限
        if from_handle not in self.instances:
            return False
        from_instance = self.instances[from_handle]
        if not (from_instance.permissions & IrqPerm.SGI):
            return False

        return self.trigger_irq(target_handle, irq_num, from_handle)

    def check_interrupt(self, current_domain_id: int,
                        domain_handles: Dict[int, int]) -> Optional[Tuple[int, int]]:
        """
        检查是否有待处理的中断

        从当前域向上查找，返回最高优先级（最上层）的待处理中断。

        Args:
            current_domain_id: 当前域 ID
            domain_handles: 域 ID 到中断实例 handle 的映射

        Returns:
            (handle, vector) 或 None
        """
        if not self.global_pending:
            return None

        # 从当前域向上查找（通过 parent_handle 链）
        # 这里简化处理：只检查当前域的实例
        handles = self.domain_instances.get(current_domain_id, [])
        for handle in handles:
            if handle not in self.instances:
                continue
            instance = self.instances[handle]

            # 检查是否有 pending 且 I-bit 启用
            if instance.pending != 0 and instance.irq_enable:
                # 返回第一个待处理的中断
                irq_num = (instance.pending & -instance.pending).bit_length() - 1
                return (handle, instance.vector)

        return None

    def get_instance(self, handle: int) -> Optional[InterruptInstance]:
        """获取实例"""
        return self.instances.get(handle)

    def is_enabled(self, handle: int) -> bool:
        """检查中断是否启用"""
        if handle not in self.instances:
            return False
        return self.instances[handle].irq_enable

    def _update_global_pending(self) -> None:
        """更新全局 pending 标志"""
        self.global_pending = any(
            inst.pending != 0 for inst in self.instances.values()
        )