//! Provenance metadata attached to every Bronze record set — Rust port of
//! `pipelines/ingestion/src/banklens_ingestion/provenance.py`.
//!
//! Auditability is a first-class requirement (this is a bank). Every raw
//! landing carries where it came from, when, and a content checksum so
//! re-runs are idempotent and any downstream number is traceable to its
//! source bytes.
//!
//! Checksum note: `serde_json::Value`'s map type is a `BTreeMap` (this crate
//! does not enable the `preserve_order` feature), so `serde_json::to_string`
//! already sorts object keys and uses compact separators — matching Python's
//! `json.dumps(payload, sort_keys=True, separators=(",", ":"))` byte-for-byte
//! for the same decoded value. Not relied upon for cross-language equality
//! (float formatting can still differ) — only for this engine's own
//! fetch-is-idempotent guarantee.

use serde::Serialize;
use serde_json::Value;
use sha2::{Digest, Sha256};

pub fn sha256_of(payload: &Value) -> String {
    let raw = serde_json::to_string(payload).expect("Value always serializes");
    let mut hasher = Sha256::new();
    hasher.update(raw.as_bytes());
    format!("{:x}", hasher.finalize())
}

#[derive(Debug, Clone, Serialize)]
pub struct Provenance {
    pub source: String,
    pub endpoint: String,
    pub license: String,
    pub fetched_at: String,
    pub record_count: usize,
    pub checksum: String,
}

impl Provenance {
    pub fn create(source: &str, endpoint: &str, license: &str, records: &[Value]) -> Self {
        let payload = Value::Array(records.to_vec());
        Provenance {
            source: source.to_string(),
            endpoint: endpoint.to_string(),
            license: license.to_string(),
            fetched_at: chrono::Utc::now().to_rfc3339(),
            record_count: records.len(),
            checksum: sha256_of(&payload),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn checksum_is_deterministic_for_identical_payloads() {
        let a = json!([{"CERT": 3511, "ASSET": 100}]);
        let b = json!([{"CERT": 3511, "ASSET": 100}]);
        assert_eq!(sha256_of(&a), sha256_of(&b));
    }

    #[test]
    fn checksum_differs_for_different_payloads() {
        let a = json!([{"CERT": 3511, "ASSET": 100}]);
        let b = json!([{"CERT": 3511, "ASSET": 101}]);
        assert_ne!(sha256_of(&a), sha256_of(&b));
    }

    #[test]
    fn checksum_is_insensitive_to_key_order() {
        // BTreeMap-backed serde_json::Value sorts keys on serialize (see this
        // file's module doc) — verify that's actually true, not assumed.
        let a = json!({"b": 2, "a": 1});
        let b = json!({"a": 1, "b": 2});
        assert_eq!(sha256_of(&a), sha256_of(&b));
    }

    #[test]
    fn create_records_the_right_count_and_license() {
        let records = vec![json!({"CERT": 1}), json!({"CERT": 2}), json!({"CERT": 3})];
        let prov = Provenance::create("fdic.bankfind", "https://example.test", "public-domain-us-gov", &records);
        assert_eq!(prov.record_count, 3);
        assert_eq!(prov.source, "fdic.bankfind");
        assert_eq!(prov.license, "public-domain-us-gov");
        assert!(!prov.checksum.is_empty());
    }
}
