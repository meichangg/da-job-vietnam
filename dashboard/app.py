"""
DA Job Market Dashboard — Vietnam
Dùng Supabase REST API (httpx) thay vì kết nối PostgreSQL trực tiếp.
"""
import httpx
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(
    page_title="DA Job Market Vietnam",
    page_icon="📊",
    layout="wide",
)

# ─────────────────────────────────────────────────────────
# Supabase REST API helpers
# ─────────────────────────────────────────────────────────

def get_supabase_config():
    if hasattr(st, "secrets") and "SUPABASE_URL" in st.secrets:
        return st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"]
    import os
    return os.getenv("SUPABASE_URL", ""), os.getenv("SUPABASE_KEY", "")


def supabase_get(table: str, select: str = "*", extra_params: dict = None) -> list:
    url, key = get_supabase_config()
    if not url or not key:
        st.error("SUPABASE_URL hoặc SUPABASE_KEY chưa được cấu hình.")
        st.stop()

    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    params = {"select": select, "limit": "2000"}
    if extra_params:
        params.update(extra_params)

    resp = httpx.get(f"{url}/rest/v1/{table}", headers=headers, params=params, timeout=20)
    resp.raise_for_status()
    return resp.json()


@st.cache_data(ttl=300)
def load_jobs() -> pd.DataFrame:
    rows = supabase_get(
        "jobs",
        select="id,title,url,location,level,salary_min,salary_max,salary_raw,is_active,first_seen_at,last_seen_at,closed_at,companies(name),sources(name)"
    )
    df = pd.json_normalize(rows)
    df = df.rename(columns={"companies.name": "company", "sources.name": "source"})
    for col in ["first_seen_at", "last_seen_at", "closed_at"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


@st.cache_data(ttl=300)
def load_skills() -> pd.DataFrame:
    rows = supabase_get("job_skills", select="skills(name)")
    names = [r["skills"]["name"] for r in rows if r.get("skills")]
    if not names:
        return pd.DataFrame(columns=["skill", "count"])
    s = pd.Series(names).value_counts().reset_index()
    s.columns = ["skill", "count"]
    return s


@st.cache_data(ttl=300)
def load_crawl_runs() -> pd.DataFrame:
    rows = supabase_get(
        "crawl_runs",
        select="started_at,jobs_crawled,jobs_new,jobs_updated,status,sources(name)"
    )
    df = pd.json_normalize(rows)
    if "sources.name" in df.columns:
        df = df.rename(columns={"sources.name": "source"})
    if "started_at" in df.columns:
        df["started_at"] = pd.to_datetime(df["started_at"], errors="coerce")
    return df


@st.cache_data(ttl=300)
def load_weekly_snapshots() -> pd.DataFrame:
    rows = supabase_get(
        "weekly_snapshots",
        select="week_start,active_jobs,new_jobs,closed_jobs,sources(name)"
    )
    df = pd.json_normalize(rows)
    if "sources.name" in df.columns:
        df = df.rename(columns={"sources.name": "source"})
    if "week_start" in df.columns:
        df["week_start"] = pd.to_datetime(df["week_start"], errors="coerce")
    return df


# ─────────────────────────────────────────────────────────
# Load data
# ─────────────────────────────────────────────────────────

df_jobs   = load_jobs()
df_skills = load_skills()
df_weekly = load_weekly_snapshots()
df_runs   = load_crawl_runs()

# ─────────────────────────────────────────────────────────
# Header
# ─────────────────────────────────────────────────────────

st.title("📊 Thị trường tuyển dụng Data Analyst - Việt Nam")
st.caption("Dữ liệu crawl từ TopCV · VietnamWorks · YBox · LinkedIn")

# ─────────────────────────────────────────────────────────
# KPI cards
# ─────────────────────────────────────────────────────────

total_jobs  = len(df_jobs)
active_jobs = int(df_jobs["is_active"].sum()) if "is_active" in df_jobs.columns else 0
closed_jobs = total_jobs - active_jobs

today = pd.Timestamp.now(tz="UTC").normalize()
if "closed_at" in df_jobs.columns:
    closed_at = pd.to_datetime(df_jobs["closed_at"], utc=True, errors="coerce")
    closed_today = int((closed_at >= today).sum())
else:
    closed_today = 0

c1, c2, c3, c4 = st.columns(4)
c1.metric("Tổng số jobs", total_jobs)
c2.metric("Đang tuyển dụng", active_jobs)
c3.metric("Đã đóng", closed_jobs)
c4.metric("Đóng hôm nay", closed_today)

st.divider()

# ─────────────────────────────────────────────────────────
# Thống kê job mới / mất sau mỗi lần crawl
# ─────────────────────────────────────────────────────────

st.subheader("Biến động job sau mỗi lần crawl")
if len(df_runs) and "jobs_new" in df_runs.columns:
    recent = df_runs[df_runs["status"] == "success"].copy()
    if len(recent):
        # Tổng hợp theo lần crawl (started_at)
        recent["date"] = recent["started_at"].dt.strftime("%Y-%m-%d %H:%M")
        agg = recent.groupby("date")[["jobs_new", "jobs_crawled"]].sum().reset_index()
        agg = agg.sort_values("date").tail(20)

        fig_runs = go.Figure()
        fig_runs.add_trace(go.Bar(x=agg["date"], y=agg["jobs_new"],
                                   name="Job mới thêm", marker_color="#00CC96"))
        fig_runs.add_trace(go.Scatter(x=agg["date"], y=agg["jobs_crawled"],
                                       name="Tổng crawled", mode="lines+markers",
                                       line=dict(color="#636EFA", dash="dot")))
        fig_runs.update_layout(barmode="group", xaxis_title="Lần crawl",
                               yaxis_title="Số lượng", legend=dict(orientation="h"),
                               xaxis_tickangle=-30)
        st.plotly_chart(fig_runs, use_container_width=True)

        # Bảng chi tiết 10 lần crawl gần nhất
        show_runs = recent.sort_values("started_at", ascending=False).head(10)
        show_runs = show_runs[["date", "source", "jobs_crawled", "jobs_new", "jobs_updated"]].rename(columns={
            "date": "Thời gian", "source": "Nguồn",
            "jobs_crawled": "Tổng crawled", "jobs_new": "Job mới", "jobs_updated": "Cập nhật",
        })
        st.dataframe(show_runs, use_container_width=True, hide_index=True)
    else:
        st.info("Chưa có dữ liệu crawl runs")
else:
    st.info("Chưa có dữ liệu crawl runs")

st.divider()

# ─────────────────────────────────────────────────────────
# Row 1: Theo nguồn & level
# ─────────────────────────────────────────────────────────

col1, col2 = st.columns(2)

with col1:
    st.subheader("Job theo nguồn tuyển dụng")
    if "source" in df_jobs.columns:
        by_source = df_jobs.groupby("source").size().reset_index(name="count")
        fig = px.pie(by_source, names="source", values="count",
                     color_discrete_sequence=px.colors.qualitative.Set2)
        fig.update_traces(textposition="inside", textinfo="percent+label")
        st.plotly_chart(fig, use_container_width=True)

with col2:
    st.subheader("Phân bổ theo cấp bậc")
    level_df = df_jobs[df_jobs["level"].notna()] if "level" in df_jobs.columns else pd.DataFrame()
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
# Row 2: Skills & địa điểm
# ─────────────────────────────────────────────────────────

col3, col4 = st.columns(2)

with col3:
    st.subheader("Top kỹ năng được yêu cầu")
    if len(df_skills):
        top_skills = df_skills.head(15)
        fig3 = px.bar(top_skills.sort_values("count"),
                      x="count", y="skill", orientation="h",
                      color="count", color_continuous_scale="Blues")
        fig3.update_layout(showlegend=False, yaxis_title="", xaxis_title="Số jobs yêu cầu",
                           coloraxis_showscale=False)
        st.plotly_chart(fig3, use_container_width=True)
    else:
        st.info("Chưa có dữ liệu skills")

with col4:
    st.subheader("Phân bổ theo địa điểm")
    if "location" in df_jobs.columns:
        loc_df = df_jobs[df_jobs["location"].notna() & (df_jobs["location"] != "Unknown")]
        if len(loc_df):
            by_loc = loc_df.groupby("location").size().reset_index(name="count")
            by_loc = by_loc.sort_values("count", ascending=False).head(10)
            fig4 = px.bar(by_loc.sort_values("count"),
                          x="count", y="location", orientation="h",
                          color="count", color_continuous_scale="Greens")
            fig4.update_layout(showlegend=False, yaxis_title="", xaxis_title="Số jobs",
                               coloraxis_showscale=False)
            st.plotly_chart(fig4, use_container_width=True)
        else:
            st.info("Chưa có dữ liệu địa điểm")

# ─────────────────────────────────────────────────────────
# Row 3: Lương & xu hướng tuần
# ─────────────────────────────────────────────────────────

st.divider()
col5, col6 = st.columns(2)

with col5:
    st.subheader("Phân bổ mức lương theo cấp bậc (triệu VND/tháng)")
    if "salary_min" in df_jobs.columns:
        sal_df = df_jobs[(df_jobs["salary_min"].notna()) & (df_jobs["salary_min"] > 0)].copy()
        if len(sal_df):
            sal_df["salary_avg_m"] = (
                (sal_df["salary_min"] + sal_df["salary_max"].fillna(sal_df["salary_min"])) / 2 / 1_000_000
            )
            sal_df = sal_df[sal_df["salary_avg_m"] < 200]
            sal_df["Cấp bậc"] = sal_df["level"].fillna("Không rõ") if "level" in sal_df.columns else "Không rõ"

            hover_cols = [c for c in ["title", "company"] if c in sal_df.columns]
            fig5 = px.strip(
                sal_df, x="Cấp bậc", y="salary_avg_m",
                color="source" if "source" in sal_df.columns else None,
                hover_data=hover_cols,
                labels={"salary_avg_m": "Lương trung bình (triệu/tháng)"},
                color_discrete_sequence=px.colors.qualitative.Set2,
            )
            fig5.update_traces(jitter=0.4, marker=dict(size=9, opacity=0.75))
            fig5.update_layout(yaxis_title="Lương trung bình (triệu/tháng)", legend_title="Nguồn")
            st.plotly_chart(fig5, use_container_width=True)
        else:
            st.info("Chưa có đủ dữ liệu lương")

with col6:
    st.subheader("Xu hướng job theo tuần")
    if len(df_weekly) and "week_start" in df_weekly.columns:
        cols_needed = ["active_jobs", "new_jobs", "closed_jobs"]
        for c in cols_needed:
            if c not in df_weekly.columns:
                df_weekly[c] = 0
        weekly_total = df_weekly.groupby("week_start")[cols_needed].sum().reset_index()
        fig6 = go.Figure()
        fig6.add_trace(go.Scatter(x=weekly_total["week_start"], y=weekly_total["active_jobs"],
                                  mode="lines+markers", name="Đang tuyển",
                                  line=dict(color="#00CC96")))
        fig6.add_trace(go.Bar(x=weekly_total["week_start"], y=weekly_total["new_jobs"],
                              name="Job mới", marker_color="#636EFA", opacity=0.7))
        fig6.add_trace(go.Bar(x=weekly_total["week_start"], y=weekly_total["closed_jobs"],
                              name="Job đóng", marker_color="#EF553B", opacity=0.7))
        fig6.update_layout(barmode="group", xaxis_title="Tuần",
                           yaxis_title="Số lượng", legend=dict(orientation="h"))
        st.plotly_chart(fig6, use_container_width=True)
    else:
        st.info("Chưa đủ dữ liệu tuần")

# ─────────────────────────────────────────────────────────
# Row 4: Danh sách jobs
# ─────────────────────────────────────────────────────────

st.divider()
st.subheader("Danh sách jobs DA đang tuyển")

active_df = df_jobs[df_jobs["is_active"] == True].copy() if "is_active" in df_jobs.columns else df_jobs.copy()

fcol1, fcol2, fcol3 = st.columns(3)
with fcol1:
    src_opts = active_df["source"].dropna().unique().tolist() if "source" in active_df.columns else []
    src_filter = st.multiselect("Nguồn", options=src_opts, default=[])
with fcol2:
    loc_opts = sorted(active_df["location"].dropna().unique().tolist()) if "location" in active_df.columns else []
    loc_filter = st.multiselect("Địa điểm", options=loc_opts, default=[])
with fcol3:
    lvl_opts = sorted(active_df["level"].dropna().unique().tolist()) if "level" in active_df.columns else []
    lvl_filter = st.multiselect("Cấp bậc", options=lvl_opts, default=[])

filtered = active_df.copy()
if src_filter:
    filtered = filtered[filtered["source"].isin(src_filter)]
if loc_filter:
    filtered = filtered[filtered["location"].isin(loc_filter)]
if lvl_filter:
    filtered = filtered[filtered["level"].isin(lvl_filter)]

show_cols = [c for c in ["title", "company", "source", "location", "level", "salary_raw", "first_seen_at", "url"] if c in filtered.columns]
show_df = filtered[show_cols].rename(columns={
    "title": "Tên Job", "company": "Công ty", "source": "Nguồn",
    "location": "Địa điểm", "level": "Cấp bậc",
    "salary_raw": "Lương", "first_seen_at": "Ngày thấy lần đầu",
    "url": "Link",
})
if "Ngày thấy lần đầu" in show_df.columns:
    show_df["Ngày thấy lần đầu"] = pd.to_datetime(show_df["Ngày thấy lần đầu"]).dt.strftime("%Y-%m-%d")

st.dataframe(
    show_df,
    use_container_width=True,
    height=400,
    hide_index=True,
    column_config={
        "Link": st.column_config.LinkColumn("Link", display_text="Xem job ↗"),
    },
)
st.caption(f"Hiển thị {len(filtered)} / {len(active_df)} jobs đang tuyển")
