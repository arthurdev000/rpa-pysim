"""
Thread and Exception Tests for RPA

使用汇编指令测试 DESCEND/ESCALATE/RETURN 机制。
所有测试使用单一 Core，让指令真正执行域切换。

DomainBlock 布局:
    0x00: ctrlblock_size
    0x04: exception_vector
    0x08: reserved
    0x0C: interrupt_ctrl
    0x10: memtable_address
    0x14: domain_id
    0x18: reserved (原 parent_block)
    0x1C: child_block
    0x20: security_domain
    0x24: access_id
    0x28: saved_sp (ISA 扩展)
    0x2C: saved_lr (ISA 扩展 - 首次 DESCEND 入口地址由父域写入，ESCALATE 保存返回地址)
    0x30: saved_psr (ISA 扩展)
"""

import pytest
from rpa_sim import (
    Memory, SimpleISA, MemoryManager, DomainBlock, RPALogic, CTRLBLOCK_SIZE
)
from rpa_sim.isa_simple import (
    SAVED_SP_OFFSET as OFFSET_SAVED_SP,
    SAVED_LR_OFFSET as OFFSET_SAVED_LR,
    SAVED_PSR_OFFSET as OFFSET_SAVED_PSR
)


# 偏移常量
OFFSET_CTRLBLOCK_SIZE = 0x00
OFFSET_EXCEPTION_VECTOR = 0x04
OFFSET_INTERRUPT_CTRL = 0x0C
OFFSET_MEMTABLE_ADDRESS = 0x10
OFFSET_DOMAIN_ID = 0x14
OFFSET_RESERVED_18 = 0x18
OFFSET_CHILD_BLOCK = 0x1C


