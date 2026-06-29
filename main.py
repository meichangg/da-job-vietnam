"""
Entry point — chạy tất cả crawler, sau đó cập nhật weekly snapshot.
Usage:
    python main.py                  # chạy tất cả
    python main.py --source ybox    # chạy một nguồn cụ thể
    python main.py --dry-run        # chỉ test, không ghi DB
"""
import os
import sys
import argparse
from datetime import date, timedelta
from dotenv import load_dotenv
from loguru import logger
from sqlalchemy.orm import Session

from db.models import WeeklySnapshot, JobWeeklyChange
from db.repository import get_engine, init_db, get_or_create_source
from sqlalchemy import select, func

load_dotenv()

DATABASE_URL  = os.getenv("DATABASE_URL", "")
SUPABASE_URL  = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY  = os.getenv("SUPABASE_KEY", "")
MAX_PAGES     = int(os.getenv("MAX_PAGES_PER_SOURCE", "5"))
DELAY         = float(os.getenv("CRAWL_DELAY_SECONDS", "2"))


def _make_session():
    """Trả về SupabaseRepo (cloud) hoặc SQLAlchemy Session (local)."""
    if SUPABASE_URL and SUPABASE_KEY:
        from db.supabase_repo import SupabaseRepo
        logger.info("Using Supabase REST API for database")
        return SupabaseRepo(SUPABASE_URL, SUPABASE_KEY)
    if DATABASE_URL:
        logger.info("Using direct PostgreSQL connection")
        engine = get_engine(DATABASE_URL)
        init_db(engine)
        return Session(engine)
    logger.error("No database config: set SUPABASE_URL+SUPABASE_KEY or DATABASE_URL")
    sys.exit(1)


def run_crawlers(source_filter: str | None = None) -> dict:
    from crawlers.ybox         import YBoxCrawler
    from crawlers.vietnamworks import VietnamWorksCrawler
    from crawlers.topcv        import TopCVCrawler

    crawlers = {
        "ybox":         YBoxCrawler,
        "vietnamworks": VietnamWorksCrawler,
        "topcv":        TopCVCrawler,
    }

    if source_filter:
        crawlers = {k: v for k, v in crawlers.items() if k == source_filter}
        if not crawlers:
            logger.error(f"Unknown source: {source_filter}")
            sys.exit(1)

    session = _make_session()
    summary = {}
    try:
        for name, CrawlerClass in crawlers.items():
            try:
                crawler = CrawlerClass(session, max_pages=MAX_PAGES, delay=DELAY)
                result  = crawler.run()
                summary[name] = result
            except Exception as e:
                logger.error(f"Crawler [{name}] failed: {e}")
                summary[name] = {"error": str(e)}

        build_weekly_snapshot(session)
    finally:
        if hasattr(session, "close"):
            session.close()

    return summary


def build_weekly_snapshot(session):
    if hasattr(session, "build_weekly_snapshot"):
        today      = date.today()
        week_start = today - timedelta(days=today.weekday())
        week_end   = week_start + timedelta(days=6)
        session.build_weekly_snapshot(week_start, week_end)
        return

    today      = date.today()
    week_start = today - timedelta(days=today.weekday())  # Thứ Hai
    week_end   = week_start + timedelta(days=6)           # Chủ Nhật

    from db.models import Source, Job

    sources = session.scalars(select(Source).where(Source.is_active == True)).all()

    for source in sources:
        # Đếm job active hiện tại
        active_count = session.scalar(
            select(func.count(Job.id)).where(
                Job.source_id == source.id,
                Job.is_active == True,
            )
        ) or 0

        # Job mới trong tuần này (first_seen trong khoảng tuần)
        from datetime import datetime
        new_count = session.scalar(
            select(func.count(Job.id)).where(
                Job.source_id == source.id,
                Job.first_seen_at >= datetime.combine(week_start, datetime.min.time()),
                Job.first_seen_at <= datetime.combine(week_end,   datetime.max.time()),
            )
        ) or 0

        # Job đóng trong tuần này
        closed_count = session.scalar(
            select(func.count(Job.id)).where(
                Job.source_id == source.id,
                Job.is_active == False,
                Job.closed_at >= datetime.combine(week_start, datetime.min.time()),
                Job.closed_at <= datetime.combine(week_end,   datetime.max.time()),
            )
        ) or 0

        # Upsert snapshot
        snapshot = session.scalar(
            select(WeeklySnapshot).where(
                WeeklySnapshot.week_start == week_start,
                WeeklySnapshot.source_id  == source.id,
            )
        )

        if not snapshot:
            snapshot = WeeklySnapshot(
                week_start = week_start,
                week_end   = week_end,
                source_id  = source.id,
            )
            session.add(snapshot)

        snapshot.total_jobs  = active_count + closed_count
        snapshot.new_jobs    = new_count
        snapshot.closed_jobs = closed_count
        snapshot.active_jobs = active_count

        logger.info(
            f"[Snapshot] {source.name} | week {week_start} | "
            f"active={active_count} new={new_count} closed={closed_count}"
        )

    session.commit()


def main():
    parser = argparse.ArgumentParser(description="DA Job Market Vietnam Crawler")
    parser.add_argument("--source",  type=str, help="Run specific source: ybox|vietnamworks|topcv")
    parser.add_argument("--dry-run", action="store_true", help="Test crawlers without saving to DB")
    args = parser.parse_args()

    has_db = DATABASE_URL or (SUPABASE_URL and SUPABASE_KEY)
    if not has_db and not args.dry_run:
        logger.error("No database config: set SUPABASE_URL+SUPABASE_KEY or DATABASE_URL")
        sys.exit(1)

    if args.dry_run:
        logger.info("DRY RUN mode — no DB writes")
        # Chỉ test fetch, không ghi DB
        from crawlers.ybox import YBoxCrawler
        class FakeSession:
            def scalar(self, *a, **kw): return None
            def add(self, *a): pass
            def flush(self): pass
            def commit(self): pass
        logger.info("Testing YBox fetch...")
        # Không thể chạy đầy đủ dry-run mà không có Session thật
        logger.warning("Dry-run chưa hỗ trợ đầy đủ, cần DATABASE_URL")
        return

    summary = run_crawlers(args.source)

    print("\n" + "="*50)
    print("CRAWL SUMMARY")
    print("="*50)
    for source, result in summary.items():
        if "error" in result:
            print(f"  {source:15s} ERROR: {result['error']}")
        else:
            print(
                f"  {source:15s} "
                f"crawled={result.get('crawled', 0):4d} "
                f"new={result.get('new', 0):4d} "
                f"updated={result.get('updated', 0):4d} "
                f"closed={result.get('closed', 0):4d}"
            )
    print("="*50)


if __name__ == "__main__":
    main()
