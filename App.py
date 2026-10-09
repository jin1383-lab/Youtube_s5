import os
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import requests
import streamlit as st

API = "https://www.googleapis.com/youtube/v3"
KST = timezone(timedelta(hours=9))

st.set_page_config(page_title="YouTube 기간별 검색기", page_icon="📊", layout="wide")


# ---------- API 키 ----------
def get_api_key():
    try:
        if "YOUTUBE_API_KEY" in st.secrets:
            return st.secrets["YOUTUBE_API_KEY"]
    except Exception:
        pass
    return os.environ.get("YOUTUBE_API_KEY", "")


# ---------- YouTube API ----------
def to_rfc3339(d: date, end_of_day=False):
    dt = datetime(d.year, d.month, d.day, tzinfo=KST)
    if end_of_day:
        dt += timedelta(days=1) - timedelta(seconds=1)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def call(key, endpoint, params):
    r = requests.get(f"{API}/{endpoint}", params={**params, "key": key}, timeout=30)
    if r.status_code != 200:
        try:
            msg = r.json()["error"]["message"]
        except Exception:
            msg = r.text
        raise RuntimeError(f"API 오류 ({r.status_code}): {msg}")
    return r.json()


@st.cache_data(ttl=3600, show_spinner=False)
def fetch(key, query, channel, start, end, max_results, order):
    ids, token = [], None
    while len(ids) < max_results:
        params = {
            "part": "id",
            "type": "video",
            "publishedAfter": start,
            "publishedBefore": end,
            "order": order,
            "maxResults": min(50, max_results - len(ids)),
        }
        if query:
            params["q"] = query
        if channel:
            params["channelId"] = channel
        if token:
            params["pageToken"] = token
        data = call(key, "search", params)
        ids += [it["id"]["videoId"] for it in data.get("items", [])]
        token = data.get("nextPageToken")
        if not token:
            break

    rows = []
    for i in range(0, len(ids), 50):
        data = call(key, "videos", {"part": "snippet,statistics", "id": ",".join(ids[i:i + 50])})
        for it in data.get("items", []):
            st_, sn = it.get("statistics", {}), it["snippet"]
            pub = datetime.fromisoformat(sn["publishedAt"].replace("Z", "+00:00")).astimezone(KST)
            rows.append({
                "업로드일": pub.strftime("%Y-%m-%d %H:%M"),
                "제목": sn["title"],
                "채널": sn["channelTitle"],
                "조회수": int(st_.get("viewCount", 0)),
                "댓글수": int(st_["commentCount"]) if "commentCount" in st_ else None,
                "좋아요수": int(st_["likeCount"]) if "likeCount" in st_ else None,
                "링크": f"https://www.youtube.com/watch?v={it['id']}",
            })
    return pd.DataFrame(rows)


# ---------- UI ----------
st.title("📊 YouTube 기간별 검색기")
st.caption("업로드 날짜 기준으로 조회수 · 댓글수 · 좋아요수를 조회합니다.")

with st.sidebar:
    st.header("검색 조건")
    api_key = get_api_key()
    if not api_key:
        api_key = st.text_input("YouTube API Key", type="password")

    query = st.text_input("검색어")
    channel = st.text_input("채널 ID (선택, UC...)")

    today = date.today()
    c1, c2 = st.columns(2)
    start = c1.date_input("시작일", today - timedelta(days=30))
    end = c2.date_input("종료일", today)

    max_results = st.slider("최대 영상 수", 10, 500, 50, step=10)
    order = st.selectbox(
        "API 검색 정렬", ["date", "viewCount", "rating", "relevance"],
        format_func=lambda x: {"date": "최신순", "viewCount": "조회수순",
                               "rating": "평점순", "relevance": "관련도순"}[x],
    )

    st.subheader("최소값 필터")
    min_views = st.number_input("조회수 ≥", 0, step=1000)
    min_comments = st.number_input("댓글수 ≥", 0, step=10)
    min_likes = st.number_input("좋아요수 ≥", 0, step=100)

    run = st.button("검색", type="primary", use_container_width=True)
    st.caption("검색 1회(50개)당 할당량 100 소모 / 일 10,000")

if run:
    if not api_key:
        st.error("API 키를 입력하거나 secrets에 설정해 주세요.")
    elif not query and not channel:
        st.error("검색어 또는 채널 ID 중 하나는 필요합니다.")
    elif start > end:
        st.error("시작일이 종료일보다 늦습니다.")
    else:
        try:
            with st.spinner("조회 중..."):
                df = fetch(api_key, query, channel.strip(),
                           to_rfc3339(start), to_rfc3339(end, True), max_results, order)
            st.session_state["df"] = df
        except RuntimeError as e:
            st.error(str(e))

df = st.session_state.get("df")
if df is not None:
    if df.empty:
        st.info("검색 결과가 없습니다.")
    else:
        f = df[(df["조회수"] >= min_views)
               & (df["댓글수"].fillna(0) >= min_comments)
               & (df["좋아요수"].fillna(0) >= min_likes)]

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("영상 수", f"{len(f):,}")
        m2.metric("총 조회수", f"{int(f['조회수'].sum()):,}")
        m3.metric("총 댓글수", f"{int(f['댓글수'].sum()):,}")
        m4.metric("총 좋아요수", f"{int(f['좋아요수'].sum()):,}")

        sort_col = st.radio("정렬 기준", ["조회수", "댓글수", "좋아요수", "업로드일"], horizontal=True)
        f = f.sort_values(sort_col, ascending=False, na_position="last")

        st.dataframe(
            f,
            use_container_width=True,
            hide_index=True,
            column_config={
                "조회수": st.column_config.NumberColumn(format="%d"),
                "댓글수": st.column_config.NumberColumn(format="%d", help="비공개/댓글 중지는 빈칸"),
                "좋아요수": st.column_config.NumberColumn(format="%d", help="비공개는 빈칸"),
                "링크": st.column_config.LinkColumn("링크", display_text="열기"),
            },
        )

        st.download_button(
            "CSV 다운로드",
            f.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"youtube_{start}_{end}.csv",
            mime="text/csv",
        )
