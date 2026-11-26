"""
💕 데이트 코스 플래너 — Streamlit + Google Gemini 챗봇

기능
  · 비밀번호(pnumis) 로그인
  · [A] 사이드바 조건 입력 (지역·날짜·시간대·예산·이동수단·관계·취향)
  · [B] 첫 화면 예시 질문 버튼   · [G] 새 대화 / 로그아웃
  · [C] 대화로 코스 수정          · [F] 정해진 답변 형식(타임라인·비용·꿀팁·플랜B)
  · [D] Google 검색 연동으로 실제 장소 추천
  · [E] 코스 파일 저장(.md)
  · [H] 장소명 → 네이버지도 링크 자동 변환
  · [I] 👍👎 코스 평가 (👎 시 자동 재추천 + 사이드바 만족도 통계)
  · [J] 🎲 랜덤 데이트 (조건 전부 무작위)
  · [K] 🗺️ 코스 지도: 장소 번호 마커 + 실제 도로 경로 (course_map.py)
  · [L] ☀️ 데이트 날 일기예보 카드 + AI 코스에 날씨 반영 (weather.py)
"""

import hmac
import html
import queue
import threading
import random
import re
import uuid
from datetime import date, datetime
from urllib.parse import quote

import streamlit as st
from google import genai
from google.genai import errors, types

from course_map import show_course_map, split_course
from weather import get_weather, show_weather_card, weather_prompt

# ─────────────────────────────────────────────
# 기본 설정
# ─────────────────────────────────────────────
st.set_page_config(page_title="데이트 코스 플래너", page_icon="💕", layout="centered")

