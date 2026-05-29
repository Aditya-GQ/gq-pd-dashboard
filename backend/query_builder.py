"""
Dynamic SQL Query Builder
--------------------------
Builds SQL for PD comments and PD recordings.

PD Comment filters:
    app_ids      : list[int]          (optional)
    date_from    : str  YYYY-MM-DD    (filters on PD comment date, not app logged date)
    date_to      : str  YYYY-MM-DD
    product_type : str  FSF | Non FSF | EdTech | All

PD Recording filters:
    app_ids      : list[int]          (optional)
    date_from    : str  YYYY-MM-DD
    date_to      : str  YYYY-MM-DD
    product_type : str  FSF | Non FSF | EdTech | All

System Profile data:
    build_system_data_query(app_ids) → CIBIL, overdue, DPD, income, work status
    Used for context-aware conditional quality scoring.
"""

import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import PD_TEAM_IAM_GROUP_ID


# ──────────────────────────────────────────────────────────────
# LOOKUP  — populate product type dropdown (no longer needs
#           group/location/inst dropdowns on PD Comment page)
# ──────────────────────────────────────────────────────────────

def get_lookup_query() -> str:
    """Still used by recording page for any future group filters."""
    return """
SELECT DISTINCT
    gigm.group_name,  gigm.group_id,
    giim.inst_name,   giim.inst_id,
    gilm.location_name, gilm.location_id
FROM institutes i
LEFT JOIN gq_internal_group_master gigm ON gigm.group_id = i.group_id
LEFT JOIN gq_internal_institute_master giim ON giim.inst_id = i.inst_id
LEFT JOIN gq_internal_location_master gilm ON gilm.location_id = i.location_id
WHERE i.status = 1 AND gigm.group_id IS NOT NULL
ORDER BY gigm.group_name
""".strip()


# ──────────────────────────────────────────────────────────────
# PRODUCT TYPE CASE  (shared)
# ──────────────────────────────────────────────────────────────

_PRODUCT_CASE = """CASE
        WHEN i.platform LIKE '%EdTech%' THEN 'EdTech'
        WHEN i.retention_percent > 0    THEN 'FSF'
        ELSE 'Non FSF'
    END AS product_type"""


# ──────────────────────────────────────────────────────────────
# PD COMMENT QUERY  (uses CTE for caller name + comment date)
# ──────────────────────────────────────────────────────────────

def build_pd_query(filters: dict) -> str:
    """
    Uses the PD_commented_by CTE to:
      - Get caller name (pd_caller_name)
      - Filter by PD comment date (gial.created_on) — NOT application logged date
      - Remove customer_tracker dependency entirely

    Filters: app_ids, date_from, date_to, product_type
    """
    app_ids      = filters.get("app_ids", [])
    date_from    = filters.get("date_from")
    date_to      = filters.get("date_to")
    product_type = filters.get("product_type")

    # ── CTE — identical to what was shared ──
    cte = f"""WITH PD_commented_by AS (
    SELECT
        CONCAT(giud.first_name, ' ', giud.last_name) AS pd_caller_name,
        gioacm.application_id,
        gial.cfd_id,
        gial.created_on                              AS pd_comment_date,
        LENGTH(gial.comment)                         AS comment_length,
        gial.comment                                 AS credit_pd_comment
    FROM gq_internal_old_application_cfd_mapping gioacm
    LEFT JOIN gq_internal_audit_logs gial
        ON gial.cfd_id = gioacm.cfd_id
    LEFT JOIN gq_iam_user_has_groups giuhg
        ON giuhg.user_id = gial.user_id AND giuhg.deleted_on IS NULL
    LEFT JOIN gq_iam_group_master gigm
        ON gigm.id = giuhg.group_id
    LEFT JOIN gq_iam_users giu
        ON giu.id = gial.user_id
    LEFT JOIN gq_iam_user_details giud
        ON giud.user_id = giu.id
    WHERE gial.`type` = 'COMMENT'
      AND LENGTH(gial.comment) > 300
      AND gigm.id IN ({PD_TEAM_IAM_GROUP_ID})
)"""

    # ── Main SELECT ──
    select = f"""SELECT
    bi.id                AS app_id,
    pcb.pd_caller_name,
    pcb.pd_comment_date,
    pcb.comment_length,
    {_PRODUCT_CASE},
    pcb.credit_pd_comment"""

    # ── JOINs — no customer_tracker, no group/location/inst ──
    joins = """FROM basic_info bi
JOIN PD_commented_by pcb
    ON pcb.application_id = bi.id
LEFT JOIN course_details cd
    ON cd.basic_info_id = bi.id
LEFT JOIN institutes i
    ON i.institute_id = cd.institute_id"""

    # ── WHERE ──
    where_parts = []
    if date_from and date_to:
        where_parts.append(
            f"DATE(pcb.pd_comment_date) BETWEEN '{date_from}' AND '{date_to}'"
        )
    elif date_from:
        where_parts.append(f"DATE(pcb.pd_comment_date) = '{date_from}'")

    if app_ids:
        ids_str = ", ".join(str(x) for x in app_ids)
        where_parts.append(f"bi.id IN ({ids_str})")

    where = ("WHERE " + "\n  AND ".join(where_parts)) if where_parts else ""

    inner_sql = (
        f"{cte}\n{select}\n{joins}\n{where}\nORDER BY pcb.pd_comment_date DESC"
    )

    # Wrap for product_type filter
    if product_type and product_type != "All":
        return (
            f"SELECT * FROM (\n{inner_sql}\n) t\n"
            f"WHERE t.product_type = '{product_type}'"
        )
    return inner_sql


