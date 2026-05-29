"""
PD Scoring Criteria
--------------------
Quality checks and risk factors per product type (FSF / Non-FSF / EdTech).

Quality Score  -> evaluates the PD CALLER (did they cover all parameters?)
Risk Score     -> evaluates the LOAN CASE (are actual values bad?)

Conditional checks (CIBIL / Overdue / DPD):
  - Only required for caller to discuss when system data shows a bad value
  - If system data is clean -> auto-pass as N/R (Not Required), full points
"""

# ── Thresholds per product type ───────────────────────────────
FSF_CIBIL_MIN       = 650
FSF_OVERDUE_MAX     = 30_000      # Rs.30,000

NFSF_CIBIL_MIN      = 700
NFSF_OVERDUE_MAX    = 15_000      # Rs.15,000

EDTECH_CIBIL_MIN    = 700
EDTECH_OVERDUE_MAX  = 15_000      # Rs.15,000

# ── Shared risk thresholds ────────────────────────────────────
FOIR_MAX            = 70          # FOIR < 70% is acceptable; ≥ 70% = risk flag

# ── CIBIL ignore rule (all product types) ────────────────────
# CIBIL < CIBIL_IGNORE_BELOW  →  completely IGNORE (no credit file / placeholder value)
#   - Do NOT ask in PD call  — not required
#   - Do NOT flag as risk    — exclude from risk table
#   - Do NOT count in denominator for quality score
# CIBIL >= CIBIL_IGNORE_BELOW AND < threshold  →  REQUIRED (must cover in call)
# CIBIL >= threshold          →  N/R (system clean, auto-pass, exclude from denominator)
CIBIL_IGNORE_BELOW  = 10

# ── Quality score structure ───────────────────────────────────
TONE_MARKS          = 2           # Fixed 2 pts for tone / documentation
QUALITY_MARKS       = 8           # Distributed only across ACTIVE params (not N/R / IGNORE)


# ── FSF Criteria (9 quality checks) ──────────────────────────
FSF_CRITERIA = [
    {
        "parameter": "Student Type",
        "verify_question": "New or existing admission?",
        "positive": "Caller asked and noted whether student is new or existing admission",
        "negative": "Caller never asked about student type / admission status not discussed",
        "risk_note": "New admission = risk flag in Part 3",
        "conditional": False,
    },
    {
        "parameter": "Co-applicant Relation",
        "verify_question": "Relation to student? (Father/Mother preferred)",
        "positive": "Caller asked and noted co-applicant's relationship to student",
        "negative": "Caller never asked co-applicant relation / topic absent from PD",
        "risk_note": "Distant relation (uncle/aunt/cousin) = risk flag in Part 3",
        "conditional": False,
    },
    {
        "parameter": "Address / Residence",
        "verify_question": "Residential address + owned or rented?",
        "positive": "Caller asked and noted address with ownership status (owned/rented)",
        "negative": "Caller never asked about address / residence not discussed",
        "risk_note": "Rented or mismatch with system address = risk flag in Part 3",
        "conditional": False,
    },
    {
        "parameter": "Work Status / Income",
        "verify_question": "Work type + monthly income amount?",
        "positive": "Caller asked and noted work status and income source/amount",
        "negative": "Caller never asked about work or income / topic absent from PD",
        "risk_note": "Unemployed or unverifiable income = risk flag in Part 3",
        "conditional": False,
    },
    {
        "parameter": "CIBIL Score",
        "verify_question": "CIBIL score? (IGNORE if <10 / N/R if >=650 / FLAG if 10-649)",
        "positive": "Caller asked and noted CIBIL score (N/R if >=650; IGNORE if <10 — no credit file)",
        "negative": "Caller never asked about CIBIL / topic absent from PD",
        "risk_note": "CIBIL 10-649 = risk flag | CIBIL <10 = ignore (no credit history)",
        "conditional": True,
        "system_field": "cibil_score",
        "system_threshold": FSF_CIBIL_MIN,
        "threshold_direction": "min",
    },
    {
        "parameter": "Overdue Amount",
        "verify_question": "Any overdue? (threshold < Rs.30k)",
        "positive": "Caller asked and noted overdue status (or N/R if system overdue < Rs.30k)",
        "negative": "Caller never asked about overdue / topic absent from PD",
        "risk_note": "Overdue > Rs.30,000 = risk flag in Part 3",
        "conditional": True,
        "system_field": "overdue_amount",
        "system_threshold": FSF_OVERDUE_MAX,
        "threshold_direction": "max",
    },
    {
        "parameter": "DPDs (Days Past Due)",
        "verify_question": "Any DPDs? (should be 0)",
        "positive": "Caller asked and noted DPD status (or N/R if system DPD = 0)",
        "negative": "Caller never asked about DPDs / topic absent from PD",
        "risk_note": "DPDs present = risk flag in Part 3",
        "conditional": True,
        "system_field": "gq_dpd_days",
        "system_threshold": 0,
        "threshold_direction": "exact_zero",
    },
    {
        "parameter": "Alternate Contact Number",
        "verify_question": "Alternate contact (spouse/parent)?",
        "positive": "Caller collected alternate contact number (spouse / parent)",
        "negative": "Alternate contact number not collected / same as applicant number",
        "conditional": False,
    },
    {
        "parameter": "Risk Factors Check",
        "verify_question": "Divorce / single parent / GQ DPDs / consent pending?",
        "positive": "Caller checked for risk factors (divorce, consent, GQ DPDs) and noted findings",
        "negative": "Caller never checked or mentioned any risk factor topics",
        "risk_note": "Divorced / single parent / GQ DPDs / consent pending = risk flags in Part 3",
        "conditional": False,
    },
]


