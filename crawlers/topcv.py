"""
TopCV crawler — scrape HTML từ category pages.
Dùng fresh Playwright session riêng biệt cho từng category để tránh Cloudflare.
"""
import re
from loguru import logger
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

from crawlers.base_crawler import BaseCrawler, JobItem
from utils.normalizer import is_da_job

CATEGORY_URLS = [
    "https://www.topcv.vn/viec-lam-it",
    "https://www.topcv.vn/viec-lam-kinh-doanh",
    "https://www.topcv.vn/tim-viec-lam-data-analyst",
    "https://www.topcv.vn/tim-viec-lam-business-analyst",
    "https://www.topcv.vn/tim-viec-lam-data",
]

DA_KEYWORDS = [
    "data analyst", "business analyst", "bi analyst", "data analytics",
    "business intelligence", "phân tích dữ liệu", "phân tích kinh doanh",
    "data engineer", "analytics", "dữ liệu",
]


def _is_da(title: str) -> bool:
    t = title.lower()
    return any(k in t for k in DA_KEYWORDS) or is_da_job(title)


def _parse_cards(html: str, source_url: str) -> list[dict]:
    soup  = BeautifulSoup(html, "html.parser")
    cards = soup.select(".job-item-search-result")
    jobs  = []
    for card in cards:
        title_el = card.select_one("h3.title a, .title a, h3 a")
        if not title_el:
            continue

        title = re.sub(r"^(Nổi bật|Hot|Urgent)\s*", "", title_el.get_text(strip=True)).strip()
        url   = title_el.get("href", "")
        if url and not url.startswith("http"):
            url = "https://www.topcv.vn" + url

        jid_m  = re.search(r"/(\d+)\.html", url)
        job_id = jid_m.group(1) if jid_m else ""

        company_el = card.select_one(".company a, .company, .name-company a, .name-company")
        company    = company_el.get_text(strip=True) if company_el else "Unknown"

        salary_el = card.select_one(".salary, [class*='salary']")
        salary    = salary_el.get_text(strip=True) if salary_el else "Thương lượng"

        loc_el   = card.select_one(".address, [class*='location']")
        location = loc_el.get_text(strip=True) if loc_el else ""

        if job_id and title:
            jobs.append({
                "id": job_id, "title": title, "company": company,
                "url": url or f"https://www.topcv.vn/viec-lam/{job_id}.html",
                "salary": salary, "location": location,
            })
    return jobs


def _scrape_category(category_url: str) -> list[dict]:
    """Open a fresh browser session and scrape 1 page of jobs."""
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            locale="vi-VN",
            viewport={"width": 1280, "height": 900},
            extra_http_headers={
                "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        page = context.new_page()
        try:
            page.goto(category_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)
            title = page.title()
            if "cloudflare" in title.lower() or "attention" in title.lower():
                logger.warning(f"[TopCV] Cloudflare block on {category_url}")
                return []
            jobs = _parse_cards(page.content(), category_url)
            logger.info(f"[TopCV] {category_url} → {len(jobs)} raw cards")
            return jobs
        except Exception as e:
            logger.warning(f"[TopCV] Error on {category_url}: {e}")
            return []
        finally:
            browser.close()


class TopCVCrawler(BaseCrawler):
    SOURCE_NAME = "topcv"
    SOURCE_URL  = "https://www.topcv.vn"

    def fetch_jobs(self) -> list[JobItem]:
        all_items: dict[str, JobItem] = {}

        for cat_url in CATEGORY_URLS:
            raw_jobs = _scrape_category(cat_url)
            for job in raw_jobs:
                if not _is_da(job["title"]):
                    continue
                item = self._parse(job)
                if item:
                    all_items[item.external_id] = item

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
