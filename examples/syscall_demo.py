"""
Fast System Call Example

Demonstrates how RPA's shared page table (INHERIT mode) enables
fast system calls without TLB flushes.

Traditional syscall:
    1. Save user context
    2. Switch to kernel mode
    3. Load kernel page table
    4. TLB flush (expensive!)
    5. Execute syscall
    6. Switch back to user page table
    7. TLB flush (expensive again!)
    8. Restore user context

RPA syscall with INHERIT:
    1. Save user context
    2. descend() to kernel sublayer
    3. Execute syscall (page tables shared, no TLB flush)
    4. return_to_parent()
    5. Restore user context
"""

import sys
sys.path.insert(0, '..')

from rpa_sim import RPACore, Level, SubConfig, INHERIT, INDEPENDENT


def setup_traditional_syscall():
    """
    Traditional syscall with independent page tables (slow).
    Each context switch requires TLB flush.
    """
    rpa = RPACore()

    # User process configures kernel sublayer with INDEPENDENT page table
    kernel_config = SubConfig(
        entry=0x80000000,        # Kernel entry point
        exception_vector=0x80000004,
        page_table=0x20000,      # Independent kernel page table
        params={"name": "Kernel (Traditional)", "mode": "slow"}
    )
    rpa.configure_sublayer(rpa.root, kernel_config)

    return rpa, "Traditional (Independent Page Table)"


def setup_rpa_fast_syscall():
    """
    RPA fast syscall with shared page tables (fast).
    No TLB flush needed on descend/escalate.
    """
    rpa = RPACore()

    # User process configures kernel sublayer with INHERIT page table
    kernel_config = SubConfig(
        entry=0x80000000,        # Kernel entry point
        exception_vector=0x80000004,
        page_table=INHERIT,      # Share user's page table!
        params={"name": "Kernel (RPA Fast)", "mode": "fast"}
    )
    rpa.configure_sublayer(rpa.root, kernel_config)

    return rpa, "RPA Fast (Shared Page Table)"


def simulate_syscall(rpa, name, syscall_num, args):
    """
    Simulate a system call through descend/escalate.
    """
    print(f"\n--- {name}: Syscall {syscall_num} ---")

    # Descend to kernel
    result = rpa.descend({
        "syscall_num": syscall_num,
        "args": args
    })
    print(f"  Descended to kernel (Level {rpa.get_level_depth()})")
    print(f"  Page table mode: {'INHERIT (shared)' if rpa.current.page_table == INHERIT else 'INDEPENDENT (flush needed)'}")

    # Simulate syscall execution
    syscall_results = {
        1: {"status": "success", "return_value": 42},      # getpid
        2: {"status": "success", "return_value": 1024},   # read
        3: {"status": "success", "return_value": 512},    # write
    }

    syscall_result = syscall_results.get(syscall_num, {"status": "unknown"})

    # Return to user
    rpa.return_to_parent(syscall_result)
    print(f"  Returned to user (Level {rpa.get_level_depth()})")
    print(f"  Result: {syscall_result}")

    return syscall_result


def benchmark_syscalls():
    """
    Compare syscall overhead between traditional and RPA approaches.
    """
    print("=" * 60)
    print("RPA Fast System Call Demonstration")
    print("=" * 60)

    print("\n### Traditional Syscall (Independent Page Tables) ###")
    print("Each syscall requires:")
    print("  - TLB flush on kernel entry")
    print("  - TLB flush on kernel exit")
    print("  - Estimated overhead: 100-500 cycles per flush")

    rpa_trad, name_trad = setup_traditional_syscall()

    # Simulate multiple syscalls
    for i in range(3):
        simulate_syscall(rpa_trad, name_trad, (i % 3) + 1, {"fd": 0, "buf": 0x1000})

    print(f"\nTraditional statistics: {rpa_trad.get_stats()}")

    print("\n" + "=" * 60)
    print("### RPA Fast Syscall (Shared Page Tables) ###")
    print("Each syscall requires:")
    print("  - descend() overhead: 1-3 cycles")
    print("  - No TLB flush!")
    print("  - return_to_parent() overhead: 1-3 cycles")
    print("  - Estimated total: 2-6 cycles vs 200-1000 cycles")

    rpa_fast, name_fast = setup_rpa_fast_syscall()

    # Simulate the same syscalls
    for i in range(3):
        simulate_syscall(rpa_fast, name_fast, (i % 3) + 1, {"fd": 0, "buf": 0x1000})

    print(f"\nRPA Fast statistics: {rpa_fast.get_stats()}")

    print("\n" + "=" * 60)
    print("Performance Comparison")
    print("=" * 60)
    print(f"Traditional TLB flushes: {rpa_trad.get_stats()['descend_count'] * 2} (2 per syscall)")
    print(f"RPA Fast TLB flushes: 0 (shared page tables)")
    print(f"\nSpeedup factor: ~100x for syscall overhead")
    print("=" * 60)


def main():
    benchmark_syscalls()


if __name__ == "__main__":
    main()