# ── Non-FSF Criteria (13 quality checks) ─────────────────────
NFSF_CRITERIA = [
    {
        "parameter": "Student Type",
        "verify_question": "New or existing admission?",
        "positive": "Caller asked and noted whether student is new or existing admission",
        "negative": "Caller never asked about student type / admission status not discussed",
        "risk_note": "New admission = risk flag in Part 3",
        "conditional": False,
    },
    {
        "parameter": "Co-applicant Relation",
        "verify_question": "Relation to student? (Father/Mother only)",
        "positive": "Caller asked and noted co-applicant's relationship to student",
        "negative": "Caller never asked co-applicant relation / topic absent from PD",
        "risk_note": "Non-parent relation (uncle/aunt/brother/sister/cousin) = risk flag in Part 3",
        "conditional": False,
    },
    {
        "parameter": "Address / Residence",
        "verify_question": "Residential address + owned or rented?",
        "positive": "Caller asked and noted address with ownership status (owned/rented)",
        "negative": "Caller never asked about address / residence not discussed",
        "risk_note": "Rented or mismatch with CIBIL address = risk flag in Part 3",
        "conditional": False,
    },
    {
        "parameter": "Work Status / Income",
        "verify_question": "Work type + monthly income amount?",
        "positive": "Caller asked and noted work status and income source/amount",
        "negative": "Caller never asked about work or income / topic absent from PD",
        "risk_note": "Unemployed or unverifiable income = risk flag in Part 3",
        "conditional": False,
    },
    {
        "parameter": "CIBIL Score",
        "verify_question": "CIBIL score? (N/R if >=700 / FLAG if <700 or no file)",
        "positive": "Caller asked and noted CIBIL score (N/R if >=700; <700 or no credit file = must ask and flag)",
        "negative": "Caller never asked about CIBIL / topic absent from PD",
        "risk_note": "CIBIL <700 (including no credit file) = risk flag",
        "conditional": True,
        "system_field": "cibil_score",
        "system_threshold": NFSF_CIBIL_MIN,
        "threshold_direction": "min",
    },
    {
        "parameter": "Overdue Amount",
        "verify_question": "Any overdue? (N/R if 0 / FLAG if > Rs.15k)",
        "positive": "Caller asked and noted overdue status (or N/R if system overdue < Rs.15k)",
        "negative": "Caller never asked about overdue / topic absent from PD",
        "risk_note": "Overdue > Rs.15,000 = risk flag in Part 3",
        "conditional": True,
        "system_field": "overdue_amount",
        "system_threshold": NFSF_OVERDUE_MAX,
        "threshold_direction": "max",
    },
    {
        "parameter": "DPDs (Days Past Due)",
        "verify_question": "Any DPDs? (N/R if 0 / FLAG if > 0)",
        "positive": "Caller asked and noted DPD status (or N/R if system DPD = 0)",
        "negative": "Caller never asked about DPDs / topic absent from PD",
        "risk_note": "DPDs present = risk flag in Part 3",
        "conditional": True,
        "system_field": "gq_dpd_days",
        "system_threshold": 0,
        "threshold_direction": "exact_zero",
    },
    {
        "parameter": "Obligations vs Income",
        "verify_question": "Total EMI obligations vs income ratio?",
        "positive": "Caller collected banking and noted total obligations vs income/credits",
        "negative": "Banking not collected / obligations vs income not discussed",
        "conditional": False,
        "requires_banking": True,
    },
    {
        "parameter": "Average Monthly Credits",
        "verify_question": "Avg monthly credits > GQ EMI?",
        "positive": "Caller collected banking, avg monthly credits > GQ EMI",
        "negative": "Banking not shared OR avg credits < GQ EMI",
        "conditional": False,
        "requires_banking": True,
    },
    {
        "parameter": "Salary Mapping",
        "verify_question": "Regular salary credits last 3 months?",
        "positive": "Caller collected banking, regular salary credits for last 3 months confirmed",
        "negative": "Banking not shared OR cannot trace salary in banking",
        "conditional": False,
        "requires_banking": True,
    },
    {
        "parameter": "High Value Credits",
        "verify_question": "Unexplained high credits explained?",
        "positive": "Caller collected banking, high value credits explained (business / family)",
        "negative": "Banking not shared OR unexplained high credits / only loan disbursements",
        "conditional": False,
        "requires_banking": True,
    },
    {
        "parameter": "ABB (Average Bank Balance)",
        "verify_question": "Average bank balance > GQ EMI?",
        "positive": "Caller collected banking, ABB > GQ EMI",
        "negative": "Banking not shared OR ABB < GQ EMI",
        "conditional": False,
        "requires_banking": True,
    },
    {
        "parameter": "Alternate Contact Number",
        "verify_question": "Alternate contact (spouse/parent)?",
        "positive": "Caller collected alternate contact number (spouse / parent)",
        "negative": "Alternate contact number not collected / same as applicant number",
        "conditional": False,
    },
]


