"""
Page 2 — PD Recording Analysis
Transcribe MP3 recordings via Groq Whisper, then apply
quality scoring, risk scoring, and tone analysis.
"""

import streamlit as st
import pandas as pd
import sys, os
from datetime import date, timedelta

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.metabase_client import run_query
from backend.query_builder   import get_lookup_query, build_recording_query, build_comment_for_app_query
from backend.llm_analyzer    import (
    transcribe_audio_deepgram, score_recording_transcript,
    compare_comment_to_transcript,
    batch_summary, ask_question, ensure_english_or_hindi_transcript,
)
from backend.auth import require_login, show_logout_button
import time

st.set_page_config(page_title="PD Recording Analysis", page_icon="🎙️", layout="wide")
require_login()

st.markdown("""
<style>
.section-title { font-size:1.3rem; font-weight:700; color:#1f4e79; margin:16px 0 8px 0; }
.rec-card {
    background:#fff; border-radius:10px; padding:16px 20px;
    box-shadow:0 2px 8px rgba(0,0,0,0.07); margin-bottom:12px;
    border-left: 4px solid #1f4e79;
}
.badge {
    display:inline-block; border-radius:10px; padding:2px 10px;
    font-size:0.78rem; font-weight:600; margin:2px;
}
.badge-fsf  { background:#dbeafe; color:#1e40af; }
.badge-nfsf { background:#fef9c3; color:#92400e; }
.badge-edt  { background:#dcfce7; color:#166534; }
</style>
""", unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────
st.markdown("# 🎙️ PD Recording Analysis")
st.caption("Transcribe PD call recordings → Quality scoring + Risk assessment + Tone analysis")
st.divider()


# ── Load lookup ───────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner="Loading groups…")
def load_lookup():
    rows = run_query(get_lookup_query())
    return rows or []

lookup = load_lookup()
groups = sorted({r["group_name"] for r in lookup if r.get("group_name")})


# ── Sidebar Filters ───────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🔍 Filters — PD Recordings")
    show_logout_button()
    st.divider()

    product_type = st.selectbox(
        "Product Type",
        ["All", "FSF", "Non FSF", "EdTech"],
    )

    st.divider()

    filter_mode = st.radio("Filter by", ["By Date", "By App ID"])

    if filter_mode == "By Date":
        col1, col2 = st.columns(2)
        with col1:
            date_from = st.date_input("From Date", value=date.today())
        with col2:
            date_to   = st.date_input("To Date",   value=date.today())
        raw_ids = ""
    else:
        raw_ids   = st.text_area("App ID(s)", placeholder="e.g. 1764374, 1764340")
        col1, col2 = st.columns(2)
        with col1:
            date_from = st.date_input("From Date", value=date.today() - timedelta(days=7))
        with col2:
            date_to   = st.date_input("To Date",   value=date.today())

    st.divider()
    fetch_btn = st.button("📋 Fetch Recordings", use_container_width=True, type="secondary")
    st.caption("Step 1: Fetch the list of recordings")

    st.divider()
    analyze_btn = st.button("🤖 Transcribe & Score All", use_container_width=True, type="primary")
    st.caption("Step 2: Deepgram Nova-3 (diarize) → Groq Quality + Risk + Tone scoring")

    n_fetched = len(st.session_state.get("rec_rows", []))
    if n_fetched > 0:
        eta_rough = round(n_fetched * 65 / 60)
        if n_fetched <= 10:
            st.caption(f"ℹ️ {n_fetched} recording(s) — ~{eta_rough} min estimated")
        elif n_fetched <= 50:
            st.warning(f"⚠️ {n_fetched} recordings — ~{eta_rough} min. Paced at 6k TPM limit.")
        else:
            st.warning(f"⚠️ {n_fetched} recordings — ~{eta_rough} min. Keep this tab open.")


# ── STEP 1 — Fetch recordings list ───────────────────────────
if fetch_btn:
    st.session_state["rec_rows"]        = []
    st.session_state["rec_chat_history"] = []
    st.session_state["rec_data_context"] = ""
    st.session_state["rec_system_data"]  = {}   # app_id → profile dict

    filters = {}
    if product_type != "All":
        filters["product_type"] = product_type

    filters["date_from"] = str(date_from)
    filters["date_to"]   = str(date_to)

    if raw_ids.strip():
        try:
            filters["app_ids"] = [int(x.strip()) for x in raw_ids.split(",") if x.strip()]
        except ValueError:
            st.error("App IDs must be numbers.")
            st.stop()

    with st.spinner("Fetching recordings from Metabase…"):
        sql  = build_recording_query(filters)
        rows = run_query(sql)

    if rows is None:
        st.stop()

    if not rows:
        st.warning("No answered recordings found for the selected filters.")
        with st.expander("🔍 View SQL"):
            st.code(sql, language="sql")
        st.stop()

    st.session_state["rec_rows"] = rows
    st.session_state["rec_sql"]  = sql

    # ── System profile data is now merged into recording query ──
    # Build map directly from rows — each row already has cibil_score,
    # overdue_amount, gq_dpd_days, monthly_income, work_status, system_address, foir
    system_data_map = {r["app_id"]: r for r in rows if r.get("app_id")}
    st.session_state["rec_system_data"] = system_data_map
    apps_with_data = sum(1 for r in rows if r.get("cibil_score") is not None)
    if apps_with_data:
        st.success(f"✅ System profile data available for {apps_with_data}/{len(rows)} app(s) — context-aware scoring enabled.")
    else:
        st.info("ℹ️ No system profile data found (CAM report may be missing). Standard scoring will be used.")

    # ── Pre-fetch panel comments for consistency check (Step 2) ──
    all_app_ids = [r["app_id"] for r in rows if r.get("app_id")]
    st.session_state["rec_comment_map"] = {}
    if all_app_ids:
        try:
            comment_sql = build_comment_for_app_query(all_app_ids)
            with st.spinner("Fetching panel comments for consistency check…"):
                comment_rows = run_query(comment_sql) or []
            comment_map = {
                r["app_id"]: {
                    "comment":      r.get("credit_pd_comment", ""),
                    "comment_date": str(r.get("pd_comment_date", ""))[:10],
                    "caller_name":  r.get("pd_caller_name", ""),
                }
                for r in comment_rows if r.get("app_id")
            }
            st.session_state["rec_comment_map"] = comment_map
            if comment_map:
                st.info(f"📋 Panel comments found for **{len(comment_map)}/{len(all_app_ids)}** app(s) — consistency check will run after scoring.")
            else:
                st.info("📋 No panel comments found for these app(s) — consistency check will be skipped.")
        except Exception as e:
            st.warning(f"⚠️ Could not fetch panel comments ({e}). Consistency check will be skipped.")


# ── Show recordings table ─────────────────────────────────────
rows = st.session_state.get("rec_rows", [])

if rows:
    st.success(f"✅ {len(rows)} answered recording(s) found")

    with st.expander("🔍 View SQL"):
        st.code(st.session_state.get("rec_sql", ""), language="sql")

    st.markdown('<div class="section-title">📄 Recordings List</div>', unsafe_allow_html=True)

    display_rows = []
    for r in rows:
        dur_sec  = r.get("call_duration_seconds", 0) or 0
        duration = f"{dur_sec // 60}m {dur_sec % 60}s"
        cibil_raw = r.get("cibil_score")
        cibil_disp = (
            "-1 (no history)" if cibil_raw is not None and int(float(cibil_raw)) == -1
            else str(int(float(cibil_raw))) if cibil_raw is not None
            else "—"
        )
        display_rows.append({
            "App ID":              r.get("app_id"),
            "Caller":              r.get("caller"),
            "Product":             r.get("product_type"),
            "Student Type":        r.get("student_type") or "—",
            "Gender":              r.get("gender") or "—",
            "Called On":           r.get("called_on"),
            "Duration":            duration,
            "CIBIL":               cibil_disp,
            "Overdue (Rs.)":       int(float(r["overdue_amount"])) if r.get("overdue_amount") is not None else "—",
            "GQ DPD (days)":       int(float(r["gq_dpd_days"])) if r.get("gq_dpd_days") is not None else "—",
            "Income/mo (Rs.)":     int(float(r["monthly_income"])) if r.get("monthly_income") is not None else "—",
            "Total Obligations":   int(float(r["total_obligations"])) if r.get("total_obligations") is not None else "—",
            "FOIR (%)":            r.get("foir") or "—",
            "Work Status":         r.get("work_status") or "—",
            "System Address":      r.get("system_address") or "—",
            "Recording URL":       r.get("recording_url", ""),
        })

    df = pd.DataFrame(display_rows)
    st.dataframe(df, use_container_width=True)

    st.download_button(
        "⬇ Download List as CSV",
        data=df.to_csv(index=False).encode("utf-8"),
        file_name="pd_recordings_list.csv",
        mime="text/csv",
    )

    st.info("👆 Click **Transcribe & Score All** in the sidebar to start AI analysis.")


# ── STEP 2 — Transcribe + Score ───────────────────────────────
if analyze_btn:
    rows = st.session_state.get("rec_rows", [])
    if not rows:
        st.warning("Please fetch recordings first (Step 1).")
        st.stop()

    system_data_map = st.session_state.get("rec_system_data", {})

    st.divider()
    st.markdown('<div class="section-title">🤖 AI Transcription & Scoring</div>', unsafe_allow_html=True)

    if system_data_map:
        st.info(f"⚙️ **Context-aware scoring enabled** — CIBIL / Overdue / DPD checks are conditional based on system data for {len(system_data_map)} app(s).")
    else:
        st.warning("⚠️ No system profile data available — all parameters will be scored normally (non-conditional).")

    individual_scores = []
    all_transcripts   = {}

    # ── Rate-limit constants (Groq free tier: 6000 TPM) ──────────
    # scoring uses ~3200 tokens → needs 32s to recover
    # consistency uses ~2000 tokens → needs 20s to recover
    # We use slightly padded values for safety.
    SLEEP_AFTER_SCORE       = 35   # seconds after scoring call (before consistency)
    SLEEP_AFTER_CONSISTENCY = 30   # seconds after consistency call (before next recording)
    SLEEP_NO_CONSISTENCY    = 40   # seconds between recordings when no consistency call runs

    n_total = len(rows)
    comment_map_check = st.session_state.get("rec_comment_map", {})
    n_with_comment = sum(
        1 for r in rows
        if comment_map_check.get(r.get("app_id")) or comment_map_check.get(str(r.get("app_id", "")))
    )
    # ETA: each recording with comment ~71s, without ~50s
    eta_sec = n_with_comment * 71 + (n_total - n_with_comment) * 50
    eta_min = round(eta_sec / 60)
    st.info(
        f"⏱️ **Estimated time:** ~{eta_min} min for {n_total} recording(s) "
        f"({n_with_comment} with panel comment). Groq 6k TPM pacing applied automatically."
    )

    progress = st.progress(0, text="Starting…")

    for idx, row in enumerate(rows):
        app_id  = row.get("app_id", "N/A")
        caller  = row.get("caller", "Unknown")
        product = row.get("product_type", "Non FSF")
        url     = row.get("recording_url", "")
        dur_sec = row.get("call_duration_seconds", 0) or 0
        duration = f"{dur_sec // 60}m {dur_sec % 60}s"

        # Get system data for this specific app_id (may be None)
        sys_data = system_data_map.get(app_id) or system_data_map.get(str(app_id))

        remaining = n_total - idx
        remaining_sec = remaining * (71 if (comment_map_check.get(app_id) or comment_map_check.get(str(app_id))) else 50)
        remaining_min = max(0, round(remaining_sec / 60))
        progress.progress(
            (idx + 1) / n_total,
            text=f"App ID {app_id} ({idx+1}/{n_total}) — ~{remaining_min} min remaining"
        )

        with st.expander(
            f"🎙️ App ID: {app_id} | Caller: {caller} | {product} | Duration: {duration}",
            expanded=(idx == 0)
        ):
            if not url:
                st.warning("No recording URL available for this entry.")
                continue

            # ── Show system profile data panel ────────────────
            if sys_data:
                cibil_raw  = sys_data.get("cibil_score")
                cibil_disp = (
                    "-1 (no history)" if cibil_raw is not None and int(float(cibil_raw)) == -1
                    else str(int(float(cibil_raw))) if cibil_raw is not None
                    else "N/A"
                )
                st.markdown(
                    f"⚙️ **System Profile** | "
                    f"CIBIL: **{cibil_disp}** | "
                    f"Overdue: **₹{int(float(sys_data.get('overdue_amount') or 0)):,}** | "
                    f"GQ DPD: **{int(float(sys_data.get('gq_dpd_days') or 0))}d** | "
                    f"Income: ₹{int(float(sys_data.get('monthly_income') or 0)):,}/mo | "
                    f"FOIR: {sys_data.get('foir') or 'N/A'}% | "
                    f"Work: {sys_data.get('work_status') or '—'} | "
                    f"Gender: {sys_data.get('gender') or '—'}"
                )

            # ── Step 1: Deepgram Nova-3 — transcription + speaker diarization ──
            st.markdown("**Step 1 — Transcribing via Deepgram Nova-3 (multi-language + speaker labels)…**")
            with st.spinner("Deepgram: transcribing & identifying Caller / Customer from audio…"):
                transcript = transcribe_audio_deepgram(url)

            if transcript.startswith("❌"):
                st.error(transcript)
                if idx < len(rows) - 1:
                    time.sleep(5)
                continue

            # ── Language detection + translation ─────────────────
            # Detects Marathi, Tamil, Telugu, Kannada, Bengali etc. → auto-translates to English
            with st.spinner("Checking language…"):
                transcript, detected_lang = ensure_english_or_hindi_transcript(transcript)
            if detected_lang != "Hindi / English":
                st.info(f"🌐 Original language: **{detected_lang}** — translated to English for scoring")

            # Show full [Caller]/[Customer] transcript — labelled directly from audio
            with st.expander(f"📝 View Transcript ([Caller] / [Customer]) — {detected_lang}"):
                st.markdown(transcript)

            all_transcripts[app_id] = transcript

            # ── Step 2: Groq LLM — Quality + Risk + Tone scoring (context-aware) ──
            sys_label = "context-aware" if sys_data else "standard"
            st.markdown(f"**Step 2 — AI Scoring (Quality + Risk + Tone) — {sys_label} mode…**")
            with st.spinner("Groq LLM: scoring quality, risk & tone…"):
                score_text = score_recording_transcript(row, transcript, system_data=sys_data)

            if score_text.startswith("❌"):
                st.error(score_text)
                # Still sleep so the next recording doesn't hit the same limit
                if idx < n_total - 1:
                    with st.spinner(f"⏳ TPM cooldown {SLEEP_NO_CONSISTENCY}s before next recording…"):
                        time.sleep(SLEEP_NO_CONSISTENCY)
                continue

            st.markdown(score_text)
            individual_scores.append(score_text)

            # ── Step 3: Comment vs Call Consistency Check ─────────
            comment_map  = st.session_state.get("rec_comment_map", {})
            comment_info = comment_map.get(app_id) or comment_map.get(str(app_id))

            st.markdown("**Step 3 — Comment vs Call Consistency Check**")
            with st.expander("📋 Part 5 — Call vs Panel Comment Consistency", expanded=False):
                if not comment_info or not comment_info.get("comment"):
                    st.info(
                        f"📝 No panel comment found for App ID **{app_id}** — "
                        "consistency check skipped. (Comment may not have been written yet, "
                        "or the caller belongs to a different team group.)"
                    )
                else:
                    panel_comment  = comment_info["comment"]
                    comment_date   = comment_info.get("comment_date", "")
                    comment_caller = comment_info.get("caller_name", "")

                    # Show the panel comment text
                    with st.expander(
                        f"📄 View Panel Comment — {comment_caller} | {comment_date}",
                        expanded=False
                    ):
                        st.markdown(panel_comment)

                    # TPM recovery before second Groq call (scoring used ~3200 tokens)
                    with st.spinner(f"⏳ TPM recovery {SLEEP_AFTER_SCORE}s before consistency check…"):
                        time.sleep(SLEEP_AFTER_SCORE)

                    with st.spinner("Groq LLM: comparing call transcript to panel comment…"):
                        consistency_text = compare_comment_to_transcript(
                            transcript   = transcript,
                            comment      = panel_comment,
                            product_type = product,
                        )

                    if consistency_text.startswith("❌"):
                        st.error(consistency_text)
                    else:
                        st.markdown(consistency_text)

            # ── TPM cooldown before next recording ────────────────
            if idx < n_total - 1:
                has_comment = bool(comment_info and comment_info.get("comment"))
                sleep_sec   = SLEEP_AFTER_CONSISTENCY if has_comment else SLEEP_NO_CONSISTENCY
                with st.spinner(f"⏳ TPM cooldown {sleep_sec}s before next recording…"):
                    time.sleep(sleep_sec)

    progress.empty()

    # ── Batch summary ─────────────────────────────────────────
    if len(individual_scores) > 1:
        st.divider()
        st.markdown('<div class="section-title">📊 Management Summary (All Recordings)</div>', unsafe_allow_html=True)
        with st.spinner("Generating batch summary…"):
            summary = batch_summary(individual_scores, mode="recording")
        st.markdown(summary)

        st.download_button(
            "⬇ Download Summary as Text",
            data=summary.encode("utf-8"),
            file_name="pd_recording_summary.txt",
            mime="text/plain",
        )

    # Store context for chat
    ctx_lines = []
    for app_id, tr in all_transcripts.items():
        ctx_lines.append(f"App ID {app_id} Transcript:\n{tr}\n{'─'*60}")
    st.session_state["rec_data_context"]  = "\n".join(ctx_lines)
    st.session_state["rec_chat_history"]  = []


# ── Info when nothing loaded ──────────────────────────────────
elif not rows:
    st.info("👈 Use the filters in the sidebar → **Fetch Recordings** → then **Transcribe & Score All**.")
    with st.expander("📖 How this page works"):
        st.markdown("""
**Step 1 — Fetch Recordings**
Pulls all answered PD call recordings for the selected date and product type.

**Step 2 — Transcribe & Score All**
For each recording:
1. **Sarvam AI** (saaras:v3 codemix) transcribes the MP3 — optimised for Hindi/Hinglish PD calls
2. **Groq LLM** formats into **[Caller] / [Customer]** dialogue from word timestamps
3. **Groq LLM** scores the clean transcript:
   - 🏆 **Quality Score** (out of 10) — did the caller cover all parameters?
   - 🚩 **Risk Score** — are negative indicators present?
   - 🎭 **Tone & Professionalism** — 6-point QA audit

**Batch delay applied between recordings to stay within Sarvam + Groq rate limits.**
**Scoring criteria differ by product type (FSF / Non-FSF / EdTech)**
        """)


# ── Chat / Q&A ────────────────────────────────────────────────
if st.session_state.get("rec_data_context"):
    st.divider()
    st.markdown('<div class="section-title">💬 Ask a Question About These Recordings</div>', unsafe_allow_html=True)
    st.caption("Ask anything about the transcripts or scoring results.")

    for msg in st.session_state.get("rec_chat_history", []):
        with st.chat_message(msg["role"], avatar="🧑" if msg["role"] == "user" else "🤖"):
            st.markdown(msg["content"])

    user_q = st.chat_input("Ask about the recordings… e.g. 'Which caller had the best tone?'")
    if user_q:
        with st.chat_message("user", avatar="🧑"):
            st.markdown(user_q)
        with st.chat_message("assistant", avatar="🤖"):
            with st.spinner("Thinking…"):
                answer = ask_question(
                    question     = user_q,
                    data_context = st.session_state["rec_data_context"],
                    chat_history = st.session_state.get("rec_chat_history", []),
                    category     = "PD",
                )
            st.markdown(answer)
        st.session_state.setdefault("rec_chat_history", [])
        st.session_state["rec_chat_history"].append({"role": "user",      "content": user_q})
        st.session_state["rec_chat_history"].append({"role": "assistant",  "content": answer})

    if st.session_state.get("rec_chat_history"):
        if st.button("🗑 Clear Chat", key="clear_rec_chat"):
            st.session_state["rec_chat_history"] = []
            st.rerun()
