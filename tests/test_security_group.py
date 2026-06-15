"""
Security Domain Tests - 安全组功能测试

测试安全组系统的核心功能：
- 安全组创建和销毁
- 域绑定和解绑
- DMA 访问控制
- 内存加密
- 与 RPALogic 的集成
"""

import pytest
from rpa_sim import (
    RPALogic, DomainBlock, Memory, MemoryManager,
    SecurityGroupController, SecurityGroupConfig, SecGroupPerm,
    SimpleISA
)


class TestSecurityGroupController:
    """安全组控制器测试"""

    def test_create_security_group(self):
        """测试创建安全组"""
        mem = Memory(1024 * 1024)
        mem_mgr = MemoryManager(mem)
        controller = SecurityGroupController(mem_mgr)

        # 创建新安全组 (domain_id=1 在 EXPECTED_ATTESTATION_IDS 中)
        config = SecurityGroupConfig(
            inherit_from_parent=False,
            create_new=True,
            isolated=True
        )
        handle = controller.create(owner_domain_id=1, config=config)

        assert handle >= SecurityGroupController.HANDLE_BASE
        instance = controller.get_instance(handle)
        assert instance is not None
        assert instance.owner_domain_id == 1
        assert instance.memory_isolated is True

    def test_attestation_verification(self):
        """测试 attestation 验证"""
        mem = Memory(1024 * 1024)
        mem_mgr = MemoryManager(mem)
        controller = SecurityGroupController(mem_mgr)

        # EXPECTED_ATTESTATION_IDS = {0, 1, 2, 3}
        # 允许的 domain_id 应该能创建安全组
        for domain_id in [0, 1, 2, 3]:
            config = SecurityGroupConfig(create_new=True, isolated=True)
            handle = controller.create(owner_domain_id=domain_id, config=config)
            assert handle != 0, f"domain_id {domain_id} should be allowed to create security group"

        # 不允许的 domain_id 应该被拒绝
        config = SecurityGroupConfig(create_new=True, isolated=True)
        handle = controller.create(owner_domain_id=99, config=config)
        assert handle == 0, "domain_id 99 should be rejected"

    def test_inherit_security_group(self):
        """测试继承父安全组"""
        mem = Memory(1024 * 1024)
        mem_mgr = MemoryManager(mem)
        controller = SecurityGroupController(mem_mgr)

        # 继承父安全组（默认配置）
        config = SecurityGroupConfig(inherit_from_parent=True)
        handle = controller.create(owner_domain_id=1, config=config)

        # 应该返回 root 安全组
        assert handle == controller.root_handle

    def test_multiple_domains_same_security(self):
        """测试多域共享同一安全组"""
        mem = Memory(1024 * 1024)
        mem_mgr = MemoryManager(mem)
        controller = SecurityGroupController(mem_mgr)

        # 创建安全组
        config = SecurityGroupConfig(create_new=True, isolated=True)
        handle = controller.create(owner_domain_id=1, config=config)

        # 绑定多个域
        controller.bind_domain(handle, 1)
        controller.bind_domain(handle, 2)

        instance = controller.get_instance(handle)
        assert instance.ref_count == 2
        assert 1 in instance.bound_domains
        assert 2 in instance.bound_domains

    def test_security_group_destroy(self):
        """测试销毁安全组"""
        mem = Memory(1024 * 1024)
        mem_mgr = MemoryManager(mem)
        controller = SecurityGroupController(mem_mgr)

        # 创建安全组 (owner_domain_id=1 在 EXPECTED_ATTESTATION_IDS 中)
        config = SecurityGroupConfig(create_new=True)
        handle = controller.create(owner_domain_id=1, config=config)

        # 绑定域
        controller.bind_domain(handle, 1)

        # 引用计数不为 0，无法销毁
        assert controller.destroy(handle, caller_id=1) is False

        # 解绑
        controller.unbind_domain(handle, 1)

        # 现在可以销毁（调用者是 owner）
        assert controller.destroy(handle, caller_id=1) is True
        assert controller.get_instance(handle) is None

        # 测试非 owner 无法销毁
        handle2 = controller.create(owner_domain_id=1, config=config)
        assert handle2 != 0
        assert controller.destroy(handle2, caller_id=2) is False  # 非 owner
        assert controller.destroy(handle2, caller_id=1) is True   # owner 可以销毁

    def test_force_destroy(self):
        """测试强制销毁（仅 root 域可用）"""
        mem = Memory(1024 * 1024)
        mem_mgr = MemoryManager(mem)
        controller = SecurityGroupController(mem_mgr)

        # 创建安全组 (owner_domain_id=1 在 EXPECTED_ATTESTATION_IDS 中)
        config = SecurityGroupConfig(create_new=True)
        handle = controller.create(owner_domain_id=1, config=config)

        # 绑定域
        controller.bind_domain(handle, 1)

        # 非 root 域无法强制销毁
        assert controller.destroy_force(handle, caller_id=1) is False

        # root 域可以强制销毁（不检查引用计数）
        assert controller.destroy_force(handle, caller_id=0) is True
        assert controller.get_instance(handle) is None

        # root 安全组不能销毁
        assert controller.destroy_force(controller.root_handle, caller_id=0) is False

    def test_dma_access_control(self):
        """测试 DMA 访问控制"""
        mem = Memory(1024 * 1024)
        mem_mgr = MemoryManager(mem)
        controller = SecurityGroupController(mem_mgr)

        # 创建安全组
        config = SecurityGroupConfig(create_new=True)
        handle = controller.create(owner_domain_id=1, config=config)

        # 绑定两个域
        controller.bind_domain(handle, 1)
        controller.bind_domain(handle, 2)

        # 同一安全组内允许访问
        assert controller.check_dma_access(handle, 1, 'read') is True
        assert controller.check_dma_access(handle, 2, 'write') is True

        # 添加外部访问者
        controller.add_dma_accessor(handle, 3)
        assert controller.check_dma_access(handle, 3, 'read') is True

        # 移除访问者
        controller.remove_dma_accessor(handle, 3)
        assert controller.check_dma_access(handle, 3, 'read') is False

    def test_confidential_domain(self):
        """测试机密计算域"""
        mem = Memory(1024 * 1024)
        mem_mgr = MemoryManager(mem)
        controller = SecurityGroupController(mem_mgr)

        # 创建机密计算域
        config = SecurityGroupConfig(
            create_new=True,
            isolated=True,
            encrypted=True,
            confidential=True,
            passphrase=0x12345678
        )
        handle = controller.create(owner_domain_id=1, config=config)

        instance = controller.get_instance(handle)
        assert instance.is_confidential is True
        assert instance.encrypted is True
        assert instance.encryption_key != 0

        # 机密计算域禁止添加外部访问者
        assert controller.add_dma_accessor(handle, 2) is False

        # 机密计算域禁止外部访问
        assert controller.check_dma_access(handle, 2, 'read') is False

    def test_encrypted_memory(self):
        """测试加密内存"""
        mem = Memory(1024 * 1024)
        mem_mgr = MemoryManager(mem)
        controller = SecurityGroupController(mem_mgr)

        # 创建加密安全组
        config = SecurityGroupConfig(create_new=True, encrypted=True)
        handle = controller.create(owner_domain_id=1, config=config)

        # 设置加密区域
        success = controller.set_encryption(handle, 0x1000, 0x1000)
        assert success is True

        # 验证加密区域已设置
        instance = controller.get_instance(handle)
        assert instance.encrypted is True


