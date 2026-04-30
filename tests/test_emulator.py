"""
模拟执行测试

测试 RPA 核心功能使用真正的指令模拟。

测试场景：
1. RPACore 分配和释放功能
2. 子层分配和执行：子层有独立页表，代码放在地址空间尾部，
   程序最后使用 ESCALATE 退出，验证执行序列。
"""

import pytest
import sys
sys.path.insert(0, '..')

from rpa_sim import (
    RPACore, Level, LevelConfig, INHERIT, INDEPENDENT,
    PhysicalMemory, MemoryManager, Emulator, Asm
)


class TestPhysicalMemory:
    """
    测试物理内存模拟器

    验证基本的内存读写功能。
    """

    def test_create_physical_memory(self):
        """
        测试创建物理内存

        创建1MB物理内存，地址范围 0x00000000 - 0x000FFFFF
        """
        mem = PhysicalMemory(size=1024 * 1024)
        assert mem.size == 1024 * 1024

    def test_read_write_byte(self):
        """
        测试字节读写

        在地址 0x1000 写入字节 0xAB，然后读取验证
        """
        mem = PhysicalMemory(size=1024 * 1024)
        mem.write_byte(0x1000, 0xAB)
        assert mem.read_byte(0x1000) == 0xAB

    def test_read_write_word(self):
        """
        测试字（32位）读写

        在地址 0x2000 写入 0xDEADBEEF，然后读取验证
        """
        mem = PhysicalMemory(size=1024 * 1024)
        mem.write_word(0x2000, 0xDEADBEEF)
        assert mem.read_word(0x2000) == 0xDEADBEEF

    def test_read_write_bytes(self):
        """
        测试多字节读写

        写入一个字节序列，然后读取验证
        """
        mem = PhysicalMemory(size=1024 * 1024)
        data = bytes([0x01, 0x02, 0x03, 0x04, 0x05])
        mem.write_bytes(0x3000, data)
        assert mem.read_bytes(0x3000, 5) == data

    def test_memory_bounds_check(self):
        """
        测试内存边界检查

        访问超出内存范围的地址应该抛出 MemoryError
        """
        mem = PhysicalMemory(size=1024)  # 1KB 内存
        with pytest.raises(MemoryError):
            mem.read_byte(0x1000)  # 超出范围

    def test_access_log(self):
        """
        测试访问日志

        内存读写应该被记录到访问日志中
        """
        mem = PhysicalMemory(size=1024)
        mem.clear_access_log()

        mem.write_word(0x100, 0x12345678)
        mem.read_word(0x100)

        assert len(mem.access_log) == 2
        assert mem.access_log[0]["type"] == "write"
        assert mem.access_log[1]["type"] == "read"


