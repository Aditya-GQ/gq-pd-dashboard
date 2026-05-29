"""
GQ Intelligence Dashboard — Home Page
"""

import streamlit as st
import sys, os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config import APP_TITLE, APP_ICON, APP_VERSION
from backend.auth import require_login, show_logout_button

st.set_page_config(
    page_title=APP_TITLE, page_icon=APP_ICON,
    layout="wide", initial_sidebar_state="expanded",
)
require_login()

st.markdown("""
<style>
.card {
    background:#fff; border-radius:12px; padding:28px 24px;
    box-shadow:0 2px 12px rgba(0,0,0,0.08); border-left:5px solid #1f4e79;
    margin-bottom:16px;
}
.card h3 { margin:0 0 8px 0; color:#1f4e79; }
.card p  { margin:0; color:#555; font-size:0.95rem; }
.badge {
    display:inline-block; background:#e8f0fe; color:#1f4e79;
    border-radius:20px; padding:3px 12px; font-size:0.8rem;
    font-weight:600; margin-top:10px; margin-right:4px;
}
.home-title { font-size:2.2rem; font-weight:700; color:#1f4e79; margin-bottom:4px; }
.home-sub   { font-size:1.05rem; color:#666; margin-bottom:32px; }
</style>
""", unsafe_allow_html=True)

st.markdown(f'<div class="home-title">{APP_ICON} {APP_TITLE}</div>', unsafe_allow_html=True)
st.markdown('<div class="home-sub">AI-powered PD quality scoring & risk assessment for the Credit team</div>', unsafe_allow_html=True)
st.markdown(f"`{APP_VERSION}`")
st.divider()

col1, col2 = st.columns(2, gap="large")

with col1:
    st.markdown("""
    <div class="card">
        <h3>📋 PD Comment Analysis</h3>
        <p>Analyse Personal Discussion comments written by PD callers.
        Get AI-powered quality scores, risk flags, and improvement areas
        for each case — filtered by product type, group, location, or App ID.</p>
        <span class="badge">Quality Score</span>
        <span class="badge">Risk Flag</span>
        <span class="badge">Improvement Areas</span>
    </div>
    """, unsafe_allow_html=True)
    st.page_link("pages/1_PD_Comments.py", label="Open PD Comment Analysis →", icon="📋")

with col2:
    st.markdown("""
    <div class="card">
        <h3>🎙️ PD Recording Analysis</h3>
        <p>Transcribe PD call recordings via AI, then score the caller's quality,
        assess loan risk, and evaluate tone & communication professionalism —
        all automatically from the MP3 recording.</p>
        <span class="badge">Transcription</span>
        <span class="badge">Quality Score</span>
        <span class="badge">Tone Analysis</span>
    </div>
    """, unsafe_allow_html=True)
    st.page_link("pages/2_PD_Recordings.py", label="Open PD Recording Analysis →", icon="🎙️")

st.divider()

with st.expander("ℹ️ How scoring works"):
    st.markdown("""
### 🏆 Quality Score (out of 10)
Evaluates **the PD caller** — did they cover all required parameters during the discussion?

| Product | Parameters checked | CIBIL threshold | Overdue limit |
|---------|-------------------|-----------------|---------------|
| FSF     | 8 checks          | > 650           | < ₹30,000     |
| Non-FSF | 12 checks         | > 700           | < ₹15,000     |
| EdTech  | 11 checks         | > 700           | < ₹15,000     |

### 🚩 Risk Flag — Loan Approval Decision
Evaluates **the loan case** based on values found in the PD.

| Risk Level | Meaning |
|------------|---------|
| 🟢 LOW RISK | 0 negative flags — loan looks clean |
| 🟡 MEDIUM RISK | 1 negative flag — needs review |
| 🔴 HIGH RISK | 2+ flags — recommend decline / re-verify |

### 🎭 Tone Analysis (recordings only)
AI evaluates professionalism, empathy, structure, and completeness of the call.
    """)

with st.sidebar:
    st.markdown("### 🧭 Navigation")
    st.page_link("app.py",                  label="🏠 Home")
    st.page_link("pages/1_PD_Comments.py",  label="📋 PD Comment Analysis")
    st.page_link("pages/2_PD_Recordings.py",label="🎙️ PD Recording Analysis")
    st.divider()
    show_logout_button()
    st.caption(APP_VERSION)
