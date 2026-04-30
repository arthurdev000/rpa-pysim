"""
Nested Virtualization Example

Demonstrates multi-level descend/escalate for nested virtualization:
- Level 0: Host OS
- Level 1: Guest VM (running a simple "kernel")
- Level 2: Nested Guest VM

This shows how RPA naturally handles nested virtualization without
the complexity of traditional nested page tables.
"""

import sys
sys.path.insert(0, '..')

from rpa_sim import RPACore, Level, LevelConfig, INHERIT


def setup_nested_virtualization():
    """
    Set up a nested virtualization scenario with 3 levels.

    Level 0 (Host):
        - Owns physical memory
        - Configures VM1 as sublayer

    Level 1 (Guest VM):
        - Owns virtualized physical memory
        - Configures Nested VM as sublayer

    Level 2 (Nested Guest):
        - Owns nested virtual memory
        - Can escalate to VM1 for I/O
    """
    rpa = RPACore()

    # Host (Level 0) configures Guest VM (Level 1)
    guest_config = LevelConfig(
        execution_addr=0x8000,           # Guest kernel entry point
        exception_vector=0x8004,         # Guest exception handler
        page_table=0x10000,              # Guest has independent page table
        params={"name": "Guest VM 1", "memory_size": 1024 * 1024}
    )
    rpa.configure_sublayer(rpa.root, guest_config)

    # Descend into Guest VM
    print("=== Host -> Guest VM ===")
    result = rpa.descend(LevelConfig(
        execution_addr=0x8000,
        params={"operation": "start", "vcpu_id": 0}
    ))
    print(f"  Descended to Level {rpa.get_level_depth()}")
    print(f"  Entry: {result['entry']:#x}")

    # Guest VM (Level 1) configures Nested Guest (Level 2)
    nested_config = LevelConfig(
        execution_addr=0x4000,           # Nested guest entry point
        exception_vector=0x4004,
        page_table=INHERIT,              # Share Guest's page table (trust relationship)
        params={"name": "Nested VM", "memory_size": 512 * 1024}
    )
    level1 = rpa.current
    rpa.configure_sublayer(level1, nested_config)

    # Descend into Nested Guest
    print("\n=== Guest VM -> Nested Guest ===")
    result = rpa.descend(LevelConfig(
        execution_addr=0x4000,
        params={"operation": "start", "vcpu_id": 0}
    ))
    print(f"  Descended to Level {rpa.get_level_depth()}")
    print(f"  Entry: {result['entry']:#x}")

    return rpa


def demonstrate_escalation(rpa):
    """
    Demonstrate escalation from nested guest to guest VM.
    """
    print("\n=== Nested Guest -> Guest VM (Escalate) ===")

    # Nested Guest requests I/O service from Guest VM
    io_request = {
        "type": "disk_read",
        "sector": 100,
        "buffer": 0x1000,
        "size": 512
    }

    result = rpa.escalate(LevelConfig(
        execution_addr=0,
        params=io_request
    ))
    print(f"  Escalated from Level {rpa.current.level_id - 1}")
    print(f"  Result: {result}")

    # Guest VM handles and returns (simulated - we're still at Level 2)
    print("\n=== Guest VM handles I/O request ===")
    print(f"  Handling disk_read: sector={io_request['sector']}, size={io_request['size']}")
    # Note: In a real implementation, Guest VM would handle this
    # For demonstration, we just return to Level 1
    rpa.return_to_parent({"status": "completed", "bytes_read": 512})
    print(f"  Returned to Level {rpa.get_level_depth()}")


def demonstrate_fault_propagation(rpa):
    """
    Demonstrate fault propagation from nested guest to host.
    """
    print("\n=== Fault Propagation Test ===")

    # RPA is already at Level 2 (Nested Guest) from setup
    print(f"  Current Level: {rpa.get_level_depth()}")

    # Trigger a fault at Level 2
    print("  Triggering fault at Level 2...")
    try:
        rpa.fault("bus_error", address=0xDEADBEEF)
    except RuntimeError as e:
        print(f"  Fault propagated to root: {e}")


def main():
    print("=" * 60)
    print("RPA Nested Virtualization Demonstration")
    print("=" * 60)

    # Setup
    rpa = setup_nested_virtualization()

    # Show current state
    print(f"\nCurrent level depth: {rpa.get_level_depth()}")
    print(f"Current level ID: {rpa.current.level_id}")

    # Escalate back up
    demonstrate_escalation(rpa)

    # Return to root
    print("\n=== Returning to Host ===")
    while rpa.current.parent is not None:
        rpa.return_to_parent({"reason": "shutdown"})
        print(f"  Returned to Level {rpa.get_level_depth()}")

    # Show statistics
    print("\n=== Statistics ===")
    stats = rpa.get_stats()
    print(f"  Descend count: {stats['descend_count']}")
    print(f"  Escalate count: {stats['escalate_count']}")

    # Fault propagation test
    rpa2 = setup_nested_virtualization()
    demonstrate_fault_propagation(rpa2)

    print("\n" + "=" * 60)
    print("Demonstration complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()