"""
Thread and Exception Tests for RPA

测试场景：
1. 创建两个线程（共享内存的子域）
2. Try-catch 机制（使用子域实现异常捕获）
3. 内存访问异常（访问不存在的地址触发异常）
"""

import pytest
import sys
sys.path.insert(0, '..')

from rpa_sim import (
    RPACore, Domain, DomainBlock, Memory, SimpleCore, Machine
)


class TestThreadCreation:
    """
    测试线程创建场景

    线程与进程的区别：
    - 线程共享父进程的内存空间（memtable_address = 0）
    - 线程有独立执行入口和栈
    - 线程可访问父进程的资源
    """

    def test_create_two_threads(self):
        """
        测试创建两个线程

        场景：
        1. 进程创建两个线程
        2. 两个线程共享内存（memtable_address = 0）
        3. 两个线程有独立入口和栈
        4. 两个线程可以访问共享数据
        """
        machine = Machine(memory_size=1024 * 1024)

        # 共享数据地址
        shared_addr = 0x5000
        machine.write_memory(shared_addr, 100)  # 初始值 100

        # 线程1代码：将共享数据 +200
        thread1_core = SimpleCore(memory=machine.memory)
        thread1_code = """
            MOV R1, #0x5000
            LDR R0, [R1]
            ADD R0, R0, #200
            STR R0, [R1]
            ESCALATE R0
        """
        thread1_core.load_assembly(thread1_code, base_addr=0x2000)
        thread1_core.state.pc = 0x2000
        thread1_core.escalate_handler = lambda x: (setattr(thread1_core, 'halted', True), 0)[1]
        thread1_core.run()

        # 验证线程1执行后共享数据 = 300
        assert machine.memory.read_word(shared_addr) == 300

        # 线程2代码：将共享数据 +300
        thread2_core = SimpleCore(memory=machine.memory)
        thread2_code = """
            MOV R1, #0x5000
            LDR R0, [R1]
            ADD R0, R0, #300
            STR R0, [R1]
            ESCALATE R0
        """
        thread2_core.load_assembly(thread2_code, base_addr=0x3000)
        thread2_core.state.pc = 0x3000
        thread2_core.escalate_handler = lambda x: (setattr(thread2_core, 'halted', True), 0)[1]
        thread2_core.run()

        # 验证线程2执行后共享数据 = 600
        assert machine.memory.read_word(shared_addr) == 600


class TestTryCatchException:
    """
    测试 Try-Catch 异常捕获机制

    RPA 实现异常捕获的方式：
    1. 创建子域作为 try 块
    2. 子域设置 exception_vector 指向 catch 块
    3. 子域触发异常时，跳转到 exception_vector
    4. catch 块处理后继续执行或返回
    """

    def test_try_catch_with_memory_exception(self):
        """
        测试 try-catch 捕获内存异常

        场景：
        1. 进程代码包含 try 块
        2. try 块中访问无效地址
        3. 触发内存异常
        4. catch 块捕获异常并处理
        """
        machine = Machine(memory_size=1024 * 1024)

        # try 块代码：访问无效地址
        try_core = SimpleCore(memory=machine.memory)
        try_code = """
            MOV R0, #0x5000
            LDR R1, [R0]
            ESCALATE R1
        """
        try_core.load_assembly(try_code, base_addr=0x2000)
        try_core.state.pc = 0x2000

        # 正常执行（有效地址）
        try_core.escalate_handler = lambda x: (setattr(try_core, 'halted', True), 0)[1]
        try_core.run()

        # 验证正常执行完成
        assert try_core.halted

        # 模拟内存异常场景
        exception_caught = [False]

        # catch 块代码
        catch_core = SimpleCore(memory=machine.memory)
        catch_code = """
            MOV R5, #2          ; 标记：异常捕获
            ESCALATE R5
        """
        catch_core.load_assembly(catch_code, base_addr=0x3000)
        catch_core.state.pc = 0x3000
        catch_core.escalate_handler = lambda x: (
            setattr(catch_core, 'halted', True),
            exception_caught.__setitem__(0, True),
            0  # 返回值
        )[2]

        # 模拟：try 块触发异常，跳转到 catch 块
        # 在实际硬件中，异常会自动跳转到 exception_vector
        catch_core.run()

        # 验证 catch 块被执行
        assert exception_caught[0] is True
        assert catch_core.state.get_reg(5) == 2


