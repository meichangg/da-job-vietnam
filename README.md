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

## Lưu ý / hạn chế đã biết

- **TopCV**: dùng Cloudflare chống bot, thỉnh thoảng 1 lượt crawl bị chặn hoàn toàn (đã có retry tự động, nhưng không đảm bảo 100%). Đây là nguồn phụ, không ảnh hưởng lớn tới tổng dữ liệu.
- **LinkedIn**: dùng API "guest" công khai (không cần đăng nhập) nên không có `LINKEDIN_EMAIL`/`PASSWORD` — nếu vẫn thấy biến này ở phiên bản `.env` cũ thì có thể xóa, không còn dùng.
- Muốn crawl nhanh LinkedIn mà không cần cả project (không cần database) — dùng `scripts/linkedin_standalone.py` (chỉ cần `pip install httpx beautifulsoup4`).