class TestDescendEscalate:
    """
    测试 DESCEND 和 ESCALATE 指令
    """

    def test_first_descend_jumps_to_saved_lr(self):
        """
        首次 DESCEND 跳转到 saved_lr (父域在 DESCEND 前写入入口地址)
        """
        mem = Memory(size=64 * 1024)

        # 设置控制块
        block_addr = 0x1000
        entry_addr = 0x2000
        mem.write_word(block_addr + OFFSET_CTRLBLOCK_SIZE, CTRLBLOCK_SIZE)  # ctrlblock_size
        mem.write_word(block_addr + OFFSET_EXCEPTION_VECTOR, 0)             # exception_vector
        mem.write_word(block_addr + OFFSET_MEMTABLE_ADDRESS, 0)             # memtable_address
        mem.write_word(block_addr + OFFSET_SAVED_LR, entry_addr)            # saved_lr = 入口地址

        rpa = RPALogic()
        rpa.memory = mem
        # 设置父域的 exception_vector
        rpa.root_domain.block.exception_vector = 0x3000

        core = SimpleISA(rpa=rpa, memory=mem)

        # 主程序
        core.load_assembly("""
            MOV R0, #0x1000    ; 控制块地址
            DESCEND R0
            ; DESCEND 后应该跳转到子域，不会执行到这里
            MOV R5, #0xBAD
            HALT
        """, base_addr=0x0000)

        # 子域代码
        core.load_assembly("""
            MOV R1, #42
            ESCALATE R1
            HALT
        """, base_addr=entry_addr)

        # 异常处理代码 - 父域接收 ESCALATE
        core.load_assembly("""
            ; 父域收到 ESCALATE
            HALT
        """, base_addr=0x3000)

        core.state.pc = 0x0000
        core.domain_block_addr = 0

        core.run()

        # 验证：跳转到了子域代码
        assert core.state.get_reg(1) == 42
        # R5 不应该被设置（没有执行 MOV R5, #0xBAD）
        assert core.state.get_reg(5) == 0

    def test_escalate_jumps_to_exception_vector(self):
        """
        ESCALATE 跳转到父域的 exception_vector
        """
        mem = Memory(size=64 * 1024)

        # 子域控制块
        block_addr = 0x1000
        entry_addr = 0x2000
        mem.write_word(block_addr + OFFSET_CTRLBLOCK_SIZE, CTRLBLOCK_SIZE)  # ctrlblock_size
        mem.write_word(block_addr + OFFSET_EXCEPTION_VECTOR, 0)             # exception_vector
        mem.write_word(block_addr + OFFSET_MEMTABLE_ADDRESS, 0)             # memtable_address
        mem.write_word(block_addr + OFFSET_SAVED_LR, entry_addr)            # saved_lr = 入口地址

        rpa = RPALogic()
        rpa.memory = mem
        core = SimpleISA(rpa=rpa, memory=mem)

        # 修改父域（根域）的 exception_vector
        rpa.root_domain.block.exception_vector = 0x3000

        core.load_assembly("""
            MOV R0, #0x1000
            DESCEND R0
            HALT
        """, base_addr=0x0000)

        core.load_assembly("""
            MOV R1, #42
            ESCALATE R1
            HALT
        """, base_addr=entry_addr)

        # 父域异常处理代码 - 执行后 halt
        core.load_assembly("""
            MOV R2, #0xCAFE
            HALT
        """, base_addr=0x3000)

        core.state.pc = 0x0000
        core.run()

        # 验证：ESCALATE 跳转到了父域的 exception_vector 并执行了异常处理代码
        assert core.state.get_reg(2) == 0xCAFE

    def test_descend_updates_memtable_chain(self):
        """
        DESCEND 更新 memtable_chain，ESCALATE 恢复
        """
        mem = Memory(size=64 * 1024)

        block_addr = 0x0800
        mem.write_word(block_addr + OFFSET_CTRLBLOCK_SIZE, CTRLBLOCK_SIZE)  # ctrlblock_size
        mem.write_word(block_addr + OFFSET_EXCEPTION_VECTOR, 0)             # exception_vector
        mem.write_word(block_addr + OFFSET_MEMTABLE_ADDRESS, 0x10000)       # memtable_address
        mem.write_word(block_addr + OFFSET_SAVED_LR, 0x2000)                # saved_lr = 入口地址

        rpa = RPALogic()
        rpa.memory = mem
        core = SimpleISA(rpa=rpa, memory=mem)
        core.memtable_chain = []

        core.load_assembly("""
            MOV R0, #0x0800
            DESCEND R0
        """, base_addr=0x0000)

        core.load_assembly("""
            MOV R0, #0
            ESCALATE R0
            HALT
        """, base_addr=0x2000)

        rpa.root_domain.block.exception_vector = 0x3000
        core.load_assembly("HALT", base_addr=0x3000)

        core.state.pc = 0x0000
        core.run()

        # ESCALATE 后 memtable_chain 应该恢复为空
        assert core.memtable_chain == []

    def test_shared_memory_between_domains(self):
        """
        父子域共享内存（memtable_address = 0）
        """
        mem = Memory(size=64 * 1024)

        # 共享数据
        shared_addr = 0x5000
        mem.write_word(shared_addr, 100)

        block_addr = 0x1000
        mem.write_word(block_addr + OFFSET_CTRLBLOCK_SIZE, CTRLBLOCK_SIZE)  # ctrlblock_size
        mem.write_word(block_addr + OFFSET_EXCEPTION_VECTOR, 0)             # exception_vector
        mem.write_word(block_addr + OFFSET_MEMTABLE_ADDRESS, 0)             # memtable_address = 0 (共享)
        mem.write_word(block_addr + OFFSET_SAVED_LR, 0x2000)                # saved_lr = 入口地址

        rpa = RPALogic()
        rpa.memory = mem
        core = SimpleISA(rpa=rpa, memory=mem)

        # 主程序
        core.load_assembly("""
            MOV R0, #0x1000
            DESCEND R0
            ; 子域返回后
            MOV R1, #0x5000
            LDR R2, [R1]
            HALT
        """, base_addr=0x0000)

        # 子域：+200
        core.load_assembly("""
            MOV R1, #0x5000
            LDR R0, [R1]
            ADD R0, R0, #200
            STR R0, [R1]
            MOV R0, #0
            ESCALATE R0
            HALT
        """, base_addr=0x2000)

        # 设置父域的 exception_vector 让 ESCALATE 后 halt
        rpa.root_domain.block.exception_vector = 0x3000
        core.load_assembly("HALT", base_addr=0x3000)

        core.state.pc = 0x0000
        core.run()

        # 共享数据被修改
        assert mem.read_word(shared_addr) == 300

    def test_child_block_tracking(self):
        """
        测试 child_block 字段正确跟踪子域
        """
        mem = Memory(size=64 * 1024)

        # 子域控制块
        child_block_addr = 0x1000
        entry_addr = 0x2000
        mem.write_word(child_block_addr + OFFSET_CTRLBLOCK_SIZE, CTRLBLOCK_SIZE)
        mem.write_word(child_block_addr + OFFSET_EXCEPTION_VECTOR, 0)
        mem.write_word(child_block_addr + OFFSET_MEMTABLE_ADDRESS, 0)
        mem.write_word(child_block_addr + OFFSET_SAVED_LR, entry_addr)

        rpa = RPALogic()
        rpa.memory = mem
        core = SimpleISA(rpa=rpa, memory=mem)

        core.load_assembly("""
            MOV R0, #0x1000
            DESCEND R0
            HALT
        """, base_addr=0x0000)

        core.load_assembly("""
            MOV R1, #1
            ESCALATE R1
            HALT
        """, base_addr=entry_addr)

        rpa.root_domain.block.exception_vector = 0x3000
        core.load_assembly("HALT", base_addr=0x3000)

        core.state.pc = 0x0000
        core.run()

        # 验证 child_block 被正确写入父域
        child_block = mem.read_word(0 + OFFSET_CHILD_BLOCK)  # 根域 block_addr 是 0
        assert child_block == child_block_addr


