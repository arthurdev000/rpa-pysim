"""
RPA Core Tests - Basic functionality tests
"""

import pytest
from rpa_sim import RPACore, Domain, DomainBlock, Memory, SimpleISA, MemoryManager


class TestDomainBlock:
    """Tests for DomainBlock"""

    def test_create_block(self):
        block = DomainBlock(
            execution_address=0x1000,
            exception_vector=0x2000,
            memtable_address=0x10000,
        )
        assert block.execution_address == 0x1000
        assert block.exception_vector == 0x2000
        assert block.memtable_address == 0x10000


class TestDomain:
    """Tests for Domain"""

    def test_create_domain(self):
        block = DomainBlock(execution_address=0x8000)
        domain = Domain(domain_id=0, block=block)
        assert domain.domain_id == 0
        assert len(domain.children) == 0

    def test_add_child(self):
        block = DomainBlock(execution_address=0x8000)
        parent = Domain(domain_id=0, block=block)

        child_block = DomainBlock(execution_address=0x1000)
        child = Domain(domain_id=1, block=child_block)

        idx = parent.add_child(child)
        assert idx == 0
        assert len(parent.children) == 1
        assert child.parent == parent


class TestRPACore:
    """Tests for RPACore"""

    def test_create_core(self):
        rpa = RPACore()
        assert rpa.current_domain is rpa.root_domain
        assert rpa.get_depth() == 0

    def test_configure_child(self):
        rpa = RPACore()

        child_block = DomainBlock(
            execution_address=0x1000,
            exception_vector=0x2000,
            memtable_address=0x10000,
        )
        idx = rpa.configure_child(rpa.root_domain, child_block)
        assert idx == 0
        assert len(rpa.root_domain.children) == 1

    def test_descend_needs_memory(self):
        rpa = RPACore()

        child_block = DomainBlock(execution_address=0x1000)
        rpa.configure_child(rpa.root_domain, child_block)

        with pytest.raises(RuntimeError, match="Memory not set"):
            rpa.descend(0x1000)

    def test_escalate_from_root_fails(self):
        rpa = RPACore()

        with pytest.raises(RuntimeError, match="Cannot escalate from root"):
            rpa.escalate(0)

    def test_stats(self):
        rpa = RPACore()
        stats = rpa.get_stats()
        assert stats["descend_count"] == 0
        assert stats["escalate_count"] == 0


class TestSimpleISA:
    """Tests for SimpleISA"""

    def test_execute_mov(self):
        mem = Memory(size=64 * 1024)
        core = SimpleISA(memory=mem)

        core.load_assembly("MOV R0, #123", base_addr=0x1000)
        core.state.pc = 0x1000
        core.step()

        assert core.state.get_reg(0) == 123

    def test_execute_add(self):
        mem = Memory(size=64 * 1024)
        core = SimpleISA(memory=mem)

        core.load_assembly("""
            MOV R1, #10
            MOV R2, #20
            ADD R0, R1, R2
            HALT
        """, base_addr=0x1000)
        core.state.pc = 0x1000
        core.run()

        assert core.state.get_reg(0) == 30

    def test_descend_escalate(self):
        """Test DESCEND and ESCALATE instructions"""
        mem = Memory(size=64 * 1024)

        # 设置控制块 - 地址不能和代码重叠
        block_addr = 0x0800
        child_entry = 0x2000
        mem.write_word(block_addr + 0x00, child_entry)  # execution_address
        mem.write_word(block_addr + 0x04, 0x3000)       # exception_vector
        mem.write_word(block_addr + 0x10, 0)            # memtable_address

        core = SimpleISA(memory=mem)

        # 主程序
        core.load_assembly("""
            MOV R0, #0x0800
            DESCEND R0
            HALT
        """, base_addr=0x1000)

        # 子域代码
        core.load_assembly("""
            MOV R1, #5
            ESCALATE R1
            HALT
        """, base_addr=child_entry)

        escalate_result = [0]

        def on_escalate(service_type):
            escalate_result[0] = service_type
            core.halted = True
            return service_type

        core.escalate_handler = on_escalate
        core.state.pc = 0x1000
        core.run()

        # ESCALATE 被调用，传入 R1 的值
        assert escalate_result[0] == 5

    def test_sysop(self):
        mem = Memory(size=64 * 1024)
        core = SimpleISA(memory=mem)

        sysop_result = [None]

        def on_sysop(op, subop, arg1, arg2, rd, rn):
            sysop_result[0] = (op, subop, arg1, arg2)
            return 123

        core.sysop_handler = on_sysop

        core.load_assembly("""
            SYSOP irq, read, #1, R0
            HALT
        """, base_addr=0x1000)
        core.state.pc = 0x1000
        core.run()

        assert sysop_result[0] == (1, 1, 1, 0)