class TestSecurityGroupWithRPALogic:
    """安全组与 RPALogic 集成测试"""

    def test_descend_with_security_group(self):
        """测试 DESCEND 时绑定安全组"""
        mem = Memory(1024 * 1024)
        mem_mgr = MemoryManager(mem)
        controller = SecurityGroupController(mem_mgr)

        rpa = RPALogic()
        rpa.memory = mem
        rpa.set_security_controller(controller)  # 使用 set_security_controller 设置

        # 准备 DomainBlock
        block_addr = 0x1000
        block = DomainBlock(control_block_size=32, trap_vector=0x8004)
        mem.write_word(block_addr + 0x00, block.control_block_size)
        mem.write_word(block_addr + 0x08, block.trap_vector)  # trap_vector at 0x08
        mem.write_word(block_addr + 0x1C, 0)  # security_group = 0 (继承)

        # DESCEND
        result = rpa.descend(block_addr)

        assert result['is_first'] is True
        assert rpa.current_domain.domain_id == 1

        # 验证安全组继承
        assert rpa.current_domain.block.security_group == controller.root_handle

    def test_descend_with_new_security_group(self):
        """测试 DESCEND 时创建新安全组"""
        mem = Memory(1024 * 1024)
        mem_mgr = MemoryManager(mem)
        controller = SecurityGroupController(mem_mgr)

        rpa = RPALogic()
        rpa.memory = mem
        rpa.set_security_controller(controller)

        # 先创建安全组
        config = SecurityGroupConfig(create_new=True, isolated=True)
        sec_handle = controller.create(owner_domain_id=0, config=config)

        # 准备 DomainBlock
        block_addr = 0x1000
        block = DomainBlock(control_block_size=32, trap_vector=0x8004)
        mem.write_word(block_addr + 0x00, block.control_block_size)
        mem.write_word(block_addr + 0x08, block.trap_vector)  # trap_vector at 0x08
        mem.write_word(block_addr + 0x1C, sec_handle)  # 指定安全组 at 0x1C

        # DESCEND
        result = rpa.descend(block_addr)

        assert result['is_first'] is True
        assert rpa.current_domain.block.security_group == sec_handle

        # 验证绑定
        instance = controller.get_instance(sec_handle)
        assert rpa.current_domain.domain_id in instance.bound_domains

    def test_exit_unbinds_security_group(self):
        """测试 EXIT 时解绑安全组"""
        mem = Memory(1024 * 1024)
        mem_mgr = MemoryManager(mem)
        controller = SecurityGroupController(mem_mgr)

        rpa = RPALogic()
        rpa.memory = mem
        rpa.set_security_controller(controller)

        # 创建安全组
        config = SecurityGroupConfig(create_new=True, isolated=True)
        sec_handle = controller.create(owner_domain_id=0, config=config)

        # 准备子域 DomainBlock
        child_block_addr = 0x1000
        mem.write_word(child_block_addr + 0x00, 32)
        mem.write_word(child_block_addr + 0x08, 0x8004)  # trap_vector at 0x08
        mem.write_word(child_block_addr + 0x1C, sec_handle)  # security_group at 0x1C

        # DESCEND
        rpa.descend(child_block_addr)
        child_domain_id = rpa.current_domain.domain_id

        # 验证绑定
        instance = controller.get_instance(sec_handle)
        assert child_domain_id in instance.bound_domains

        # EXIT
        rpa.ascend(0, release=True)

        # 验证解绑
        instance = controller.get_instance(sec_handle)
        assert child_domain_id not in instance.bound_domains


