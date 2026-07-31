//! Land raw records into the Bronze layer as partitioned JSON + a provenance
//! sidecar — Rust port of
//! `pipelines/ingestion/src/banklens_ingestion/bronze/writer.py`. Same layout,
//! same two files, so either engine's output is a drop-in for the other:
//! `data/bronze/source=<src>/cert=<cert>/records.json` + `_provenance.json`.
//!
//! Bronze is **append-only and immutable**: we never edit landed bytes, we
//! re-land.

use serde_json::Value;
use std::io;
use std::path::{Path, PathBuf};

use crate::provenance::Provenance;

pub fn write_bronze(
    records: &[Value], provenance: &Provenance, base_dir: &Path, source: &str, cert: i64,
) -> io::Result<PathBuf> {
    write_bronze_partitioned(records, provenance, base_dir, source, &format!("cert={cert}"))
}

/// Same landing logic as `write_bronze`, but for sources not naturally keyed
/// by a FDIC cert (e.g. the failed-bank-narrative scraper, keyed by URL slug —
/// cert correlation is a separate, later join against FDIC's own
/// `/api/failures` endpoint, not something Bronze needs to know about).
/// `partition` is the full `key=value` partition directory name.
pub fn write_bronze_partitioned(
    records: &[Value], provenance: &Provenance, base_dir: &Path, source: &str, partition: &str,
) -> io::Result<PathBuf> {
    let dir = base_dir.join(format!("source={source}")).join(partition);
    std::fs::create_dir_all(&dir)?;

    let records_path = dir.join("records.json");
    let prov_path = dir.join("_provenance.json");

    std::fs::write(&records_path, serde_json::to_string_pretty(records).unwrap())?;
    std::fs::write(&prov_path, serde_json::to_string_pretty(provenance).unwrap())?;
    Ok(records_path)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn writes_records_and_provenance_to_the_expected_partition_layout() {
        let tmp = std::env::temp_dir().join(format!("banklens_bronze_test_{}", std::process::id()));
        let records = vec![json!({"CERT": 3511, "ASSET": 100})];
        let prov = Provenance::create("fdic.bankfind", "https://example.test", "public-domain-us-gov", &records);

        let path = write_bronze(&records, &prov, &tmp, "fdic", 3511).unwrap();
        assert_eq!(path, tmp.join("source=fdic").join("cert=3511").join("records.json"));

        let read_back: Vec<Value> = serde_json::from_str(&std::fs::read_to_string(&path).unwrap()).unwrap();
        assert_eq!(read_back, records);

        let prov_path = tmp.join("source=fdic").join("cert=3511").join("_provenance.json");
        assert!(prov_path.exists());

        std::fs::remove_dir_all(&tmp).ok();
    }

    #[test]
    fn write_bronze_partitioned_uses_the_given_partition_name_not_cert() {
        let tmp = std::env::temp_dir().join(format!("banklens_bronze_slug_test_{}", std::process::id()));
        let records = vec![json!({"slug": "signature-ny", "title": "Signature Bank"})];
        let prov = Provenance::create("fdic.failures", "https://example.test", "public-domain-us-gov", &records);

        let path = write_bronze_partitioned(&records, &prov, &tmp, "fdic_failure_narrative", "slug=signature-ny").unwrap();
        assert_eq!(path, tmp.join("source=fdic_failure_narrative").join("slug=signature-ny").join("records.json"));
        assert!(path.exists());

        std::fs::remove_dir_all(&tmp).ok();
    }
}