class TestEmulator:
    """
    测试指令模拟器

    验证汇编、加载和执行功能。
    """

    def test_assemble_basic(self):
        """
        测试基本汇编

        汇编简单的 MOV 指令，验证正确解析
        """
        emu = Emulator()
        end_addr = emu.load_assembly("MOV R0, #42", base_addr=0x1000)

        assert end_addr == 0x1004  # 一条指令4字节
        assert 0x1000 in emu.instructions
        inst = emu.instructions[0x1000]
        assert inst.opcode.name == "MOV"
        assert inst.rd == 0
        assert inst.imm == 42

    def test_assemble_with_labels(self):
        """
        测试带标签的汇编

        汇编包含标签和分支的代码
        """
        emu = Emulator()
        code = """
        start:
            MOV R0, #1
            ADD R0, R0, #1
            B start
        """
        emu.load_assembly(code, base_addr=0x1000)

        assert "start" in emu.labels
        assert emu.labels["start"] == 0x1000

    def test_execute_mov(self):
        """
        测试 MOV 指令执行

        执行 MOV R0, #123，验证寄存器值
        """
        mem = PhysicalMemory(size=64 * 1024)  # 64KB
        emu = Emulator(memory=mem)

        emu.load_assembly("MOV R0, #123", base_addr=0x1000)
        emu.state.pc = 0x1000
        emu.step()

        assert emu.state.get_reg(0) == 123

    def test_execute_add(self):
        """
        测试 ADD 指令执行

        执行 R0 = R1 + R2
        """
        mem = PhysicalMemory(size=64 * 1024)  # 64KB
        emu = Emulator(memory=mem)

        code = """
            MOV R1, #10
            MOV R2, #20
            ADD R0, R1, R2
            HALT
        """
        emu.load_assembly(code, base_addr=0x1000)
        emu.state.pc = 0x1000
        emu.run()

        assert emu.state.get_reg(0) == 30

    def test_execute_loop(self):
        """
        测试循环执行

        计算 1 + 2 + ... + 10 = 55
        """
        mem = PhysicalMemory(size=64 * 1024)  # 64KB
        emu = Emulator(memory=mem)

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
        emu.load_assembly(code, base_addr=0x1000)
        emu.state.pc = 0x1000
        emu.run()

        assert emu.state.get_reg(0) == 55  # 1+2+...+10 = 55

    def test_execution_log(self):
        """
        测试执行日志

        验证每条指令的执行都被记录
        """
        mem = PhysicalMemory(size=64 * 1024)  # 64KB
        emu = Emulator(memory=mem)

        code = """
            MOV R0, #1
            MOV R1, #2
            ADD R0, R0, R1
            HALT
        """
        emu.load_assembly(code, base_addr=0x1000)
        emu.state.pc = 0x1000
        emu.run()

        log = emu.get_execution_log()
        assert len(log) == 4  # 4条指令

        # 验证每条指令的记录
        assert log[0]["opcode"] == "MOV"
        assert log[0]["rd"] == 0
        assert log[2]["opcode"] == "ADD"


