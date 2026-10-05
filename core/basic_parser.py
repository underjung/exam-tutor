import re

QSTART = re.compile(r"^\s*(\d{1,3})[\.\)]\s+(.+)")
CHOICES = [
    re.compile(r"^\s*([1-9])[\)\.]\s*(.+)"),
    re.compile(r"^\s*([①②③④⑤⑥⑦⑧⑨])\s*(.+)")
]

def _choice(line):
    for p in CHOICES:
        m = p.match(line)
        if m:
            return m.group(2).strip()
    return None

def extract_questions(pages):
    out = []
    for page in pages:
        current = None
        mode = "question"
        for raw in (page.get("text") or "").splitlines():
            line = re.sub(r"\s+", " ", raw).strip()
            if not line:
                continue

            # answer/explanation labels
            if current and re.match(r"^(정답|답)\s*[:\]]", line, re.I):
                current["correct_answer"] = re.sub(r"^(정답|답)\s*[:\]]\s*", "", line, flags=re.I)
                mode = "answer"
                continue
            if current and re.match(r"^(해설|설명)\s*[:\]]", line, re.I):
                current["explanation"] = re.sub(r"^(해설|설명)\s*[:\]]\s*", "", line, flags=re.I)
                mode = "explanation"
                continue

            m = QSTART.match(line)
            looks_q = bool(m and ("?" in m.group(2) or "시오" in m.group(2) or len(m.group(2)) >= 18))
            if looks_q:
                if current:
                    out.append(current)
                current = {
                    "question_type": "multiple_choice",
                    "question_text": m.group(2).strip(),
                    "choices": [],
                    "correct_answer": "",
                    "explanation": "",
                    "source_page": page.get("page")
                }
                mode = "question"
                continue

            if current:
                c = _choice(line)
                if c and len(current["choices"]) < 9:
                    current["choices"].append(c)
                    continue
                if mode == "explanation":
                    current["explanation"] = (current["explanation"] + " " + line).strip()
                elif mode == "question" and not current["choices"] and len(line) < 240:
                    current["question_text"] += " " + line

        if current:
            out.append(current)

    cleaned = []
    for q in out:
        if len(q["question_text"]) < 8:
            continue
        q["question_type"] = "multiple_choice" if q["choices"] else "short_answer"
        cleaned.append(q)
    return cleaned
