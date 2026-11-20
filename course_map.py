"""
[K] 코스 지도 — 장소 좌표(Gemini) + 실제 도로 경로(OSRM) → folium 지도

흐름
  1. Gemini가 답변 끝에 <course>{"places": [...]}</course> 로 장소·좌표를 덧붙인다 (화면에는 숨김)
  2. 이웃한 장소끼리 OSRM 길찾기 서버(OpenStreetMap 기반, 무료·키 없음)로 실제 경로를 받는다
     - 도보 → 도보 경로, 자동차 → 자동차 경로
     - 대중교통 → 1.5km 이하는 도보 경로, 그보다 멀면 도로 경로를 점선으로(버스·지하철 이동)
  3. 번호 마커 + 경로 선을 folium(Leaflet) 지도로 그린다
"""

import html
import json
import math
import re
from urllib.parse import quote

import folium
import requests
import streamlit as st
import streamlit.components.v1 as components

COURSE_BLOCK = re.compile(r"<course>\s*(.*?)\s*</course>", re.S)
OSRM_URL = "https://routing.openstreetmap.de/routed-{profile}/route/v1/driving/{coords}"
HEADERS = {"User-Agent": "date-course-planner/1.0 (Streamlit student project)"}
COLOR = "#E8456B"
WALK_LIMIT_M = 1500          # 대중교통 선택 시 이 거리 이하는 걸어서 이동
CIRCLED = "①②③④⑤⑥⑦⑧"


# ─────────────────────────────────────────────
# 1) 답변에서 장소 데이터 분리
# ─────────────────────────────────────────────
def split_course(text: str):
    """답변 → (화면에 보여줄 글, 장소 목록). 스트리밍 중 아직 닫히지 않은 <course 블록도 숨긴다."""
    match = COURSE_BLOCK.search(text)
    visible = COURSE_BLOCK.sub("", text)
    cut = visible.find("<course")
    if cut != -1:
        visible = visible[:cut]
    for k in range(len("<course") - 1, 1, -1):       # 끝에 걸린 '<cou' 같은 조각도 숨김
        if visible.endswith("<course"[:k]):
            visible = visible[:-k]
            break
    places = _parse_places(match.group(1)) if match else []
    return visible.rstrip(), places


def _parse_places(raw: str):
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        data = json.loads(raw)
    except ValueError:
        return []
    items = data.get("places", []) if isinstance(data, dict) else data
    places = []
    for p in items if isinstance(items, list) else []:
        try:
            lat, lng = float(p["lat"]), float(p["lng"])
        except (TypeError, KeyError, ValueError):
            continue
        if not (33 <= lat <= 39 and 124 <= lng <= 132):   # 한국 밖 좌표는 버림
            continue
        name = str(p.get("name") or "장소").strip()[:40]
        places.append({
            "name": name,
            "query": str(p.get("query") or name).strip()[:80],
            "time": str(p.get("time") or "").strip()[:20],
            "cost": str(p.get("cost") or "").strip()[:30],
            "lat": lat,
            "lng": lng,
        })
    return places[: len(CIRCLED)]


# ─────────────────────────────────────────────
# 2) 경로 계산
# ─────────────────────────────────────────────
def _straight_m(a, b) -> float:
    """두 좌표 사이 직선거리(m)."""
    lat1, lng1, lat2, lng2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


@st.cache_data(ttl=86400, show_spinner=False)
def _osrm(profile: str, a: tuple, b: tuple) -> dict:
    """OSRM 경로 요청. 실패하면 예외를 던져 캐시에 남지 않게 한다."""
    url = OSRM_URL.format(profile=profile, coords=f"{a[1]},{a[0]};{b[1]},{b[0]}")
    res = requests.get(url, params={"overview": "full", "geometries": "geojson"}, headers=HEADERS, timeout=8)
    res.raise_for_status()
    data = res.json()
    if data.get("code") != "Ok" or not data.get("routes"):
        raise ValueError(data.get("code"))
    route = data["routes"][0]
    return {
        "path": [(lat, lng) for lng, lat in route["geometry"]["coordinates"]],
        "distance": route["distance"],
        "duration": route["duration"],
    }


