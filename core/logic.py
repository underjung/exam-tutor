import re
from .database import list_questions, latest_attempt_map, consecutive_correct

def normalize_answer(value):
    if value is None:
        return ""
    s = str(value).strip().lower()
    circled = {"①":"1","②":"2","③":"3","④":"4","⑤":"5","⑥":"6","⑦":"7","⑧":"8","⑨":"9"}
    for k,v in circled.items():
        s = s.replace(k,v)
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"번$", "", s)
    return s

def deterministic_mc_grade(q, user_answer):
    correct = normalize_answer(q.get("correct_answer",""))
    user = normalize_answer(user_answer)
    if not correct:
        return None

    # Number inside answers such as "2번, AMPA" or "정답 2"
    m = re.search(r"(?<!\d)([1-9])(?!\d)", correct)
    if m and user == m.group(1):
        return True

    if user.isdigit():
        idx = int(user) - 1
        choices = q.get("choices", [])
        if 0 <= idx < len(choices):
            chosen = normalize_answer(choices[idx])
            if chosen and (chosen == correct or chosen in correct or correct in chosen):
                return True

    return user == correct

def eligible(mode, topic_id=None):
    qs = list_questions(topic_id)
    latest = latest_attempt_map()
    out = []
    for q in qs:
        a = latest.get(q["id"])
        if mode == "전체":
            out.append(q)
        elif mode == "미풀이" and not a:
            out.append(q)
        elif mode == "오답만" and a and a.get("status") == "wrong":
            out.append(q)
        elif mode == "불확실만" and a and a.get("status") in {"uncertain","skipped"}:
            out.append(q)
        elif mode == "오답 + 불확실" and a and a.get("status") in {"wrong","uncertain","skipped"}:
            out.append(q)
        elif mode == "미숙달" and consecutive_correct(q["id"]) < 2:
            out.append(q)
    return out

def topic_performance():
    qs = list_questions()
    latest = latest_attempt_map()
    agg = {}
    for q in qs:
        title = q.get("topic_title") or "미분류"
        x = agg.setdefault(title, {"단원":title, "문제수":0, "풀이수":0, "오답수":0, "불확실":0, "숙달":0})
        x["문제수"] += 1
        a = latest.get(q["id"])
        if a:
            x["풀이수"] += 1
            if a.get("status") == "wrong":
                x["오답수"] += 1
            if a.get("status") in {"uncertain","skipped"}:
                x["불확실"] += 1
        if consecutive_correct(q["id"]) >= 2:
            x["숙달"] += 1
    rows = list(agg.values())
    for x in rows:
        x["정답률(%)"] = round(
            100 * (x["풀이수"] - x["오답수"] - x["불확실"]) / x["풀이수"], 1
        ) if x["풀이수"] else 0.0
    return rows
