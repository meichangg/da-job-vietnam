"""
LinkedIn crawler — dùng "jobs-guest" API công khai (không cần đăng nhập).
Đây là endpoint phục vụ trang search jobs cho người dùng chưa đăng nhập
(giống trang https://www.linkedin.com/jobs/search/ khi mở ẩn danh), nên
không có rủi ro tài khoản cá nhân bị checkpoint/khoá như cách login qua
Playwright trước đây.
"""
import re
import time
import random
import httpx
from bs4 import BeautifulSoup
from loguru import logger
from sqlalchemy.orm import Session

from crawlers.base_crawler import BaseCrawler, JobItem
from utils.normalizer import extract_skills

PAGE_SIZE = 25


class LinkedInCrawler(BaseCrawler):
    SOURCE_NAME = "linkedin"
    SOURCE_URL  = "https://www.linkedin.com"

    API_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"

    SEARCH_TERMS = [
        "data analyst",
        "business analyst",
        "bi analyst",
        "data analytics",
        "business intelligence",
        "data scientist",
        "machine learning engineer",
        "ai engineer",
    ]

    def __init__(self, session: Session, max_pages: int = 5, delay: float = 2.0):
        super().__init__(session, max_pages, delay)
        self.client = httpx.Client(
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8",
            },
            timeout=20,
        )

    def fetch_jobs(self) -> list[JobItem]:
        all_items: dict[str, JobItem] = {}

        for term in self.SEARCH_TERMS:
            logger.info(f"[LinkedIn] Searching: '{term}'")
            items = self._search(term)
            for item in items:
                all_items[item.external_id] = item
            time.sleep(self.delay + random.uniform(1, 2))

        return list(all_items.values())

    def _search(self, term: str) -> list[JobItem]:
        items = []

        for page in range(self.max_pages):
            start = page * PAGE_SIZE
            params = {
                "keywords": term,
                "location": "Vietnam",
                "f_TPR":    "r604800",  # 7 ngày gần nhất
                "start":    start,
            }

            try:
                resp = self.client.get(self.API_URL, params=params)
                resp.raise_for_status()
            except Exception as e:
                logger.warning(f"[LinkedIn] Page {page} failed for '{term}': {e}")
                break

            cards = self._parse(resp.text)
            if not cards:
                break

            items.extend(cards)
            if len(cards) < PAGE_SIZE:
                break

            time.sleep(self.delay + random.uniform(0.5, 1.5))

        return items

    def _parse(self, html: str) -> list[JobItem]:
        soup    = BeautifulSoup(html, "html.parser")
        results = []

        for card in soup.select("div.base-card"):
            item = self._parse_card(card)
            if item:
                results.append(item)

        return results

    def _parse_card(self, card) -> JobItem | None:
        try:
            urn    = card.get("data-entity-urn", "")
            id_m   = re.search(r":(\d+)$", urn)

            link_el = card.select_one("a.base-card__full-link, a")
            href    = link_el.get("href", "") if link_el else ""
            url     = href.split("?")[0]
            # LinkedIn trả về subdomain theo quốc gia (vn.linkedin.com, de.linkedin.com...)
            # nhưng các subdomain này hay bị treo/đóng kết nối — www.linkedin.com luôn ổn định.
            url = re.sub(r"^https://[a-z]{2,3}\.linkedin\.com/", "https://www.linkedin.com/", url)

            job_id = id_m.group(1) if id_m else ""
            if not job_id:
                m = re.search(r"-(\d+)(?:\?|$)", href)
                job_id = m.group(1) if m else ""

            title_el   = card.select_one(".base-search-card__title, h3")
            company_el = card.select_one(".base-search-card__subtitle, h4")
            loc_el     = card.select_one(".job-search-card__location")

            title   = title_el.get_text(strip=True)   if title_el   else ""
            company = company_el.get_text(strip=True) if company_el else "Unknown"
            loc     = loc_el.get_text(strip=True)     if loc_el     else "Vietnam"

            if not title or not job_id or not url:
                return None

            return JobItem(
                external_id  = f"li-{job_id}",
                source_name  = self.SOURCE_NAME,
                title        = title,
                company_name = company,
                url          = url,
                location     = loc,
                salary_raw   = None,
            )
        except Exception as e:
            logger.debug(f"[LinkedIn] Card parse error: {e}")
            return None

    def fetch_job_detail(self, url: str) -> dict:
        """Lấy mô tả chi tiết — gọi có chọn lọc để tránh rate limit."""
        try:
            resp = self.client.get(url, timeout=20)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            desc_el = soup.select_one(".show-more-less-html__markup, .description__text")
            desc    = desc_el.get_text("\n", strip=True) if desc_el else ""
            return {
                "description": desc,
                "skills":      extract_skills(desc),
            }
        except Exception as e:
            logger.debug(f"[LinkedIn] Detail error: {e}")
            return {}