# ── EdTech Criteria (12 quality checks) ──────────────────────
EDTECH_CRITERIA = [
    {
        "parameter": "Student Type / Institute",
        "verify_question": "New/existing admission + institute confirmed?",
        "positive": "Caller asked and noted student type (new/existing) and confirmed institute",
        "negative": "Caller never asked about student type or institute / topic absent from PD",
        "risk_note": "New admission = risk flag in Part 3",
        "conditional": False,
    },
    {
        "parameter": "Co-applicant Relation",
        "verify_question": "Relation to student?",
        "positive": "Caller asked and noted co-applicant's relationship to student",
        "negative": "Caller never asked co-applicant relation / topic absent from PD",
        "risk_note": "Uncle/aunt/cousin = risk flag in Part 3",
        "conditional": False,
    },
    {
        "parameter": "Address / Residence",
        "verify_question": "Residential address + owned or rented?",
        "positive": "Caller asked and noted address with ownership status (owned/rented)",
        "negative": "Caller never asked about address / residence not discussed",
        "risk_note": "Rented or mismatch with CIBIL address = risk flag in Part 3",
        "conditional": False,
    },
    {
        "parameter": "Work Status / Income",
        "verify_question": "Work type + monthly income amount?",
        "positive": "Caller asked and noted work status and income source/amount",
        "negative": "Caller never asked about work or income / topic absent from PD",
        "risk_note": "Unemployed or unverifiable income = risk flag in Part 3",
        "conditional": False,
    },
    {
        "parameter": "CIBIL Score",
        "verify_question": "CIBIL score? (N/R if >=700 / FLAG if <700 or no file)",
        "positive": "Caller asked and noted CIBIL score (N/R if >=700; <700 or no credit file = must ask and flag)",
        "negative": "Caller never asked about CIBIL / topic absent from PD",
        "risk_note": "CIBIL <700 (including no credit file) = risk flag",
        "conditional": True,
        "system_field": "cibil_score",
        "system_threshold": EDTECH_CIBIL_MIN,
        "threshold_direction": "min",
    },
    {
        "parameter": "Overdue Amount",
        "verify_question": "Any overdue? (N/R if 0 / FLAG if > Rs.15k)",
        "positive": "Caller asked and noted overdue status (or N/R if system overdue < Rs.15k)",
        "negative": "Caller never asked about overdue / topic absent from PD",
        "risk_note": "Overdue > Rs.15,000 = risk flag in Part 3",
        "conditional": True,
        "system_field": "overdue_amount",
        "system_threshold": EDTECH_OVERDUE_MAX,
        "threshold_direction": "max",
    },
    {
        "parameter": "DPDs (Days Past Due)",
        "verify_question": "Any DPDs? (N/R if 0 / FLAG if > 0)",
        "positive": "Caller asked and noted DPD status (or N/R if system DPD = 0)",
        "negative": "Caller never asked about DPDs / topic absent from PD",
        "risk_note": "DPDs present = risk flag in Part 3",
        "conditional": True,
        "system_field": "gq_dpd_days",
        "system_threshold": 0,
        "threshold_direction": "exact_zero",
    },
    {
        "parameter": "Obligations vs Income",
        "verify_question": "Total EMI obligations vs income?",
        "positive": "Caller collected banking and noted total obligations vs income/credits",
        "negative": "Banking not collected / obligations vs income not discussed",
        "conditional": False,
        "requires_banking": True,
    },
    {
        "parameter": "Average Monthly Credits",
        "verify_question": "Avg monthly credits > GQ EMI?",
        "positive": "Caller collected banking, avg monthly credits > GQ EMI",
        "negative": "Banking not shared OR avg credits < GQ EMI",
        "conditional": False,
        "requires_banking": True,
    },
    {
        "parameter": "Salary Mapping",
        "verify_question": "Regular salary credits last 3 months?",
        "positive": "Caller collected banking, regular salary credits for last 3 months confirmed",
        "negative": "Banking not shared OR cannot trace salary in banking",
        "conditional": False,
        "requires_banking": True,
    },
    {
        "parameter": "ABB (Average Bank Balance)",
        "verify_question": "Average bank balance > GQ EMI?",
        "positive": "Caller collected banking, ABB > GQ EMI",
        "negative": "Banking not shared OR ABB < GQ EMI",
        "conditional": False,
        "requires_banking": True,
    },
    {
        "parameter": "Alternate Contact Number",
        "verify_question": "Alternate contact (spouse/parents)?",
        "positive": "Caller collected alternate contact number (spouse / parents)",
        "negative": "Alternate contact number not collected / same as applicant number",
        "conditional": False,
    },
]