class TestMemoryTranslation:
    """
    测试带地址翻译的内存访问
    """

    def test_ldr_with_translation(self):
        """
        LDR 通过页表翻译地址
        """
        mem = Memory(size=64 * 1024)
        mm = MemoryManager(physical_memory=mem)

        # 创建页表：VA 0x1000 -> PA 0x2000
        pt = mm.create_page_table(base_addr=0x10000, owner_domain=1)
        pt.map(0x1000, 0x2000)

        # 写入数据到物理地址
        mem.write_word(0x2000, 0xDEADBEEF)

        rpa = RPALogic()
        core = SimpleISA(rpa=rpa, memory=mem, memory_manager=mm)
        core.memtable_chain = [0x10000]

        core.load_assembly("""
            MOV R1, #0x1000
            LDR R0, [R1]
            HALT
        """, base_addr=0x3000)

        core.state.pc = 0x3000
        core.run()

        # 读到翻译后的数据
        assert core.state.get_reg(0) == 0xDEADBEEF

    def test_str_with_translation(self):
        """
        STR 通过页表翻译地址
        """
        mem = Memory(size=64 * 1024)
        mm = MemoryManager(physical_memory=mem)

        pt = mm.create_page_table(base_addr=0x10000, owner_domain=1)
        pt.map(0x1000, 0x2000)

        rpa = RPALogic()
        core = SimpleISA(rpa=rpa, memory=mem, memory_manager=mm)
        core.memtable_chain = [0x10000]

        core.load_assembly("""
            MOV R0, #0xCAFEBABE
            MOV R1, #0x1000
            STR R0, [R1]
            HALT
        """, base_addr=0x3000)

        core.state.pc = 0x3000
        core.run()

        # 写入到翻译后的地址
        assert mem.read_word(0x2000) == 0xCAFEBABE
        assert mem.read_word(0x1000) == 0

    def test_descend_with_memtable(self):
        """
        DESCEND 带页表，子域使用独立的地址空间
        """
        mem = Memory(size=64 * 1024)
        mm = MemoryManager(physical_memory=mem)

        # Domain 0 页表（根页表）
        pt0 = mm.create_page_table(base_addr=0x10000, owner_domain=0)
        pt0.map(0x0000, 0x0000)  # 代码段
        pt0.map(0x3000, 0x3000)  # 数据段

        # Domain 1 页表
        # VA 0x1000 -> IPA 0x3000
        pt1 = mm.create_page_table(base_addr=0x20000, owner_domain=1)
        pt1.map(0x1000, 0x3000)

        # 设置控制块
        block_addr = 0x0800
        mem.write_word(block_addr + OFFSET_CTRLBLOCK_SIZE, CTRLBLOCK_SIZE)
        mem.write_word(block_addr + OFFSET_EXCEPTION_VECTOR, 0)
        mem.write_word(block_addr + OFFSET_MEMTABLE_ADDRESS, 0x20000)
        mem.write_word(block_addr + OFFSET_SAVED_LR, 0x2000)

        rpa = RPALogic()
        rpa.memory = mem
        core = SimpleISA(rpa=rpa, memory=mem, memory_manager=mm)
        core.memtable_chain = [0x10000]  # Domain 0 的页表

        # 主程序
        core.load_assembly("""
            MOV R0, #0x0800
            DESCEND R0
            HALT
        """, base_addr=0x0000)

        # 子域代码
        core.load_assembly("""
            MOV R1, #0x1000
            LDR R0, [R1]
            ESCALATE R0
            HALT
        """, base_addr=0x2000)

        # 在 PA 0x3000 写入数据
        mem.write_word(0x3000, 0x12345678)

        rpa.root_domain.block.exception_vector = 0x4000
        core.load_assembly("HALT", base_addr=0x4000)

        core.state.pc = 0x0000
        core.run()

        # 子域读到了翻译后的数据
        assert core.state.get_reg(0) == 0x12345678


