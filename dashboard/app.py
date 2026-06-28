"""
DA Job Market Dashboard — Vietnam
Streamlit app đọc dữ liệu từ PostgreSQL (Supabase) và hiển thị phân tích.
"""
import os
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(
    page_title="DA Job Market Vietnam",
    page_icon="📊",
    layout="wide",
)

# ─────────────────────────────────────────────────────────
# Database helpers
# ─────────────────────────────────────────────────────────

@st.cache_resource
def get_engine():
    # Streamlit Cloud: đọc từ st.secrets trước, fallback sang os.getenv (local)
    url = st.secrets.get("DATABASE_URL") if hasattr(st, "secrets") else None
    if not url:
        url = os.getenv("DATABASE_URL")
    if not url:
        st.error("DATABASE_URL not set. Add it in Streamlit Cloud Secrets or .env file.")
        st.stop()
    return create_engine(url, pool_pre_ping=True)


@st.cache_data(ttl=300)
def load_jobs() -> pd.DataFrame:
    engine = get_engine()
    query = """
        SELECT
            j.id, j.title, j.title_normalized, j.location, j.level,
            j.salary_min, j.salary_max, j.salary_raw, j.is_active,
            j.first_seen_at, j.last_seen_at, j.closed_at,
            c.name   AS company,
            s.name   AS source
        FROM jobs j
        LEFT JOIN companies c ON j.company_id = c.id
        LEFT JOIN sources   s ON j.source_id  = s.id
        ORDER BY j.first_seen_at DESC
    """
    with engine.connect() as conn:
        return pd.read_sql(text(query), conn, parse_dates=["first_seen_at", "last_seen_at", "closed_at"])


@st.cache_data(ttl=300)
def load_skills() -> pd.DataFrame:
    engine = get_engine()
    query = """
        SELECT sk.name AS skill, COUNT(*) AS count
        FROM job_skills js
        JOIN skills sk ON js.skill_id = sk.id
        GROUP BY sk.name
        ORDER BY count DESC
    """
    with engine.connect() as conn:
        return pd.read_sql(text(query), conn)


@st.cache_data(ttl=300)
def load_weekly_snapshots() -> pd.DataFrame:
    engine = get_engine()
    query = """
        SELECT
            ws.week_start, ws.active_jobs, ws.new_jobs, ws.closed_jobs,
            s.name AS source
        FROM weekly_snapshots ws
        LEFT JOIN sources s ON ws.source_id = s.id
        ORDER BY ws.week_start, s.name
    """
    with engine.connect() as conn:
        return pd.read_sql(text(query), conn, parse_dates=["week_start"])


# ─────────────────────────────────────────────────────────
# Load data
# ─────────────────────────────────────────────────────────

df_jobs    = load_jobs()
df_skills  = load_skills()
df_weekly  = load_weekly_snapshots()

# ─────────────────────────────────────────────────────────
# Header
# ─────────────────────────────────────────────────────────

st.title("📊 Thị trường tuyển dụng Data Analyst - Việt Nam")
st.caption("Dữ liệu crawl từ TopCV · VietnamWorks · YBox · LinkedIn")

# ─────────────────────────────────────────────────────────
# KPI cards
# ─────────────────────────────────────────────────────────

total_jobs   = len(df_jobs)
active_jobs  = df_jobs["is_active"].sum()
closed_jobs  = total_jobs - active_jobs
sources      = df_jobs["source"].nunique()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Tổng số jobs", total_jobs)
c2.metric("Đang tuyển dụng", int(active_jobs))
c3.metric("Đã đóng", int(closed_jobs))
c4.metric("Nguồn dữ liệu", sources)

st.divider()

# ─────────────────────────────────────────────────────────
# Row 1: Phân bổ theo nguồn & theo level
# ─────────────────────────────────────────────────────────

col1, col2 = st.columns(2)

with col1:
    st.subheader("Job theo nguồn tuyển dụng")
    by_source = df_jobs.groupby("source").size().reset_index(name="count")
    fig = px.pie(by_source, names="source", values="count",
                 color_discrete_sequence=px.colors.qualitative.Set2)
    fig.update_traces(textposition="inside", textinfo="percent+label")
    st.plotly_chart(fig, use_container_width=True)

with col2:
    st.subheader("Phân bổ theo cấp bậc")
    level_df = df_jobs[df_jobs["level"].notna()]
    if len(level_df):
        by_level = level_df.groupby("level").size().reset_index(name="count")
        fig2 = px.bar(by_level.sort_values("count", ascending=True),
                      x="count", y="level", orientation="h",
                      color="level",
                      color_discrete_sequence=px.colors.qualitative.Pastel)
        fig2.update_layout(showlegend=False, yaxis_title="", xaxis_title="Số lượng jobs")
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("Chưa có dữ liệu cấp bậc")

# ─────────────────────────────────────────────────────────
# Row 2: Top skills & địa điểm
# ─────────────────────────────────────────────────────────

col3, col4 = st.columns(2)

