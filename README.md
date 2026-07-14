# DA Job Market Vietnam

Hệ thống tự động thu thập, lưu trữ và trực quan hóa dữ liệu tuyển dụng Data Analyst / Business Analyst / BI tại Việt Nam từ 4 nguồn: **TopCV, VietnamWorks, YBox, LinkedIn**.

## Kiến trúc

```
crawlers/   -> code crawl từng nguồn (base_crawler.py là lớp cha dùng chung)
db/         -> schema (models.py) + tầng thao tác database (2 cách: Postgres trực tiếp / Supabase REST)
utils/      -> chuẩn hóa dữ liệu (title, location, skill, level, lương)
dashboard/  -> app Streamlit trực quan hóa dữ liệu
scripts/    -> script phụ, độc lập với project (vd linkedin_standalone.py)
main.py     -> entry point chạy crawler
.github/workflows/weekly_crawl.yml -> tự động crawl hàng ngày qua GitHub Actions
```

## 1. Yêu cầu

- Python 3.11+
- Tài khoản [Supabase](https://supabase.com) (free tier đủ dùng) — dùng làm database Postgres

## 2. Cài đặt

```bash
git clone <repo-url>
cd da-job-market

python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS/Linux

pip install -r requirements.txt
python -m playwright install chromium   # bắt buộc cho crawler TopCV
```

## 3. Cấu hình

```bash
copy .env.example .env          # Windows
# cp .env.example .env          # macOS/Linux
```

Mở `.env` và điền:

- **`DATABASE_URL`** — connection string Postgres của Supabase (Project Settings → Database → Connection string). Dùng cho lần chạy đầu tiên để tự tạo bảng, và khi chạy crawler/dashboard local.
- **`SUPABASE_URL`** / **`SUPABASE_KEY`** — lấy ở Project Settings → API. Dùng khi chạy trên GitHub Actions hoặc deploy dashboard lên Streamlit Cloud (không cần lộ mật khẩu database trực tiếp).

Chỉ cần điền 1 trong 2 cách để chạy crawler; nhưng **dashboard chỉ hỗ trợ `SUPABASE_URL`+`SUPABASE_KEY`** (không đọc `DATABASE_URL`).

## 4. Khởi tạo database (chạy 1 lần đầu tiên)

Với `DATABASE_URL` đã điền trong `.env`, chạy thử 1 crawler bất kỳ — các bảng (`jobs`, `companies`, `sources`, `skills`...) sẽ **tự động được tạo**:

```bash
python main.py --source ybox
```

## 5. Chạy crawler

```bash
python main.py                    # chạy tất cả 4 nguồn
python main.py --source topcv     # chạy 1 nguồn cụ thể: ybox | vietnamworks | topcv | linkedin
```

## 6. Chạy dashboard

```bash
streamlit run dashboard/app.py
```

Mở trình duyệt vào `http://localhost:8501`.

## 7. Tự động hóa hàng ngày (tùy chọn)

Project có sẵn workflow GitHub Actions (`.github/workflows/weekly_crawl.yml`) chạy crawler mỗi ngày lúc 8h sáng (giờ VN). Để bật:

1. Vào repo trên GitHub → **Settings → Secrets and variables → Actions**
2. Thêm 2 secret: `SUPABASE_URL`, `SUPABASE_KEY`
3. Workflow tự chạy theo lịch, hoặc vào tab **Actions** → chọn workflow → **Run workflow** để chạy tay.

## 8. Deploy dashboard lên Streamlit Cloud (tùy chọn)

1. Push code lên GitHub, vào [share.streamlit.io](https://share.streamlit.io) → **New app** → chọn repo, file `dashboard/app.py`.
2. Trong **App settings → Secrets**, thêm:
   ```toml
   SUPABASE_URL = "https://xxxx.supabase.co"
   SUPABASE_KEY = "your-anon-or-service-key"
   ```

## 9. Thông báo hàng ngày qua Telegram + Email (tùy chọn)

`notify.py` đọc dữ liệu đã crawl (không tự crawl) và gửi báo cáo: tổng số job đang tuyển, danh sách job mới trong ngày kèm link. Workflow `.github/workflows/daily_notify.yml` chạy sẵn lúc **15h chiều (giờ VN)** mỗi ngày.

**Thiết lập Telegram:**
1. Mở Telegram, chat với **@BotFather** → gõ `/newbot`, làm theo hướng dẫn để lấy `TELEGRAM_BOT_TOKEN`.
2. Nhắn bất kỳ tin nào cho bot vừa tạo, sau đó mở trình duyệt vào:
   `https://api.telegram.org/bot<TOKEN>/getUpdates` — lấy giá trị `chat.id` trong JSON trả về, đó là `TELEGRAM_CHAT_ID`.

**Thiết lập Email (Gmail):**
1. Bật xác minh 2 bước (2FA) cho tài khoản Gmail nếu chưa bật.
2. Vào [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords), tạo 1 "App Password" mới — dùng mật khẩu này cho `SMTP_PASSWORD` (không dùng mật khẩu Gmail thường).

**Bật trên GitHub Actions**: vào **Settings → Secrets and variables → Actions**, thêm các secret: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `SMTP_EMAIL`, `SMTP_PASSWORD`, `NOTIFY_EMAIL_TO` (cùng với `SUPABASE_URL`/`SUPABASE_KEY` đã có).

**Test local trước khi push:**
```bash
python notify.py --dry-run   # chỉ in ra nội dung, không gửi đi đâu
python notify.py             # gửi thật (cần đã điền đủ biến trong .env)
```

## 10. Điều khiển qua lệnh Telegram (tùy chọn)

Ngoài thông báo 1 chiều (`notify.py`), `telegram_bot.py` cho phép **ra lệnh 2 chiều** qua chat với bot:

- `/crawl` — kích hoạt workflow crawl chính chạy ngay (không đợi trong lệnh này vì crawl mất nhiều phút; trả lời ngay là "đã kích hoạt", xem kết quả trên dashboard sau ~15-30 phút)
- `/report` — trả lời ngay báo cáo job hiện tại
- `/status` — xem 5 lần crawl gần nhất
- `/help` — danh sách lệnh

Chạy qua workflow `.github/workflows/telegram_listener.yml`, kiểm tra tin nhắn mới **mỗi 5 phút** (đây là polling, không phải phản hồi tức thì — do project không có server chạy liên tục 24/7). Vì lý do bảo mật, bot **chỉ nhận lệnh từ đúng `TELEGRAM_CHAT_ID`** đã cấu hình, tin nhắn từ chat khác sẽ bị bỏ qua.

Không cần thêm secret nào ngoài các secret Telegram đã có ở mục 9 — `GITHUB_TOKEN` được GitHub Actions tự cấp, chỉ cần workflow có khai báo `permissions: actions: write` (đã có sẵn trong file).

Test local:
```bash
python telegram_bot.py    # xử lý 1 lần các lệnh đang chờ, dùng để test trước khi đẩy lên GitHub
```

## Lưu ý / hạn chế đã biết

- **TopCV**: dùng Cloudflare chống bot, thỉnh thoảng 1 lượt crawl bị chặn hoàn toàn (đã có retry tự động, nhưng không đảm bảo 100%). Đây là nguồn phụ, không ảnh hưởng lớn tới tổng dữ liệu.
- **LinkedIn**: dùng API "guest" công khai (không cần đăng nhập) nên không có `LINKEDIN_EMAIL`/`PASSWORD` — nếu vẫn thấy biến này ở phiên bản `.env` cũ thì có thể xóa, không còn dùng.
- Muốn crawl nhanh LinkedIn mà không cần cả project (không cần database) — dùng `scripts/linkedin_standalone.py` (chỉ cần `pip install httpx beautifulsoup4`).
