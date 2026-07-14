"""
Điều khiển project qua lệnh Telegram (2 chiều) — bổ sung cho notify.py
(vốn chỉ gửi 1 chiều theo lịch).

Chạy định kỳ (polling mỗi ~5 phút qua GitHub Actions, xem
.github/workflows/telegram_listener.yml) để kiểm tra tin nhắn mới. Vì
GitHub Actions không có server chạy liên tục 24/7, đây là cách gần-thời-gian-thực
khả thi nhất mà không cần thêm hạ tầng (VPS/serverless function riêng).

Lệnh hỗ trợ:
    /crawl   - kích hoạt workflow crawl chính chạy ngay (không chờ đợi trong
               script này vì crawl mất nhiều phút, sẽ block lịch polling)
    /report  - xây và trả lời ngay báo cáo hiện tại (tổng job + job mới hôm nay)
    /status  - xem 5 lần crawl gần nhất (nguồn, kết quả, thời gian)
    /help    - danh sách lệnh
"""
import os
import sys

import httpx
from dotenv import load_dotenv
from loguru import logger

import notify  # tái dùng build_report() và _supabase_get()

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")  # chỉ chat này được ra lệnh

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO  = os.getenv("GITHUB_REPO", "")  # dạng "owner/repo"
CRAWL_WORKFLOW_FILE = "weekly_crawl.yml"

API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

HELP_TEXT = (
    "Các lệnh hỗ trợ:\n"
    "/crawl - kích hoạt crawl tất cả nguồn ngay (chạy nền, xem kết quả sau ~15-30 phút)\n"
    "/report - xem báo cáo job hiện tại\n"
    "/status - xem 5 lần crawl gần nhất\n"
    "/help - xem danh sách lệnh này"
)


def get_updates() -> list[dict]:
    resp = httpx.get(f"{API_BASE}/getUpdates", timeout=20)
    resp.raise_for_status()
    return resp.json().get("result", [])


def confirm_updates(last_update_id: int) -> None:
    """Báo Telegram đã xử lý xong tới update_id này để không nhận lại ở lần sau."""
    httpx.get(f"{API_BASE}/getUpdates", params={"offset": last_update_id + 1}, timeout=20)


def reply(chat_id: str, text: str) -> None:
    httpx.post(f"{API_BASE}/sendMessage", data={"chat_id": chat_id, "text": text}, timeout=20)


def trigger_crawl_workflow() -> str:
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return "Chưa cấu hình GITHUB_TOKEN/GITHUB_REPO nên không thể kích hoạt crawl từ xa."
    resp = httpx.post(
        f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/{CRAWL_WORKFLOW_FILE}/dispatches",
        headers={
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
        },
        json={"ref": "main"},
        timeout=20,
    )
    if resp.status_code == 204:
        return "🔄 Đã kích hoạt crawl tất cả nguồn. Kết quả sẽ có sau khoảng 15-30 phút, xem trên dashboard."
    return f"Kích hoạt crawl thất bại (HTTP {resp.status_code}): {resp.text[:200]}"


def _status_rows_supabase() -> list[dict]:
    raw = notify._supabase_get(
        "crawl_runs",
        "started_at,status,jobs_crawled,jobs_new,sources(name)",
        {"order": "started_at.desc", "limit": "5"},
    )
    return [
        {
            "started_at":   r.get("started_at", ""),
            "status":       r.get("status"),
            "jobs_crawled": r.get("jobs_crawled", 0),
            "jobs_new":     r.get("jobs_new", 0),
            "source":       (r.get("sources") or {}).get("name") or "?",
        }
        for r in raw
    ]


def _status_rows_postgres() -> list[dict]:
    import psycopg2
    import psycopg2.extras

    conn = psycopg2.connect(notify.DATABASE_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        """
        SELECT cr.started_at, cr.status, cr.jobs_crawled, cr.jobs_new, s.name AS source
        FROM crawl_runs cr LEFT JOIN sources s ON s.id = cr.source_id
        ORDER BY cr.started_at DESC LIMIT 5
        """
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


def build_status_text() -> str:
    if notify.SUPABASE_URL and notify.SUPABASE_KEY:
        rows = _status_rows_supabase()
    elif notify.DATABASE_URL:
        rows = _status_rows_postgres()
    else:
        return "Chưa cấu hình database."

    if not rows:
        return "Chưa có lịch sử crawl nào."

    lines = ["5 lần crawl gần nhất:"]
    for r in rows:
        started = str(r["started_at"])[:16]
        lines.append(
            f"- {started} | {r['source']} | {r['status']} | "
            f"crawled={r['jobs_crawled']} new={r['jobs_new']}"
        )
    return "\n".join(lines)


def handle_command(chat_id: str, text: str) -> None:
    command = text.strip().split()[0].lower()

    if command == "/crawl":
        reply(chat_id, trigger_crawl_workflow())
    elif command == "/report":
        reply(chat_id, notify.build_report())
    elif command == "/status":
        reply(chat_id, build_status_text())
    elif command in ("/help", "/start"):
        reply(chat_id, HELP_TEXT)
    else:
        reply(chat_id, f"Không nhận diện được lệnh '{text}'.\n\n{HELP_TEXT}")


def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        logger.error("Chưa cấu hình TELEGRAM_BOT_TOKEN")
        sys.exit(1)

    updates = get_updates()
    if not updates:
        logger.info("Không có tin nhắn mới")
        return

    last_update_id = updates[-1]["update_id"]

    for upd in updates:
        msg = upd.get("message") or upd.get("edited_message")
        if not msg or "text" not in msg:
            continue

        chat_id = str(msg["chat"]["id"])
        text    = msg["text"]

        if TELEGRAM_CHAT_ID and chat_id != str(TELEGRAM_CHAT_ID):
            logger.warning(f"Bỏ qua lệnh từ chat không xác định: {chat_id}")
            continue

        if text.startswith("/"):
            logger.info(f"Nhận lệnh: {text}")
            handle_command(chat_id, text)

    confirm_updates(last_update_id)


if __name__ == "__main__":
    main()
