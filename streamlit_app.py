import json
import hmac
import re
import streamlit as st
import pandas as pd

from core.config import app_password, has_openai, has_supabase
from core.database import (
    init_db, list_topics, replace_topic_order, topic_id,
    add_document, list_documents, add_question, update_question, delete_question,
    list_questions, get_question, add_attempt, list_attempts,
    latest_attempt_map, consecutive_correct, stats, export_backup,
    upload_source_file, download_source_file, update_document_analysis, mark_document_status
)
from core.document_parser import parse_file, pages_to_text, is_image_pdf, chunks_from_pages
from core.basic_parser import extract_questions as basic_extract
from core.retrieval import retrieve_summary_context
from core.logic import deterministic_mc_grade, eligible, topic_performance
from core import ai

st.set_page_config(
    page_title="기초신경계 기출 튜터",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded"
)

init_db()

DEFAULT_TOPICS = [
    "시냅스","감각수용기","오름신경로","통증","척수반사",
    "시각자극의 감각과 전달","시각반사","청각의 감각과 전달","평형감각기관",
    "연합영역","미각과 후각","섭식조절기전","항상성 유지와 중추신경계","수면, 각성 및 뇌파",
    "뇌와 척수의 발생","뇌의 구조","뇌줄기","내림신경로","중추신경계 기형",
    "눈과 시각계통의 구조","귀와 청각계통의 구조","둘레계통과 언어영역",
    "Cellular Pathology of the CNS","Neurodegenerative Diseases","Pathology of CNS Neoplasm",
    "Peripheral Neuropathies","CNS infections",
    "Drugs for Epilepsy","Opioids","Drugs for Neurodegenerative Diseases",
    "Anxiolytic and Hypnotic Drugs","Drugs affecting the ANS",
    "Antipsychotic drugs","Antidepressants","Anesthetics","시각기관의 질환"
]

if not list_topics():
    replace_topic_order(DEFAULT_TOPICS)

st.markdown("""
<style>
:root { --card:#fff; --line:rgba(25,25,35,.10); --muted:#6F7482; }
.block-container { max-width: 1120px; padding-top: 1rem; padding-bottom: 4rem; }
[data-testid="stSidebar"] { border-right: 1px solid var(--line); }
.hero {
  background: linear-gradient(135deg, #ffffff 0%, #f0f1ff 100%);
  border: 1px solid var(--line); border-radius: 24px; padding: 28px 30px; margin-bottom: 20px;
}
.qcard {
  background:white; border:1px solid var(--line); border-radius:20px; padding:22px 24px;
  box-shadow:0 6px 28px rgba(20,20,60,.05); margin:10px 0 18px 0;
}
.meta { color:var(--muted); font-size:.9rem; margin-bottom:8px; }
.result-card { background:#fff; border:1px solid var(--line); border-radius:18px; padding:18px 20px; }
.small { color:var(--muted); font-size:.88rem; }
div[data-testid="stMetric"] {
  background:white; border:1px solid var(--line); padding:12px 14px; border-radius:16px;
}
.stButton>button { border-radius:12px; }
</style>
""", unsafe_allow_html=True)

def password_gate():
    pw = app_password()
    if not pw:
        return True
    if st.session_state.get("authenticated"):
        return True
    st.markdown("<div class='hero'><h2>🧠 기초신경계 기출 튜터</h2><p>개인 학습 사이트입니다.</p></div>", unsafe_allow_html=True)
    value = st.text_input("접속 비밀번호", type="password")
    if st.button("들어가기", type="primary"):
        if hmac.compare_digest(value, pw):
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("비밀번호가 맞지 않습니다.")
    st.stop()

password_gate()

if "current_qid" not in st.session_state:
    st.session_state.current_qid = None
if "result_qid" not in st.session_state:
    st.session_state.result_qid = None
if "last_result" not in st.session_state:
    st.session_state.last_result = None

