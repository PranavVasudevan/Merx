"""BankLens ingestion — reference connectors for the Bronze layer.

Phase 1 uses this Python package as the *reference implementation* of the
connector pattern (fetch -> provenance -> land raw in Bronze). The production
connector SDK is planned in Rust under ``services/ingestion`` (see the master
architecture plan). Keeping a small, dependency-free Python version here lets us
learn the data and validate metrics before investing in the Rust rewrite.
"""

__version__ = "0.1.0"
