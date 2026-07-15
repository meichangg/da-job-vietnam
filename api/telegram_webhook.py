"""
Webhook Telegram cho Vercel — phản hồi tức thì thay vì đợi polling 5 phút
qua GitHub Actions (xem .github/workflows/telegram_listener.yml, sẽ tắt
đi sau khi webhook này hoạt động ổn định vì Telegram không cho dùng đồng
thời cả webhook lẫn getUpdates cho cùng 1 bot).

Telegram gọi thẳng vào URL này (dạng POST) mỗi khi có tin nhắn/nút bấm mới,
nên không cần tự đi hỏi (poll) như telegram_bot.py.
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import telegram_bot as tb  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        # Xác thực request thật sự đến từ Telegram (không phải ai đó đoán ra URL)
        secret = self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        expected = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
        if expected and secret != expected:
            self.send_response(403)
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else b"{}"

        try:
            update = json.loads(body)
            self._process(update)
        except Exception as e:
            print(f"[telegram_webhook] Error: {e}")

        # Luôn trả 200 cho Telegram dù xử lý lỗi, tránh Telegram retry liên tục
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def _process(self, update: dict) -> None:
        callback = update.get("callback_query")
        if callback:
            tb.handle_callback(callback)
            return

        msg = update.get("message") or update.get("edited_message")
        if not msg or "text" not in msg:
            return

        chat_id = str(msg["chat"]["id"])
        text = msg["text"]

        if tb.TELEGRAM_CHAT_ID and chat_id != str(tb.TELEGRAM_CHAT_ID):
            print(f"[telegram_webhook] Bỏ qua chat lạ: {chat_id}")
            return

        if text.startswith("/"):
            tb.handle_command(chat_id, text)

    def do_GET(self):
        # Cho phép mở URL bằng trình duyệt để kiểm tra webhook còn sống không
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("DA Job Market Telegram webhook is running.".encode("utf-8"))