class TestFaultHandling:
    """
    测试异常处理
    """

    def test_translation_fault(self):
        """
        访问未映射地址触发 fault_handler
        """
        mem = Memory(size=64 * 1024)
        mm = MemoryManager(physical_memory=mem)

        # 创建页表但不映射
        pt = mm.create_page_table(base_addr=0x10000, owner_domain=2)

        rpa = RPALogic()
        core = SimpleISA(rpa=rpa, memory=mem, memory_manager=mm)
        core.memtable_chain = [0x10000]

        core.load_assembly("""
            MOV R0, #0x5000
            LDR R1, [R0]
            HALT
        """, base_addr=0x2000)

        fault_info = {}

        def on_fault(fault_type, va, info):
            fault_info['type'] = fault_type
            fault_info['va'] = va
            fault_info['owner'] = info
            core.halted = True

        core.fault_handler = on_fault
        core.state.pc = 0x2000
        core.run()

        assert fault_info['type'] == 'translation'
        assert fault_info['va'] == 0x5000
        assert fault_info['owner'] == 2

    def test_bus_error(self):
        """
        访问超出物理内存范围触发 fault_handler
        """
        mem = Memory(size=1024)  # 1KB 内存

        rpa = RPALogic()
        core = SimpleISA(rpa=rpa, memory=mem)

        core.load_assembly("""
            MOV R0, #0x10000   ; 超出范围
            LDR R1, [R0]
            HALT
        """, base_addr=0x0100)

        fault_info = {}

        def on_fault(fault_type, va, info):
            fault_info['type'] = fault_type
            fault_info['va'] = va
            core.halted = True

        core.fault_handler = on_fault
        core.state.pc = 0x0100
        core.run()

        assert fault_info['type'] == 'memory'
        assert fault_info['va'] == 0x10000


