"""
Tests for Heterogeneous ISA Support

These tests verify RPA's ability to support domains with different ISAs,
such as ARM and x86-64 running in the same system.
"""

import pytest
from rpa_sim import (
    RPALogic, Domain, DomainBlock, Memory, SimpleISA, MemoryManager,
    ISA_TAG_INHERIT, ISA_TAG_ARM, ISA_TAG_RISCV, ISA_TAG_X86, ISA_TAG_IBMZ,
    OFFSET_ISA_TAG, OFFSET_CONTROL_BLOCK_SIZE, OFFSET_IPA_REGIONS,
)
from rpa_sim.isa_simple import SAVED_LR_OFFSET


class TestISATag:
    """Tests for ISA tag field in DomainBlock"""

    def test_isa_tag_constants(self):
        """Verify ISA tag constants are defined correctly"""
        assert ISA_TAG_INHERIT == 0x0000
        assert ISA_TAG_ARM == 0x0001
        assert ISA_TAG_RISCV == 0x0002
        assert ISA_TAG_X86 == 0x0003
        assert ISA_TAG_IBMZ == 0x0004

    def test_domainblock_has_isa_tag(self):
        """DomainBlock should have isa_tag field"""
        block = DomainBlock(isa_tag=ISA_TAG_X86)
        assert block.isa_tag == ISA_TAG_X86

    def test_domainblock_default_isa_inherit(self):
        """Default isa_tag should be INHERIT (0)"""
        block = DomainBlock()
        assert block.isa_tag == ISA_TAG_INHERIT


class TestISATagInheritance:
    """Tests for ISA tag inheritance during descend"""

    def test_inherit_isa_from_parent_arm(self):
        """Child domain should inherit ARM ISA from parent when isa_tag=0"""
        mem = Memory(size=64 * 1024)
        rpa = RPALogic()
        rpa.memory = mem

        # Set root domain ISA to ARM
        root_block = rpa.root_domain.block
        root_block.isa_tag = ISA_TAG_ARM
        mem.write_word(rpa.root_domain.block_addr + OFFSET_ISA_TAG, ISA_TAG_ARM)

        # Create child with isa_tag=0 (inherit)
        child_addr = 0x1000
        mem.write_word(child_addr + OFFSET_CONTROL_BLOCK_SIZE, 32)
        mem.write_word(child_addr + OFFSET_IPA_REGIONS, 0)
        mem.write_word(child_addr + SAVED_LR_OFFSET, 0x2000)
        mem.write_word(child_addr + OFFSET_ISA_TAG, ISA_TAG_INHERIT)

        # Descend should resolve INHERIT to ARM
        result = rpa.descend(child_addr)

        # Verify child now has ARM ISA
        assert rpa.current_domain.block.isa_tag == ISA_TAG_ARM
        # Verify memory was updated
        assert mem.read_word(child_addr + OFFSET_ISA_TAG) == ISA_TAG_ARM

    def test_inherit_isa_from_parent_x86(self):
        """Child domain should inherit x86 ISA from parent when isa_tag=0"""
        mem = Memory(size=64 * 1024)
        rpa = RPALogic()
        rpa.memory = mem

        # Set root domain ISA to x86
        root_block = rpa.root_domain.block
        root_block.isa_tag = ISA_TAG_X86
        mem.write_word(rpa.root_domain.block_addr + OFFSET_ISA_TAG, ISA_TAG_X86)

        # Create child with isa_tag=0 (inherit)
        child_addr = 0x1000
        mem.write_word(child_addr + OFFSET_CONTROL_BLOCK_SIZE, 32)
        mem.write_word(child_addr + OFFSET_IPA_REGIONS, 0)
        mem.write_word(child_addr + SAVED_LR_OFFSET, 0x2000)
        mem.write_word(child_addr + OFFSET_ISA_TAG, ISA_TAG_INHERIT)

        # Descend should resolve INHERIT to x86
        result = rpa.descend(child_addr)

        # Verify child now has x86 ISA
        assert rpa.current_domain.block.isa_tag == ISA_TAG_X86

    def test_explicit_isa_not_overridden(self):
        """Child domain with explicit ISA should not be overridden"""
        mem = Memory(size=64 * 1024)
        rpa = RPALogic()
        rpa.memory = mem

        # Set root domain ISA to ARM
        root_block = rpa.root_domain.block
        root_block.isa_tag = ISA_TAG_ARM
        mem.write_word(rpa.root_domain.block_addr + OFFSET_ISA_TAG, ISA_TAG_ARM)

        # Create child with explicit x86 ISA
        child_addr = 0x1000
        mem.write_word(child_addr + OFFSET_CONTROL_BLOCK_SIZE, 32)
        mem.write_word(child_addr + OFFSET_IPA_REGIONS, 0)
        mem.write_word(child_addr + SAVED_LR_OFFSET, 0x2000)
        mem.write_word(child_addr + OFFSET_ISA_TAG, ISA_TAG_X86)  # Explicit x86

        # Descend
        result = rpa.descend(child_addr)

        # Child should keep x86 ISA (not inherit ARM)
        assert rpa.current_domain.block.isa_tag == ISA_TAG_X86


