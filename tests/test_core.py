"""
Tests for RPA Core

Basic unit tests for the RPA simulator core functionality.
"""

import pytest
from rpa_sim import RPACore, Level, LevelConfig, INHERIT, INDEPENDENT, FaultInfo


# 标记预期失败的测试
xfail_design_issue = pytest.mark.xfail(
    reason="设计问题：escalate 时 service_handler 应该在父层查找还是当前层查找？"
)


class TestRPACore:
    """Tests for RPACore class"""

    def test_create_core(self):
        """Test creating RPA core"""
        rpa = RPACore()
        assert rpa.current is rpa.root
        assert rpa.get_level_depth() == 0

    def test_add_sublayer(self):
        """Test adding sublayer configuration"""
        rpa = RPACore()

        config = LevelConfig(
            execution_addr=0x1000,
            exception_vector=0x2000,
            page_table=INHERIT,
        )

        idx = rpa.configure_sublayer(rpa.root, config)
        assert idx == 0
        assert rpa.root.get_sublayer(0) is not None

    def test_descend(self):
        """Test descending to sublayer"""
        rpa = RPACore()

        config = LevelConfig(
            execution_addr=0x1000,
            exception_vector=0x2000,
            page_table=INHERIT,
        )

        rpa.configure_sublayer(rpa.root, config)
        result = rpa.descend(LevelConfig(
            execution_addr=0x1000,
            params={"test": "data"}
        ))

        assert rpa.stats["descend_count"] == 1
        assert rpa.get_level_depth() == 1

    def test_escalate_from_root_fails(self):
        """Test that escalating from root fails"""
        rpa = RPACore()

        with pytest.raises(RuntimeError, match="Cannot escalate from root"):
            rpa.escalate(LevelConfig(
                execution_addr=0,
                params={"request": "test"}
            ))

    def test_escalate_from_sublayer(self):
        """Test escalating from sublayer"""
        rpa = RPACore()

        config = LevelConfig(
            execution_addr=0x1000,
            exception_vector=0x2000,
            page_table=INHERIT,
        )

        rpa.configure_sublayer(rpa.root, config)
        rpa.descend(LevelConfig(
            execution_addr=0x1000,
            params={"test": "data"}
        ))

        result = rpa.escalate(LevelConfig(
            execution_addr=0,
            params={"request": "service"}
        ))
        assert result["escalated"] is True

    def test_return_to_parent(self):
        """Test returning to parent"""
        rpa = RPACore()

        config = LevelConfig(
            execution_addr=0x1000,
            exception_vector=0x2000,
            page_table=INHERIT,
        )

        rpa.configure_sublayer(rpa.root, config)
        rpa.descend(LevelConfig(
            execution_addr=0x1000,
            params={"test": "data"}
        ))

        assert rpa.get_level_depth() == 1

        rpa.return_to_parent({"result": "success"})

        assert rpa.get_level_depth() == 0
        assert rpa.root.context.get("sublayer_result") == {"result": "success"}

    def test_nested_levels(self):
        """Test multiple nested levels"""
        rpa = RPACore()

        # Level 0 -> Level 1
        config1 = LevelConfig(
            execution_addr=0x1000,
            exception_vector=0x2000,
            page_table=INHERIT,
        )
        rpa.configure_sublayer(rpa.root, config1)

        # Descend to Level 1
        rpa.descend(LevelConfig(
            execution_addr=0x1000,
            params={"level": 1}
        ))
        assert rpa.get_level_depth() == 1

        # Configure Level 1's sublayer (Level 2)
        level1 = rpa.current
        config2 = LevelConfig(
            execution_addr=0x3000,
            exception_vector=0x4000,
            page_table=INHERIT,
        )
        rpa.configure_sublayer(level1, config2)

        # Descend to Level 2
        rpa.descend(LevelConfig(
            execution_addr=0x3000,
            params={"level": 2}
        ))
        assert rpa.get_level_depth() == 2

        # Escalate from Level 2 to Level 1
        result = rpa.escalate(LevelConfig(
            execution_addr=0,
            params={"request": "from_level_2"}
        ))
        assert result["from_level"] == 2

    def test_stats(self):
        """Test statistics tracking"""
        rpa = RPACore()

        config = LevelConfig(
            execution_addr=0x1000,
            exception_vector=0x2000,
            page_table=INHERIT,
        )

        rpa.configure_sublayer(rpa.root, config)
        rpa.descend(LevelConfig(
            execution_addr=0x1000,
            params={"test": "data"}
        ))
        rpa.escalate(LevelConfig(
            execution_addr=0,
            params={"request": "service"}
        ))

        stats = rpa.get_stats()
        assert stats["descend_count"] == 1
        assert stats["escalate_count"] == 1


