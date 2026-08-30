import re
import isodate
import pandas as pd
import streamlit as st
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ================= ============================================
# 1. Page Configuration & Setup
# ==============================================================
st.set_page_config(
    page_title="Shorts Finder V1",
    page_icon="🎬",
    layout="wide"
)

st.title("🎬 Shorts Finder V1")
st.caption("유튜브 급상승 쇼츠 및 키워드별 고조회수 쇼츠를 탐색합니다.")

# Sidebar for API Key
with st.sidebar:
    st.header("🔑 API 설정")
    api_key = st.text_input("YouTube API Key를 입력하세요", type="password")
    st.markdown("---")
    st.markdown("### 💡 이용 안내")
    st.markdown("""
    - **급상승 쇼츠 모드**: 키워드 없이 현재 한국에서 가장 인기 있는 쇼츠를 수집합니다.
    - **키워드 검색 모드**: 특정 키워드 관련 영상 중 조회수 순으로 수집 후 쇼츠를 추려냅니다.
    """)

if not api_key:
    st.info("👈 좌측 사이드바에 YouTube API Key를 입력해주세요.")
    st.stop()

# Build YouTube Client
try:
    youtube = build("youtube", "v3", developerKey=api_key)
except Exception as e:
    st.error(f"API 클라이언트 생성 실패: {e}")
    st.stop()

# ================= ============================================
# 2. Helper Functions
# ==============================================================
def parse_duration_seconds(duration_str):
    """ISO 8601 duration 문자열을 초(seconds) 단위로 변환"""
    try:
        dur = isodate.parse_duration(duration_str)
        return int(dur.total_seconds())
    except Exception:
        return 0

def fetch_video_details(youtube_client, video_ids):
    """비디오 ID 리스트를 받아 상세 정보(조회수, 재생시간 등)를 수집"""
    details = []
    # API 한 번에 최대 50개까지 조회 가능하므로 Chunk 처리
    for i in range(0, len(video_ids), 50):
        chunk_ids = video_ids[i:i+50]
        request = youtube_client.videos().list(
            part="snippet,contentDetails,statistics",
            id=",".join(chunk_ids)
        )
        response = request.execute()
        
        for item in response.get("items", []):
            snippet = item.get("snippet", {})
            content = item.get("contentDetails", {})
            stats = item.get("statistics", {})
            
            dur_sec = parse_duration_seconds(content.get("duration", "PT0S"))
            
            details.append({
                "video_id": item.get("id"),
                "title": snippet.get("title"),
                "channel_title": snippet.get("channelTitle"),
                "published_at": snippet.get("publishedAt", "")[:10],
                "duration_sec": dur_sec,
                "view_count": int(stats.get("viewCount", 0)),
                "like_count": int(stats.get("likeCount", 0)),
                "comment_count": int(stats.get("commentCount", 0)),
                "thumbnail_url": snippet.get("thumbnails", {}).get("medium", {}).get("url", ""),
                "video_url": f"https://www.youtube.com/shorts/{item.get('id')}"
            })
    return pd.DataFrame(details)

# ================= ============================================
# 3. Main Logic: Tabs
# ==============================================================
tab1, tab2 = st.tabs(["🔥 실시간 급상승 쇼츠 (키워드 X)", "🔍 키워드 검색 쇼츠"])

# --------------------------------------------------------------
# Tab 1: Most Popular Shorts (No Keyword)
# --------------------------------------------------------------
with tab1:
    st.subheader("한국 실시간 급상승 쇼츠 탐색")
    
    col1, col2 = st.columns(2)
    with col1:
        min_views_tab1 = st.number_input(
            "최소 조회수 필터", 
            min_value=0, 
            value=100000, 
            step=100000,
            key="min_views_t1",
            help="예: 500000 입력 시 50만 회 이상만 표시"
        )
    with col2:
        max_duration_tab1 = st.selectbox(
            "최대 영상 길이", 
            options=[60, 180], 
            index=0, 
            key="max_dur_t1",
            format_func=lambda x: f"{x}초 이하"
        )

    if st.button("급상승 쇼츠 수집 시작", type="primary", key="btn_t1"):
        with st.spinner("유튜브 급상승 영상 및 쇼츠 데이터를 분석 중입니다..."):
            try:
                # 1. mostPopular 차트 수집 (최대 200개 수집 가능)
                video_ids = []
                next_page_token = None
                
                for _ in range(4): # 50개씩 4번 = 최대 200개
                    req = youtube.videos().list(
                        part="id",
                        chart="mostPopular",
                        regionCode="KR",
                        maxResults=50,
                        pageToken=next_page_token
                    )
                    res = req.execute()
                    video_ids.extend([item["id"] for item in res.get("items", [])])
                    
                    next_page_token = res.get("nextPageToken")
                    if not next_page_token:
                        break

                if not video_ids:
                    st.warning("수집된 급상승 영상이 없습니다.")
                else:
                    # 2. 비디오 상세 정보 가져오기
                    df = fetch_video_details(youtube, video_ids)
                    
                    # 3. 쇼츠 및 조회수 필터링
                    filtered_df = df[
                        (df["duration_sec"] <= max_duration_tab1) & 
                        (df["duration_sec"] > 0) & 
                        (df["view_count"] >= min_views_tab1)
                    ].copy()

                    filtered_df.sort_values(by="view_count", ascending=False, inplace=True)

                    st.success(f"총 {len(filtered_df)}개의 급상승 쇼츠를 찾았습니다!")

                    # 4. 결과 출력
                    if not filtered_df.empty:
                        st.dataframe(
                            filtered_df[["title", "channel_title", "view_count", "published_at", "video_url"]],
                            column_config={
                                "video_url": st.column_config.LinkColumn("링크", display_text="쇼츠 보기"),
                                "view_count": st.column_config.NumberColumn("조회수", format="%d 회")
                            },
                            use_container_width=True
                        )
                    else:
                        st.info("선택한 조건(조회수/영상 길이)을 만족하는 급상승 쇼츠가 없습니다. 필터 기준을 낮춰보세요.")

            except HttpError as e:
                st.error(f"YouTube API 에러가 발생했습니다: {e}")