st.sidebar.markdown("## 🧠 Neuro Tutor")
menu = st.sidebar.radio(
    "메뉴",
    ["대시보드","문제 풀기","오답 복습","자료 가져오기","문제 관리","백업/설정"]
)
st.sidebar.divider()
st.sidebar.caption("온라인 DB: " + ("✅ Supabase" if has_supabase() else "🖥️ 로컬 SQLite"))
st.sidebar.caption("AI 평가: " + ("✅ 연결됨" if has_openai() else "⚪ 미연결"))

def dashboard():
    st.markdown("""
    <div class="hero">
      <h1 style="margin:.1rem 0 .45rem">기초신경계 기출 튜터</h1>
      <div style="color:#606575">정리본 순서대로 문제를 풀고, 사고 과정을 기록하고, 틀린 문제만 반복합니다.</div>
    </div>
    """, unsafe_allow_html=True)
    s = stats()
    cols = st.columns(6)
    for c, (label, key) in zip(cols, [
        ("전체","total"),("미풀이","new"),("정답","correct"),("오답","wrong"),
        ("불확실","uncertain"),("숙달","mastered")
    ]):
        c.metric(label, s[key])

    st.subheader("단원별 학습 상태")
    rows = topic_performance()
    if rows:
        df = pd.DataFrame(rows)
        st.dataframe(
            df[["단원","문제수","풀이수","오답수","불확실","숙달","정답률(%)"]],
            use_container_width=True, hide_index=True
        )
    else:
        st.info("기출문제를 가져오면 단원별 현황이 나타납니다.")

    st.subheader("학습 규칙")
    st.write("정답을 제출하기 전에는 정답·해설이 표시되지 않습니다. **찍음**으로 맞힌 문제는 숙달 연속 정답에 포함하지 않고, 2회 연속 확실한 정답이면 숙달로 처리합니다.")

def nav_to_question(qid):
    st.session_state.current_qid = qid
    st.session_state.result_qid = None
    st.session_state.last_result = None

