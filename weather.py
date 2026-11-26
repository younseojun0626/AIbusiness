"""
[L] 데이트 날 날씨 — Open-Meteo 일기예보(무료·키 없음)

흐름
  1. 사이드바 '지역' 글자에서 도시를 찾는다 (예: '부산 서면·전포' → 부산, '성수동' → 서울)
  2. 그 도시·날짜의 시간별 예보를 받아, 선택한 시간대(예: 14~21시)만 요약한다
  3. 화면에 날씨 카드를 보여주고, 같은 내용을 AI 지시문에 넣어 코스에 반영하게 한다
"""

import re
import time
from datetime import date

import requests
import streamlit as st

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# 도시 단위 좌표 (날씨는 도시 단위면 충분)
CITY_COORDS = {
    "서울": (37.5665, 126.9780), "부산": (35.1796, 129.0756), "인천": (37.4563, 126.7052),
    "대구": (35.8714, 128.6014), "대전": (36.3504, 127.3845), "광주": (35.1595, 126.8526),
    "울산": (35.5384, 129.3114), "세종": (36.4800, 127.2890), "수원": (37.2636, 127.0286),
    "성남": (37.4200, 127.1265), "고양": (37.6584, 126.8320), "용인": (37.2411, 127.1776),
    "가평": (37.8315, 127.5105), "양평": (37.4917, 127.4875), "파주": (37.7599, 126.7800),
    "춘천": (37.8813, 127.7298), "강릉": (37.7519, 128.8761), "속초": (38.2070, 128.5918),
    "경주": (35.8562, 129.2247), "포항": (36.0190, 129.3435), "안동": (36.5684, 128.7294),
    "창원": (35.2280, 128.6811), "통영": (34.8544, 128.4331), "거제": (34.8806, 128.6211),
    "전주": (35.8242, 127.1480), "군산": (35.9676, 126.7369), "여수": (34.7604, 127.6622),
    "순천": (34.9507, 127.4872), "목포": (34.8118, 126.3922), "천안": (36.8151, 127.1139),
    "청주": (36.6424, 127.4890), "제주": (33.4996, 126.5312), "서귀포": (33.2541, 126.5600),
}
# 동네·명소 이름 → 도시 (도시 이름이 없을 때만 사용)
AREA_TO_CITY = {
    "부산": ["해운대", "광안", "서면", "전포", "남포", "영도", "흰여울", "기장", "송정", "온천장", "부산대", "센텀", "다대포", "태종대"],
    "서울": ["성수", "홍대", "연남", "강남", "잠실", "익선", "한남", "이태원", "여의도", "종로", "명동", "신촌", "압구정",
             "가로수길", "망원", "을지로", "북촌", "삼청", "건대", "혜화", "대학로", "남산", "롯데월드"],
    "인천": ["송도", "월미도", "차이나타운"],
    "대구": ["동성로", "수성못"],
    "경주": ["황리단길", "보문"],
    "전주": ["한옥마을"],
    "강릉": ["안목", "경포"],
    "여수": ["낭만포차", "돌산"],
    "제주": ["애월", "협재", "함덕", "성산", "우도"],
    "서귀포": ["중문"],
    "수원": ["행궁동"],
    "춘천": ["남이섬"],
}

# WMO 날씨 코드 → (이모지, 설명). 숫자가 클수록 대체로 궂은 날씨
WEATHER_CODES = [
    (0, "☀️", "맑음"), (2, "🌤️", "구름 조금"), (3, "☁️", "흐림"), (48, "🌫️", "안개"),
    (57, "🌦️", "이슬비"), (67, "🌧️", "비"), (77, "🌨️", "눈"), (82, "🌦️", "소나기"),
    (86, "🌨️", "눈 소나기"), (99, "⛈️", "뇌우"),
]
WEEKDAYS = "월화수목금토일"


def find_city(region: str):
    text = region or ""
    for city in sorted(CITY_COORDS, key=len, reverse=True):   # '서귀포'를 '서' 계열보다 먼저
        if city in text:
            return city
    for city, areas in AREA_TO_CITY.items():
        if any(area in text for area in areas):
            return city
    return None


def _describe(code: int):
    for limit, emoji, desc in WEATHER_CODES:
        if code <= limit:
            return emoji, desc
    return "🌡️", "알 수 없음"


def _slot_hours(time_slot: str):
    m = re.search(r"(\d+)시~(\d+)시", time_slot or "")
    return (int(m.group(1)), int(m.group(2))) if m else (10, 22)