# ── Risk Factors (common to all product types) ────────────────
RISK_FACTORS = [
    "Divorced co-applicant",
    "Single parent household",
    "Existing GQ DPDs (overdue with GrayQuest in another loan)",
    "Overdue in another loan ID",
    "Consent pending with parent / guardian",
    "Co-applicant is distant relative (uncle/aunt/cousin)",
]


# ── Helpers ───────────────────────────────────────────────────

def get_criteria(product_type: str) -> list:
    mapping = {
        "FSF":     FSF_CRITERIA,
        "Non FSF": NFSF_CRITERIA,
        "Non-FSF": NFSF_CRITERIA,
        "EdTech":  EDTECH_CRITERIA,
        "Edtech":  EDTECH_CRITERIA,
    }
    return mapping.get(product_type, NFSF_CRITERIA)


def get_points_each(product_type: str) -> float:
    """Points per quality check (8 pts / number of checks, NOT including banking if absent)."""
    return round(QUALITY_MARKS / len(get_criteria(product_type)), 2)


def get_banking_param_count(product_type: str) -> int:
    """How many params require banking statement for this product type."""
    return sum(1 for c in get_criteria(product_type) if c.get("requires_banking"))


def get_quality_pts_without_banking(product_type: str) -> float:
    """Points per check when banking params are excluded from denominator."""
    n_all = len(get_criteria(product_type))
    n_bank = get_banking_param_count(product_type)
    n_scored = n_all - n_bank
    if n_scored <= 0:
        return round(QUALITY_MARKS / n_all, 2)
    return round(QUALITY_MARKS / n_scored, 2)


