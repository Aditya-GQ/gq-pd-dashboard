"""
Groq LLM Analyzer + Whisper Transcription
-------------------------------------------
- Quality scoring (how well the PD caller covered all parameters)
- Risk scoring   (are negative indicators present in the case)
- Tone analysis  (for recordings only)
- Whisper MP3 transcription via Groq
- Follow-up Q&A chat
"""

import requests
import time
import sys, os
from collections import defaultdict

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    GROQ_API_KEY, GROQ_MODEL, GROQ_TIMEOUT, LLM_CHUNK_SIZE, MAX_COMMENTS_PER_APP,
    HF_TOKEN, WHISPERX_MODEL, WHISPERX_DEVICE,
    SARVAM_API_KEY, SARVAM_MODEL, SARVAM_MODE, SARVAM_LANG, SARVAM_BATCH_DELAY,
    DEEPGRAM_API_KEY, DEEPGRAM_MODEL, DEEPGRAM_LANGUAGE,
)
from backend.scoring_criteria import (
    build_criteria_text, build_risk_factors_text, get_points_each, get_criteria,
    get_conditional_notes, build_risk_scoring_table,
    get_banking_param_count, get_quality_pts_without_banking,
    build_quality_table_template,
    TONE_MARKS, QUALITY_MARKS,
)

GROQ_CHAT_ENDPOINT  = "https://api.groq.com/openai/v1/chat/completions"
GROQ_AUDIO_ENDPOINT = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_WHISPER_MODEL  = "whisper-large-v3"


# ──────────────────────────────────────────────────────────────
# CORE LLM CALL
# ──────────────────────────────────────────────────────────────

def call_llm(user_prompt: str, system_prompt: str, max_tokens: int = 2048,
             _retry: int = 0) -> str:
    """
    Call Groq LLM with automatic retry on 429 rate-limit errors.
    Waits 20s → 40s → 60s before each retry (3 attempts total).
    """
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type":  "application/json",
    }
    payload = {
        "model":       GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        "temperature": 0.2,
        "max_tokens":  max_tokens,
    }
    try:
        resp = requests.post(GROQ_CHAT_ENDPOINT, json=payload, headers=headers, timeout=GROQ_TIMEOUT)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except requests.exceptions.HTTPError as exc:
        if exc.response.status_code == 401:
            return "❌ **Invalid Groq API Key.** Update `GROQ_API_KEY` in config.py."
        if exc.response.status_code == 413:
            return "❌ **Prompt too large for Groq.** Try a shorter date range or fewer recordings."
        if exc.response.status_code == 429:
            # Auto-retry with backoff: 60s → 90s → 120s
            # (Groq 6k TPM: a full 60s clears the entire per-minute budget)
            MAX_RETRIES = 3
            if _retry < MAX_RETRIES:
                wait_sec = 60 + 30 * _retry   # 60s, 90s, 120s
                time.sleep(wait_sec)
                return call_llm(user_prompt, system_prompt, max_tokens, _retry=_retry + 1)
            return "❌ **Groq rate limit.** Retried 3× (up to 4.5 min) — still limited. The batch will continue with the next recording."
        return f"❌ **Groq API Error ({exc.response.status_code}):** {exc.response.text}"
    except requests.exceptions.ConnectionError:
        return "❌ **Cannot connect to Groq API.** Check your internet connection."
    except Exception as exc:
        return f"❌ **LLM Error:** {exc}"


# ──────────────────────────────────────────────────────────────
# WHISPER TRANSCRIPTION
# ──────────────────────────────────────────────────────────────

