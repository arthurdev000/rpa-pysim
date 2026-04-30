"""
Try-Catch Example

Demonstrates how RPA can implement exception handling (try-catch)
using sublayers and fault propagation.

Traditional try-catch:
    - Compiler generates exception tables
    - Runtime unwinds stack on exception
    - Limited to single-process exception handling

RPA try-catch:
    - try block = sublayer
    - catch block = exception_vector in parent
    - Fault propagation through escalate
    - Can span multiple privilege domains
"""

import sys
sys.path.insert(0, '..')

from rpa_sim import RPACore, Level, LevelConfig, INHERIT, INDEPENDENT, FaultInfo


class TryCatchDemo:
    """
    Demonstrates try-catch using RPA descend/escalate.
    """

    def __init__(self):
        self.rpa = RPACore()
        self.exception_handled = False
        self.exception_type = None

    def setup_try_block(self, exception_handler_addr=0x2000):
        """
        Set up a try block as a sublayer.

        The exception_vector points to the catch block.
        """
        try_config = LevelConfig(
            execution_addr=0x1000,              # try block entry
            exception_vector=exception_handler_addr,  # catch block
            page_table=INHERIT,                 # Share page table for fast handling
            params={"block_type": "try"}
        )
        self.rpa.configure_sublayer(self.rpa.root, try_config)

        # Set up exception handler at root level to simulate catch behavior
        # In a real implementation, the parent's exception_vector would catch this
        self.rpa.exception_handlers["bus_error"] = self.handle_bus_error
        self.rpa.exception_handlers["div_by_zero"] = self.handle_div_by_zero

        # Store the handler in root's context for demonstration
        self.rpa.root.context["exception_handlers"] = {
            "bus_error": self.handle_bus_error,
            "div_by_zero": self.handle_div_by_zero,
        }

    def handle_bus_error(self, fault_info):
        """
        Handle bus error (catch block simulation).
        """
        print(f"  [CATCH] Bus Error at address {fault_info.address:#x}")
        print(f"  [CATCH] Layer: {fault_info.layer}")
        self.exception_handled = True
        self.exception_type = "bus_error"

    def handle_div_by_zero(self, fault_info):
        """
        Handle division by zero.
        """
        print(f"  [CATCH] Division by Zero at layer {fault_info.layer}")
        self.exception_handled = True
        self.exception_type = "div_by_zero"

    def enter_try_block(self):
        """
        Enter the try block (descend to sublayer).
        """
        print("  [TRY] Entering try block...")
        self.rpa.descend(LevelConfig(
            execution_addr=0x1000,
            params={"operation": "try_enter"}
        ))

    def throw_exception(self, exception_type="bus_error"):
        """
        Throw an exception (trigger fault).
        """
        print(f"  [THROW] Raising {exception_type}...")
        self.rpa.fault(exception_type, address=0xDEADBEEF)

    def exit_try_block(self, success=True):
        """
        Exit try block (return to parent).
        """
        if success:
            print("  [TRY] Block completed successfully")
            self.rpa.return_to_parent({"status": "success"})
        else:
            print("  [TRY] Block exited due to exception")


def demo_successful_try():
    """
    Demonstrate a try block that completes successfully.
    """
    print("=" * 60)
    print("Demo 1: Successful Try Block")
    print("=" * 60)

    demo = TryCatchDemo()
    demo.setup_try_block()

    # Enter try block
    demo.enter_try_block()
    print(f"  Current level: {demo.rpa.get_level_depth()}")

    # Simulate some work
    print("  [TRY] Executing protected code...")
    print("  [TRY] No exceptions occurred!")

    # Exit successfully
    demo.exit_try_block(success=True)
    print(f"  Current level: {demo.rpa.get_level_depth()}")

    print(f"\nException handled: {demo.exception_handled}")
    print("=" * 60)


def demo_caught_exception():
    """
    Demonstrate catching an exception within the try block.
    """
    print("\nDemo 2: Caught Exception")
    print("=" * 60)

    demo = TryCatchDemo()
    demo.setup_try_block()

    # Enter try block
    demo.enter_try_block()

    # Simulate work that throws - in a real implementation,
    # the parent's exception_vector would catch this
    print("  [TRY] Executing protected code...")

    # For demonstration, we manually call the handler
    # In real RPA hardware, the fault would be caught by exception_vector
    fault_info = FaultInfo(
        fault_type="bus_error",
        layer=demo.rpa.current.level_id,
        address=0xDEADBEEF
    )
    demo.handle_bus_error(fault_info)

    # Exit try block after exception
    demo.exit_try_block(success=False)
    print(f"  Current level: {demo.rpa.get_level_depth()}")

    print(f"\n  Exception handled: {demo.exception_handled}")
    print(f"  Exception type: {demo.exception_type}")
    print("=" * 60)