def build_criteria_text(product_type: str) -> str:
    """Compact one-line-per-parameter format to stay within Groq token limits."""
    criteria = get_criteria(product_type)
    pts_each = get_points_each(product_type)
    lines = []
    for i, c in enumerate(criteria, 1):
        if c.get("conditional"):
            tag = " [N/R if system data clean]"
        elif c.get("requires_banking"):
            tag = " [BANKING: award pts ONLY if caller collected banking statement]"
        else:
            tag = ""
        risk = f" | NOTE: {c['risk_note']}" if c.get("risk_note") else ""
        lines.append(
            f"{i}. **{c['parameter']}** ({pts_each}pts){tag} -- "
            f"COVERED: {c['positive']} | MISSED: {c['negative']}{risk}"
        )
    return "\n".join(lines)


def build_quality_table_template(
    product_type: str,
    conditional_notes: dict = None,
    banking_discussed: bool | None = None,
) -> str:
    """
    Build a quality scorecard table template for the LLM prompt.
    Columns: # | Parameter | What to Verify | Covered? | Value Found | Points

    Pre-filled by Python:
      - # (row number)
      - Parameter (name)
      - What to Verify (verify_question from criteria)
      - N/R rows: Covered? = "N/R ✅" and Points pre-filled

    LLM fills (shown as [fill X] placeholders):
      - Covered? = ✅ / ❌
      - Value Found = exact value from transcript / comment
      - Points = numeric score
    """
    criteria    = get_criteria(product_type)
    n_total     = len(criteria)
    n_banking   = get_banking_param_count(product_type)
    cond        = conditional_notes or {}

    # ── Dynamic denominator ───────────────────────────────────
    # N/R and IGNORE params are excluded from the 8-pt quality pool.
    # Only "active" params (params the caller actually needs to ask) count.
    n_excluded  = sum(1 for v in cond.values() if v.startswith(("N/R", "IGNORE")))
    n_active    = n_total - n_excluded           # params that need active asking
    n_active_no_bank = n_active - n_banking      # active non-banking params

    # pts per active param (when banking discussed)
    pts_active  = round(QUALITY_MARKS / n_active, 2)      if n_active > 0      else round(QUALITY_MARKS / n_total, 2)
    # pts per active non-banking param (when banking not discussed)
    pts_no_bank = round(QUALITY_MARKS / n_active_no_bank, 2) if n_active_no_bank > 0 else pts_active

    header = (
        "| # | Parameter | What to Verify | Covered? | Value Found | Points |\n"
        "|---|-----------|----------------|----------|-------------|--------|\n"
    )

    rows = []
    for i, c in enumerate(criteria, 1):
        param = c["parameter"]
        what  = c.get("verify_question", c["positive"])
        note  = cond.get(param, "")

        if note.startswith("IGNORE"):
            # CIBIL < 10 — completely excluded (no credit file)
            rows.append(
                f"| {i} | {param} | {what} | IGNORE ⬜ | No credit file | N/A |"
            )
        elif note.startswith("N/R"):
            # System data clean — auto-pass, excluded from denominator
            rows.append(
                f"| {i} | {param} | {what} | N/R ✅ | System clean | N/A |"
            )
        elif c.get("requires_banking"):
            # Banking param — LLM fills based on whether banking was discussed
            rows.append(
                f"| {i} | {param} | {what} | [✅/❌/NA] | [value or not discussed] | [{pts_active}/0/NA] |"
            )
        else:
            # Active param — LLM fills
            rows.append(
                f"| {i} | {param} | {what} | [✅/❌] | [value] | [{pts_active}/0] |"
            )

    # Summary line showing the effective denominator
    excluded_label = f" ({n_excluded} excluded)" if n_excluded > 0 else ""
    instructions = (
        f"\nDenominator: {n_active} params{excluded_label} × {pts_active} pts = {QUALITY_MARKS} max\n"
        "Replace every [fill] cell. Keep N/R and IGNORE rows unchanged."
    )

    return header + "\n".join(rows) + instructions


