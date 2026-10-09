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
            "publish
