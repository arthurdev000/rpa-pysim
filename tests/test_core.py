"""
RPA Core Tests - Basic functionality tests for the refactored API
"""

import pytest
from rpa_sim import RPACore, Domain, DomainBlock, Memory, SimpleCore, INHERIT


class TestDomainBlock:
    """Tests for DomainBlock"""

    def test_create_block(self):
        """Test creating a domain block"""
        block = DomainBlock(
            entry_addr=0x1000,
            exception_vector=0x2000,
            memtable_addr=0x10000,
        )
        assert block.entry_addr == 0x1000
        assert block.exception_vector == 0x2000
        assert block.memtable_addr == 0x10000


class TestDomain:
    """Tests for Domain"""

    def test_create_domain(self):
        """Test creating a domain"""
        block = DomainBlock(entry_addr=0x8000)
        domain = Domain(domain_id=0, block=block)
        assert domain.domain_id == 0
        assert len(domain.children) == 0

    def test_add_child(self):
        """Test adding child domains"""
        block = DomainBlock(entry_addr=0x8000)
        parent = Domain(domain_id=0, block=block)

        child_block = DomainBlock(entry_addr=0x1000)
        child = Domain(domain_id=1, block=child_block)

        idx = parent.add_child(child)
        assert idx == 0
        assert len(parent.children) == 1
        assert child.parent == parent


class TestRPACore:
    """Tests for RPACore"""

    def test_create_core(self):
        """Test creating RPA core"""
        rpa = RPACore()
        assert rpa.current_domain is rpa.root_domain
        assert rpa.get_depth() == 0

    def test_configure_child(self):
        """Test configuring a child domain"""
        rpa = RPACore()

        child_block = DomainBlock(
            entry_addr=0x1000,
            exception_vector=0x2000,
            memtable_addr=0x10000,
        )
        idx = rpa.configure_child(rpa.root_domain, child_block)
        assert idx == 0
        assert len(rpa.root_domain.children) == 1

    def test_descend_needs_memory(self):
        """Test descend requires memory"""
        rpa = RPACore()

        child_block = DomainBlock(entry_addr=0x1000)
        rpa.configure_child(rpa.root_domain, child_block)

        # descend requires memory to read DomainBlock
        with pytest.raises(RuntimeError, match="Memory not set"):
            rpa.descend(0x1000)

    def test_escalate_from_root_fails(self):
        """Test that escalating from root fails"""
        rpa = RPACore()

        with pytest.raises(RuntimeError, match="Cannot escalate from root"):
            rpa.escalate(0)

    def test_stats(self):
        """Test statistics tracking"""
        rpa = RPACore()
        stats = rpa.get_stats()
        assert stats["descend_count"] == 0
        assert stats["escalate_count"] == 0


class TestSimpleCore:
    """Tests for SimpleCore"""

    def test_execute_mov(self):
        """Test MOV instruction"""
        mem = Memory(size=64 * 1024)
        core = SimpleCore(memory=mem)

        core.load_assembly("MOV R0, #123", base_addr=0x1000)
        core.state.pc = 0x1000
        core.step()

        assert core.state.get_reg(0) == 123

    def test_execute_add(self):
        """Test ADD instruction"""
        mem = Memory(size=64 * 1024)
        core = SimpleCore(memory=mem)

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
        core = SimpleCore(memory=mem)

        # Set up handlers
        descend_result = [0]
        escalate_result = [0]

        def on_descend(block_addr):
            descend_result[0] = block_addr
            return 42

        def on_escalate(service_type):
            escalate_result[0] = service_type
            return 100

        core.descend_handler = on_descend
        core.escalate_handler = on_escalate

        core.load_assembly("""
            MOV R0, #0x1000
            DESCEND R0
            MOV R1, #5
            ESCALATE R1
            HALT
        """, base_addr=0x1000)
        core.state.pc = 0x1000
        core.run()

        assert descend_result[0] == 0x1000
        assert escalate_result[0] == 5

    def test_sysop(self):
        """Test SYSOP instruction"""
        mem = Memory(size=64 * 1024)
        core = SimpleCore(memory=mem)

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

        # op=1 (IRQ), subop=1 (READ), arg1=1, arg2=0
        assert sysop_result[0] == (1, 1, 1, 0)


class TestIntegration:
    """Integration tests"""

    def test_memory_and_core(self):
        """Test memory and core integration"""
        mem = Memory(size=1024 * 1024)
        core = SimpleCore(memory=mem)

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
        """Test writing and reading DomainBlock from memory"""
        mem = Memory(size=1024 * 1024)
        rpa = RPACore()
        rpa.memory = mem

        block = DomainBlock(
            entry_addr=0x4000,
            exception_vector=0x4004,
            memtable_addr=0x50000,
        )

        # Write to memory
        rpa._write_domain_block(0x1000, block)

        # Read back
        read_block = rpa._read_domain_block(0x1000)

        assert read_block.entry_addr == 0x4000
        assert read_block.exception_vector == 0x4004
        assert read_block.memtable_addr == 0x50000