def build_risk_factors_text() -> str:
    return "\n".join(f"- {r}" for r in RISK_FACTORS)


def build_risk_scoring_table(product_type: str, system_data: dict = None) -> str:
    """
    Risk assessment table.

    ALL system-data fields (CIBIL, Overdue, DPD, Gender, Work, FOIR) are pre-computed
    in Python — value AND flag already filled before sending to LLM.

    Transcript-only fields (address ownership, co-applicant relation, admission status,
    divorce, consent) — LLM extracts value from transcript and decides flag.

    Column: Value (DB/Call) = whatever is available (DB first, call if not in DB).
    0 FLAGS = APPROVE | 1 FLAG = APPROVE WITH CONDITIONS | 2+ FLAGS = DECLINE
    ⬜ IGNORE and ⚠️ NOTE rows do NOT count toward flag total.
    """
    sd = system_data or {}

    cibil_val   = sd.get("cibil_score")
    overdue_val = sd.get("overdue_amount")
    dpd_val     = sd.get("gq_dpd_days")
    income_val  = sd.get("monthly_income")
    work_val    = sd.get("work_status", "") or ""
    foir_val    = sd.get("foir")
    addr_val    = sd.get("system_address", "") or ""
    gender_val  = sd.get("gender", "") or ""

    # ── Pre-compute all system-data flags ────────────────────────

    def _cibil_row(threshold: int) -> tuple[str, str]:
        if cibil_val is None:
            return "—", "—"
        v = float(cibil_val)
        disp = str(int(v))
        # IGNORE (no credit file) only applies to FSF
        # Non-FSF / EdTech: CIBIL < threshold (including -1) = 🚩 FLAG — must ask in call
        is_fsf = product_type in ("FSF",)
        if is_fsf and int(v) < CIBIL_IGNORE_BELOW:
            return disp, f"⬜ IGNORE  (no credit file — not required for FSF)"
        if v >= threshold:
            return disp, f"✅ PASS  ({int(v)} ≥ {threshold})"
        return disp, f"🚩 FLAG  ({int(v)} < {threshold})"

    def _overdue_row(threshold: int) -> tuple[str, str]:
        if overdue_val is None:
            return "—", "—"
        v = float(overdue_val)
        disp = f"Rs.{int(v):,}"
        if v <= threshold:
            return disp, f"✅ PASS  (Rs.{int(v):,} ≤ Rs.{threshold:,})"
        return disp, f"🚩 FLAG  (Rs.{int(v):,} > Rs.{threshold:,})"

    def _dpd_row() -> tuple[str, str]:
        if dpd_val is None:
            return "—", "—"
        v = float(dpd_val)
        if v == 0:
            return "0", "✅ PASS  (no DPDs)"
        return str(int(v)), f"🚩 FLAG  ({int(v)} days past due)"

    def _gender_row() -> tuple[str, str]:
        if not gender_val:
            return "—", "—"
        gl = gender_val.lower().strip()
        if "male" in gl and "female" not in gl:
            return gender_val, "✅ PASS  (Male — preferred)"
        return gender_val, "⚠️ NOTE  (Female — informational)"

    def _work_row() -> tuple[str, str]:
        inc = f"Rs.{int(float(income_val)):,}/mo" if income_val else "—"
        if not work_val:
            return inc, "—"
        wl = work_val.lower()
        label = f"{inc} ({work_val})"
        # Check no-income / negative cases FIRST to avoid substring false-matches
        if any(k in wl for k in ("unemployed", "housewife", "retired", "student", "no income")):
            return label, "🚩 FLAG  (No active income)"
        if any(k in wl for k in ("self-employed", "self employed", "selfemployed", "business", "proprietor", "freelance")):
            return label, "⚠️ NOTE  (Self-employed — verify income stability)"
        if any(k in wl for k in ("salaried", "salary", "employed", "job", "service", "govt")):
            return label, "✅ PASS  (Salaried — preferred)"
        return label, "—"

    def _foir_row() -> tuple[str, str]:
        if foir_val is None:
            return "—", "—"
        try:
            v = float(foir_val)
        except (ValueError, TypeError):
            return "—", "—"
        disp = f"{v}%"
        if v < FOIR_MAX:
            return disp, f"✅ PASS  ({v}% < {FOIR_MAX}%)"
        return disp, f"🚩 FLAG  ({v}% ≥ {FOIR_MAX}%)"

    # ── Instruction header ────────────────────────────────────────
    instructions = (
        "Pre-filled Flag rows (✅/🚩/⚠️/⬜): do NOT change (from DB).\n"
        "Flag '—' rows: extract from transcript → ✅ PASS / 🚩 FLAG / ⚠️ NOTE / 'Not mentioned'\n"
        "⬜ IGNORE + ⚠️ NOTE = do NOT count toward flags. 0🚩=APPROVE | 1🚩=CONDITIONS | 2+🚩=DECLINE\n\n"
    )

    # ── FSF ───────────────────────────────────────────────────────
    if product_type in ("FSF",):
        cibil_v, cibil_f  = _cibil_row(FSF_CIBIL_MIN)
        over_v,  over_f   = _overdue_row(FSF_OVERDUE_MAX)
        dpd_v,   dpd_f    = _dpd_row()
        gen_v,   gen_f    = _gender_row()
        work_v,  work_f   = _work_row()
        foir_v,  foir_f   = _foir_row()
        addr_ref = addr_val or "—"

        return instructions + (
            f"| # | Parameter | Good / Threshold | Value (DB/Call) | Flag |\n"
            f"|---|-----------|-----------------|-----------------|------|\n"
            f"| 1 | CIBIL Score | ≥ {FSF_CIBIL_MIN} (ignore if <{CIBIL_IGNORE_BELOW}) | {cibil_v} (DB) | {cibil_f} |\n"
            f"| 2 | Overdue Amount | < Rs.30,000 | {over_v} (DB) | {over_f} |\n"
            f"| 3 | DPD (Days Past Due) | = 0 | {dpd_v} (DB) | {dpd_f} |\n"
            f"| 4 | Gender | Male preferred | {gen_v} (DB) | {gen_f} |\n"
            f"| 5 | Work Status / Income | Salaried preferred | {work_v} (DB) | {work_f} |\n"
            f"| 6 | FOIR | < {FOIR_MAX}% | {foir_v} (DB) | {foir_f} |\n"
            f"| 7 | Address / Ownership | Owned preferred | DB:{addr_ref} → extract owned/rented | — |\n"
            f"| 8 | Co-applicant Relation | Father/Mother/Bro/Sis | extract from call | — |\n"
            f"| 9 | Admission Status | Existing enrolled | extract from call | — |\n"
            f"| 10 | Divorced / Single parent | No | extract from call | — |\n"
            f"| 11 | Consent (if minor) | Obtained / N/A | extract from call | — |\n\n"
            f"Rows 7-11: 7=✅owned/🚩rented/⚠️joint | 8=✅father-mother-bro-sis/🚩uncle-cousin | 9=✅existing/🚩new | 10=✅none/🚩divorced | 11=✅obtained/🚩pending\n"
            f"Total 🚩: __ → LOW(0) / MEDIUM(1) / HIGH(2+)"
        )

    # ── Non-FSF / EdTech ─────────────────────────────────────────
    is_nfsf   = product_type in ("Non FSF", "Non-FSF")
    cibil_t   = NFSF_CIBIL_MIN if is_nfsf else EDTECH_CIBIL_MIN
    over_t    = NFSF_OVERDUE_MAX if is_nfsf else EDTECH_OVERDUE_MAX
    rel_rule  = "Father/Mother only (strict)" if is_nfsf else "Father/Mother/Bro/Sis/Self"
    over_lbl  = f"Rs.{over_t // 1000}k"

    cibil_v, cibil_f  = _cibil_row(cibil_t)
    over_v,  over_f   = _overdue_row(over_t)
    dpd_v,   dpd_f    = _dpd_row()
    foir_v,  foir_f   = _foir_row()
    gen_v,   gen_f    = _gender_row()
    work_v,  work_f   = _work_row()
    addr_ref = addr_val or "—"

    return instructions + (
        f"| # | Parameter | Good / Threshold | Value (DB/Call) | Flag |\n"
        f"|---|-----------|-----------------|-----------------|------|\n"
        f"| 1 | CIBIL Score | ≥ {cibil_t} (no file = FLAG) | {cibil_v} (DB) | {cibil_f} |\n"
        f"| 2 | Overdue Amount | < {over_lbl} | {over_v} (DB) | {over_f} |\n"
        f"| 3 | DPD (Days Past Due) | = 0 | {dpd_v} (DB) | {dpd_f} |\n"
        f"| 4 | FOIR | < {FOIR_MAX}% | {foir_v} (DB) | {foir_f} |\n"
        f"| 5 | Gender | Male preferred | {gen_v} (DB) | {gen_f} |\n"
        f"| 6 | Work Status / Income | Salaried preferred | {work_v} (DB) | {work_f} |\n"
        f"| 7 | Address / Ownership | Owned preferred | DB:{addr_ref} → extract owned/rented | — |\n"
        f"| 8 | Co-applicant Relation | {rel_rule} | extract from call | — |\n"
        f"| 9 | Admission Status | Existing enrolled | extract from call | — |\n"
        f"| 10 | Avg Monthly Credits | > GQ EMI | extract from banking if discussed | — |\n"
        f"| 11 | Salary Mapping | Regular 3-month credits | extract from banking if discussed | — |\n"
        f"| 12 | ABB (Avg Bank Balance) | > GQ EMI | extract from banking if discussed | — |\n"
        f"| 13 | Divorced / Single parent | No | extract from call | — |\n"
        f"| 14 | Consent (if minor) | Obtained / N/A | extract from call | — |\n\n"
        f"Rows 7-14: 7=✅owned/🚩rented/⚠️joint | 8=✅{rel_rule}/🚩uncle-cousin | 9=✅existing/🚩new | 10-12=✅banking OK/🚩insufficient/⚠️not discussed | 13=✅none/🚩divorced | 14=✅obtained/🚩pending\n"
        f"Total 🚩: __ → LOW(0) / MEDIUM(1) / HIGH(2+)"
    )


