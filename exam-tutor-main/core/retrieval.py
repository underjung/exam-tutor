import re

STOP = {
    "다음","중","것은","대한","설명","옳은","고르시오","무엇","있는","한다","그리고",
    "에서","으로","하는","하여","관련","문제","정답","해설"
}

def tokenize(text):
    text = re.sub(r"[^0-9A-Za-z가-힣+\-]+", " ", (text or "").lower())
    return [x for x in text.split() if len(x) >= 2 and x not in STOP]

def split_blocks(content, size=1800, overlap=250):
    content = content or ""
    if not content:
        return []
    blocks = []
    start = 0
    while start < len(content):
        blocks.append(content[start:start+size])
        start += max(1, size-overlap)
    return blocks

def retrieve_summary_context(question_text, topic_title, summary_docs, top_k=3):
    query_tokens = set(tokenize((topic_title or "") + " " + (question_text or "")))
    scored = []
    for doc in summary_docs:
        for block in split_blocks(doc.get("content","")):
            bt = set(tokenize(block))
            score = len(query_tokens & bt)
            if topic_title and topic_title.lower() in block.lower():
                score += 4
            if score:
                scored.append((score, doc.get("filename",""), block))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:top_k]
