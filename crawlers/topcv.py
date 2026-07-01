"""
TopCV crawler — Playwright (Chromium) vì Cloudflare block TLS fingerprint của httpx.
Job listings được render bởi JS nên cần đợi selector xuất hiện sau khi trang load.
"""
import re
import time
from loguru import logger
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from bs4 import BeautifulSoup

from crawlers.base_crawler import BaseCrawler, JobItem
from utils.normalizer import is_da_job, extract_skills

# Tìm kiếm DA jobs theo keyword — dùng URL search có keyword sẵn
SEARCH_QUERIES = [
    "https://www.topcv.vn/viec-lam-it?keyword=data+analyst",
    "https://www.topcv.vn/viec-lam-it?keyword=business+analyst",
    "https://www.topcv.vn/viec-lam-it?keyword=data+analytics",
    "https://www.topcv.vn/viec-lam-it?keyword=bi+analyst",
    "https://www.topcv.vn/tim-viec-lam-data-analyst",
    "https://www.topcv.vn/tim-viec-lam-business-analyst",
    "https://www.topcv.vn/tim-viec-lam-data",
]

DA_KEYWORDS = [
    "data analyst", "business analyst", "bi analyst", "data analytics",
    "business intelligence", "phân tích dữ liệu", "phân tích kinh doanh",
    "data engineer", "analytics", "dữ liệu",
]

# Selector có thể có trên TopCV — thử tuần tự
JOB_CARD_SELECTORS = [
    ".job-item-search-result",
    ".job-item",
    "[data-job-id]",
    ".box-job",
    "div[class*='JobItem']",
]


def _is_da(title: str) -> bool:
    t = title.lower()
    return any(k in t for k in DA_KEYWORDS) or is_da_job(title)


def _parse_jobs(html: str) -> list[dict]:
    soup  = BeautifulSoup(html, "html.parser")
    cards = []
    used_sel = ""
    for sel in JOB_CARD_SELECTORS:
        cards = soup.select(sel)
        if cards:
            used_sel = sel
            break

    if not cards:
        return []

    logger.debug(f"[TopCV] Selector '{used_sel}' -> {len(cards)} cards")
    jobs = []
    for card in cards:
        title_el = card.select_one(
            "h3.title a, .title a, h3 a, [class*='title'] a, a[href*='/viec-lam/']"
        )
        if not title_el:
            continue

        title = re.sub(r"^(Nổi bật|Hot|Urgent|New)\s*", "", title_el.get_text(strip=True)).strip()
        url   = title_el.get("href", "")
        if url and not url.startswith("http"):
            url = "https://www.topcv.vn" + url

        jid_m  = re.search(r"/(\d+)\.html", url)
        job_id = jid_m.group(1) if jid_m else (card.get("data-job-id", "") or "")

        company_el = card.select_one(
            ".company a, .company, .name-company a, .name-company, [class*='company'] a"
        )
        company = company_el.get_text(strip=True) if company_el else "Unknown"

        salary_el = card.select_one(".salary, [class*='salary']")
        salary    = salary_el.get_text(strip=True) if salary_el else "Thương lượng"

        loc_el   = card.select_one(".address, [class*='location']")
        location = loc_el.get_text(strip=True) if loc_el else ""

        if title and job_id:
            jobs.append({
                "id": job_id, "title": title, "company": company,
                "url": url or "https://www.topcv.vn",
                "salary": salary, "location": location,
            })
    return jobs


def _scrape_url(page, url: str) -> list[dict]:
    """Navigate đến URL và parse jobs. Dùng lại page đã có để giữ cookies."""
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)

        # Đợi job cards xuất hiện (tối đa 10s)
        loaded = False
        for sel in JOB_CARD_SELECTORS:
            try:
                page.wait_for_selector(sel, timeout=10000)
                loaded = True
                break
            except PlaywrightTimeout:
                continue

        if not loaded:
            # Không tìm thấy selector, kiểm tra xem có bị block không
            title = page.title()
            if any(x in title.lower() for x in ["cloudflare", "attention", "just a moment"]):
                logger.warning(f"[TopCV] Cloudflare block: {title} | {url}")
            else:
                logger.warning(f"[TopCV] No job cards found on: {url} (title: {title[:60]})")
            return []

        # Cuộn trang để trigger lazy loading
        page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
        page.wait_for_timeout(1500)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1000)

        jobs = _parse_jobs(page.content())
        logger.info(f"[TopCV] {url} -> {len(jobs)} raw cards")
        return jobs

    except Exception as e:
        logger.warning(f"[TopCV] Error on {url}: {e}")
        return []


class TopCVCrawler(BaseCrawler):
    SOURCE_NAME = "topcv"
    SOURCE_URL  = "https://www.topcv.vn"

    def fetch_jobs(self) -> list[JobItem]:
        all_items: dict[str, JobItem] = {}

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
                locale="vi-VN",
                viewport={"width": 1280, "height": 900},
                extra_http_headers={
                    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
            )
            page = context.new_page()

            # Warm up: visit homepage để lấy cookies
            try:
                page.goto("https://www.topcv.vn", wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(2000)
                logger.info("[TopCV] Warmup done")
            except Exception as e:
                logger.warning(f"[TopCV] Warmup failed: {e}")

            for url in SEARCH_QUERIES:
                raw_jobs = _scrape_url(page, url)
                for job in raw_jobs:
                    if not _is_da(job["title"]):
                        continue
                    item = self._parse(job)
                    if item:
                        all_items[item.external_id] = item
                time.sleep(self.delay)

            browser.close()

        logger.info(f"[TopCV] {len(all_items)} DA jobs after filter")
        return list(all_items.values())

    def _parse(self, job: dict) -> JobItem | None:
        try:
            return JobItem(
                external_id  = f"topcv-{job['id']}",
                source_name  = self.SOURCE_NAME,
                title        = job["title"],
                company_name = job["company"],
                url          = job["url"],
                location     = job.get("location", ""),
                salary_raw   = job.get("salary", "Thương lượng"),
                skills       = [],
            )
        except Exception as e:
            logger.debug(f"[TopCV] Parse error: {e}")
            return None
