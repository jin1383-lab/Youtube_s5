import os
import re
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests
import streamlit as st

API = "https://www.googleapis.com/youtube/v3"
KST = timezone(timedelta(hours=9))
SHORTS_MAX_SEC = 180  # 숏폼 기준: 3분 이하

PERIODS = {"1일": 1, "3일": 3, "1주일": 7, "1개월": 30, "3개월": 90, "6개월": 180, "1년": 365}
COUNTRIES = {"한국": "KR", "일본": "JP", "미국": "US", "글로벌": None}
ORDERS = {"조회수순": "viewCount", "최신순": "date"}

st.set_page_config(page_title="YouTube 기간별 검색기", page_icon="📊", layout="wide")


# ---------- API 키 ----------
def get_api_key():
    try:
        if "YOUTUBE_API_KEY" in st.secrets:
            return st.secrets["YOUTUBE_API_KEY"]
    except Exception:
        pass
    return os.environ.get("YOUTUBE_API_KEY", "")


# ---------- 유틸 ----------
def parse_duration(s):
    """ISO 8601 길이(PT1M5S 등) -> 초"""
    m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", s or "")
    if not m:
        return 0
    d, h, mi, sec = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + sec


def fmt_duration(sec):
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


# ---------- YouTube API ----------
def call(key, endpoint, params):
    r = requests.get(f"{API}/{endpoint}", params={**params, "key": key}, timeout=30)
    if r.status_code != 200:
        try:
            msg = r.json()["error"]["message"]
        except Exception:
            msg = r.text
        raise RuntimeError(f"API 오류 ({r.status_code}): {msg}")
    return r.json()


def search_ids(key, query, start, region, duration, max_results, order):
    ids, token = [], None
    while len(ids) < max_results:
        params = {
            "part": "id",
            "type": "video",
            "q": query,
            "publishedAfter": start,
            "videoDuration": duration,
            "order": order,
            "maxResults": min(50, max_results - len(ids)),
        }
        if region:
            params["regionCode"] = region
        if token:
            params["pageToken"] = token
        data = call(key, "search", params)
        ids += [it["id"]["videoId"] for it in data.get("items", [])]
        token = data.get("nextPageToken")
        if not token:
            break
    return ids


@st.cache_data(ttl=3600, show_spinner=False)
def fetch(key, query, start, region, form, max_results, order):
    # 숏폼: 4분 미만 검색 후 3분 이하만 남김 / 롱폼: 4분 이상(중간+긴 영상)
    durations = ["short"] if form == "short" else ["medium", "long"]
    ids = []
    for dur in durations:
        for vid in search_ids(key, query, start, region, dur, max_results, order):
            if vid not in ids:
                ids.append(vid)

    rows = []
    for i in range(0, len(ids), 50):
        data = call(key, "videos", {
            "part": "snippet,statistics,contentDetails",
            "id": ",".join(ids[i:i + 50]),
        })
        for it in data.get("items", []):
            sec = parse_duration(it["contentDetails"].get("duration"))
            if form == "short" and not (0 < sec <= SHORTS_MAX_SEC):
                continue
            if form == "long" and sec <= SHORTS_MAX_SEC:
                continue
            st_, sn = it.get("statistics", {}), it["snippet"]
            pub = datetime.fromisoformat(sn["publishedAt"].replace("Z", "+00:00")).astimezone(KST)
            thumbs = sn.get("thumbnails", {})
            thumb = (thumbs.get("medium") or thumbs.get("high") or thumbs.get("default") or {}).get("url", "")
            rows.append({
                "썸네일": thumb,
                "제목": sn["title"],
                "채널": sn["channelTitle"],
                "업로드일": pub.strftime("%Y-%m-%d %H:%M"),
                "길이": fmt_duration(sec),
                "조회수": int(st_.get("viewCount", 0)),
                "댓글수": int(st_["commentCount"]) if "commentCount" in st_ else None,
                "좋아요수": int(st_["likeCount"]) if "likeCount" in st_ else None,
                "링크": f"https://www.youtube.com/watch?v={it['id']}",
            })

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    sort_col = "업로드일" if order == "date" else "조회수"
    return df.sort_values(sort_col, ascending=False).head(max_results).reset_index(drop=True)


