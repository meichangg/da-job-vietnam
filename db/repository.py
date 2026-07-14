import re
from datetime import datetime
from typing import Optional
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session
from loguru import logger

from db.models import Base, Source, Company, Skill, Job, JobSkill, CrawlRun


def get_engine(database_url: str):
    return create_engine(database_url, pool_pre_ping=True)


def init_db(engine):
    Base.metadata.create_all(engine)
    logger.info("Database tables created")


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def get_or_create_source(session, name: str, base_url: str):
    if hasattr(session, "get_or_create_source"):
        return session.get_or_create_source(name, base_url)
    source = session.scalar(select(Source).where(Source.name == name))
    if not source:
        source = Source(name=name, base_url=base_url)
        session.add(source)
        session.flush()
    return source


def get_or_create_company(session, name: str):
    if hasattr(session, "get_or_create_company"):
        return session.get_or_create_company(name)
    name = name[:250]
    slug = _slug(name)[:250]
    company = session.scalar(select(Company).where(Company.name_slug == slug))
    if not company:
        company = Company(name=name, name_slug=slug)
        session.add(company)
        session.flush()
    return company


def get_or_create_skill(session, name: str):
    if hasattr(session, "get_or_create_skill"):
        return session.get_or_create_skill(name)
    skill = session.scalar(select(Skill).where(Skill.name == name))
    if not skill:
        skill = Skill(name=name)
        session.add(skill)
        session.flush()
    return skill


def upsert_job(session, data: dict) -> tuple:
    if hasattr(session, "upsert_job"):
        return session.upsert_job(data)
    job = session.scalar(
        select(Job).where(
            Job.external_id == data["external_id"],
            Job.source_id == data["source_id"],
        )
    )

    if job:
        job.last_seen_at = datetime.utcnow()
        job.is_active = True
        job.category = data.get("category", job.category)
        job.salary_raw = data.get("salary_raw", job.salary_raw)
        job.salary_min = data.get("salary_min", job.salary_min)
        job.salary_max = data.get("salary_max", job.salary_max)
        return job, False

    job = Job(
        external_id      = data["external_id"],
        source_id        = data["source_id"],
        company_id       = data.get("company_id"),
        title            = data["title"][:250],
        title_normalized = (data.get("title_normalized") or "")[:250],
        url              = data["url"],
        description      = data.get("description"),
        level            = data.get("level"),
        job_type         = data.get("job_type"),
        location         = data.get("location"),
        category         = data.get("category", "DA"),
        salary_min       = data.get("salary_min"),
        salary_max       = data.get("salary_max"),
        salary_raw       = data.get("salary_raw"),
        experience_years = data.get("experience_years"),
        deadline         = data.get("deadline"),
        first_seen_at    = datetime.utcnow(),
        last_seen_at     = datetime.utcnow(),
    )
    session.add(job)
    session.flush()
    return job, True


def attach_skills(session, job, skill_names: list[str]):
    if hasattr(session, "attach_skills"):
        return session.attach_skills(job, skill_names)
    for name in skill_names:
        skill = get_or_create_skill(session, name)
        exists = session.scalar(
            select(JobSkill).where(
                JobSkill.job_id == job.id,
                JobSkill.skill_id == skill.id,
            )
        )
        if not exists:
            session.add(JobSkill(job_id=job.id, skill_id=skill.id))


def mark_closed_jobs(session, source_id: int, seen_external_ids: set):
    if hasattr(session, "mark_closed_jobs"):
        return session.mark_closed_jobs(source_id, seen_external_ids)
    active_jobs = session.scalars(
        select(Job).where(Job.source_id == source_id, Job.is_active == True)
    ).all()

    closed = []
    for job in active_jobs:
        if job.external_id not in seen_external_ids:
            job.is_active = False
            job.closed_at = datetime.utcnow()
            closed.append(job)
            logger.debug(f"Closed: {job.title} ({job.external_id})")

    return closed


def start_crawl_run(session, source_id: int, triggered_by: str = "scheduler"):
    if hasattr(session, "start_crawl_run"):
        return session.start_crawl_run(source_id, triggered_by)
    run = CrawlRun(source_id=source_id, triggered_by=triggered_by)
    session.add(run)
    session.flush()
    return run


def finish_crawl_run(
    session,
    run,
    status: str,
    jobs_crawled: int = 0,
    jobs_new: int = 0,
    jobs_updated: int = 0,
    error_message: Optional[str] = None,
):
    if hasattr(session, "finish_crawl_run"):
        return session.finish_crawl_run(run, status, jobs_crawled, jobs_new, jobs_updated, error_message)
    run.finished_at   = datetime.utcnow()
    run.status        = status
    run.jobs_crawled  = jobs_crawled
    run.jobs_new      = jobs_new
    run.jobs_updated  = jobs_updated
    run.error_message = error_message