def demo_nested_try_catch():
    """
    Demonstrate nested try-catch blocks.
    """
    print("\nDemo 3: Nested Try-Catch")
    print("=" * 60)

    demo = TryCatchDemo()
    demo.setup_try_block()

    # Enter outer try block
    demo.enter_try_block()
    print(f"  Outer try level: {demo.rpa.get_level_depth()}")

    # Set up inner try block
    inner_config = LevelConfig(
        execution_addr=0x1500,
        exception_vector=0x2500,  # Inner catch block
        page_table=INHERIT,
        params={"block_type": "inner_try"}
    )
    level1 = demo.rpa.current
    demo.rpa.configure_sublayer(level1, inner_config)

    # Enter inner try block
    demo.rpa.descend(LevelConfig(
        execution_addr=0x1500,
        params={"operation": "inner_try_enter"}
    ))
    print(f"  Inner try level: {demo.rpa.get_level_depth()}")

    # Throw from inner block - simulate via handler
    print("  [TRY] Throwing from inner block...")
    fault_info = FaultInfo(
        fault_type="div_by_zero",
        layer=demo.rpa.current.level_id,
        address=0xCAFEBABE
    )
    demo.handle_div_by_zero(fault_info)

    # Return from inner block
    demo.rpa.return_to_parent({"exception": "div_by_zero"})
    print(f"  Back to outer try level: {demo.rpa.get_level_depth()}")

    print(f"  Exception handled: {demo.exception_handled}")
    print(f"  Exception type: {demo.exception_type}")
    print("=" * 60)


def demo_exception_propagation():
    """
    Demonstrate exception propagation to parent when not caught.
    """
    print("\nDemo 4: Exception Propagation to Parent")
    print("=" * 60)

    demo = TryCatchDemo()
    demo.setup_try_block()

    # Set up a sublayer without exception handler at root level
    no_handler_config = LevelConfig(
        execution_addr=0x3000,
        exception_vector=0,  # No exception handler!
        page_table=INDEPENDENT,  # Use independent to show it's isolated
        params={"block_type": "no_handler"}
    )
    demo.rpa.configure_sublayer(demo.rpa.root, no_handler_config)

    # Enter the sublayer (use sub_index=1 for the no_handler config)
    demo.rpa.descend(LevelConfig(
        execution_addr=0x3000,
        params={"operation": "no_handler_enter"},
        sub_index=1  # The no_handler config is at index 1
    ))
    print(f"  Current level: {demo.rpa.get_level_depth()}")

    # Trigger fault - should propagate to parent
    print("  [TRY] Throwing exception without handler...")
    try:
        # The fault will try to propagate but fail because root has no parent
        demo.rpa.fault("bus_error", address=0xBADC0DE)
    except RuntimeError as e:
        print(f"  [PROPAGATE] Fault propagated to root: {e}")

    print("=" * 60)


def demo_escalate_for_service():
    """
    Demonstrate using escalate() for exception handling service.
    """
    print("\nDemo 5: Escalate for Service During Exception")
    print("=" * 60)

    rpa = RPACore()

    # Root has a service handler
    def service_handler(params):
        print(f"  [SERVICE] Root received request: {params}")
        return {"status": "granted", "resource": "memory_page_42"}

    # Set up a service provider sublayer at root
    service_config = LevelConfig(
        execution_addr=0x8000,
        exception_vector=0x8004,
        page_table=INHERIT,
        params={"type": "service_provider"}
    )
    rpa.configure_sublayer(rpa.root, service_config)

    # Descend into service sublayer
    rpa.descend(LevelConfig(
        execution_addr=0x8000,
        params={"client": "application"}
    ))
    rpa.current.context["service_handler"] = service_handler

    print(f"  Application level: {rpa.get_level_depth()}")

    # Application requests service via escalate
    print("  [APP] Requesting memory allocation...")
    result = rpa.escalate(LevelConfig(
        execution_addr=0,
        params={"type": "alloc_memory", "size": 4096}
    ))
    print(f"  [APP] Received: {result}")

    # Return to root
    rpa.return_to_parent({"result": "done"})
    print(f"  Back at root level: {rpa.get_level_depth()}")

    print(f"\nStatistics: {rpa.get_stats()}")
    print("=" * 60)


def main():
    print("\n" + "=" * 60)
    print("RPA Try-Catch Demonstration")
    print("=" * 60)

    demo_successful_try()
    demo_caught_exception()
    demo_nested_try_catch()
    demo_exception_propagation()
    demo_escalate_for_service()

    print("\n" + "=" * 60)
    print("All demonstrations complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()