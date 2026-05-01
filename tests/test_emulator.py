"""
Tests for Memory and SimpleCore
"""

import pytest
import sys
sys.path.insert(0, '..')

from rpa_sim import (
    Memory, MemoryManager, SimpleCore, Asm
)


class TestMemory:
    """Tests for Memory"""

    def test_create_memory(self):
        """Test creating memory"""
        mem = Memory(size=1024 * 1024)
        assert mem.size == 1024 * 1024

    def test_read_write_byte(self):
        """Test byte read/write"""
        mem = Memory(size=1024 * 1024)
        mem.write_byte(0x1000, 0xAB)
        assert mem.read_byte(0x1000) == 0xAB

    def test_read_write_word(self):
        """Test word (32-bit) read/write"""
        mem = Memory(size=1024 * 1024)
        mem.write_word(0x2000, 0xDEADBEEF)
        assert mem.read_word(0x2000) == 0xDEADBEEF

    def test_read_write_bytes(self):
        """Test multi-byte read/write"""
        mem = Memory(size=1024 * 1024)
        data = bytes([0x01, 0x02, 0x03, 0x04, 0x05])
        mem.write_bytes(0x3000, data)
        assert mem.read_bytes(0x3000, 5) == data

    def test_memory_bounds_check(self):
        """Test memory bounds check"""
        mem = Memory(size=1024)
        with pytest.raises(MemoryError):
            mem.read_byte(0x1000)

    def test_access_log(self):
        """Test access logging"""
        mem = Memory(size=1024)
        mem.clear_access_log()

        mem.write_word(0x100, 0x12345678)
        mem.read_word(0x100)

        assert len(mem.access_log) == 2
        assert mem.access_log[0]["type"] == "write"
        assert mem.access_log[1]["type"] == "read"


class TestSimpleCore:
    """Tests for SimpleCore"""

    def test_assemble_basic(self):
        """Test basic assembly"""
        core = SimpleCore()
        end_addr = core.load_assembly("MOV R0, #42", base_addr=0x1000)

        assert end_addr == 0x1004
        assert 0x1000 in core.instructions
        inst = core.instructions[0x1000]
        assert inst.opcode.name == "MOV"
        assert inst.rd == 0
        assert inst.imm == 42

    def test_assemble_with_labels(self):
        """Test assembly with labels"""
        core = SimpleCore()
        code = """
        start:
            MOV R0, #1
            ADD R0, R0, #1
            B start
        """
        core.load_assembly(code, base_addr=0x1000)

        assert "start" in core.labels
        assert core.labels["start"] == 0x1000

    def test_execute_mov(self):
        """Test MOV execution"""
        mem = Memory(size=64 * 1024)
        core = SimpleCore(memory=mem)

        core.load_assembly("MOV R0, #123", base_addr=0x1000)
        core.state.pc = 0x1000
        core.step()

        assert core.state.get_reg(0) == 123

    def test_execute_add(self):
        """Test ADD execution"""
        mem = Memory(size=64 * 1024)
        core = SimpleCore(memory=mem)

        code = """
            MOV R1, #10
            MOV R2, #20
            ADD R0, R1, R2
            HALT
        """
        core.load_assembly(code, base_addr=0x1000)
        core.state.pc = 0x1000
        core.run()

        assert core.state.get_reg(0) == 30

    def test_execute_loop(self):
        """Test loop execution (1+2+...+10 = 55)"""
        mem = Memory(size=64 * 1024)
        core = SimpleCore(memory=mem)

        code = """
            MOV R0, #0
            MOV R1, #1
        loop:
            ADD R0, R0, R1
            ADD R1, R1, #1
            CMP R1, #11
            BNE loop
            HALT
        """
        core.load_assembly(code, base_addr=0x1000)
        core.state.pc = 0x1000
        core.run()

        assert core.state.get_reg(0) == 55

    def test_execution_log(self):
        """Test execution logging"""
        mem = Memory(size=64 * 1024)
        core = SimpleCore(memory=mem)

        code = """
            MOV R0, #1
            MOV R1, #2
            ADD R0, R0, R1
            HALT
        """
        core.load_assembly(code, base_addr=0x1000)
        core.state.pc = 0x1000
        core.run()

        log = core.get_execution_log()
        assert len(log) == 4
        assert log[0]["opcode"] == "MOV"
        assert log[0]["rd"] == 0
        assert log[2]["opcode"] == "ADD"


class TestDomainExecution:
    """Tests for domain execution with descend/escalate"""

    def test_descend_escalate_simulation(self):
        """Test descend and escalate instruction simulation"""
        mem = Memory(size=1024 * 1024)
        core = SimpleCore(memory=mem)

        # Domain code: calculate and escalate
        code = """
            MOV R0, #42
            MOV R1, #100
            ADD R0, R0, R1
            ESCALATE R0
        """

        escalate_result = {"called": False, "value": 0}

        def escalate_handler(service_type):
            escalate_result["called"] = True
            escalate_result["value"] = service_type
            core.halted = True
            return service_type

        core.escalate_handler = escalate_handler
        core.load_assembly(code, base_addr=0x1000)
        core.state.pc = 0x1000
        core.run()

        assert escalate_result["called"] is True
        assert core.state.get_reg(0) == 142

    def test_memory_isolation_simulation(self):
        """Test memory isolation between domains"""
        mem = Memory(size=1024 * 1024)

        # Domain A code at 0x0000
        core_a = SimpleCore(memory=mem)
        core_a.load_assembly("""
            MOV R0, #100
            MOV R1, #200
            ADD R2, R0, R1
            STR R2, [R3]
            HALT
        """, base_addr=0x0000)
        core_a.state.set_reg(3, 0x0100)

        # Domain B code at 0x8000
        core_b = SimpleCore(memory=mem)
        core_b.load_assembly("""
            MOV R4, #1000
            MOV R5, #2000
            ADD R6, R4, R5
            STR R6, [R7]
            ESCALATE R6
        """, base_addr=0x8000)
        core_b.state.set_reg(7, 0x8100)

        def escalate_handler(params):
            core_b.halted = True
            return params

        core_b.escalate_handler = escalate_handler

        # Run domain A
        core_a.state.pc = 0x0000
        core_a.run()

        # Run domain B
        core_b.state.pc = 0x8000
        core_b.run()

        # Verify isolation
        assert core_a.state.get_reg(2) == 300
        assert core_b.state.get_reg(6) == 3000
        assert mem.read_word(0x0100) == 300
        assert mem.read_word(0x8100) == 3000