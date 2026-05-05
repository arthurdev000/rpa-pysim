"""
Tests for Memory and SimpleISA
"""

import pytest
from rpa_sim import Memory, MemoryManager, SimpleISA, RPALogic, Asm


class TestMemory:
    """Tests for Memory"""

    def test_create_memory(self):
        mem = Memory(size=1024 * 1024)
        assert mem.size == 1024 * 1024

    def test_read_write_byte(self):
        mem = Memory(size=1024 * 1024)
        mem.write_byte(0x1000, 0xAB)
        assert mem.read_byte(0x1000) == 0xAB

    def test_read_write_word(self):
        mem = Memory(size=1024 * 1024)
        mem.write_word(0x2000, 0xDEADBEEF)
        assert mem.read_word(0x2000) == 0xDEADBEEF

    def test_read_write_bytes(self):
        mem = Memory(size=1024 * 1024)
        data = bytes([0x01, 0x02, 0x03, 0x04, 0x05])
        mem.write_bytes(0x3000, data)
        assert mem.read_bytes(0x3000, 5) == data

    def test_memory_bounds_check(self):
        mem = Memory(size=1024)
        with pytest.raises(MemoryError):
            mem.read_byte(0x1000)

    def test_access_log(self):
        mem = Memory(size=1024)
        mem.clear_access_log()

        mem.write_word(0x100, 0x12345678)
        mem.read_word(0x100)

        assert len(mem.access_log) == 2
        assert mem.access_log[0]["type"] == "write"
        assert mem.access_log[1]["type"] == "read"


class TestSimpleISA:
    """Tests for SimpleISA"""

    def test_assemble_basic(self):
        rpa = RPALogic()
        core = SimpleISA(rpa=rpa)
        end_addr = core.load_assembly("MOV R0, #42", base_addr=0x1000)

        assert end_addr == 0x1004
        assert 0x1000 in core.instructions
        inst = core.instructions[0x1000]
        assert inst.opcode.name == "MOV"
        assert inst.rd == 0
        assert inst.imm == 42

    def test_assemble_with_labels(self):
        rpa = RPALogic()
        core = SimpleISA(rpa=rpa)
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
        mem = Memory(size=64 * 1024)
        rpa = RPALogic()
        core = SimpleISA(rpa=rpa, memory=mem)

        core.load_assembly("MOV R0, #123", base_addr=0x1000)
        core.state.pc = 0x1000
        core.step()

        assert core.state.get_reg(0) == 123

    def test_execute_add(self):
        mem = Memory(size=64 * 1024)
        rpa = RPALogic()
        core = SimpleISA(rpa=rpa, memory=mem)

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
        mem = Memory(size=64 * 1024)
        rpa = RPALogic()
        core = SimpleISA(rpa=rpa, memory=mem)

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
        mem = Memory(size=64 * 1024)
        rpa = RPALogic()
        core = SimpleISA(rpa=rpa, memory=mem)

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
        assert log[0]["instruction"] == "MOV R0, #1"
        assert log[2]["instruction"] == "ADD R0, R0, R1"


class TestMemoryTranslation:
    """Tests for memory translation"""

    def test_ldr_str_with_page_table(self):
        """Test LDR/STR with page table translation"""
        mem = Memory(size=64 * 1024)
        mm = MemoryManager(physical_memory=mem)
        rpa = RPALogic()
        core = SimpleISA(rpa=rpa, memory=mem, memory_manager=mm)

        # 创建页表：VA 0x1000 -> PA 0x2000
        pt = mm.create_page_table(base_addr=0x10000, owner_domain=1)
        pt.map(0x1000, 0x2000)

        # 写入数据到物理地址
        mem.write_word(0x2000, 0xDEADBEEF)

        # 设置 memtable_chain
        core.memtable_chain = [0x10000]

        # 测试 LDR
        core.load_assembly("""
            MOV R1, #0x1000
            LDR R0, [R1]
            HALT
        """, base_addr=0x3000)
        core.state.pc = 0x3000
        core.run()

        assert core.state.get_reg(0) == 0xDEADBEEF

    def test_str_with_page_table(self):
        """Test STR with page table translation"""
        mem = Memory(size=64 * 1024)
        mm = MemoryManager(physical_memory=mem)
        rpa = RPALogic()
        core = SimpleISA(rpa=rpa, memory=mem, memory_manager=mm)

        # 创建页表
        pt = mm.create_page_table(base_addr=0x10000, owner_domain=1)
        pt.map(0x1000, 0x2000)

        core.memtable_chain = [0x10000]

        core.load_assembly("""
            MOV R0, #0xCAFEBABE
            MOV R1, #0x1000
            STR R0, [R1]
            HALT
        """, base_addr=0x3000)
        core.state.pc = 0x3000
        core.run()

        # 验证写入到翻译后的地址
        assert mem.read_word(0x2000) == 0xCAFEBABE
        # 原虚拟地址不应有数据
        assert mem.read_word(0x1000) == 0