@st.cache_data(ttl=1800, show_spinner=False)
def _forecast(lat: float, lng: float, day: str) -> dict:
    """시간별 예보. 실패하면 예외를 던져 캐시에 남지 않게 한다."""
    res = requests.get(FORECAST_URL, timeout=10, params={
        "latitude": lat, "longitude": lng, "timezone": "Asia/Seoul",
        "hourly": "temperature_2m,precipitation_probability,weather_code",
        "start_date": day, "end_date": day,
    })
    data = res.json()
    if data.get("error"):
        raise ValueError(data.get("reason", "forecast error"))
    res.raise_for_status()
    return data["hourly"]


def get_weather(region: str, day: date, time_slot: str) -> dict:
    """날씨 요약 dict. 실패 시 {'error': 안내 문구}."""
    city = find_city(region)
    if not city:
        return {"error": "지역에서 도시를 찾지 못해 날씨를 불러오지 못했어요 (예: '부산 해운대'처럼 도시 이름을 넣어 주세요)."}
    if (day - date.today()).days > 14:
        return {"error": f"{day:%m/%d}은 아직 일기예보가 나오지 않았어요 (약 2주 이내 날짜만 가능)."}
    hourly = None
    for wait in (0, 1, 2):   # 무료 서버가 가끔 '동시 요청 많음'을 돌려줘서 잠깐 쉬고 다시 시도
        time.sleep(wait)
        try:
            hourly = _forecast(*CITY_COORDS[city], day.isoformat())
            break
        except Exception:
            continue
    if hourly is None:
        return {"error": "날씨 서버에 연결하지 못했어요. 잠시 후 다시 확인해 주세요."}

    start, end = _slot_hours(time_slot)
    rows = [(int(t[11:13]), temp, pop, code)
            for t, temp, pop, code in zip(hourly["time"], hourly["temperature_2m"],
                                          hourly["precipitation_probability"], hourly["weather_code"])
            if start <= int(t[11:13]) <= end and temp is not None]
    if not rows:
        return {"error": "선택한 시간대의 예보가 없어요."}
    temps = [r[1] for r in rows]
    pops = [r[2] or 0 for r in rows]
    emoji, desc = _describe(max(r[3] or 0 for r in rows))
    return {
        "city": city, "day": day, "hours": (start, end), "emoji": emoji, "desc": desc,
        "tmin": round(min(temps)), "tmax": round(max(temps)), "pop": max(pops),
    }


def weather_headline(w: dict) -> str:
    return (f"{w['emoji']} {w['day']:%m/%d}({WEEKDAYS[w['day'].weekday()]}) {w['city']} "
            f"{w['hours'][0]}~{w['hours'][1]}시 · {w['desc']} · {w['tmin']}~{w['tmax']}°C · 강수확률 {w['pop']}%")


def weather_tips(w: dict):
    tips = []
    if w["pop"] >= 50:
        tips.append("☔ 비 소식이 있어 실내 위주로 추천해요")
    elif w["pop"] >= 30:
        tips.append("🌂 비가 올 수도 있어요. 우산을 챙기세요")
    if w["tmin"] <= 3:
        tips.append("🧣 많이 추워요. 따뜻한 실내 장소를 섞어 추천해요")
    elif w["tmin"] <= 8:
        tips.append("🧥 쌀쌀해요. 겉옷을 챙기세요")
    if w["tmax"] >= 30:
        tips.append("🥵 더워요. 더위를 피할 수 있는 곳을 섞어 추천해요")
    return tips


def weather_prompt(w: dict) -> str:
    """AI 지시문에 넣을 날씨 설명."""
    if "error" in w:
        return "- 일기예보 없음: 날짜의 계절(월)을 고려해 코스를 짜세요."
    return (f"- 예보: {weather_headline(w)}\n"
            "- 답변 첫 부분에 이 날씨를 한 줄로 언급하고 코스에 반영하세요.\n"
            "  · 강수확률 50% 이상이면 실내 위주로, 30~49%면 실내 대안을 가까이 두세요.\n"
            "  · 최저기온 5°C 이하면 따뜻한 실내 장소·따뜻한 메뉴를, 최고기온 28°C 이상이면 더위를 피할 곳을 넣으세요.\n"
            "  · 플랜 B도 이 날씨에 맞게 제안하세요.")


def show_weather_card(w: dict):
    if "error" in w:
        st.caption(f"🌤️ 날씨: {w['error']}")
        return
    with st.container(border=True):
        st.markdown(f"**{weather_headline(w)}**".replace("~", "\\~"))   # '~' 두 개가 취소선이 되지 않게
        tips = weather_tips(w)
        st.caption((" · ".join(tips) + " — " if tips else "") + "AI가 이 날씨를 반영해 코스를 짜요. (예보: Open-Meteo)")
