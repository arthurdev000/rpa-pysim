"""
RPA Core Tests - Basic functionality tests
"""

import pytest
from rpa_sim import RPALogic, Domain, DomainBlock, Memory, SimpleISA, MemoryManager, DomainBlockError


class TestDomainBlock:
    """Tests for DomainBlock"""

    def test_create_block(self):
        block = DomainBlock(
            exception_vector=0x2000,
            memtable_address=0x10000,
        )
        assert block.exception_vector == 0x2000
        assert block.memtable_address == 0x10000


class TestDomain:
    """Tests for Domain"""

    def test_create_domain(self):
        block = DomainBlock()
        domain = Domain(domain_id=0, block=block)
        assert domain.domain_id == 0
        assert domain.parent is None

    def test_domain_with_parent(self):
        parent_block = DomainBlock()
        parent = Domain(domain_id=0, block=parent_block)

        child_block = DomainBlock()
        child = Domain(domain_id=1, block=child_block, parent=parent)

        assert child.parent == parent
        assert child.domain_id == 1


class TestRPALogic:
    """Tests for RPALogic"""

    def test_create_core(self):
        rpa = RPALogic()
        assert rpa.current_domain is rpa.root_domain
        assert rpa.get_depth() == 0

    def test_descend_needs_memory(self):
        rpa = RPALogic()

        with pytest.raises(RuntimeError, match="Memory not set"):
            rpa.descend(0x1000)

    def test_escalate_from_root_fails(self):
        rpa = RPALogic()

        with pytest.raises(RuntimeError, match="Cannot escalate from root"):
            rpa.escalate(0)

    def test_stats(self):
        rpa = RPALogic()
        stats = rpa.get_stats()
        assert stats["descend_count"] == 0
        assert stats["escalate_count"] == 0

    def test_descend_conflict_child_block(self):
        """
        父域已有子域时，尝试 DESCEND 到不同的子域应报错
        """
        mem = Memory(size=64 * 1024)
        rpa = RPALogic()
        rpa.memory = mem

        # 第一个子域控制块
        child1_addr = 0x1000
        mem.write_word(child1_addr + 0x00, 32)  # ctrlblock_size
        mem.write_word(child1_addr + 0x10, 0)   # memtable_address
        mem.write_word(child1_addr + 0x24, 0x2000)  # saved_lr

        # 第二个子域控制块
        child2_addr = 0x2000
        mem.write_word(child2_addr + 0x00, 32)  # ctrlblock_size
        mem.write_word(child2_addr + 0x10, 0)   # memtable_address
        mem.write_word(child2_addr + 0x24, 0x3000)  # saved_lr

        # 首次 DESCEND 到 child1
        rpa.descend(child1_addr)
        assert rpa.current_domain.block_addr == child1_addr

        # ESCALATE 回到根域
        rpa.escalate(0)
        assert rpa.current_domain == rpa.root_domain

        # 尝试 DESCEND 到 child2（应该报错，因为 child1 还存在）
        from rpa_sim import DomainBlockError
        with pytest.raises(DomainBlockError, match="already has child"):
            rpa.descend(child2_addr)


