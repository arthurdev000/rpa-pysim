# Confidential Domain Destruction Routine Design

## Concept

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Security Request Flow                             │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│   Caller Domain (P)                Security Subsystem                │
│   ┌─────────────┐                  ┌─────────────────┐              │
│   │             │  1. Request      │                 │              │
│   │  Parent of  │ ──────────────▶  │  SecurityGroup  │              │
│   │  Confidential│                 │  Controller     │              │
│   │  Child (C)  │                  │                 │              │
│   │             │                  └────────┬────────┘              │
│   └─────────────┘                           │                       │
│                                             │ 2. Query hierarchy     │
│                                             ▼                       │
│   ┌─────────────┐                  ┌─────────────────┐              │
│   │   Root      │  3. Return info  │                 │              │
│   │   Domain    │ ◀─────────────── │   RPALogic      │              │
│   │   (id=0)    │                  │   (root layer)  │              │
│   └─────────────┘                  └─────────────────┘              │
│         │                                                            │
│         │ 4. Root holds:                                               │
│         │    - Core context (domain registry)                         │
│         │    - Root trust (root domain info)                          │
│         │    - Domain hierarchy (parent chain)                        │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

## Design Rationale

### Why Security Subsystem as First Entry Point?

1. **Layer Efficiency**: RPA architecture has many layers. If each layer reports up, hardware needs more logic; software kernels need more code.

2. **Centralized Policy**: Security subsystem handles ALL security policy decisions. This avoids policy scatter across layers.

3. **Visibility**: Unlike separated TPM, security subsystem can observe chip actions directly.

4. **Process-Level Granularity**: Confidential/security domains are process-level entities, not function-level.

### Why Only Parent-Child Verification?

1. **Simplicity**: For proof-of-concept simulation, we only need to verify logical relationships, not implement actual cryptography.

2. **Trust Chain**: Parent-child relationship is the core of RPA privilege delegation. If caller is direct parent, it has authority over child.

3. **Root Layer as Truth**: Root layer maintains complete domain hierarchy. Security subsystem queries root layer for authoritative information.

## Implementation

### 1. RPALogic Extensions

```python
# In rpa_logic.py

def get_domain_hierarchy(self) -> Dict[int, Dict[str, Any]]:
    """
    Get domain hierarchy information from root layer.

    Returns:
        Dict mapping domain_id to:
        - "parent_id": parent domain ID (None for root)
        - "block_addr": DomainBlock address
        - "security_group": bound security group handle
    """
    ...

def verify_parent_child(self, parent_id: int, child_id: int) -> bool:
    """
    Verify parent-child relationship.

    Args:
        parent_id: Claimed parent domain ID
        child_id: Target child domain ID

    Returns:
        True if parent_id is the direct parent of child_id
    """
    ...

def get_domain_by_id(self, domain_id: int) -> Optional[Domain]:
    """Get domain object by ID."""
    ...
```

### 2. SecurityGroupController Extensions

```python
# In security_group.py

def request_destroy_confidential(
    self,
    handle: int,
    caller_domain_id: int,
    rpa_logic: 'RPALogic'
) -> Tuple[bool, str]:
    """
    Request destruction of a confidential domain.

    Flow:
    1. Security subsystem receives request
    2. Queries root layer (via RPALogic) for hierarchy
    3. Verifies caller is direct parent of confidential domain
    4. Executes destroy if authorized

    Args:
        handle: Security group handle to destroy
        caller_domain_id: Domain ID of the caller (claiming to be parent)
        rpa_logic: RPALogic instance for hierarchy query

    Returns:
        (success, message) tuple
    """
    ...

def is_confidential_domain(self, domain_id: int) -> bool:
    """Check if a domain is confidential."""
    ...
```

## Test Scenario

```
Root Domain (id=0, security_group=1)
    │
    ├── VM Manager Domain (id=1, security_group=2)
    │       │
    │       └── Confidential VM (id=2, security_group=3, is_confidential=True)
    │
    └── Malicious Domain (id=3, security_group=4)

Scenario 1: Valid Destruction
  - Caller: VM Manager (id=1)
  - Target: Confidential VM (id=2, security_group=3)
  - Result: SUCCESS (id=1 is parent of id=2)

Scenario 2: Unauthorized Destruction
  - Caller: Malicious Domain (id=3)
  - Target: Confidential VM (id=2, security_group=3)
  - Result: DENIED (id=3 is not parent of id=2)

Scenario 3: Root Override
  - Caller: Root (id=0)
  - Target: Confidential VM (id=2, security_group=3)
  - Result: SUCCESS (root can destroy any)
```

## Security Considerations

1. **No Crypto Required**: This is proof-of-concept simulation. Real implementation would add attestation and signatures.

2. **Root Trust**: Root layer holds authoritative hierarchy. Security subsystem must query root layer, not trust caller's claim.

3. **Process-Level**: Confidential domains are process-level, not function-level. Cross-domain communication requires IPC or exception/interrupt mechanism.

4. **Interrupt-Based Access**: Most efficient mechanism for cross-domain access is security exception/interrupt, not direct function call.