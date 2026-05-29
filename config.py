# =============================================================
# GQ Intelligence Dashboard — Configuration
# =============================================================
# Secrets (API keys, URLs) are read from:
#   Local dev  →  .env file  (loaded by python-dotenv)
#   Streamlit Cloud  →  App secrets set in the Streamlit dashboard
#
# Non-secret settings (model names, timeouts, IDs) stay here.
# =============================================================

import os

# Load .env file when running locally (no-op if file doesn't exist)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _secret(key: str, default: str = "") -> str:
    """
    Read a secret in order:
      1. Streamlit secrets  (st.secrets — Streamlit Community Cloud)
      2. OS environment variable  (.env → loaded above, or system env)
      3. default fallback
    """
    # Try Streamlit secrets first (works on Streamlit Cloud)
    try:
        import streamlit as st
        val = st.secrets.get(key)
        if val:
            return str(val)
    except Exception:
        pass
    # Fall back to environment variable (works locally with .env)
    return os.environ.get(key, default)


# ── Metabase ──────────────────────────────────────────────────
METABASE_URL         = _secret("METABASE_URL")
METABASE_API_KEY     = _secret("METABASE_API_KEY")
METABASE_DATABASE_ID = int(_secret("METABASE_DATABASE_ID", "2"))

# ── Groq API ─────────────────────────────────────────────────
GROQ_API_KEY  = _secret("GROQ_API_KEY")
GROQ_MODEL    = "llama-3.1-8b-instant"
GROQ_TIMEOUT  = 60

# ── Deepgram (transcription + speaker diarization) ───────────
DEEPGRAM_API_KEY  = _secret("DEEPGRAM_API_KEY")
DEEPGRAM_MODEL    = "nova-3"
DEEPGRAM_LANGUAGE = "multi"

# ── Sarvam AI (Hindi/Hinglish transcription) ─────────────────
SARVAM_API_KEY    = _secret("SARVAM_API_KEY")
SARVAM_MODEL      = "saaras:v3"
SARVAM_MODE       = "codemix"
SARVAM_LANG       = "unknown"
SARVAM_BATCH_DELAY = 3

# ── WhisperX (local transcription) ───────────────────────────
HF_TOKEN       = _secret("HF_TOKEN")
WHISPERX_MODEL  = "small"
WHISPERX_DEVICE = "cpu"

# ── Internal IAM Group IDs ────────────────────────────────────
PD_TEAM_IAM_GROUP_ID         = 17
COLLECTION_TEAM_IAM_GROUP_ID = 14

# ── App ───────────────────────────────────────────────────────
APP_TITLE   = "GQ Intelligence Dashboard"
APP_ICON    = "🎓"
APP_VERSION = "v1.0.0"

# ── LLM / comment settings ───────────────────────────────────
PD_COMMENT_MIN_LENGTH = 300
LLM_CHUNK_SIZE        = 4000
MAX_COMMENTS_PER_APP  = 10
