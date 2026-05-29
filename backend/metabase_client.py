"""
Metabase API Client
-------------------
Executes native SQL queries against your Metabase instance and returns
results as a list of dicts (one per row).
"""

import requests
import streamlit as st
import sys, os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import METABASE_URL, METABASE_API_KEY, METABASE_DATABASE_ID


def run_query(sql: str) -> list[dict] | None:
    """
    Post a native SQL query to Metabase /api/dataset.
    Returns list of row-dicts, or None on error.
    """
    headers = {
        "x-api-key": METABASE_API_KEY,
        "Content-Type": "application/json",
    }

    payload = {
        "type": "native",
        "native": {"query": sql},
        "database": METABASE_DATABASE_ID,
        "parameters": [],
    }

    try:
        resp = requests.post(
            f"{METABASE_URL}/api/dataset",
            json=payload,
            headers=headers,
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()

        if "data" not in data:
            st.error(f"Unexpected Metabase response format:\n{data}")
            return None

        cols = [col["name"] for col in data["data"]["cols"]]
        rows = data["data"]["rows"]
        return [dict(zip(cols, row)) for row in rows]

    except requests.exceptions.ConnectionError:
        st.error(
            "❌ Cannot connect to Metabase. "
            "Please verify the URL and your network connection."
        )
        return None

    except requests.exceptions.Timeout:
        st.error(
            "❌ Query timed out (>120 s). "
            "Try a smaller date range or fewer App IDs."
        )
        return None

    except requests.exceptions.HTTPError as exc:
        st.error(
            f"❌ Metabase API returned HTTP {exc.response.status_code}:\n"
            f"{exc.response.text}"
        )
        return None

    except Exception as exc:
        st.error(f"❌ Unexpected error calling Metabase: {exc}")
        return None