def transcribe_audio(recording_url: str, max_retries: int = 3) -> str:
    """
    Download MP3 from URL and transcribe via Groq Whisper.
    Returns timestamped segments so the LLM can detect speaker changes
    from natural pauses. Format: '[MM:SS – MM:SS] text' per segment.
    Auto-detects language (handles Hindi/English/Hinglish calls).
    """
    # ── Download ──────────────────────────────────────────────
    try:
        audio_resp = requests.get(recording_url, timeout=60)
        audio_resp.raise_for_status()
        audio_bytes = audio_resp.content
    except Exception as exc:
        return f"❌ Could not download recording: {exc}"

    headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
    files   = {"file": ("recording.mp3", audio_bytes, "audio/mpeg")}
    data    = {
        "model":           GROQ_WHISPER_MODEL,
        "response_format": "verbose_json",  # gives per-segment timestamps
        # No "language" → auto-detect (better for Hinglish)
    }

    for attempt in range(max_retries):
        try:
            resp = requests.post(
                GROQ_AUDIO_ENDPOINT,
                headers=headers,
                files=files,
                data=data,
                timeout=180,
            )
            resp.raise_for_status()
            result = resp.json()

            segments = result.get("segments", [])
            if segments:
                # Format each segment with timestamps so LLM can use
                # silence gaps (≥1.5s between end of one and start of next)
                # as speaker-change signals
                lines = []
                for seg in segments:
                    start = float(seg.get("start", 0))
                    end   = float(seg.get("end",   start))
                    text  = seg.get("text", "").strip()
                    if not text:
                        continue
                    s_min, s_sec = int(start // 60), int(start % 60)
                    e_min, e_sec = int(end   // 60), int(end   % 60)
                    lines.append(
                        f"[{s_min:02d}:{s_sec:02d}–{e_min:02d}:{e_sec:02d}] {text}"
                    )
                return "\n".join(lines)

            # Fallback: no segments → return flat text
            return result.get("text", "").strip()

        except requests.exceptions.HTTPError as exc:
            if exc.response.status_code == 429:
                if attempt < max_retries - 1:
                    wait = (attempt + 1) * 15   # 15s, 30s, 45s
                    time.sleep(wait)
                    continue
                return "❌ Whisper rate limit hit after retries. Wait a minute and try again."
            return f"❌ Transcription error ({exc.response.status_code}): {exc.response.text}"
        except Exception as exc:
            return f"❌ Transcription failed: {exc}"

    return "❌ Transcription failed after all retries."


# ──────────────────────────────────────────────────────────────
# SARVAM AI TRANSCRIPTION  (Hindi/Hinglish — best for PD calls)
# ──────────────────────────────────────────────────────────────

SARVAM_STT_ENDPOINT = "https://api.sarvam.ai/speech-to-text"
SARVAM_CHUNK_SEC    = 25   # REST API limit is 30s — use 25s for safety margin


def _sarvam_transcribe_chunk(chunk_bytes: bytes, time_offset: float,
                              max_retries: int = 3) -> list[tuple[float, float, str]]:
    """
    Send one ≤25s audio chunk to Sarvam REST API.
    Returns list of (start_sec, end_sec, text) segments with time_offset applied.
    """
    headers = {"api-subscription-key": SARVAM_API_KEY}

    for attempt in range(max_retries):
        try:
            files = {"file": ("chunk.mp3", chunk_bytes, "audio/mpeg")}
            data  = {
                "model":         SARVAM_MODEL,
                "mode":          SARVAM_MODE,
                "language_code": SARVAM_LANG,
            }
            resp = requests.post(
                SARVAM_STT_ENDPOINT,
                headers=headers, files=files, data=data, timeout=60,
            )
            resp.raise_for_status()
            result = resp.json()

            ts     = result.get("timestamps", {})
            words  = ts.get("words", [])
            starts = ts.get("start_time_seconds", [])
            ends   = ts.get("end_time_seconds", [])

            if not words:
                # No timestamps — return flat text as one segment
                text = result.get("transcript", "").strip()
                if text:
                    return [(time_offset, time_offset + SARVAM_CHUNK_SEC, text)]
                return []

            # Group words into segments (split on pauses > 1.0s)
            segments: list[tuple[float, float, str]] = []
            seg_words, seg_start, prev_end = [], None, None
            for w, s, e in zip(words, starts, ends):
                s += time_offset
                e += time_offset
                if seg_start is None:
                    seg_start, prev_end, seg_words = s, e, [w]
                elif s - prev_end > 1.0:
                    segments.append((seg_start, prev_end, " ".join(seg_words)))
                    seg_start, prev_end, seg_words = s, e, [w]
                else:
                    seg_words.append(w)
                    prev_end = e
            if seg_words:
                segments.append((seg_start, prev_end, " ".join(seg_words)))
            return segments

        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code
            if status == 429 and attempt < max_retries - 1:
                time.sleep(20 * (attempt + 1))
                continue
            raise   # re-raise so caller can handle
        except Exception:
            raise

    return []


def transcribe_audio_sarvam(recording_url: str) -> str:
    """
    Transcribe a full PD call recording using Sarvam AI (saaras:v3 codemix).
    Handles recordings of ANY length by splitting into 25s chunks automatically.
    Returns timestamped segments: [MM:SS–MM:SS] text  (one per line)
    so format_transcript_speakers() can assign [Caller]/[Customer].
    """
    import tempfile, io

    # ── Download audio ────────────────────────────────────────
    try:
        audio_resp = requests.get(recording_url, timeout=60)
        audio_resp.raise_for_status()
        audio_bytes = audio_resp.content
    except Exception as exc:
        return f"❌ Could not download recording: {exc}"

    try:
        _ensure_ffmpeg()   # add ffmpeg dir to PATH first

        from pydub import AudioSegment
        import shutil

        # Tell pydub exactly where ffmpeg/ffprobe are
        _ffmpeg_bin  = os.path.join(_FFMPEG_DIR, "ffmpeg.exe")
        _ffprobe_bin = os.path.join(_FFMPEG_DIR, "ffprobe.exe")
        AudioSegment.converter = _ffmpeg_bin
        AudioSegment.ffmpeg    = _ffmpeg_bin
        AudioSegment.ffprobe   = _ffprobe_bin

        # Load audio
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes), format="mp3")
        duration_sec = len(audio) / 1000.0

        chunk_ms  = SARVAM_CHUNK_SEC * 1000
        all_segs: list[tuple[float, float, str]] = []

        # Chunk and transcribe
        for i, start_ms in enumerate(range(0, len(audio), chunk_ms)):
            chunk     = audio[start_ms: start_ms + chunk_ms]
            offset    = start_ms / 1000.0

            # Export chunk to MP3 bytes
            buf = io.BytesIO()
            chunk.export(buf, format="mp3")
            chunk_bytes = buf.getvalue()

            try:
                segs = _sarvam_transcribe_chunk(chunk_bytes, time_offset=offset)
                all_segs.extend(segs)
            except requests.exceptions.HTTPError as exc:
                status = exc.response.status_code
                if status == 403:
                    return "❌ Sarvam API key invalid or quota exhausted. Check SARVAM_API_KEY in config.py."
                if status == 429:
                    return "❌ Sarvam rate limit hit. Wait a minute and try again."
                return f"❌ Sarvam API error ({status}) on chunk {i+1}: {exc.response.text[:200]}"
            except Exception as exc:
                return f"❌ Sarvam chunk {i+1} failed: {exc}"

            # Small delay between chunks to respect 60 req/min rate limit
            if start_ms + chunk_ms < len(audio):
                time.sleep(1.2)

        if not all_segs:
            return "❌ Sarvam returned empty transcript for all chunks."

        # Format as timestamped lines
        lines = []
        for s, e, text in all_segs:
            s_min, s_sec = int(s // 60), int(s % 60)
            e_min, e_sec = int(e // 60), int(e % 60)
            lines.append(f"[{s_min:02d}:{s_sec:02d}–{e_min:02d}:{e_sec:02d}] {text}")
        return "\n".join(lines)

    except Exception as exc:
        return f"❌ Sarvam transcription failed: {exc}"


# ──────────────────────────────────────────────────────────────
# DEEPGRAM TRANSCRIPTION  (Nova-3 + real speaker diarization)
# ──────────────────────────────────────────────────────────────

DEEPGRAM_ENDPOINT = "https://api.deepgram.com/v1/listen"

def transcribe_audio_deepgram(recording_url: str) -> str:
    """
    Transcribe a PD call recording using Deepgram Nova-3.
    - language=multi  → Hindi / English / Tamil / any Indian language auto-handled
    - diarize=true    → real audio-based speaker separation (SPEAKER_0 / SPEAKER_1)
    - smart_format    → proper punctuation, numbers, dates
    - utterances=true → per-turn speaker segments

    Maps first speaker → [Caller], second speaker → [Customer].
    Returns clean [Caller]: ... / [Customer]: ... dialogue.
    No chunking needed — Deepgram handles full-length recordings natively.
    """
    # ── Download audio ────────────────────────────────────────
    try:
        audio_resp = requests.get(recording_url, timeout=60)
        audio_resp.raise_for_status()
        audio_bytes = audio_resp.content
    except Exception as exc:
        return f"❌ Could not download recording: {exc}"

    headers = {
        "Authorization": f"Token {DEEPGRAM_API_KEY}",
        "Content-Type":  "audio/mpeg",
    }
    params = {
        "model":        DEEPGRAM_MODEL,     # nova-3
        "language":     DEEPGRAM_LANGUAGE,  # multi
        "diarize":      "true",
        "smart_format": "true",
        "punctuate":    "true",
        "utterances":   "true",
    }

    try:
        resp = requests.post(
            DEEPGRAM_ENDPOINT,
            headers=headers,
            params=params,
            data=audio_bytes,
            timeout=300,   # 5 min — long recordings may take time
        )
        resp.raise_for_status()
        result = resp.json()
    except requests.exceptions.HTTPError as exc:
        status = exc.response.status_code
        if status == 401:
            return "❌ Deepgram API key invalid. Check DEEPGRAM_API_KEY in config.py."
        if status == 402:
            return "❌ Deepgram quota exhausted. Check your account at deepgram.com."
        return f"❌ Deepgram API error ({status}): {exc.response.text[:300]}"
    except Exception as exc:
        return f"❌ Deepgram request failed: {exc}"

    # ── Parse utterances ──────────────────────────────────────
    utterances = result.get("results", {}).get("utterances", [])

    if not utterances:
        # Fallback: no utterances → try flat transcript
        try:
            flat = result["results"]["channels"][0]["alternatives"][0]["transcript"]
            return flat.strip() if flat.strip() else "❌ Deepgram returned empty transcript."
        except Exception:
            return "❌ Deepgram returned no utterances or transcript."

    # ── Content-based speaker identification ─────────────────────
    # Order-based mapping is unreliable: in some calls the GQ employee
    # speaks first, in others the customer does.
    # Instead, scan each speaker's first 5 utterances for GQ Caller signals.
    #
    # GQ Caller signals (Hinglish PD call patterns):
    #   - Company name: "grayquest", "gq"
    #   - Introduction patterns: "this side", "side se", "baat kar raha/rahi", "calling from"
    #   - Verification phrases: "verify", "confirm", "karna tha", "karna hai"
    #   - Topics they ask about: "cibil", "income", "address", "admission",
    #     "emi", "application", "financial", "loan", "overdue"
    #   - Question openers: "aapka", "aap ka", "kyaa aap", "batao", "bata do"
    _GQ_CALLER_SIGNALS = [
        "grayquest", "gray quest", " gq ", "gq se",
        "this side", "side se", "baat kar raha", "baat kar rahi",
        "calling from", "call kar raha", "call kar rahi",
        "verify", "karna tha", "karna hai", "checklist",
        "confirm kar", "cibil", "overdue", "dpd",
        "admission", "application", "income", "salary", "emi",
        "financial", "loan company", "grayquest",
    ]

    def _is_caller_content(texts: list[str]) -> bool:
        combined = " ".join(texts)
        return any(sig in combined for sig in _GQ_CALLER_SIGNALS)

    # Collect first 5 utterances per speaker
    _early: dict[int, list[str]] = {}
    for utt in utterances[:30]:
        spk  = utt.get("speaker", 0)
        text = utt.get("transcript", "").lower().strip()
        if text and len(_early.get(spk, [])) < 5:
            _early.setdefault(spk, []).append(text)

    # Identify the GQ Caller speaker ID
    _caller_spk: int | None = None
    for spk_id, texts in _early.items():
        if _is_caller_content(texts):
            _caller_spk = spk_id
            break

    # Build speaker map
    speaker_map: dict[int, str] = {}
    _seen_non_caller = False
    for utt in utterances:
        spk = utt.get("speaker", 0)
        if spk in speaker_map:
            continue
        if _caller_spk is not None:
            speaker_map[spk] = "Caller" if spk == _caller_spk else "Customer"
        else:
            # Fallback (no signals found): treat second distinct speaker as Caller
            if not _seen_non_caller:
                speaker_map[spk] = "Customer"
                _seen_non_caller = True
            else:
                speaker_map[spk] = "Caller"

    # Any extra speakers (3-way calls) labelled as Speaker N
    for utt in utterances:
        spk = utt.get("speaker", 0)
        if spk not in speaker_map:
            speaker_map[spk] = f"Speaker {spk}"

    # ── Build clean dialogue ──────────────────────────────────
    lines = []
    prev_label = None
    cur_text   = ""

    for utt in utterances:
        spk   = utt.get("speaker", 0)
        text  = utt.get("transcript", "").strip()
        if not text:
            continue
        label = speaker_map.get(spk, f"Speaker {spk}")

        if label == prev_label:
            cur_text += " " + text   # merge consecutive turns from same speaker
        else:
            if prev_label and cur_text:
                lines.append(f"[{prev_label}]: {cur_text.strip()}")
            prev_label = label
            cur_text   = text

    if prev_label and cur_text:
        lines.append(f"[{prev_label}]: {cur_text.strip()}")

    if not lines:
        return "❌ Deepgram diarization returned no labelled turns."

    return "\n\n".join(lines)


# ──────────────────────────────────────────────────────────────
# LANGUAGE DETECTION + TRANSLATION
# ──────────────────────────────────────────────────────────────

def ensure_english_or_hindi_transcript(transcript: str) -> tuple[str, str]:
    """
    Detect language of a diarized transcript. If it is not English, Hindi, or
    Hinglish, translate the FULL transcript to English while preserving all
    [Caller]: / [Customer]: labels, amounts, and names.

    Returns:
        (final_transcript, detected_language)
        detected_language = "Hindi / English" if no translation was needed.

    Detection logic (two-pass):
    Pass 1 — Script range check:
        U+0980–U+0DFF  →  Bengali / Gujarati / Tamil / Telugu / Kannada / Malayalam
                          (distinct scripts — always translate)
    Pass 2 — Word check for Devanagari-script non-Hindi languages:
        Marathi, Konkani, Bhojpuri etc. use Devanagari (U+0900–U+097F) like Hindi.
        Detect via common Marathi/regional words that don't appear in Hindi.
    """
    sample = transcript[:1200]

    # ── Pass 1: non-Devanagari regional scripts ───────────────
    regional_count = sum(1 for c in sample if 0x0980 <= ord(c) <= 0x0DFF)
    if regional_count >= 20:
        return _translate_transcript(transcript, "Regional Indian Language")

    # ── Pass 2: Marathi / Konkani detection via vocabulary ────
    # These words are common in Marathi but absent (or very rare) in Hindi/Hinglish
    _MARATHI_MARKERS = [
        "आहे", "आहेत", "होते", "होती", "होतो",
        "नाही", "नाहीत", "आलो", "आले", "गेलो", "गेले",
        "करतो", "करते", "बघतो", "बोलतो", "सांगतो",
        "मला", "तुम्ही", "तुम्हाला", "आम्ही", "त्यांना",
        "काय", "कसे", "कुठे", "केव्हा", "कोण",
        "माझे", "माझी", "माझा", "तुझे", "तुझी",
        "ठीक आहे", "हो ना", "बरं",
    ]
    marathi_hits = sum(1 for w in _MARATHI_MARKERS if w in sample)
    if marathi_hits >= 3:
        return _translate_transcript(transcript, "Marathi")

    # ── No regional language detected → return as-is ─────────
    return transcript, "Hindi / English"


def _translate_transcript(transcript: str, hint_lang: str) -> tuple[str, str]:
    """
    Translate a regional-language transcript to English using Groq LLM.
    Preserves [Caller]: / [Customer]: labels, amounts, and proper nouns.
    Returns (translated_transcript, detected_language_name).
    """
    system = (
        "You are an expert translator for Indian loan-verification call transcripts. "
        "Translate accurately to English, preserving speaker labels, amounts, and proper nouns."
    )
    prompt = f"""Translate this PD call transcript to English.

Rules:
• First line MUST be: LANGUAGE: [exact language name, e.g. Marathi / Telugu / Bengali]
• Keep [Caller]: and [Customer]: labels EXACTLY unchanged (do not rename them)
• Keep all numbers, amounts (Rs., EMI), phone numbers, and proper names unchanged
• Translate ALL other text to clear, natural English
• Do NOT summarise — translate every turn completely

TRANSCRIPT:
{transcript[:2800]}"""

    result = call_llm(prompt, system, max_tokens=2800)
    if result.startswith("❌"):
        return transcript, f"{hint_lang} (translation failed)"

    lines = result.strip().split("\n")
    detected_lang = hint_lang
    start_idx = 0
    if lines and lines[0].upper().startswith("LANGUAGE:"):
        detected_lang = lines[0].split(":", 1)[1].strip()
        start_idx = 1

    translated = "\n".join(lines[start_idx:]).strip()
    return translated, detected_lang


# ── Module-level model cache (loaded once per Streamlit session) ──────────────
# Models are heavy (~500MB RAM). Reloading per recording wastes 2-5 min each time.
# These are set by _load_whisperx_models() and reused across all recordings.
_wx_model       = None   # WhisperX ASR model
_wx_align_cache = {}     # {language_code: (model_a, metadata)}
_diarize_pipeline = None # pyannote speaker diarization pipeline

_FFMPEG_DIR = r"C:\Users\aditya_kumar\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.1-full_build\bin"


def _ensure_ffmpeg():
    """Add ffmpeg to PATH if not already there."""
    if _FFMPEG_DIR not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _FFMPEG_DIR + os.pathsep + os.environ.get("PATH", "")


def load_whisperx_models():
    """
    Load WhisperX ASR + pyannote diarization pipeline into module-level cache.
    Call this ONCE before processing a batch — subsequent recordings reuse the same objects.
    Returns (whisperx_model, diarize_pipeline) or raises on failure.
    """
    global _wx_model, _diarize_pipeline

    _ensure_ffmpeg()

    try:
        import whisperx
    except ImportError:
        raise RuntimeError("WhisperX not installed in this environment.")

    device       = WHISPERX_DEVICE
    compute_type = "int8" if device == "cpu" else "float16"

    if _wx_model is None:
        _wx_model = whisperx.load_model(WHISPERX_MODEL, device, compute_type=compute_type)

    if _diarize_pipeline is None:
        from pyannote.audio import Pipeline as PyannotePipeline
        _diarize_pipeline = PyannotePipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            token=HF_TOKEN,
        )

    return _wx_model, _diarize_pipeline


def transcribe_audio_whisperx(recording_url: str) -> str:
    """
    Transcribe a PD call recording using WhisperX + pyannote speaker diarization.
    Runs locally on Python 3.11 venv (venv311).
    Models are cached — only loaded once per session, reused for every recording.
    Returns clean [Caller] / [Customer] labelled dialogue.
    """
    import tempfile, traceback

    _ensure_ffmpeg()

    # ── Load models (from cache if already loaded) ────────────
    try:
        import whisperx
        wx_model, diarize_pipeline = load_whisperx_models()
    except Exception as exc:
        return f"❌ Model loading failed: {exc}"

    # ── Download audio ────────────────────────────────────────
    try:
        audio_resp = requests.get(recording_url, timeout=60)
        audio_resp.raise_for_status()
        audio_bytes = audio_resp.content
    except Exception as exc:
        return f"❌ Could not download recording: {exc}"

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name

        device = WHISPERX_DEVICE

        # ── Step 1: Transcribe ────────────────────────────────
        audio  = whisperx.load_audio(tmp_path)
        result = wx_model.transcribe(audio, batch_size=8)
        lang   = result.get("language", "hi")

        # ── Step 2: Align (cache align model per language) ────
        try:
            global _wx_align_cache
            if lang not in _wx_align_cache:
                model_a, metadata = whisperx.load_align_model(language_code=lang, device=device)
                _wx_align_cache[lang] = (model_a, metadata)
            model_a, metadata = _wx_align_cache[lang]
            result = whisperx.align(result["segments"], model_a, metadata, audio, device)
        except Exception:
            pass

        # ── Step 3: Speaker diarization via pyannote ──────────
        # NOTE: Pass audio as a waveform dict (not a file path) to bypass
        # torchcodec.AudioDecoder which fails on Windows due to missing DLLs.
        # pyannote explicitly supports {'waveform': tensor, 'sample_rate': int}.
        try:
            import torchaudio

            # Load audio with torchaudio — avoids torchcodec entirely
            waveform, sample_rate = torchaudio.load(tmp_path)
            # Resample to 16kHz if needed (pyannote expects 16kHz)
            if sample_rate != 16000:
                waveform = torchaudio.functional.resample(waveform, sample_rate, 16000)
                sample_rate = 16000

            # Pass waveform dict — skips AudioDecoder (torchcodec) code path
            diarize_output = diarize_pipeline({"waveform": waveform, "sample_rate": sample_rate})
            # Newer pyannote returns DiarizeOutput wrapper; unwrap to Annotation
            if hasattr(diarize_output, "speaker_diarization"):
                annotation = diarize_output.speaker_diarization
            else:
                annotation = diarize_output   # older API returned Annotation directly
            speaker_turns = [
                (float(seg.start), float(seg.end), spk)
                for seg, _, spk in annotation.itertracks(yield_label=True)
            ]
        except Exception as exc:
            return f"❌ Speaker diarization failed: {exc}"

        # ── Step 4: Match segments → speakers ─────────────────
        def get_speaker(s: float, e: float) -> str:
            best_spk, best_ov = "SPEAKER_00", 0.0
            for ts, te, spk in speaker_turns:
                ov = min(e, te) - max(s, ts)
                if ov > best_ov:
                    best_ov, best_spk = ov, spk
            return best_spk

        segments = result.get("segments", [])
        if not segments:
            return "❌ WhisperX returned no segments."

        # ── Step 5: Build dialogue ────────────────────────────
        speaker_map: dict[str, str] = {}
        lines:       list[str]      = []
        cur_spk,  cur_txt           = None, ""

        for seg in segments:
            s    = float(seg.get("start", 0))
            e    = float(seg.get("end", s))
            txt  = seg.get("text", "").strip()
            if not txt:
                continue
            raw  = get_speaker(s, e)
            if raw not in speaker_map:
                speaker_map[raw] = "Caller" if not speaker_map else "Customer"
            if raw == cur_spk:
                cur_txt += " " + txt
            else:
                if cur_spk:
                    lines.append(f"[{speaker_map[cur_spk]}]: {cur_txt.strip()}")
                cur_spk, cur_txt = raw, txt

        if cur_spk and cur_txt:
            lines.append(f"[{speaker_map[cur_spk]}]: {cur_txt.strip()}")

        return "\n\n".join(lines)

    except Exception as exc:
        return f"❌ WhisperX failed: {exc}\n\n```\n{traceback.format_exc()}\n```"
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def score_recording_transcript(row: dict, transcript: str, system_data: dict = None) -> str:
    """
    Score a clean, speaker-labelled transcript using Groq LLM.
    Sections: Quality Score | Tone & Professionalism | Risk Assessment | Summary

    system_data (optional): dict with CIBIL, overdue, DPD, income etc. from GQ database.
    When provided:
      - CIBIL / Overdue / DPD checks become CONDITIONAL:
          Good value → auto-pass (N/R), caller not penalised
          Bad value  → caller MUST have covered it
      - System address shown for Caller to verify against what customer stated
      - Risk score uses actual system values, not just transcript
    """
    app_id       = row.get("app_id", "N/A")
    product_type = row.get("product_type", "Non FSF")
    caller       = row.get("caller", "")

    # Truncate transcript — Groq context limit (~8192 tokens); Hindi tokenizes ~1 char/token
    MAX_TRANSCRIPT_CHARS = 2800
    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        transcript = transcript[:MAX_TRANSCRIPT_CHARS] + "\n[... truncated ...]"

    n_checks       = len(get_criteria(product_type))
    n_banking      = get_banking_param_count(product_type)
    n_non_banking  = n_checks - n_banking
    pts_with_bank  = round(QUALITY_MARKS / n_checks, 2)
    pts_no_bank    = round(QUALITY_MARKS / n_non_banking, 2) if n_non_banking > 0 else pts_with_bank

    # ── Compact system data line ──────────────────────────────
    sys_line          = ""
    conditional_notes = {}
    if system_data:
        cibil       = system_data.get("cibil_score", -1) or -1
        overdue     = system_data.get("overdue_amount", 0) or 0
        gq_dpd      = system_data.get("gq_dpd_days", 0) or 0
        income      = system_data.get("monthly_income", 0) or 0
        work_status = system_data.get("work_status", "") or ""
        foir        = system_data.get("foir", 0) or 0
        address     = system_data.get("system_address", "") or ""
        gender      = system_data.get("gender", "") or ""
        cibil_disp  = str(int(float(cibil))) if int(float(cibil)) != -1 else "-1(no hist)"
        sys_line = (
            f"\nSYSTEM DATA: CIBIL={cibil_disp} | Overdue=Rs.{int(float(overdue)):,} | "
            f"GQ_DPD={int(float(gq_dpd))}d | Income=Rs.{int(float(income)):,}/mo({work_status}) | "
            f"FOIR={foir}% | Gender={gender or 'N/A'} | Addr={address or 'N/A'}\n"
        )
        conditional_notes = get_conditional_notes(product_type, system_data)

    risk_table = build_risk_scoring_table(product_type, system_data)

    # Banking conditional note (compact)
    banking_instr = ""
    if n_banking > 0:
        banking_instr = (
            f"\nBANKING: Did caller ask for banking statement/ABB/salary credits?"
            f" YES → {pts_with_bank}pts each for all {n_checks} params."
            f" NO → fill banking rows as 'Banking not discussed', N/A pts;"
            f" score {n_non_banking} non-banking params at {pts_no_bank}pts each.\n"
        )

    quality_table = build_quality_table_template(product_type, conditional_notes)

    prompt = f"""GrayQuest PD QA — App ID:{app_id} | Product:{product_type} | Caller:{caller}
[Caller]=GQ PD employee (asks questions). [Customer]=loan applicant (answers).
{sys_line}
TRANSCRIPT:
{transcript}

---
PART 1 — QUALITY SCORECARD ({QUALITY_MARKS} pts)

⚠️ SCORING RULE (read carefully):
✅ COVERED = [Caller] mentioned / asked about this topic at any point. Value doesn't matter — even bad answers (new admission, uncle, rented) = ✅ COVERED.
❌ MISSED  = [Caller] never brought up this topic at all in the entire transcript.
N/R = pre-filled (system data clean, auto-pass — do not change).

Examples from Hinglish calls:
  "naya admission hai ya existing?" → Student Type = ✅ COVERED
  "Riya aapke kaun hai?" / "meri bachi hai" → Co-applicant Relation = ✅ COVERED
  "plot number confirm karo / yeh home hai ya rented?" → Address = ✅ COVERED
  "aapki income kitni hai?" → Work/Income = ✅ COVERED
{banking_instr}
⚠️ OUTPUT FORMAT FOR PART 1: You MUST reproduce the table below with ALL [fill X] placeholders replaced. Do NOT use a list.

{quality_table}

**Quality Checks Score: X/{QUALITY_MARKS}**
**Areas to Improve:** (list only the ❌ MISSED rows — skip N/R and banking-not-discussed rows)

---
PART 2 — TONE & PROFESSIONALISM ({TONE_MARKS} pts)
1. Professional intro & conduct: (quote)
2. Respectful to customer: Yes/No + evidence
3. Aggressive/pressuring language: (exact quote or "None detected")
4. Compliance issues: (quote or "None")
**Tone Score: X/{TONE_MARKS}**  **Verdict:** PASS / NEEDS IMPROVEMENT / FAIL

**OVERALL QUALITY SCORE: [Checks + Tone] = X/10**

---
PART 3 — RISK ASSESSMENT
{risk_table}

**Total FLAGS: [count]**
**Risk Level:** LOW / MEDIUM / HIGH
**Recommendation:** APPROVE / APPROVE WITH CONDITIONS / DECLINE
**Reason:** (one bullet per flagged row with actual value and reason)

---
PART 4 — SUMMARY
1. Quality: X/10 (checks X/{QUALITY_MARKS} + tone X/{TONE_MARKS}) — [strengths and gaps]
2. Banking: [Verified / Not discussed / Partial]
3. Risk: [level] — [main factor or "clean profile"]
4. Key Concerns: [2–3 items with values, or "None"]
5. Decision: [APPROVE / CONDITIONS / DECLINE] — [specific reason with values]
"""

    return call_llm(prompt, _SYSTEM_SCORER, max_tokens=1800)


def compare_comment_to_transcript(transcript: str, comment: str, product_type: str) -> str:
    """
    Compare what was actually discussed in the PD call vs what the caller
    wrote in the panel comment.

    Detects:
      - Items discussed in call but NOT documented in comment (omissions)
      - Items written in comment but NOT found in call (fabrications / unverified claims)
      - Consistent items (discussed AND documented correctly)

    Returns a structured markdown report with a comparison table + verdict.
    """
    MAX_TRANSCRIPT_CHARS = 1800   # Shorter than scoring — just need key topics
    MAX_COMMENT_CHARS    = 1200

    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        transcript = transcript[:MAX_TRANSCRIPT_CHARS] + "\n[... truncated ...]"
    if len(comment) > MAX_COMMENT_CHARS:
        comment = comment[:MAX_COMMENT_CHARS] + "\n[... truncated ...]"

    system = (
        "You are a GrayQuest PD QA auditor. Your job is to compare a PD call transcript "
        "with the panel comment written by the caller after the call. "
        "Be precise — only flag clear discrepancies, not vague ones."
    )

    prompt = f"""GrayQuest PD — Call vs Panel Comment Consistency Check
Product Type: {product_type}

CALL TRANSCRIPT (what was actually discussed):
{transcript}

PANEL COMMENT (what the caller wrote in the system after the call):
{comment}

---
Compare the above and produce the following output:

**PART 5 — CALL vs PANEL COMMENT CONSISTENCY**

**Comparison Table:**
| # | Topic | In Call? | In Comment? | Status |
|---|-------|----------|-------------|--------|
(Fill one row per key PD topic: student type, co-applicant relation, address/ownership, work/income, CIBIL, overdue/DPD, alternate contact, banking, risk factors)

Status rules:
✅ Consistent     = discussed in call AND documented correctly in comment
⚠️ Not documented = discussed in call but NOT mentioned in comment
🚩 Not in call    = written in comment but NOT found anywhere in call transcript
➖ N/A            = topic not relevant or not expected for this product type

**Consistency Verdict:** CONSISTENT / MINOR GAPS / MAJOR DISCREPANCY
- CONSISTENT      = 0 🚩 rows and ≤ 1 ⚠️ row
- MINOR GAPS      = 0 🚩 rows but 2+ ⚠️ rows (under-documented)
- MAJOR DISCREPANCY = 1+ 🚩 rows (comment contains facts not discussed in call)

**Key Findings:**
- [list only ⚠️ and 🚩 rows here — skip ✅ rows]

**Auditor Note:** (1 sentence — overall quality of the caller's documentation)
"""

    return call_llm(prompt, system, max_tokens=900)


def format_transcript_speakers(raw_transcript: str) -> str:
    """
    LEAN call — just assigns [Caller] / [Customer] labels to timestamped Whisper output.
    Kept intentionally small to stay within Groq free-tier 6k TPM limit.
    Returns clean [Caller]: ... / [Customer]: ... dialogue.
    """
    if not raw_transcript or raw_transcript.startswith("❌"):
        return raw_transcript

    # Sarvam transcripts are already concise (no hallucination bloat)
    # Allow up to 8000 chars — covers ~8-10 min calls comfortably
    MAX_CHARS = 8000
    truncated = ""
    if len(raw_transcript) > MAX_CHARS:
        raw_transcript = raw_transcript[:MAX_CHARS] + "\n[... transcript truncated ...]"
        truncated = " *(first ~8 min shown)*"

    system = """You are a transcript formatter for GrayQuest PD (Personal Discussion) loan verification calls.
Your ONLY job: assign [Caller] or [Customer] to EVERY segment. Never leave any segment empty or skipped."""

    prompt = f"""Format this transcript into clean [Caller] / [Customer] dialogue.
IMPORTANT: Include the FULL text for EVERY turn — never leave a [Caller]: or [Customer]: label blank.

SPEAKER RULES:
- [Caller] = GrayQuest employee: introduces themselves, ASKS about CIBIL/income/address/EMI/co-applicant/admission/DPDs, controls flow
- [Customer] = loan applicant: ANSWERS questions, gives their name/address/income/bank details, asks about loan status

RAW TRANSCRIPT (timestamped):
{raw_transcript}

OUTPUT FORMAT — reproduce ALL spoken text, nothing skipped:
[Caller]: (their exact words)

[Customer]: (their exact words)

[Caller]: (next turn)

...continue for full call...{truncated}"""

    return call_llm(prompt, system, max_tokens=2500)


def clean_transcript(raw_transcript: str) -> str:
    """
    Use LLM to format raw Whisper output into clean, readable dialogue.
    Carefully identifies Caller (GrayQuest PD employee) vs Customer (applicant).
    """
    if not raw_transcript or raw_transcript.startswith("❌"):
        return raw_transcript

    system = """You are an expert call transcript formatter for GrayQuest, an Indian education loan company.
You format raw Whisper speech-to-text output into clean, readable dialogue.
Calls are in Hindi, English, or Hinglish (mixed) — always preserve the original language, never translate."""

    prompt = f"""Format this raw speech-to-text transcript into clean, labelled dialogue.

RAW TRANSCRIPT:
{raw_transcript}

---

SPEAKER IDENTIFICATION RULES — follow these carefully:

**[Caller]** = GrayQuest PD (Personal Discussion) team employee. Identifies as:
- Introduces themselves as calling from GrayQuest / financial services / loan company
- ASKS questions to verify information
- Asks about: CIBIL score, address, income, EMI, co-applicant relation, DPDs, bank details, alternate number, admission details
- Uses phrases like: "verify karna tha", "confirm karna tha", "bata dijiye", "aapka", "sir/ma'am aap..."
- Never provides their own personal/financial details
- Controls the flow of the conversation

**[Customer]** = Loan applicant or co-applicant. Identifies as:
- ANSWERS questions
- Provides their own personal details (name, address, income, CIBIL etc.)
- Asks questions about loan status, EMI amount, fees, approval
- Uses phrases like: "haan ji", "theek hai", "mera/meri", gives numbers/amounts when asked
- Reacts to what the caller says

COMMON MISTAKES TO AVOID:
- Do NOT label as Customer when someone is asking verification questions → that is the Caller
- Do NOT label as Caller when someone is giving their personal address/income → that is the Customer
- If caller is on bike / noisy background → still label correctly based on content
- Repetitive words (transcription glitch) → keep once and mark as [unclear audio]

FORMATTING RULES:
1. Add proper punctuation and natural sentence breaks
2. Group 2-3 related sentences into one paragraph per speaker turn
3. Remove word-for-word repetitions caused by audio glitches (keep meaning, remove duplicates)
4. Mark genuinely unclear sections as [unclear]
5. Keep ALL original content — do not summarize or skip anything
6. Do NOT translate Hindi/Hinglish to English

Return ONLY the formatted transcript. No introduction, no commentary."""

    return call_llm(prompt, system, max_tokens=3000)


# ──────────────────────────────────────────────────────────────
# SCORING PROMPT BUILDER
# ──────────────────────────────────────────────────────────────

_SYSTEM_SCORER = """You are a senior PD (Personal Discussion) quality analyst and fintech QA auditor at GrayQuest,
an Indian education loan company. You evaluate PD calls and comments across three dimensions:
1. QUALITY — did the Caller cover all required parameters?
2. TONE & PROFESSIONALISM — was the call conducted ethically and respectfully?
3. RISK — are there negative indicators that affect loan approval?

Be specific, quote exact phrases where relevant, reference App IDs, and always give actionable feedback.
Respond in clean Markdown."""


def build_scoring_prompt(
    content: str,
    app_id: int | str,
    product_type: str,
    content_type: str = "comment",   # "comment" or "recording"
    caller_name: str = "",
) -> str:
    criteria_text  = build_criteria_text(product_type)
    risk_text      = build_risk_factors_text()
    pts_each       = get_points_each(product_type)
    n_checks       = len(get_criteria(product_type))

    caller_line = f"**Caller:** {caller_name}\n" if caller_name else ""

    tone_instruction = ""
    if content_type == "recording":
        tone_instruction = """
---
### PART 3 — Tone & Communication Quality (out of 2 bonus points)
Evaluate based on the transcript:
- **Professionalism**: polite, respectful language
- **Structure**: clear and logical flow of questions
- **Empathy**: handles sensitive topics (DPDs, financial issues) with care
- **Completeness**: covered topics systematically without rushing

Format:
**Tone Score: X/2**
| Dimension | Observation |
|-----------|-------------|
| Professionalism | ... |
| Structure | ... |
| Empathy | ... |
| Completeness | ... |

**Tone Improvement Areas:** (if any)
"""

    return f"""## PD {content_type.upper()} SCORING — App ID: {app_id} | Product: {product_type}
{caller_line}
---
### SCORING CRITERIA FOR {product_type.upper()} ({n_checks} checks, {pts_each} pts each)

{criteria_text}

---
### RISK FACTORS (check separately — for loan approval decision)

{risk_text}

---
### {content_type.upper()} CONTENT TO EVALUATE:

{content}

---
## YOUR EVALUATION:

### PART 1 — QUALITY SCORECARD (out of 10)

**Instructions:** For each parameter, check if the caller MENTIONED or VERIFIED it in the PD.
Award points for coverage — even if the finding was negative.
Do NOT award points if the topic was completely absent from the discussion.

| # | Parameter | Covered? | Finding from PD | Points |
|---|-----------|----------|-----------------|--------|
(fill one row per parameter — use ✅ for covered, ❌ for not covered)

**Total Quality Score: X/10**

**Areas to Improve:**
(list parameters that were NOT covered, or covered insufficiently)

---
### PART 2 — RISK ASSESSMENT (for loan approval)

**Instructions:** Based on actual VALUES found in the PD, identify negative indicators.

**Risk Flags Found:**
(list each, e.g. "🔴 CIBIL 580 < threshold of 650" or "🟢 No DPDs — clear")

**Risk Level:** 🟢 LOW RISK / 🟡 MEDIUM RISK / 🔴 HIGH RISK
(0 negative flags = LOW, 1 = MEDIUM, 2+ = HIGH)

**Loan Recommendation:** APPROVE / APPROVE WITH CONDITIONS / DECLINE
**Reason:** (reference specific findings with values){tone_instruction}

---
### OVERALL SUMMARY
2–3 lines: quality of this PD call + risk profile of this case.
"""


# ──────────────────────────────────────────────────────────────
# SCORE ALL PD COMMENTS — single LLM call for all app IDs
# ──────────────────────────────────────────────────────────────

def score_pd_comments_batch(rows: list[dict]) -> str:
    """
    Score ALL PD comment rows in ONE single LLM call.
    Drastically reduces API calls: N app IDs = 1 call (not N calls).
    Returns full markdown with a scored section per app ID.
    """
    from backend.scoring_criteria import FSF_CRITERIA, NFSF_CRITERIA, EDTECH_CRITERIA, RISK_FACTORS

    # Build all-criteria reference (so LLM knows criteria for every product type)
    def fmt_criteria(criteria, label):
        pts = round(10 / len(criteria), 2)
        lines = [f"\n**{label} ({len(criteria)} checks, {pts} pts each):**"]
        for i, c in enumerate(criteria, 1):
            lines.append(f"{i}. {c['parameter']}: positive={c['positive']} | negative={c['negative']}")
        return "\n".join(lines)

    all_criteria_text = (
        fmt_criteria(FSF_CRITERIA,   "FSF")
        + fmt_criteria(NFSF_CRITERIA,  "Non FSF")
        + fmt_criteria(EDTECH_CRITERIA,"EdTech")
        + "\n\n**RISK FACTORS (all product types):**\n"
        + "\n".join(f"- {r}" for r in RISK_FACTORS)
    )

    # Format all cases into one block
    cases_text = ""
    for row in rows:
        app_id  = row.get("app_id") or row.get("id", "N/A")
        product = row.get("product_type", "Non FSF")
        caller  = row.get("pd_caller_name", "—")
        date    = str(row.get("pd_comment_date", ""))[:10]
        comment = (row.get("credit_pd_comment") or "").strip()

        if not comment:
            cases_text += f"\n\n---\n**App ID: {app_id}** | {product} | {caller}\n⚠ No comment available.\n"
            continue

        cases_text += (
            f"\n\n{'='*60}\n"
            f"**APP ID: {app_id}** | Product: {product} | "
            f"Caller: {caller} | Date: {date}\n"
            f"{'='*60}\n"
            f"{comment}\n"
        )

    prompt = f"""You are a senior PD quality analyst at GrayQuest, an Indian education loan company.
Score EACH of the following PD cases. Apply the correct scoring criteria based on each case's product type.

## SCORING CRITERIA REFERENCE
{all_criteria_text}

## CASES TO SCORE
{cases_text}

## INSTRUCTIONS
For EACH App ID above, provide this exact structure:

---
## 📋 App ID: [X] | [Product] | Caller: [Name]

### Quality Scorecard
| # | Parameter | Covered? | Finding | Points |
|---|-----------|----------|---------|--------|
(one row per parameter for that product type — ✅ covered / ❌ not covered)

**Quality Score: X/10**
**Areas to Improve:** (bullet list of missing/weak parameters)

### Risk Assessment
**Risk Flags:** (list each: 🔴 negative finding OR 🟢 clear)
**Risk Level:** 🟢 LOW / 🟡 MEDIUM / 🔴 HIGH
**Recommendation:** APPROVE / APPROVE WITH CONDITIONS / DECLINE
**Reason:** (specific values from the PD)

### Summary
One line: quality + risk overview for this case.
---

Score every App ID. Do not skip any."""

    return call_llm(prompt, _SYSTEM_SCORER, max_tokens=3000)


# ──────────────────────────────────────────────────────────────
# SCORE SINGLE PD COMMENT — rich format matching recording page
# ──────────────────────────────────────────────────────────────

def score_pd_comment(row: dict, system_data: dict = None) -> str:
    """
    Score ONE PD comment with 4-part format:
      Part 1 — Quality Scorecard (table with ✅/❌/N/R, findings, points)
      Part 2 — PD Documentation Audit (structured, thorough, compliant?)
      Part 3 — Risk Assessment (flags + level + recommendation)
      Part 4 — Overall Summary

    system_data (optional): dict with CIBIL, overdue, DPD etc. from GQ database.
    When provided, CIBIL/Overdue/DPD checks become conditional (same as recording scoring).
    """
    app_id       = row.get("app_id") or row.get("id", "N/A")
    product_type = row.get("product_type", "Non FSF")
    caller       = row.get("pd_caller_name", "—")
    date_str     = str(row.get("pd_comment_date", ""))[:10]
    comment      = (row.get("credit_pd_comment") or "").strip()

    if not comment:
        return f"⚠️ **App ID {app_id}** — No PD comment available."

    criteria_text  = build_criteria_text(product_type)
    n_checks       = len(get_criteria(product_type))
    n_banking      = get_banking_param_count(product_type)
    n_non_banking  = n_checks - n_banking
    pts_with_bank  = round(QUALITY_MARKS / n_checks, 2)
    pts_no_bank    = round(QUALITY_MARKS / n_non_banking, 2) if n_non_banking > 0 else pts_with_bank

    MAX_COMMENT_CHARS = 2000
    truncated_note = ""
    if len(comment) > MAX_COMMENT_CHARS:
        comment = comment[:MAX_COMMENT_CHARS] + "\n[... truncated ...]"
        truncated_note = " *(truncated)*"

    # ── Compact system data line ──────────────────────────────
    sys_line          = ""
    conditional_notes = {}
    if system_data:
        cibil       = system_data.get("cibil_score", -1) or -1
        overdue     = system_data.get("overdue_amount", 0) or 0
        gq_dpd      = system_data.get("gq_dpd_days", 0) or 0
        income      = system_data.get("monthly_income", 0) or 0
        work_status = system_data.get("work_status", "") or ""
        foir        = system_data.get("foir", 0) or 0
        address     = system_data.get("system_address", "") or ""
        gender      = system_data.get("gender", "") or ""
        cibil_disp  = str(int(float(cibil))) if int(float(cibil)) != -1 else "-1(no hist)"
        sys_line = (
            f"\nSYSTEM DATA: CIBIL={cibil_disp} | Overdue=Rs.{int(float(overdue)):,} | "
            f"GQ_DPD={int(float(gq_dpd))}d | Income=Rs.{int(float(income)):,}/mo({work_status}) | "
            f"FOIR={foir}% | Gender={gender or 'N/A'} | Addr={address or 'N/A'}\n"
        )
        conditional_notes = get_conditional_notes(product_type, system_data)

    cond_lines = ""
    if conditional_notes:
        cond_lines = "\nConditional overrides: " + " | ".join(
            f"{p}: {n}" for p, n in conditional_notes.items()
        ) + "\n"

    risk_table = build_risk_scoring_table(product_type, system_data)

    banking_instr = ""
    if n_banking > 0:
        banking_instr = (
            f"\nBANKING CHECK — do this FIRST:\n"
            f"Does the comment mention collecting / verifying banking statement, ABB, or salary credits?\n"
            f"→ YES: score all {n_checks} params at {pts_with_bank}pts each.\n"
            f"→ NO: for every [BANKING] param write 'Banking Not Taken in PD' + N/A pts.\n"
            f"   Score remaining {n_non_banking} non-banking params at {pts_no_bank}pts each.\n"
        )

    quality_table = build_quality_table_template(product_type, conditional_notes)

    prompt = f"""GrayQuest PD comment QA — App ID:{app_id} | Product:{product_type} | Caller:{caller} | Date:{date_str}
{sys_line}
PD COMMENT{truncated_note}:
{comment}

---
PART 1 — QUALITY SCORECARD ({QUALITY_MARKS} pts)

⚠️ SCORING RULE (read carefully):
✅ COVERED = The comment mentions this topic anywhere. Value doesn't matter — even bad values (new admission, uncle, rented) = ✅ COVERED.
❌ MISSED  = Topic is completely absent from the comment — not written anywhere.
N/R = pre-filled (system data clean, auto-pass — do not change).

Examples:
  "student new admission hai" → Student Type = ✅ COVERED (value noted, even though new = risk)
  "co-applicant uncle hai" → Co-applicant Relation = ✅ COVERED (uncle is a risk flag in Part 3, not a quality miss)
  "address verified, rented" → Address = ✅ COVERED
{cond_lines}{banking_instr}
⚠️ OUTPUT FORMAT FOR PART 1: You MUST reproduce the table below with ALL [fill X] placeholders replaced. Do NOT use a bullet list.

{quality_table}

**Quality Checks Score: X/{QUALITY_MARKS}**
**Areas to Improve:** (list only the ❌ MISSED rows — 1 line each; skip N/R and banking-not-discussed rows)

---
PART 2 — DOCUMENTATION QUALITY ({TONE_MARKS} pts)
1. Completeness: all covered topics documented with specific values?
2. Clarity: actual numbers/amounts or vague language?
3. Structure: organised and easy to review?
4. Compliance: any red flags or missing disclosures?
**Documentation Score: X/{TONE_MARKS}**  **Verdict:** WELL DOCUMENTED / NEEDS IMPROVEMENT / POOR DOCUMENTATION

**OVERALL QUALITY SCORE: [Checks + Docs] = X/10**

---
PART 3 — RISK ASSESSMENT
{risk_table}

**Total FLAGS: [count]**
**Risk Level:** LOW / MEDIUM / HIGH
**Recommendation:** APPROVE / APPROVE WITH CONDITIONS / DECLINE
**Reason:** (one bullet per flagged row with actual value and reason)

---
PART 4 — SUMMARY
1. Quality: X/10 (checks X/{QUALITY_MARKS} + docs X/{TONE_MARKS}) — [strengths and gaps]
2. Banking: [Verified / Not mentioned / Partial]
3. Risk: [level] — [main factor or "clean profile"]
4. Key Concerns: [2–3 items with values, or "None"]
5. Decision: [APPROVE / CONDITIONS / DECLINE] — [specific reason with values]
"""

    return call_llm(prompt, _SYSTEM_SCORER, max_tokens=2200)


# ──────────────────────────────────────────────────────────────
# SCORE PD RECORDING — clean transcript + score in ONE LLM call
# ──────────────────────────────────────────────────────────────

def clean_and_score_recording(row: dict, raw_transcript: str) -> tuple[str, str]:
    """
    Combine transcript cleaning AND scoring into a SINGLE LLM call.
    Reduces per-recording API calls from 3 → 2 (Whisper + this).
    Returns (cleaned_transcript, score_markdown).
    """
    app_id       = row.get("app_id", "N/A")
    product_type = row.get("product_type", "Non FSF")
    caller       = row.get("caller", "")

    criteria_text = build_criteria_text(product_type)
    risk_text     = build_risk_factors_text()
    pts_each      = get_points_each(product_type)
    n_checks      = len(get_criteria(product_type))

    prompt = f"""You are a senior PD quality analyst at GrayQuest, an Indian education loan company.
Complete TWO tasks for this PD call recording.

**App ID:** {app_id} | **Product:** {product_type} | **Caller:** {caller}

---
## RAW WHISPER TRANSCRIPT (timestamped segments):

Each line = one Whisper segment. Format: [MM:SS–MM:SS] spoken text.
A GAP of 1.5 seconds or more between the end of one segment and the start of the next = likely speaker change.

{raw_transcript}

---
## TASK 1 — RECONSTRUCT THE DIALOGUE

You must assign EVERY segment to either [Caller] or [Customer].

**WHO IS THE CALLER (GrayQuest PD employee):**
- Introduces themselves as calling from GrayQuest / loan company
- ASKS verification questions: CIBIL, income, address, EMI, co-applicant, DPDs, admission, alternate number
- Uses: "verify karna tha", "confirm karna tha", "bata dijiye", "aapka naam", "kya relation hai"
- Controls the conversation — always the one starting a new topic
- Never gives their own personal/financial details
- Their turns tend to be LONGER (asking multiple things at once)

**WHO IS THE CUSTOMER (loan applicant / co-applicant):**
- ANSWERS the caller's questions with their own details
- Gives their name, address, income, CIBIL score, EMI amount, bank name
- Short, factual responses: "haan ji", "theek hai", numbers, amounts, names
- Asks about loan status / fees / approval
- Their turns tend to be SHORTER

**HOW TO USE TIMESTAMPS:**
- A gap ≥ 1.5s between segment end and next segment start = strong signal of speaker change
- Multiple consecutive segments with no gap = same speaker continuing
- If both speakers' content appears in one segment (audio bleed), split it at the natural question/answer boundary

**FORMATTING RULES:**
- Merge consecutive segments from the same speaker into one paragraph
- Add proper punctuation, natural sentence breaks
- Remove word repetitions caused by audio glitches; mark genuinely unclear audio as [unclear]
- Keep ALL Hindi/Hinglish — do NOT translate anything
- Do NOT skip or summarize any content

---
## TASK 2 — QUALITY & RISK SCORING

### Scoring Criteria for {product_type} ({n_checks} checks, {pts_each} pts each):
{criteria_text}

### Risk Factors:
{risk_text}

---
## YOUR RESPONSE — use EXACTLY this format:

## 📝 FORMATTED TRANSCRIPT

[Caller]: (first turn — they always open the call)

[Customer]: (response)

[Caller]: (next question / topic)

[Customer]: (response)

... continue for entire call ...

---
## 📊 QUALITY & RISK SCORECARD — App ID: {app_id}

### Quality Scorecard
| # | Parameter | Covered? | Finding from call | Points |
|---|-----------|----------|-------------------|--------|
(one row per parameter — ✅ covered / ❌ not covered)

**Quality Score: X/10**
**Areas to Improve:** (bullet list of missed/weak parameters)

### Tone & Communication
| Dimension | Observation |
|-----------|-------------|
| Professionalism | ... |
| Structure | ... |
| Empathy | ... |
| Completeness | ... |
**Tone Score: X/2**

### Risk Assessment
**Risk Flags:** (list each: 🔴 negative finding OR 🟢 clear)
**Risk Level:** 🟢 LOW / 🟡 MEDIUM / 🔴 HIGH
**Recommendation:** APPROVE / APPROVE WITH CONDITIONS / DECLINE
**Reason:** (cite specific values found in the call)

### Summary
One line: quality of this PD call + risk profile of this case."""

    full_response = call_llm(prompt, _SYSTEM_SCORER, max_tokens=4000)

    # Split response into transcript and scorecard sections
    if "## 📊 QUALITY & RISK SCORECARD" in full_response:
        parts     = full_response.split("## 📊 QUALITY & RISK SCORECARD")
        transcript_part = parts[0].replace("## 📝 FORMATTED TRANSCRIPT", "").strip()
        score_part      = "## 📊 QUALITY & RISK SCORECARD" + parts[1]
    else:
        # Fallback if LLM didn't split cleanly
        transcript_part = raw_transcript
        score_part      = full_response

    return transcript_part, score_part


# ──────────────────────────────────────────────────────────────
# BATCH SUMMARY (overall across all app IDs)
# ──────────────────────────────────────────────────────────────

_SYSTEM_SUMMARY = """You are a senior PD quality manager at GrayQuest, an Indian education loan company.
You are reviewing a batch of PD quality evaluations. Provide a concise management summary."""


def batch_summary(individual_scores: list[str], mode: str = "comment") -> str:
    """Given list of individual score texts, generate an overall team summary."""
    joined = "\n\n---\n\n".join(individual_scores)
    content_type = "comment" if mode == "comment" else "recording"
    prompt = f"""Below are individual PD {content_type} quality scores for multiple loan applications.

{joined}

---
Provide a detailed MANAGEMENT SUMMARY with the following sections:

## 📊 Batch Overview
- Total cases reviewed: X
- Quality scores: list each App ID with its score (e.g. App 123456: 7.5/10)
- Average quality score: X/10
- Risk distribution: X LOW / X MEDIUM / X HIGH
- Decisions: X APPROVE / X CONDITIONS / X DECLINE

## 🏆 Best Performing Cases
For each top performer: App ID, score, specific strengths (e.g. "covered CIBIL 750, income Rs.45k/mo, address verified")

## ⚠️ Cases Needing Attention
For each weak case: App ID, score, specific missing parameters, actual values found (e.g. "missed banking verification, CIBIL 580 < threshold")

## 🔴 Loan Decisions
For each DECLINE / CONDITIONS case:
- App ID, decision, and exact reason with values (e.g. "DECLINE — CIBIL 480, overdue Rs.65,000")
For APPROVE cases: brief confirmation (e.g. "App 123456 — APPROVE, clean CIBIL 780, no overdue")

## 📈 Team Improvement Areas
- List top 3 parameters most commonly missed across all cases
- Specific coaching points for the team (not generic — reference actual gaps observed)

## 🎯 Priority Actions
- Which cases need immediate review / escalation and why
- Any compliance concerns observed across the batch
"""
    return call_llm(prompt, _SYSTEM_SUMMARY, max_tokens=2000)


# ──────────────────────────────────────────────────────────────
# DATA FORMATTER (for chat context)
# ──────────────────────────────────────────────────────────────

def _fmt_pd_rows(rows: list[dict]) -> str:
    lines = []
    for row in rows:
        app_id = row.get("app_id") or row.get("id", "N/A")
        parts  = [f"App ID: {app_id}"]
        for k, label in [
            ("pd_caller_name",  "PD Caller"),
            ("pd_comment_date", "Comment Date"),
            ("product_type",    "Product"),
        ]:
            if row.get(k):
                parts.append(f"{label}: {row[k]}")
        comment = row.get("credit_pd_comment") or "No PD comment recorded"
        lines.append("  |  ".join(parts))
        lines.append(f"PD Comment:\n{comment}")
        lines.append("─" * 70)
    return "\n".join(lines)


def _fmt_collection_rows(rows: list[dict]) -> str:
    grouped: dict = defaultdict(list)
    meta: dict    = {}
    for row in rows:
        app_id = row.get("id")
        grouped[app_id].append((row.get("commented_on", ""), row.get("collection_comment", "")))
        if app_id not in meta:
            meta[app_id] = {k: row.get(k) for k in ("logged_date", "group_name", "location_name", "inst_name")}
    lines = []
    for app_id, comments in grouped.items():
        m = meta[app_id]
        parts = [f"App ID: {app_id}"]
        for k, label in [("logged_date", "Date"), ("group_name", "Group"), ("location_name", "Location"), ("inst_name", "Institute")]:
            if m.get(k): parts.append(f"{label}: {m[k]}")
        total = len(comments)
        comments = comments[-MAX_COMMENTS_PER_APP:]
        truncated = total - len(comments)
        lines.append("  |  ".join(parts))
        lines.append(f"Comments (showing {len(comments)} of {total}" + (f", {truncated} older omitted)" if truncated else ")") + ":")
        for date, comment in comments:
            lines.append(f"  • {'[' + str(date) + '] ' if date else ''}{comment}")
        lines.append("─" * 70)
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────
# CHAT / Q&A
# ──────────────────────────────────────────────────────────────

# Max characters of data context sent to chat (prevents token overflow)
_CHAT_CONTEXT_LIMIT  = 3000
# Max recent conversation turns kept (prevents history from growing too large)
_CHAT_HISTORY_TURNS  = 4   # = last 4 messages (2 user + 2 assistant)


def _trim_context(context: str) -> str:
    """Trim data context to fit within token budget for chat."""
    if len(context) <= _CHAT_CONTEXT_LIMIT:
        return context
    trimmed = context[:_CHAT_CONTEXT_LIMIT]
    # Cut at last complete line to avoid partial content
    last_newline = trimmed.rfind("\n")
    if last_newline > 0:
        trimmed = trimmed[:last_newline]
    return trimmed + f"\n\n[... {len(context) - _CHAT_CONTEXT_LIMIT} characters trimmed to fit token limit ...]"


def ask_question(
    question: str,
    data_context: str,
    chat_history: list[dict],
    category: str = "PD",
) -> str:
    """
    Answer a follow-up question about the fetched PD data.
    Keeps token usage low by:
      - Trimming data context to _CHAT_CONTEXT_LIMIT chars
      - Only keeping last _CHAT_HISTORY_TURNS messages from history
    """

    system = """You are an AI PD quality analyst at GrayQuest, an Indian education loan company.
You are given PD (Personal Discussion) data including comments, caller names, app IDs, product types, and quality scores.
Answer questions clearly and concisely based ONLY on the data provided.
Always reference specific App IDs and caller names in your answers.
If the answer is not in the data, say so clearly — never make things up."""

    # Trim context to safe size
    trimmed_context = _trim_context(data_context)

    # Keep only the last N history messages
    recent_history = chat_history[-_CHAT_HISTORY_TURNS:] if len(chat_history) > _CHAT_HISTORY_TURNS else chat_history

    messages = [
        {
            "role": "system",
            "content": system
        },
        {
            "role": "user",
            "content": (
                f"Here is the PD data to answer questions about:\n\n"
                f"{trimmed_context}\n\n"
                f"I will now ask you questions about this data."
            )
        },
        {
            "role": "assistant",
            "content": "Got it. I have reviewed the PD data and I'm ready to answer your questions."
        },
    ]

    # Append trimmed history
    for turn in recent_history:
        messages.append({"role": turn["role"], "content": turn["content"]})

    # Append new question
    messages.append({"role": "user", "content": question})

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type":  "application/json"
    }
    payload = {
        "model":       GROQ_MODEL,
        "messages":    messages,
        "temperature": 0.2,
        "max_tokens":  768,    # kept small — chat answers should be concise
    }

    try:
        resp = requests.post(
            GROQ_CHAT_ENDPOINT,
            json=payload,
            headers=headers,
            timeout=GROQ_TIMEOUT
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    except requests.exceptions.HTTPError as exc:
        if exc.response.status_code == 429:
            return (
                "⏳ Rate limit reached. Please wait **20–30 seconds** and ask again.\n\n"
                "_Tip: The chat uses the same Groq free tier as scoring. "
                "If you just ran a large analysis, wait a moment before chatting._"
            )
        if exc.response.status_code == 401:
            return "❌ Invalid Groq API key. Please check `GROQ_API_KEY` in config.py."
        return f"❌ Groq API Error ({exc.response.status_code}): {exc.response.text}"
    except requests.exceptions.ConnectionError:
        return "❌ No internet connection. Please check your network."
    except Exception as exc:
        return f"❌ Unexpected error: {exc}"
