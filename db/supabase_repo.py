"""
Supabase REST API repository — thay thế SQLAlchemy cho môi trường cloud.
Dùng httpx để gọi PostgREST API thay vì kết nối PostgreSQL trực tiếp.
"""
import re
from datetime import datetime, date
from typing import Optional
import httpx
from loguru import logger


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


class SimpleRecord:
    """Đối tượng nhẹ thay thế SQLAlchemy ORM model."""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

    def __repr__(self):
        return f"<Record {self.__dict__}>"


class SupabaseRepo:
    """
    Thay thế SQLAlchemy Session + repository functions.
    commit() và rollback() là no-op vì REST API tự commit.
    """

    def __init__(self, url: str, key: str):
        self._base = url.rstrip("/") + "/rest/v1"
        self._headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

    # ── HTTP helpers ──────────────────────────────────────────────────

    def _get(self, table: str, params) -> list:
        resp = httpx.get(
            f"{self._base}/{table}",
            headers=self._headers,
            params=params,
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()

    def _post(self, table: str, data: dict, prefer_extra: str = "") -> dict:
        headers = dict(self._headers)
        if prefer_extra:
            headers["Prefer"] = f"return=representation,{prefer_extra}"
        resp = httpx.post(
            f"{self._base}/{table}",
            headers=headers,
            json=data,
            timeout=20,
        )
        resp.raise_for_status()
        rows = resp.json()
        return rows[0] if rows else {}

    def _patch(self, table: str, params, data: dict):
        resp = httpx.patch(
            f"{self._base}/{table}",
            headers=self._headers,
            params=params,
            json=data,
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()

    # ── Session compatibility (no-op) ────────────────────────────────

    def commit(self): pass
    def rollback(self): pass

    # ── Repository methods ───────────────────────────────────────────

    def get_or_create_source(self, name: str, base_url: str) -> SimpleRecord:
        rows = self._get("sources", {"name": f"eq.{name}"})
        if rows:
            return SimpleRecord(**rows[0])
        row = self._post("sources", {"name": name, "base_url": base_url, "is_active": True})
        logger.info(f"[DB] Created source: {name}")
        return SimpleRecord(**row)

    def get_or_create_company(self, name: str) -> SimpleRecord:
        name = (name or "Unknown")[:250]
        slug = _slug(name)[:250]
        rows = self._get("companies", {"name_slug": f"eq.{slug}"})
        if rows:
            return SimpleRecord(**rows[0])
        row = self._post("companies", {"name": name, "name_slug": slug})
        return SimpleRecord(**row)

    def get_or_create_skill(self, name: str) -> SimpleRecord:
        rows = self._get("skills", {"name": f"eq.{name}"})
        if rows:
            return SimpleRecord(**rows[0])
        row = self._post("skills", {"name": name})
        return SimpleRecord(**row)

    def upsert_job(self, data: dict) -> tuple:
        rows = self._get("jobs", [
            ("external_id", f"eq.{data['external_id']}"),
            ("source_id",   f"eq.{data['source_id']}"),
        ])
        now = datetime.utcnow().isoformat()

        if rows:
            job_row = rows[0]
            self._patch("jobs", [("id", f"eq.{job_row['id']}")], {
                "last_seen_at": now,
                "is_active":    True,
                "url":          data.get("url") or job_row.get("url"),
                "salary_raw":   data.get("salary_raw") or job_row.get("salary_raw"),
                "salary_min":   data.get("salary_min") or job_row.get("salary_min"),
                "salary_max":   data.get("salary_max") or job_row.get("salary_max"),
            })
            return SimpleRecord(**job_row), False

        insert = {k: v for k, v in data.items() if v is not None}
        insert["first_seen_at"] = now
        insert["last_seen_at"]  = now
        insert["is_active"]     = True
        if "title" in insert:
            insert["title"] = insert["title"][:250]
        row = self._post("jobs", insert)
        return SimpleRecord(**row), True

    def attach_skills(self, job: SimpleRecord, skill_names: list[str]):
        for name in skill_names:
            try:
                skill = self.get_or_create_skill(name)
                exists = self._get("job_skills", [
                    ("job_id",   f"eq.{job.id}"),
                    ("skill_id", f"eq.{skill.id}"),
                ])
                if not exists:
                    self._post("job_skills", {"job_id": job.id, "skill_id": skill.id})
            except Exception as e:
                logger.debug(f"[DB] attach_skill '{name}' skipped: {e}")

    def mark_closed_jobs(self, source_id: int, seen_external_ids: set) -> list:
        rows = self._get("jobs", [
            ("source_id", f"eq.{source_id}"),
            ("is_active", "eq.true"),
        ])
        now = datetime.utcnow().isoformat()
        closed = []
        for row in rows:
            if row["external_id"] not in seen_external_ids:
                self._patch("jobs", [("id", f"eq.{row['id']}")], {
                    "is_active": False,
                    "closed_at": now,
                })
                logger.debug(f"Closed: {row['title']} ({row['external_id']})")
                closed.append(SimpleRecord(**row))
        return closed

    def start_crawl_run(self, source_id: int, triggered_by: str = "scheduler") -> SimpleRecord:
        try:
            row = self._post("crawl_runs", {
                "source_id":    source_id,
                "triggered_by": triggered_by,
                "status":       "running",
                "started_at":   datetime.utcnow().isoformat(),
            })
            return SimpleRecord(**row) if row else SimpleRecord(id=0)
        except Exception:
            return SimpleRecord(id=0)

    def finish_crawl_run(self, run: SimpleRecord, status: str, jobs_crawled: int = 0,
                         jobs_new: int = 0, jobs_updated: int = 0,
                         error_message: Optional[str] = None):
        if not getattr(run, "id", 0):
            return
        data = {
            "finished_at":  datetime.utcnow().isoformat(),
            "status":       status,
            "jobs_crawled": jobs_crawled,
            "jobs_new":     jobs_new,
            "jobs_updated": jobs_updated,
        }
        if error_message:
            data["error_message"] = error_message
        try:
            self._patch("crawl_runs", [("id", f"eq.{run.id}")], data)
        except Exception:
            pass

    def get_all_sources(self) -> list:
        rows = self._get("sources", {"is_active": "eq.true"})
        return [SimpleRecord(**r) for r in rows]

    def build_weekly_snapshot(self, week_start: date, week_end: date):
        sources = self.get_all_sources()
        ws = week_start.isoformat()
        we = week_end.isoformat() + "T23:59:59"

        for source in sources:
            active_rows = self._get("jobs", [
                ("source_id", f"eq.{source.id}"),
                ("is_active", "eq.true"),
                ("select",    "id"),
            ])
            new_rows = self._get("jobs", [
                ("source_id",    f"eq.{source.id}"),
                ("first_seen_at", f"gte.{ws}"),
                ("first_seen_at", f"lte.{we}"),
                ("select",       "id"),
            ])
            closed_rows = self._get("jobs", [
                ("source_id", f"eq.{source.id}"),
                ("is_active", "eq.false"),
                ("closed_at", f"gte.{ws}"),
                ("closed_at", f"lte.{we}"),
                ("select",    "id"),
            ])

            active  = len(active_rows)
            new     = len(new_rows)
            closed  = len(closed_rows)

            existing = self._get("weekly_snapshots", [
                ("week_start", f"eq.{week_start.isoformat()}"),
                ("source_id",  f"eq.{source.id}"),
            ])
            snap_data = {
                "week_start":  week_start.isoformat(),
                "week_end":    week_end.isoformat(),
                "source_id":   source.id,
                "active_jobs": active,
                "new_jobs":    new,
                "closed_jobs": closed,
                "total_jobs":  active + closed,
            }
            if existing:
                self._patch("weekly_snapshots",
                            [("id", f"eq.{existing[0]['id']}")], snap_data)
            else:
                self._post("weekly_snapshots", snap_data)

            logger.info(
                f"[Snapshot] {source.name} | week {week_start} | "
                f"active={active} new={new} closed={closed}"
            )