class TestSimpleISA:
    """Tests for SimpleISA"""

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

        # 设置控制块 - 新布局
        # 0x00: ctrlblock_size
        # 0x04: exception_vector
        # 0x08: interrupt_vector
        # 0x0C: interrupt_ctrl
        # 0x10: memtable_address
        # 0x14: domain_id
        # 0x18: parent_block
        # 0x1C: child_block
        # ISA 扩展:
        # 0x20: saved_sp
        # 0x24: saved_lr (首次 DESCEND 入口地址由父域写入)
        # 0x28: saved_psr
        block_addr = 0x0800
        child_entry = 0x2000
        mem.write_word(block_addr + 0x00, 32)               # ctrlblock_size = 32
        mem.write_word(block_addr + 0x04, 0)                # exception_vector (子域自己用的)
        mem.write_word(block_addr + 0x10, 0)                # memtable_address
        mem.write_word(block_addr + 0x24, child_entry)      # saved_lr = 入口地址 (父域设置)

        rpa = RPALogic()
        rpa.memory = mem
        # 设置父域（根域）的 exception_vector
        rpa.root_domain.block.exception_vector = 0x3000

        core = SimpleISA(rpa=rpa, memory=mem)

        # 主程序
        core.load_assembly("""
            MOV R0, #0x0800
            DESCEND R0
            ; 子域返回后继续
            MOV R2, #42
            HALT
        """, base_addr=0x1000)

        # 子域代码
        core.load_assembly("""
            MOV R1, #5
            ESCALATE R1
            HALT
        """, base_addr=child_entry)

        # 父域异常处理程序
        core.load_assembly("""
            ; 父域收到 ESCALATE
            MOV R3, #99
            HALT
        """, base_addr=0x3000)

        core.state.pc = 0x1000
        core.run()

        # 验证：ESCALATE 跳转到父域的 exception_vector，执行了 MOV R3, #99
        assert core.state.get_reg(3) == 99  # 异常处理程序执行了
        # 子域执行了 MOV R1, #5（但寄存器状态在域切换时保存了）
        # R1 的值在子域上下文中，当前是父域的寄存器状态

    def test_sysop(self):
        mem = Memory(size=64 * 1024)
        rpa = RPALogic()
        core = SimpleISA(rpa=rpa, memory=mem)

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
        rpa = RPALogic()
        core = SimpleISA(rpa=rpa, memory=mem, memory_manager=mm)

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
        rpa = RPALogic()
        core = SimpleISA(rpa=rpa, memory=mem, memory_manager=mm)

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
        rpa = RPALogic()
        core = SimpleISA(rpa=rpa, memory=mem, memory_manager=mm)

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
        rpa = RPALogic()
        core = SimpleISA(rpa=rpa, memory=mem)

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
        rpa = RPALogic()
        rpa.memory = mem

        block = DomainBlock(
            exception_vector=0x4004,
            memtable_address=0x50000,
        )

        rpa._write_domain_block(0x1000, block)
        read_block = rpa._read_domain_block(0x1000)

        assert read_block.exception_vector == 0x4004
        assert read_block.memtable_address == 0x50000

    def test_descend_escalate_return_cycle(self):
        """Test complete DESCEND -> ESCALATE -> RETURN cycle"""
        mem = Memory(size=64 * 1024)
        rpa = RPALogic()
        rpa.memory = mem

        # 设置子域控制块
        block_addr = 0x0800
        child_entry = 0x2000
        parent_exception_handler = 0x3000
        child_return_point = 0x2008  # After ESCALATE instruction

        mem.write_word(block_addr + 0x00, 32)                    # ctrlblock_size
        mem.write_word(block_addr + 0x04, 0)                     # exception_vector (子域自己的)
        mem.write_word(block_addr + 0x10, 0)                     # memtable_address
        mem.write_word(block_addr + 0x24, child_entry)           # saved_lr = 入口地址 (父域设置)

        # 设置父域的 exception_vector
        rpa.root_domain.block.exception_vector = parent_exception_handler

        core = SimpleISA(rpa=rpa, memory=mem)

        # 父域代码
        core.load_assembly("""
            MOV R0, #0x0800
            DESCEND R0
            ; 子域返回后继续
            MOV R5, #100
            HALT
        """, base_addr=0x1000)

        # 子域代码
        core.load_assembly("""
            MOV R1, #5
            MOV R0, #1
            ESCALATE R0
            ; RETURN 后从这里继续
            MOV R2, #42
            HALT
        """, base_addr=child_entry)

        # 父域异常处理程序（处理子域 ESCALATE，然后 RETURN）
        core.load_assembly("""
            ; 父域收到 ESCALATE
            MOV R3, #99
            MOV R0, #0x0800
            RETURN R0
            ; RETURN 后不会到这里
            HALT
        """, base_addr=parent_exception_handler)

        core.state.pc = 0x1000
        core.run()

        # 验证：
        # R3 = 99: 父域处理程序执行了
        # R1 = 5: 子域执行了 MOV R1, #5
        # R2 = 42: RETURN 后子域继续执行了 MOV R2, #42
        assert core.state.get_reg(3) == 99
        assert core.state.get_reg(2) == 42

        # 验证域切换正确
        assert rpa.get_depth() == 1  # 回到子域