def solve_view(default_mode="전체", locked_ids=None):
    topics = list_topics()
    topic_map = {"전체 단원":None, **{t["title"]:t["id"] for t in topics}}

    c1,c2 = st.columns(2)
    modes = ["전체","미풀이","오답만","불확실만","오답 + 불확실","미숙달"]
    mode_index = modes.index(default_mode) if default_mode in modes else 0
    mode = c1.selectbox("학습 모드", modes, index=mode_index, disabled=locked_ids is not None)
    topic_name = c2.selectbox("단원", list(topic_map.keys()))

    qs = eligible(mode, topic_map[topic_name])
    if locked_ids is not None:
        allowed = set(locked_ids)
        qs = [q for q in qs if q["id"] in allowed]

    if not qs:
        st.success("이 조건에 해당하는 문제가 없습니다.")
        return

    ids = [q["id"] for q in qs]
    if st.session_state.current_qid not in ids:
        nav_to_question(ids[0])

    idx = ids.index(st.session_state.current_qid)
    q = get_question(st.session_state.current_qid)

    st.progress((idx+1)/len(ids), text=f"{idx+1} / {len(ids)}")
    src = q.get("source_file") or ""
    page = f" · p.{q['source_page']}" if q.get("source_page") else ""
    st.markdown(f"<div class='meta'>{q.get('topic_title') or '미분류'} · {src}{page}</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='qcard'><b>Q.</b>&nbsp; {q['question_text']}</div>", unsafe_allow_html=True)

    if q["question_type"] == "multiple_choice" and q.get("choices"):
        labels = [f"{i+1}. {x}" for i,x in enumerate(q["choices"])]
        selection = st.radio(
            "내 답", range(1,len(labels)+1),
            format_func=lambda x: labels[x-1], index=None, key=f"ans_{q['id']}"
        )
        answer = str(selection) if selection else ""
    else:
        answer = st.text_area("내 최종 답안", height=120, key=f"ans_text_{q['id']}")

    reasoning = st.text_area(
        "내 풀이 과정",
        placeholder="왜 이 답을 골랐는지, 어떤 개념을 떠올렸는지, 어떤 선지를 왜 제외했는지 적어보세요.",
        height=190, key=f"reason_{q['id']}"
    )
    confidence = st.segmented_control(
        "자신감", ["확실함","애매함","찍음"], default="애매함", key=f"conf_{q['id']}"
    )

    left,right = st.columns([3,1])
    submit = left.button("답안 제출", type="primary", use_container_width=True)
    skip = right.button("모르겠음", use_container_width=True)

    if skip:
        add_attempt(q["id"], "", reasoning, confidence, False, "skipped", "")
        st.session_state.result_qid = q["id"]
        st.session_state.last_result = {
            "is_correct":False, "status":"skipped",
            "feedback":"모르겠음으로 기록했습니다. 아래 해설을 확인한 뒤 다시 풀어보세요."
        }
        st.rerun()

    if submit:
        if not answer:
            st.warning("답을 입력하거나 선택해주세요.")
        else:
            summary_docs = list_documents("summary")
            context = retrieve_summary_context(
                q["question_text"], q.get("topic_title"), summary_docs, top_k=3
            )

            det = None
            if q["question_type"] == "multiple_choice" and q.get("choices"):
                det = deterministic_mc_grade(q, answer)

            if has_openai() and (reasoning.strip() or det is None or q["question_type"] != "multiple_choice"):
                result = ai.grade(q, answer, reasoning, confidence, context)
                # If the answer key gives an unambiguous MC result, preserve that grade.
                if det is not None:
                    result["is_correct"] = det
                    result["status"] = "correct" if det else "wrong"
            else:
                if det is True:
                    result = {"is_correct":True, "status":"correct", "feedback":"정답입니다. AI 연결 시 풀이 과정도 평가합니다."}
                elif det is False:
                    result = {"is_correct":False, "status":"wrong", "feedback":"오답입니다. 기존 해설을 확인하세요."}
                else:
                    result = {"is_correct":None, "status":"uncertain", "feedback":"자동 채점 근거가 부족합니다."}

            if result.get("is_correct") is True and confidence in {"애매함","찍음"}:
                result["status"] = "uncertain"

            add_attempt(
                q["id"], answer, reasoning, confidence,
                result.get("is_correct"), result.get("status","uncertain"), result.get("feedback","")
            )
            st.session_state.result_qid = q["id"]
            st.session_state.last_result = result
            st.rerun()

    if st.session_state.result_qid == q["id"] and st.session_state.last_result:
        result = st.session_state.last_result
        st.divider()
        status = result.get("status")
        if status == "correct":
            st.success("✅ 정답")
        elif status == "wrong":
            st.error("❌ 오답")
        elif status == "skipped":
            st.warning("⏭️ 모르겠음")
        else:
            st.warning("🟡 불확실 — 복습 대상으로 저장")

        st.markdown("<div class='result-card'>", unsafe_allow_html=True)
        st.markdown("#### 정답")
        st.write(q.get("correct_answer") or "자료에 정답이 명시되어 있지 않습니다.")
        if q.get("explanation"):
            st.markdown("#### 기출 기존 해설")
            st.write(q["explanation"])
        if result.get("feedback"):
            st.markdown("#### 내 풀이 피드백")
            st.markdown(result["feedback"])
        st.markdown("</div>", unsafe_allow_html=True)

        streak = consecutive_correct(q["id"])
        st.caption(f"연속 정답 {streak}회" + (" · ⭐ 숙달" if streak >= 2 else ""))

        p,n = st.columns(2)
        if p.button("← 이전 문제", disabled=idx==0, use_container_width=True):
            nav_to_question(ids[idx-1]); st.rerun()
        if n.button("다음 문제 →", disabled=idx==len(ids)-1, use_container_width=True):
            nav_to_question(ids[idx+1]); st.rerun()

def solve_page():
    st.title("문제 풀기")
    solve_view()