# ---------- UI ----------
st.title("📊 YouTube 기간별 검색기")
st.caption("업로드 기간·영상 형식·국가별로 조회수 · 댓글수 · 좋아요수를 조회합니다.")

with st.sidebar:
    st.header("검색 조건")
    api_key = get_api_key()
    if not api_key:
        api_key = st.text_input("YouTube API Key", type="password")

    query = st.text_input("검색어")

    country = st.radio("국가", list(COUNTRIES.keys()), horizontal=True)
    form_label = st.radio("영상 형식", ["숏폼", "롱폼"], horizontal=True)  # 기본값: 숏폼
    period = st.selectbox("업로드 기간", list(PERIODS.keys()), index=2)

    max_results = st.slider("검색 영상 수", 10, 500, 50, step=10)
    order_label = st.radio("검색 정렬", list(ORDERS.keys()), horizontal=True)

    min_views = st.number_input("최소 조회수", min_value=0, value=1_000_000, step=100_000)

    run = st.button("검색", type="primary", use_container_width=True)
    st.caption("검색 1회(50개)당 API 할당량 100 소모 (일 10,000). 롱폼은 검색이 2회 실행되어 2배 소모됩니다.")

if run:
    if not api_key:
        st.error("API 키를 입력하거나 secrets에 설정해 주세요.")
    elif not query.strip():
        st.error("검색어를 입력해 주세요.")
    else:
        # 현재 시각 기준 N일 전 (캐시가 잘 먹도록 시 단위로 내림)
        start_dt = (datetime.now(timezone.utc) - timedelta(days=PERIODS[period])).replace(
            minute=0, second=0, microsecond=0)
        try:
            with st.spinner("조회 중..."):
                df = fetch(api_key, query.strip(),
                           start_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                           COUNTRIES[country],
                           "short" if form_label == "숏폼" else "long",
                           max_results, ORDERS[order_label])
            st.session_state["df"] = df
            st.session_state["meta"] = f"{country} · {form_label} · 최근 {period}"
        except RuntimeError as e:
            st.error(str(e))

df = st.session_state.get("df")
if df is not None:
    if df.empty:
        st.info("검색 결과가 없습니다.")
    else:
        st.subheader(st.session_state.get("meta", ""))
        f = df[df["조회수"] >= min_views]

        if f.empty:
            st.info(f"조회수 {min_views:,} 이상인 영상이 없습니다. 사이드바에서 최소 조회수를 낮춰 보세요. "
                    f"(검색된 영상 {len(df)}개)")
        else:
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("영상 수", f"{len(f):,}")
            m2.metric("총 조회수", f"{int(f['조회수'].sum()):,}")
            m3.metric("총 댓글수", f"{int(f['댓글수'].sum()):,}")
            m4.metric("총 좋아요수", f"{int(f['좋아요수'].sum()):,}")

            sort_col = st.radio("정렬 기준", ["조회수", "댓글수", "좋아요수", "업로드일"], horizontal=True)
            f = f.sort_values(sort_col, ascending=False, na_position="last")

            def n(v):
                return "비공개" if pd.isna(v) else f"{int(v):,}"

            # ---------- 카드형 결과 ----------
            for i in range(0, len(f), 3):
                cols = st.columns(3)
                for col, (_, r) in zip(cols, f.iloc[i:i + 3].iterrows()):
                    with col:
                        if r["썸네일"]:
                            st.image(r["썸네일"], use_container_width=True)
                        st.markdown(f"**[{r['제목']}]({r['링크']})**")
                        st.caption(f"{r['채널']} · {r['업로드일']} · {r['길이']}")
                        st.write(f"👁 {n(r['조회수'])}  💬 {n(r['댓글수'])}  👍 {n(r['좋아요수'])}")

            st.download_button(
                "CSV 다운로드",
                f.to_csv(index=False).encode("utf-8-sig"),
                file_name="youtube_result.csv",
                mime="text/csv",
            )
