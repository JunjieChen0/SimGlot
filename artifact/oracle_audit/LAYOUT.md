# Why this directory is flat

The files here sit directly in `artifact/oracle_audit/` rather than in `detectors/` and
`fault_injection/` subdirectories. That is not an oversight — `oracle_audit_kit` is an **importable
Python package**, and its modules import each other by package path:

```python
from oracle_audit_kit.adapters import TARGETS, Target
from oracle_audit_kit.detectors import DETECTOR_ORDER, run_all
from oracle_audit_kit.oracle_variants import reset_state
```

Moving `adapters.py` into a `detectors/` subdirectory breaks every one of those imports, and the
suite stops running. A directory layout that reads well but does not execute would be worse than one
that is slightly less tidy — especially in an artifact whose whole claim is that its code runs.

**These files are byte-identical to the archived originals.** Nothing was patched to fit this
repository; where the repository layout differs from the original working tree, `reproduce.sh`
reconstructs the original layout in a scratch directory instead. See
[`../../docs/reproduction.md`](../../docs/reproduction.md).

## What each file is

| File | Role |
|---|---|
| `__init__.py` | package marker |
| `_paths.py` | offline bootstrap: puts the vendored benchmark and the v1.0 harness on `sys.path`, and borrows `_offline.py` (network ban, disabled stubs for absent model clients) |
| `adapters.py` | the four-operation target interface every check is written against, plus the target registry |
| `detectors.py` | the eight checks: INV-1 … INV-5 and CTL-1 … CTL-3 |
| `oracle_variants.py` | the seven injected defect classes and the reference (as-shipped) variant |
| `run_audit.py` | the driver: runs the defect-class × detector matrix and writes the report |
| `verify_baseline_identity.py` | confirms which implementation the un-injected baseline actually is |
| `README.md` | the suite's own documentation, from the archived original |

## Where the rest of the fault-injection battery is

The **twenty-one held-out variants** and the **differential probes** that decide whether a variant is
detectable at all are not part of this package — they belong to the later round and live in
[`../holdout/`](../holdout/). That directory *is* a Python package, and its name is fixed for the
same reason: the gate scripts import it as `from holdout import ...`.