def wrong_review():
    st.title("오답 복습")
    latest = latest_attempt_map()
    wrong_ids = [qid for qid,a in latest.items() if a.get("status") in {"wrong","uncertain","skipped"}]
    if not wrong_ids:
        st.success("현재 복습할 오답/불확실 문제가 없습니다.")
        return
    s1,s2,s3 = st.columns(3)
    s1.metric("복습 대상",len(wrong_ids))
    s2.metric("오답",sum(1 for a in latest.values() if a.get("status")=="wrong"))
    s3.metric("불확실/모르겠음",sum(1 for a in latest.values() if a.get("status") in {"uncertain","skipped"}))
    solve_view(default_mode="오답 + 불확실", locked_ids=wrong_ids)

    st.divider()
    st.subheader("풀이 이력")
    qs = {q["id"]:q for q in list_questions()}
    rows = []
    for a in list_attempts():
        q = qs.get(a["question_id"])
        if q and q["id"] in wrong_ids:
            rows.append({
                "단원":q.get("topic_title") or "미분류",
                "문제":q["question_text"][:60],
                "시도":a["attempt_no"],
                "상태":a["status"],
                "자신감":a["confidence"],
                "답":a["answer"],
                "풀이":a["reasoning"][:100],
            })
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

def import_page():
    st.title("자료 가져오기")
    st.info("이제 파일을 먼저 **영구 저장**한 뒤, 별도로 분석합니다. 업로드 완료 후 페이지를 나가도 파일이 남아 있습니다.")

    if not has_supabase():
        st.error("영구 파일 업로드는 Supabase 연결이 필요합니다.")
        return

    st.subheader("1. 정리본 파일 영구 저장")
    summaries = st.file_uploader(
        "정리본 PDF / DOCX 여러 개", type=["pdf","docx","txt","md"],
        accept_multiple_files=True, key="summary_multi_up"
    )
    if summaries and st.button("정리본 파일 업로드", type="primary"):
        bar = st.progress(0, text="업로드 준비 중")
        for i, f in enumerate(summaries, 1):
            bar.progress((i-1)/len(summaries), text=f"업로드 중: {f.name}")
            upload_source_file("summary", f.name, f.getvalue())
            bar.progress(i/len(summaries), text=f"업로드 완료: {f.name}")
        st.success("정리본 원본을 Supabase에 영구 저장했습니다. 이제 페이지를 나가도 사라지지 않습니다.")
        st.rerun()

    stored_summaries = list_documents("summary")
    if stored_summaries:
        st.markdown("#### 저장된 정리본")
        for d in stored_summaries:
            size = d.get("size_bytes") or 0
            status = d.get("status") or ("analyzed" if d.get("content") else "uploaded")
            st.write(f"• {d['filename']} · {size/1024/1024:.1f} MB · {'✅ 분석 완료' if status == 'analyzed' else '☁️ 업로드 완료 / 분석 전'}")

        if st.button("저장된 정리본 전체 분석 → 통합 단원 순서 만들기"):
            outlines = []
            progress = st.progress(0, text="정리본 분석 준비 중")
            for i, d in enumerate(reversed(stored_summaries), 1):
                progress.progress((i-1)/len(stored_summaries), text=f"텍스트 추출 중: {d['filename']}")
                try:
                    if d.get("storage_path"):
                        raw = download_source_file(d)
                        pages = parse_file(d["filename"], raw)
                        text = pages_to_text(pages)
                    elif d.get("content"):
                        text = d["content"]
                    else:
                        raise RuntimeError("저장된 원본 또는 추출 텍스트가 없습니다.")
                    progress.progress((i-.5)/len(stored_summaries), text=f"단원 분석 중: {d['filename']}")
                    outline = ai.extract_outline(text) if has_openai() else []
                    update_document_analysis(d["id"], text, "analyzed")
                    for title in outline:
                        if title not in outlines:
                            outlines.append(title)
                except Exception as e:
                    mark_document_status(d["id"], "error")
                    st.error(f"{d['filename']} 분석 실패: {e}")
                progress.progress(i/len(stored_summaries), text=f"완료: {d['filename']}")
            if outlines:
                replace_topic_order(outlines)
                st.success(f"정리본 분석 완료: {len(outlines)}개 단원 순서를 적용했습니다.")
                st.rerun()
            else:
                st.warning("단원 순서를 만들지 못했습니다. OpenAI API 연결/잔액과 파일의 텍스트 추출 가능 여부를 확인해주세요.")
    else:
        st.caption("아직 영구 저장된 정리본이 없습니다.")

    with st.expander("현재 단원 순서"):
        st.write("\n".join(f"{x['position']}. {x['title']}" for x in list_topics()))

    st.divider()
    st.subheader("2. 기출/해설 파일 영구 저장")
    exams = st.file_uploader(
        "기출 PDF / DOCX 여러 개", type=["pdf","docx","txt","md"],
        accept_multiple_files=True, key="exam_multi_up"
    )
    if exams and st.button("기출/해설 파일 업로드", type="primary"):
        bar = st.progress(0, text="업로드 준비 중")
        for i, f in enumerate(exams, 1):
            bar.progress((i-1)/len(exams), text=f"업로드 중: {f.name}")
            upload_source_file("exam", f.name, f.getvalue())
            bar.progress(i/len(exams), text=f"업로드 완료: {f.name}")
        st.success("기출/해설 원본을 영구 저장했습니다.")
        st.rerun()

    stored_exams = list_documents("exam")
    pending = [d for d in stored_exams if (d.get("status") or ("analyzed" if d.get("content") else "uploaded")) != "analyzed"]
    if stored_exams:
        st.markdown("#### 저장된 기출/해설")
        for d in stored_exams:
            size = d.get("size_bytes") or 0
            status = d.get("status") or ("analyzed" if d.get("content") else "uploaded")
            st.write(f"• {d['filename']} · {size/1024/1024:.1f} MB · {'✅ 문제 추출 완료' if status == 'analyzed' else '☁️ 업로드 완료 / 분석 전'}")

        method = st.radio("추출 방식", ["AI 추출 — 권장", "기본 추출 — API 없이 테스트"], horizontal=True)
        if pending and st.button(f"분석 전 파일 {len(pending)}개에서 문제 추출", type="primary"):
            topics = [t["title"] for t in list_topics()]
            tmap = {t["title"]:t["id"] for t in list_topics()}
            total = 0
            bar = st.progress(0, text="문제 추출 준비 중")
            for fi, d in enumerate(reversed(pending), 1):
                try:
                    bar.progress((fi-1)/len(pending), text=f"텍스트 추출 중: {d['filename']}")
                    raw = download_source_file(d)
                    pages = parse_file(d["filename"], raw)
                    text = pages_to_text(pages)
                    bar.progress((fi-.5)/len(pending), text=f"문제 추출 중: {d['filename']}")
                    if method.startswith("AI") and has_openai():
                        if d["filename"].lower().endswith(".pdf") and is_image_pdf(pages):
                            questions = ai.extract_questions_from_image_pdf(raw, topics)
                        else:
                            questions = ai.extract_questions_from_text(chunks_from_pages(pages), topics)
                    else:
                        questions = basic_extract(pages)
                    for q in questions:
                        q["topic_id"] = tmap.get(q.get("topic", ""))
                        q["source_file"] = d["filename"]
                        q.setdefault("source_page", None); q.setdefault("year", ""); q.setdefault("professor", "")
                        q.setdefault("question_type", "multiple_choice"); q.setdefault("choices", [])
                        q.setdefault("correct_answer", ""); q.setdefault("explanation", "")
                        if q.get("question_text", "").strip():
                            add_question(q); total += 1
                    update_document_analysis(d["id"], text, "analyzed")
                except Exception as e:
                    mark_document_status(d["id"], "error")
                    st.error(f"{d['filename']} 처리 실패: {e}")
                bar.progress(fi/len(pending), text=f"완료: {d['filename']}")
            st.success(f"{total}개 문제를 저장했습니다. '문제 관리'에서 확인하세요.")
            st.rerun()
        elif not pending:
            st.success("저장된 기출/해설은 모두 문제 추출이 완료되었습니다.")
    else:
        st.caption("아직 영구 저장된 기출/해설이 없습니다.")