class TestMultiLevelTranslation:
    """
    测试多级地址翻译
    """

    def test_two_level_translation(self):
        """
        两级页表翻译：
        Domain 1 VA -> Domain 1 IPA -> Domain 0 PA
        """
        mem = Memory(size=64 * 1024)
        mm = MemoryManager(physical_memory=mem)

        # Domain 0 页表（根页表）
        # IPA 0x2000 -> PA 0x3000
        pt0 = mm.create_page_table(base_addr=0x10000, owner_domain=0)
        pt0.map(0x2000, 0x3000)

        # Domain 1 页表
        # VA 0x1000 -> IPA 0x2000
        pt1 = mm.create_page_table(base_addr=0x20000, owner_domain=1)
        pt1.map(0x1000, 0x2000)

        # 写入最终物理地址
        mem.write_word(0x3000, 0xFEEDFACE)

        rpa = RPALogic()
        core = SimpleISA(rpa=rpa, memory=mem, memory_manager=mm)
        # memtable_chain: [Domain 1 页表, Domain 0 页表]
        core.memtable_chain = [0x20000, 0x10000]

        core.load_assembly("""
            MOV R1, #0x1000
            LDR R0, [R1]
            HALT
        """, base_addr=0x4000)

        core.state.pc = 0x4000
        core.run()

        # 读到了翻译后的数据
        assert core.state.get_reg(0) == 0xFEEDFACE

    def test_fault_attribution_to_correct_domain(self):
        """
        翻译失败正确归属到失败的域
        """
        mem = Memory(size=64 * 1024)
        mm = MemoryManager(physical_memory=mem)

        # Domain 0 页表（根页表）- 不映射
        pt0 = mm.create_page_table(base_addr=0x10000, owner_domain=0)

        # Domain 1 页表 - 映射到 IPA
        pt1 = mm.create_page_table(base_addr=0x20000, owner_domain=1)
        pt1.map(0x1000, 0x2000)  # VA -> IPA, 但 IPA 没有 -> PA

        rpa = RPALogic()
        core = SimpleISA(rpa=rpa, memory=mem, memory_manager=mm)
        core.memtable_chain = [0x20000, 0x10000]

        core.load_assembly("""
            MOV R1, #0x1000
            LDR R0, [R1]
            HALT
        """, base_addr=0x4000)

        fault_info = {}

        def on_fault(fault_type, va, info):
            fault_info['type'] = fault_type
            fault_info['va'] = va
            fault_info['owner'] = info
            core.halted = True

        core.fault_handler = on_fault
        core.state.pc = 0x4000
        core.run()

        # 故障应该归属到 Domain 0（因为 Domain 0 的页表翻译失败）
        assert fault_info['type'] == 'translation'
        assert fault_info['owner'] == 0