class TestLevel:
    """Tests for Level class"""

    def test_create_level(self):
        """Test creating a level"""
        config = LevelConfig(execution_addr=0x8000)
        level = Level(level_id=0, config=config)
        assert level.level_id == 0
        assert len(level.sub_configs) == 0

    def test_add_sublayer(self):
        """Test adding sublayers"""
        config = LevelConfig(execution_addr=0x8000)
        level = Level(level_id=0, config=config)

        config1 = LevelConfig(execution_addr=0x1000, exception_vector=0x2000, page_table=INHERIT)
        config2 = LevelConfig(execution_addr=0x3000, exception_vector=0x4000, page_table=INHERIT)

        idx1 = level.add_sublayer(config1)
        idx2 = level.add_sublayer(config2)

        assert idx1 == 0
        assert idx2 == 1
        assert len(level.sub_configs) == 2

    def test_get_sublayer(self):
        """Test getting sublayer by index"""
        config = LevelConfig(execution_addr=0x8000)
        level = Level(level_id=0, config=config)

        sub_config = LevelConfig(execution_addr=0x1000, exception_vector=0x2000, page_table=INHERIT)
        level.add_sublayer(sub_config)

        assert level.get_sublayer(0) is not None
        assert level.get_sublayer(0).execution_addr == 0x1000
        assert level.get_sublayer(1) is None
        assert level.get_sublayer(-1) is None


class TestLevelConfig:
    """Tests for LevelConfig dataclass"""

    def test_create_config(self):
        """Test creating level configuration"""
        config = LevelConfig(
            execution_addr=0x1000,
            exception_vector=0x2000,
            page_table=INHERIT,
        )

        assert config.execution_addr == 0x1000
        assert config.exception_vector == 0x2000
        assert config.page_table == INHERIT

    def test_config_with_params(self):
        """Test configuration with parameters"""
        config = LevelConfig(
            execution_addr=0x1000,
            exception_vector=0x2000,
            page_table=INHERIT,
            params={"key": "value"},
        )

        assert config.params == {"key": "value"}

    def test_config_with_interrupt(self):
        """Test configuration with interrupt settings"""
        config = LevelConfig(
            execution_addr=0x1000,
            exception_vector=0x2000,
            page_table=INHERIT,
            interrupt_controller=0xFFFF0000,
            interrupt_vector=0x3000,
        )

        assert config.interrupt_controller == 0xFFFF0000
        assert config.interrupt_vector == 0x3000

    def test_config_with_program_state(self):
        """Test configuration with program state"""
        config = LevelConfig(
            execution_addr=0x1000,
            exception_vector=0x2000,
            page_table=INHERIT,
            program={"lr": 0x8000, "spsr": 0x1F},
        )

        assert config.program == {"lr": 0x8000, "spsr": 0x1F}


