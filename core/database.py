import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

from .config import has_supabase, get_secret

LOCAL_DB = Path(__file__).resolve().parents[1] / "data" / "tutor.db"

def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def _supabase():
    from supabase import create_client
    return create_client(
        get_secret("SUPABASE_URL"),
        get_secret("SUPABASE_SECRET_KEY") or get_secret("SUPABASE_SERVICE_ROLE_KEY")
    )

def _local():
    LOCAL_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(LOCAL_DB, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    if has_supabase():
        return
    conn = _local()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS topics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL UNIQUE,
        position INTEGER NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL,
        filename TEXT NOT NULL,
        content TEXT DEFAULT '',
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_file TEXT,
        source_page INTEGER,
        year TEXT,
        professor TEXT,
        topic_id INTEGER,
        question_type TEXT DEFAULT 'multiple_choice',
        question_text TEXT NOT NULL,
        choices TEXT NOT NULL DEFAULT '[]',
        correct_answer TEXT DEFAULT '',
        explanation TEXT DEFAULT '',
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question_id INTEGER NOT NULL,
        answer TEXT DEFAULT '',
        reasoning TEXT DEFAULT '',
        confidence TEXT DEFAULT '애매함',
        is_correct INTEGER,
        status TEXT NOT NULL DEFAULT 'uncertain',
        ai_feedback TEXT DEFAULT '',
        attempt_no INTEGER NOT NULL,
        created_at TEXT NOT NULL
    );
    """)
    conn.commit()
    conn.close()

# ---------- topics ----------

def list_topics():
    if has_supabase():
        data = _supabase().table("topics").select("*").order("position").order("id").execute().data
        return data or []
    conn = _local()
    rows = conn.execute("SELECT * FROM topics ORDER BY position, id").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def replace_topic_order(titles):
    titles = [str(x).strip() for x in titles if str(x).strip()]
    # preserve existing IDs when possible so question relations do not break
    existing = {x["title"]: x["id"] for x in list_topics()}
    if has_supabase():
        sb = _supabase()
        for i, title in enumerate(titles, 1):
            if title in existing:
                sb.table("topics").update({"position": i}).eq("id", existing[title]).execute()
            else:
                sb.table("topics").insert({"title": title, "position": i}).execute()
        tail = len(titles) + 1
        for title, tid in existing.items():
            if title not in titles:
                sb.table("topics").update({"position": tail}).eq("id", tid).execute()
                tail += 1
        return
    conn = _local()
    for i, title in enumerate(titles, 1):
        row = conn.execute("SELECT id FROM topics WHERE title=?", (title,)).fetchone()
        if row:
            conn.execute("UPDATE topics SET position=? WHERE id=?", (i, row["id"]))
        else:
            conn.execute(
                "INSERT INTO topics(title,position,created_at) VALUES(?,?,?)",
                (title, i, _now())
            )
    tail = len(titles) + 1
    for row in conn.execute("SELECT id,title FROM topics").fetchall():
        if row["title"] not in titles:
            conn.execute("UPDATE topics SET position=? WHERE id=?", (tail, row["id"]))
            tail += 1
    conn.commit()
    conn.close()

def topic_id(title):
    if not title:
        return None
    for t in list_topics():
        if t["title"] == title:
            return t["id"]
    return None

# ---------- documents ----------

def add_document(kind, filename, content):
    payload = {"kind": kind, "filename": filename, "content": content or "", "created_at": _now()}
    if has_supabase():
        return _supabase().table("documents").insert(payload).execute().data
    conn = _local()
    cur = conn.execute(
        "INSERT INTO documents(kind,filename,content,created_at) VALUES(?,?,?,?)",
        (kind, filename, content or "", payload["created_at"])
    )
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return rid

def list_documents(kind=None):
    if has_supabase():
        q = _supabase().table("documents").select("*").order("created_at", desc=True)
        if kind:
            q = q.eq("kind", kind)
        return q.execute().data or []
    conn = _local()
    if kind:
        rows = conn.execute(
            "SELECT * FROM documents WHERE kind=? ORDER BY created_at DESC", (kind,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM documents ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------- persistent file storage (Supabase Storage) ----------

STORAGE_BUCKET = "study-files"

def upload_source_file(kind, filename, file_bytes):
    """Upload original source bytes to private Supabase Storage and register it."""
    if not has_supabase():
        raise RuntimeError("영구 파일 저장은 Supabase 연결이 필요합니다.")
    import hashlib
    digest = hashlib.sha256(file_bytes).hexdigest()[:16]
    safe = Path(filename).name.replace("/", "_")
    path = f"{kind}/{digest}_{safe}"
    sb = _supabase()
    try:
        sb.storage.from_(STORAGE_BUCKET).upload(
            path, file_bytes, {"upsert": "true"}
        )
    except Exception as e:
        # Existing object is fine; DB registration below is idempotent by storage_path.
        if "already exists" not in str(e).lower() and "duplicate" not in str(e).lower():
            raise
    existing = sb.table("documents").select("*").eq("storage_path", path).execute().data or []
    if existing:
        return existing[0]
    payload = {
        "kind": kind, "filename": filename, "content": "",
        "storage_path": path, "size_bytes": len(file_bytes),
        "status": "uploaded", "created_at": _now()
    }
    rows = sb.table("documents").insert(payload).execute().data or []
    return rows[0] if rows else payload

def download_source_file(doc):
    if not has_supabase():
        raise RuntimeError("Supabase 연결이 필요합니다.")
    path = doc.get("storage_path")
    if not path:
        raise RuntimeError("이 자료에는 저장된 원본 파일이 없습니다.")
    return _supabase().storage.from_(STORAGE_BUCKET).download(path)

def update_document_analysis(doc_id, content, status="analyzed"):
    payload = {"content": content or "", "status": status, "analyzed_at": _now()}
    if has_supabase():
        _supabase().table("documents").update(payload).eq("id", doc_id).execute()
        return
    conn = _local()
    conn.execute("UPDATE documents SET content=? WHERE id=?", (content or "", doc_id))
    conn.commit(); conn.close()

def mark_document_status(doc_id, status):
    if has_supabase():
        _supabase().table("documents").update({"status": status}).eq("id", doc_id).execute()

# ---------- questions ----------

def _normalize_question_row(row):
    d = dict(row)
    choices = d.get("choices", [])
    if isinstance(choices, str):
        try:
            choices = json.loads(choices)
        except Exception:
            choices = []
    d["choices"] = choices or []
    return d

def add_question(q):
    payload = {
        "source_file": q.get("source_file",""),
        "source_page": q.get("source_page"),
        "year": q.get("year",""),
        "professor": q.get("professor",""),
        "topic_id": q.get("topic_id"),
        "question_type": q.get("question_type","multiple_choice"),
        "question_text": q.get("question_text","").strip(),
        "choices": q.get("choices",[]) or [],
        "correct_answer": q.get("correct_answer","") or "",
        "explanation": q.get("explanation","") or "",
        "created_at": _now()
    }
    if has_supabase():
        return _supabase().table("questions").insert(payload).execute().data
    conn = _local()
    cur = conn.execute("""
        INSERT INTO questions(
          source_file,source_page,year,professor,topic_id,question_type,
          question_text,choices,correct_answer,explanation,created_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
    """, (
        payload["source_file"], payload["source_page"], payload["year"], payload["professor"],
        payload["topic_id"], payload["question_type"], payload["question_text"],
        json.dumps(payload["choices"], ensure_ascii=False),
        payload["correct_answer"], payload["explanation"], payload["created_at"]
    ))
    conn.commit()
    qid = cur.lastrowid
    conn.close()
    return qid

def update_question(qid, q):
    payload = {
        "source_file": q.get("source_file",""),
        "source_page": q.get("source_page"),
        "year": q.get("year",""),
        "professor": q.get("professor",""),
        "topic_id": q.get("topic_id"),
        "question_type": q.get("question_type","multiple_choice"),
        "question_text": q.get("question_text","").strip(),
        "choices": q.get("choices",[]) or [],
        "correct_answer": q.get("correct_answer","") or "",
        "explanation": q.get("explanation","") or "",
    }
    if has_supabase():
        _supabase().table("questions").update(payload).eq("id", qid).execute()
        return
    conn = _local()
    conn.execute("""
        UPDATE questions SET source_file=?,source_page=?,year=?,professor=?,topic_id=?,
        question_type=?,question_text=?,choices=?,correct_answer=?,explanation=? WHERE id=?
    """, (
        payload["source_file"], payload["source_page"], payload["year"], payload["professor"],
        payload["topic_id"], payload["question_type"], payload["question_text"],
        json.dumps(payload["choices"], ensure_ascii=False), payload["correct_answer"],
        payload["explanation"], qid
    ))
    conn.commit()
    conn.close()

def delete_question(qid):
    if has_supabase():
        _supabase().table("questions").delete().eq("id", qid).execute()
        return
    conn = _local()
    conn.execute("DELETE FROM attempts WHERE question_id=?", (qid,))
    conn.execute("DELETE FROM questions WHERE id=?", (qid,))
    conn.commit()
    conn.close()

def list_questions(topic_id_filter=None):
    topics = {t["id"]: t for t in list_topics()}
    if has_supabase():
        q = _supabase().table("questions").select("*")
        if topic_id_filter is not None:
            q = q.eq("topic_id", topic_id_filter)
        data = q.order("id").execute().data or []
    else:
        conn = _local()
        if topic_id_filter is None:
            rows = conn.execute("SELECT * FROM questions ORDER BY id").fetchall()
        else:
            rows = conn.execute("SELECT * FROM questions WHERE topic_id=? ORDER BY id", (topic_id_filter,)).fetchall()
        conn.close()
        data = [dict(r) for r in rows]
    out = []
    for row in data:
        d = _normalize_question_row(row)
        t = topics.get(d.get("topic_id"))
        d["topic_title"] = t["title"] if t else None
        d["topic_position"] = t["position"] if t else 999999
        out.append(d)
    out.sort(key=lambda x: (x.get("topic_position",999999), str(x.get("year","")), str(x.get("source_file","")), x.get("source_page") or 999999, x["id"]))
    return out

def get_question(qid):
    for q in list_questions():
        if int(q["id"]) == int(qid):
            return q
    return None

# ---------- attempts ----------

def add_attempt(question_id, answer, reasoning, confidence, is_correct, status, ai_feedback=""):
    old = list_attempts(question_id)
    payload = {
        "question_id": question_id,
        "answer": answer or "",
        "reasoning": reasoning or "",
        "confidence": confidence or "애매함",
        "is_correct": is_correct,
        "status": status,
        "ai_feedback": ai_feedback or "",
        "attempt_no": len(old) + 1,
        "created_at": _now()
    }
    if has_supabase():
        return _supabase().table("attempts").insert(payload).execute().data
    conn = _local()
    conn.execute("""
        INSERT INTO attempts(question_id,answer,reasoning,confidence,is_correct,status,ai_feedback,attempt_no,created_at)
        VALUES(?,?,?,?,?,?,?,?,?)
    """, (
        payload["question_id"], payload["answer"], payload["reasoning"], payload["confidence"],
        None if is_correct is None else int(bool(is_correct)), payload["status"],
        payload["ai_feedback"], payload["attempt_no"], payload["created_at"]
    ))
    conn.commit()
    conn.close()

def list_attempts(question_id=None):
    if has_supabase():
        q = _supabase().table("attempts").select("*")
        if question_id is not None:
            q = q.eq("question_id", question_id)
        return q.order("question_id").order("attempt_no").execute().data or []
    conn = _local()
    if question_id is None:
        rows = conn.execute("SELECT * FROM attempts ORDER BY question_id,attempt_no").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM attempts WHERE question_id=? ORDER BY attempt_no", (question_id,)
        ).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        if d["is_correct"] is not None:
            d["is_correct"] = bool(d["is_correct"])
        out.append(d)
    return out

def latest_attempt_map():
    latest = {}
    for a in list_attempts():
        qid = a["question_id"]
        if qid not in latest or a["attempt_no"] > latest[qid]["attempt_no"]:
            latest[qid] = a
    return latest

def consecutive_correct(question_id):
    arr = list_attempts(question_id)
    n = 0
    for a in reversed(arr):
        if a.get("is_correct") is True and a.get("confidence") != "찍음":
            n += 1
        else:
            break
    return n

def stats():
    qs = list_questions()
    latest = latest_attempt_map()
    s = dict(total=len(qs), new=0, correct=0, wrong=0, uncertain=0, skipped=0, mastered=0)
    for q in qs:
        a = latest.get(q["id"])
        if not a:
            s["new"] += 1
        else:
            status = a.get("status","uncertain")
            if status in s:
                s[status] += 1
        if consecutive_correct(q["id"]) >= 2:
            s["mastered"] += 1
    return s

def export_backup():
    return {
        "topics": list_topics(),
        "documents": list_documents(),
        "questions": list_questions(),
        "attempts": list_attempts()
    }
