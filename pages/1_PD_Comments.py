"""
Page 1 — PD Comment Analysis
Quality scoring + Risk scoring based on PD comments.
Filters: PD Comment Date + App ID + Product Type only.
"""

import streamlit as st
import pandas as pd
import sys, os
from datetime import date, timedelta

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.metabase_client import run_query
from backend.query_builder   import build_pd_query, build_system_data_query
from backend.llm_analyzer    import (
    score_pd_comment, batch_summary, ask_question, _fmt_pd_rows
)
from backend.auth import require_login, show_logout_button
import time

st.set_page_config(page_title="PD Comment Analysis", page_icon="📋", layout="wide")
require_login()

st.markdown("""
<style>
.section-title { font-size:1.3rem; font-weight:700; color:#1f4e79; margin:16px 0 8px 0; }
.info-pill {
    display:inline-block; background:#e8f0fe; color:#1f4e79;
    border-radius:20px; padding:3px 12px; font-size:0.82rem;
    font-weight:600; margin:2px;
}
</style>
""", unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────
st.markdown("# 📋 PD Comment Analysis")
st.caption("Quality scoring & risk assessment based on PD comment date")
st.divider()


# ── Sidebar Filters ───────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🔍 Filters — PD Comments")
    show_logout_button()
    st.divider()

    # ── Product Type ──
    product_type = st.selectbox(
        "Product Type",
        ["All", "FSF", "Non FSF", "EdTech"],
        help="Scoring criteria differ per product type"
    )

    st.divider()

    # ── Date Range (PD comment date) ──
    st.markdown("**PD Comment Date**")
    st.caption("Filters by when the PD comment was written")
    col1, col2 = st.columns(2)
    with col1:
        date_from = st.date_input("From", value=date.today())
    with col2:
        date_to   = st.date_input("To",   value=date.today())

    st.divider()

    # ── App ID (optional) ──
    raw_ids = st.text_area(
        "App ID(s)  *(optional)*",
        placeholder="e.g. 1764374, 1764340\nLeave blank for all apps in date range",
        help="Leave empty to fetch all PD comments in the date range"
    )

    st.divider()
    generate = st.button("🔍 Generate Summary", use_container_width=True, type="primary")


# ── On Generate ───────────────────────────────────────────────
if generate:
    st.session_state["pd_chat_history"] = []
    st.session_state["pd_data_context"] = ""

    # Build filters
    filters = {
        "date_from": str(date_from),
        "date_to":   str(date_to),
    }
    if product_type != "All":
        filters["product_type"] = product_type

    if raw_ids.strip():
        try:
            filters["app_ids"] = [int(x.strip()) for x in raw_ids.split(",") if x.strip()]
        except ValueError:
            st.error("App IDs must be numbers. Please check your input.")
            st.stop()

    # Fetch
    with st.spinner("Fetching PD comments from Metabase…"):
        sql  = build_pd_query(filters)
        rows = run_query(sql)

    if rows is None:
        st.stop()

    if not rows:
        st.warning("No PD comments found for the selected filters.")
        with st.expander("🔍 View generated SQL"):
            st.code(sql, language="sql")
        st.stop()

    rows_with_comment = [r for r in rows if r.get("credit_pd_comment")]

    # Summary metrics
    m1, m2, m3 = st.columns(3)
    m1.metric("Total Records",         len(rows))
    m2.metric("With PD Comments",      len(rows_with_comment))
    m3.metric("Without PD Comments",   len(rows) - len(rows_with_comment))

    # ── Fetch system profile data for conditional scoring ─────
    system_data_map = {}
    app_ids = [r.get("app_id") or r.get("id") for r in rows_with_comment if (r.get("app_id") or r.get("id"))]
    if app_ids:
        profile_sql = build_system_data_query(app_ids)
        try:
            with st.spinner("Loading system profile data (CIBIL, income, DPD)…"):
                profile_rows = run_query(profile_sql) or []
            system_data_map = {r["app_id"]: r for r in profile_rows if r.get("app_id")}
            if system_data_map:
                st.info(f"⚙️ **Context-aware scoring enabled** — CIBIL / Overdue / DPD checks are conditional for {len(system_data_map)} app(s).")
        except Exception as e:
            st.warning(f"⚠️ System profile data unavailable ({e}). All parameters scored normally.")

    with st.expander("🔍 View generated SQL"):
        st.code(sql, language="sql")

    # ── Raw data table ────────────────────────────────────────
    st.markdown('<div class="section-title">📄 PD Comments — Data Table</div>', unsafe_allow_html=True)

    df = pd.DataFrame(rows)
    # Truncate comment column for display
    if "credit_pd_comment" in df.columns:
        df["comment_preview"] = df["credit_pd_comment"].str[:250] + "…"
        display_df = df.drop(columns=["credit_pd_comment"])
    else:
        display_df = df

    st.dataframe(display_df, use_container_width=True)

    st.download_button(
        "⬇ Download Full Data as CSV",
        data=df.to_csv(index=False).encode("utf-8"),
        file_name="pd_comments.csv",
        mime="text/csv",
    )

    if not rows_with_comment:
        st.info("No PD comments found to score. Records found but comments are empty or too short.")
        st.stop()

    # ── AI Scoring — one case at a time (rich format) ────────
    st.divider()
    st.markdown('<div class="section-title">🤖 AI Quality & Risk Scoring</div>', unsafe_allow_html=True)

    individual_scores = []
    progress = st.progress(0, text="Starting…")

    for idx, row in enumerate(rows_with_comment):
        app_id  = row.get("app_id") or row.get("id", "N/A")
        caller  = row.get("pd_caller_name", "Unknown")
        product = row.get("product_type", "Non FSF")
        date_s  = str(row.get("pd_comment_date", ""))[:10]
        comment = (row.get("credit_pd_comment") or "").strip()

        progress.progress(
            (idx + 1) / len(rows_with_comment),
            text=f"Scoring App ID {app_id} ({idx+1}/{len(rows_with_comment)})…"
        )

        # Get system data for this app (may be None)
        sys_data = system_data_map.get(app_id) or system_data_map.get(str(app_id))

        with st.expander(
            f"📋 App ID: {app_id} | Caller: {caller} | {product} | {date_s}",
            expanded=(idx == 0)
        ):
            # Show system profile summary if available
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

            with st.expander("📝 View PD Comment"):
                st.markdown(comment or "_No comment_")

            sys_label = "context-aware" if sys_data else "standard"
            with st.spinner(f"Groq LLM: scoring quality, risk & documentation ({sys_label})…"):
                score_text = score_pd_comment(row, system_data=sys_data)

            if score_text.startswith("❌") or score_text.startswith("⚠️"):
                st.error(score_text) if score_text.startswith("❌") else st.warning(score_text)
            else:
                st.markdown(score_text)
                individual_scores.append(score_text)

        # Wait between calls to respect 6k TPM rate limit
        if idx < len(rows_with_comment) - 1:
            time.sleep(12)

    progress.empty()

    # ── Batch management summary ──────────────────────────────
    if len(individual_scores) > 1:
        st.divider()
        st.markdown('<div class="section-title">📊 Management Summary</div>', unsafe_allow_html=True)
        with st.spinner("Generating management summary…"):
            summary = batch_summary(individual_scores, mode="comment")
        st.markdown(summary)
        st.download_button(
            "⬇ Download Summary as Text",
            data=summary.encode("utf-8"),
            file_name="pd_comment_summary.txt",
            mime="text/plain",
        )

    # Store for chat
    st.session_state["pd_data_context"] = _fmt_pd_rows(rows_with_comment)
    st.session_state.setdefault("pd_chat_history", [])


# ── Empty state ───────────────────────────────────────────────
elif not st.session_state.get("pd_data_context"):
    st.info("👈 Set the date range and click **Generate Summary** to begin.")
    with st.expander("📖 How scoring works"):
        st.markdown("""
**Part 1 — Quality Scorecard (out of 10)**
Table showing each parameter — ✅ covered / ❌ missed — with specific findings and points.

**Part 2 — PD Documentation Audit (out of 5)**
Was the comment complete, clear, and structured? Compliance check.

**Part 3 — Risk Assessment**
| | |
|---|---|
| 🟢 LOW RISK   | 0 negative flags → APPROVE |
| 🟡 MEDIUM RISK | 1 negative flag → APPROVE WITH CONDITIONS |
| 🔴 HIGH RISK  | 2+ negative flags → DECLINE |

**Part 4 — Overall Summary + Recommendation**

**Scoring criteria by product type:**
| Product | Checks | CIBIL | Overdue |
|---------|--------|-------|---------|
| FSF     | 8      | >650  | <₹30k   |
| Non-FSF | 12     | >700  | <₹15k   |
| EdTech  | 11     | >700  | <₹15k   |
        """)


# ── Chat / Q&A ────────────────────────────────────────────────
if st.session_state.get("pd_data_context"):
    st.divider()
    st.markdown('<div class="section-title">💬 Ask a Question About This Data</div>', unsafe_allow_html=True)
    st.caption("Ask anything specific about the PD comments fetched above.")

    for msg in st.session_state.get("pd_chat_history", []):
        with st.chat_message(msg["role"], avatar="🧑" if msg["role"] == "user" else "🤖"):
            st.markdown(msg["content"])

    user_q = st.chat_input("e.g. 'Which app ID has the highest risk?' or 'Who covered CIBIL properly?'")
    if user_q:
        with st.chat_message("user", avatar="🧑"):
            st.markdown(user_q)
        with st.chat_message("assistant", avatar="🤖"):
            with st.spinner("Thinking…"):
                answer = ask_question(
                    question     = user_q,
                    data_context = st.session_state["pd_data_context"],
                    chat_history = st.session_state.get("pd_chat_history", []),
                    category     = "PD",
                )
            st.markdown(answer)
        st.session_state.setdefault("pd_chat_history", [])
        st.session_state["pd_chat_history"].append({"role": "user",      "content": user_q})
        st.session_state["pd_chat_history"].append({"role": "assistant",  "content": answer})

    if st.session_state.get("pd_chat_history"):
        if st.button("🗑 Clear Chat", key="clear_pd_chat"):
            st.session_state["pd_chat_history"] = []
            st.rerun()