with col3:
    st.subheader("Top kỹ năng được yêu cầu")
    if len(df_skills):
        top_skills = df_skills.head(15)
        fig3 = px.bar(top_skills.sort_values("count"),
                      x="count", y="skill", orientation="h",
                      color="count",
                      color_continuous_scale="Blues")
        fig3.update_layout(showlegend=False, yaxis_title="", xaxis_title="Số jobs yêu cầu",
                           coloraxis_showscale=False)
        st.plotly_chart(fig3, use_container_width=True)
    else:
        st.info("Chưa có dữ liệu skills")

with col4:
    st.subheader("Phân bổ theo địa điểm")
    loc_df = df_jobs[df_jobs["location"].notna() & (df_jobs["location"] != "Unknown")]
    if len(loc_df):
        by_loc = loc_df.groupby("location").size().reset_index(name="count")
        by_loc = by_loc.sort_values("count", ascending=False).head(10)
        fig4 = px.bar(by_loc.sort_values("count"),
                      x="count", y="location", orientation="h",
                      color="count",
                      color_continuous_scale="Greens")
        fig4.update_layout(showlegend=False, yaxis_title="", xaxis_title="Số jobs",
                           coloraxis_showscale=False)
        st.plotly_chart(fig4, use_container_width=True)
    else:
        st.info("Chưa có dữ liệu địa điểm")

# ─────────────────────────────────────────────────────────
# Row 3: Lương & xu hướng theo tuần
# ─────────────────────────────────────────────────────────

st.divider()
col5, col6 = st.columns(2)

with col5:
    st.subheader("Phân bổ mức lương (triệu VND/tháng)")
    sal_df = df_jobs[(df_jobs["salary_min"].notna()) & (df_jobs["salary_min"] > 0)].copy()
    if len(sal_df):
        sal_df["salary_avg_m"] = ((sal_df["salary_min"] + sal_df["salary_max"].fillna(sal_df["salary_min"])) / 2 / 1_000_000)
        sal_df = sal_df[sal_df["salary_avg_m"] < 200]  # loại outliers
        fig5 = px.histogram(sal_df, x="salary_avg_m", nbins=20,
                            color_discrete_sequence=["#636EFA"],
                            labels={"salary_avg_m": "Lương trung bình (triệu/tháng)"})
        fig5.update_layout(yaxis_title="Số jobs")
        st.plotly_chart(fig5, use_container_width=True)
    else:
        st.info("Chưa có đủ dữ liệu lương có thể so sánh")

with col6:
    st.subheader("Xu hướng job theo tuần")
    if len(df_weekly):
        weekly_total = df_weekly.groupby("week_start")[["active_jobs", "new_jobs", "closed_jobs"]].sum().reset_index()
        fig6 = go.Figure()
        fig6.add_trace(go.Scatter(x=weekly_total["week_start"], y=weekly_total["active_jobs"],
                                  mode="lines+markers", name="Đang tuyển",
                                  line=dict(color="#00CC96")))
        fig6.add_trace(go.Bar(x=weekly_total["week_start"], y=weekly_total["new_jobs"],
                              name="Job mới", marker_color="#636EFA", opacity=0.7))
        fig6.add_trace(go.Bar(x=weekly_total["week_start"], y=weekly_total["closed_jobs"],
                              name="Job đóng", marker_color="#EF553B", opacity=0.7))
        fig6.update_layout(barmode="group", xaxis_title="Tuần",
                           yaxis_title="Số lượng jobs", legend=dict(orientation="h"))
        st.plotly_chart(fig6, use_container_width=True)
    else:
        st.info("Chưa đủ dữ liệu tuần để hiển thị xu hướng")

# ─────────────────────────────────────────────────────────
# Row 4: Job list
# ─────────────────────────────────────────────────────────

st.divider()
st.subheader("Danh sách jobs DA đang tuyển")

active_df = df_jobs[df_jobs["is_active"] == True].copy()

# Filters
fcol1, fcol2, fcol3 = st.columns(3)
with fcol1:
    src_filter = st.multiselect("Nguồn", options=active_df["source"].unique().tolist(), default=[])
with fcol2:
    loc_filter = st.multiselect("Địa điểm", options=sorted(active_df["location"].dropna().unique().tolist()), default=[])
with fcol3:
    lvl_filter = st.multiselect("Cấp bậc", options=sorted(active_df["level"].dropna().unique().tolist()), default=[])

filtered = active_df.copy()
if src_filter:
    filtered = filtered[filtered["source"].isin(src_filter)]
if loc_filter:
    filtered = filtered[filtered["location"].isin(loc_filter)]
if lvl_filter:
    filtered = filtered[filtered["level"].isin(lvl_filter)]

show_cols = ["title", "company", "source", "location", "level", "salary_raw", "first_seen_at"]
show_df   = filtered[show_cols].rename(columns={
    "title":         "Tên Job",
    "company":       "Công ty",
    "source":        "Nguồn",
    "location":      "Địa điểm",
    "level":         "Cấp bậc",
    "salary_raw":    "Lương",
    "first_seen_at": "Ngày thấy lần đầu",
})
show_df["Ngày thấy lần đầu"] = pd.to_datetime(show_df["Ngày thấy lần đầu"]).dt.strftime("%Y-%m-%d")

st.dataframe(show_df, use_container_width=True, height=400)
st.caption(f"Hiển thị {len(filtered)} / {len(active_df)} jobs đang tuyển")
