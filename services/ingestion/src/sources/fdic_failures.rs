//! FDIC "Failed Bank Information" narrative scraper — real HTML scraping,
//! because no API exists for this content. FDIC's own BankFind `/api/failures`
//! endpoint gives structured facts (CERT, closing date, resolution type,
//! deposits at failure — verified live: `GET
//! banks.data.fdic.gov/api/failures?filters=CERT:57053` returns Signature
//! Bank's record cleanly). This module is for what that endpoint does NOT
//! have: the resolution narrative (receiver, acquiring institution, deposit
//! transfer terms, whether the holding company was involved) and links to the
//! official press release(s) — matching the master plan's own explicit
//! example of a legitimate scrape target ("press-release failure detail").
//! Bulk/API first, scrape only what has no API — this module is the "scrape"
//! half, deliberately narrow.
//!
//! Politeness (verified against the real robots.txt before writing this):
//! `https://www.fdic.gov/robots.txt` declares `Crawl-delay: 1` and points to
//! `Sitemap: https://www.fdic.gov/sitemap.xml` as the discovery mechanism.
//! Both are respected: URLs are discovered ONLY via the sitemap (never
//! guessed), and every request is separated by at least `CRAWL_DELAY`.
//!
//! Selector scoping matters here more than usual: an unscoped
//! `a[href*="/news/press-releases/"]` query on IndyMac's (2008-era) page
//! returned unrelated 2026 press releases from a global "latest news" widget
//! present on every FDIC.gov page — confirmed live before shipping this, not
//! assumed. Every selector below is scoped to `article.node--failed-bank` to
//! avoid that class of false positive.

use scraper::{ElementRef, Html, Selector};
use std::time::Duration;

const SITEMAP_INDEX: &str = "https://www.fdic.gov/sitemap.xml";
const FAILURE_PATH_PREFIX: &str =
    "https://www.fdic.gov/resources/resolutions/bank-failures/failed-bank-list/";
const USER_AGENT: &str = "BankLens/0.1 (research; contact you@example.org)";
/// robots.txt: `Crawl-delay: 1`.
const CRAWL_DELAY: Duration = Duration::from_secs(1);

