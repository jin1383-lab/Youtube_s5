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
    page_title="YouTube Popularity Radar V9.1",
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
def get_published_after(option):
    now = datetime.now(timezone.utc)
    if option == "최근 1일 (24시간)": delta = timedelta(days=1)
    elif option == "최근 3일": delta = timedelta(days=3)
    elif option == "최근 1주일 (7일)": delta = timedelta(days=7)
    elif option == "최근 15일": delta = timedelta(days=15)
    elif option == "최근 1달 (30일)": delta = timedelta(days=30)
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

# --- 사이드바 제어 패널 ---
with st.sidebar:
    st.title("🔥 인기 영상 랭킹 1~50")
    st.caption("Streamlit v9.1 (카테고리/키워드 무관 TOP 50)")
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
        "🇰🇷 한국 (Korea)": "KR", "🌐 글로벌 (전체)": "", "🇺🇸 미국 (USA)": "US", 
        "🇯🇵 일본 (Japan)": "JP", "🇪🇸 스페인 (Spain)": "ES", "🇬🇧 영국 (UK)": "GB"
    }
    region_label = st.selectbox("🌍 국가 선택 (Region)", list(region_dict.keys()), index=0)
    region_code = region_dict[region_label]

    # 3. 업로드 기간 선택
    date_option = st.selectbox(
        "📅 업로드 날짜 기준", 
        ["최근 1일 (24시간)", "최근 3일", "최근 1주일 (7일)", "최근 15일", "최근 1달 (30일)", "📅 특정 날짜 지정"], 
        index=2
    )
    
    start_date = None
    end_date = None
    
    if date_option == "📅 특정 날짜 지정":
        st.caption("👇 시작일과 종료일을 지정하세요.")
        col_d1, col_d2 = st.columns(2)
        with col_d1:
            start_date = st.date_input("시작일 (From)", value=datetime(2026, 8, 1))
        with col_d2:
            end_date = st.date_input("종료일 (To)", value=datetime(2026, 8, 29))
        
        st.info(f"📅 기간: **{start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}**")

    # 4. 저장된 관심 채널 관리 Expander
    with st.expander("⭐ 저장된 관심 채널 관리"):
        if not st.session_state.saved_channels:
            st.caption("저장된 채널이 없습니다.")
        else:
            for ch in list(st.session_state.saved_channels):
                col_c1, col_c2 = st.columns([3, 1])
                with col_c1:
                    st.markdown(f"[{ch['title']}](https://youtube.com/channel/{ch['id']})")
                with col_c2:
                    if st.button("삭제", key=f"del_ch_{ch['id']}"):
                        st.session_state.saved_channels = [c for c in st.session_state.saved_channels if c['id'] != ch['id']]
                        save_json(CHANNELS_FILE, st.session_state.saved_channels)
                        st.rerun()

    st.markdown("---")
    st.subheader("📊 조회수 & 영상 형태 필터")
    
    # 5. 조회수 범위 필터
    col_v1, col_v2 = st.columns(2)
    with col_v1: min_view = st.number_input("최소 조회수", min_value=0, value=1000000, step=500000)
    with col_v2: max_view = st.number_input("최대 조회수 (0은 제한없음)", min_value=0, value=0, step=1000000)
    
    # 6. 영상 형태 선택
    video_type = st.radio(
        "📱 영상 형태 선택",
        ["📱 숏폼 (1분 미만)", "🎬 롱폼 (1분 이상)", "🌐 전체"],
        index=0
    )

    st.markdown("---")
    search_triggered = st.button("🚀 TOP 1~50 조회하기", use_container_width=True)

# --- 데이터 수집 로직 (TOP 50 수집) ---
if search_triggered:
    if not api_key:
        st.error("⚠️ 시스템에 등록된 API 키가 없습니다.")
    elif date_option == "📅 특정 날짜 지정" and start_date > end_date:
        st.error("⚠️ 시작일이 종료일보다 늦을 수 없습니다.")
    else:
        with st.spinner("최신 인기 영상 TOP 1~50 수집 중..."):
            try:
                youtube = build("youtube", "v3", developerKey=api_key)
                
                search_kwargs = {
                    "part": "snippet",
                    "type": "video",
                    "order": "viewCount",
                    "q": "#",  # 넓은 범위 수집
                    "maxResults": 50
                }
                
                if region_code: 
                    search_kwargs["regionCode"] = region_code
                
                if date_option == "📅 특정 날짜 지정":
                    search_kwargs["publishedAfter"] = format_api_datetime(start_date, is_end_of_day=False)
                    search_kwargs["publishedBefore"] = format_api_datetime(end_date, is_end_of_day=True)
                else:
                    published_after = get_published_after(date_option)
                    if published_after:
                        search_kwargs["publishedAfter"] = published_after
                
                # 1~50위 수집
                search_res = youtube.search().list(**search_kwargs).execute()
                video_items = search_res.get("items", [])
                video_ids = [item["id"]["videoId"] for item in video_items]
                
                if not video_ids:
                    st.warning("지정한 기간에 수집된 영상이 없습니다.")
                    st.session_state.raw_data = []
                else:
                    # 영상 세부 정보 가져오기
                    v_res = youtube.videos().list(
                        part="statistics,snippet,contentDetails",
                        id=",".join(video_ids)
                    ).execute()
                    video_details = v_res.get("items", [])
                    
                    # 채널 구독자 수 가져오기
                    channel_ids = list(set([item["snippet"]["channelId"] for item in video_details]))
                    channel_map = {}
                    if channel_ids:
                        c_res = youtube.channels().list(
                            part="statistics",
                            id=",".join(channel_ids)
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
        st.subheader(f"🏆 조건 만족 영상: {len(filtered_data)}개 ({video_type.split()[1]})")

    saved_ch_ids = [c["id"] for c in st.session_state.saved_channels]

    cols = st.columns(4)
    for idx, item in enumerate(filtered_data):
        col = cols[idx % 4]
        with col:
            with st.container(border=True):
                # 순위 표시
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
    st.info("👈 왼쪽 사이드바에서 기간 및 최소 조회수를 설정한 후 '🚀 TOP 1~50 조회하기' 버튼을 누르세요.")
