"""
GQ Dashboard Authentication
----------------------------
Simple email + password gate for the Streamlit dashboard.
Password is stored as a SHA-256 hash — never in plaintext.

To add a new user:
    1. Add their email to ALLOWED_USERS below
    2. Use the same hash (or generate a new one):
       python -c "import hashlib; print(hashlib.sha256('yourpassword'.encode()).hexdigest())"

To change the password:
    1. Generate a new hash (command above)
    2. Update _PWD_HASH below
"""

import hashlib
import streamlit as st

# ── Password hash (SHA-256 of the shared password) ───────────
# Never store the raw password here — only the hash.
_PWD_HASH = hashlib.sha256("grayquest@2026".encode()).hexdigest()

# ── Allowed users (email  →  password hash) ──────────────────
ALLOWED_USERS: dict[str, str] = {
    "aditya.kumar@grayquest.com": _PWD_HASH,
    "credit@grayquest.com":       _PWD_HASH,
}

# ── Login form styles ─────────────────────────────────────────
_LOGIN_CSS = """
<style>
[data-testid="stAppViewContainer"] { background: #f0f4f8; }
.login-box {
    max-width: 420px;
    margin: 80px auto 0 auto;
    background: #ffffff;
    border-radius: 16px;
    padding: 40px 36px 32px 36px;
    box-shadow: 0 4px 24px rgba(0,0,0,0.10);
    border-top: 5px solid #1f4e79;
}
.login-logo { font-size: 2.6rem; text-align: center; margin-bottom: 4px; }
.login-title {
    text-align: center;
    font-size: 1.55rem;
    font-weight: 700;
    color: #1f4e79;
    margin-bottom: 2px;
}
.login-sub {
    text-align: center;
    font-size: 0.88rem;
    color: #888;
    margin-bottom: 28px;
}
.login-footer {
    text-align: center;
    font-size: 0.78rem;
    color: #aaa;
    margin-top: 20px;
}
</style>
"""


def _check_credentials(email: str, password: str) -> bool:
    """Return True if email + password are valid."""
    email_clean = email.strip().lower()
    expected    = ALLOWED_USERS.get(email_clean)
    if not expected:
        return False
    return hashlib.sha256(password.encode()).hexdigest() == expected


def require_login() -> None:
    """
    Call this immediately after st.set_page_config() on every page.

    - If already authenticated  → returns immediately (page renders normally).
    - If not authenticated       → shows the login form and calls st.stop()
                                   so nothing else on the page is rendered.
    """
    if st.session_state.get("_gq_authenticated"):
        return  # ✅ logged in — let the page render

    # ── Show branded login form ───────────────────────────────
    st.markdown(_LOGIN_CSS, unsafe_allow_html=True)

    st.markdown('<div class="login-box">', unsafe_allow_html=True)
    st.markdown('<div class="login-logo">🔐</div>', unsafe_allow_html=True)
    st.markdown('<div class="login-title">GQ Intelligence Dashboard</div>', unsafe_allow_html=True)
    st.markdown('<div class="login-sub">GrayQuest Credit Team — Internal Tool</div>', unsafe_allow_html=True)

    with st.form("login_form", clear_on_submit=False):
        email    = st.text_input("Email", placeholder="you@grayquest.com")
        password = st.text_input("Password", type="password", placeholder="••••••••••••")
        submitted = st.form_submit_button("Login →", use_container_width=True, type="primary")

    if submitted:
        if _check_credentials(email, password):
            st.session_state["_gq_authenticated"] = True
            st.session_state["_gq_user_email"]    = email.strip().lower()
            st.rerun()
        else:
            if email.strip().lower() not in ALLOWED_USERS:
                st.error("❌ Email not recognised. Contact your admin to get access.")
            else:
                st.error("❌ Incorrect password. Please try again.")

    st.markdown('<div class="login-footer">Access restricted to authorised GrayQuest staff only.</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    st.stop()  # 🚫 block everything below this point until logged in


def show_logout_button() -> None:
    """
    Call inside `with st.sidebar:` on any page to show the logged-in user
    and a Logout button.
    """
    user = st.session_state.get("_gq_user_email", "")
    if user:
        st.markdown(f"👤 **{user}**")
    if st.button("🚪 Logout", use_container_width=True):
        st.session_state["_gq_authenticated"] = False
        st.session_state["_gq_user_email"]    = ""
        st.rerun()
