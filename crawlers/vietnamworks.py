"""
VietnamWorks crawler — POST https://ms.vietnamworks.com/job-search/v1.0/search
"""
import time
import httpx
from loguru import logger
from sqlalchemy.orm import Session

from crawlers.base_crawler import BaseCrawler, JobItem
from utils.normalizer import extract_skills

PAGE_SIZE = 20


class VietnamWorksCrawler(BaseCrawler):
    SOURCE_NAME = "vietnamworks"
    SOURCE_URL  = "https://www.vietnamworks.com"

    API_URL = "https://ms.vietnamworks.com/job-search/v1.0/search"
    JOB_URL = "https://www.vietnamworks.com/{job_url}"

    SEARCH_TERMS = [
        "data analyst",
        "business analyst",
        "bi analyst",
        "data analytics",
        "business intelligence",
        "data engineer",
        "analytics engineer",
        "phân tích dữ liệu",
        "phân tích kinh doanh",
    ]

    def __init__(self, session: Session, max_pages: int = 5, delay: float = 1.5):
        super().__init__(session, max_pages, delay)
        self.client = httpx.Client(
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0",
                "Content-Type": "application/json",
                "Referer": "https://www.vietnamworks.com/",
            },
            timeout=20,
        )

    def fetch_jobs(self) -> list[JobItem]:
        all_items: dict[str, JobItem] = {}

        for term in self.SEARCH_TERMS:
            logger.info(f"[VietnamWorks] Searching: '{term}'")
            items = self._search(term)
            for item in items:
                all_items[item.external_id] = item
            time.sleep(self.delay)

        return list(all_items.values())

    def _search(self, query: str) -> list[JobItem]:
        items = []

        for page in range(self.max_pages):
            payload = {
                "query":       query,
                "page":        page,
                "hitsPerPage": PAGE_SIZE,
                "userId":      0,
            }

            try:
                resp = self.client.post(self.API_URL, json=payload)
                resp.raise_for_status()
                body = resp.json()
            except Exception as e:
                logger.warning(f"[VietnamWorks] Page {page} failed: {e}")
                break

            meta     = body.get("meta", {})
            jobs_raw = body.get("data", [])
            nb_pages = meta.get("nbPages", 0)

            if not jobs_raw:
                break

            for job in jobs_raw:
                item = self._parse(job)
                if item:
                    items.append(item)

            if page >= nb_pages - 1:
                break

            time.sleep(self.delay)

        return items

    def _parse(self, job: dict) -> JobItem | None:
        try:
            job_id   = str(job.get("jobId", ""))
            title    = (job.get("jobTitle") or "").strip()
            company  = (job.get("companyName") or "Unknown").strip()
            job_url  = job.get("jobUrl") or f"job/{job_id}"
            if job_url.startswith("http://") or job_url.startswith("https://"):
                url = job_url
            else:
                url = self.JOB_URL.format(job_url=job_url.lstrip("/"))

            # Lương — API trả salaryMin/Max theo đúng đơn vị của salaryCurrency
            # (vd 700 USD, không phải 700 VND) nên phải tự quy đổi về VND.
            USD_TO_VND = 25_000
            sal_raw  = job.get("prettySalary") or "Thương lượng"
            currency = (job.get("salaryCurrency") or "VND").upper()
            rate     = USD_TO_VND if currency == "USD" else 1
            sal_min  = int(job.get("salaryMin") or 0) * rate or None
            sal_max  = int(job.get("salaryMax") or 0) * rate or None

            # Địa điểm
            locs     = job.get("workingLocations") or []
            location = ", ".join(
                l.get("cityNameVI") or l.get("city") or l.get("cityNameEN") or ""
                for l in locs if isinstance(l, dict)
            ).strip() or ""

            # Level
            level    = (job.get("jobLevel") or job.get("jobLevelVI") or "").lower()

            # Skills & description
            desc     = (job.get("jobDescription") or "") + "\n" + (job.get("jobRequirement") or "")
            skills_raw = job.get("skills") or []
            skills   = [s.get("skillName", "") for s in skills_raw if isinstance(s, dict)]
            if not skills:
                skills = extract_skills(desc)

            deadline = job.get("expiredOn", "")[:10] if job.get("expiredOn") else None

            if not job_id or not title:
                return None

            return JobItem(
                external_id  = f"vnw-{job_id}",
                source_name  = self.SOURCE_NAME,
                title        = title,
                company_name = company,
                url          = url,
                location     = location,
                description  = desc.strip(),
                salary_raw   = sal_raw,
                salary_min   = sal_min,
                salary_max   = sal_max,
                level        = level or None,
                deadline     = deadline,
                skills       = skills,
            )
        except Exception as e:
            logger.debug(f"[VietnamWorks] Parse error: {e}")
            return None