def get_conditional_notes(product_type: str, system_data: dict) -> dict:
    """
    Returns per-parameter status for quality scoring:
      IGNORE   = CIBIL < CIBIL_IGNORE_BELOW (no credit file) → exclude from scoring + risk, do not ask
      N/R      = system data clean → exclude from denominator, auto-pass
      REQUIRED = system data bad   → caller must have covered it
    """
    if not system_data:
        return {}

    notes = {}
    for c in get_criteria(product_type):
        if not c.get("conditional"):
            continue
        field     = c["system_field"]
        threshold = c["system_threshold"]
        direction = c["threshold_direction"]
        param     = c["parameter"]

        raw = system_data.get(field)
        if raw is None:
            continue
        try:
            val = float(raw)
        except (ValueError, TypeError):
            continue

        if direction == "min":
            is_fsf = product_type in ("FSF",)
            # CIBIL IGNORE rule: FSF only — no credit file means not required to ask.
            # Non-FSF / EdTech: CIBIL < 10 (no credit file / -1) is still a risk flag — caller MUST ask.
            if is_fsf and int(val) < CIBIL_IGNORE_BELOW:
                notes[param] = (
                    f"IGNORE -- CIBIL={int(val)} (< {CIBIL_IGNORE_BELOW}, no credit file). "
                    f"FSF only: do NOT ask. Exclude from scoring AND risk table."
                )
            elif val >= threshold:
                notes[param] = f"N/R -- system {field}={int(val)} (>= {int(threshold)}). Exclude from denominator."
            else:
                notes[param] = f"REQUIRED -- system {field}={int(val)} (< threshold {int(threshold)}). Caller must have asked."
        elif direction == "max":
            if val <= threshold:
                notes[param] = f"N/R -- system {field}=Rs.{int(val):,} (< Rs.{int(threshold):,}). Exclude from denominator."
            else:
                notes[param] = f"REQUIRED -- system {field}=Rs.{int(val):,} (> Rs.{int(threshold):,}). Caller must have asked."
        elif direction == "exact_zero":
            if val == 0:
                notes[param] = f"N/R -- system DPD=0. Exclude from denominator."
            else:
                notes[param] = f"REQUIRED -- system DPD={int(val)} days. Caller must have asked."

    return notes