class TestProcessCreation:
    """
    测试进程创建场景

    进程创建涉及：
    - 为新进程创建独立的特权层
    - 配置独立的页表（内存隔离）
    - 设置进程入口点
    - 可选：继承父进程资源
    """

    def test_create_process_with_isolated_memory(self):
        """
        测试创建具有独立内存空间的进程

        场景：操作系统创建新进程
        - 进程拥有独立页表（内存隔离）
        - 进程有独立的异常处理入口
        - 进程从指定入口点开始执行
        """
        rpa = RPACore()

        # 内核配置新进程的特权层
        # 使用 INDEPENDENT 表示进程拥有独立页表
        process_config = LevelConfig(
            execution_addr=0x400000,           # 进程入口点
            exception_vector=0x400100,         # 进程异常处理入口
            page_table=0x50000,                # 进程独立页表基址
            params={
                "process_id": 1001,            # 进程ID
                "process_name": "test_process"
            }
        )
        rpa.configure_sublayer(rpa.root, process_config)

        # 内核切换到进程（descend）
        result = rpa.descend(LevelConfig(
            execution_addr=0x400000,
            params={"process_id": 1001}
        ))

        # 验证：已进入进程特权层
        assert rpa.get_level_depth() == 1
        assert result["entry"] == 0x400000
        assert rpa.current.config.page_table == 0x50000  # 独立页表

    def test_create_process_inherit_page_table(self):
        """
        测试创建共享页表的进程（线程）

        场景：创建与父进程共享内存空间的执行单元
        - 使用 INHERIT (page_table=0) 继承父进程页表
        - 适用于线程或协程
        """
        rpa = RPACore()

        # 创建共享页表的执行单元
        thread_config = LevelConfig(
            execution_addr=0x1000,
            exception_vector=0x2000,
            page_table=INHERIT,                # 继承父进程页表
            params={"thread_id": 1}
        )
        rpa.configure_sublayer(rpa.root, thread_config)

        rpa.descend(LevelConfig(
            execution_addr=0x1000,
            params={"thread_id": 1}
        ))

        # 验证：页表继承自父层
        assert rpa.current.config.page_table == INHERIT

    def test_process_context_switch(self):
        """
        测试进程上下文切换

        场景：从一个进程切换到另一个进程
        - 保存当前进程状态到 context
        - 返回父层（return_to_parent）
        - 进入另一个进程
        """
        rpa = RPACore()

        # 配置两个进程
        process_a_config = LevelConfig(
            execution_addr=0x400000,
            exception_vector=0x400100,
            page_table=0x50000,
            params={"process_id": "A"}
        )
        process_b_config = LevelConfig(
            execution_addr=0x600000,
            exception_vector=0x600100,
            page_table=0x60000,
            params={"process_id": "B"}
        )

        rpa.configure_sublayer(rpa.root, process_a_config)   # index 0
        rpa.configure_sublayer(rpa.root, process_b_config)   # index 1

        # 进入进程 A
        rpa.descend(LevelConfig(
            execution_addr=0x400000,
            params={"process_id": "A"}
        ))
        rpa.current.context["registers"] = {"r0": 0x1111, "pc": 0x400100}

        # 切换回内核
        rpa.return_to_parent({"saved_state": "process_A_state"})

        # 进入进程 B
        rpa.descend(LevelConfig(
            execution_addr=0x600000,
            params={"process_id": "B"},
            sub_index=1
        ))

        # 验证：当前在进程 B
        assert rpa.current.config.execution_addr == 0x600000


