# RPA-PySim

Executable specification and proof-of-concept simulator for the [Recursive Privilege Architecture (RPA)](#).

[中文文档](README_zh.md)

## Overview

RPA-PySim is an **executable specification** for the Recursive Privilege Architecture, designed to:

1. **Verify semantics**: 90+ test cases prove the correctness of RPA primitives
2. **Document the design**: Code as specification — precisely describes RPA primitive behavior
3. **Enable reproducible research**: Supports independent verification and follow-up studies

> **Note**: This project is **not** a cycle-accurate simulator. For performance evaluation, use tools like gem5.

## Key Features

- **RPA Primitives**: `DESCEND`, `ASCEND`, `RETURN`, `EXIT`
- **DomainBlock**: 32-byte control structure with parent/child ownership model
- **Page Table Stacking**: Multi-level address translation with chain walking
- **IPA Boundary Checking**: Hardware-enforced memory isolation between domains
- **Security Groups**: Encryption, DMA access control, and confidential domain support
- **Interrupt Controller**: Priority-based interrupt handling with domain isolation

## Quick Start

### Installation

```bash
pip install -r requirements.txt
```

### Example

```python
from rpa_sim import RPALogic, DomainBlock, Memory, SimpleISA

# Create RPA core and memory
mem = Memory(size=64 * 1024)
rpa = RPALogic()
rpa.memory = mem

# Set up child domain control block
block_addr = 0x1000
mem.write_word(block_addr + 0x00, 32)      # ctrlblock_size
mem.write_word(block_addr + 0x10, 0)       # ipa_regions
mem.write_word(block_addr + 0x2C, 0x2000)  # saved_lr (entry point)

# Create ISA core and execute
core = SimpleISA(rpa=rpa, memory=mem)
core.load_assembly("MOV R0, #0x1000\nDESCEND R0", base_addr=0)
core.run()
```

## RPA Primitives

| Instruction | Description |
|-------------|-------------|
| `DESCEND Rn` | Enter child domain; Rn = child control block address |
| `ASCEND Rn` | Request parent service; Rn = service type |
| `RETURN Rn` | Return from parent to child; Rn = child control block address |
| `EXIT Rn` | Exit child domain and release resources; Rn = 0 |

## DomainBlock Layout

RPA Spec Field (fixed 8 words, 32 bytes):

| Offset | Field | Set by | Description |
|--------|-------|--------|-------------|
| 0x00 | ctrlblock_size | Parent | Control block size (in words, minimum 8) |
| 0x04 | domain_id | System | Domain ID (used for DMA access control) |
| 0x08 | trap_vector | Child | Trap handler entry (0 = propagate to parent) |
| 0x0C | interrupt_ctrl | System | Interrupt controller handle |
| 0x10 | ipa_regions | Parent | IPA region table address (child read-only) |
| 0x14 | pagetable | Child | Page table address (child writable) |
| 0x18 | child_block | Parent | Child control block address (parent maintained) |
| 0x1C | security_group | System | Security group handle |

ISA Context Field (platform-specific, immediately follows RPA Spec Field): defined by each ISA implementation.

## Project Structure

```
rpa-pysim/
├── rpa_sim/              # Core simulator
│   ├── __init__.py       # Package exports
│   ├── rpa_logic.py      # RPA core primitives
│   ├── isa_simple.py     # Simplified ISA interpreter
│   ├── memory.py         # Memory and page table management
│   ├── machine.py        # Full machine integration
│   ├── security_group.py # Security group mechanism
│   ├── interrupt.py      # Interrupt controller
│   └── stdio.py          # Console I/O device
├── tests/                # Unit tests (90+ test cases)
│   ├── test_rpa.py       # RPA core tests
│   ├── test_isa_simple.py # ISA tests
│   ├── test_security_group.py # Security group tests
│   └── test_thread_exception.py # Thread/exception tests
├── docs/                 # Documentation
│   ├── CONTROL_BLOCK_SPEC.md # DomainBlock specification
│   ├── SECURITY_GROUP_SPEC.md # Security group specification
│   ├── IMPLEMENTATION_GUIDE.md # Implementation guide
│   └── CONFIDENTIAL_DESTROY_DESIGN.md # Confidential domain destruction
├── LICENSE               # MIT License
├── pyproject.toml        # Project configuration
├── requirements.txt
└── README.md
```

## Testing

```bash
# Run all tests
python -m pytest tests/ -v

# Generate coverage report
python -m pytest tests/ --cov=rpa_sim --cov-report=html
```

### Test Coverage

| Module | Coverage |
|--------|----------|
| `test_rpa.py` | Domain operations (descend/ascend/return/exit), page table translation, IPA boundary checking |
| `test_isa_simple.py` | ISA instruction execution, memory translation, interrupt handling |
| `test_security_group.py` | Security group creation, attestation verification, encrypted memory, DMA access control |
| `test_thread_exception.py` | Thread exception handling, multi-level translation, fault handling |

## Citation

If you use this project in academic research, please cite:

```bibtex
@software{rpa-pysim2025,
  author = {Liu, Yongkang},
  title = {RPA-PySim: Executable Specification for Recursive Privilege Architecture},
  year = {2025},
  publisher = {GitHub},
  url = {https://github.com/arthurdev000/rpa-pysim}
}
```

## Documentation

- `docs/CONTROL_BLOCK_SPEC.md` — DomainBlock detailed specification
- `docs/SECURITY_GROUP_SPEC.md` — Security group mechanism specification
- `docs/IMPLEMENTATION_GUIDE.md` — Implementation guide
- `docs/CONFIDENTIAL_DESTROY_DESIGN.md` — Confidential domain destruction design
- `notes.md` — Design notes

## License

MIT License — see [LICENSE](LICENSE)

## Acknowledgments

AI assisted by GLM5.