class TestSublayerExecution:
    """
    测试子层执行

    测试场景：
    - 子层有独立的页表
    - 代码放在地址空间尾部
    - 程序最后使用 ESCALATE 退出
    - 验证执行序列与内存中的程序一致
    """

    def test_sublayer_with_own_page_table(self):
        """
        测试子层使用独立页表

        场景：
        1. 根层分配1MB物理内存
        2. 创建子层，使用独立页表（非INHERIT）
        3. 子层代码运行，验证隔离性
        """
        # 创建物理内存
        mem = PhysicalMemory(size=1024 * 1024)  # 1MB

        # 创建内存管理器
        mm = MemoryManager(physical_memory=mem)

        # 根层代码：简单初始化
        root_code = """
            MOV R0, #100
            MOV R1, #200
            ADD R2, R0, R1
            HALT
        """

        emu_root = Emulator(memory=mem)
        emu_root.load_assembly(root_code, base_addr=0x0000)

        # 创建子层页表
        # 子层虚拟地址 0x10000 映射到物理地址 0x80000
        sub_page_table = mm.create_page_table(base_addr=0x1000)
        sub_page_table.map(va=0x10000, pa=0x80000)

        # 子层代码：使用不同的寄存器
        sub_code = """
            MOV R3, #1000
            MOV R4, #2000
            ADD R5, R3, R4
            HALT
        """

        emu_sub = Emulator(memory=mem)
        emu_sub.load_assembly(sub_code, base_addr=0x80000)  # 物理地址

        # 运行根层
        emu_root.state.pc = 0x0000
        emu_root.run()

        # 验证根层结果
        assert emu_root.state.get_reg(2) == 300

        # 运行子层（模拟切换到子层）
        emu_sub.state.pc = 0x80000
        emu_sub.run()

        # 验证子层结果
        assert emu_sub.state.get_reg(5) == 3000

    def test_sublayer_exit_with_escalate(self):
        """
        测试子层使用 ESCALATE 退出

        场景：
        1. 子层程序执行计算
        2. 最后使用 ESCALATE 指令退出（不使用 HALT）
        3. ESCALATE 触发返回父层
        """
        mem = PhysicalMemory(size=1024 * 1024)
        emu = Emulator(memory=mem)

        # 子层代码：计算后用 ESCALATE 退出
        # ESCALATE R0 表示返回值在 R0
        code = """
            MOV R0, #42
            MOV R1, #100
            ADD R0, R0, R1    ; R0 = 142
            ESCALATE R0       ; 退出并返回 R0
        """

        emu.load_assembly(code, base_addr=0x1000)

        # 设置 escalate 处理器
        escalate_result = {"called": False, "value": 0}

        def escalate_handler(params):
            escalate_result["called"] = True
            escalate_result["value"] = params
            emu.halted = True  # 停止执行
            return params

        emu.escalate_handler = escalate_handler

        # 运行
        emu.state.pc = 0x1000
        emu.run()

        # 验证：ESCALATE 被调用
        assert escalate_result["called"] is True
        assert emu.state.get_reg(0) == 142

        # 验证执行日志：4条指令都被执行
        log = emu.get_execution_log()
        assert len(log) == 4
        assert log[3]["opcode"] == "ESCALATE"

    def test_sublayer_execution_sequence(self):
        """
        测试子层执行序列验证

        场景：
        1. 子层执行一系列指令
        2. 记录执行序列
        3. 与预期的指令序列比较
        """
        mem = PhysicalMemory(size=1024 * 1024)
        emu = Emulator(memory=mem)

        # 预定义的指令序列
        expected_sequence = [
            ("MOV", 0, 0, 0, 10),   # MOV R0, #10
            ("MOV", 1, 0, 0, 20),   # MOV R1, #20
            ("ADD", 2, 0, 1, 0),    # ADD R2, R0, R1
            ("SUB", 3, 2, 0, 0),    # SUB R3, R2, R0 (R3 = 30 - 10 = 20)
            ("ESCALATE", 2, 0, 0, 0),  # ESCALATE R2
        ]

        code = """
            MOV R0, #10
            MOV R1, #20
            ADD R2, R0, R1
            SUB R3, R2, R0
            ESCALATE R2
        """

        def escalate_handler(params):
            emu.halted = True
            return params

        emu.escalate_handler = escalate_handler

        emu.load_assembly(code, base_addr=0x1000)
        emu.state.pc = 0x1000
        emu.run()

        # 获取执行日志
        log = emu.get_execution_log()

        # 验证执行序列
        assert len(log) == len(expected_sequence)

        for i, (exp, actual) in enumerate(zip(expected_sequence, log)):
            assert actual["opcode"] == exp[0], f"指令 {i}: 操作码不匹配"

    def test_rpa_descend_escalate_simulation(self):
        """
        测试 RPA descend/escalate 模拟

        场景：
        1. 根层程序调用 DESCEND 进入子层
        2. 子层程序执行计算
        3. 子层通过 ESCALATE 退出并返回结果
        4. 根层继续执行
        """
        mem = PhysicalMemory(size=1024 * 1024)
        emu = Emulator(memory=mem)

        # 根层代码
        root_code = """
            MOV R0, #100
            MOV R1, #200
            MOV R2, #0x1000
            DESCEND R2
            ADD R3, R0, #1
            HALT
        """

        # 子层代码（在地址 0x1000）
        sub_code = """
            MOV R4, #1000
            ADD R4, R4, R0
            MOV R0, R4
            ESCALATE R0
        """

        emu.load_assembly(root_code, base_addr=0x0000)
        emu.load_assembly(sub_code, base_addr=0x1000)

        # 设置 descend 处理器
        def descend_handler(params):
            emu.state.lr = emu.state.pc + 4
            emu.state.pc = params
            return 0

        emu.descend_handler = descend_handler

        # 设置 escalate 处理器
        def escalate_handler(params):
            emu.state.pc = emu.state.lr
            emu.halted = False
            return params

        emu.escalate_handler = escalate_handler

        # 运行
        emu.state.pc = 0x0000
        steps = emu.run(max_steps=100)

        # 检查 DESCEND 和 ESCALATE 被执行
        log = emu.get_execution_log()
        descend_executed = any(entry["opcode"] == "DESCEND" for entry in log)
        escalate_executed = any(entry["opcode"] == "ESCALATE" for entry in log)

        assert descend_executed, "DESCEND 指令应被执行"
        assert escalate_executed, "ESCALATE 指令应被执行"


