"""
YBox crawler — dùng GraphQL API (https://api.ybox.vn/graphql).
Không cần Playwright, không cần browser.
"""
import re
import time
import httpx
from loguru import logger
from sqlalchemy.orm import Session

from crawlers.base_crawler import BaseCrawler, JobItem
from utils.normalizer import extract_skills, extract_salary_from_title

COMMUNITY_TUYEN_DUNG = "5a4542f355ae5009afa5a3ec"

GQL_QUERY = """
{
  SearchPosts(limit: %d, page: %d, q: "%s", communityId: "%s") {
    count
    edges {
      _id
      title
      nameCompany
      deadline
      publishedAt
      summary
      content
      sortId
      additionFields
    }
  }
}
"""


class YBoxCrawler(BaseCrawler):
    SOURCE_NAME = "ybox"
    SOURCE_URL  = "https://ybox.vn"

    API_URL     = "https://api.ybox.vn/graphql"
    JOB_URL     = "https://ybox.vn/tuyen-dung/{sort_id}"
    PAGE_SIZE   = 20

    SEARCH_TERMS = [
        "data analyst",
        "business analyst",
        "bi analyst",
        "data analytics",
        "business intelligence",
    ]

    def __init__(self, session: Session, max_pages: int = 5, delay: float = 1.5):
        super().__init__(session, max_pages, delay)
        self.client = httpx.Client(
            headers={
                "Content-Type": "application/json",
                "User-Agent":   "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            },
            timeout=20,
        )

    def fetch_jobs(self) -> list[JobItem]:
        all_items: dict[str, JobItem] = {}

        for term in self.SEARCH_TERMS:
            logger.info(f"[YBox] Searching: '{term}'")
            items = self._search(term)
            for item in items:
                all_items[item.external_id] = item
            time.sleep(self.delay)

        return list(all_items.values())

    def _search(self, query: str) -> list[JobItem]:
        items = []

        for page_num in range(1, self.max_pages + 1):
            gql = GQL_QUERY % (self.PAGE_SIZE, page_num, query, COMMUNITY_TUYEN_DUNG)
            try:
                resp = self.client.get(self.API_URL, params={"query": gql})
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.warning(f"[YBox] Request failed p{page_num}: {e}")
                break

            if "errors" in data:
                logger.warning(f"[YBox] GraphQL error: {data['errors'][0].get('message','')}")
                break

            result = data.get("data", {}).get("SearchPosts", {})
            edges  = result.get("edges", [])
            total  = result.get("count", 0)

            if not edges:
                break

            for post in edges:
                item = self._parse(post)
                if item:
                    items.append(item)

            if page_num * self.PAGE_SIZE >= total:
                break

            time.sleep(self.delay)

        return items

    def _parse(self, post: dict) -> JobItem | None:
        try:
            post_id   = post.get("_id", "")
            title     = (post.get("title") or "").strip()
            company   = (post.get("nameCompany") or "Unknown").strip()
            sort_id   = post.get("sortId") or post_id
            url       = self.JOB_URL.format(sort_id=sort_id)
            deadline  = self._parse_date(post.get("deadline"))

            description = (post.get("summary") or "") + "\n" + (post.get("content") or "")
            skills      = extract_skills(description)

            location   = self._extract_location(title)
            salary_raw = extract_salary_from_title(title) or "Thương lượng"

            if not post_id or not title:
                return None

            return JobItem(
                external_id  = f"ybox-{post_id}",
                source_name  = self.SOURCE_NAME,
                title        = title,
                company_name = company,
                url          = url,
                location     = location,
                description  = description.strip(),
                deadline     = deadline,
                skills       = skills,
                salary_raw   = salary_raw,
            )
        except Exception as e:
            logger.debug(f"[YBox] Parse error: {e}")
            return None

    def _extract_location(self, title: str) -> str:
        """Lấy địa điểm từ tiêu đề dạng '[HN] ...' hoặc '[HCM] ...'"""
        match = re.match(r"\[([^\]]+)\]", title)
        if not match:
            return ""
        loc = match.group(1).upper()
        mapping = {
            "HN": "Hà Nội", "HANOI": "Hà Nội",
            "HCM": "TP.HCM", "TPHCM": "TP.HCM", "HCMC": "TP.HCM",
            "DN": "Đà Nẵng", "DANANG": "Đà Nẵng",
            "REMOTE": "Remote", "ONLINE": "Remote",
            "HN/HCM": "Toàn quốc", "HCM/HN": "Toàn quốc",
        }
        return mapping.get(loc, loc)

    def _parse_date(self, date_str: str | None) -> str | None:
        """Chuyển 'Thu Jul 30 2026 23:59:59 GMT+0700' → '2026-07-30'"""
        if not date_str:
            return None
        try:
            from datetime import datetime
            dt = datetime.strptime(date_str[:15], "%a %b %d %Y")
            return dt.strftime("%Y-%m-%d")
        except Exception:
            return None