class TestMemoryTranslation:
    """Tests for memory translation in SimpleISA"""

    def test_ldr_without_translation(self):
        """Test LDR without page table (VA = PA)"""
        mem = Memory(size=64 * 1024)
        mm = MemoryManager(physical_memory=mem)
        core = SimpleISA(memory=mem, memory_manager=mm)

        # 写入测试数据
        mem.write_word(0x1000, 0x12345678)

        core.load_assembly("""
            MOV R1, #0x1000
            LDR R0, [R1]
            HALT
        """, base_addr=0x2000)
        core.state.pc = 0x2000
        core.run()

        assert core.state.get_reg(0) == 0x12345678

    def test_ldr_with_translation(self):
        """Test LDR with page table translation"""
        mem = Memory(size=64 * 1024)
        mm = MemoryManager(physical_memory=mem)
        core = SimpleISA(memory=mem, memory_manager=mm)

        # 创建页表：VA 0x1000 -> PA 0x2000
        pt = mm.create_page_table(base_addr=0x10000, owner_domain=1)
        pt.map(0x1000, 0x2000)

        # 写入数据到物理地址
        mem.write_word(0x2000, 0xDEADBEEF)

        # 设置 memtable_chain
        core.memtable_chain = [0x10000]

        core.load_assembly("""
            MOV R1, #0x1000
            LDR R0, [R1]
            HALT
        """, base_addr=0x3000)
        core.state.pc = 0x3000
        core.run()

        # 读取的是翻译后的地址
        assert core.state.get_reg(0) == 0xDEADBEEF

    def test_str_with_translation(self):
        """Test STR with page table translation"""
        mem = Memory(size=64 * 1024)
        mm = MemoryManager(physical_memory=mem)
        core = SimpleISA(memory=mem, memory_manager=mm)

        # 创建页表：VA 0x1000 -> PA 0x2000
        pt = mm.create_page_table(base_addr=0x10000, owner_domain=1)
        pt.map(0x1000, 0x2000)

        # 设置 memtable_chain
        core.memtable_chain = [0x10000]

        core.load_assembly("""
            MOV R0, #0xDEADBEEF
            MOV R1, #0x1000
            STR R0, [R1]
            HALT
        """, base_addr=0x3000)
        core.state.pc = 0x3000
        core.run()

        # 验证写入到翻译后的地址
        assert mem.read_word(0x2000) == 0xDEADBEEF
        # 原虚拟地址不应有数据
        assert mem.read_word(0x1000) == 0


class TestIntegration:
    """Integration tests"""

    def test_memory_and_core(self):
        mem = Memory(size=1024 * 1024)
        core = SimpleISA(memory=mem)

        code = """
            MOV R0, #1
            MOV R1, #2
            ADD R2, R0, R1
            STR R2, [R3]
            HALT
        """
        core.load_assembly(code, base_addr=0x1000)
        core.state.set_reg(3, 0x0100)
        core.state.pc = 0x1000
        core.run()

        assert core.state.get_reg(2) == 3
        assert mem.read_word(0x0100) == 3

    def test_domain_block_in_memory(self):
        mem = Memory(size=1024 * 1024)
        rpa = RPACore()
        rpa.memory = mem

        block = DomainBlock(
            execution_address=0x4000,
            exception_vector=0x4004,
            memtable_address=0x50000,
        )

        rpa._write_domain_block(0x1000, block)
        read_block = rpa._read_domain_block(0x1000)

        assert read_block.execution_address == 0x4000
        assert read_block.exception_vector == 0x4004
        assert read_block.memtable_address == 0x50000