DEFAULT_PASSWORD = "pnumis"
# 앞 모델이 혼잡(503)·사용량 초과(429)·지원 종료(404)면 다음 모델로 자동 전환
MODEL_CHAIN = ["gemini-3.8-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
BOT_AVATAR, USER_AVATAR = "💘", "🙂"

TIME_SLOTS = ["낮 (11시~17시)", "오후~저녁 (14시~21시)", "저녁 (17시~22시)", "하루 종일"]
TRANSPORTS = ["도보", "대중교통", "자동차"]
RELATIONSHIPS = ["첫 만남·소개팅", "썸", "연애 초기", "오래된 연인", "기념일", "부부"]
STYLE_OPTIONS = ["🍽️ 맛집", "☕ 카페", "🎨 전시·문화", "🎳 액티비티", "🌳 자연·산책", "🌃 야경", "🛍️ 쇼핑", "🏠 실내 위주"]

EXAMPLE_PROMPTS = [
    "이번 주말 부산 해운대 근처로 저녁 데이트 코스 짜줘",
    "비 오는 날 실내에서 즐길 수 있는 코스 추천해줘",
    "1주년 기념일인데 특별한 코스 부탁해!",
    "첫 데이트라 너무 부담스럽지 않은 코스가 좋아",
]

# [J] 랜덤 데이트 후보
RANDOM_REGIONS = [
    "부산 해운대", "부산 광안리", "부산 서면·전포", "부산 남포동", "부산 영도 흰여울마을", "부산 기장",
    "부산 온천장·부산대", "서울 성수동", "서울 익선동", "서울 연남동", "서울 잠실", "인천 송도",
    "경주 황리단길", "전주 한옥마을", "강릉 안목해변", "여수 낭만포차거리", "대구 동성로", "제주 애월",
]
RANDOM_THEMES = [
    "레트로 감성 여행", "야경 맛집 투어", "골목 탐방", "먹방 챌린지", "인생샷 투어", "힐링 산책",
    "예술 감성", "전통시장 투어", "액티브 챌린지", "가성비 데이트", "비밀 아지트 찾기", "계절 한정 이벤트",
]

REDO_PROMPT = "👎 이 코스는 마음에 안 들어요. 다른 장소들로 새로운 코스를 짜 주세요."


def get_secret(key: str, default=None):
    """secrets.toml이 없거나 키가 없어도 안전하게 읽기."""
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default


# ─────────────────────────────────────────────
# 1) 비밀번호 확인
# ─────────────────────────────────────────────
def check_password() -> bool:
    if st.session_state.get("authenticated"):
        return True

    st.title("💕 데이트 코스 플래너")
    st.caption("AI와 대화하며 나만의 데이트 코스를 만들어 보세요.")
    with st.form("login"):
        pw = st.text_input("🔒 비밀번호를 입력하세요", type="password")
        submitted = st.form_submit_button("입장하기", use_container_width=True)

    if submitted:
        if hmac.compare_digest(pw, str(get_secret("APP_PASSWORD", DEFAULT_PASSWORD))):
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("비밀번호가 올바르지 않습니다.")
    return False


if not check_password():
    st.stop()


# ─────────────────────────────────────────────
# 세션 상태 초기화
# ─────────────────────────────────────────────
ss = st.session_state
ss.setdefault("messages", [])      # [{id, role, content}]
ss.setdefault("ratings", {})       # {메시지 id: 1(👍) / 0(👎)} — 새 대화를 해도 유지
ss.setdefault("region", "부산 서면·전포")
ss.setdefault("date_day", date.today())
ss.setdefault("time_slot", TIME_SLOTS[1])
ss.setdefault("budget", 100_000)
ss.setdefault("transport", "대중교통")
ss.setdefault("relationship", "연애 초기")
ss.setdefault("styles", ["🍽️ 맛집", "☕ 카페"])
ss.setdefault("extra", "")


# ─────────────────────────────────────────────
# 버튼 콜백
# ─────────────────────────────────────────────
def randomize_date():
    """[J] 지역·시간대·예산·이동수단·취향·테마를 무작위로 정하고 바로 코스 요청."""
    ss.region = random.choice(RANDOM_REGIONS)
    ss.time_slot = random.choice(TIME_SLOTS)
    ss.budget = random.randrange(30_000, 300_001, 10_000)
    ss.transport = random.choice(TRANSPORTS)
    ss.styles = random.sample(STYLE_OPTIONS, k=random.randint(1, 3))
    ss.extra = ""
    theme = random.choice(RANDOM_THEMES)
    ss.pending_prompt = f"🎲 랜덤 데이트! '{theme}' 테마로 {ss.region}에서 깜짝 코스를 짜 줘."


def on_feedback(msg_id: str):
    """[I] 평가 저장, 👎이면 다른 코스 자동 요청."""
    value = ss.get(f"fb_{msg_id}")
    if value is None:
        ss.ratings.pop(msg_id, None)
        return
    ss.ratings[msg_id] = value
    if value == 0:
        ss.pending_prompt = REDO_PROMPT


def new_chat():
    ss.messages = []


def logout():
    ss.clear()


# ─────────────────────────────────────────────
# 2) 사이드바 [A] 조건 입력 · [J] 랜덤 · [I] 통계 · [G] 버튼
# ─────────────────────────────────────────────
with st.sidebar:
    st.header("📝 데이트 조건")
    st.button("🎲 랜덤 데이트 (조건 무작위)", on_click=randomize_date, use_container_width=True, type="primary")

    st.text_input("📍 지역", key="region", help="예: 부산 해운대, 서울 성수동, 전주 한옥마을")
    st.date_input("📅 날짜", key="date_day", min_value=date.today())
    st.selectbox("🕐 시간대", TIME_SLOTS, key="time_slot")
    st.slider("💰 2인 총 예산 (원)", 30_000, 300_000, step=10_000, format="%d원", key="budget")
    st.radio("🚇 이동수단", TRANSPORTS, key="transport", horizontal=True)
    st.selectbox("💑 관계", RELATIONSHIPS, key="relationship")
    st.multiselect("✨ 선호 스타일", STYLE_OPTIONS, key="styles")
    st.text_area("🙋 기타 요청", key="extra", placeholder="예: 매운 음식 X, 사진 찍기 좋은 곳, 조용한 분위기")

    st.divider()
    use_search = st.toggle("🔎 실시간 웹 검색으로 장소 확인", value=False,
                           help="Google 검색으로 실제 존재하는 장소를 찾아 추천합니다. "
                                "무료 Gemini 키는 검색 사용량이 없어 유료 키에서만 동작해요. "
                                "(사용할 수 없으면 자동으로 검색 없이 답변)")

    # [I] 만족도 통계
    st.divider()
    st.subheader("📊 코스 만족도")
    ups = sum(1 for v in ss.ratings.values() if v == 1)
    downs = sum(1 for v in ss.ratings.values() if v == 0)
    c1, c2 = st.columns(2)
    c1.metric("👍 좋아요", ups)
    c2.metric("👎 별로예요", downs)
    if ups + downs:
        st.progress(ups / (ups + downs), text=f"만족도 {ups / (ups + downs) * 100:.0f}%")
    else:
        st.caption("답변 아래 👍👎로 코스를 평가해 주세요")

    st.divider()
    b1, b2 = st.columns(2)
    b1.button("🔄 새 대화", on_click=new_chat, use_container_width=True)
    b2.button("🚪 로그아웃", on_click=logout, use_container_width=True)


# [L] 선택한 지역·날짜·시간대의 날씨 (30분 캐시)
weather = get_weather(ss.region, ss.date_day, ss.time_slot)

# ─────────────────────────────────────────────
# 3) Gemini 설정
# ─────────────────────────────────────────────
api_key = str(get_secret("GEMINI_API_KEY") or "").strip()
if not api_key:
    st.error("GEMINI_API_KEY가 설정되지 않았습니다. Streamlit Cloud의 **Settings → Secrets**에 키를 등록해 주세요.")
    st.stop()
if not api_key.isascii() or not api_key.isprintable() or " " in api_key:
    # 키는 HTTP 헤더로 전송되므로 한글·공백·둥근 따옴표(“ ”)·보이지 않는 문자가 섞이면 UnicodeEncodeError가 난다
    st.error(
        "GEMINI_API_KEY 값에 영문·숫자가 아닌 문자가 섞여 있어요. "
        "**Settings → Secrets**에서 예시 문구(한글)나 공백, 둥근 따옴표(“ ”)가 남아 있지 않은지 확인하고 "
        '`GEMINI_API_KEY = "발급받은 키"` 형식으로 키만 다시 붙여 넣어 주세요.'
    )
    st.stop()


@st.cache_resource
def get_client(key: str) -> genai.Client:
    # 요청 전체 마감 90초 (서버에도 전달됨). 첫 글자 대기는 FIRST_TOKEN_TIMEOUT으로 따로 짧게 끊는다.
    return genai.Client(api_key=key, http_options=types.HttpOptions(timeout=90_000))


client = get_client(api_key)
preferred = get_secret("GEMINI_MODEL", MODEL_CHAIN[0])
models_to_try = [preferred] + [m for m in MODEL_CHAIN if m != preferred]


def build_system_prompt() -> str:
    weekday = "월화수목금토일"[ss.date_day.weekday()]
    style_text = ", ".join(s.split(" ", 1)[1] for s in ss.styles) if ss.styles else "상관없음"
    return f"""당신은 '데이트 코스 플래너'라는 친절하고 센스 있는 한국어 데이트 코스 전문가입니다.
사용자와 대화하면서 조건에 맞는 현실적인 데이트 코스를 설계해 주세요.

[사용자가 사이드바에서 설정한 조건]
- 지역: {ss.region or "미정"}
- 날짜: {ss.date_day:%Y-%m-%d} ({weekday}요일)
- 시간대: {ss.time_slot}
- 2인 총 예산: {ss.budget:,}원
- 이동수단: {ss.transport}
- 관계: {ss.relationship}
- 선호 스타일: {style_text}
- 기타 요청: {ss.extra or "없음"}
(사용자가 대화에서 다른 조건을 말하면 대화 내용을 우선합니다.)

[데이트 날 날씨]
{weather_prompt(weather)}

[코스를 제안할 때 형식]
1. 한 줄 컨셉 제목 (이모지 포함)
2. 시간순 타임라인: 각 장소마다 `시간 | 장소 | 하는 일 | 예상 비용(2인)` 을 마크다운 표로
3. 장소 간 이동 방법과 소요 시간 (이동수단 고려)
4. 💰 예상 총 비용 합계 — 반드시 예산 안에서
5. 💡 꿀팁 2~3개 (예약, 웨이팅, 포토스팟, 관계 단계에 맞는 대화·매너 팁 등)
6. ☔ 플랜 B: 비가 오거나 장소가 붐빌 때 대안 1개

[장소 표기 규칙 — 매우 중요]
- 구체적인 장소(가게·명소)를 쓸 때는 반드시 `[[장소명|지도검색어]]` 형식으로 감싸세요.
  지도검색어는 '지역 + 장소명'으로 네이버지도에서 바로 찾을 수 있게 씁니다.
  예) [[블루라인파크|부산 해운대 블루라인파크]], [[모모스커피|부산 영도 모모스커피]]
- 이 표기는 화면에서 네이버지도 링크로 자동 변환됩니다. 다른 링크(URL)는 직접 쓰지 마세요.

[지도용 장소 데이터 — 매우 중요]
- 코스를 제안하거나 수정한 답변의 **맨 끝**에, 타임라인의 장소를 방문 순서대로 아래 형식으로 덧붙이세요.
  이 부분은 화면에 보이지 않고 지도에 경로를 그리는 데만 쓰입니다. 코스 없이 질문만 하는 답변에는 넣지 마세요.
<course>{{"places": [{{"name": "장소명", "query": "지역 + 장소명", "time": "14:00", "cost": "18,000원", "lat": 35.1556, "lng": 129.0640}}]}}</course>
- lat/lng는 그 장소의 실제 위도·경도(소수점 4자리 이상)로 정확하게 쓰세요.
- 플랜 B 장소는 넣지 말고, 타임라인에 있는 장소만 넣으세요. JSON 외의 다른 글은 쓰지 마세요.

[규칙]
- 장소는 실제로 존재하는 곳을 추천하고, 확실하지 않으면 '(방문 전 영업시간 확인 필요)'라고 표시하세요.
- 3~5개 장소로 구성하고, 동선이 지그재그가 되지 않도록 가까운 곳끼리 묶으세요.
- 조건이 부족하면 코스를 먼저 하나 제안한 뒤, 더 맞춤형으로 바꾸기 위한 질문을 1~2개 덧붙이세요.
- 사용자가 "카페 바꿔줘", "더 저렴하게"처럼 수정을 요청하면 이전 코스를 바탕으로 해당 부분만 고쳐 전체 코스를 다시 보여주세요.
- 사용자가 코스가 마음에 안 든다고 하면, 이전 코스와 겹치지 않는 장소로 새 코스를 짜세요.
- 데이트·여가와 무관한 질문에는 정중하게 데이트 코스 이야기로 돌려주세요.
- 마크다운으로 깔끔하게, 너무 길지 않게 답하세요."""


# [H] [[장소명|검색어]] → 네이버지도 링크
PLACE_PATTERN = re.compile(r"\[\[([^\[\]|\n]{1,50})(?:\|([^\[\]\n]{1,80}))?\]\]")


def add_map_links(text: str) -> str:
    def repl(m):
        name, query = m.group(1).strip(), (m.group(2) or m.group(1)).strip()
        return f"[📍{name}](https://map.naver.com/p/search/{quote(query)})"
    return PLACE_PATTERN.sub(repl, text)


BOLD_PATTERN = re.compile(r"\*\*(.+?)\*\*")


def render(text: str) -> str:
    """화면 표시용 변환: 굵은 글씨 + 지도 링크.
    한국어는 '**강조)**를'처럼 조사가 바로 붙으면 마크다운 굵게가 깨지므로 <strong>으로 직접 바꾼다.
    AI 답변 속 HTML은 먼저 이스케이프해 그대로 실행되지 않게 한다."""
    safe = html.escape(split_course(text)[0], quote=False)   # [K] 지도용 데이터 블록은 숨김
    safe = BOLD_PATTERN.sub(r"<strong>\1</strong>", safe)
    safe = safe.replace("~", "\\~")   # '3~4만 원 … 5~6시'처럼 '~'가 두 번 나오면 취소선이 되는 것 방지
    return add_map_links(safe)


def to_gemini_history(messages):
    return [
        types.Content(role="user" if m["role"] == "user" else "model",
                      parts=[types.Part.from_text(text=m["content"])])
        for m in messages
    ]


FIRST_TOKEN_TIMEOUT = 15   # 서버가 붐벼 첫 글자가 이 시간(초) 안에 안 오면 다음 모델로


def stream_reply(messages, model: str, search: bool, thinking_low: bool = True):
    """Gemini 응답을 백그라운드 스레드에서 받아 조각(str)으로 내보낸다.
    첫 조각이 FIRST_TOKEN_TIMEOUT초 안에 오지 않으면 TimeoutError."""
    config = types.GenerateContentConfig(
        system_instruction=build_system_prompt(),   # session_state를 읽으므로 스레드 밖에서 미리 만든다
        temperature=0.8,
        tools=[types.Tool(google_search=types.GoogleSearch())] if search else None,  # [D]
        # 생각 단계를 짧게 해서 답이 빨리 시작되게 함 (지원하지 않는 모델은 generate()에서 빼고 재시도)
        thinking_config=types.ThinkingConfig(thinking_level="low") if thinking_low else None,
    )
    contents = to_gemini_history(messages)
    chunks = queue.Queue()

    def worker():
        try:
            for chunk in client.models.generate_content_stream(model=model, contents=contents, config=config):
                if chunk.text:
                    chunks.put(("text", chunk.text))
            chunks.put(("done", None))
        except Exception as e:
            chunks.put(("error", e))

    threading.Thread(target=worker, daemon=True).start()

    def pieces():
        wait = FIRST_TOKEN_TIMEOUT
        while True:
            try:
                kind, value = chunks.get(timeout=wait)
            except queue.Empty:
                raise TimeoutError(f"{model}: {wait}초 동안 응답 없음") from None
            if kind == "text":
                wait = 90   # 첫 조각 이후에는 넉넉히 기다림
                yield value
            elif kind == "done":
                return
            else:
                raise value

    return pieces()


def generate(messages) -> str:
    """답변을 실시간으로 화면에 그리고, 실패하면 검색 없이 / 다음 모델로 재시도."""
    box = st.empty()
    search_ok = use_search
    last_error = None
    for n, model in enumerate(models_to_try):
        for search in ([True, False] if search_ok else [False]):
            thinking_low = True
            while True:
                box.markdown("💭 코스를 짜는 중이에요..." if n == 0 else
                             "💭 AI 서버가 붐벼서 다른 모델로 다시 시도하는 중이에요...")
                text = ""
                try:
                    for piece in stream_reply(messages, model, search, thinking_low):
                        text += piece
                        box.markdown(render(text) + " ▌", unsafe_allow_html=True)
                    box.markdown(render(text), unsafe_allow_html=True)
                    if use_search and not search:
                        st.caption("ℹ️ 웹 검색을 사용할 수 없어 검색 없이 답변했어요. (방문 전 장소 정보를 확인해 주세요)")
                    return text
                except errors.APIError as e:
                    last_error = e
                    if e.code == 400 and "hinking" in str(e) and thinking_low:
                        thinking_low = False   # 이 모델은 생각 단계 설정 미지원 → 설정 없이 재시도
                        continue
                    if search:
                        search_ok = False      # 검색 사용량 초과 등 → 이후로는 검색 없이
                except Exception as e:         # 시간 초과·네트워크 오류 등 → 다음 모델로
                    last_error = e
                break

    box.empty()
    code = getattr(last_error, "code", None)
    if "timeout" in type(last_error).__name__.lower():
        st.error("AI 서버 응답이 너무 늦어요. 잠시 후 다시 시도해 주세요.")
    elif code == 429:
        st.error("요청이 너무 많아 잠시 쉬어야 해요. 1분 뒤 다시 시도해 주세요. (무료 사용량 제한)")
    elif code == 503:
        st.error("지금 AI 서버가 혼잡해요. 잠시 후 다시 시도해 주세요.")
    else:
        st.error(f"AI 응답 중 오류가 발생했어요: {last_error}")
    return ""


def feedback_widget(msg_id: str):
    st.feedback("thumbs", key=f"fb_{msg_id}", on_change=on_feedback, args=(msg_id,))


# ─────────────────────────────────────────────
# 4) 채팅 화면
# ─────────────────────────────────────────────
st.title("💕 데이트 코스 플래너")
st.caption(f"📍 {ss.region or '지역 미정'} · 💰 {ss.budget:,}원 · 🚇 {ss.transport} · 💑 {ss.relationship}"
           " — 조건은 왼쪽 사이드바에서 바꿀 수 있어요")
show_weather_card(weather)   # [L] 날씨 카드

# 입력: 채팅창 / 예시 버튼 / 랜덤 / 👎 재추천
prompt = st.chat_input("원하는 데이트를 말해 주세요 (예: 카페를 한 곳 더 넣어줘)")
prompt = prompt or ss.pop("pending_prompt", None)

# [B] 첫 화면: 인사말 + 예시 질문 (대화 시작 전에만)
if not ss.messages and not prompt:
    with st.chat_message("assistant", avatar=BOT_AVATAR):
        st.markdown(
            "안녕하세요! 저는 **데이트 코스 플래너**예요 😊\n\n"
            "왼쪽에서 지역·예산·취향을 고르고 원하는 데이트를 자유롭게 말씀해 주세요. "
            "마음에 안 드는 부분은 대화로 계속 바꿀 수 있고, 고민될 땐 **🎲 랜덤 데이트**를 눌러 보세요!"
        )
    st.markdown("**💬 이렇게 물어보세요**")
    cols = st.columns(2)
    for i, ex in enumerate(EXAMPLE_PROMPTS):
        if cols[i % 2].button(ex, key=f"ex{i}", use_container_width=True):
            ss.pending_prompt = ex
            st.rerun()

# 지난 대화 출력 (답변마다 지도 + 👍👎)
for m in ss.messages:
    with st.chat_message(m["role"], avatar=BOT_AVATAR if m["role"] == "assistant" else USER_AVATAR):
        st.markdown(render(m["content"]) if m["role"] == "assistant" else m["content"], unsafe_allow_html=m["role"] == "assistant")
        if m["role"] == "assistant":
            show_course_map(m.get("places", []), m.get("transport", "대중교통"))
            feedback_widget(m["id"])

if prompt:
    ss.messages.append({"id": uuid.uuid4().hex, "role": "user", "content": prompt})
    with st.chat_message("user", avatar=USER_AVATAR):
        st.markdown(prompt)

# 답변이 아직 없는 질문이 있으면 답변 생성
# (답변 생성 중 다른 버튼을 눌러 중단된 경우도 여기서 이어서 답변)
if ss.messages and ss.messages[-1]["role"] == "user":
    with st.chat_message("assistant", avatar=BOT_AVATAR):
        reply = generate(ss.messages)
        if reply:
            msg_id = uuid.uuid4().hex
            places = split_course(reply)[1]
            ss.messages.append({"id": msg_id, "role": "assistant", "content": reply,
                                "places": places, "transport": ss.transport})
            show_course_map(places, ss.transport)
            feedback_widget(msg_id)
    if not reply:
        ss.messages.pop()  # 실패한 질문은 기록에서 제거

# [E] 마지막 코스 저장
last = next((m for m in reversed(ss.messages) if m["role"] == "assistant"), None)
if last:
    st.download_button(
        "📥 마지막 코스 저장하기 (.md)",
        data=add_map_links(split_course(last["content"])[0]),
        file_name=f"date_course_{datetime.now():%Y%m%d_%H%M}.md",
        mime="text/markdown",
    )