def build_segments(places, transport: str):
    segments = []
    for i, (p, q) in enumerate(zip(places, places[1:])):
        a, b = (p["lat"], p["lng"]), (q["lat"], q["lng"])
        straight = _straight_m(a, b)
        if transport == "자동차":
            profile, mode = "car", "자동차"
        elif transport == "도보" or straight <= WALK_LIMIT_M:
            profile, mode = "foot", "도보"
        else:
            profile, mode = "car", "대중교통"
        try:
            route = _osrm(profile, a, b)
        except Exception:
            route = None   # 길찾기 실패 → 직선 점선으로 대체
        segments.append({
            "index": i,
            "mode": mode,
            "routed": route is not None,
            "path": route["path"] if route else [a, b],
            "distance": route["distance"] if route else straight,
            # 대중교통은 버스·지하철 시간을 알 수 없어 표시하지 않음
            "duration": route["duration"] if route and mode != "대중교통" else None,
        })
    return segments


def _fmt_distance(m: float) -> str:
    return f"{m / 1000:.1f}km" if m >= 1000 else f"{m:.0f}m"


def _fmt_minutes(seconds: float) -> str:
    minutes = max(1, round(seconds / 60))
    return f"약 {minutes // 60}시간 {minutes % 60}분" if minutes >= 60 else f"약 {minutes}분"


def _segment_label(seg) -> str:
    i = seg["index"]
    text = f"{CIRCLED[i]}→{CIRCLED[i + 1]} {seg['mode']} {_fmt_distance(seg['distance'])}"
    if seg["duration"]:
        text += f" · {_fmt_minutes(seg['duration'])}"
    if not seg["routed"]:
        text += " (직선)"
    return text


# ─────────────────────────────────────────────
# 3) 지도 그리기
# ─────────────────────────────────────────────
def _build_map(places, segments) -> folium.Map:
    fmap = folium.Map(location=[places[0]["lat"], places[0]["lng"]], zoom_start=15,
                      tiles="OpenStreetMap", control_scale=True)

    for seg in segments:
        dashed = seg["mode"] == "대중교통" or not seg["routed"]
        folium.PolyLine(seg["path"], color=COLOR, weight=5, opacity=0.85,
                        dash_array="10 10" if dashed else None,
                        tooltip=_segment_label(seg)).add_to(fmap)

    for i, p in enumerate(places):
        name = html.escape(p["name"])
        detail = " · ".join(html.escape(x) for x in (p["time"], p["cost"]) if x)
        link = f"https://map.naver.com/p/search/{quote(p['query'])}"
        popup = (f"<div style='font-size:13px;line-height:1.5'><b>{CIRCLED[i]} {name}</b><br>"
                 f"{detail}<br><a href='{link}' target='_blank'>네이버지도에서 보기 ↗</a></div>")
        badge = (f"<div style='background:{COLOR};color:#fff;border:2px solid #fff;border-radius:50%;"
                 "width:28px;height:28px;display:flex;align-items:center;justify-content:center;"
                 f"font-weight:700;font-size:14px;box-shadow:0 1px 4px rgba(0,0,0,.4)'>{i + 1}</div>")
        folium.Marker([p["lat"], p["lng"]], tooltip=f"{i + 1}. {name}",
                      popup=folium.Popup(popup, max_width=240),
                      icon=folium.DivIcon(html=badge, icon_size=(28, 28), icon_anchor=(14, 14))).add_to(fmap)

    points = [pt for seg in segments for pt in seg["path"]] + [(p["lat"], p["lng"]) for p in places]
    if len(points) > 1:
        fmap.fit_bounds([[min(x[0] for x in points), min(x[1] for x in points)],
                         [max(x[0] for x in points), max(x[1] for x in points)]], padding=(30, 30))
    return fmap


def show_course_map(places, transport: str):
    """답변 아래에 코스 지도와 구간 요약을 그린다."""
    if not places:
        return
    with st.spinner("🗺️ 지도에 경로를 그리는 중..."):
        segments = build_segments(places, transport)
        fmap = _build_map(places, segments)
    components.html(fmap.get_root().render(), height=380)

    if segments:
        total = sum(s["distance"] for s in segments)
        st.markdown(f"**🗺️ 이동 경로** · 총 {_fmt_distance(total)}  \n" +
                    "  \n".join(_segment_label(s) for s in segments))
    notes = ["📍 위치는 AI가 추정한 좌표라 실제와 조금 다를 수 있어요. 정확한 위치는 마커를 눌러 네이버지도로 확인하세요."]
    if any(s["mode"] == "대중교통" for s in segments):
        notes.append("점선은 버스·지하철로 이동하는 구간이에요 (도로 기준으로 표시).")
    notes.append("경로: OpenStreetMap · OSRM")
    st.caption(" ".join(notes))