# ──────────────────────────────────────────────────────────────
# PD RECORDING QUERY  (unchanged — no profile data added here)
# Profile data is fetched separately via build_system_data_query()
# ──────────────────────────────────────────────────────────────

def build_recording_query(filters: dict) -> str:
    date_from    = filters.get("date_from")
    date_to      = filters.get("date_to")
    product_type = filters.get("product_type")
    app_ids      = filters.get("app_ids", [])

    where_parts = [
        "gccd.deleted_on IS NULL",
        f"gigm.id = {PD_TEAM_IAM_GROUP_ID}",
        "json_unquote(json_extract(gccwl.json_response, '$.Status')) = 'Answered'",
    ]

    if date_from and date_to:
        where_parts.append(
            f"DATE(gccd.created_on) BETWEEN '{date_from}' AND '{date_to}'"
        )
    elif date_from:
        where_parts.append(f"DATE(gccd.created_on) = '{date_from}'")

    if app_ids:
        ids_str = ", ".join(str(x) for x in app_ids)
        where_parts.append(f"bi.id IN ({ids_str})")

    where_clause = "\n  AND ".join(where_parts)

    inner_sql = f"""SELECT
    CONCAT(giud.first_name, ' ', giud.last_name)                   AS caller,
    gccd2.cfd_id                                                    AS cfd,
    bi.id                                                           AS app_id,
    bi.student_type,
    {_PRODUCT_CASE},
    json_unquote(json_extract(gccwl.json_response, '$.Status'))     AS call_status,
    gccd.created_on                                                 AS called_on,
    COALESCE(
        TIMESTAMPDIFF(SECOND, gccd2.start_timestamp, gccd2.end_timestamp), 1
    )                                                               AS call_duration_seconds,
    json_unquote(json_extract(gccwl.json_response, '$.AudioFile'))  AS recording_url,

    /* ── System Profile (CAM report) ── */
    COALESCE(CAST(JSON_EXTRACT(gicr.cam_report, '$.cibil_analysis.score') AS SIGNED), -1)
                                                                    AS cibil_score,
    COALESCE(CAST(JSON_EXTRACT(gicr.cam_report, '$.cibil_analysis.total_amt_overdue_all_loans') AS SIGNED), 0)
                                                                    AS overdue_amount,
    COALESCE(CAST(JSON_EXTRACT(gicr.cam_report, '$.cibil_analysis.max_dpd_previous_gq_loans') AS SIGNED), 0)
                                                                    AS gq_dpd_days,
    IF(
        JSON_EXTRACT(gicr.cam_report, '$.financial_details.net_salary') IS NULL,
        ROUND(CAST(JSON_EXTRACT(gicr.cam_report, '$.financial_details.business_annual_income') AS SIGNED) / 12, 0),
        CAST(JSON_EXTRACT(gicr.cam_report, '$.financial_details.net_salary') AS SIGNED)
    )                                                               AS monthly_income,
    JSON_UNQUOTE(JSON_EXTRACT(gicr.cam_report, '$.financial_details.work_status'))
                                                                    AS work_status,
    COALESCE(CAST(JSON_EXTRACT(gicr.cam_report, '$.cibil_analysis.total_obligation_emi_amounts_with_gq_amt') AS SIGNED), 0)
                                                                    AS total_obligations,
    ROUND(
        COALESCE(CAST(JSON_EXTRACT(gicr.cam_report, '$.cibil_analysis.total_obligation_emi_amounts_with_gq_amt') AS SIGNED), 0)
        /
        NULLIF(
            IF(
                JSON_EXTRACT(gicr.cam_report, '$.financial_details.net_salary') IS NULL,
                ROUND(CAST(JSON_EXTRACT(gicr.cam_report, '$.financial_details.business_annual_income') AS SIGNED) / 12, 0),
                CAST(JSON_EXTRACT(gicr.cam_report, '$.financial_details.net_salary') AS SIGNED)
            ), 0
        ) * 100, 1
    )                                                               AS foir,

    /* ── Co-borrower address ── */
    cd2.addr_line_1                                                 AS system_address,
    cd2.city                                                        AS cus_city,
    cd2.state                                                       AS cus_state,
    cd2.gender

FROM gq_cloudagent_call_details gccd
LEFT JOIN gq_iam_user_details giud      ON giud.email = gccd.caller_name
LEFT JOIN gq_iam_user_has_groups giuhg  ON giud.user_id = giuhg.user_id
LEFT JOIN gq_iam_group_master gigm      ON giuhg.group_id = gigm.id
LEFT JOIN gq_cfd_calling_details gccd2  ON gccd2.vendor_code = gccd.code
LEFT JOIN gq_cloudagent_call_webhook_logs gccwl
    ON gccwl.ccd_code = gccd.code AND gccwl.is_active = 1 AND gccwl.deleted_on IS NULL
LEFT JOIN gq_internal_old_application_cfd_mapping gioacm
    ON gccd2.cfd_id = gioacm.cfd_id
LEFT JOIN basic_info bi    ON bi.id = gioacm.application_id
LEFT JOIN course_details cd ON cd.basic_info_id = bi.id
LEFT JOIN institutes i      ON cd.institute_id = i.institute_id
LEFT JOIN gq_internal_cam_report gicr
    ON gicr.application_id = bi.id AND JSON_VALID(gicr.cam_report)
LEFT JOIN coborrower_details cd2        ON cd2.basic_info_id = bi.id
WHERE {where_clause}
ORDER BY gccd.created_on DESC"""

    if product_type and product_type != "All":
        return (
            f"SELECT * FROM (\n{inner_sql}\n) t\n"
            f"WHERE t.product_type = '{product_type}'"
        )
    return inner_sql