class TestSecurityGroupSysop:
    """sysop secgroup 指令测试"""

    def test_sysop_create(self):
        """测试 sysop secgroup create"""
        mem = Memory(1024 * 1024)
        mem_mgr = MemoryManager(mem)
        controller = SecurityGroupController(mem_mgr)

        rpa = RPALogic()
        rpa.memory = mem

        isa = SimpleISA(rpa, mem, mem_mgr, security_controller=controller)
        isa.state.set_reg(0, 0x01)  # isolated

        # 模拟 sysop secgroup, create
        isa._execute_sysop_secgroup(0x01, 0, 0, 1, 0)

        handle = isa.state.get_reg(1)
        assert handle >= SecurityGroupController.HANDLE_BASE

    def test_sysop_destroy(self):
        """测试 sysop secgroup destroy"""
        mem = Memory(1024 * 1024)
        mem_mgr = MemoryManager(mem)
        controller = SecurityGroupController(mem_mgr)

        rpa = RPALogic()
        rpa.memory = mem

        isa = SimpleISA(rpa, mem, mem_mgr, security_controller=controller)

        # 创建安全组
        config = SecurityGroupConfig(create_new=True)
        handle = controller.create(0, config)

        # destroy 需要 ref_count=0，创建后默认 ref_count=0
        # 销毁：rd=0 (结果存入R0), rn=1 (handle从R1获取)
        isa.state.set_reg(1, handle)  # R1 = handle
        isa._execute_sysop_secgroup(0x02, 0, 0, 0, 1)  # destroy, rd=0, rn=1

        # destroy 返回成功，实例被移除
        result = isa.state.get_reg(0)  # rd 返回值
        assert result == 1  # 成功
        assert controller.get_instance(handle) is None

    def test_sysop_get_handle(self):
        """测试 sysop secgroup get_handle"""
        mem = Memory(1024 * 1024)
        mem_mgr = MemoryManager(mem)
        controller = SecurityGroupController(mem_mgr)

        rpa = RPALogic()
        rpa.memory = mem

        isa = SimpleISA(rpa, mem, mem_mgr, security_controller=controller)

        # 获取 root 域的安全组 handle
        isa.state.set_reg(0, 0)  # domain_id = 0
        isa._execute_sysop_secgroup(0x0A, 0, 0, 1, 0)

        handle = isa.state.get_reg(1)
        assert handle == controller.root_handle


