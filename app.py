import json
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

# 저장 목록 (현재 브라우저 세션에 보관)
st.session_state.setdefault("saved_videos", {})    # {영상ID: {...}}
st.session_state.setdefault("saved_channels", {})  # {채널ID: {...}}


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


def clean(row):
    """DataFrame 행 -> JSON 저장 가능한 dict (NaN은 None, numpy 숫자는 파이썬 숫자)"""
    out = {}
    for k, v in dict(row).items():
        if v is None or (not isinstance(v, str) and pd.isna(v)):
            out[k] = None
        elif hasattr(v, "item"):
            out[k] = v.item()
        else:
            out[k] = v
    return out


def n(v):
    return "비공개" if v is None or pd.isna(v) else f"{int(v):,}"


# ---------- 저장 기능 ----------
def now_str():
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M")


def toggle_video(r):
    saved = st.session_state["saved_videos"]
    if r["영상ID"] in saved:
        del saved[r["영상ID"]]
    else:
        saved[r["영상ID"]] = {**r, "저장일": now_str()}


def toggle_channel(c):
    saved = st.session_state["saved_channels"]
    if c["채널ID"] in saved:
        del saved[c["채널ID"]]
    else:
        saved[c["채널ID"]] = {**c, "저장일": now_str()}


def render_card(r, ns):
    """영상 카드 1개 + 영상/채널 저장 버튼. ns는 위젯 key 충돌 방지용 접두사."""
    if r.get("썸네일"):
        st.image(r["썸네일"], use_container_width=True)
    st.markdown(f"**[{r['제목']}]({r['링크']})**")
    st.caption(f"{r['채널']} · {r['업로드일']} · {r['길이']}")
    st.write(f"👁 {n(r['조회수'])}  💬 {n(r['댓글수'])}  👍 {n(r['좋아요수'])}")

    ch = {
        "채널ID": r["채널ID"],
        "채널": r["채널"],
        "채널링크": f"https://www.youtube.com/channel/{r['채널ID']}",
    }
    v_saved = r["영상ID"] in st.session_state["saved_videos"]
    c_saved = r["채널ID"] in st.session_state["saved_channels"]
    b1, b2 = st.columns(2)
    b1.button("✅ 영상 저장됨" if v_saved else "⭐ 영상 저장",
              key=f"{ns}_v_{r['영상ID']}", on_click=toggle_video, args=(r,),
              use_container_width=True)
    b2.button("✅ 채널 저장됨" if c_saved else "📌 채널 저장",
              key=f"{ns}_c_{r['영상ID']}", on_click=toggle_channel, args=(ch,),
              use_container_width=True)


def render_cards(records, ns):
    for i in range(0, len(records), 3):
        cols = st.columns(3)
        for col, r in zip(cols, records[i:i + 3]):
            with col:
                render_card(r, ns)


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
                "영상ID": it["id"],
                "채널ID": sn["channelId"],
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

    max_results = st.number_input("검색 영상 수", min_value=50, max_value=500, value=50, step=50)
    order_label = st.radio("검색 정렬", list(ORDERS.keys()), horizontal=True)

    min_views = st.number_input("최소 조회수", min_value=0, value=1000000, step=100000)

    run = st.button("검색", type="primary", use_container_width=True)
    st.caption("검색 1회(50개)당 API 할당량 100 소모 (일 10,000). 롱폼은 검색이 2회 실행되어 2배 소모됩니다.")
    st.caption("버전 v5 (영상·채널 저장 기능)")

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

saved_v = st.session_state["saved_videos"]
saved_c = st.session_state["saved_channels"]
tab_results, tab_saved = st.tabs(["🔎 검색 결과", f"⭐ 저장 목록 (영상 {len(saved_v)} · 채널 {len(saved_c)})"])

# ---------- 검색 결과 탭 ----------
with tab_results:
    df = st.session_state.get("df")
    if df is None:
        st.info("왼쪽에서 검색어를 입력하고 '검색'을 눌러주세요.")
    elif df.empty:
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

            render_cards([clean(r) for _, r in f.iterrows()], "res")

            st.download_button(
                "CSV 다운로드",
                f.drop(columns=["영상ID", "채널ID"]).to_csv(index=False).encode("utf-8-sig"),
                file_name="youtube_result.csv",
                mime="text/csv",
            )

# ---------- 저장 목록 탭 ----------
with tab_saved:
    st.warning("저장 목록은 현재 브라우저 세션에만 보관됩니다. 새로고침하거나 앱이 재시작되면 사라지니, "
               "중요한 목록은 아래 '백업 저장'으로 파일을 내려받아 두세요.")

    c1, c2 = st.columns(2)
    backup = json.dumps({"videos": list(saved_v.values()), "channels": list(saved_c.values())},
                        ensure_ascii=False, indent=2)
    c1.download_button("💾 백업 저장 (JSON)", backup.encode("utf-8"),
                       file_name="youtube_saved.json", mime="application/json",
                       disabled=not (saved_v or saved_c), use_container_width=True)
    up = c2.file_uploader("백업 불러오기", type="json", label_visibility="collapsed")
    if up is not None:
        sig = f"{up.name}-{up.size}"
        if st.session_state.get("_restored") != sig:
            try:
                data = json.load(up)
                for v in data.get("videos", []):
                    saved_v[v["영상ID"]] = v
                for c in data.get("channels", []):
                    saved_c[c["채널ID"]] = c
                st.session_state["_restored"] = sig
                st.rerun()
            except (ValueError, KeyError, AttributeError):
                st.error("백업 파일을 읽을 수 없습니다.")

    kind = st.radio("보기", ["영상", "채널"], horizontal=True, key="saved_kind")

    if kind == "영상":
        if not saved_v:
            st.info("저장한 영상이 없습니다. 검색 결과 카드의 '⭐ 영상 저장'을 눌러보세요.")
        else:
            vids = sorted(saved_v.values(), key=lambda v: v.get("저장일", ""), reverse=True)
            render_cards(vids, "sv")
            st.download_button(
                "저장한 영상 CSV 다운로드",
                pd.DataFrame(vids).drop(columns=["영상ID", "채널ID", "썸네일"], errors="ignore")
                .to_csv(index=False).encode("utf-8-sig"),
                file_name="saved_videos.csv", mime="text/csv",
            )
    else:
        if not saved_c:
            st.info("저장한 채널이 없습니다. 검색 결과 카드의 '📌 채널 저장'을 눌러보세요.")
        else:
            chans = sorted(saved_c.values(), key=lambda c: c.get("저장일", ""), reverse=True)
            for c in chans:
                cnt = sum(1 for v in saved_v.values() if v.get("채널ID") == c["채널ID"])
                a, b, d = st.columns([5, 2, 2])
                a.markdown(f"**[{c['채널']}]({c['채널링크']})**  \n저장일 {c.get('저장일', '')}")
                b.write(f"저장한 영상 {cnt}개")
                d.button("🗑 삭제", key=f"sc_del_{c['채널ID']}",
                         on_click=toggle_channel, args=(c,), use_container_width=True)
            st.download_button(
                "저장한 채널 CSV 다운로드",
                pd.DataFrame(chans).to_csv(index=False).encode("utf-8-sig"),
                file_name="saved_channels.csv", mime="text/csv",
            )