class TestNestedISATags:
    """Tests for ISA tag propagation in nested domains"""

    def test_multi_level_inheritance(self):
        """ISA should propagate through multiple levels"""
        mem = Memory(size=64 * 1024)
        rpa = RPALogic()
        rpa.memory = mem

        # Root domain: x86
        rpa.root_domain.block.isa_tag = ISA_TAG_X86
        mem.write_word(rpa.root_domain.block_addr + OFFSET_ISA_TAG, ISA_TAG_X86)

        # Domain 1: inherit (should become x86)
        child1_addr = 0x1000
        mem.write_word(child1_addr + OFFSET_CONTROL_BLOCK_SIZE, 32)
        mem.write_word(child1_addr + OFFSET_IPA_REGIONS, 0)
        mem.write_word(child1_addr + SAVED_LR_OFFSET, 0x2000)
        mem.write_word(child1_addr + OFFSET_ISA_TAG, ISA_TAG_INHERIT)

        rpa.descend(child1_addr)
        assert rpa.current_domain.block.isa_tag == ISA_TAG_X86

        # Domain 2: inherit (should also become x86)
        child2_addr = 0x2000
        mem.write_word(child2_addr + OFFSET_CONTROL_BLOCK_SIZE, 32)
        mem.write_word(child2_addr + OFFSET_IPA_REGIONS, 0)
        mem.write_word(child2_addr + SAVED_LR_OFFSET, 0x3000)
        mem.write_word(child2_addr + OFFSET_ISA_TAG, ISA_TAG_INHERIT)

        rpa.descend(child2_addr)
        assert rpa.current_domain.block.isa_tag == ISA_TAG_X86

    def test_mixed_isa_domains(self):
        """Test a system with mixed ISA domains"""
        mem = Memory(size=64 * 1024)
        rpa = RPALogic()
        rpa.memory = mem

        # Root domain: ARM
        rpa.root_domain.block.isa_tag = ISA_TAG_ARM
        mem.write_word(rpa.root_domain.block_addr + OFFSET_ISA_TAG, ISA_TAG_ARM)

        # Domain 1: inherit ARM
        child1_addr = 0x1000
        mem.write_word(child1_addr + OFFSET_CONTROL_BLOCK_SIZE, 32)
        mem.write_word(child1_addr + OFFSET_IPA_REGIONS, 0)
        mem.write_word(child1_addr + SAVED_LR_OFFSET, 0x2000)
        mem.write_word(child1_addr + OFFSET_ISA_TAG, ISA_TAG_INHERIT)

        rpa.descend(child1_addr)
        assert rpa.current_domain.block.isa_tag == ISA_TAG_ARM

        # Ascend back to root with release=True
        rpa.ascend(0, release=True)

        # Now we can create a new child domain
        # Domain 2: explicit x86 (different ISA!)
        child2_addr = 0x2000
        mem.write_word(child2_addr + OFFSET_CONTROL_BLOCK_SIZE, 32)
        mem.write_word(child2_addr + OFFSET_IPA_REGIONS, 0)
        mem.write_word(child2_addr + SAVED_LR_OFFSET, 0x3000)
        mem.write_word(child2_addr + OFFSET_ISA_TAG, ISA_TAG_X86)  # Explicit x86

        rpa.descend(child2_addr)
        assert rpa.current_domain.block.isa_tag == ISA_TAG_X86


