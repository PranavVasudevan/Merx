//! FDIC BankFind Suite connector (Bronze) — Rust port of
//! `pipelines/ingestion/src/banklens_ingestion/sources/fdic.py`.
//!
//! Docs: <https://banks.data.fdic.gov/docs/> (public REST API, no auth
//! required). Same politeness discipline as the Python reference: an
//! identifying User-Agent, a per-request delay, and bounded retries with
//! exponential backoff.
//!
//! FDIC financial amounts are reported in **thousands of USD**; unit
//! normalisation happens in the Silver layer (Python, unchanged), not here —
//! Bronze stays raw, byte-for-byte what the API returned.

use serde_json::Value;
use std::time::Duration;

const API_ROOT: &str = "https://banks.data.fdic.gov/api";

/// Same curated field set as fdic.py's FINANCIAL_FIELDS — verified live
/// against the FDIC API there; kept identical here rather than re-verified,
/// since it's the same API contract.
pub const FINANCIAL_FIELDS: &[&str] = &[
    "CERT", "REPDTE", "NAMEFULL", "STALP", "ASSET",
    "NAMEHCR", "RSSDHCR", "RSSDID",
    "DEP", "DEPDOM", "DEPINS", "DEPUNINS", "COREDEP",
    "LNLSGR", "LNLSNET",
    "LNRE", "LNRECONS", "LNREMULT", "LNRENRES", "LNRELOC", "LNRERES", "LNREAG",
    "LNAG", "LNCI", "LNCON", "LNCRCD", "LNAUTO", "LNCONOTH",
    "SC", "SCAF", "SCHA",
    "EQ", "RBCT1J", "RBC", "RWAJT", "ASSET5", "CHBAL",
    "IDT1CER", "IDT1RWAJR", "RBCRWAJ", "RBC1AAJ", "EQV", "LNLSDEPR",
];

pub const INSTITUTION_FIELDS: &[&str] = &["NAME", "CERT", "STALP", "CITY", "ACTIVE", "ASSET", "DEP", "ESTYMD"];

pub struct FdicSource {
    client: reqwest::Client,
    timeout: Duration,
    delay: Duration,
    max_retries: u32,
}

pub const NAME: &str = "fdic.bankfind";
pub const LICENSE: &str = "public-domain-us-gov";

impl FdicSource {
    pub fn new() -> Self {
        let client = reqwest::Client::builder()
            .cookie_store(true) // the CDN/WAF's redirect+cookie challenge needs this — same finding as fdic.py
            .user_agent("BankLens/0.1 (data pipeline, Rust; contact you@example.org)")
            .build()
            .expect("reqwest client build");
        FdicSource { client, timeout: Duration::from_secs(30), delay: Duration::from_millis(400), max_retries: 4 }
    }

    async fn get(&self, endpoint: &str, params: &[(&str, String)]) -> Result<(Value, String), String> {
        let url = format!("{API_ROOT}/{endpoint}");
        let mut last_err = String::new();
        for attempt in 1..=self.max_retries {
            let resp = tokio::time::timeout(
                self.timeout,
                self.client.get(&url)
                    .query(params)
                    .header("Accept", "application/json, text/plain, */*")
                    .header("Accept-Language", "en-US,en;q=0.9")
                    .send(),
            ).await;
            match resp {
                Ok(Ok(r)) if r.status().is_success() => {
                    let full_url = r.url().to_string();
                    match r.json::<Value>().await {
                        Ok(body) => {
                            tokio::time::sleep(self.delay).await; // be a good citizen
                            return Ok((body, full_url));
                        }
                        Err(e) => last_err = format!("body decode failed: {e}"),
                    }
                }
                Ok(Ok(r)) => last_err = format!("HTTP {}", r.status()),
                Ok(Err(e)) => last_err = e.to_string(),
                Err(_) => last_err = "request timed out".to_string(),
            }
            tokio::time::sleep(self.delay * 2u32.pow(attempt)).await; // exponential backoff
        }
        Err(format!("FDIC request failed after {} retries: {url} ({last_err})", self.max_retries))
    }

    fn unwrap_rows(payload: &Value) -> Vec<Value> {
        payload.get("data").and_then(|d| d.as_array())
            .map(|rows| rows.iter().map(|row| row.get("data").cloned().unwrap_or(Value::Null)).collect())
            .unwrap_or_default()
    }

    /// The most recent `quarters` financial records for a bank, newest-first
    /// (mirrors fdic.py's `fetch()`).
    pub async fn fetch(&self, cert: i64, quarters: u32) -> Result<Vec<Value>, String> {
        let params = [
            ("filters", format!("CERT:{cert}")),
            ("fields", FINANCIAL_FIELDS.join(",")),
            ("sort_by", "REPDTE".to_string()),
            ("sort_order", "DESC".to_string()),
            ("limit", quarters.to_string()),
        ];
        let (payload, url) = self.get("financials", &params).await?;
        let mut rows = Self::unwrap_rows(&payload);
        for row in &mut rows {
            if let Some(obj) = row.as_object_mut() {
                obj.insert("_source_url".to_string(), Value::String(url.clone()));
            }
        }
        Ok(rows)
    }
}

impl Default for FdicSource {
    fn default() -> Self { Self::new() }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    /// Hermetic — no network. Live-API tests are kept separate and opt-in,
    /// same convention as pipelines/ingestion/tests/test_fdic.py.
    #[test]
    fn unwrap_rows_extracts_the_inner_data_envelope() {
        let payload = json!({"data": [
            {"data": {"CERT": 3511, "ASSET": 1}, "score": {}},
            {"data": {"CERT": 3511, "ASSET": 2}, "score": {}},
        ]});
        let rows = FdicSource::unwrap_rows(&payload);
        assert_eq!(rows, vec![json!({"CERT": 3511, "ASSET": 1}), json!({"CERT": 3511, "ASSET": 2})]);
    }

    #[test]
    fn unwrap_rows_empty_data_is_empty() {
        assert_eq!(FdicSource::unwrap_rows(&json!({"data": []})), Vec::<Value>::new());
    }

    #[test]
    fn unwrap_rows_missing_data_key_is_empty() {
        assert_eq!(FdicSource::unwrap_rows(&json!({})), Vec::<Value>::new());
    }
}
