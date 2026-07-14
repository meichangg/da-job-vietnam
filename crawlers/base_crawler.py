from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
from loguru import logger
from sqlalchemy.orm import Session

from db import repository as repo
from utils.normalizer import (
    normalize_title, normalize_location, normalize_skill_name,
    extract_level, extract_skills, parse_salary, classify_job_category,
)


@dataclass
class JobItem:
    external_id:     str
    source_name:     str
    title:           str
    url:             str
    company_name:    str
    location:        Optional[str]   = None
    description:     Optional[str]   = None
    salary_raw:      Optional[str]   = None
    salary_min:      Optional[int]   = None
    salary_max:      Optional[int]   = None
    level:           Optional[str]   = None
    job_type:        Optional[str]   = None
    experience_years: Optional[int]  = None
    deadline:        Optional[str]   = None
    skills:          list[str]       = field(default_factory=list)


class BaseCrawler(ABC):
    SOURCE_NAME: str = ""
    SOURCE_URL:  str = ""

    def __init__(self, session: Session, max_pages: int = 10, delay: float = 2.0):
        self.session   = session
        self.max_pages = max_pages
        self.delay     = delay
        self.source    = repo.get_or_create_source(session, self.SOURCE_NAME, self.SOURCE_URL)
        session.commit()

    @abstractmethod
    def fetch_jobs(self) -> list[JobItem]:
        """Crawl toàn bộ job từ source. Override trong subclass."""
        ...

    def run(self) -> dict:
        logger.info(f"[{self.SOURCE_NAME}] Starting crawl...")
        run = repo.start_crawl_run(self.session, self.source.id)
        self.session.commit()

        jobs_new = jobs_updated = 0
        seen_ids: set[str] = set()

        try:
            items = self.fetch_jobs()
            logger.info(f"[{self.SOURCE_NAME}] Fetched {len(items)} raw items")

            for item in items:
                category = classify_job_category(item.title)
                if not category:
                    continue

                seen_ids.add(item.external_id)
                job_data = self._to_db_dict(item)
                job_data["category"] = category
                job, is_new = repo.upsert_job(self.session, job_data)

                if item.skills:
                    skills = [normalize_skill_name(s) for s in item.skills]
                    repo.attach_skills(self.session, job, skills)

                if is_new:
                    jobs_new += 1
                else:
                    jobs_updated += 1

            if items:
                closed = repo.mark_closed_jobs(self.session, self.source.id, seen_ids)
            else:
                # 0 job crawl được nhiều khả năng là crawl bị chặn/lỗi (vd Cloudflare),
                # không phải thị trường hết job — bỏ qua bước đóng để tránh đóng nhầm
                # toàn bộ job đang active của nguồn này.
                closed = []
                logger.warning(
                    f"[{self.SOURCE_NAME}] 0 items fetched — skipping mark_closed_jobs "
                    "(likely a blocked/failed crawl, not an empty market)"
                )
            self.session.commit()

            repo.finish_crawl_run(
                self.session, run,
                status="success",
                jobs_crawled=len(items),
                jobs_new=jobs_new,
                jobs_updated=jobs_updated,
            )
            self.session.commit()

            result = {
                "source":       self.SOURCE_NAME,
                "crawled":      len(items),
                "new":          jobs_new,
                "updated":      jobs_updated,
                "closed":       len(closed),
            }
            logger.success(f"[{self.SOURCE_NAME}] Done: {result}")
            return result

        except Exception as e:
            self.session.rollback()
            repo.finish_crawl_run(self.session, run, status="failed", error_message=str(e))
            self.session.commit()
            logger.error(f"[{self.SOURCE_NAME}] Failed: {e}")
            raise

    def _to_db_dict(self, item: JobItem) -> dict:
        sal_min, sal_max = parse_salary(item.salary_raw or "")
        company = repo.get_or_create_company(self.session, item.company_name)

        return {
            "external_id":      item.external_id,
            "source_id":        self.source.id,
            "company_id":       company.id,
            "title":            item.title,
            "title_normalized": normalize_title(item.title),
            "url":              item.url,
            "description":      item.description,
            "level":            item.level or extract_level(item.title, item.description or ""),
            "job_type":         item.job_type,
            "location":         normalize_location(item.location or ""),
            "salary_raw":       item.salary_raw,
            "salary_min":       item.salary_min or sal_min,
            "salary_max":       item.salary_max or sal_max,
            "experience_years": item.experience_years,
            "deadline":         item.deadline,
        }
