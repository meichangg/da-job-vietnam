from sqlalchemy import (
    Column, Integer, String, Text, Boolean, Date,
    DateTime, ForeignKey, UniqueConstraint, func
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Source(Base):
    __tablename__ = "sources"

    id         = Column(Integer, primary_key=True)
    name       = Column(String(50), nullable=False, unique=True)
    base_url   = Column(Text, nullable=False)
    is_active  = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())

    jobs = relationship("Job", back_populates="source")
    snapshots = relationship("WeeklySnapshot", back_populates="source")
    crawl_runs = relationship("CrawlRun", back_populates="source")


class Company(Base):
    __tablename__ = "companies"

    id           = Column(Integer, primary_key=True)
    name         = Column(String(255), nullable=False)
    name_slug    = Column(String(255), unique=True)
    industry     = Column(String(100))
    company_size = Column(String(50))
    location     = Column(String(100))
    created_at   = Column(DateTime, default=func.now())
    updated_at   = Column(DateTime, default=func.now(), onupdate=func.now())

    jobs = relationship("Job", back_populates="company")


class Skill(Base):
    __tablename__ = "skills"

    id       = Column(Integer, primary_key=True)
    name     = Column(String(100), nullable=False, unique=True)
    category = Column(String(50))


class JobSkill(Base):
    __tablename__ = "job_skills"

    job_id   = Column(Integer, ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True)
    skill_id = Column(Integer, ForeignKey("skills.id"), primary_key=True)


class Job(Base):
    __tablename__ = "jobs"

    id               = Column(Integer, primary_key=True)
    external_id      = Column(String(255), nullable=False)
    source_id        = Column(Integer, ForeignKey("sources.id"))
    company_id       = Column(Integer, ForeignKey("companies.id"))

    title            = Column(Text, nullable=False)
    title_normalized = Column(Text)
    url              = Column(Text, nullable=False)
    description      = Column(Text)

    level            = Column(String(50))
    job_type         = Column(String(50))
    location         = Column(String(100))
    category         = Column(String(10), default="DA")  # DA | DS | AI

    salary_min       = Column(Integer)
    salary_max       = Column(Integer)
    salary_currency  = Column(String(10), default="VND")
    salary_raw       = Column(String(100))

    experience_years = Column(Integer)
    deadline         = Column(Date)

    first_seen_at    = Column(DateTime, default=func.now())
    last_seen_at     = Column(DateTime, default=func.now())
    is_active        = Column(Boolean, default=True)
    closed_at        = Column(DateTime)

    source  = relationship("Source", back_populates="jobs")
    company = relationship("Company", back_populates="jobs")

    __table_args__ = (
        UniqueConstraint("external_id", "source_id", name="uq_job_source"),
    )


class WeeklySnapshot(Base):
    __tablename__ = "weekly_snapshots"

    id          = Column(Integer, primary_key=True)
    week_start  = Column(Date, nullable=False)
    week_end    = Column(Date, nullable=False)
    source_id   = Column(Integer, ForeignKey("sources.id"))
    run_at      = Column(DateTime, default=func.now())

    total_jobs  = Column(Integer, default=0)
    new_jobs    = Column(Integer, default=0)
    closed_jobs = Column(Integer, default=0)
    active_jobs = Column(Integer, default=0)

    source  = relationship("Source", back_populates="snapshots")
    changes = relationship("JobWeeklyChange", back_populates="snapshot")

    __table_args__ = (
        UniqueConstraint("week_start", "source_id", name="uq_snapshot_week_source"),
    )


class JobWeeklyChange(Base):
    __tablename__ = "job_weekly_changes"

    id          = Column(Integer, primary_key=True)
    snapshot_id = Column(Integer, ForeignKey("weekly_snapshots.id"))
    job_id      = Column(Integer, ForeignKey("jobs.id"))
    change_type = Column(String(20), nullable=False)  # 'new', 'closed', 'active'
    detected_at = Column(DateTime, default=func.now())

    snapshot = relationship("WeeklySnapshot", back_populates="changes")


class CrawlRun(Base):
    __tablename__ = "crawl_runs"

    id            = Column(Integer, primary_key=True)
    source_id     = Column(Integer, ForeignKey("sources.id"))
    started_at    = Column(DateTime, default=func.now())
    finished_at   = Column(DateTime)
    status        = Column(String(20), default="running")
    jobs_crawled  = Column(Integer, default=0)
    jobs_new      = Column(Integer, default=0)
    jobs_updated  = Column(Integer, default=0)
    error_message = Column(Text)
    triggered_by  = Column(String(50), default="scheduler")

    source = relationship("Source", back_populates="crawl_runs")
