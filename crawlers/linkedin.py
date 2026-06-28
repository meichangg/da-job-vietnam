"""
LinkedIn crawler — dùng Playwright với đăng nhập.
LinkedIn có anti-bot mạnh: chạy chậm, thêm delay ngẫu nhiên.
Nếu bị block, cân nhắc dùng LinkedIn Jobs RSS hoặc RapidAPI thay thế.
"""
import re
import time
import random
import os
from loguru import logger
from playwright.sync_api import sync_playwright, Page, TimeoutError as PWTimeout
from sqlalchemy.orm import Session

from crawlers.base_crawler import BaseCrawler, JobItem
from utils.normalizer import extract_skills


class LinkedInCrawler(BaseCrawler):
    SOURCE_NAME = "linkedin"
    SOURCE_URL  = "https://www.linkedin.com"

    SEARCH_URL = (
        "https://www.linkedin.com/jobs/search/"
        "?keywords={query}&location=Vietnam&f_TPR=r604800"  # 7 ngày gần nhất
        "&start={start}"
    )
    SEARCH_TERMS = ["data analyst", "business analyst", "BI analyst"]

    def __init__(self, session: Session, max_pages: int = 5, delay: float = 3.0):
        super().__init__(session, max_pages, delay)
        self.email    = os.getenv("LINKEDIN_EMAIL", "")
        self.password = os.getenv("LINKEDIN_PASSWORD", "")

        if not self.email or not self.password:
            logger.warning("[LinkedIn] Credentials not set — will try without login (limited results)")

    def fetch_jobs(self) -> list[JobItem]:
        all_items: dict[str, JobItem] = {}

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=os.getenv("HEADLESS", "true").lower() == "true",
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1366, "height": 768},
                locale="vi-VN",
            )
            page = context.new_page()

            # Ẩn dấu hiệu automation
            page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )

            if not self.email or not self.password:
                logger.warning("[LinkedIn] No credentials in .env — skipping")
                browser.close()
                return []

            if not self._login(page):
                logger.error("[LinkedIn] Login failed, aborting")
                browser.close()
                return []

            for term in self.SEARCH_TERMS:
                logger.info(f"[LinkedIn] Searching: '{term}'")
                items = self._crawl_term(page, term)
                for item in items:
                    all_items[item.external_id] = item

            browser.close()

        return list(all_items.values())

    def _login(self, page: Page) -> bool:
        try:
            page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=30_000)
            # LinkedIn có 2 email inputs — cái thứ 2 mới là visible form
            email_locator = page.locator("input[type='email']").nth(1)
            email_locator.wait_for(state="visible", timeout=15_000)
            email_locator.fill(self.email)
            page.locator("input[type='password']").nth(1).fill(self.password)
            # LinkedIn dùng type="button" thay vì type="submit", nút đăng nhập là cái cuối
            page.locator("button").last.click()
            page.wait_for_url("**/feed/**", timeout=30_000)
            logger.info("[LinkedIn] Login successful")
            time.sleep(random.uniform(2, 4))
            return True
        except Exception as e:
            logger.error(f"[LinkedIn] Login error: {e}")
            return False

    def _crawl_term(self, page: Page, term: str) -> list[JobItem]:
        items = []

        for page_num in range(self.max_pages):
            start = page_num * 25
            url   = self.SEARCH_URL.format(
                query=term.replace(" ", "%20"), start=start
            )

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_timeout(random.randint(2000, 4000))

                # Scroll để load lazy content
                self._scroll_page(page)

            except PWTimeout:
                logger.warning(f"[LinkedIn] Timeout on page {page_num}")
                break
            except Exception as e:
                logger.warning(f"[LinkedIn] Navigation error p{page_num}: {e}")
                break

            page_items = self._parse_job_cards(page)
            if not page_items:
                logger.info(f"[LinkedIn] No more results at page {page_num}")
                break

            items.extend(page_items)
            time.sleep(random.uniform(self.delay, self.delay + 2))

        return items

    def _scroll_page(self, page: Page):
        for _ in range(3):
            page.evaluate("window.scrollBy(0, window.innerHeight)")
            page.wait_for_timeout(random.randint(800, 1500))

    def _parse_job_cards(self, page: Page) -> list[JobItem]:
        items = []

        cards = page.query_selector_all(
            ".job-search-card, .jobs-search__results-list li, "
            "[data-entity-urn*='jobPosting']"
        )

        for card in cards:
            item = self._parse_card(page, card)
            if item:
                items.append(item)

        return items

    def _parse_card(self, page: Page, card) -> JobItem | None:
        try:
            # Extract job ID từ data-entity-urn hoặc href
            urn     = card.get_attribute("data-entity-urn") or ""
            job_id  = re.search(r":(\d+)$", urn)
            job_id  = job_id.group(1) if job_id else ""

            link_el = card.query_selector("a.job-card-list__title, a[href*='/jobs/view/']")
            if not link_el:
                return None

            href    = link_el.get_attribute("href") or ""
            url     = href.split("?")[0]  # bỏ tracking params

            if not job_id:
                match = re.search(r"/jobs/view/(\d+)", href)
                job_id = match.group(1) if match else href.split("/")[-1]

            title_el = card.query_selector(".job-card-list__title, h3.base-search-card__title")
            comp_el  = card.query_selector(".job-card-container__company-name, h4.base-search-card__subtitle")
            loc_el   = card.query_selector(".job-card-container__metadata-item, .job-search-card__location")

            title   = title_el.inner_text().strip() if title_el else ""
            company = comp_el.inner_text().strip()  if comp_el  else "Unknown"
            loc     = loc_el.inner_text().strip()   if loc_el   else "Vietnam"

            if not title or not job_id:
                return None

            if not url.startswith("http"):
                url = self.SOURCE_URL + url

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

    def fetch_job_detail(self, page: Page, url: str) -> dict:
        """Lấy mô tả chi tiết — gọi có chọn lọc để tránh rate limit."""
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20_000)
            page.wait_for_timeout(random.randint(1500, 3000))

            desc_el = page.query_selector(".jobs-description__content, .job-view-layout")
            desc    = desc_el.inner_text() if desc_el else ""

            return {
                "description": desc.strip(),
                "skills":      extract_skills(desc),
            }
        except Exception as e:
            logger.debug(f"[LinkedIn] Detail error: {e}")
            return {}