class TestEncryptedMemory:
    """加密内存测试"""

    def test_encrypted_write_read(self):
        """测试加密写入和读取"""
        mem = Memory(1024 * 1024)
        key = 0xDEADBEEFCAFEBABE

        # 设置加密区域
        mem.set_encryption(0x1000, 0x100, 1, key)

        # 写入数据（会自动加密）
        test_data = b'\x01\x02\x03\x04\x05\x06\x07\x08'
        mem.write_bytes(0x1000, test_data, encrypt=True)

        # 直接读取内存（不解密）应该得到加密后的数据
        raw_data = mem.read_bytes(0x1000, 8, decrypt=False)
        assert raw_data != test_data

        # 读取数据（会自动解密）
        decrypted_data = mem.read_bytes(0x1000, 8, decrypt=True)
        assert decrypted_data == test_data

    def test_non_encrypted_region(self):
        """测试非加密区域"""
        mem = Memory(1024 * 1024)
        key = 0xDEADBEEFCAFEBABE

        # 设置加密区域
        mem.set_encryption(0x1000, 0x100, 1, key)

        # 非加密区域写入和读取
        test_data = b'\x01\x02\x03\x04'
        mem.write_bytes(0x2000, test_data, encrypt=True)

        # 非加密区域不会加密
        raw_data = mem.read_bytes(0x2000, 4, decrypt=False)
        assert raw_data == test_data

    def test_clear_encryption(self):
        """测试清除加密区域"""
        mem = Memory(1024 * 1024)
        key = 0xDEADBEEFCAFEBABE

        # 设置加密区域
        mem.set_encryption(0x1000, 0x100, 1, key)

        # 清除
        count = mem.clear_encryption_by_handle(1)
        assert count == 1

        # 再次清除应该返回 0
        count = mem.clear_encryption_by_handle(1)
        assert count == 0


class TestDomainIDAllocation:
    """domain_id 分配测试"""

    def test_domain_id_from_security_controller(self):
        """测试从安全子系统分配 domain_id"""
        mem = Memory(1024 * 1024)
        mem_mgr = MemoryManager(mem)
        controller = SecurityGroupController(mem_mgr)
        controller.enabled = True

        rpa = RPALogic()
        rpa.memory = mem
        rpa.set_security_controller(controller)

        # 创建安全组
        config = SecurityGroupConfig(create_new=True)
        sec_handle = controller.create(0, config)

        # 准备 DomainBlock
        block_addr = 0x1000
        mem.write_word(block_addr + 0x00, 32)
        mem.write_word(block_addr + 0x08, 0x8004)  # trap_vector at 0x08
        mem.write_word(block_addr + 0x1C, sec_handle)  # security_group at 0x1C

        # DESCEND
        result = rpa.descend(block_addr)

        # 验证域已绑定到安全组
        instance = controller.get_instance(sec_handle)
        assert result['domain_id'] in instance.bound_domains

    def test_domain_id_without_security_controller(self):
        """测试无安全子系统时的 domain_id 分配"""
        mem = Memory(1024 * 1024)

        rpa = RPALogic()
        rpa.memory = mem
        # 不设置 security_controller

        # 准备 DomainBlock
        block_addr = 0x1000
        mem.write_word(block_addr + 0x00, 32)
        mem.write_word(block_addr + 0x08, 0x8004)  # trap_vector at 0x08

        # DESCEND
        result = rpa.descend(block_addr)

        # domain_id 应该从 RPALogic 分配（1, 2, 3...）
        assert result['domain_id'] == 1