class TestISAImplementation:
    """Tests for ISA abstraction layer"""

    def test_arm_isa_properties(self):
        """Test ARM ISA implementation"""
        from rpa_sim.isa import ARMISA

        arm = ARMISA()
        assert arm.name == "ARM"
        assert arm.isa_tag == ISA_TAG_ARM
        assert arm.word_size == 4
        # r0-r15 = 16 registers
        assert len(arm.registers) == 16

    def test_x86_isa_properties(self):
        """Test x86-64 ISA implementation"""
        from rpa_sim.isa import X86ISA

        x86 = X86ISA()
        assert x86.name == "x86-64"
        assert x86.isa_tag == ISA_TAG_X86
        assert x86.word_size == 8
        # RAX-R15 = 16 registers + RIP = 17
        assert len(x86.registers) == 17

    def test_arm_calling_convention(self):
        """Test ARM calling convention"""
        from rpa_sim.isa import ARMISA

        arm = ARMISA()
        cc = arm.calling_convention

        assert cc.arg_registers == ["r0", "r1", "r2", "r3"]
        assert cc.return_registers == ["r0", "r1"]
        assert "r4" in cc.callee_saved

    def test_x86_calling_convention(self):
        """Test x86-64 calling convention"""
        from rpa_sim.isa import X86ISA

        x86 = X86ISA()
        cc = x86.calling_convention

        assert cc.arg_registers == ["rdi", "rsi", "rdx", "rcx", "r8", "r9"]
        assert cc.return_registers == ["rax", "rdx"]
        assert "rbx" in cc.callee_saved

    def test_get_isa_by_tag(self):
        """Test ISA registry lookup"""
        from rpa_sim.isa import get_isa_by_tag, ARMISA, X86ISA

        arm = get_isa_by_tag(ISA_TAG_ARM)
        assert isinstance(arm, ARMISA)

        x86 = get_isa_by_tag(ISA_TAG_X86)
        assert isinstance(x86, X86ISA)

        with pytest.raises(ValueError, match="INHERIT"):
            get_isa_by_tag(ISA_TAG_INHERIT)

        with pytest.raises(ValueError, match="Unknown"):
            get_isa_by_tag(0xFFFF)


class TestCrossISAContextSwitch:
    """Tests for context switching between different ISAs"""

    def test_context_save_area_different_sizes(self):
        """Different ISAs have different context save area sizes"""
        from rpa_sim.isa import ARMISA, X86ISA

        arm = ARMISA()
        x86 = X86ISA()

        # ARM: SP + LR + PSR = 12 bytes
        assert arm.get_context_save_size() == 12

        # x86-64: RSP + RIP + RFLAGS = 24 bytes
        assert x86.get_context_save_size() == 24

    def test_arm_context_serialization(self):
        """Test ARM context serialization"""
        from rpa_sim.isa import ARMISA, ISAContext

        arm = ARMISA()
        ctx = ISAContext(
            registers={'sp': 0x1000, 'lr': 0x2000},
            pc=0x2000,
            sp=0x1000,
            flags={'n': True, 'z': False, 'c': True, 'v': False},
            isa_tag=ISA_TAG_ARM
        )

        data = arm.serialize_context(ctx)
        assert len(data) == 12

        # Deserialize
        ctx2 = arm.deserialize_context(data)
        assert ctx2.sp == 0x1000
        assert ctx2.flags['n'] == True
        assert ctx2.flags['z'] == False

    def test_x86_context_serialization(self):
        """Test x86-64 context serialization"""
        from rpa_sim.isa import X86ISA, ISAContext

        x86 = X86ISA()
        ctx = ISAContext(
            registers={'rsp': 0x10000, 'rip': 0x20000},
            pc=0x20000,
            sp=0x10000,
            flags={'c': True, 'z': False, 's': True, 'o': False},
            isa_tag=ISA_TAG_X86
        )

        data = x86.serialize_context(ctx)
        assert len(data) == 24

        # Deserialize
        ctx2 = x86.deserialize_context(data)
        assert ctx2.sp == 0x10000
        assert ctx2.flags['c'] == True
