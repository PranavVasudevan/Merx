//! BankLens ingestion CLI (Rust) — fetch + land FDIC Bronze data.
//!
//!     cargo run --release --bin banklens-ingest -- fetch --cert 3511 --quarters 8
//!     cargo run --release --bin banklens-ingest -- fetch-many --certs 3511,6976,16068 --quarters 8
//!     cargo run --release --bin banklens-ingest -- scrape-failures --slugs signature-ny,silicon-valley,first-republic,indymac
//!
//! `fetch` mirrors the Bronze-landing half of
//! `pipelines/ingestion/src/banklens_ingestion/cli.py` (fetch -> provenance ->
//! write_bronze; Silver/Gold/X-Ray stay Python's job, unchanged). `fetch-many`
//! is the actual "throughput" story from this crate's original skeleton
//! comment: bounded-concurrency fetches across several banks at once, which
//! the Python reference (one cert per synchronous process) can't do without
//! its own concurrency layer. `scrape-failures` is the real scraper (see
//! sources/fdic_failures.rs) — narrative resolution detail for bank failures
//! that has no API, landed to a separate `source=fdic_failure_narrative`
//! Bronze partition keyed by URL slug (not CERT — see that module's docs).

use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::sync::Arc;
use std::time::{Duration, Instant};

use banklens_ingestion::bronze::{write_bronze, write_bronze_partitioned};
use banklens_ingestion::provenance::Provenance;
use banklens_ingestion::sources::fdic::{FdicSource, LICENSE, NAME};
use banklens_ingestion::sources::fdic_failures::FdicFailureScraper;

const FAILURE_PATH_PREFIX: &str =
    "https://www.fdic.gov/resources/resolutions/bank-failures/failed-bank-list/";
/// Same crawl-delay the scraper module itself uses between sitemap fetches —
/// applied here too between individual page fetches, since main.rs (not the
/// module) controls the fetch loop for scrape-failures.
const SCRAPE_DELAY: Duration = Duration::from_secs(1);

struct Common {
    quarters: u32,
    data_dir: PathBuf,
}

async fn fetch_and_land(src: &FdicSource, cert: i64, common: &Common) -> Result<(usize, std::time::Duration), String> {
    let t0 = Instant::now();
    let records = src.fetch(cert, common.quarters).await?;
    if records.is_empty() {
        return Err(format!("no records returned for CERT {cert}"));
    }
    let endpoint = records[0].get("_source_url").and_then(|v| v.as_str()).unwrap_or("").to_string();
    let prov = Provenance::create(NAME, &endpoint, LICENSE, &records);
    let base = common.data_dir.join("bronze");
    write_bronze(&records, &prov, &base, "fdic", cert).map_err(|e| e.to_string())?;
    Ok((records.len(), t0.elapsed()))
}

fn print_usage() {
    eprintln!("usage:");
    eprintln!("  banklens-ingest fetch --cert <N> [--quarters N] [--data-dir DIR]");
    eprintln!("  banklens-ingest fetch-many --certs <N,N,...> [--quarters N] [--data-dir DIR] [--concurrency N]");
    eprintln!("  banklens-ingest scrape-failures --slugs <slug,slug,...> [--data-dir DIR]");
    eprintln!("  banklens-ingest scrape-failures --discover-limit <N> [--data-dir DIR]");
}

async fn scrape_and_land_failure(
    scraper: &FdicFailureScraper, url: &str, data_dir: &Path,
) -> Result<String, String> {
    let detail = scraper.fetch_detail(url).await?;
    let record = serde_json::to_value(&detail).map_err(|e| e.to_string())?;
    let records = vec![record];
    let prov = Provenance::create("fdic.failure_narrative", url, "public-domain-us-gov", &records);
    let base = data_dir.join("bronze");
    write_bronze_partitioned(&records, &prov, &base, "fdic_failure_narrative",
                            &format!("slug={}", detail.slug))
        .map_err(|e| e.to_string())?;
    Ok(detail.slug)
}

