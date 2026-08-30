import streamlit as st
from googleapiclient.discovery import build
from datetime import datetime, timedelta, timezone
import isodate
import json
import os

KEYWORDS_FILE = "keywords.json"
CHANNELS_FILE = "channels.json"

# 유튜브 주요 기본 카테고리 매핑 (ID: 이름)
YOUTUBE_CATEGORIES = {
    "전체 (카테고리 지정 안함)": "",
    "🎬 영화/애니메이션": "1",
    "🚗 자동차": "2",
    "🎵 음악": "10",
    "🐶 반려동물/동물": "15",
    "⚽ 스포츠": "17",
    "🎮 게임": "20",
    "📷 일상/블로그": "22",
    "🤣 코미디": "23",
    "🎭 엔터테인먼트": "24",
    "📰 뉴스/정치": "25",
    "💡 노하우/스타일": "26",
    "🎓 교육": "27",
    "🔬 과학기술": "28"
}

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
    page_title="YouTube Insight Dashboard V8.1",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 세션 상태 초기화 ---
if "raw_data" not in st.session_state:
    st.session_state.raw_data = []

if "keyword_history" not in st.session_state:
    st.session_state.keyword_history = load_json(KEYWORDS_FILE, ["#family", "#funny cat", "#comedy"])

if "saved_channels" not in st.session_state:
    st.session_state.saved_channels = load_json(CHANNELS_FILE, [])

if "search_keyword_input" not in st.session_state:
    st.session_state.search_keyword_input = ""

# --- 헬퍼 함수 ---
def get_published_after(option):
    if option in ["전체", "📅 특정 년/월/일 지정"]: return None
    now = datetime.now(timezone.utc)
    if option == "최근 24시간": delta = timedelta(days=1)
    elif option == "최근 3일": delta = timedelta(days=3)
    elif option == "최근 1주일": delta = timedelta(days=7)
    elif option == "최근 1달": delta = timedelta(days=30)
    elif option == "최근 3개월": delta = timedelta(days=90)
    elif option == "최근 6개월": delta = timedelta(days=180)
    elif option == "최근 1년": delta = timedelta(days=365)
    elif option == "최근 2년": delta = timedelta(days=365 * 2)
    elif option == "최근 3년": delta = timedelta(days=365 * 3)
    else: return None
    
    target_time = now - delta
    return target_time.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%S") + "Z"

def format_api_datetime(date_obj, is_end_of_day=False):
    if is_end_of_day:
        dt = datetime.combine(date_obj, datetime.max.time()).replace(tzinfo=timezone.utc)
    else:
        dt = datetime.combine(date_obj, datetime.min.time()).replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"

def format_duration(seconds):
    m, s = divmod(seconds, 60)
    return f"{m}분 {s}초" if m > 0 else f"{s}초"

def format_num(n):
    if n >= 100000000: return f"{n / 100000000:.1f}억"
    if n >= 10000: return f"{n / 10000:.1f}만"
    return f"{n:,}"

# 📌 급상승 판별 함수
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

def apply_selected_keyword():
    selected = st.session_state.history_select
    if selected != "선택하세요...":
        st.session_state.search_keyword_input = selected

# --- 사이드바 제어 패널 ---
with st.sidebar:
    st.title("🚀 Insight Dash")
    st.caption("Streamlit v8.1 (카테고리 검색 & 무키워드 TOP 50 지원)")
    st.markdown("---")
    
    # 1. API Key 체크
    api_key = ""
    if "YOUTUBE_API_KEY" in st.secrets:
        api_key = st.secrets["YOUTUBE_API_KEY"]
        st.success("✅ YouTube API KEY 연결 완료")
    else:
        st.error("⚠️ API KEY가 등록되지 않았습니다.\nSecrets 설정을 확인해 주세요.")
    
    st.markdown("---")
    
    # 2. 국가 선택
    region_dict = {
        "🌐 글로벌 (전체)": "", "🇰🇷 한국 (Korea)": "KR", "🇺🇸 미국 (USA)": "US", 
        "🇯🇵 일본 (Japan)": "JP", "🇪🇸 스페인 (Spain)": "ES", "🇩🇪 독일 (Germany)": "DE", 
        "🇬🇧 영국 (UK)": "GB", "🇫🇷 프랑스 (France)": "FR", "🇮🇹 이탈리아 (Italy)": "IT"
    }
    region_label = st.selectbox("🌍 국가 선택 (Region)", list(region_dict.keys()), index=1)
    region_code = region_dict[region_label]
    
    # 3. 유튜브 카테고리 선택 (NEW)
    selected_category_label = st.selectbox("📂 유튜브 카테고리 선택", list(YOUTUBE_CATEGORIES.keys()), index=0)
    category_id = YOUTUBE_CATEGORIES[selected_category_label]

    # 4. 키워드 검색 (선택 사항)
    keyword = st.text_input(
        "🔍 키워드 검색 (선택 - 비워두면 카테고리 전체)", 
        key="search_keyword_input",
        placeholder="비워두거나 키워드 입력 (예: #family)"
    )
    
    if st.session_state.keyword_history:
        st.selectbox(
            "📜 저장된 자주 쓰는 키워드",
            ["선택하세요..."] + st.session_state.keyword_history,
            key="history_select",
            on_change=apply_selected_keyword
        )

    # 5. 기간 설정 방식 선택 (기본값: 특정 년/월/일 지정)
    date_option = st.selectbox(
        "📅 기간 설정 방식", 
        ["📅 특정 년/월/일 지정", "최근 24시간", "최근 3일", "최근 1주일", "최근 1달", "최근 3개월", "최근 6개월", "최근 1년", "전체"], 
        index=0
    )
    
    start_date = None
    end_date = None
    
    if date_option == "📅 특정 년/월/일 지정":
        st.caption("👇 특정 기간을 선택하세요.")
        col_d1, col_d2 = st.columns(2)
        with col_d1:
            start_date = st.date_input("시작일 (From)", value=datetime(2026, 8, 1))
        with col_d2:
            end_date = st.date_input("종료일 (To)", value=datetime(2026, 8, 29))
        
        st.info(f"📅 검색 범위: **{start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}**")
    
    st.markdown("---")
    st.subheader("📊 실시간 정밀 필터")
    
    # 6. 조회수 범위 필터
    col_v1, col_v2 = st.columns(2)
    with col_v1: min_view = st.number_input("최소 조회수", min_value=0, value=1000000, step=100000)
    with col_v2: max_view = st.number_input("최대 조회수 (0은 없음)", min_value=0, value=0, step=100000)
    
    # 7. 영상 형태 선택
    video_type = st.radio(
        "📱 영상 형태 선택",
        ["📱 숏폼 (1분 미만)", "🎬 롱폼 (1분 이상)", "🌐 전체"],
        index=0
    )

    st.markdown("---")
    search_triggered = st.button("🚀 TOP 50 분석 시작", use_container_width=True)

