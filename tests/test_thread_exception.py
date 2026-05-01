"""
Thread and Exception Tests for RPA

使用汇编指令测试 DESCEND/ESCALATE/RETURN 机制。
所有测试使用单一 Core，让指令真正执行域切换。
"""

import pytest
from rpa_sim import (
    Memory, SimpleCore, MemoryManager, DomainBlock
)


class TestDescendEscalate:
    """
    测试 DESCEND 和 ESCALATE 指令
    """

    def test_descend_jumps_to_execution_address(self):
        """
        DESCEND 跳转到 execution_address
        """
        mem = Memory(size=64 * 1024)

        # 设置控制块
        block_addr = 0x1000
        execution_addr = 0x2000
        mem.write_word(block_addr + 0x00, execution_addr)  # execution_address
        mem.write_word(block_addr + 0x04, 0x3000)          # exception_vector
        mem.write_word(block_addr + 0x10, 0)               # memtable_address

        # 主程序
        main_code = """
            MOV R0, #0x1000    ; 控制块地址
            DESCEND R0
            ; DESCEND 后应该跳转到子域，不会执行到这里
            MOV R5, #0xBAD
            HALT
        """

        # 子域代码
        child_code = """
            MOV R1, #42
            ESCALATE R1
            HALT
        """

        core = SimpleCore(memory=mem)
        core.load_assembly(main_code, base_addr=0x0000)
        core.load_assembly(child_code, base_addr=execution_addr)

        core.state.pc = 0x0000
        core.domain_block_addr = 0  # 初始无控制块

        # ESCALATE 时停止
        core.escalate_handler = lambda x: (setattr(core, 'halted', True), x)[1]

        core.run()

        # 验证：跳转到了子域代码
        assert core.state.get_reg(1) == 42
        # R5 不应该被设置（没有执行 MOV R5, #0xBAD）
        assert core.state.get_reg(5) == 0

    def test_descend_updates_memtable_chain(self):
        """
        DESCEND 更新 memtable_chain
        """
        mem = Memory(size=64 * 1024)

        block_addr = 0x0800
        mem.write_word(block_addr + 0x00, 0x2000)    # execution_address
        mem.write_word(block_addr + 0x04, 0)
        mem.write_word(block_addr + 0x10, 0x10000)   # memtable_address

        core = SimpleCore(memory=mem)
        core.memtable_chain = []

        core.load_assembly("""
            MOV R0, #0x0800
            DESCEND R0
            HALT
        """, base_addr=0x0000)

        core.load_assembly("""
            ESCALATE R0
            HALT
        """, base_addr=0x2000)

        core.state.pc = 0x0000
        core.escalate_handler = lambda x: (setattr(core, 'halted', True), x)[1]
        core.run()

        # 验证：memtable_chain 被更新
        assert core.memtable_chain == [0x10000]

    def test_escalate_jumps_to_exception_vector(self):
        """
        ESCALATE 跳转到 exception_vector
        """
        mem = Memory(size=64 * 1024)

        block_addr = 0x1000
        execution_addr = 0x2000
        exception_vec = 0x3000
        mem.write_word(block_addr + 0x00, execution_addr)
        mem.write_word(block_addr + 0x04, exception_vec)
        mem.write_word(block_addr + 0x10, 0)

        core = SimpleCore(memory=mem)
        core.load_assembly("""
            MOV R0, #0x1000
            DESCEND R0
            HALT
        """, base_addr=0x0000)

        core.load_assembly("""
            MOV R1, #42
            ESCALATE R1
            HALT
        """, base_addr=execution_addr)

        # 异常处理代码 - 执行后 halt
        core.load_assembly("""
            MOV R2, #0xCAFE
            HALT
        """, base_addr=exception_vec)

        core.state.pc = 0x0000
        core.run()

        # 验证：跳转到了 exception_vector 并执行了异常处理代码
        assert core.state.get_reg(2) == 0xCAFE

    def test_shared_memory_between_domains(self):
        """
        父子域共享内存（memtable_address = 0）
        """
        mem = Memory(size=64 * 1024)

        # 共享数据
        shared_addr = 0x5000
        mem.write_word(shared_addr, 100)

        block_addr = 0x1000
        mem.write_word(block_addr + 0x00, 0x2000)   # execution_address
        mem.write_word(block_addr + 0x04, 0)        # exception_vector
        mem.write_word(block_addr + 0x10, 0)        # memtable_address = 0 (共享)

        core = SimpleCore(memory=mem)

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

        core.state.pc = 0x0000
        core.escalate_handler = lambda x: (setattr(core, 'halted', True), x)[1]
        core.run()

        # 共享数据被修改
        assert mem.read_word(shared_addr) == 300


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

        core = SimpleCore(memory=mem, memory_manager=mm)
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

        core = SimpleCore(memory=mem, memory_manager=mm)
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

    def test_descend_updates_memtable_chain(self):
        """
        DESCEND 更新 memtable_chain
        """
        mem = Memory(size=64 * 1024)
        mm = MemoryManager(physical_memory=mem)

        # Domain 0 页表（根页表）
        # 需要映射所有最终的物理地址
        pt0 = mm.create_page_table(base_addr=0x10000, owner_domain=0)
        pt0.map(0x0000, 0x0000)  # 代码段
        pt0.map(0x3000, 0x3000)  # 数据段（IPA -> PA）

        # Domain 1 页表
        # VA 0x1000 -> IPA 0x3000
        pt1 = mm.create_page_table(base_addr=0x20000, owner_domain=1)
        pt1.map(0x1000, 0x3000)

        # 设置控制块
        block_addr = 0x0800
        mem.write_word(block_addr + 0x00, 0x2000)    # execution_address
        mem.write_word(block_addr + 0x04, 0)
        mem.write_word(block_addr + 0x10, 0x20000)   # memtable_address

        core = SimpleCore(memory=mem, memory_manager=mm)
        core.memtable_chain = [0x10000]  # Domain 0 的页表

        # 主程序
        core.load_assembly("""
            MOV R0, #0x0800
            DESCEND R0
            HALT
        """, base_addr=0x0000)

        # 子域代码：使用翻译地址
        core.load_assembly("""
            MOV R1, #0x1000
            LDR R0, [R1]
            ESCALATE R0
            HALT
        """, base_addr=0x2000)

        # 在 PA 0x3000 写入数据
        mem.write_word(0x3000, 0x12345678)

        core.state.pc = 0x0000
        core.escalate_handler = lambda x: (setattr(core, 'halted', True), x)[1]
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

        core = SimpleCore(memory=mem, memory_manager=mm)
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

        core = SimpleCore(memory=mem)

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

        core = SimpleCore(memory=mem, memory_manager=mm)
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

        场景：
        - Domain 1 页表映射了 VA -> IPA
        - Domain 0 页表没有映射 IPA -> PA
        - 翻译失败应该归属到 Domain 0
        """
        mem = Memory(size=64 * 1024)
        mm = MemoryManager(physical_memory=mem)

        # Domain 0 页表（根页表）- 不映射
        pt0 = mm.create_page_table(base_addr=0x10000, owner_domain=0)

        # Domain 1 页表 - 映射到 IPA
        pt1 = mm.create_page_table(base_addr=0x20000, owner_domain=1)
        pt1.map(0x1000, 0x2000)  # VA -> IPA, 但 IPA 没有 -> PA

        core = SimpleCore(memory=mem, memory_manager=mm)
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


class TestSharedMemoryThread:
    """
    测试共享内存的线程模型
    """

    def test_two_threads_sequential(self):
        """
        两个"线程"顺序执行，共享内存

        这是用两个 SimpleCore 模拟共享 memtable_chain = [] 的场景
        """
        mem = Memory(size=64 * 1024)

        shared_addr = 0x5000
        mem.write_word(shared_addr, 100)

        # 线程1代码
        thread1 = SimpleCore(memory=mem)
        thread1.load_assembly("""
            MOV R1, #0x5000
            LDR R0, [R1]
            ADD R0, R0, #200
            STR R0, [R1]
            ESCALATE R0
            HALT
        """, base_addr=0x1000)

        thread1.state.pc = 0x1000
        thread1.escalate_handler = lambda x: (setattr(thread1, 'halted', True), x)[1]
        thread1.run()

        assert mem.read_word(shared_addr) == 300

        # 线程2代码
        thread2 = SimpleCore(memory=mem)
        thread2.load_assembly("""
            MOV R1, #0x5000
            LDR R0, [R1]
            ADD R0, R0, #300
            STR R0, [R1]
            ESCALATE R0
            HALT
        """, base_addr=0x2000)

        thread2.state.pc = 0x2000
        thread2.escalate_handler = lambda x: (setattr(thread2, 'halted', True), x)[1]
        thread2.run()

        assert mem.read_word(shared_addr) == 600