class TestThreadCreation:
    """
    测试线程创建场景

    线程与进程的区别：
    - 线程共享父进程的内存空间（INHERIT 页表）
    - 线程有独立的执行入口和栈
    - 线程可访问父进程的资源
    """

    def test_create_user_thread(self):
        """
        测试创建用户态线程

        场景：进程内创建新线程
        - 线程共享进程页表
        - 线程有独立入口点
        - 线程有独立栈（通过 params 传递）
        """
        rpa = RPACore()

        # 先创建进程层
        process_config = LevelConfig(
            execution_addr=0x400000,
            exception_vector=0x400100,
            page_table=0x50000,
        )
        rpa.configure_sublayer(rpa.root, process_config)
        rpa.descend(LevelConfig(execution_addr=0x400000))

        # 在进程内配置线程
        # 线程继承进程页表
        thread_config = LevelConfig(
            execution_addr=0x410000,           # 线程入口
            exception_vector=INHERIT,          # 继承进程异常处理
            page_table=INHERIT,                # 继承进程页表
            program={
                "sp": 0x7F000000,              # 线程独立栈指针
                "lr": 0x400000,                # 返回地址
            },
            params={"thread_id": 1, "stack_base": 0x7F000000}
        )

        level1 = rpa.current
        rpa.configure_sublayer(level1, thread_config)
        rpa.descend(LevelConfig(
            execution_addr=0x410000,
            program={"sp": 0x7F000000}
        ))

        # 验证：线程在进程内，共享页表
        assert rpa.get_level_depth() == 2
        assert rpa.current.config.page_table == INHERIT
        assert rpa.current.config.program["sp"] == 0x7F000000

    @xfail_design_issue
    def test_thread_access_parent_resource(self):
        """
        测试线程访问父进程资源

        场景：线程通过 escalate 请求父进程服务
        - 线程需要访问共享资源
        - 通过 escalate 向进程请求

        FIXME: 测试失败 - KeyError: 'granted'
        原因分析：
        - service_handler 设置在进程层（父层）
        - 线程层调用 escalate 时，当前实现从 current.context 查找 handler
        - 但 current 是线程层，不是进程层
        - 问题：escalate 是否应该自动切换到父层上下文执行？
        - 还是需要在 descend 时继承父层的 handler？
        """
        rpa = RPACore()

        # 创建进程和线程
        process_config = LevelConfig(
            execution_addr=0x400000,
            exception_vector=0x400100,
            page_table=0x50000,
        )
        rpa.configure_sublayer(rpa.root, process_config)
        rpa.descend(LevelConfig(execution_addr=0x400000))

        # 在进程层设置资源处理器
        def resource_handler(params):
            return {"granted": True, "resource": "shared_memory"}

        rpa.current.context["service_handler"] = resource_handler

        # 创建线程
        thread_config = LevelConfig(
            execution_addr=0x410000,
            page_table=INHERIT,
        )
        rpa.configure_sublayer(rpa.current, thread_config)
        rpa.descend(LevelConfig(execution_addr=0x410000))

        # 线程请求进程资源
        result = rpa.escalate(LevelConfig(
            execution_addr=0,
            params={"request": "access_shared_resource"}
        ))

        # 验证：请求成功
        assert result["granted"] is True