# ──────────────────────────────────────────────────────────────
# PANEL COMMENT QUERY  (call vs comment consistency check)
# ──────────────────────────────────────────────────────────────

def build_comment_for_app_query(app_ids: list) -> str:
    """
    Fetch the most recent PD panel comment for each app_id.
    Used in the Recording page to compare what was said in the call
    vs what the caller wrote in the system.

    Filters: same as build_pd_query — PD team IAM group, type=COMMENT,
    length > 300 chars. Returns one row per app_id (latest comment).
    """
    if not app_ids:
        return ""

    ids_str = ", ".join(str(x) for x in app_ids)

    return f"""
WITH ranked_comments AS (
    SELECT
        gioacm.application_id                                    AS app_id,
        gial.comment                                             AS credit_pd_comment,
        gial.created_on                                          AS pd_comment_date,
        CONCAT(giud.first_name, ' ', giud.last_name)             AS pd_caller_name,
        ROW_NUMBER() OVER (
            PARTITION BY gioacm.application_id
            ORDER BY gial.created_on DESC
        )                                                        AS rn
    FROM gq_internal_old_application_cfd_mapping gioacm
    LEFT JOIN gq_internal_audit_logs gial
        ON gial.cfd_id = gioacm.cfd_id
    LEFT JOIN gq_iam_user_has_groups giuhg
        ON giuhg.user_id = gial.user_id AND giuhg.deleted_on IS NULL
    LEFT JOIN gq_iam_group_master gigm
        ON gigm.id = giuhg.group_id
    LEFT JOIN gq_iam_users giu
        ON giu.id = gial.user_id
    LEFT JOIN gq_iam_user_details giud
        ON giud.user_id = giu.id
    WHERE gial.`type` = 'COMMENT'
      AND LENGTH(gial.comment) > 300
      AND gigm.id IN ({PD_TEAM_IAM_GROUP_ID})
      AND gioacm.application_id IN ({ids_str})
)
SELECT app_id, credit_pd_comment, pd_comment_date, pd_caller_name
FROM ranked_comments
WHERE rn = 1
""".strip()