# --- 데이터 수집 로직 ---
if search_triggered:
    if not api_key:
        st.error("⚠️ 시스템에 등록된 API 키가 없습니다.")
    elif date_option == "📅 특정 년/월/일 지정" and start_date > end_date:
        st.error("⚠️ 시작일이 종료일보다 늦을 수 없습니다.")
    else:
        if keyword:
            if keyword in st.session_state.keyword_history:
                st.session_state.keyword_history.remove(keyword)
            st.session_state.keyword_history.insert(0, keyword)
            st.session_state.keyword_history = st.session_state.keyword_history[:30]
            save_json(KEYWORDS_FILE, st.session_state.keyword_history)

        with st.spinner("유튜브 데이터 수집 및 TOP 50 추출 중..."):
            try:
                youtube = build("youtube", "v3", developerKey=api_key)
                
                search_kwargs = {
                    "part": "snippet",
                    "type": "video",
                    "order": "viewCount",  # 조회수 기준 높은 순 정렬
                    "maxResults": 50
                }
                
                # 키워드가 있으면 추가, 없으면 제거
                if keyword.strip():
                    search_kwargs["q"] = keyword.strip()
                
                # 카테고리 ID 적용
                if category_id:
                    search_kwargs["videoCategoryId"] = category_id
                
                # 국가 코드 적용
                if region_code: 
                    search_kwargs["regionCode"] = region_code
                
                # 기간 설정
                if date_option == "📅 특정 년/월/일 지정":
                    search_kwargs["publishedAfter"] = format_api_datetime(start_date, is_end_of_day=False)
                    search_kwargs["publishedBefore"] = format_api_datetime(end_date, is_end_of_day=True)
                else:
                    published_after = get_published_after(date_option)
                    if published_after:
                        search_kwargs["publishedAfter"] = published_after
                
                search_res = youtube.search().list(**search_kwargs).execute()
                video_ids = [item["id"]["videoId"] for item in search_res.get("items", [])]
                
                if not video_ids:
                    st.warning("선택한 조건에 일치하는 영상이 없습니다.")
                    st.session_state.raw_data = []
                else:
                    video_res = youtube.videos().list(
                        part="statistics,snippet,contentDetails",
                        id=",".join(video_ids)
                    ).execute()
                    
                    channel_ids = list(set([item["snippet"]["channelId"] for item in video_res.get("items", [])]))
                    channel_res = youtube.channels().list(
                        part="statistics",
                        id=",".join(channel_ids)
                    ).execute()
                    
                    channel_map = {c["id"]: int(c["statistics"].get("subscriberCount", 1)) for c in channel_res.get("items", [])}
                    
                    parsed_list = []
                    for item in video_res.get("items", []):
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
st.title("📺 YouTube Insight Dashboard")

col_count, col_sort = st.columns([2, 3])
filtered_data = st.session_state.raw_data

if filtered_data:
    # 최소/최대 조회수 필터 적용
    filtered_data = [
        item for item in filtered_data
        if item["viewCount"] >= min_view and (max_view == 0 or item["viewCount"] <= max_view)
    ]
    
    # 숏폼/롱폼 필터 적용
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
        st.subheader(f"🏆 TOP 랭킹 결과: {len(filtered_data)}개 ({video_type.split()[1]})")

    saved_ch_ids = [c["id"] for c in st.session_state.saved_channels]

    cols = st.columns(4)
    for idx, item in enumerate(filtered_data):
        col = cols[idx % 4]
        with col:
            with st.container(border=True):
                # 순위 표시 (1위 ~ N위)
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
                
                if item["channelId"] in saved_ch_ids:
                    st.button("✅ 저장된 채널", key=f"btn_saved_{item['id']}", disabled=True, use_container_width=True)
                else:
                    if st.button("⭐ 채널 저장", key=f"btn_save_{item['id']}", use_container_width=True):
                        st.session_state.saved_channels.append({
                            "id": item["channelId"],
                            "title": item["channelTitle"]
                        })
                        save_json(CHANNELS_FILE, st.session_state.saved_channels)
                        st.toast(f"'{item['channelTitle']}' 채널이 저장되었습니다! ⭐")
                        st.rerun()
else:
    st.info("👈 왼쪽 사이드바에서 조건(카테고리, 날짜, 조회수 등)을 선택한 뒤 '🚀 TOP 50 분석 시작' 버튼을 눌러주세요.")
