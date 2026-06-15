"""
Thread and Exception Tests for RPA

使用汇编指令测试 DESCEND/ASCEND/RETURN 机制。
所有测试使用单一 Core，让指令真正执行域切换。

DomainBlock 布局 (32 字节):
    0x00: ctrlblock_size   (父域设置)
    0x04: domain_id        (系统分配)
    0x08: trap_vector      (子域设置，0=传播到父域)
    0x0C: interrupt_ctrl   (系统分配)
    0x10: ipa_regions      (父域设置，只读)
    0x14: pagetable        (子域设置，可写)
    0x18: child_block      (父域维护)
    0x1C: security_group  (系统分配)
    ISA 扩展:
    0x28: saved_sp
    0x2C: saved_lr (首次 DESCEND 入口地址由父域写入，ASCEND 保存返回地址)
    0x30: saved_psr
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
OFFSET_DOMAIN_ID = 0x04
OFFSET_TRAP_VECTOR = 0x08
OFFSET_INTERRUPT_CTRL = 0x0C
OFFSET_IPA_REGIONS = 0x10
OFFSET_PAGETABLE = 0x14
OFFSET_CHILD_BLOCK = 0x18
OFFSET_SECURITY_GROUP = 0x1C


class TestDescendAscend:
    """
    测试 DESCEND 和 ASCEND 指令
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
        mem.write_word(block_addr + OFFSET_TRAP_VECTOR, 0)             # trap_vector
        mem.write_word(block_addr + OFFSET_IPA_REGIONS, 0)             # ipa_regions
        mem.write_word(block_addr + OFFSET_SAVED_LR, entry_addr)            # saved_lr = 入口地址

        rpa = RPALogic()
        rpa.memory = mem
        # 设置父域的 trap_vector
        rpa.root_domain.block.trap_vector = 0x3000

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
            ASCEND R1
            HALT
        """, base_addr=entry_addr)

        # 异常处理代码 - 父域接收 ASCEND
        core.load_assembly("""
            ; 父域收到 ASCEND
            HALT
        """, base_addr=0x3000)

        core.state.pc = 0x0000
        core.domain_block_addr = 0

        core.run()

        # 验证：跳转到了子域代码
        assert core.state.get_reg(1) == 42
        # R5 不应该被设置（没有执行 MOV R5, #0xBAD）
        assert core.state.get_reg(5) == 0

    def test_ascend_jumps_to_trap_vector(self):
        """
        ASCEND 跳转到父域的 trap_vector
        """
        mem = Memory(size=64 * 1024)

        # 子域控制块
        block_addr = 0x1000
        entry_addr = 0x2000
        mem.write_word(block_addr + OFFSET_CTRLBLOCK_SIZE, CTRLBLOCK_SIZE)  # ctrlblock_size
        mem.write_word(block_addr + OFFSET_TRAP_VECTOR, 0)             # trap_vector
        mem.write_word(block_addr + OFFSET_IPA_REGIONS, 0)             # ipa_regions
        mem.write_word(block_addr + OFFSET_SAVED_LR, entry_addr)            # saved_lr = 入口地址

        rpa = RPALogic()
        rpa.memory = mem
        core = SimpleISA(rpa=rpa, memory=mem)

        # 修改父域（根域）的 trap_vector
        rpa.root_domain.block.trap_vector = 0x3000

        core.load_assembly("""
            MOV R0, #0x1000
            DESCEND R0
            HALT
        """, base_addr=0x0000)

        core.load_assembly("""
            MOV R1, #42
            ASCEND R1
            HALT
        """, base_addr=entry_addr)

        # 父域异常处理代码 - 执行后 halt
        core.load_assembly("""
            MOV R2, #0xCAFE
            HALT
        """, base_addr=0x3000)

        core.state.pc = 0x0000
        core.run()

        # 验证：ASCEND 跳转到了父域的 trap_vector 并执行了异常处理代码
        assert core.state.get_reg(2) == 0xCAFE

    def test_descend_updates_page_table_chain(self):
        """
        DESCEND 更新 page_table_chain，ASCEND 恢复
        """
        mem = Memory(size=64 * 1024)

        block_addr = 0x0800
        mem.write_word(block_addr + OFFSET_CTRLBLOCK_SIZE, CTRLBLOCK_SIZE)  # ctrlblock_size
        mem.write_word(block_addr + OFFSET_TRAP_VECTOR, 0)             # trap_vector
        mem.write_word(block_addr + OFFSET_IPA_REGIONS, 0x10000)       # ipa_regions
        mem.write_word(block_addr + OFFSET_SAVED_LR, 0x2000)                # saved_lr = 入口地址

        rpa = RPALogic()
        rpa.memory = mem
        core = SimpleISA(rpa=rpa, memory=mem)
        core.page_table_chain = []

        core.load_assembly("""
            MOV R0, #0x0800
            DESCEND R0
        """, base_addr=0x0000)

        core.load_assembly("""
            MOV R0, #0
            ASCEND R0
            HALT
        """, base_addr=0x2000)

        rpa.root_domain.block.trap_vector = 0x3000
        core.load_assembly("HALT", base_addr=0x3000)

        core.state.pc = 0x0000
        core.run()

        # ASCEND 后 page_table_chain 应该恢复为空
        assert core.page_table_chain == []

    def test_shared_memory_between_domains(self):
        """
        父子域共享内存（ipa_regions = 0）
        """
        mem = Memory(size=64 * 1024)

        # 共享数据
        shared_addr = 0x5000
        mem.write_word(shared_addr, 100)

        block_addr = 0x1000
        mem.write_word(block_addr + OFFSET_CTRLBLOCK_SIZE, CTRLBLOCK_SIZE)  # ctrlblock_size
        mem.write_word(block_addr + OFFSET_TRAP_VECTOR, 0)             # trap_vector
        mem.write_word(block_addr + OFFSET_IPA_REGIONS, 0)             # ipa_regions = 0 (共享)
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
            ASCEND R0
            HALT
        """, base_addr=0x2000)

        # 设置父域的 trap_vector 让 ASCEND 后 halt
        rpa.root_domain.block.trap_vector = 0x3000
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
        mem.write_word(child_block_addr + OFFSET_TRAP_VECTOR, 0)
        mem.write_word(child_block_addr + OFFSET_IPA_REGIONS, 0)
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
            ASCEND R1
            HALT
        """, base_addr=entry_addr)

        rpa.root_domain.block.trap_vector = 0x3000
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
        core.page_table_chain = [0x10000]

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
        core.page_table_chain = [0x10000]

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

    def test_descend_with_pagetable(self):
        """
        DESCEND 带页表，子域使用独立的地址空间

        父域为子域设置页表地址，子域通过页表翻译访问内存。
        - ipa_regions (0x10): IPA 区域约束（父域设置，子域只读）
        - pagetable (0x18): 页表地址（子域可写，但父域也可预设）
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
        mem.write_word(block_addr + OFFSET_TRAP_VECTOR, 0)
        mem.write_word(block_addr + OFFSET_IPA_REGIONS, 0)       # ipa_regions = 0 (无约束)
        mem.write_word(block_addr + OFFSET_PAGETABLE, 0x20000)   # pagetable = Domain 1 的页表
        mem.write_word(block_addr + OFFSET_SAVED_LR, 0x2000)

        rpa = RPALogic()
        rpa.memory = mem
        core = SimpleISA(rpa=rpa, memory=mem, memory_manager=mm)
        core.page_table_chain = [0x10000]  # Domain 0 的页表

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
            ASCEND R0
            HALT
        """, base_addr=0x2000)

        # 在 PA 0x3000 写入数据
        mem.write_word(0x3000, 0x12345678)

        rpa.root_domain.block.trap_vector = 0x4000
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
        core.page_table_chain = [0x10000]

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
        # page_table_chain: [Domain 1 页表, Domain 0 页表]
        core.page_table_chain = [0x20000, 0x10000]

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
        core.page_table_chain = [0x20000, 0x10000]

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
        core.page_table_chain = [0x10000]

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
        core.page_table_chain = [0x10000]

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
        core.page_table_chain = [0x10000]

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
        core.page_table_chain = [0x10000]

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
        core.page_table_chain = [0x10000]

        core.load_assembly("""
            MOV R0, #0xCAFEBABE
            MOV R1, #0x1000
            STR R0, [R1]
            MOV R2, #0
            LDR R3, [R1]
            HALT
        """, base_addr=0x3000)


class TestSysopMemtable:
    """
    测试 sysop memtable 指令
    """

    def test_sysop_memtable_query(self):
        """
        sysop memtable, query, #index, #regmask 查询 IPA 区域表
        """
        mem = Memory(size=128 * 1024)  # 128KB

        # 创建 IPA 区域表 (3 个条目 + 结束标记)
        # 条目格式: base(4) + size(4) + attr(4) = 12 字节
        table_addr = 0x10000
        # 条目 0: base=0x0000, size=0x1000, attr=0x07 (rwx)
        mem.write_word(table_addr + 0, 0x0000)
        mem.write_word(table_addr + 4, 0x1000)
        mem.write_word(table_addr + 8, 0x07)
        # 条目 1: base=0x2000, size=0x2000, attr=0x03 (rw)
        mem.write_word(table_addr + 12, 0x2000)
        mem.write_word(table_addr + 16, 0x2000)
        mem.write_word(table_addr + 20, 0x03)
        # 条目 2: base=0x8000, size=0x1000, attr=0x05 (rx)
        mem.write_word(table_addr + 24, 0x8000)
        mem.write_word(table_addr + 28, 0x1000)
        mem.write_word(table_addr + 32, 0x05)
        # 结束标记
        mem.write_word(table_addr + 36, 0)
        mem.write_word(table_addr + 40, 0)
        mem.write_word(table_addr + 44, 0)

        rpa = RPALogic()
        core = SimpleISA(rpa=rpa, memory=mem)
        core.ipa_regions = table_addr

        # 查询条目 1，结果存入 R0=base, R1=size, R2=attr
        # regmask = 0b00000111 = 0x07 (R0, R1, R2)
        core.load_assembly("""
            SYSOP memtable, query, #1, #0x07
            HALT
        """, base_addr=0x0000)

        core.state.pc = 0x0000
        core.run()

        assert core.state.get_reg(0) == 0x2000  # base
        assert core.state.get_reg(1) == 0x2000  # size
        assert core.state.get_reg(2) == 0x03    # attr

    def test_sysop_memtable_query_different_regs(self):
        """
        使用不同的寄存器掩码
        """
        mem = Memory(size=128 * 1024)

        table_addr = 0x10000
        # 条目 0: base=0x1000, size=0x2000, attr=0x0F
        mem.write_word(table_addr + 0, 0x1000)
        mem.write_word(table_addr + 4, 0x2000)
        mem.write_word(table_addr + 8, 0x0F)
        # 结束标记
        mem.write_word(table_addr + 12, 0)
        mem.write_word(table_addr + 16, 0)
        mem.write_word(table_addr + 20, 0)

        rpa = RPALogic()
        core = SimpleISA(rpa=rpa, memory=mem)
        core.ipa_regions = table_addr

        # 使用 regmask = 0b00111000 = 0x38 (R3, R4, R5)
        # base -> R3, size -> R4, attr -> R5
        core.load_assembly("""
            SYSOP memtable, query, #0, #0x38
            HALT
        """, base_addr=0x0000)

        core.state.pc = 0x0000
        core.run()

        assert core.state.get_reg(3) == 0x1000  # base
        assert core.state.get_reg(4) == 0x2000  # size
        assert core.state.get_reg(5) == 0x0F    # attr

    def test_sysop_memtable_count(self):
        """
        sysop memtable, count, Rd 返回条目数
        """
        mem = Memory(size=128 * 1024)

        table_addr = 0x10000
        # 条目 0
        mem.write_word(table_addr + 0, 0x0000)
        mem.write_word(table_addr + 4, 0x1000)
        mem.write_word(table_addr + 8, 0x07)
        # 条目 1
        mem.write_word(table_addr + 12, 0x2000)
        mem.write_word(table_addr + 16, 0x2000)
        mem.write_word(table_addr + 20, 0x03)
        # 结束标记
        mem.write_word(table_addr + 24, 0)
        mem.write_word(table_addr + 28, 0)
        mem.write_word(table_addr + 32, 0)

        rpa = RPALogic()
        core = SimpleISA(rpa=rpa, memory=mem)
        core.ipa_regions = table_addr

        core.load_assembly("""
            SYSOP memtable, count, R4
            HALT
        """, base_addr=0x0000)

        core.state.pc = 0x0000
        core.run()

        assert core.state.get_reg(4) == 2  # 2 个条目

    def test_sysop_memtable_query_out_of_range(self):
        """
        查询超出范围的条目返回全零
        """
        mem = Memory(size=128 * 1024)

        table_addr = 0x10000
        # 只有 1 个条目
        mem.write_word(table_addr + 0, 0x1000)
        mem.write_word(table_addr + 4, 0x2000)
        mem.write_word(table_addr + 8, 0x07)
        # 结束标记
        mem.write_word(table_addr + 12, 0)
        mem.write_word(table_addr + 16, 0)
        mem.write_word(table_addr + 20, 0)

        rpa = RPALogic()
        core = SimpleISA(rpa=rpa, memory=mem)
        core.ipa_regions = table_addr

        # 查询条目 5 (不存在)
        core.load_assembly("""
            SYSOP memtable, query, #5, #0x07
            HALT
        """, base_addr=0x0000)

        core.state.pc = 0x0000
        core.run()

        assert core.state.get_reg(0) == 0  # base
        assert core.state.get_reg(1) == 0  # size
        assert core.state.get_reg(2) == 0  # attr

    def test_sysop_memtable_query_no_table(self):
        """
        ipa_regions 为 0 时返回全零
        """
        mem = Memory(size=64 * 1024)

        rpa = RPALogic()
        core = SimpleISA(rpa=rpa, memory=mem)
        core.ipa_regions = 0  # 无 IPA 区域表

        core.load_assembly("""
            SYSOP memtable, query, #0, #0x07
            HALT
        """, base_addr=0x0000)

        core.state.pc = 0x0000
        core.run()

        assert core.state.get_reg(0) == 0
        assert core.state.get_reg(1) == 0
        assert core.state.get_reg(2) == 0


class TestIPABoundsChecking:
    """
    测试 IPA 边界检查
    """

    def test_ipa_within_bounds(self):
        """
        IPA 在允许范围内，访问成功
        """
        mem = Memory(size=256 * 1024)  # 256KB
        mm = MemoryManager(physical_memory=mem)

        # 创建页表
        pt = mm.create_page_table(base_addr=0x10000, owner_domain=1)
        pt.map(0x1000, 0x3000)  # VA 0x1000 -> IPA 0x3000

        # 创建 IPA 区域表：允许 0x2000-0x5000
        ipa_regions = 0x20000
        mem.write_word(ipa_regions + 0, 0x2000)  # base
        mem.write_word(ipa_regions + 4, 0x3000)  # size
        mem.write_word(ipa_regions + 8, 0x07)    # attr
        # 结束标记
        mem.write_word(ipa_regions + 12, 0)
        mem.write_word(ipa_regions + 16, 0)
        mem.write_word(ipa_regions + 20, 0)

        # 在 PA 0x3000 写入数据
        mem.write_word(0x3000, 0xDEADBEEF)

        rpa = RPALogic()
        core = SimpleISA(rpa=rpa, memory=mem, memory_manager=mm)
        core.page_table_chain = [0x10000]
        core.ipa_regions = ipa_regions

        core.load_assembly("""
            MOV R1, #0x1000
            LDR R0, [R1]
            HALT
        """, base_addr=0x0000)

        core.state.pc = 0x0000
        core.run()

        # IPA 0x3000 在允许范围 0x2000-0x5000 内，访问成功
        assert core.state.get_reg(0) == 0xDEADBEEF

    def test_ipa_out_of_bounds(self):
        """
        IPA 超出允许范围，触发 fault
        """
        mem = Memory(size=256 * 1024)  # 256KB
        mm = MemoryManager(physical_memory=mem)

        # 创建页表
        pt = mm.create_page_table(base_addr=0x10000, owner_domain=1)
        pt.map(0x1000, 0x6000)  # VA 0x1000 -> IPA 0x6000 (超出范围)

        # 创建 IPA 区域表：只允许 0x2000-0x5000
        ipa_regions = 0x20000
        mem.write_word(ipa_regions + 0, 0x2000)  # base
        mem.write_word(ipa_regions + 4, 0x3000)  # size
        mem.write_word(ipa_regions + 8, 0x07)    # attr
        # 结束标记
        mem.write_word(ipa_regions + 12, 0)
        mem.write_word(ipa_regions + 16, 0)
        mem.write_word(ipa_regions + 20, 0)

        # 在 PA 0x6000 写入数据（虽然存在，但 IPA 不允许）
        mem.write_word(0x6000, 0xDEADBEEF)

        rpa = RPALogic()
        core = SimpleISA(rpa=rpa, memory=mem, memory_manager=mm)
        core.page_table_chain = [0x10000]
        core.ipa_regions = ipa_regions

        core.load_assembly("""
            MOV R1, #0x1000
            LDR R0, [R1]
            HALT
        """, base_addr=0x0000)

        fault_info = {}

        def on_fault(fault_type, va, owner):
            fault_info['type'] = fault_type
            fault_info['va'] = va
            fault_info['owner'] = owner
            core.halted = True

        core.fault_handler = on_fault
        core.state.pc = 0x0000
        core.run()

        # IPA 0x6000 超出允许范围，应触发 fault
        assert fault_info['type'] == 'translation'
        assert fault_info['va'] == 0x1000

    def test_ipa_no_regions_table(self):
        """
        没有 IPA 区域表（ipa_regions=0），不进行边界检查
        """
        mem = Memory(size=128 * 1024)
        mm = MemoryManager(physical_memory=mem)

        # 创建页表
        pt = mm.create_page_table(base_addr=0x10000, owner_domain=1)
        pt.map(0x1000, 0x6000)  # VA 0x1000 -> IPA 0x6000

        # 不设置 ipa_regions (ipa_regions=0)

        # 在 PA 0x6000 写入数据
        mem.write_word(0x6000, 0xCAFEBABE)

        rpa = RPALogic()
        core = SimpleISA(rpa=rpa, memory=mem, memory_manager=mm)
        core.page_table_chain = [0x10000]
        core.ipa_regions = 0  # 无边界检查

        core.load_assembly("""
            MOV R1, #0x1000
            LDR R0, [R1]
            HALT
        """, base_addr=0x0000)

        core.state.pc = 0x0000
        core.run()

        # 无边界检查，访问成功
        assert core.state.get_reg(0) == 0xCAFEBABE

    def test_ipa_multiple_regions(self):
        """
        IPA 在多个区域之一内，访问成功
        """
        mem = Memory(size=256 * 1024)  # 256KB
        mm = MemoryManager(physical_memory=mem)

        # 创建页表
        pt = mm.create_page_table(base_addr=0x10000, owner_domain=1)
        pt.map(0x1000, 0x7000)  # VA 0x1000 -> IPA 0x7000

        # 创建 IPA 区域表：两个区域
        ipa_regions = 0x20000
        # 区域 0: 0x2000-0x4000
        mem.write_word(ipa_regions + 0, 0x2000)
        mem.write_word(ipa_regions + 4, 0x2000)
        mem.write_word(ipa_regions + 8, 0x07)
        # 区域 1: 0x6000-0x8000
        mem.write_word(ipa_regions + 12, 0x6000)
        mem.write_word(ipa_regions + 16, 0x2000)
        mem.write_word(ipa_regions + 20, 0x07)
        # 结束标记
        mem.write_word(ipa_regions + 24, 0)
        mem.write_word(ipa_regions + 28, 0)
        mem.write_word(ipa_regions + 32, 0)

        # 在 PA 0x7000 写入数据
        mem.write_word(0x7000, 0x12345678)

        rpa = RPALogic()
        core = SimpleISA(rpa=rpa, memory=mem, memory_manager=mm)
        core.page_table_chain = [0x10000]
        core.ipa_regions = ipa_regions

        core.load_assembly("""
            MOV R1, #0x1000
            LDR R0, [R1]
            HALT
        """, base_addr=0x0000)

        core.state.pc = 0x0000
        core.run()

        # IPA 0x7000 在第二个区域 0x6000-0x8000 内，访问成功
        assert core.state.get_reg(0) == 0x12345678

    def test_inherit_mode_ipa_bounds_check(self):
        """
        INHERIT 模式（pagetable=0）：仍然检查 IPA 边界

        子域使用 INHERIT 模式时，共享父域地址空间，但父域设置的 ipa_regions
        仍然约束子域的可访问范围。
        """
        mem = Memory(size=256 * 1024)
        mm = MemoryManager(physical_memory=mem)

        # 不创建页表 - INHERIT 模式（pagetable = 0）
        # page_table_chain = [0] 表示跳过翻译

        # 创建 IPA 区域表：只允许 0x2000-0x5000
        ipa_regions = 0x20000
        mem.write_word(ipa_regions + 0, 0x2000)  # base
        mem.write_word(ipa_regions + 4, 0x3000)  # size
        mem.write_word(ipa_regions + 8, 0x07)    # attr
        # 结束标记
        mem.write_word(ipa_regions + 12, 0)
        mem.write_word(ipa_regions + 16, 0)
        mem.write_word(ipa_regions + 20, 0)

        # 在 PA 0x3000 写入数据（在允许范围内）
        mem.write_word(0x3000, 0xDEADBEEF)

        # 在 PA 0x6000 写入数据（超出范围）
        mem.write_word(0x6000, 0xCAFEBABE)

        rpa = RPALogic()
        core = SimpleISA(rpa=rpa, memory=mem, memory_manager=mm)
        # INHERIT 模式：page_table_chain = [0]
        core.page_table_chain = [0]
        core.ipa_regions = ipa_regions

        # 测试1：访问允许范围内的地址
        core.load_assembly("""
            MOV R1, #0x3000
            LDR R0, [R1]
            HALT
        """, base_addr=0x0000)

        core.state.pc = 0x0000
        core.run()

        # 访问成功
        assert core.state.get_reg(0) == 0xDEADBEEF

        # 测试2：访问超出范围的地址
        core.load_assembly("""
            MOV R1, #0x6000
            LDR R0, [R1]
            HALT
        """, base_addr=0x1000)

        fault_info = {}

        def on_fault(fault_type, va, owner):
            fault_info['type'] = fault_type
            fault_info['va'] = va
            fault_info['owner'] = owner
            core.halted = True

        core.fault_handler = on_fault
        core.state.pc = 0x1000
        core.halted = False
        core.run()

        # IPA 0x6000 超出允许范围，应触发 fault
        assert fault_info['type'] == 'translation'
        assert fault_info['va'] == 0x6000