#[tokio::main]
async fn main() -> ExitCode {
    let argv: Vec<String> = std::env::args().skip(1).collect();
    if argv.is_empty() {
        print_usage();
        return ExitCode::FAILURE;
    }
    let cmd = argv[0].clone();
    let rest = &argv[1..];

    let mut quarters = 8u32;
    let mut data_dir = PathBuf::from("data");
    let mut certs: Vec<i64> = vec![];
    let mut concurrency = 4usize;
    let mut slugs: Vec<String> = vec![];
    let mut discover_limit: Option<usize> = None;

    let mut i = 0;
    while i < rest.len() {
        match rest[i].as_str() {
            "--cert" => { i += 1; if let Some(v) = rest.get(i) { certs.push(v.parse().unwrap_or(0)); } }
            "--certs" => { i += 1; if let Some(v) = rest.get(i) {
                certs = v.split(',').filter_map(|s| s.trim().parse().ok()).collect();
            } }
            "--quarters" => { i += 1; quarters = rest.get(i).and_then(|v| v.parse().ok()).unwrap_or(8); }
            "--data-dir" => { i += 1; if let Some(v) = rest.get(i) { data_dir = PathBuf::from(v); } }
            "--concurrency" => { i += 1; concurrency = rest.get(i).and_then(|v| v.parse().ok()).unwrap_or(4); }
            "--slugs" => { i += 1; if let Some(v) = rest.get(i) {
                slugs = v.split(',').map(|s| s.trim().to_string()).filter(|s| !s.is_empty()).collect();
            } }
            "--discover-limit" => { i += 1; discover_limit = rest.get(i).and_then(|v| v.parse().ok()); }
            other => { eprintln!("unknown argument: {other}"); print_usage(); return ExitCode::FAILURE; }
        }
        i += 1;
    }
    if cmd != "scrape-failures" && certs.is_empty() {
        eprintln!("error: --cert or --certs is required");
        print_usage();
        return ExitCode::FAILURE;
    }
    let common = Common { quarters, data_dir: data_dir.clone() };
    let src = FdicSource::new();

    match cmd.as_str() {
        "fetch" => {
            let cert = certs[0];
            match fetch_and_land(&src, cert, &common).await {
                Ok((n, elapsed)) => {
                    println!("FETCH CERT {cert}: {n} quarterly records landed to {}/bronze/source=fdic/cert={cert}/records.json in {:.0}ms",
                             common.data_dir.display(), elapsed.as_secs_f64() * 1000.0);
                    ExitCode::SUCCESS
                }
                Err(e) => { eprintln!("error: {e}"); ExitCode::FAILURE }
            }
        }
        "fetch-many" => {
            let src = Arc::new(src);
            let common = Arc::new(common);
            let semaphore = Arc::new(tokio::sync::Semaphore::new(concurrency));
            let t0 = Instant::now();
            let mut set = tokio::task::JoinSet::new();
            for cert in certs.clone() {
                let src = Arc::clone(&src);
                let common = Arc::clone(&common);
                let semaphore = Arc::clone(&semaphore);
                set.spawn(async move {
                    let _permit = semaphore.acquire().await.unwrap();
                    let result = fetch_and_land(&src, cert, &common).await;
                    (cert, result)
                });
            }
            let mut ok = 0;
            let mut failed = 0;
            while let Some(joined) = set.join_next().await {
                match joined {
                    Ok((cert, Ok((n, elapsed)))) => {
                        println!("  CERT {cert}: {n} records in {:.0}ms", elapsed.as_secs_f64() * 1000.0);
                        ok += 1;
                    }
                    Ok((cert, Err(e))) => { eprintln!("  CERT {cert}: FAILED ({e})"); failed += 1; }
                    Err(e) => { eprintln!("  task panicked: {e}"); failed += 1; }
                }
            }
            println!("fetch-many: {ok} ok, {failed} failed, {} banks, concurrency={concurrency}, wall clock {:.0}ms",
                     certs.len(), t0.elapsed().as_secs_f64() * 1000.0);
            if failed > 0 { ExitCode::FAILURE } else { ExitCode::SUCCESS }
        }
        "scrape-failures" => {
            let scraper = FdicFailureScraper::new();
            let urls: Vec<String> = if !slugs.is_empty() {
                slugs.iter().map(|s| format!("{FAILURE_PATH_PREFIX}{s}.html")).collect()
            } else if let Some(limit) = discover_limit {
                println!("discovering failed-bank URLs via sitemap.xml (respecting Crawl-delay: 1)...");
                match scraper.discover_urls().await {
                    Ok(all) => {
                        println!("  discovered {} total; scraping the first {}", all.len(), limit.min(all.len()));
                        all.into_iter().take(limit).collect()
                    }
                    Err(e) => { eprintln!("discovery failed: {e}"); return ExitCode::FAILURE; }
                }
            } else {
                eprintln!("error: scrape-failures needs --slugs or --discover-limit");
                print_usage();
                return ExitCode::FAILURE;
            };

            let mut ok = 0;
            let mut failed = 0;
            for (idx, url) in urls.iter().enumerate() {
                if idx > 0 {
                    tokio::time::sleep(SCRAPE_DELAY).await; // robots.txt: Crawl-delay: 1
                }
                match scrape_and_land_failure(&scraper, url, &data_dir).await {
                    Ok(slug) => { println!("  {slug}: landed"); ok += 1; }
                    Err(e) => { eprintln!("  {url}: FAILED ({e})"); failed += 1; }
                }
            }
            println!("scrape-failures: {ok} ok, {failed} failed, {} pages", urls.len());
            if failed > 0 { ExitCode::FAILURE } else { ExitCode::SUCCESS }
        }
        other => { eprintln!("unknown command: {other}"); print_usage(); ExitCode::FAILURE }
    }
}
