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

        # 设置 pagetable_chain
        core.pagetable_chain = [0x10000]

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

        core.pagetable_chain = [0x10000]

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


class TestInterruptReturn:
    """Tests for interrupt handling and bx lr return"""

    def test_irq_return_flag_in_lr(self):
        """Test that IRQ sets LR with IRQ_RETURN_FLAG"""
        from rpa_sim import InterruptController
        from rpa_sim.isa_simple import IRQ_RETURN_FLAG

        mem = Memory(size=64 * 1024)
        rpa = RPALogic()
        rpa.memory = mem
        irq_ctrl = InterruptController()
        core = SimpleISA(rpa=rpa, memory=mem, interrupt_controller=irq_ctrl)

        # 设置根域控制块
        root_block_addr = 0x1000
        mem.write_word(root_block_addr + 0x00, 32)  # ctrlblock_size
        mem.write_word(root_block_addr + 0x08, 0x8000)  # trap_vector at 0x08
        rpa.root_domain.block_addr = root_block_addr
        core.domain_block_addr = root_block_addr  # 设置当前域控制块地址

        # 申请中断实例
        handle = irq_ctrl.request(owner_domain_id=0, permissions=0x07)
        irq_ctrl.set_vector(handle, 0x5000)  # 中断向量
        irq_ctrl.enable(handle)

        # 主程序：R0 = 1, 2, 3... 然后停止
        core.load_assembly("""
            MOV R0, #1
            MOV R0, #2
            MOV R0, #3
            HALT
        """, base_addr=0x2000)
        core.state.pc = 0x2000

        # 中断处理程序：R1 = 0xFF，然后 bx lr 返回
        core.load_assembly("""
            MOV R1, #0xFF
            BX LR
        """, base_addr=0x5000)

        # 触发中断
        irq_ctrl.trigger_irq(handle, 0)

        # 执行一步后应该进入中断
        core.step()  # MOV R0, #1
        assert core.state.in_interrupt == True, "Should be in interrupt after first instruction"
        assert core.state.lr & IRQ_RETURN_FLAG, "LR should have IRQ_RETURN_FLAG set"
        assert core.state.pc == 0x5000, "PC should jump to interrupt vector"

    def test_bx_lr_returns_from_interrupt(self):
        """Test that bx lr correctly returns from interrupt"""
        from rpa_sim import InterruptController
        from rpa_sim.isa_simple import IRQ_RETURN_FLAG

        mem = Memory(size=64 * 1024)
        rpa = RPALogic()
        rpa.memory = mem
        irq_ctrl = InterruptController()
        core = SimpleISA(rpa=rpa, memory=mem, interrupt_controller=irq_ctrl)

        # 设置根域控制块
        root_block_addr = 0x1000
        mem.write_word(root_block_addr + 0x00, 32)  # ctrlblock_size
        rpa.root_domain.block_addr = root_block_addr
        core.domain_block_addr = root_block_addr  # 设置当前域控制块地址

        # 申请中断实例
        handle = irq_ctrl.request(owner_domain_id=0, permissions=0x07)
        irq_ctrl.set_vector(handle, 0x5000)  # 中断向量
        irq_ctrl.enable(handle)

        # 主程序
        core.load_assembly("""
            MOV R0, #1      ; 0x2000 - 被中断点
            MOV R0, #2      ; 0x2004 - 应该在这里继续
            MOV R0, #3      ; 0x2008
            HALT            ; 0x200C
        """, base_addr=0x2000)

        # 中断处理程序
        core.load_assembly("""
            MOV R1, #0xFF   ; 0x5000 - 设置 R1
            BX LR           ; 0x5004 - 返回
        """, base_addr=0x5000)

        core.state.pc = 0x2000

        # 触发中断
        irq_ctrl.trigger_irq(handle, 0)

        # 执行：MOV R0, #1 -> 触发中断 -> MOV R1, #0xFF -> BX LR
        core.step()  # MOV R0, #1 + 进入中断
        assert core.state.in_interrupt == True

        core.step()  # MOV R1, #0xFF (in ISR)
        assert core.state.get_reg(1) == 0xFF

        core.step()  # BX LR -> 返回
        assert core.state.in_interrupt == False, "Should exit interrupt after bx lr"
        assert core.state.irq_disabled == False, "IRQ should be re-enabled"
        assert core.state.pc == 0x2004, "Should return to instruction after interrupted PC"

        # 继续执行
        core.step()  # MOV R0, #2
        assert core.state.get_reg(0) == 2

    def test_interrupt_preserves_context(self):
        """Test that interrupt preserves all registers"""
        from rpa_sim import InterruptController
        from rpa_sim.isa_simple import IRQ_SAVE_R0, IRQ_SAVE_PC, IRQ_SAVE_PSR

        mem = Memory(size=64 * 1024)
        rpa = RPALogic()
        rpa.memory = mem
        irq_ctrl = InterruptController()
        core = SimpleISA(rpa=rpa, memory=mem, interrupt_controller=irq_ctrl)

        # 设置根域控制块
        root_block_addr = 0x1000
        mem.write_word(root_block_addr + 0x00, 32)  # ctrlblock_size
        rpa.root_domain.block_addr = root_block_addr
        core.domain_block_addr = root_block_addr  # 设置当前域控制块地址
        core.domain_block_addr = root_block_addr

        # 申请中断实例
        handle = irq_ctrl.request(owner_domain_id=0, permissions=0x07)
        irq_ctrl.set_vector(handle, 0x5000)
        irq_ctrl.enable(handle)

        # 主程序：设置多个寄存器
        core.load_assembly("""
            MOV R0, #1
            MOV R1, #2
            MOV R2, #3
            MOV R3, #4      ; 被中断点
            ADD R0, R0, #1  ; 返回后继续
            HALT
        """, base_addr=0x2000)

        # 中断处理程序：修改寄存器
        core.load_assembly("""
            MOV R0, #0xFF
            MOV R1, #0xFF
            MOV R2, #0xFF
            MOV R3, #0xFF
            BX LR
        """, base_addr=0x5000)

        core.state.pc = 0x2000

        # 执行前几条指令
        core.step()  # MOV R0, #1
        core.step()  # MOV R1, #2
        core.step()  # MOV R2, #3

        # 触发中断
        irq_ctrl.trigger_irq(handle, 0)

        core.step()  # MOV R3, #4 + 进入中断
        # 保存的 PC 应该是 0x2010 (MOV R3 后的下一条指令地址)
        saved_pc = mem.read_word(root_block_addr + IRQ_SAVE_PC)
        # 注意：被中断的是 MOV R3, #4 执行后的 PC，所以是 0x2010

        # ISR 修改寄存器
        core.step()  # MOV R0, #0xFF
        core.step()  # MOV R1, #0xFF
        core.step()  # MOV R2, #0xFF
        core.step()  # MOV R3, #0xFF
        assert core.state.get_reg(0) == 0xFF

        # BX LR 返回
        core.step()  # BX LR
        assert core.state.in_interrupt == False

        # 寄存器应该恢复
        assert core.state.get_reg(0) == 1, "R0 should be restored"
        assert core.state.get_reg(1) == 2, "R1 should be restored"
        assert core.state.get_reg(2) == 3, "R2 should be restored"
        assert core.state.get_reg(3) == 4, "R3 should be restored"