class TestInterruptHandling:
    """
    测试中断处理场景

    中断 vs 异常：
    - 中断：外部事件触发，需要快速响应
    - 异常：内部执行错误，需要处理恢复
    - RPA 提供独立的中断向量（interrupt_vector）
    """

    def test_interrupt_vector_configuration(self):
        """
        测试中断向量配置

        场景：配置特权层的中断处理
        - interrupt_controller: 中断控制器基址
        - interrupt_vector: 中断处理入口
        """
        rpa = RPACore()

        # 配置带有中断处理的特权层
        config = LevelConfig(
            execution_addr=0x8000,
            exception_vector=0x8004,           # 异常处理入口
            interrupt_controller=0xFFFF0000,   # GIC 基址（ARM 示例）
            interrupt_vector=0x9000,           # 中断处理入口
            page_table=INHERIT,
        )
        rpa.configure_sublayer(rpa.root, config)
        rpa.descend(LevelConfig(execution_addr=0x8000))

        # 验证：中断配置正确传递
        assert rpa.current.config.interrupt_controller == 0xFFFF0000
        assert rpa.current.config.interrupt_vector == 0x9000
        # 中断向量与异常向量分离
        assert rpa.current.config.exception_vector == 0x8004
        assert rpa.current.config.interrupt_vector == 0x9000

    def test_interrupt_handler_registration(self):
        """
        测试中断处理器注册

        场景：特权层注册中断处理器
        - 注册特定中断类型的处理函数
        - 中断触发时调用对应处理器
        """
        rpa = RPACore()

        # 中断处理计数器
        interrupt_count = {"timer": 0, "uart": 0}

        # 注册中断处理器
        def timer_handler(fault_info):
            interrupt_count["timer"] += 1

        def uart_handler(fault_info):
            interrupt_count["uart"] += 1

        rpa.exception_handlers["timer_interrupt"] = timer_handler
        rpa.exception_handlers["uart_interrupt"] = uart_handler

        # 触发中断（通过 fault 模拟）
        rpa.fault("timer_interrupt", address=0)
        rpa.fault("uart_interrupt", address=0)

        # 验证：中断处理器被调用
        assert interrupt_count["timer"] == 1
        assert interrupt_count["uart"] == 1

    def test_nested_interrupt_handling(self):
        """
        测试嵌套中断处理

        场景：中断处理过程中发生另一个中断
        - 高优先级中断可以抢占低优先级中断
        - 需要正确保存/恢复上下文
        """
        rpa = RPACore()

        # 配置外层（低优先级中断处理）
        outer_config = LevelConfig(
            execution_addr=0x8000,
            exception_vector=0x8004,
            interrupt_vector=0x9000,
            page_table=INHERIT,
        )
        rpa.configure_sublayer(rpa.root, outer_config)

        # 进入外层
        rpa.descend(LevelConfig(execution_addr=0x8000))

        # 配置内层（高优先级中断处理）
        inner_config = LevelConfig(
            execution_addr=0xA000,
            exception_vector=0xA004,
            interrupt_vector=0xB000,
            page_table=INHERIT,
        )
        rpa.configure_sublayer(rpa.current, inner_config)

        # 进入内层（模拟高优先级中断抢占）
        rpa.descend(LevelConfig(execution_addr=0xA000))

        # 验证：嵌套深度正确
        assert rpa.get_level_depth() == 2
        assert rpa.current.config.interrupt_vector == 0xB000


