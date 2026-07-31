//! BankLens Bronze-layer connectors (Rust) — see README.md for exact scope:
//! this ports the FDIC BankFind connector only (not SEC/Tiingo/SOD, which
//! stay Python-only for now), landing to the identical Bronze partition
//! layout the Python reference uses so either engine's output is a drop-in
//! for the other.

pub mod bronze;
pub mod provenance;
pub mod sources;
