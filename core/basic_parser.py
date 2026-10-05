import re

# Free/offline parser for Korean past-exam explanation files.
QSTART = re.compile(r"^\s*(\d{1,3})\s*(?:[\.\)\-]|번\s*[\.\)]?)\s*(.+)")
CHOICE_PATTERNS = [
    re.compile(r"^\s*([1-9])\s*[\)\.]\s*(.+)"),
    re.compile(r"^\s*([①②③④⑤⑥⑦⑧⑨])\s*(.+)"),
]
ANSWER = re.compile(r"^\s*(?:정답|답)\s*[:：\]]\s*(.*)$", re.I)
EXPL = re.compile(r"^\s*(?:해설|설명)\s*[:：\]]?\s*(.*)$", re.I)


def _choice(line):
    for p in CHOICE_PATTERNS:
        m = p.match(line)
        if m:
            return m.group(2).strip()
    return None


def _new_question(text, page):
    return {
        "question_type": "multiple_choice",
        "question_text": text.strip(),
        "choices": [],
        "correct_answer": "",
        "explanation": "",
        "source_page": page,
    }


def extract_questions(pages):
    """Heuristic parser; no external API required.

    It is intentionally permissive for Korean hand-me-down explanation PDFs:
    '1. ...', '1 - ...', '1) ...', choices, then 정답/해설 blocks.
    """
    out = []
    current = None
    mode = "question"

    for page in pages:
        page_no = page.get("page")
        lines = (page.get("text") or "").splitlines()
        for raw in lines:
            line = re.sub(r"\s+", " ", raw).strip()
            if not line:
                continue

            am = ANSWER.match(line)
            if current and am:
                current["correct_answer"] = am.group(1).strip()
                mode = "answer"
                continue
            em = EXPL.match(line)
            if current and em:
                current["explanation"] = em.group(1).strip()
                mode = "explanation"
                continue

            m = QSTART.match(line)
            if m:
                body = m.group(2).strip()
                # Avoid treating a choice as a new question while a question is open.
                # New question numbers usually carry a sentence/question or substantial text.
                looks_like_q = (
                    "?" in body or "시오" in body or "것은" in body or "고르" in body
                    or "다음" in body or len(body) >= 16
                )
                if looks_like_q:
                    if current:
                        out.append(current)
                    current = _new_question(body, page_no)
                    mode = "question"
                    continue

            if current:
                c = _choice(line)
                if c and mode == "question" and len(current["choices"]) < 12:
                    current["choices"].append(c)
                    continue
                if mode == "explanation":
                    current["explanation"] = (current["explanation"] + " " + line).strip()
                elif mode == "answer":
                    # Some files put a short answer on the next line.
                    if not current["correct_answer"] and len(line) < 120:
                        current["correct_answer"] = line
                    else:
                        current["explanation"] = (current["explanation"] + " " + line).strip()
                elif mode == "question" and not current["choices"] and len(line) < 260:
                    current["question_text"] += " " + line

    if current:
        out.append(current)

    cleaned = []
    seen = set()
    for q in out:
        q["question_text"] = re.sub(r"\s+", " ", q["question_text"]).strip()
        if len(q["question_text"]) < 8:
            continue
        key = (q["source_page"], q["question_text"][:120])
        if key in seen:
            continue
        seen.add(key)
        q["question_type"] = "multiple_choice" if q["choices"] else "short_answer"
        cleaned.append(q)
    return cleaned
