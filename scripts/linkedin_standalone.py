"""
LinkedIn job crawler — bản độc lập, không phụ thuộc phần còn lại của project
(không cần database, không cần BaseCrawler). Chỉ cần cài:

    pip install httpx beautifulsoup4

Chạy:
    python linkedin_standalone.py
    python linkedin_standalone.py --keywords "data analyst,business analyst" --location Vietnam --pages 3
    python linkedin_standalone.py --out jobs.csv

Dùng API "guest" công khai của LinkedIn (không cần đăng nhập) — cùng API
phục vụ trang tìm việc cho người dùng chưa đăng nhập, nên không có rủi ro
tài khoản cá nhân bị khóa/checkpoint như khi tự động hóa đăng nhập.
"""
import argparse
import csv
import json
import re
import sys
import time
from dataclasses import dataclass, asdict

import httpx
from bs4 import BeautifulSoup

API_URL   = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
PAGE_SIZE = 25


@dataclass
class Job:
    job_id:   str
    title:    str
    company:  str
    location: str
    url:      str


def fetch_jobs(keywords: list[str], location: str, max_pages: int, delay: float) -> list[Job]:
    client = httpx.Client(
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8",
        },
        timeout=20,
    )

    all_jobs: dict[str, Job] = {}

    for term in keywords:
        print(f"Đang tìm: '{term}'...", file=sys.stderr)

        for page in range(max_pages):
            params = {
                "keywords": term,
                "location": location,
                "f_TPR":    "r604800",  # 7 ngày gần nhất
                "start":    page * PAGE_SIZE,
            }
            resp = client.get(API_URL, params=params)
            if resp.status_code != 200:
                print(f"  Trang {page}: HTTP {resp.status_code}, dừng.", file=sys.stderr)
                break

            soup  = BeautifulSoup(resp.text, "html.parser")
            cards = soup.select("div.base-card")
            if not cards:
                break

            for card in cards:
                job = _parse_card(card)
                if job:
                    all_jobs[job.job_id] = job

            print(f"  Trang {page}: {len(cards)} job", file=sys.stderr)

            if len(cards) < PAGE_SIZE:
                break
            time.sleep(delay)

        time.sleep(delay)

    return list(all_jobs.values())


def _parse_card(card) -> Job | None:
    try:
        urn   = card.get("data-entity-urn", "")
        id_m  = re.search(r":(\d+)$", urn)

        link_el = card.select_one("a.base-card__full-link, a")
        href    = link_el.get("href", "") if link_el else ""
        url     = href.split("?")[0]
        # LinkedIn hay trả subdomain theo quốc gia (vn.linkedin.com...) không ổn định
        url = re.sub(r"^https://[a-z]{2,3}\.linkedin\.com/", "https://www.linkedin.com/", url)

        job_id = id_m.group(1) if id_m else ""
        if not job_id:
            m = re.search(r"-(\d+)(?:\?|$)", href)
            job_id = m.group(1) if m else ""

        title_el   = card.select_one(".base-search-card__title, h3")
        company_el = card.select_one(".base-search-card__subtitle, h4")
        loc_el     = card.select_one(".job-search-card__location")

        title   = title_el.get_text(strip=True)   if title_el   else ""
        company = company_el.get_text(strip=True) if company_el else "Unknown"
        loc     = loc_el.get_text(strip=True)     if loc_el     else ""

        if not title or not job_id or not url:
            return None

        return Job(job_id=job_id, title=title, company=company, location=loc, url=url)
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser(description="Crawl job LinkedIn (không cần đăng nhập)")
    parser.add_argument("--keywords", type=str, default="data analyst,business analyst,bi analyst",
                         help="Danh sách từ khóa, cách nhau bởi dấu phẩy")
    parser.add_argument("--location", type=str, default="Vietnam")
    parser.add_argument("--pages",    type=int, default=3, help="Số trang tối đa mỗi từ khóa (25 job/trang)")
    parser.add_argument("--delay",    type=float, default=2.0, help="Giây nghỉ giữa các request")
    parser.add_argument("--out",      type=str, default=None, help="Đường dẫn file .csv hoặc .json để lưu kết quả")
    args = parser.parse_args()

    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    jobs = fetch_jobs(keywords, args.location, args.pages, args.delay)

    print(f"\nTổng cộng: {len(jobs)} job\n", file=sys.stderr)

    if args.out and args.out.endswith(".json"):
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump([asdict(j) for j in jobs], f, ensure_ascii=False, indent=2)
        print(f"Đã lưu vào {args.out}", file=sys.stderr)
    elif args.out and args.out.endswith(".csv"):
        with open(args.out, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=["job_id", "title", "company", "location", "url"])
            writer.writeheader()
            for j in jobs:
                writer.writerow(asdict(j))
        print(f"Đã lưu vào {args.out}", file=sys.stderr)
    else:
        for j in jobs:
            print(f"{j.title} | {j.company} | {j.location} | {j.url}")


if __name__ == "__main__":
    main()
