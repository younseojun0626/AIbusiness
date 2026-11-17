# 💕 데이트 코스 플래너

Streamlit과 Google Gemini로 만든 **대화형 데이트 코스 추천 웹앱**입니다.
지역·예산·취향을 정하고 챗봇과 대화하면 시간순 데이트 코스를 짜 줍니다.

- 접속 비밀번호: `pnumis`

## 주요 기능
| 기능 | 설명 |
|---|---|
| 🔒 비밀번호 로그인 | 비밀번호를 입력해야 사용 가능 |
| 📝 조건 입력 사이드바 | 지역·날짜·시간대·예산·이동수단·관계·선호 스타일·기타 요청 |
| 💬 예시 질문 버튼 | 첫 화면에서 클릭 한 번으로 대화 시작 |
| ✏️ 대화로 코스 수정 | "카페 바꿔줘", "더 저렴하게" 등 |
| 🔎 실시간 웹 검색 | Gemini의 Google 검색 기능으로 실제 장소 추천 (유료 키 전용, 기본 꺼짐) |
| 📍 네이버지도 링크 | 추천 장소를 누르면 네이버지도 검색으로 연결 |
| 👍👎 코스 평가 | 👎를 누르면 새 코스 자동 추천, 사이드바에 만족도 통계 |
| 🎲 랜덤 데이트 | 지역·시간대·예산·이동수단·취향·테마를 무작위로 정해 깜짝 코스 추천 |
| 📥 코스 저장 | 마지막 코스를 `.md` 파일로 다운로드 |
| 🔄 새 대화 / 🚪 로그아웃 | 대화 초기화 / 처음 화면으로 |

## 로컬 실행
```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # GEMINI_API_KEY 입력
streamlit run app.py
```

## Streamlit Community Cloud 배포
1. 이 폴더를 GitHub 저장소에 올립니다. (`secrets.toml`은 올리지 마세요. `.gitignore`에 포함됨)
2. https://share.streamlit.io 에서 **Create app** → 저장소 / 브랜치 / `app.py` 선택
3. **Advanced settings → Secrets** 에 아래 내용 입력 후 Deploy
   ```toml
   GEMINI_API_KEY = "Google AI Studio에서 발급받은 키"
   APP_PASSWORD = "pnumis"
   ```
4. 생성된 `https://….streamlit.app` 주소를 PPT에 넣습니다.

Gemini API 키는 https://aistudio.google.com/apikey 에서 무료로 발급받을 수 있습니다.
기본 모델은 `gemini-3.8-flash`이며, 혼잡(503)·사용량 초과(429) 시 `gemini-3.5-flash` → `gemini-3.5-flash-lite` → `gemini-3.1-flash-lite` 순으로 자동 전환합니다.