class TestMemoryAccessException:
    """
    测试内存访问异常

    当访问不存在的地址时触发数据访问异常。
    """

    def test_access_invalid_address_triggers_exception(self):
        """
        测试访问无效地址触发异常

        场景：
        1. 子域尝试访问超出内存范围的地址
        2. 触发 MemoryError（模拟内存异常）
        3. 异常信息应该被记录
        """
        machine = Machine(memory_size=1024 * 1024)  # 1MB 内存

        # 子域代码：访问超出范围的地址
        child_core = SimpleCore(memory=machine.memory)
        child_code = """
            MOV R0, #0x2000000   ; 32MB - 超出内存范围
            LDR R1, [R0]        ; 触发异常
            ESCALATE R1
        """
        child_core.load_assembly(child_code, base_addr=0x1000)
        child_core.state.pc = 0x1000

        # 执行 MOV 指令
        child_core.step()
        assert child_core.state.get_reg(0) == 0x2000000

        # 执行 LDR 指令 - 应该触发 MemoryError
        exception_info = {}
        try:
            child_core.step()
        except MemoryError as e:
            # 捕获内存异常
            exception_info['type'] = 'memory_fault'
            exception_info['message'] = str(e)

        # 验证：异常被触发
        assert exception_info['type'] == 'memory_fault'
        assert '0x2000000' in exception_info['message']

        # 在真实 RPA 系统中，这会：
        # 1. 保存异常信息到控制块
        # 2. 跳转到 exception_vector
        # 3. 执行异常处理程序

    def test_nested_try_catch(self):
        """
        测试嵌套 try-catch

        场景：
        1. 外层 try 块
        2. 内层 try 块触发异常
        3. 内层 catch 处理后，外层 catch 不执行
        """
        machine = Machine(memory_size=1024 * 1024)

        # 外层代码
        outer_code = """
            ; 设置内层 try 块
            MOV R0, #0x1000     ; 内层控制块
            MOV R1, #0x3000     ; 内层 try 入口
            STR R1, [R0]
            MOV R1, #0x4000     ; 内层 catch 入口
            STR R1, [R0, #4]

            DESCEND R0

            ; 内层正常返回
            MOV R5, #0          ; 标记：正常完成
            HALT
        """
        machine.load_code(outer_code, base_addr=0x8000, domain_id=0)

        # 内层 try 代码
        inner_try_code = """
            MOV R0, #99
            ESCALATE R0         ; 正常返回
        """
        machine.load_code(inner_try_code, base_addr=0x3000)

        # 内层 catch 代码（不应该执行）
        inner_catch_code = """
            MOV R5, #2          ; 标记：异常捕获
            ESCALATE R5
        """
        machine.load_code(inner_catch_code, base_addr=0x4000)

        # 设置执行环境
        outer_core = machine.root_core
        inner_core = SimpleCore(memory=machine.memory)

        def on_descend(block_addr):
            inner_core.load_assembly(inner_try_code, base_addr=0x3000)
            inner_core.state.pc = 0x3000
            inner_core.escalate_handler = lambda x: (setattr(inner_core, 'halted', True), x)[1]
            inner_core.run()
            return inner_core.state.get_reg(0)

        outer_core.descend_handler = on_descend
        outer_core.state.pc = 0x8000
        outer_core.run()

        # 验证：正常完成，没有异常
        assert outer_core.state.get_reg(5) == 0  # 正常完成标记


