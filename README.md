# 기초신경계 기출 튜터 — 웹사이트 버전

노트북과 태블릿에서 같은 주소로 접속해서 문제를 풀고,
풀이 기록·오답·숙달 상태를 동기화하는 Streamlit 웹앱입니다.

## 들어있는 기능

- 정리본 PDF/DOCX 업로드
- 정리본의 단원 순서 자동 추출 + 직접 수정
- 기출 PDF/DOCX 여러 개 업로드
- 기출 문제 자동 추출 및 단원 매칭
- 이미지형/스캔 PDF AI 인식
- 문제 제출 전 **정답 완전 숨김**
- 객관식/단답형/서술형
- **내 풀이 과정** 전용 입력칸
- 자신감: `확실함 / 애매함 / 찍음`
- 제출 후 정답, 기존 해설, AI 피드백
- `오답만 / 불확실만 / 오답+불확실 / 미숙달` 재풀이
- 풀이 시도 전체 이력 저장
- 찍음이 아닌 **2회 연속 정답 → 숙달**
- 단원별 오답률 대시보드
- 문제 관리/수정
- JSON 백업 다운로드
- 앱 비밀번호
- Supabase를 연결하면 태블릿 ↔ 노트북 기록 동기화
- Supabase 미연결 시 로컬 SQLite로 테스트 가능

---

# 가장 빠른 실제 사이트 배포 방법

## 1. Supabase 만들기

1. https://supabase.com 에서 새 프로젝트를 만듭니다.
2. `SQL Editor`를 엽니다.
3. 이 프로젝트의 `supabase_schema.sql` 내용을 붙여넣고 Run 합니다.
4. 프로젝트의 URL과 **server-side secret key (`sb_secret_...`)**를 확인합니다. 기존 `service_role` 키도 호환되지만 새 secret key 사용을 권장합니다.

> service role key는 비밀키입니다. GitHub에 올리지 마세요.

## 2. GitHub 저장소 만들기

이 폴더 전체를 GitHub repository에 올립니다.
단, `.streamlit/secrets.toml`, `.env` 같은 실제 비밀키 파일은 올리지 마세요.

## 3. Streamlit Community Cloud에 배포

1. https://share.streamlit.io 접속
2. GitHub 계정 연결
3. `Create app`
4. 방금 만든 repository 선택
5. Main file path: `streamlit_app.py`
6. App settings > Secrets에 아래를 입력

```toml
APP_PASSWORD = "사이트에 들어갈 때 사용할 비밀번호"

OPENAI_API_KEY = "sk-..."
OPENAI_MODEL = "gpt-5"

SUPABASE_URL = "https://xxxxx.supabase.co"
SUPABASE_SECRET_KEY = "sb_secret_..."
```

7. Deploy

배포가 완료되면 다음처럼 고정 주소가 생깁니다.

```text
https://원하는이름.streamlit.app
```

노트북과 태블릿에서 같은 URL을 열면 됩니다.

---

# 로컬에서 먼저 테스트

Python 3.10+ 권장.

```bash
python -m venv .venv
```

Windows:

```bash
.venv\Scripts\activate
```

macOS:

```bash
source .venv/bin/activate
```

설치:

```bash
pip install -r requirements.txt
```

실행:

```bash
streamlit run streamlit_app.py
```

Supabase를 아직 연결하지 않았다면 자동으로 `data/tutor.db`를 사용합니다.

---

# 사용 순서

1. 관리자 > 정리본 가져오기
2. 자동으로 뽑힌 단원 순서를 확인하고 수정
3. 관리자 > 기출 가져오기
4. 문제 추출 후 문제 관리에서 정답/단원 확인
5. 문제 풀기
6. 답 + 풀이 과정 + 자신감 제출
7. 오답 복습에서 틀린 문제만 재풀이

---

# 중요한 설계

AI 해설은 가능한 한 다음 근거 순서를 사용합니다.

1. 해당 문제 파일에 포함된 기존 정답/해설
2. 업로드한 정리본에서 검색된 관련 문맥
3. 자료가 부족하면 부족하다고 표시

즉 정리본에 없는 내용을 마음대로 정답처럼 덧붙이지 않도록 프롬프트를 구성했습니다.