# --------------------------------------------------------------
# Tab 2: Keyword Search Shorts
# --------------------------------------------------------------
with tab2:
    st.subheader("키워드 기반 인기 쇼츠 탐색")
    
    keyword = st.text_input("검색할 키워드를 입력하세요", value="요리", key="kw_input")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        batch_count = st.slider(
            "탐색 데이터 수 (50개 단위)", 
            min_value=1, 
            max_value=5, 
            value=5, 
            help="1=50개, 5=250개 수집"
        )
    with col2:
        min_views_tab2 = st.number_input(
            "최소 조회수 필터", 
            min_value=0, 
            value=500000, 
            step=100000, 
            key="min_views_t2"
        )
    with col3:
        max_duration_tab2 = st.selectbox(
            "최대 영상 길이", 
            options=[60, 180], 
            index=0, 
            key="max_dur_t2",
            format_func=lambda x: f"{x}초 이하"
        )

    if st.button("키워드 검색 시작", type="primary", key="btn_t2"):
        if not keyword.strip():
            st.warning("키워드를 입력해주세요.")
        else:
            with st.spinner(f"'{keyword}' 관련 높은 조회수의 영상 및 쇼츠 데이터를 수집 중입니다..."):
                try:
                    video_ids = []
                    next_page_token = None
                    
                    # 1. Search API로 video_id 수집 (order='viewCount' 적용)
                    for _ in range(batch_count):
                        req = youtube.search().list(
                            q=keyword,
                            type="video",
                            part="id",
                            order="viewCount",  # 조회수 높은 순으로 가져오도록 설정
                            maxResults=50,
                            pageToken=next_page_token
                        )
                        res = req.execute()
                        
                        for item in res.get("items", []):
                            if item.get("id", {}).get("kind") == "youtube#video":
                                video_ids.append(item["id"]["videoId"])
                        
                        next_page_token = res.get("nextPageToken")
                        if not next_page_token:
                            break

                    if not video_ids:
                        st.warning("검색 결과가 없습니다.")
                    else:
                        # 2. 상세 데이터 수집 및 쇼츠/조회수 필터링
                        df = fetch_video_details(youtube, video_ids)
                        
                        filtered_df = df[
                            (df["duration_sec"] <= max_duration_tab2) & 
                            (df["duration_sec"] > 0) & 
                            (df["view_count"] >= min_views_tab2)
                        ].copy()

                        filtered_df.sort_values(by="view_count", ascending=False, inplace=True)

                        st.success(f"조건에 맞는 쇼츠 {len(filtered_df)}개를 찾았습니다!")

                        # 3. 결과 출력
                        if not filtered_df.empty:
                            st.dataframe(
                                filtered_df[["title", "channel_title", "view_count", "published_at", "video_url"]],
                                column_config={
                                    "video_url": st.column_config.LinkColumn("링크", display_text="쇼츠 보기"),
                                    "view_count": st.column_config.NumberColumn("조회수", format="%d 회")
                                },
                                use_container_width=True
                            )
                        else:
                            st.info("수집된 영상 중 설정한 최소 조회수 및 쇼츠 길이 조건을 만족하는 결과가 없습니다.")

                except HttpError as e:
                    if e.resp.status == 429:
                        st.error("API 요청 한도가 초과되었습니다 (429 Error). 잠시 후 다시 시도해 주세요.")
                    else:
                        st.error(f"YouTube API 에러가 발생했습니다: {e}")