class TestConfidentialDomainDestruction:
    """机密域销毁测试 - 安全子系统入口模式"""

    def test_confidential_destroy_authorized_parent(self):
        """测试父域授权销毁机密子域"""
        mem = Memory(1024 * 1024)
        mem_mgr = MemoryManager(mem)
        controller = SecurityGroupController(mem_mgr)

        rpa = RPALogic()
        rpa.memory = mem
        rpa.set_security_controller(controller)

        # 创建父域安全组 (VM Manager, domain_id=1)
        parent_config = SecurityGroupConfig(create_new=True, isolated=True)
        parent_handle = controller.create(owner_domain_id=1, config=parent_config)

        # 创建子域安全组 (Confidential VM, is_confidential=True)
        child_config = SecurityGroupConfig(
            create_new=True,
            isolated=True,
            confidential=True
        )
        child_handle = controller.create(owner_domain_id=2, config=child_config)

        # 绑定域
        controller.bind_domain(parent_handle, 1)  # 父域绑定
        controller.bind_domain(child_handle, 2)   # 子域绑定

        # 设置父子关系（通过 DESCEND）
        parent_block_addr = 0x1000
        child_block_addr = 0x2000

        # 父域 DCB
        mem.write_word(parent_block_addr + 0x00, 32)  # control_block_size
        mem.write_word(parent_block_addr + 0x1C, parent_handle)  # security_group

        # 子域 DCB（父域创建）
        mem.write_word(child_block_addr + 0x00, 32)  # control_block_size
        mem.write_word(child_block_addr + 0x1C, child_handle)  # security_group
        mem.write_word(child_block_addr + 0x08, 0x8004)  # trap_vector

        # DESCEND 创建父子关系
        rpa.descend(parent_block_addr)  # 创建父域
        rpa.descend(child_block_addr)   # 创建子域（父域是当前域）

        # 验证父子关系
        assert rpa.verify_parent_child(1, 2)  # domain 1 是 domain 2 的父域

        # 父域请求销毁机密子域
        success, message = controller.request_destroy_confidential(
            handle=child_handle,
            caller_domain_id=1,
            rpa_logic=rpa
        )

        assert success is True
        assert "destroyed" in message.lower()
        assert controller.get_instance(child_handle) is None  # 已销毁

    def test_confidential_destroy_unauthorized_domain(self):
        """测试非父域尝试销毁机密域（应被拒绝）"""
        mem = Memory(1024 * 1024)
        mem_mgr = MemoryManager(mem)
        controller = SecurityGroupController(mem_mgr)

        rpa = RPALogic()
        rpa.memory = mem
        rpa.set_security_controller(controller)

        # 创建合法父域 (VM Manager, domain_id=1)
        parent_config = SecurityGroupConfig(create_new=True, isolated=True)
        parent_handle = controller.create(owner_domain_id=1, config=parent_config)

        # 创建机密子域 (Confidential VM, domain_id=2)
        child_config = SecurityGroupConfig(
            create_new=True,
            isolated=True,
            confidential=True
        )
        child_handle = controller.create(owner_domain_id=2, config=child_config)

        # 创建恶意域 (Malicious Domain, domain_id=3)
        malicious_config = SecurityGroupConfig(create_new=True, isolated=True)
        malicious_handle = controller.create(owner_domain_id=3, config=malicious_config)

        # 绑定域
        controller.bind_domain(parent_handle, 1)
        controller.bind_domain(child_handle, 2)
        controller.bind_domain(malicious_handle, 3)

        # 设置正确的父子关系
        parent_block_addr = 0x1000
        child_block_addr = 0x2000

        mem.write_word(parent_block_addr + 0x00, 32)
        mem.write_word(parent_block_addr + 0x1C, parent_handle)

        mem.write_word(child_block_addr + 0x00, 32)
        mem.write_word(child_block_addr + 0x1C, child_handle)
        mem.write_word(child_block_addr + 0x08, 0x8004)

        rpa.descend(parent_block_addr)
        rpa.descend(child_block_addr)

        # 恶意域尝试销毁机密子域
        success, message = controller.request_destroy_confidential(
            handle=child_handle,
            caller_domain_id=3,  # 恶意域
            rpa_logic=rpa
        )

        assert success is False
        assert "denied" in message.lower()
        assert controller.get_instance(child_handle) is not None  # 未销毁

    def test_root_can_destroy_any_confidential(self):
        """测试 Root 可以销毁任何机密域"""
        mem = Memory(1024 * 1024)
        mem_mgr = MemoryManager(mem)
        controller = SecurityGroupController(mem_mgr)

        rpa = RPALogic()
        rpa.memory = mem
        rpa.set_security_controller(controller)

        # 创建机密域（不通过 DESCEND，直接创建安全组）
        child_config = SecurityGroupConfig(
            create_new=True,
            isolated=True,
            confidential=True
        )
        child_handle = controller.create(owner_domain_id=2, config=child_config)
        controller.bind_domain(child_handle, 2)

        # Root (domain_id=0) 请求销毁
        success, message = controller.request_destroy_confidential(
            handle=child_handle,
            caller_domain_id=0,  # Root
            rpa_logic=rpa
        )

        assert success is True
        assert "destroyed" in message.lower()

    def test_non_confidential_rejected(self):
        """测试非机密域不能使用 request_destroy_confidential"""
        mem = Memory(1024 * 1024)
        mem_mgr = MemoryManager(mem)
        controller = SecurityGroupController(mem_mgr)

        rpa = RPALogic()
        rpa.memory = mem
        rpa.set_security_controller(controller)

        # 创建普通安全组（非机密）
        normal_config = SecurityGroupConfig(
            create_new=True,
            isolated=True,
            confidential=False  # 非机密
        )
        normal_handle = controller.create(owner_domain_id=1, config=normal_config)

        # 尝试使用 request_destroy_confidential
        success, message = controller.request_destroy_confidential(
            handle=normal_handle,
            caller_domain_id=0,
            rpa_logic=rpa
        )

        assert success is False
        assert "not a confidential domain" in message.lower()

    def test_hierarchy_query(self):
        """测试域层次查询接口"""
        mem = Memory(1024 * 1024)
        mem_mgr = MemoryManager(mem)
        controller = SecurityGroupController(mem_mgr)

        rpa = RPALogic()
        rpa.memory = mem
        rpa.set_security_controller(controller)

        # 创建三层域结构
        # Root (id=0) -> Parent (id=1) -> Child (id=2)
        parent_block_addr = 0x1000
        child_block_addr = 0x2000

        parent_handle = controller.create(owner_domain_id=1, config=SecurityGroupConfig(create_new=True))
        child_handle = controller.create(owner_domain_id=2, config=SecurityGroupConfig(create_new=True))

        mem.write_word(parent_block_addr + 0x00, 32)
        mem.write_word(parent_block_addr + 0x1C, parent_handle)

        mem.write_word(child_block_addr + 0x00, 32)
        mem.write_word(child_block_addr + 0x1C, child_handle)
        mem.write_word(child_block_addr + 0x08, 0x8004)

        # 创建层次
        rpa.descend(parent_block_addr)  # domain 1, parent is root
        rpa.descend(child_block_addr)   # domain 2, parent is domain 1

        # 查询层次
        hierarchy = rpa.get_domain_hierarchy()
        assert 0 in hierarchy  # root
        assert 1 in hierarchy  # parent
        assert 2 in hierarchy  # child

        # 验证父子关系
        assert hierarchy[1]["parent_id"] == 0  # parent's parent is root
        assert hierarchy[2]["parent_id"] == 1  # child's parent is parent

        # 验证路径查询
        path = rpa.get_domain_path_to_root(2)
        assert path == [2, 1, 0]

    def test_is_confidential_handle(self):
        """测试机密域检测"""
        mem = Memory(1024 * 1024)
        mem_mgr = MemoryManager(mem)
        controller = SecurityGroupController(mem_mgr)

        # 创建机密安全组
        confidential_config = SecurityGroupConfig(
            create_new=True,
            confidential=True
        )
        confidential_handle = controller.create(owner_domain_id=1, config=confidential_config)

        # 创建普通安全组
        normal_config = SecurityGroupConfig(
            create_new=True,
            confidential=False
        )
        normal_handle = controller.create(owner_domain_id=2, config=normal_config)

        assert controller.is_confidential_handle(confidential_handle) is True
        assert controller.is_confidential_handle(normal_handle) is False


if __name__ == '__main__':
    pytest.main([__file__, '-v'])