class TestPermissionChecking:
    """
    测试权限检查
    """

    def test_control_area_requires_sysop_for_read(self):
        """
        控制区域必须用 sysop 访问，LDR 应触发异常
        """
        mem = Memory(size=64 * 1024)
        mm = MemoryManager(physical_memory=mem)

        pt = mm.create_page_table(base_addr=0x10000, owner_domain=1)
        pt.map(0x1000, 0x2000, control=True)

        mem.write_word(0x2000, 0xDEADBEEF)

        rpa = RPALogic()
        core = SimpleISA(rpa=rpa, memory=mem, memory_manager=mm)
        core.memtable_chain = [0x10000]

        core.load_assembly("""
            MOV R1, #0x1000
            LDR R0, [R1]
            HALT
        """, base_addr=0x3000)

        fault_info = {}

        def on_fault(fault_type, va, owner):
            fault_info['type'] = fault_type
            fault_info['va'] = va
            fault_info['owner'] = owner
            core.halted = True

        core.fault_handler = on_fault
        core.state.pc = 0x3000
        core.run()

        assert fault_info['type'] == 'permission'
        assert fault_info['va'] == 0x1000

    def test_control_area_requires_sysop_for_write(self):
        """
        控制区域必须用 sysop 访问，STR 应触发异常
        """
        mem = Memory(size=64 * 1024)
        mm = MemoryManager(physical_memory=mem)

        pt = mm.create_page_table(base_addr=0x10000, owner_domain=1)
        pt.map(0x1000, 0x2000, control=True)

        rpa = RPALogic()
        core = SimpleISA(rpa=rpa, memory=mem, memory_manager=mm)
        core.memtable_chain = [0x10000]

        core.load_assembly("""
            MOV R0, #0xCAFEBABE
            MOV R1, #0x1000
            STR R0, [R1]
            HALT
        """, base_addr=0x3000)

        fault_info = {}

        def on_fault(fault_type, va, owner):
            fault_info['type'] = fault_type
            fault_info['va'] = va
            fault_info['owner'] = owner
            core.halted = True

        core.fault_handler = on_fault
        core.state.pc = 0x3000
        core.run()

        assert fault_info['type'] == 'permission'
        assert fault_info['va'] == 0x1000

    def test_read_only_page_blocks_write(self):
        """
        只读页面应阻止写入
        """
        mem = Memory(size=64 * 1024)
        mm = MemoryManager(physical_memory=mem)

        pt = mm.create_page_table(base_addr=0x10000, owner_domain=1)
        pt.map(0x1000, 0x2000, r=True, w=False)

        rpa = RPALogic()
        core = SimpleISA(rpa=rpa, memory=mem, memory_manager=mm)
        core.memtable_chain = [0x10000]

        core.load_assembly("""
            MOV R0, #0xCAFEBABE
            MOV R1, #0x1000
            STR R0, [R1]
            HALT
        """, base_addr=0x3000)

        fault_info = {}

        def on_fault(fault_type, va, owner):
            fault_info['type'] = fault_type
            fault_info['va'] = va
            fault_info['owner'] = owner
            core.halted = True

        core.fault_handler = on_fault
        core.state.pc = 0x3000
        core.run()

        assert fault_info['type'] == 'permission'
        assert fault_info['va'] == 0x1000

    def test_write_only_page_blocks_read(self):
        """
        只写页面应阻止读取
        """
        mem = Memory(size=64 * 1024)
        mm = MemoryManager(physical_memory=mem)

        pt = mm.create_page_table(base_addr=0x10000, owner_domain=1)
        pt.map(0x1000, 0x2000, r=False, w=True)

        mem.write_word(0x2000, 0xDEADBEEF)

        rpa = RPALogic()
        core = SimpleISA(rpa=rpa, memory=mem, memory_manager=mm)
        core.memtable_chain = [0x10000]

        core.load_assembly("""
            MOV R1, #0x1000
            LDR R0, [R1]
            HALT
        """, base_addr=0x3000)

        fault_info = {}

        def on_fault(fault_type, va, owner):
            fault_info['type'] = fault_type
            fault_info['va'] = va
            fault_info['owner'] = owner
            core.halted = True

        core.fault_handler = on_fault
        core.state.pc = 0x3000
        core.run()

        assert fault_info['type'] == 'permission'
        assert fault_info['va'] == 0x1000

    def test_normal_page_allows_rw(self):
        """
        正常页面（非控制区域）应允许 LDR/STR
        """
        mem = Memory(size=64 * 1024)
        mm = MemoryManager(physical_memory=mem)

        pt = mm.create_page_table(base_addr=0x10000, owner_domain=1)
        pt.map(0x1000, 0x2000)

        rpa = RPALogic()
        core = SimpleISA(rpa=rpa, memory=mem, memory_manager=mm)
        core.memtable_chain = [0x10000]

        core.load_assembly("""
            MOV R0, #0xCAFEBABE
            MOV R1, #0x1000
            STR R0, [R1]
            MOV R2, #0
            LDR R3, [R1]
            HALT
        """, base_addr=0x3000)

        core.state.pc = 0x3000
        core.run()

        assert mem.read_word(0x2000) == 0xCAFEBABE
        assert core.state.get_reg(3) == 0xCAFEBABE