def question_admin():
    st.title("문제 관리")
    qs = list_questions()
    topics = list_topics()
    topic_opts = {"미분류":None, **{t["title"]:t["id"] for t in topics}}
    if not qs:
        st.info("기출을 먼저 가져와주세요.")
        return

    c1,c2 = st.columns([2,1])
    search = c1.text_input("검색")
    filt_topic = c2.selectbox("단원 필터", ["전체"] + list(topic_opts.keys()))
    filtered = qs
    if search:
        filtered = [q for q in filtered if search.lower() in q["question_text"].lower()]
    if filt_topic != "전체":
        target = topic_opts[filt_topic]
        filtered = [q for q in filtered if q.get("topic_id")==target]
    st.caption(f"{len(filtered)}문제")

    for q in filtered[:250]:
        label = f"#{q['id']} · {q.get('topic_title') or '미분류'} · {q['question_text'][:75]}"
        with st.expander(label):
            types = ["multiple_choice","short_answer","essay"]
            qtype = st.selectbox(
                "유형", types, index=types.index(q["question_type"]) if q["question_type"] in types else 0,
                key=f"qt_{q['id']}"
            )
            qtext = st.text_area("문제", q["question_text"], key=f"qq_{q['id']}")
            choices = st.text_area("선지 — 한 줄에 하나", "\n".join(q.get("choices",[])), key=f"qc_{q['id']}")
            ans = st.text_input("정답", q.get("correct_answer",""), key=f"qa_{q['id']}")
            exp = st.text_area("기존 해설", q.get("explanation",""), key=f"qe_{q['id']}")
            names = list(topic_opts.keys())
            current = q.get("topic_title") or "미분류"
            topic_name = st.selectbox("단원", names, index=names.index(current) if current in names else 0, key=f"qtp_{q['id']}")
            cc1,cc2 = st.columns(2)
            if cc1.button("수정 저장", key=f"save_{q['id']}"):
                update_question(q["id"],{
                    "source_file":q.get("source_file",""), "source_page":q.get("source_page"),
                    "year":q.get("year",""), "professor":q.get("professor",""),
                    "topic_id":topic_opts[topic_name], "question_type":qtype,
                    "question_text":qtext,
                    "choices":[x.strip() for x in choices.splitlines() if x.strip()],
                    "correct_answer":ans, "explanation":exp
                })
                st.success("저장했습니다.")
                st.rerun()
            if cc2.button("문제 삭제", key=f"delete_{q['id']}"):
                delete_question(q["id"])
                st.rerun()