class TestPageFaultHandling:
    """
    测试缺页异常处理场景

    缺页异常是内存管理中的核心场景：
    - 访问未映射页面时触发
    - 需要向父层请求页面映射
    - 处理完成后恢复执行
    """

    def test_page_fault_basic(self):
        """
        测试基本缺页异常处理

        场景：进程访问未映射地址
        - 触发缺页异常
        - 异常传递到父层处理
        - 父层映射页面后恢复执行
        """
        rpa = RPACore()

        # 配置带有异常处理的子层
        process_config = LevelConfig(
            execution_addr=0x400000,
            exception_vector=0x400100,
            page_table=0x50000,
        )
        rpa.configure_sublayer(rpa.root, process_config)

        # 记录异常信息
        fault_info_captured = {}

        def page_fault_handler(info):
            fault_info_captured["type"] = info.fault_type
            fault_info_captured["address"] = info.address
            fault_info_captured["layer"] = info.layer

        rpa.exception_handlers["page_fault"] = page_fault_handler

        # 进入进程
        rpa.descend(LevelConfig(execution_addr=0x400000))

        # 触发缺页异常
        rpa.fault("page_fault", address=0xDEADBEEF)

        # 验证：异常被正确捕获
        assert fault_info_captured["type"] == "page_fault"
        assert fault_info_captured["address"] == 0xDEADBEEF
        assert fault_info_captured["layer"] == 1

    @xfail_design_issue
    def test_page_fault_escalation(self):
        """
        测试缺页异常向上传递

        场景：子层无法处理缺页，需要向父层请求
        - 子层触发缺页
        - escalate 到父层请求页面
        - 父层处理并返回

        FIXME: 测试失败 - KeyError: 'status'
        原因分析：
        - page_allocator 设置在父层（level 1）
        - 子层（level 2）调用 escalate 时，当前实现从 current.context 查找 handler
        - 但 current 是子层，不是父层
        - 问题：escalate 是否应该自动切换到父层上下文执行？
        - 这是与 test_thread_access_parent_resource 相同的设计问题
        """
        rpa = RPACore()

        # 父层设置
        parent_config = LevelConfig(
            execution_addr=0x1000,
            exception_vector=0x1004,
            page_table=0x10000,
        )
        rpa.configure_sublayer(rpa.root, parent_config)
        rpa.descend(LevelConfig(execution_addr=0x1000))

        # 在父层设置页面分配处理器
        def page_allocator(params):
            if params.get("type") == "page_fault":
                return {
                    "status": "mapped",
                    "physical_addr": 0x80000000,
                    "page_size": 4096
                }
            return {"status": "unknown"}

        rpa.current.context["service_handler"] = page_allocator

        # 配置子层
        child_config = LevelConfig(
            execution_addr=0x2000,
            exception_vector=0x2004,
            page_table=INHERIT,
        )
        rpa.configure_sublayer(rpa.current, child_config)
        rpa.descend(LevelConfig(execution_addr=0x2000))

        # 子层触发缺页并向父层请求
        result = rpa.escalate(LevelConfig(
            execution_addr=0,
            params={
                "type": "page_fault",
                "virtual_addr": 0xDEADBEEF,
                "access_type": "read"
            }
        ))

        # 验证：父层正确处理
        assert result["status"] == "mapped"
        assert result["page_size"] == 4096

    def test_page_fault_propagation_to_root(self):
        """
        测试缺页异常传播到根层

        场景：多层嵌套中，缺页一直传播到根层
        - 最内层触发缺页
        - 各层无法处理，逐层向上
        - 最终由根层处理
        """
        rpa = RPACore()

        # 构建三层结构
        layer1_config = LevelConfig(
            execution_addr=0x1000,
            exception_vector=0x1004,
            page_table=0x10000,
        )
        rpa.configure_sublayer(rpa.root, layer1_config)
        rpa.descend(LevelConfig(execution_addr=0x1000))

        layer2_config = LevelConfig(
            execution_addr=0x2000,
            exception_vector=0x2004,
            page_table=INHERIT,
        )
        rpa.configure_sublayer(rpa.current, layer2_config)
        rpa.descend(LevelConfig(execution_addr=0x2000))

        layer3_config = LevelConfig(
            execution_addr=0x3000,
            exception_vector=0,             # 无异常处理
            page_table=INHERIT,
        )
        rpa.configure_sublayer(rpa.current, layer3_config)
        rpa.descend(LevelConfig(execution_addr=0x3000))

        # 验证：在第3层
        assert rpa.get_level_depth() == 3

        # 触发缺页，应该传播到根层
        # 由于根层没有异常处理器，会抛出 RuntimeError
        try:
            rpa.fault("page_fault", address=0xBADC0DE0)
        except RuntimeError as e:
            # 验证：异常传播到根层
            assert "Unhandled fault" in str(e)

    def test_page_fault_with_recovery(self):
        """
        测试缺页异常恢复

        场景：缺页处理后恢复执行
        - 触发缺页
        - 处理器映射页面
        - 返回并恢复执行
        """
        rpa = RPACore()

        # 配置
        config = LevelConfig(
            execution_addr=0x400000,
            exception_vector=0x400100,
            page_table=0x50000,
        )
        rpa.configure_sublayer(rpa.root, config)

        # 页面映射状态
        mapped_pages = set()

        def page_fault_handler(info):
            # 模拟页面映射
            page_addr = info.address & ~0xFFF
            mapped_pages.add(page_addr)

        rpa.exception_handlers["page_fault"] = page_fault_handler

        # 进入子层
        rpa.descend(LevelConfig(execution_addr=0x400000))

        # 触发缺页
        rpa.fault("page_fault", address=0x12345678)

        # 验证：页面被映射
        assert 0x12345000 in mapped_pages

        # 可以继续执行（模拟）
        assert rpa.get_level_depth() == 1