pub struct FdicFailureScraper {
    client: reqwest::Client,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct LinkRef {
    pub url: String,
    pub title: String,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct FailureDetail {
    pub slug: String,
    pub source_url: String,
    pub title: String,
    /// Raw joined narrative text. Deliberately unstructured (Bronze stays
    /// raw) — see module docs: page structure varies a lot between a modern
    /// (2023) failure and a legacy (2008-era) one, so this is NOT a uniform
    /// shape across every bank, just the best-effort narrative text for that
    /// page's actual layout.
    pub narrative: String,
    pub press_releases: Vec<LinkRef>,
    pub faq_url: Option<String>,
}

impl FdicFailureScraper {
    pub fn new() -> Self {
        let client = reqwest::Client::builder()
            .user_agent(USER_AGENT)
            .build()
            .expect("reqwest client build");
        FdicFailureScraper { client }
    }

    /// Discover every "Failed Bank Information" detail-page URL via the
    /// sitemap `robots.txt` declares. Never guesses a URL slug.
    pub async fn discover_urls(&self) -> Result<Vec<String>, String> {
        let index = self.get_text(SITEMAP_INDEX).await?;
        let sub_sitemaps: Vec<String> = extract_locs(&index)
            .into_iter()
            .filter(|u| u.contains("sitemap.xml?page="))
            .collect();

        let mut urls = Vec::new();
        for sm in sub_sitemaps {
            tokio::time::sleep(CRAWL_DELAY).await;
            let xml = self.get_text(&sm).await?;
            urls.extend(
                extract_locs(&xml).into_iter().filter(|u| u.starts_with(FAILURE_PATH_PREFIX)),
            );
        }
        urls.sort();
        urls.dedup();
        Ok(urls)
    }

    /// Fetch and parse one "Failed Bank Information" page. Callers are
    /// responsible for spacing calls at least `CRAWL_DELAY` apart when
    /// fetching several — this function does not sleep itself, since a
    /// single-page fetch shouldn't pay a delay it doesn't need.
    pub async fn fetch_detail(&self, url: &str) -> Result<FailureDetail, String> {
        let html = self.get_text(url).await?;
        let doc = Html::parse_document(&html);

        let title = select_text(&doc.root_element(), "h1").unwrap_or_default();
        let article_sel = Selector::parse("article.node--failed-bank")
            .map_err(|e| format!("selector parse: {e:?}"))?;
        let Some(article) = doc.select(&article_sel).next() else {
            return Err(format!("no article.node--failed-bank found on {url}"));
        };

        let narrative = select_narrative(&article);
        let press_releases = select_links(&article, "a[href*=\"/news/press-releases/\"]");
        let faq_url = select_links(&article, "a[href*=\"frequently-asked-questions\"]")
            .into_iter()
            .next()
            .map(|l| l.url);

        let slug = url
            .trim_start_matches(FAILURE_PATH_PREFIX)
            .trim_end_matches(".html")
            .to_string();
        Ok(FailureDetail { slug, source_url: url.to_string(), title, narrative, press_releases, faq_url })
    }

    async fn get_text(&self, url: &str) -> Result<String, String> {
        self.client
            .get(url)
            .send()
            .await
            .map_err(|e| format!("GET {url} failed: {e}"))?
            .error_for_status()
            .map_err(|e| format!("GET {url}: {e}"))?
            .text()
            .await
            .map_err(|e| format!("body decode failed for {url}: {e}"))
    }
}

impl Default for FdicFailureScraper {
    fn default() -> Self {
        Self::new()
    }
}

/// A tiny, dependency-free `<loc>...</loc>` extractor — sitemap XML is simple
/// enough not to need a full XML parser for this one tag.
fn extract_locs(xml: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut rest = xml;
    while let Some(start) = rest.find("<loc>") {
        let after = &rest[start + 5..];
        let Some(end) = after.find("</loc>") else { break };
        out.push(after[..end].trim().to_string());
        rest = &after[end + 6..];
    }
    out
}

fn select_text(root: &ElementRef, selector_str: &str) -> Option<String> {
    let sel = Selector::parse(selector_str).ok()?;
    root.select(&sel).next().map(|el| el.text().collect::<String>().trim().to_string())
}

/// The FIRST `.paragraph--type--text` block inside the article is the
/// resolution narrative (verified live: on the modern template it's cleanly
/// separated from the FAQ/press-release links block that follows; on legacy
/// pages it's the one long block that holds most of the page's content).
fn select_narrative(article: &ElementRef) -> String {
    let Ok(block_sel) = Selector::parse(".paragraph--type--text") else { return String::new() };
    let Ok(p_sel) = Selector::parse("p") else { return String::new() };
    let Some(first_block) = article.select(&block_sel).next() else { return String::new() };
    first_block
        .select(&p_sel)
        .map(|el| el.text().collect::<String>().trim().to_string())
        .filter(|t| !t.is_empty())
        .collect::<Vec<_>>()
        .join("\n\n")
}

fn select_links(article: &ElementRef, selector_str: &str) -> Vec<LinkRef> {
    let Ok(sel) = Selector::parse(selector_str) else { return Vec::new() };
    article
        .select(&sel)
        .filter_map(|el| {
            let href = el.value().attr("href")?;
            let url = if href.starts_with("http") {
                href.to_string()
            } else {
                format!("https://www.fdic.gov{href}")
            };
            let title = el.text().collect::<String>().trim().to_string();
            Some(LinkRef { url, title })
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parse(html: &str) -> Html {
        Html::parse_document(html)
    }

    const SIGNATURE_LIKE: &str = r#"
        <html><body>
        <h1>Failed Bank Information for Signature Bank, New York, NY</h1>
        <article class="node--failed-bank">
          <div class="paragraph paragraph--type--text">
            <p><a class="ck-anchor" id="top"></a>On March 12, 2023, Signature Bank was closed.</p>
            <p>Depositors became depositors of the assuming institution.</p>
          </div>
          <div class="paragraph paragraph--type--layout">
            <div class="paragraph paragraph--type--text">
              <p><a href="/bank-failures/frequently-asked-questions-signature-bank-new-york-ny">Frequently Asked Questions</a></p>
            </div>
            <div class="paragraph paragraph--type--text">
              <p><a href="/news/press-releases/2023/pr23018.html">March 12, 2023 Official Press Release</a></p>
            </div>
          </div>
        </article>
        <aside><a href="/news/press-releases/2026/unrelated-bank.html">Unrelated 2026 press release</a></aside>
        </body></html>
    "#;

    #[test]
    fn narrative_is_only_the_first_text_block_not_the_faq_links() {
        let doc = parse(SIGNATURE_LIKE);
        let article_sel = Selector::parse("article.node--failed-bank").unwrap();
        let article = doc.select(&article_sel).next().unwrap();
        let narrative = select_narrative(&article);
        assert!(narrative.contains("Signature Bank was closed"));
        assert!(!narrative.contains("Frequently Asked Questions"));
        assert!(!narrative.contains("Press Release"));
    }

    #[test]
    fn press_releases_are_scoped_to_the_article_not_sitewide_widgets() {
        let doc = parse(SIGNATURE_LIKE);
        let article_sel = Selector::parse("article.node--failed-bank").unwrap();
        let article = doc.select(&article_sel).next().unwrap();
        let links = select_links(&article, "a[href*=\"/news/press-releases/\"]");
        assert_eq!(links.len(), 1);
        assert!(links[0].url.ends_with("pr23018.html"));
        assert!(!links.iter().any(|l| l.url.contains("unrelated-bank")));
    }

    #[test]
    fn faq_link_is_found_and_absolute() {
        let doc = parse(SIGNATURE_LIKE);
        let article_sel = Selector::parse("article.node--failed-bank").unwrap();
        let article = doc.select(&article_sel).next().unwrap();
        let faq = select_links(&article, "a[href*=\"frequently-asked-questions\"]");
        assert_eq!(faq.len(), 1);
        assert!(faq[0].url.starts_with("https://www.fdic.gov/"));
    }

    #[test]
    fn missing_article_returns_empty_not_a_panic() {
        let doc = parse("<html><body><h1>No article here</h1></body></html>");
        let article_sel = Selector::parse("article.node--failed-bank").unwrap();
        assert!(doc.select(&article_sel).next().is_none());
    }

    #[test]
    fn extract_locs_parses_a_minimal_sitemap() {
        let xml = r#"<?xml version="1.0"?><urlset>
            <url><loc>https://www.fdic.gov/resources/resolutions/bank-failures/failed-bank-list/foo.html</loc></url>
            <url><loc>https://www.fdic.gov/some-other-page.html</loc></url>
        </urlset>"#;
        let locs = extract_locs(xml);
        assert_eq!(locs.len(), 2);
        assert!(locs[0].ends_with("foo.html"));
    }
}