def backup_settings():
    st.title("백업 / 설정")
    st.subheader("연결 상태")
    st.write("**데이터베이스:**", "Supabase — 여러 기기 동기화" if has_supabase() else "로컬 SQLite — 이 기기 테스트용")
    st.write("**AI:**", "OpenAI API 연결됨" if has_openai() else "미연결")

    st.subheader("JSON 백업")
    data = export_backup()
    raw = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    st.download_button(
        "전체 학습 데이터 백업 다운로드",
        raw, file_name="neuro_tutor_backup.json", mime="application/json"
    )

    st.subheader("업로드된 자료")
    docs = list_documents()
    if docs:
        st.dataframe(pd.DataFrame([
            {"종류":d["kind"],"파일":d["filename"],"저장일":d["created_at"]}
            for d in docs
        ]), use_container_width=True, hide_index=True)
    else:
        st.caption("아직 저장된 자료가 없습니다.")

    st.subheader("태블릿에서 앱처럼 쓰기")
    st.write("배포된 사이트를 태블릿 브라우저에서 연 뒤 **홈 화면에 추가**하면 아이콘으로 바로 실행할 수 있습니다.")

if menu == "대시보드":
    dashboard()
elif menu == "문제 풀기":
    solve_page()
elif menu == "오답 복습":
    wrong_review()
elif menu == "자료 가져오기":
    import_page()
elif menu == "문제 관리":
    question_admin()
elif menu == "백업/설정":
    backup_settings()