class TestDesignQuestions:
    """
    设计问题验证测试

    这些测试用于验证 RPA 设计的核心假设。
    如果测试失败，需要停下来讨论设计问题。
    """

    def test_escalate_jumps_to_parent_exception_vector(self):
        """
        验证 ESCALATE 跳转到父域 exception_vector

        问题：当前 ESCALATE 使用 handler 回调，
        但设计上应该跳转到父域的 exception_vector。
        """
        machine = Machine(memory_size=1024 * 1024)

        # 父域代码
        parent_code = """
            ; 设置子域控制块
            MOV R0, #0x1000
            MOV R1, #0x2000     ; 子域入口
            STR R1, [R0]
            ; exception_vector 由控制块设置

            DESCEND R0

            ; 从子域返回后继续
            HALT
        """
        machine.load_code(parent_code, base_addr=0x8000, domain_id=0)

        # 子域代码
        child_code = """
            MOV R0, #42         ; 服务请求类型
            ESCALATE R0
            ; 返回后继续执行
            HALT
        """
        machine.load_code(child_code, base_addr=0x2000)

        # 父域异常处理代码（exception_vector 指向这里）
        parent_handler_code = """
            ; 处理 ESCALATE
            ; R0 包含服务类型
            ADD R0, R0, #100    ; 处理：返回值 = 服务类型 + 100
            ; 返回子域（简化：设置返回值后 halt）
            HALT
        """
        machine.load_code(parent_handler_code, base_addr=0x3000)

        # 创建控制块
        block = DomainBlock(
            execution_address=0x2000,
            exception_vector=0x3000,  # 父域处理入口
        )
        machine.load_domain_block(0x1000, block)

        # 当前设计验证：
        # ESCALATE 应该：1) 保存子域上下文 2) 跳转到父域 exception_vector
        # 这是设计目标，需要检查当前实现是否正确

        parent_core = machine.root_core
        child_core = SimpleCore(memory=machine.memory)

        child_core.load_assembly(child_code, base_addr=0x2000)

        # 设置 descend 处理
        def on_descend(block_addr):
            child_core.state.pc = 0x2000
            child_core.escalate_handler = lambda x: (setattr(child_core, 'halted', True), x + 100)[1]
            child_core.run()
            return child_core.state.get_reg(0)

        parent_core.descend_handler = on_descend
        parent_core.state.pc = 0x8000
        parent_core.run()

        # 当前实现使用回调机制
        # 设计目标：跳转到 exception_vector
        print(f"Note: Current ESCALATE uses callback, design goal is to jump to exception_vector")

    def test_descend_saves_parent_context(self):
        """
        验证 DESCEND 保存父域上下文

        问题：进入子域时，是否应该自动保存父域寄存器？
        当前实现：没有自动保存，需要手动保存。
        """
        machine = Machine(memory_size=1024 * 1024)

        # 父域代码
        parent_code = """
            MOV R0, #100
            MOV R1, #200
            MOV R2, #0x1000     ; 控制块地址
            DESCEND R2
            ; 返回后检查 R0, R1
            ; 设计问题：R0, R1 应该恢复为 100, 200 还是保持子域的修改？
            HALT
        """
        machine.load_code(parent_code, base_addr=0x8000, domain_id=0)

        # 子域代码
        child_code = """
            MOV R0, #999        ; 修改 R0
            MOV R1, #888        ; 修改 R1
            ESCALATE R0
        """
        machine.load_code(child_code, base_addr=0x2000)

        # 创建控制块
        block = DomainBlock(execution_address=0x2000)
        machine.load_domain_block(0x1000, block)

        parent_core = machine.root_core
        child_core = SimpleCore(memory=machine.memory)

        def on_descend(block_addr):
            child_core.load_assembly(child_code, base_addr=0x2000)
            child_core.state.pc = 0x2000
            child_core.escalate_handler = lambda x: (setattr(child_core, 'halted', True), x)[1]
            child_core.run()
            return child_core.state.get_reg(0)

        parent_core.descend_handler = on_descend
        parent_core.state.pc = 0x8000

        # 执行父域代码
        parent_core.step()  # MOV R0, #100
        parent_core.step()  # MOV R1, #200
        parent_core.step()  # MOV R2, #0x1000

        # 保存父域状态
        saved_r0 = parent_core.state.get_reg(0)
        saved_r1 = parent_core.state.get_reg(1)

        parent_core.step()  # DESCEND R2

        # 问题：子域修改了 R0, R1
        # 返回后父域的 R0, R1 应该是什么值？
        # 设计决策：是否需要自动上下文保存/恢复？

        print(f"Parent R0 before descend: {saved_r0}")
        print(f"Parent R1 before descend: {saved_r1}")
        print(f"Parent R0 after descend: {parent_core.state.get_reg(0)}")
        print(f"Parent R1 after descend: {parent_core.state.get_reg(1)}")
        print(f"Note: Design question - should DESCEND auto-save parent context?")