class TestExitInstruction:
    """Tests for EXIT instruction"""

    def test_exit_releases_child_domain(self):
        """
        EXIT 指令释放子域，清空父子关系
        """
        mem = Memory(size=64 * 1024)
        rpa = RPALogic()
        rpa.memory = mem

        # 子域控制块
        block_addr = 0x0800
        child_entry = 0x2000
        mem.write_word(block_addr + 0x00, 32)               # ctrlblock_size
        mem.write_word(block_addr + 0x04, 0)                # exception_vector
        mem.write_word(block_addr + 0x10, 0)                # memtable_address
        mem.write_word(block_addr + 0x24, child_entry)      # saved_lr

        core = SimpleISA(rpa=rpa, memory=mem)
        rpa.root_domain.block.exception_vector = 0x3000

        # 父域代码
        core.load_assembly("""
            MOV R0, #0x0800
            DESCEND R0
            ; EXIT 后回到这里，子域已释放
            MOV R5, #100
            HALT
        """, base_addr=0x1000)

        # 子域代码 - 使用 EXIT 退出
        core.load_assembly("""
            MOV R1, #42
            MOV R0, #0
            EXIT R0
            ; EXIT 后不会执行到这里
            MOV R2, #999
            HALT
        """, base_addr=child_entry)

        # 父域异常处理程序
        core.load_assembly("""
            HALT
        """, base_addr=0x3000)

        core.state.pc = 0x1000
        core.run()

        # 验证子域执行了
        assert core.state.get_reg(1) == 42
        # 验证父域回到了根域
        assert rpa.get_depth() == 0
        # 验证父域的 child_block 被清空
        assert rpa.root_domain.block.child_block == 0
        # 验证子域的 parent_block 被清空
        assert mem.read_word(block_addr + 0x18) == 0  # parent_block
        # 验证子域的 domain_id 被清空
        assert mem.read_word(block_addr + 0x14) == 0  # domain_id

    def test_exit_allows_reuse_of_child_block(self):
        """
        EXIT 后可以重新 DESCEND 到同一个控制块
        """
        mem = Memory(size=64 * 1024)
        rpa = RPALogic()
        rpa.memory = mem

        # 子域控制块
        block_addr = 0x0800
        child_entry = 0x2000
        mem.write_word(block_addr + 0x00, 32)               # ctrlblock_size
        mem.write_word(block_addr + 0x04, 0)                # exception_vector
        mem.write_word(block_addr + 0x10, 0)                # memtable_address

        core = SimpleISA(rpa=rpa, memory=mem)
        rpa.root_domain.block.exception_vector = 0x3000

        # 父域代码
        core.load_assembly("""
            MOV R0, #0x0800
            MOV R1, #0x2000
            STR R1, [R0, #0x24]  ; saved_lr = 入口地址
            DESCEND R0
            HALT
        """, base_addr=0x1000)

        # 子域代码 - 使用 EXIT 退出
        core.load_assembly("""
            MOV R4, #99
            MOV R0, #0
            EXIT R0
            HALT
        """, base_addr=child_entry)

        # 父域异常处理程序
        core.load_assembly("HALT", base_addr=0x3000)

        core.state.pc = 0x1000
        core.run()

        # 验证子域执行了
        assert core.state.get_reg(4) == 99
        # 验证回到根域
        assert rpa.get_depth() == 0
        # 验证父域的 child_block 被清空
        assert rpa.root_domain.block.child_block == 0

        # 现在可以重新 DESCEND 到同一个控制块
        # 重置入口地址
        mem.write_word(block_addr + 0x24, child_entry)

        result = rpa.descend(block_addr)
        assert result["is_first"] == True  # 应该是首次 DESCEND（因为之前 EXIT 释放了）
        assert rpa.root_domain.block.child_block == block_addr

    def test_exit_vs_escalate_difference(self):
        """
        EXIT 与 ESCALATE 的区别：
        - ESCALATE 后父域可以 RETURN 回子域
        - EXIT 后子域被释放，父域无法 RETURN
        """
        mem = Memory(size=64 * 1024)

        # === ESCALATE 场景 ===
        block_addr1 = 0x0800
        child_entry1 = 0x2000
        mem.write_word(block_addr1 + 0x00, 32)
        mem.write_word(block_addr1 + 0x04, 0)
        mem.write_word(block_addr1 + 0x10, 0)
        mem.write_word(block_addr1 + 0x24, child_entry1)

        rpa1 = RPALogic()
        rpa1.memory = mem
        core1 = SimpleISA(rpa=rpa1, memory=mem)
        rpa1.root_domain.block.exception_vector = 0x3000

        core1.load_assembly("""
            MOV R0, #0x0800
            DESCEND R0
            ; ESCALATE+RETURN 后继续
            MOV R1, #111
            HALT
        """, base_addr=0x1000)

        core1.load_assembly("""
            MOV R0, #1
            ESCALATE R0
            ; RETURN 后继续
            MOV R2, #222
            HALT
        """, base_addr=child_entry1)

        core1.load_assembly("""
            ; 父域处理
            MOV R0, #0x0800
            RETURN R0
            HALT
        """, base_addr=0x3000)

        core1.state.pc = 0x1000
        core1.run()

        # ESCALATE 后可以 RETURN
        assert core1.state.get_reg(2) == 222  # 子域继续执行了
        assert rpa1.get_depth() == 1  # 在子域

        # === EXIT 场景 ===
        mem2 = Memory(size=64 * 1024)

        block_addr2 = 0x1000
        child_entry2 = 0x3000
        mem2.write_word(block_addr2 + 0x00, 32)
        mem2.write_word(block_addr2 + 0x04, 0)
        mem2.write_word(block_addr2 + 0x10, 0)
        mem2.write_word(block_addr2 + 0x24, child_entry2)

        rpa2 = RPALogic()
        rpa2.memory = mem2
        core2 = SimpleISA(rpa=rpa2, memory=mem2)
        rpa2.root_domain.block.exception_vector = 0x4000

        core2.load_assembly("""
            MOV R0, #0x1000
            DESCEND R0
            ; EXIT 后回到这里
            MOV R3, #333
            HALT
        """, base_addr=0x0000)

        core2.load_assembly("""
            MOV R4, #444
            MOV R0, #0
            EXIT R0
            ; EXIT 后不会执行
            MOV R5, #555
            HALT
        """, base_addr=child_entry2)

        core2.load_assembly("HALT", base_addr=0x4000)

        core2.state.pc = 0x0000
        core2.run()

        # EXIT 后子域被释放
        assert core2.state.get_reg(4) == 444  # 子域执行了
        assert core2.state.get_reg(5) == 0    # EXIT 后没执行
        assert rpa2.get_depth() == 0  # 回到根域
        assert rpa2.root_domain.block.child_block == 0  # 子域已释放