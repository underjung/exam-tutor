import json
import re
import base64

from .config import get_secret, openai_model, has_openai

def _client():
    from openai import OpenAI
    return OpenAI(api_key=get_secret("OPENAI_API_KEY"))

def _parse_json(text):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    # If the model wrapped JSON with prose, extract outermost structure.
    for left, right in [("[", "]"), ("{", "}")]:
        a, b = text.find(left), text.rfind(right)
        if a != -1 and b > a:
            try:
                return json.loads(text[a:b+1])
            except Exception:
                pass
    return json.loads(text)

def _respond(prompt):
    r = _client().responses.create(
        model=openai_model(),
        input=prompt
    )
    return r.output_text

def extract_outline(document_text):
    if not has_openai():
        return []
    prompt = f"""
아래 자료는 의과대학 시험 대비 정리본이다.
문서가 가르치는 순서대로 '학습 단원'만 추출하라.

중요:
- 표지의 과목명, 총평, 문항 수, 출제 경향은 단원으로 넣지 마라.
- 교수명이 있으면 교수명 아래 강의 주제 순서를 유지해도 된다.
- 너무 세세한 개별 사실이 아니라 문제를 분류할 수 있는 강의/소단원 단위로 만든다.
- 원문에 없는 단원을 새로 만들지 마라.
- JSON 배열만 반환한다.

형식:
["시냅스","감각수용기","오름신경로","통증", ...]

원문:
{document_text[:90000]}
"""
    try:
        data = _parse_json(_respond(prompt))
        return [str(x).strip() for x in data if str(x).strip()]
    except Exception:
        return []

def extract_questions_from_text(chunks, topics):
    topic_text = "\n".join(f"- {x}" for x in topics)
    out = []
    for chunk in chunks:
        prompt = f"""
아래는 의과대학 기출/해설 자료의 일부다.
'실제 시험문제'를 원문 근거대로 구조화하라.

정리본 단원 후보:
{topic_text}

반드시 JSON 배열만 반환:
[
  {{
    "question_type": "multiple_choice" | "short_answer" | "essay",
    "question_text": "정답이나 해설을 섞지 않은 문제 본문",
    "choices": ["선지1","선지2"],
    "correct_answer": "원문에 정답이 있으면 기록, 없으면 빈 문자열",
    "explanation": "원문에 기존 해설이 있으면 기록, 없으면 빈 문자열",
    "topic": "위 단원 후보 중 가장 가까운 것, 확신 없으면 빈 문자열",
    "year": "원문에서 확인되면 기록, 아니면 빈 문자열",
    "professor": "원문에서 확인되면 기록, 아니면 빈 문자열",
    "source_page": 1
  }}
]

규칙:
- 복기 불완전 문제도 가능한 범위에서 유지한다.
- 목차/총평/출제경향은 문제로 만들지 않는다.
- 원문에 없는 정답을 추측해서 넣지 않는다.
- source_page는 [PAGE N] 표시를 근거로 숫자를 넣는다.
- 문제 본문에서 '정답:', '해설:' 부분은 제거한다.

원문:
{chunk}
"""
        try:
            data = _parse_json(_respond(prompt))
            if isinstance(data, list):
                out.extend(data)
        except Exception:
            continue
    return out

def extract_questions_from_image_pdf(file_bytes, topics, max_pages=80):
    import fitz
    if not has_openai():
        return []
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    topic_text = "\n".join(f"- {x}" for x in topics)
    out = []
    for i, page in enumerate(doc):
        if i >= max_pages:
            break
        pix = page.get_pixmap(matrix=fitz.Matrix(1.45, 1.45), alpha=False)
        b64 = base64.b64encode(pix.tobytes("png")).decode("ascii")
        prompt = f"""
이 이미지는 의과대학 기출/해설 PDF의 {i+1}페이지다.
보이는 실제 문제들을 읽어 원문 근거대로 JSON 배열로 구조화하라.

단원 후보:
{topic_text}

형식:
[
  {{
    "question_type":"multiple_choice|short_answer|essay",
    "question_text":"",
    "choices":[],
    "correct_answer":"",
    "explanation":"",
    "topic":"",
    "year":"",
    "professor":"",
    "source_page":{i+1}
  }}
]

색/밑줄/표시로 정답을 알 수 있을 때만 correct_answer에 반영하라.
정답을 추측하지 마라. JSON만 반환.
"""
        try:
            r = _client().responses.create(
                model=openai_model(),
                input=[{
                    "role": "user",
                    "content": [
                        {"type":"input_text","text":prompt},
                        {"type":"input_image","image_url":f"data:image/png;base64,{b64}"}
                    ]
                }]
            )
            data = _parse_json(r.output_text)
            if isinstance(data, list):
                for q in data:
                    q["source_page"] = i+1
                    out.append(q)
        except Exception:
            continue
    return out

def grade(question, user_answer, reasoning, confidence, summary_context):
    if not has_openai():
        return {
            "is_correct": None,
            "status": "uncertain",
            "feedback": "AI가 연결되어 있지 않아 자동 평가를 하지 않았습니다."
        }

    context_text = "\n\n".join(
        f"[정리본: {filename}]\n{block}"
        for _, filename, block in summary_context
    )
    prompt = f"""
너는 의과대학 기출문제 학습 튜터다.
학생의 최종 답과 풀이 과정을 평가한다.

가장 중요한 원칙:
1) 아래 '기출의 정답/기존 해설'과 '정리본 검색 문맥'을 우선 근거로 사용한다.
2) 자료가 정답 판단을 충분히 뒷받침하지 않으면 그 사실을 명확히 말하고 억지로 단정하지 않는다.
3) 학생이 정답을 맞혔더라도 풀이 과정에 개념 오류가 있으면 지적한다.
4) 내부 추론 과정은 보여주지 말고, 학습에 필요한 간결한 설명만 제공한다.

문제:
{question.get("question_text","")}

선지:
{question.get("choices",[])}

기출에 기록된 정답:
{question.get("correct_answer","")}

기출의 기존 해설:
{question.get("explanation","")}

정리본 검색 문맥:
{context_text or "(검색된 문맥 없음)"}

학생 최종 답:
{user_answer}

학생 풀이 과정:
{reasoning}

자신감:
{confidence}

JSON만 반환:
{{
  "is_correct": true | false | null,
  "status": "correct" | "wrong" | "uncertain",
  "feedback": "### 잘한 점\\n...\\n\\n### 보완할 점\\n...\\n\\n### 핵심 해설\\n...\\n\\n### 더 좋은 풀이 접근\\n..."
}}
"""
    try:
        return _parse_json(_respond(prompt))
    except Exception as e:
        return {"is_correct": None, "status":"uncertain", "feedback":f"AI 평가 오류: {e}"}