# ──────────────────────────────────────────────────────────────
# SYSTEM PROFILE DATA QUERY  (context-aware scoring)
# ──────────────────────────────────────────────────────────────

def build_system_data_query(app_ids: list) -> str:
    """
    Fetch system profile data for scoring — only for app IDs that have PD recordings.
    Source: gq_internal_cam_report (CAM report JSON) + coborrower_details + basic_info.

    Column aliases map to what scoring code expects:
      cibil_score, overdue_amount, gq_dpd_days, monthly_income, work_status, foir, system_address
    """
    if not app_ids:
        return ""

    ids_str = ", ".join(str(x) for x in app_ids)

    return f"""
SELECT
    bi.id                                                                   AS app_id,
    bi.student_type,

    /* ── Co-borrower address (system address for verification) ── */
    cd2.addr_line_1                                                         AS system_address,
    cd2.city                                                                AS cus_city,
    cd2.state                                                               AS cus_state,
    cd2.gender,

    /* ── Financial details from CAM report JSON ── */
    JSON_UNQUOTE(JSON_EXTRACT(gicr.cam_report, '$.financial_details.work_status'))
                                                                            AS work_status,

    /* Monthly income: net salary if available, else business_annual_income / 12 */
    IF(
        JSON_EXTRACT(gicr.cam_report, '$.financial_details.net_salary') IS NULL,
        ROUND(CAST(JSON_EXTRACT(gicr.cam_report, '$.financial_details.business_annual_income') AS SIGNED) / 12, 0),
        CAST(JSON_EXTRACT(gicr.cam_report, '$.financial_details.net_salary') AS SIGNED)
    )                                                                       AS monthly_income,

    /* ── CIBIL data from CAM report ── */
    COALESCE(CAST(JSON_EXTRACT(gicr.cam_report, '$.cibil_analysis.score') AS SIGNED), -1)
                                                                            AS cibil_score,

    COALESCE(CAST(JSON_EXTRACT(gicr.cam_report, '$.cibil_analysis.total_amt_overdue_all_loans') AS SIGNED), 0)
                                                                            AS overdue_amount,

    COALESCE(CAST(JSON_EXTRACT(gicr.cam_report, '$.cibil_analysis.max_dpd_previous_gq_loans') AS SIGNED), 0)
                                                                            AS gq_dpd_days,

    /* ── Total obligations (EMI + GQ EMI) ── */
    COALESCE(CAST(JSON_EXTRACT(gicr.cam_report, '$.cibil_analysis.total_obligation_emi_amounts_with_gq_amt') AS SIGNED), 0)
                                                                            AS total_obligations,

    /* ── FOIR = total_obligations / monthly_income ── */
    ROUND(
        COALESCE(CAST(JSON_EXTRACT(gicr.cam_report, '$.cibil_analysis.total_obligation_emi_amounts_with_gq_amt') AS SIGNED), 0)
        /
        NULLIF(
            IF(
                JSON_EXTRACT(gicr.cam_report, '$.financial_details.net_salary') IS NULL,
                ROUND(CAST(JSON_EXTRACT(gicr.cam_report, '$.financial_details.business_annual_income') AS SIGNED) / 12, 0),
                CAST(JSON_EXTRACT(gicr.cam_report, '$.financial_details.net_salary') AS SIGNED)
            ), 0
        ) * 100, 1
    )                                                                       AS foir

FROM basic_info bi
LEFT JOIN course_details cd         ON cd.basic_info_id    = bi.id
LEFT JOIN institutes i              ON cd.institute_id     = i.institute_id
LEFT JOIN gq_internal_cam_report gicr
                                    ON gicr.application_id = bi.id
                                    AND JSON_VALID(gicr.cam_report)
LEFT JOIN coborrower_details cd2    ON cd2.basic_info_id   = bi.id
LEFT JOIN application_repayment_plan arp
                                    ON arp.application_id  = bi.id
                                    AND arp.product_id     = cd.institute_id
                                    AND arp.deleted_on IS NULL

WHERE bi.id IN ({ids_str})
""".strip()
