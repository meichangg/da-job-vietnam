import re
from typing import Optional

DA_TITLE_KEYWORDS = [
    "data analyst", "phân tích dữ liệu", "business analyst", "bi analyst",
    "data analytics", "analytics engineer", "reporting analyst",
    "business intelligence", "bi developer", "data reporting",
    "insight analyst", "product analyst", "marketing analyst",
    "financial analyst", "risk analyst", "operations analyst",
]

SKILL_KEYWORDS = {
    "Python":     ["python"],
    "SQL":        ["sql", "mysql", "postgresql", "mssql", "sql server"],
    "Power BI":   ["power bi", "powerbi"],
    "Tableau":    ["tableau"],
    "Excel":      ["excel", "advanced excel"],
    "R":          [r"\br\b", "r programming", "r language"],
    "Looker":     ["looker", "lookml"],
    "Google Analytics": ["google analytics", "ga4"],
    "Spark":      ["spark", "pyspark"],
    "Airflow":    ["airflow"],
    "dbt":        [r"\bdbt\b"],
    "BigQuery":   ["bigquery"],
    "Redshift":   ["redshift"],
    "Snowflake":  ["snowflake"],
    "AWS":        [r"\baws\b", "amazon web services"],
    "GCP":        [r"\bgcp\b", "google cloud"],
    "Azure":      ["azure"],
    "Statistics": ["statistics", "thống kê", "statistical"],
    "Machine Learning": ["machine learning", "ml", "sklearn", "scikit"],
}

LEVEL_PATTERNS = {
    "intern":   ["intern", "thực tập", "internship"],
    "fresher":  ["fresher", "fresh graduate", "mới tốt nghiệp", "entry level", "entry-level"],
    "junior":   ["junior", "j1", "j2", r"\b1[\-–]2 year", r"\b0[\-–]2 year"],
    "mid":      ["middle", "mid-level", r"\b2[\-–]4 year", r"\b3[\-–]5 year"],
    "senior":   ["senior", "sr\.", r"\b5\+ year", r"\b4[\-–]7 year"],
    "lead":     ["lead", "manager", "head of", "principal", "staff"],
}


def is_da_job(title: str) -> bool:
    title_lower = title.lower()
    return any(kw in title_lower for kw in DA_TITLE_KEYWORDS)


def normalize_title(title: str) -> str:
    title = title.strip()
    title = re.sub(r"\s+", " ", title)
    return title


def extract_level(title: str, description: str = "") -> Optional[str]:
    text = (title + " " + description).lower()
    for level, patterns in LEVEL_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return level
    return None


def extract_skills(description: str) -> list[str]:
    found = []
    text = description.lower()
    for skill, patterns in SKILL_KEYWORDS.items():
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                found.append(skill)
                break
    return found


def parse_salary(salary_raw: str) -> tuple[Optional[int], Optional[int]]:
    """
    Parse các dạng lương:
      '15 - 25 triệu'  → (15_000_000, 25_000_000)
      '1000 - 2000 USD' → (25_000_000, 50_000_000)  # ~25k VND/USD
      'Thỏa thuận'     → (None, None)
    """
    if not salary_raw:
        return None, None

    raw = salary_raw.lower().strip()

    if any(x in raw for x in ["thỏa thuận", "competitive", "negotiable", "thoả thuận"]):
        return None, None

    USD_RATE = 25_000

    nums = re.findall(r"[\d,\.]+", raw)
    nums = [float(n.replace(",", "")) for n in nums if n]

    if not nums:
        return None, None

    is_usd = "usd" in raw or "$" in raw
    multiplier = 1_000_000 if "triệu" in raw or "million" in raw else 1

    if is_usd:
        multiplier = USD_RATE

    if len(nums) == 1:
        val = int(nums[0] * multiplier)
        return val, val
    else:
        low = int(min(nums[0], nums[1]) * multiplier)
        high = int(max(nums[0], nums[1]) * multiplier)
        return low, high


def normalize_location(location: str) -> str:
    if not location:
        return "Unknown"
    loc = location.strip()
    mapping = {
        "hà nội": "Hà Nội",
        "ha noi": "Hà Nội",
        "hanoi": "Hà Nội",
        "hồ chí minh": "TP.HCM",
        "ho chi minh": "TP.HCM",
        "hcm": "TP.HCM",
        "tp.hcm": "TP.HCM",
        "tp hcm": "TP.HCM",
        "saigon": "TP.HCM",
        "đà nẵng": "Đà Nẵng",
        "da nang": "Đà Nẵng",
        "remote": "Remote",
        "toàn quốc": "Toàn quốc",
    }
    return mapping.get(loc.lower(), loc)
