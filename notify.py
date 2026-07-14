"""
Gửi báo cáo tổng hợp job hàng ngày qua Telegram + Email.
Chạy độc lập với main.py — chỉ ĐỌC dữ liệu đã có trong DB (Supabase REST API),
không tự crawl. Chạy sau lần crawl buổi sáng (main.py) để báo cáo số liệu mới nhất.

Usage:
    python notify.py             # gửi cả Telegram + Email (tuỳ theo đã cấu hình)
    python notify.py --dry-run   # chỉ in ra nội dung, không gửi đi đâu cả
"""
import argparse
import os
import smtplib
from datetime import date, datetime, timezone
from email.mime.text import MIMEText

import httpx
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

SMTP_HOST       = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT       = int(os.getenv("SMTP_PORT", "587"))
SMTP_EMAIL      = os.getenv("SMTP_EMAIL", "")
SMTP_PASSWORD   = os.getenv("SMTP_PASSWORD", "")
NOTIFY_EMAIL_TO = os.getenv("NOTIFY_EMAIL_TO", "")

MAX_JOBS_LISTED = 25  # tránh tin nhắn/email quá dài nếu 1 ngày có quá nhiều job mới


def _supabase_get(table: str, select: str, extra_params: dict) -> list:
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    }
    params = {"select": select, "limit": "2000", **extra_params}
    resp = httpx.get(f"{SUPABASE_URL}/rest/v1/{table}", headers=headers, params=params, timeout=20)
    resp.raise_for_status()
    return resp.json()


VALID_CATEGORIES = {"DA", "DS", "AI"}


def _postgres_get(today_str: str, category: str | None = None) -> tuple[int, list[dict]]:
    import psycopg2
    import psycopg2.extras

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    if category:
        cur.execute("SELECT count(*) AS c FROM jobs WHERE is_active = true AND category = %s", (category,))
    else:
        cur.execute("SELECT count(*) AS c FROM jobs WHERE is_active = true")
    active_count = cur.fetchone()["c"]

    query = """
        SELECT j.title, j.url, c.name AS company, s.name AS source
        FROM jobs j
        LEFT JOIN companies c ON c.id = j.company_id
        LEFT JOIN sources   s ON s.id = j.source_id
        WHERE j.is_active = true AND j.first_seen_at >= %s
    """
    params: list = [today_str]
    if category:
        query += " AND j.category = %s"
        params.append(category)

    cur.execute(query, params)
    new_jobs = [dict(row) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return active_count, new_jobs


def build_report(category: str | None = None) -> str:
    if category:
        category = category.strip().upper()
        if category not in VALID_CATEGORIES:
            return f"Nhóm ngành '{category}' không hợp lệ. Chọn 1 trong: {', '.join(sorted(VALID_CATEGORIES))}"

    today_str = date.today().isoformat()
    cat_filter = {"category": f"eq.{category}"} if category else {}

    if SUPABASE_URL and SUPABASE_KEY:
        active_jobs = _supabase_get("jobs", "id", {"is_active": "eq.true", **cat_filter})
        raw_new = _supabase_get(
            "jobs",
            "title,url,first_seen_at,companies(name),sources(name)",
            {"is_active": "eq.true", "first_seen_at": f"gte.{today_str}", **cat_filter},
        )
        active_count = len(active_jobs)
        new_jobs = [
            {
                "title":   j["title"],
                "url":     j["url"],
                "company": (j.get("companies") or {}).get("name"),
                "source":  (j.get("sources") or {}).get("name"),
            }
            for j in raw_new
        ]
    elif DATABASE_URL:
        active_count, new_jobs = _postgres_get(today_str, category)
    else:
        raise RuntimeError("Chưa cấu hình SUPABASE_URL+SUPABASE_KEY hoặc DATABASE_URL trong .env")

    label = f"({category})" if category else "(tất cả nhóm ngành)"
    lines = [
        f"📊 Báo cáo thị trường {label} — {today_str}",
        f"Tổng số job đang tuyển: {active_count}",
        f"Job mới thêm hôm nay: {len(new_jobs)}",
        "",
    ]

    if new_jobs:
        lines.append("Danh sách job mới:")
        for j in new_jobs[:MAX_JOBS_LISTED]:
            company = j.get("company") or "Unknown"
            source  = j.get("source") or ""
            lines.append(f"- {j['title']} ({company}, {source})")
            lines.append(f"  {j['url']}")
        remaining = len(new_jobs) - MAX_JOBS_LISTED
        if remaining > 0:
            lines.append(f"... và {remaining} job khác, xem đầy đủ trên dashboard.")
    else:
        lines.append("Không có job mới nào hôm nay.")

    return "\n".join(lines)


def send_telegram(text: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("[Telegram] Chưa cấu hình TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID — bỏ qua")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    resp = httpx.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=20)
    resp.raise_for_status()
    logger.success("[Telegram] Đã gửi báo cáo")


def send_email(subject: str, text: str) -> None:
    if not SMTP_EMAIL or not SMTP_PASSWORD or not NOTIFY_EMAIL_TO:
        logger.warning("[Email] Chưa cấu hình SMTP_EMAIL/SMTP_PASSWORD/NOTIFY_EMAIL_TO — bỏ qua")
        return
    msg = MIMEText(text, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = SMTP_EMAIL
    msg["To"] = NOTIFY_EMAIL_TO

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
        server.starttls()
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        server.send_message(msg)
    logger.success("[Email] Đã gửi báo cáo")


def main():
    parser = argparse.ArgumentParser(description="Gửi báo cáo job hàng ngày qua Telegram/Email")
    parser.add_argument("--dry-run", action="store_true", help="Chỉ in ra nội dung, không gửi")
    parser.add_argument("--category", type=str, default=None, help="Lọc theo nhóm ngành: DA | DS | AI")
    args = parser.parse_args()

    text = build_report(args.category)

    if args.dry_run:
        print(text)
        return

    send_telegram(text)
    label = f" ({args.category})" if args.category else ""
    send_email(f"[DA Job Market] Báo cáo{label} {date.today().isoformat()}", text)


if __name__ == "__main__":
    main()
