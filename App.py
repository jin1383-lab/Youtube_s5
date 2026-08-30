import streamlit as st
from googleapiclient.discovery import build
from datetime import datetime, timedelta, timezone
import isodate
import json
import os

CHANNELS_FILE = "channels.json"

# --- JSON 파일 관리 헬퍼 함수 ---
def load_json(filename, default_val):
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default_val

def save_json(filename, data):
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        st.error(f"데이터 저장 중 오류 발생: {e}")

# --- 페이지 설정 ---
st.set_page_config(
    page_title="YouTube Popularity Radar V9.3",
    page_icon="🔥",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 세션 상태 초기화 ---
if "raw_data" not in st.session_state:
    st.session_state.raw_data = []

if "saved_channels" not in st.session_state:
    st.session_state.saved_channels = load_json(CHANNELS_FILE, [])

# --- 헬퍼 함수 ---
def format_duration(seconds):
    m, s = divmod(seconds, 60)
    return f"{m}분 {s}초" if m > 0 else f"{s}초"

def format_num(n):
    if n >= 100000000: return f"{n / 100000000:.1f}억"
    if n >= 10000: return f"{n / 10000:.1f}만"
    return f"{n:,}"

def check_trending(published_at_str, view_count):
    try:
        pub_date = datetime.strptime(published_at_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        diff_days = (now - pub_date).total_seconds() / 86400.0
        
        if diff_days <= 1 and view_count >= 200000:
            return True, "1일 20만+"
        elif diff_days <= 3 and view_count >= 500000:
            return True, "3일 50만+"
        elif diff_days <= 7 and view_count >= 1000000:
            return True, "7일 100만+"
    except Exception:
        pass
    return False, ""

# --- 사이드바 제어 패널 ---
with st.sidebar:
    st.title("🔥 인기 영상 랭킹 수집")
    st.caption("Streamlit v9.3 (대량 데이터 다중 수집 적용)")
    st.markdown("---")
    
    # 1. API Key 체크
    api_key = ""
    if "YOUTUBE_API_KEY" in st.secrets:
        api_key = st.secrets["YOUTUBE_API_KEY"]
        st.success("✅ YouTube API KEY 연결 완료")
    else:
        st.error("⚠️ API KEY가 등록되지 않았습니다.")
    
    st.markdown("---")
    
    # 2. 국가 선택
    region_dict = {
        "🇰🇷 한국 (Korea)": "KR", "🌐 글로벌 (전체)": "", "🇺🇸 미국 (USA)": "US", 
        "🇯🇵 일본 (Japan)": "JP", "🇪🇸 스페인 (Spain)": "ES", "🇬🇧 영국 (UK)": "GB"
    }
    region_label = st.selectbox("🌍 국가 선택 (Region)", list(region_dict.keys()), index=0)
    region_code = region_dict[region_label]

    # 3. 키워드 검색 옵션 (선택 사항)
    keyword_input = st.text_input("🔍 검색 키워드 (비워두면 전체 탐색)", value="")

    # 4. 탐색 깊이 (호출 페이지 수)
    fetch_pages = st.slider("📊 탐색 데이터 수 (50개 단위)", min_value=1, max_value=5, value=3, help="5페이지 설정 시 최대 250개 동영상을 조회하여 500만 이상 동영상을 추출합니다.")

    st.markdown("---")
    st.subheader("📊 조회수 & 영상 형태 필터")
    
    # 5. 조회수 범위 필터
    col_v1, col_v2 = st.columns(2)
    with col_v1: min_view = st.number_input("최소 조회수", min_value=0, value=5000000, step=500000)
    with col_v2: max_view = st.number_input("최대 조회수 (0은 제한없음)", min_value=0, value=0, step=1000000)
    
    # 6. 영상 형태 선택
    video_type = st.radio(
        "📱 영상 형태 선택",
        ["📱 숏폼 (1분 미만)", "🎬 롱폼 (1분 이상)", "🌐 전체"],
        index=0
    )

    st.markdown("---")
    search_triggered = st.button("🚀 데이터 수집 및 분석 시작", use_container_width=True)

# --- 데이터 수집 로직 (다중 페이지 탐색) ---
if search_triggered:
    if not api_key:
        st.error("⚠️ 시스템에 등록된 API 키가 없습니다.")
    else:
        with st.spinner(f"최대 {fetch_pages * 50}개 동영상을 수집 중입니다..."):
            try:
                youtube = build("youtube", "v3", developerKey=api_key)
                
                all_video_ids = []
                next_page_token = None
                
                # 지정된 페이지 수만큼 반복 호출하여 후보군을 200~250개 확보
                for _ in range(fetch_pages):
                    search_kwargs = {
                        "part": "snippet",
                        "type": "video",
                        "order": "viewCount",
                        "q": keyword_input if keyword_input.strip() else "",
                        "maxResults": 50,
                        "pageToken": next_page_token
                    }
                    if region_code:
                        search_kwargs["regionCode"] = region_code
                    
                    search_res = youtube.search().list(**search_kwargs).execute()
                    items = search_res.get("items", [])
                    
                    for item in items:
                        if "videoId" in item["id"]:
                            all_video_ids.append(item["id"]["videoId"])
                            
                    next_page_token = search_res.get("nextPageToken")
                    if not next_page_token:
                        break

                if not all_video_ids:
                    st.warning("수집된 영상이 없습니다.")
                    st.session_state.raw_data = []
                else:
                    # 50개 단위로 나누어 API 상세 데이터 조회
                    video_details = []
                    for i in range(0, len(all_video_ids), 50):
                        chunk_ids = all_video_ids[i:i+50]
                        v_res = youtube.videos().list(
                            part="statistics,snippet,contentDetails",
                            id=",".join(chunk_ids)
                        ).execute()
                        video_details.extend(v_res.get("items", []))
                    
                    # 채널 정보 가져오기
                    channel_ids = list(set([item["snippet"]["channelId"] for item in video_details]))
                    channel_map = {}
                    
                    for i in range(0, len(channel_ids), 50):
                        chunk_cids = channel_ids[i:i+50]
                        c_res = youtube.channels().list(
                            part="statistics",
                            id=",".join(chunk_cids)
                        ).execute()
                        for c in c_res.get("items", []):
                            channel_map[c["id"]] = int(c["statistics"].get("subscriberCount", 1))
                    
                    parsed_list = []
                    for item in video_details:
                        views = int(item["statistics"].get("viewCount", 0))
                        ch_id = item["snippet"]["channelId"]
                        subs = channel_map.get(ch_id, 1)
                        if subs == 0: subs = 1
                        
                        iso_duration = item["contentDetails"].get("duration", "PT0S")
                        duration_sec = int(isodate.parse_duration(iso_duration).total_seconds())
                        
                        parsed_list.append({
                            "id": item["id"],
                            "title": item["snippet"]["title"],
                            "channelTitle": item["snippet"]["channelTitle"],
                            "channelId": ch_id,
                            "publishedAt": item["snippet"]["publishedAt"],
                            "thumb": item["snippet"]["thumbnails"]["high"]["url"],
                            "viewCount": views,
                            "subCount": subs,
                            "duration": duration_sec,
                            "viralScore": (views / subs) * 100
                        })
                    
                    st.session_state.raw_data = parsed_list
            except Exception as e:
                st.error(f"오류가 발생했습니다: {e}")

# --- 메인 레이아웃 및 필터링 ---
st.title("📺 YouTube Popularity Radar")

col_count, col_sort = st.columns([2, 3])
filtered_data = st.session_state.raw_data

if filtered_data:
    # 1. 최소/최대 조회수 필터링
    filtered_data = [
        item for item in filtered_data
        if item["viewCount"] >= min_view and (max_view == 0 or item["viewCount"] <= max_view)
    ]
    
    # 2. 숏폼/롱폼 필터링
    if video_type == "📱 숏폼 (1분 미만)":
        filtered_data = [i for i in filtered_data if i["duration"] < 60]
    elif video_type == "🎬 롱폼 (1분 이상)":
        filtered_data = [i for i in filtered_data if i["duration"] >= 60]

    with col_sort:
        sort_by = st.radio("정렬 기준", ["조회수 순", "🔥 떡상 성과순", "최신순"], horizontal=True)
        
    if sort_by == "조회수 순":
        filtered_data = sorted(filtered_data, key=lambda x: x["viewCount"], reverse=True)
    elif "떡상" in sort_by:
        filtered_data = sorted(filtered_data, key=lambda x: x["viralScore"], reverse=True)
    elif sort_by == "최신순":
        filtered_data = sorted(filtered_data, key=lambda x: x["publishedAt"], reverse=True)

    with col_count:
        st.subheader(f"🏆 조건 만족 영상: {len(filtered_data)}개")

    if len(filtered_data) == 0:
        st.warning("⚠️ 지정한 조건(최소 500만 이상 등)에 맞는 영상이 탐색 데이터 내에 없습니다. 사이드바에서 '탐색 데이터 수' 슬라이더를 더 늘려보세요.")
    else:
        cols = st.columns(4)
        for idx, item in enumerate(filtered_data):
            col = cols[idx % 4]
            with col:
                with st.container(border=True):
                    st.markdown(f"### 🥇 **{idx + 1}위**")
                    
                    is_trending, trend_reason = check_trending(item["publishedAt"], item["viewCount"])
                    if is_trending:
                        st.error(f"🚀 **급상승** ({trend_reason})")

                    st.image(item["thumb"], use_container_width=True)
                    st.caption(f"⏱️ 영상 길이: {format_duration(item['duration'])}")
                    st.markdown(f"**[{item['title']}](https://youtube.com/watch?v={item['id']})**")
                    st.markdown(f"📺 **[ {item['channelTitle']} ](https://youtube.com/channel/{item['channelId']})**")
                    
                    multiplier = item['viralScore'] / 100
                    if item['viralScore'] >= 500:
                        st.warning(f"🔥 떡상급 성과 (x{multiplier:.1f})")
                    else:
                        st.info(f"📈 성과지수 (x{multiplier:.1f})")
                    
                    stat_col1, stat_col2 = st.columns(2)
                    with stat_col1:
                        st.metric(label="조회수", value=format_num(item['viewCount']))
                    with stat_col2:
                        st.metric(label="구독자", value=format_num(item['subCount']))
else:
    st.info("👈 사이드바에서 '🚀 데이터 수집 및 분석 시작' 버튼을 누르세요.")
