"""
[M] 실제 장소 검증 — 카카오 로컬 장소 검색 API (무료, REST 키 필요)

AI가 추천한 장소([[장소명|검색어]])를 카카오맵에서 하나씩 검색해
  · 찾으면  → 카카오에 등록된 정식 이름·주소·좌표·상세 페이지 링크로 교체 (✅)
  · 못 찾으면 → None (app.py가 AI에게 다른 실제 장소로 바꿔 달라고 다시 요청)
"""

import math
import re
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher

import requests
import streamlit as st

KAKAO_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
PLACE_PATTERN = re.compile(r"\[\[([^\[\]|\n]{1,50})(?:\|([^\[\]\n]{1,80}))?\]\]")
MAX_DISTANCE_M = 8000      # AI 좌표와 이보다 멀면 같은 이름의 다른 지역 가게로 보고 제외
SIMILARITY = 0.8           # 이름 유사도 기준 (0~1)


def extract_places(text: str):
    """답변 속 [[장소명|검색어]] → {장소명: 검색어} (순서 유지, 중복 제거)."""
    found = {}
    for m in PLACE_PATTERN.finditer(text):
        name = m.group(1).strip()
        found.setdefault(name, (m.group(2) or name).strip())
    return found


def _norm(name: str) -> str:
    return re.sub(r"[\s\-·.,'’&()\[\]]", "", name).lower()


def _core(name: str) -> str:
    """'블랙업커피 서면본점' → '블랙업커피' (마지막 단어가 'OO점'이면 지점명으로 보고 뗌)."""
    words = name.split()
    if len(words) > 1 and words[-1].endswith("점"):
        words = words[:-1]
    return _norm(" ".join(words))


def same_place(ai_name: str, kakao_name: str) -> bool:
    a, k = _core(ai_name), _core(kakao_name)
    a_full, k_full = _norm(ai_name), _norm(kakao_name)
    if not a or not k:
        return False
    if a == k or a_full == k_full or a_full == k or a == k_full:
        return True
    return SequenceMatcher(None, a, k).ratio() >= SIMILARITY


def _distance_m(lat1, lng1, lat2, lng2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    h = (math.sin((p2 - p1) / 2) ** 2 +
         math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2)
    return 2 * 6371000 * math.asin(math.sqrt(h))


@st.cache_data(ttl=86400, show_spinner=False)
def _kakao_search(key: str, query: str) -> list:
    """카카오 키워드 검색. 실패하면 예외를 던져 캐시에 남지 않게 한다."""
    res = requests.get(KAKAO_URL, params={"query": query, "size": 10},
                       headers={"Authorization": f"KakaoAK {key}"}, timeout=6)
    res.raise_for_status()
    return res.json().get("documents", [])


def _verify_one(key: str, name: str, query: str, hint):
    """장소 하나 확인 → 카카오 정보 dict 또는 None. hint = AI가 준 (lat, lng) 또는 None."""
    for q in dict.fromkeys([query, name]):          # 검색어로 먼저, 안 되면 이름만으로
        docs = _kakao_search(key, q)   # 키·네트워크 오류는 예외로 올라가 '없는 장소'와 구분된다
        for d in docs:
            if not same_place(name, d["place_name"]):
                continue
            lat, lng = float(d["y"]), float(d["x"])
            if hint and _distance_m(hint[0], hint[1], lat, lng) > MAX_DISTANCE_M:
                continue
            return {
                "name": d["place_name"],
                "address": d.get("road_address_name") or d.get("address_name", ""),
                "category": (d.get("category_name") or "").split(" > ")[-1],
                "lat": lat, "lng": lng,
                "url": d.get("place_url") or f"https://map.kakao.com/link/search/{d['place_name']}",
            }
    return None


def verify_places(key: str, text: str, coords: dict):
    """답변 속 모든 장소 확인.
    반환: ({장소명: 카카오정보 또는 None}, 오류메시지 또는 None)
    coords = {장소명: (lat, lng)} — AI가 지도용으로 준 좌표 (같은 이름 다른 지역 구분용)"""
    places = extract_places(text)
    if not places:
        return {}, None
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {name: pool.submit(_verify_one, key, name, query, coords.get(name))
                   for name, query in places.items()}
    results, error = {}, None
    for name, fut in futures.items():
        try:
            results[name] = fut.result()
        except requests.HTTPError as e:
            code = e.response.status_code if e.response is not None else None
            error = ("카카오 키가 올바르지 않거나 '카카오맵' 사용 설정이 꺼져 있어요."
                     if code in (401, 403) else "카카오 장소 검색에 실패했어요.")
        except Exception:
            error = "카카오 장소 검색 서버에 연결하지 못했어요."
    if error:        # 검색 자체가 안 되면 '없는 장소'로 판정하지 않음
        return {}, error
    return results, None
