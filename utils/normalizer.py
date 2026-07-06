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


# Một số nguồn (vd VietnamWorks) trả sẵn tag kỹ năng dạng free-text thay vì
# qua extract_skills(), nên bị lệch chữ hoa/thường giữa các lần khác nhau
# (vd "PowerBI" vs "Power BI", "Sql" vs "SQL") -> tách thành 2 skill khác nhau
# trong DB. normalize_skill_name() gộp các biến thể đã biết về 1 tên chuẩn.
SKILL_ALIASES = {
    "sql":                    "SQL",
    "mysql":                  "MySQL",
    "postgresql":             "PostgreSQL",
    "powerbi":                "Power BI",
    "power bi":               "Power BI",
    "python":                 "Python",
    "pyspark":                "PySpark",
    "tableau":                "Tableau",
    "excel":                  "Excel",
    "business intelligence":  "Business Intelligence",
    "business analysis":      "Business Analysis",
    "data analysis":          "Data Analysis",
    "data analytics":         "Data Analytics",
    "analytical skills":      "Analytical Skills",
    "stakeholder management": "Stakeholder Management",
    "english":                "English",
    "oracle":                 "Oracle",
}


def normalize_skill_name(name: str) -> str:
    if not name:
        return name
    cleaned = re.sub(r"\s+", " ", name.strip())
    key = cleaned.lower()
    if key in SKILL_ALIASES:
        return SKILL_ALIASES[key]
    # Tag toàn chữ hoa kiểu 'PYTHON' -> chuyển Title Case cho dễ đọc/nhất quán
    if cleaned.isupper() and len(cleaned) > 4:
        return cleaned.title()
    return cleaned


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


LOCATION_KEYWORDS = [
    (["hà nội", "ha noi", "hanoi"],                                   "Hà Nội"),
    (["hồ chí minh", "ho chi minh", "hcm", "sài gòn", "saigon", "củ chi"], "TP.HCM"),
    (["đà nẵng", "da nang", "danang"],                                 "Đà Nẵng"),
    (["cần thơ", "can tho"],                                          "Cần Thơ"),
    (["remote"],                                                       "Remote"),
]


def normalize_location(location: str) -> str:
    """Gộp các biến thể ghi khác nhau của cùng 1 địa điểm (vd 'Ho Chi Minh City,
    Vietnam', 'Ho Chi Minh City Metropolitan Area', 'Hồ Chí Minh (mới)' đều
    thành 'TP.HCM') bằng so khớp chứa từ khóa thay vì so khớp tuyệt đối."""
    if not location:
        return "Unknown"
    loc = location.strip()
    loc_lower = loc.lower()

    # Tin đăng nhiều địa điểm / remote cùng lúc — gộp vào "Toàn quốc"
    if "online" in loc_lower or loc.count("/") >= 2:
        return "Toàn quốc"

    for keywords, normalized in LOCATION_KEYWORDS:
        if any(k in loc_lower for k in keywords):
            return normalized

    if loc_lower in ("vietnam", "việt nam", "toàn quốc"):
        return "Toàn quốc"

    return loc
