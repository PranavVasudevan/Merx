"""BankLens transforms — Bronze -> Silver -> Gold reference implementation.

Phase 1 uses Python here so we can *see and validate the math* by hand. Phases
2+ move these transforms to dbt + PySpark for scale and testability, but the
canonical definitions live here first and the dbt models must reproduce them.
"""

__version__ = "0.1.0"