class TestRPACoreBasic:
    """
    测试 RPACore 基本功能

    验证层级创建、销毁和状态管理。
    """

    def test_rpa_core_creation(self):
        """
        测试 RPACore 创建和初始化
        """
        rpa = RPACore()

        assert rpa.root is not None
        assert rpa.current is rpa.root
        assert rpa.get_level_depth() == 0

    def test_rpa_sublayer_allocation(self):
        """
        测试子层分配

        创建子层配置并验证配置正确存储
        """
        rpa = RPACore()

        sub_config = LevelConfig(
            execution_addr=0x1000,
            exception_vector=0x2000,
            page_table=0x10000,
        )

        idx = rpa.configure_sublayer(rpa.root, sub_config)
        assert idx == 0
        assert rpa.root.get_sublayer(0) is not None

    def test_rpa_descend_and_return(self):
        """
        测试 descend 和 return_to_parent
        """
        rpa = RPACore()

        sub_config = LevelConfig(
            execution_addr=0x1000,
            exception_vector=0x2000,
            page_table=0x10000,
        )
        rpa.configure_sublayer(rpa.root, sub_config)

        result = rpa.descend(LevelConfig(
            execution_addr=0x1000,
            params={"test": "data"}
        ))

        assert rpa.get_level_depth() == 1
        assert result["executed"] is True

        rpa.return_to_parent({"result": "success"})

        assert rpa.get_level_depth() == 0
        assert rpa.root.context.get("sublayer_result") == {"result": "success"}


class TestIntegrationMemoryAndEmulator:
    """
    集成测试：内存 + 模拟器 + RPA
    """

    def test_full_execution_with_memory(self):
        """
        完整执行测试

        场景：
        1. 创建物理内存
        2. 加载程序到内存
        3. 执行程序
        4. 验证结果
        """
        mem = PhysicalMemory(size=1024 * 1024)
        emu = Emulator(memory=mem)

        simple_code = """
            MOV R0, #1
            MOV R1, #2
            ADD R2, R0, R1
            ADD R2, R2, R0
            ADD R2, R2, R1
            ESCALATE R2
        """

        def escalate_handler(params):
            emu.halted = True
            return params

        emu.escalate_handler = escalate_handler

        emu.load_assembly(simple_code, base_addr=0x1000)
        emu.state.pc = 0x1000
        emu.run()

        assert emu.state.get_reg(2) == 6

    def test_memory_isolation_simulation(self):
        """
        测试内存隔离模拟

        场景：
        1. 根层有独立的地址空间
        2. 子层有独立的地址空间（独立页表）
        3. 两层的代码在不同物理地址
        """
        mem = PhysicalMemory(size=1024 * 1024)

        # 根层代码在物理地址 0x0000
        root_emu = Emulator(memory=mem)
        root_emu.load_assembly("""
            MOV R0, #100
            MOV R1, #200
            ADD R2, R0, R1
            STR R2, [R3]
            HALT
        """, base_addr=0x0000)
        root_emu.state.set_reg(3, 0x0100)

        # 子层代码在物理地址 0x8000
        sub_emu = Emulator(memory=mem)
        sub_emu.load_assembly("""
            MOV R4, #1000
            MOV R5, #2000
            ADD R6, R4, R5
            STR R6, [R7]
            ESCALATE R6
        """, base_addr=0x8000)
        sub_emu.state.set_reg(7, 0x8100)

        def escalate_handler(params):
            sub_emu.halted = True
            return params

        sub_emu.escalate_handler = escalate_handler

        # 执行根层
        root_emu.state.pc = 0x0000
        root_emu.run()

        # 执行子层
        sub_emu.state.pc = 0x8000
        sub_emu.run()

        # 验证结果隔离
        assert root_emu.state.get_reg(2) == 300
        assert sub_emu.state.get_reg(6) == 3000

        # 验证内存隔离
        assert mem.read_word(0x0100) == 300
        assert mem.read_word(0x8100) == 3000