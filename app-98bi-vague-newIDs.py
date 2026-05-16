import streamlit as st


# --- Source selector helper ---
def _select_items_from_source(df_src, want_block: bool, k: int):
    import random
    if df_src is None or k <= 0:
        return []
    bbcol = None
    for name in ("Blockbilling","BLOCKBILLING","Blockbilled","BlockBilled"):
        if name in df_src.columns:
            bbcol = name
            break
    if bbcol is None:
        return []
    norm = df_src[bbcol].astype(str).str.strip().str.upper().map({"Y": True, "N": False}).fillna(False)
    df = df_src[norm] if want_block else df_src[~norm]
    if df.empty:
        return []
    pool = []
    for _, r in df.iterrows():
        pool.append({
            "TASK_CODE": str(r.get("TASK_CODE","")).strip(),
            "ACTIVITY_CODE": str(r.get("ACTIVITY_CODE","")).strip(),
            "DESC": str(r.get("DESCRIPTION","")).strip(),
            "TK_CLASSIFICATION": str(r.get("TK_CLASSIFICATION","")).strip(),
        })
    if len(pool) >= k:
        picks = random.sample(pool, k)
    else:
        picks = [random.choice(pool) for _ in range(k)]
        try:
            st.warning(f"Requested {k} {'block-billed' if want_block else 'non-block'} items but only {len(pool)} available; sampling with replacement.")
        except Exception:
            pass
    return picks

# --- Begin: Blockbilling-from-source helpers ---
def _get_blockbilling_col(df):
    for name in ["Blockbilling", "BlockBilling", "Blockbilled", "BlockBilled"]:
        if name in df.columns:
            return name
    return None

def _normalize_blockbilling(df, colname):
    norm = (
        df[colname]
        .astype(str)
        .str.strip()
        .str.upper()
        .map({"Y": True, "N": False})
        .fillna(False)
    )
    df = df.copy()
    df["is_block_billed"] = norm
    return df

def _enforce_block_billed_limit_df(df, max_blocks:int):
    if max_blocks is None or max_blocks < 0:
        return df
    df = df.copy()
    if "is_block_billed" not in df.columns:
        return df
    mask = df["is_block_billed"]
    if int(mask.sum()) <= int(max_blocks):
        return df
    true_idx = list(df.index[mask])
    to_downgrade = true_idx[int(max_blocks):]
    df.loc[to_downgrade, "is_block_billed"] = False
    return df

def _pick_timekeeper_by_class(timekeepers, target_class):
    import random
    tks = [t for t in (timekeepers or []) if str(t.get("TIMEKEEPER_CLASSIFICATION","")).strip().lower() == str(target_class).strip().lower()]
    if not tks:
        tks = timekeepers or []
    return random.choice(tks) if tks else None

def _generate_fee_lines_from_source_df(df_source, fee_count, timekeeper_data, billing_start_date, billing_end_date, invoice_desc, client_id, law_firm_id, max_hours_per_tk_per_day, faker_instance):
    import random
    import datetime
    rows = []
    if df_source is None or df_source.empty or fee_count <= 0:
        return rows
    # Choose rows to use
    df_use = df_source.sample(n=min(fee_count, len(df_source)), replace=False, random_state=None).reset_index(drop=True)

    # Track hours per (date, tk_id)
    daily_hours = {}

    delta_days = (billing_end_date - billing_start_date).days
    if delta_days < 0:
        delta_days = 0

    for _, r in df_use.iterrows():
        task_code = str(r.get("TASK_CODE","")).strip()
        activity_code = str(r.get("ACTIVITY_CODE","")).strip()
        description = str(r.get("DESCRIPTION","")).strip()
        tk_class = str(r.get("TK_CLASSIFICATION","")).strip() or None

        # Pick a date
        day_offset = random.randint(0, delta_days) if delta_days > 0 else 0
        date_obj = billing_start_date + datetime.timedelta(days=day_offset)
        date_str = date_obj.strftime("%Y-%m-%d")

        # Pick timekeeper
        tk = _pick_timekeeper_by_class(timekeeper_data, tk_class) if tk_class else (random.choice(timekeeper_data) if timekeeper_data else None)
        if not tk:
            # If no timekeepers are loaded, skip safely
            continue
        timekeeper_id = tk.get("TIMEKEEPER_ID","")
        tk_name = tk.get("TIMEKEEPER_NAME","")
        tk_class_actual = tk.get("TIMEKEEPER_CLASSIFICATION","")
        rate = float(tk.get("RATE", 0.0))

        # Remaining capacity for this TK+day
        current = daily_hours.get((date_str, timekeeper_id), 0.0)
        remaining = float(max_hours_per_tk_per_day) - float(current)
        if remaining <= 0:
            # pick a new day with capacity if possible
            found = False
            for _try in range(7):
                if delta_days <= 0:
                    break
                d2 = billing_start_date + datetime.timedelta(days=random.randint(0, delta_days))
                ds2 = d2.strftime("%Y-%m-%d")
                cur2 = daily_hours.get((ds2, timekeeper_id), 0.0)
                rem2 = float(max_hours_per_tk_per_day) - float(cur2)
                if rem2 > 0:
                    date_str = ds2
                    remaining = rem2
                    found = True
                    break
            if not found and remaining <= 0:
                continue

        # Hours: single-line, under cap
        hours = round(random.uniform(0.5, min(8.0, remaining)), 1)
        if hours <= 0:
            hours = min(0.5, remaining)

        # Description placeholders
        description = _process_description(description, faker_instance)

        rows.append({
            "INVOICE_DESCRIPTION": invoice_desc,
            "CLIENT_ID": client_id,
            "LAW_FIRM_ID": law_firm_id,
            "LINE_ITEM_DATE": date_str,
            "TIMEKEEPER_NAME": tk_name,
            "TIMEKEEPER_CLASSIFICATION": tk_class_actual,
            "TIMEKEEPER_ID": timekeeper_id,
            "TASK_CODE": task_code,
            "ACTIVITY_CODE": activity_code,
            "EXPENSE_CODE": "",
            "DESCRIPTION": description,
            "HOURS": float(hours),
            "RATE": rate,
            "LINE_ITEM_TOTAL": round(float(hours) * float(rate), 2),
            # Marker (not serialized into LEDES but may be useful for debugging)
            "_is_block_billed_from_source": bool(r.get("is_block_billed", False)),
        })
        daily_hours[(date_str, timekeeper_id)] = daily_hours.get((date_str, timekeeper_id), 0.0) + float(hours)

    return rows
# --- End: Blockbilling-from-source helpers ---
# Baseline so static analyzers see it as defined before any use
selected_items = []  # baseline for pylance

# --- Streamlit DuplicateWidgetID guard ---------------------------------------
# If a checkbox is rendered more than once with the same label and no explicit key,
# Streamlit raises DuplicateWidgetID. This wrapper injects a stable, unique key
# based on the callsite (file line) when no key is provided.
import inspect, hashlib as _hashlib

if not hasattr(st, "_orig_checkbox"):
    st._orig_checkbox = st.checkbox  # preserve original

def _safe_checkbox(label, **kwargs):
    if "key" not in kwargs or kwargs["key"] is None:
        # Hash label + call line number for a stable, unique key
        caller = inspect.currentframe().f_back
        callsite = f"{label}|{caller.f_lineno}"
        auto_key = "cb_" + _hashlib.md5(callsite.encode("utf-8")).hexdigest()[:10]
        kwargs["key"] = auto_key
    return st._orig_checkbox(label, **kwargs)

# Monkey patch
st.checkbox = _safe_checkbox
# -----------------------------------------------------------------------------

# --- Red warning message styling ---------------------------------------------
# Streamlit's native st.warning() renders as a yellow alert. This app treats
# warnings as invoice-generation guardrails, so render warning calls with the
# red alert treatment while preserving existing st.warning(...) call sites.
if not hasattr(st, "_orig_warning"):
    st._orig_warning = st.warning

def _red_warning(body, *args, **kwargs):
    icon = kwargs.pop("icon", "⚠️")
    return st.error(body, *args, icon=icon, **kwargs)

st.warning = _red_warning
# -----------------------------------------------------------------------------


# Central boolean for sending email
st.session_state.setdefault("send_email", False)

import pandas as pd
import random
import datetime
import io
import os
import logging
import re
import csv
import uuid
import smtplib
from typing import Optional, List, Dict, Any, Tuple
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from faker import Faker
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
#from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
from PIL import Image as PILImage, ImageDraw, ImageFont, Image
import zipfile
from datetime import date, timedelta
# --- Invoice number helpers (multiple billing periods) ---
def _month_stamp_for_date(d: date) -> str:
    """Return YYYY-MMM (MMM is 3-letter month abbreviation, upper-case)."""
    yyyy = int(d.year)
    mmm = calendar.month_abbr[int(d.month)].upper()
    return f"{yyyy}-{mmm}"

def _invoice_number_for_period(base_invoice_number: str, period_end_date: date) -> str:
    """
    For Multiple Billing Periods:
    - Keep the suffix (everything after the second dash) from base_invoice_number
    - Swap the YYYY-MMM prefix to match period_end_date

    Examples:
      base=2025-DEC-123456, end=2025-11-30 -> 2025-NOV-123456
      base=2026-JAN-123456, end=2025-12-31 -> 2025-DEC-123456
    """
    base = str(base_invoice_number or "").strip()
    if not base:
        return base

    stamp = _month_stamp_for_date(period_end_date)

    # Preferred: base already looks like YYYY-MMM-REST...
    m = re.match(r"^(\d{4})-([A-Za-z]{3})-(.+)$", base)
    if m:
        rest = m.group(3)  # keep everything after YYYY-MMM-
        return f"{stamp}-{rest}"

    # Fallback: keep the final segment as the suffix
    parts = base.split("-")
    suffix = parts[-1] if parts else base
    return f"{stamp}-{suffix}"


def _default_invoice_description_lines(base_text: str, period_end_date: date, num_periods: int) -> str:
    """Build default Invoice Description text (one line per period, newest to oldest).

    Example (end=2025-12-31, num_periods=3):
      Professional Services Rendered - Dec 2025
      Professional Services Rendered - Nov 2025
      Professional Services Rendered - Oct 2025
    """
    base = (base_text or "").strip() or "Professional Services Rendered"
    try:
        n = int(num_periods)
    except Exception:
        n = 1
    n = max(1, n)

    y0 = int(period_end_date.year)
    m0 = int(period_end_date.month)

    lines = []
    for i in range(n):
        total = y0 * 12 + (m0 - 1) - i
        y = total // 12
        m = total % 12 + 1
        lines.append(f"{base} - {calendar.month_abbr[m].upper()} {y}")
    return "\n".join(lines)


def _mark_invoice_desc_manual():
    # Called when the user edits the Invoice Description field so we don't overwrite their changes.
    st.session_state["invoice_desc_auto"] = False

import calendar


st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;700&display=swap');
        
        html, body, [class*="css"]  {
            font-family: 'Inter', sans-serif;
        }
    </style>
""", unsafe_allow_html=True)

# --- Presets Configuration ---
PRESETS = {
    "Custom": {"fees": 0, "expenses": 0},
    "Small": {"fees": 25, "expenses": 10},
    "Medium": {"fees": 50, "expenses": 25},
    "Large": {"fees": 100, "expenses": 30},
}

# Default invoice size preset used when the app first loads.
DEFAULT_INVOICE_PRESET = "Medium"

def apply_preset():
    preset_name = st.session_state.invoice_preset
    if preset_name in PRESETS:
        preset = PRESETS[preset_name]
        st.session_state.fee_slider = preset["fees"]
        st.session_state.expense_slider = preset["expenses"]

# ===============================
# Billing Profiles Configuration
# ===============================
# Format: (Environment, Client Name, Client ID, Law Firm Name, Law Firm ID)
BILLING_PROFILES = [("OnitX USD - Nelson",    "A Onit Inc.",   "02-4388252", "Nelson and Murdock", "02-1234567"),
    ("OnitX CAD - SS&E Group", "A Onit Inc.", "02-4388252", "Simpson Schneider and Ellis Group", "879376127RT0002"),
    ("OnitX EUR - Nelson", "Onit LLC - Belgium", "00-4100871", "Nelson and Murdock - Belgium", "3233384400"),
    ("OnitX GBP - Nelson", "Onit - UK", "23058", "Nelson and Murdock - Belgium", "3233384400"),
    ("SimpleLegal/Unity - JDC", "Penguin LLC",   "C004",       "JDC",               "JDC001"),
    ("SimpleLegal/Unity - Kirkland", "Penguin LLC",   "C004",       "Kirkland & Ellis LLP",               "18"),
    ("SimpleLegal/Unity - Latham", "Cardinal Company",   "C003",       "Latham & Watkins LLP",               "17"),
    ("SimpleLegal/Unity - Davis", "Owl LLC",   "C001",       "Davis Polk & Wardell LLP (New York)",               "19"),
    ("SimpleLegal/Unity - Cravath", "Eagle LLC",   "C002",       "Cravath, Swaine & Moore LLP",               "11"),
    ("SimpleLegal/Unity - Whitaker", "Penguin LLC", "C004", "Whitaker & Holbrook LLP", "195"),
    #("Unity",       "Unity Demo",    "uniti-demo", "Gold USD",          "Gold USD"),
]


# Extended profile details (addresses, tax ids, defaults)
# NOTE: VAT-enabled profiles should default to LEDES 1998BI and EUR, and can be used to generate VAT-style invoices.
VAT_ENABLED_PROFILES = {"OnitX EUR - Nelson", "OnitX CAD - SS&E Group", "OnitX GBP - Nelson"}

def _is_vat_profile(profile_id: str) -> bool:
    return str(profile_id or "") in VAT_ENABLED_PROFILES

BILLING_PROFILE_DETAILS = {
    "OnitX CAD - SS&E Group": {
        # Enable VAT-style invoices for the SS&E profile
        "ledes_default": "1998BI",
        # Default currency (can be changed in Tax Fields)
        "invoice_currency": "CAD",
        # Law Firm details
        "law_firm": {
            "name": "Simpson Schneider and Ellis Group",
            "id": "879376127RT0002",
            "address1": "100 Vancouver Blvd",
            "address2": "Suite 2100",
            "city": "Vancouver",
            "state": "British Columbia",
            "postcode": "V5K 0A1",
            "country": "Canada",
        },
        # Client details (Belgium)
        "client": {
            "name": "CN - Canada",
            "id": "23956",
            "tax_id": "23956",
            "address1": "935 Rue de la Gauchetiere",
            "address2": "",
            "city": "Montreal",
            "state": "Quebec",
            "postcode": "H3B 2M9",
            "country": "Canada",
        },
    },
    
    "OnitX EUR - Nelson": {
        "ledes_default": "1998BI",
        "invoice_currency": "EUR",
        # Law Firm details (Belgium)
        "law_firm": {
            "name": "Nelson and Murdock - Belgium",
            "id": "3233384400",
            "address1": "Hanzestedenplaats 1",
            "address2": "",
            "city": "Antwerpen",
            "state": "",
            "postcode": "2000",
            "country": "Belgium",
        },
        # Client details (Belgium)
        "client": {
            "name": "Onit LLC - Belgium",
            "id": "00-4100871",
            "tax_id": "00-4100871",
            "address1": "P.O. Box 636",
            "address2": "4368 Feugiat. Avenue",
            "city": "Grand-Hallet",
            "state": "Luxemburg",
            "postcode": "3230",
            "country": "Belgium",
        },
    },

    "OnitX GBP - Nelson": {
        # Enable VAT-style invoices for the SS&E profile
        "ledes_default": "1998BI",
        # Default currency (can be changed in Tax Fields)
        "invoice_currency": "GBP",
        # Law Firm details
        "law_firm": {
            "name": "Nelson and Murdock - London",
            "id": "3233384400",
            "address1": "90 Fenchurch Street",
            "address2": "6th Floor",
            "city": "London",
            "state": "",
            "postcode": "EC3M 4BY",
            "country": "United Kingdom",
        },
        # Client details (London)
        "client": {
            "name": "Onit - UK",
            "id": "23058",
            "tax_id": "23058",
            "address1": "9046 The Crescent",
            "address2": "",
            "city": "London",
            "state": "",
            "postcode": "NW9 7BD",
            "country": "United Kingdom",
        },
    },
}



# --- LINE_ITEM_TAX_TYPE mapping (profile-driven) ---
# Rule:
#   - If the selected profile's invoice_currency is EUR -> BE_VAT
#   - If the selected profile's invoice_currency is GBP -> UK_VAT
#   - Otherwise -> fallback (usually VAT)
LINE_ITEM_TAX_TYPE_BY_CURRENCY = {
    "EUR": "BE_VAT",
    "GBP": "UK_VAT",
}

def _resolve_line_item_tax_type(active_profile_id: str, fallback: str = "VAT") -> str:
    """Resolve LINE_ITEM_TAX_TYPE for LEDES 1998BI/1998BIv2 lines based on profile."""
    prof_cur = ""
    try:
        prof_cur = str((BILLING_PROFILE_DETAILS.get(str(active_profile_id), {}) or {}).get("invoice_currency", "") or "")
    except Exception:
        prof_cur = ""
    cur = (prof_cur or st.session_state.get("tax_invoice_currency") or st.session_state.get("invoice_currency") or "")
    cur = str(cur).strip().upper()
    return LINE_ITEM_TAX_TYPE_BY_CURRENCY.get(cur, str(fallback))

# --- Client/Vendor catalogs (mix-and-match selections) ---
# These catalogs allow users to mix-and-match a Client (Legal Entity) and a Vendor/Law Firm profile
# independent of the selected Environment/Profile.
#
# Add new entities here (optional). Keys should be unique and are displayed in the dropdowns.
EXTRA_CLIENT_PROFILES = {
    # "Acme Corp (C123)": {
    #     "name": "Acme Corp",
    #     "id": "C123",
    #     "tax_id": "C123",  # optional
    #     "address1": "1 Market St",
    #     "address2": "",
    #     "city": "San Francisco",
    #     "state": "CA",
    #     "postcode": "94105",
    #     "country": "United States",
    # },
}

EXTRA_VENDOR_PROFILES = {
    # "Example Law LLP (V456)": {
    #     "name": "Example Law LLP",
    #     "id": "V456",
    #     "address1": "100 Main St",
    #     "address2": "Suite 200",
    #     "city": "New York",
    #     "state": "NY",
    #     "postcode": "10001",
    #     "country": "United States",
    # },
}

def _entity_label(name: str, entity_id: str) -> str:
    name = str(name or "").strip()
    entity_id = str(entity_id or "").strip()
    if name and entity_id:
        return f"{name} ({entity_id})"
    return name or entity_id or "Unnamed"

def _merge_nonempty(dst: dict, src: dict) -> dict:
    """Merge src into dst, preferring non-empty values in src."""
    out = dict(dst or {})
    for k, v in (src or {}).items():
        if v is None:
            continue
        if isinstance(v, str) and v.strip() == "":
            continue
        out[k] = v
    return out

def _build_entity_catalogs():
    # Start with any explicitly provided extras
    client_cat = {k: dict(v) for k, v in (EXTRA_CLIENT_PROFILES or {}).items()}
    vendor_cat = {k: dict(v) for k, v in (EXTRA_VENDOR_PROFILES or {}).items()}

    # Pull entities out of BILLING_PROFILE_DETAILS (richer data)
    for env, prof in (BILLING_PROFILE_DETAILS or {}).items():
        cl = (prof or {}).get("client", {}) or {}
        lf = (prof or {}).get("law_firm", {}) or {}
        cl_key = _entity_label(cl.get("name"), cl.get("id"))
        lf_key = _entity_label(lf.get("name"), lf.get("id"))
        if cl_key not in client_cat:
            client_cat[cl_key] = {}
        client_cat[cl_key] = _merge_nonempty(client_cat[cl_key], cl)
        if lf_key not in vendor_cat:
            vendor_cat[lf_key] = {}
        vendor_cat[lf_key] = _merge_nonempty(vendor_cat[lf_key], lf)

    # Pull entities from BILLING_PROFILES (basic data)
    for p in (BILLING_PROFILES or []):
        try:
            env, c_name, c_id, lf_name, lf_id = p
        except Exception:
            continue
        cl_key = _entity_label(c_name, c_id)
        lf_key = _entity_label(lf_name, lf_id)
        client_cat.setdefault(cl_key, {"name": c_name, "id": c_id})
        vendor_cat.setdefault(lf_key, {"name": lf_name, "id": lf_id})

    # Determine default client/vendor per env (prefer detailed profile; otherwise fall back to BILLING_PROFILES tuple)
    env_defaults = {}
    for p in (BILLING_PROFILES or []):
        try:
            env, c_name, c_id, lf_name, lf_id = p
        except Exception:
            continue

        if env in (BILLING_PROFILE_DETAILS or {}):
            prof = BILLING_PROFILE_DETAILS.get(env, {}) or {}
            cl = (prof.get("client", {}) or {})
            lf = (prof.get("law_firm", {}) or {})
            c_name = cl.get("name", c_name)
            c_id = cl.get("id", c_id)
            lf_name = lf.get("name", lf_name)
            lf_id = lf.get("id", lf_id)

        cl_key = _entity_label(c_name, c_id)
        lf_key = _entity_label(lf_name, lf_id)
        # Ensure keys exist
        client_cat.setdefault(cl_key, {"name": c_name, "id": c_id})
        vendor_cat.setdefault(lf_key, {"name": lf_name, "id": lf_id})
        env_defaults[env] = (cl_key, lf_key)

    # Stable sorted options
    client_cat = dict(sorted(client_cat.items(), key=lambda kv: str(kv[0]).lower()))
    vendor_cat = dict(sorted(vendor_cat.items(), key=lambda kv: str(kv[0]).lower()))
    return client_cat, vendor_cat, env_defaults

CLIENT_CATALOG, VENDOR_CATALOG, ENV_DEFAULTS = _build_entity_catalogs()

# --- Environment indexes (SimpleLegal/Unity vs OnitX) ---------------------------------
# Canonical environment names + backward-compatible aliases
ENV_ONITX = "OnitX"
ENV_SIMPLELEGAL_UNITY = "SimpleLegal/Unity"
_ENV_ALIASES = {
    "SimpleLegal": ENV_SIMPLELEGAL_UNITY,  # legacy
    "Unity": ENV_SIMPLELEGAL_UNITY,        # legacy
}

def _canonical_env(env: str) -> str:
    env = str(env or "").strip()
    return _ENV_ALIASES.get(env, env)

def _env_ledes_version_default(env: str):
    """Return a forced/default LEDES version for an environment, or None.

    Business rules:
    - SimpleLegal/Unity: default/reset to 1998B
    """
    env = _canonical_env(env)
    if env == ENV_SIMPLELEGAL_UNITY:
        return "1998B"
    return None

# The UI uses st.session_state["selected_env"] as a HIGH-LEVEL environment name
# (e.g., "OnitX" or "SimpleLegal/Unity"). The detailed defaults (currency, LEDES default, etc.)
# are driven by an "active" profile id derived from Environment + selected Client/Vendor pair.
def _infer_environment(profile_id: str, prof_detail=None) -> str:
    """Return environment name for a profile id (prefers explicit prof_detail['environment'])."""
    try:
        if prof_detail and prof_detail.get("environment"):
            return _canonical_env(str(prof_detail.get("environment")).strip())
    except Exception:
        pass
    s = str(profile_id or "").strip()
    if not s:
        return ""
    # Convention: first token is the environment (e.g., "OnitX", "SimpleLegal/Unity")
    return _canonical_env(s.split()[0].strip())

def _build_env_indexes():
    envs = set()
    env_client = {}  # env -> set(client_keys)
    env_vendor = {}  # env -> set(vendor_keys)
    env_default_pair = {}  # env -> (client_key, vendor_key) first seen
    pair_to_profile = {}  # (env, client_key, vendor_key) -> profile_id

    # From BILLING_PROFILES
    for p in (BILLING_PROFILES or []):
        try:
            profile_id, c_name, c_id, lf_name, lf_id = p
        except Exception:
            continue
        env = _infer_environment(profile_id, (BILLING_PROFILE_DETAILS or {}).get(profile_id))
        if not env:
            continue
        envs.add(env)
        ck = _entity_label(c_name, c_id)
        vk = _entity_label(lf_name, lf_id)
        env_client.setdefault(env, set()).add(ck)
        env_vendor.setdefault(env, set()).add(vk)
        env_default_pair.setdefault(env, (ck, vk))
        pair_to_profile.setdefault((env, ck, vk), profile_id)

    # From BILLING_PROFILE_DETAILS (richer; may correct names/ids)
    for profile_id, prof in (BILLING_PROFILE_DETAILS or {}).items():
        env = _infer_environment(profile_id, prof)
        if not env:
            continue
        envs.add(env)
        cl = (prof or {}).get("client", {}) or {}
        lf = (prof or {}).get("law_firm", {}) or {}
        ck = _entity_label(cl.get("name"), cl.get("id"))
        vk = _entity_label(lf.get("name"), lf.get("id"))
        if ck:
            env_client.setdefault(env, set()).add(ck)
        if vk:
            env_vendor.setdefault(env, set()).add(vk)
        env_default_pair.setdefault(env, (ck, vk))
        pair_to_profile.setdefault((env, ck, vk), profile_id)

    # Include EXTRA_* profiles:
    # - If an extra dict includes "environment", only include for that env (or envs list).
    # - If it has no "environment", include in all known envs (backward compatible).
    known_envs = sorted([e for e in envs if e]) or [ENV_ONITX, ENV_SIMPLELEGAL_UNITY]
    for k, v in (EXTRA_CLIENT_PROFILES or {}).items():
        env_val = (v or {}).get("environment", None)
        if env_val:
            env_list = [env_val] if isinstance(env_val, str) else list(env_val)
            for e in env_list:
                e = _canonical_env(str(e).strip())
                if not e:
                    continue
                env_client.setdefault(e, set()).add(k)
                envs.add(e)
        else:
            for e in known_envs:
                env_client.setdefault(e, set()).add(k)

    for k, v in (EXTRA_VENDOR_PROFILES or {}).items():
        env_val = (v or {}).get("environment", None)
        if env_val:
            env_list = [env_val] if isinstance(env_val, str) else list(env_val)
            for e in env_list:
                e = _canonical_env(str(e).strip())
                if not e:
                    continue
                env_vendor.setdefault(e, set()).add(k)
                envs.add(e)
        else:
            for e in known_envs:
                env_vendor.setdefault(e, set()).add(k)

    envs = sorted([e for e in envs if e]) or known_envs
    env_client_opts = {e: sorted(list(env_client.get(e, set())), key=lambda x: str(x).lower()) for e in envs}
    env_vendor_opts = {e: sorted(list(env_vendor.get(e, set())), key=lambda x: str(x).lower()) for e in envs}

    # Ensure every env has a default pair
    for e in envs:
        if e not in env_default_pair:
            dc = env_client_opts.get(e, [""])[0] if env_client_opts.get(e) else ""
            dv = env_vendor_opts.get(e, [""])[0] if env_vendor_opts.get(e) else ""
            env_default_pair[e] = (dc, dv)

    return envs, env_client_opts, env_vendor_opts, env_default_pair, pair_to_profile

ENVIRONMENTS, ENV_CLIENT_OPTIONS, ENV_VENDOR_OPTIONS, ENV_DEFAULT_ENTITY_PAIR, PROFILE_PAIR_TO_ID = _build_env_indexes()

def _resolve_active_profile_id(env: str, client_key: str, vendor_key: str) -> str:
    """Pick the most appropriate profile id for defaults, given env + selected Client/Vendor."""
    env = _canonical_env(str(env or "").strip())
    client_key = str(client_key or "").strip()
    vendor_key = str(vendor_key or "").strip()

    pid = PROFILE_PAIR_TO_ID.get((env, client_key, vendor_key))
    if pid:
        return pid

    # Fall back to the first profile id we can find for this environment
    for p in (BILLING_PROFILES or []):
        try:
            profile_id = p[0]
        except Exception:
            continue
        if _infer_environment(profile_id, (BILLING_PROFILE_DETAILS or {}).get(profile_id)) == env:
            return profile_id

    # Last resort: any profile id
    try:
        return (BILLING_PROFILES or [])[0][0]
    except Exception:
        return ""

def _ensure_env_profile_state():
    """
    Ensure selected_env (environment), selected_client_profile, selected_vendor_profile,
    and active_profile_id are all populated in session_state.
    """
    envs = ENVIRONMENTS or [ENV_ONITX, ENV_SIMPLELEGAL_UNITY]
    # Backward-compat: map legacy env names to canonical names
    st.session_state["selected_env"] = _canonical_env(st.session_state.get("selected_env", ""))
    if _canonical_env(st.session_state.get("selected_env")) not in envs:
        st.session_state["selected_env"] = envs[0] if envs else ENV_ONITX
    env = _canonical_env(st.session_state.get("selected_env", envs[0] if envs else ENV_ONITX))

    # Client/Vendor defaults for this environment
    default_client, default_vendor = ENV_DEFAULT_ENTITY_PAIR.get(env, ("", ""))
    valid_clients = set(ENV_CLIENT_OPTIONS.get(env, [])) or set(CLIENT_CATALOG.keys())
    valid_vendors = set(ENV_VENDOR_OPTIONS.get(env, [])) or set(VENDOR_CATALOG.keys())

    if st.session_state.get("selected_client_profile") not in valid_clients:
        st.session_state["selected_client_profile"] = default_client or (next(iter(valid_clients)) if valid_clients else "")
    if st.session_state.get("selected_vendor_profile") not in valid_vendors:
        st.session_state["selected_vendor_profile"] = default_vendor or (next(iter(valid_vendors)) if valid_vendors else "")

    st.session_state["active_profile_id"] = _resolve_active_profile_id(
        env,
        st.session_state.get("selected_client_profile", ""),
        st.session_state.get("selected_vendor_profile", ""),
    )
# -------------------------------------------------------------------------------



def get_profile(env: str):
    """Return (client_name, client_id, law_firm_name, law_firm_id) for the environment."""
    for p in BILLING_PROFILES:
        if p[0] == env:
            return (p[1], p[2], p[3], p[4])
    p = BILLING_PROFILES[0]
    return (p[1], p[2], p[3], p[4])


# --- Logging Setup ---
logging.basicConfig(level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Constants ---
CONFIG = {
    'EXPENSE_CODES': {
        "Photocopies": "E101", "Outside printing": "E102", "Word processing": "E103",
        "Facsimile": "E104", "Telephone": "E105", "Online research": "E106",
        "Delivery services/messengers": "E107", "Postage": "E108", "Local travel": "E109",
        "Out-of-town travel": "E110", "Meals": "E111", "Court fees": "E112",
        "Subpoena fees": "E113", "Witness fees": "E114", "Deposition transcripts": "E115",
        "Trial transcripts": "E116", "Trial exhibits": "E117",
        "Litigation support vendors": "E118", "Experts": "E119",
        "Private investigators": "E120", "Arbitrators/mediators": "E121",
        "Local counsel": "E122", "Other professionals": "E123", "Other": "E124",
    },
    'DEFAULT_TASK_ACTIVITY_DESC': [
        ("L100", "A101", "Legal Research: Analyze legal precedents"),
        ("L110", "A101", "Legal Research: Review statutes and regulations"),
        ("L120", "A101", "Legal Research: Draft research memorandum"),
        ("L130", "A102", "Case Assessment: Initial case evaluation"),
        ("L140", "A102", "Case Assessment: Develop case strategy"),
        ("L150", "A102", "Case Assessment: Identify key legal issues"),
        ("L160", "A103", "Fact Investigation: Interview witnesses"),
        ("L190", "A104", "Pleadings: Draft complaint/petition"),
        ("L200", "A104", "Pleadings: Prepare answer/response"),
        ("L210", "A104", "Pleadings: File motion to dismiss"),
        ("L220", "A105", "Discovery: Draft interrogatories"),
        ("L230", "A105", "Discovery: Prepare requests for production"),
        ("L240", "A105", "Discovery: Review opposing party's discovery responses"),
        ("L250", "A106", "Depositions: Prepare for deposition"),
        ("L260", "A106", "Depositions: Attend deposition"),
        ("L300", "A107", "Motions: Argue motion in court"),
        ("L310", "A108", "Settlement/Mediation: Prepare for mediation"),
        ("L320", "A108", "Settlement/Mediation: Attend mediation"),
        ("L330", "A108", "Settlement/Mediation: Draft settlement agreement"),
        ("L340", "A109", "Trial Preparation: Prepare witness for trial"),
        ("L350", "A109", "Trial Preparation: Organize trial exhibits"),
        ("L390", "A110", "Trial: Present closing argument"),
        ("L400", "A111", "Appeals: Research appellate issues"),
        ("L410", "A111", "Appeals: Draft appellate brief"),
        ("L420", "A111", "Appeals: Argue before appellate court"),
        ("L430", "A112", "Client Communication: Client meeting"),
        ("L440", "A112", "Client Communication: Phone call with client"),
        ("L450", "A112", "Client Communication: Email correspondence with client"),
    ],
    'MAJOR_TASK_CODES': {"L110", "L120", "L130", "L140", "L150", "L160", "L170", "L180", "L190"},
    'DEFAULT_CLIENT_ID': "02-4388252",
    'DEFAULT_LAW_FIRM_ID': "02-1234567",
    'DEFAULT_INVOICE_DESCRIPTION': "Monthly Legal Services",
    'MANDATORY_ITEMS': {
        'KBCG': {
            'desc': ("Commenced data entry into the KBCG e-licensing portal for Piers Walter Vermont "
                     "form 1005 application; Drafted deficiency notice to send to client re: same; "
                     "Scheduled follow-up call with client to review application status and address outstanding deficiencies."),
            'tk_name': "Tom Delaganis",
            'task': "L140",
            'activity': "A107",
            'is_expense': False
        },
        'John Doe': {
            'desc': ("Reviewed and summarized deposition transcript of John Doe; prepared exhibit index; "
                     "updated case chronology spreadsheet for attorney review"),
            'tk_name': "Ryan Kinsey",
            'task': "L120",
            'activity': "A102",
            'is_expense': False
        },
        'Uber E110': {
            'desc': "Uber ride to client's office",
            'expense_code': "E110",
            'is_expense': True,
            'requires_details': True # Flag for special handling
        },
        'Partner: Paralegal Tasks': {
            'desc': "Prepared trial binder including witness lists and exhibit summaries.",
            'tk_name': "Ryan Kinsey",
            'task': "L140",
            'activity': "A103",
            'is_expense': False
        },
        'Airfare E110': {
            'desc': "Airfare",
            'expense_code': "E110",
            'is_expense': True,
            'requires_details': True # Flag for special handling
        },
    }
}
# --- Airfare E110 helpers: United-served nonstop US destinations from SFO ---
# Source (update as routes change): FlySFO "Where We Fly - United States"
# We include destinations where United Airlines is listed as a nonstop operator from SFO.
SFO_DEPARTURE_CITY = "San Francisco (SFO)"

UA_SFO_US_DESTINATIONS = [
    "Albuquerque (ABQ)",
    "Anchorage (ANC)",
    "Arcata/Eureka (ACV)",
    "Aspen (ASE)",
    "Atlanta (ATL)",
    "Austin (AUS)",
    "Bakersfield (BFL)",
    "Baltimore (BWI)",
    "Bishop (BIH)",
    "Boise (BOI)",
    "Boston (BOS)",
    "Bozeman (BZN)",
    "Burbank (BUR)",
    "Carlsbad (CLD)",
    "Chicago-O'Hare (ORD)",
    "Cleveland (CLE)",
    "Columbus (CMH)",
    "Dallas/Fort Worth (DFW)",
    "Denver (DEN)",
    "Detroit (DTW)",
    "Eugene (EUG)",
    "Fort Lauderdale (FLL)",
    "Fresno (FAT)",
    "Hailey/Sun Valley (SUN)",
    "Hayden (HDN)",
    "Honolulu (HNL)",
    "Houston (IAH)",
    "Indianapolis (IND)",
    "Jackson Hole (JAC)",
    "Kahului/Maui (OGG)",
    "Kalispell (FCA)",
    "Kansas City (MCI)",
    "Kona (KOA)",
    "Las Vegas (LAS)",
    "Lihue (LIH)",
    "Los Angeles (LAX)",
    "Medford (MFR)",
    "Miami (MIA)",
    "Minneapolis/St Paul (MSP)",
    "Missoula (MSO)",
    "Monterey (MRY)",
    "Montrose (MTJ)",
    "New Orleans (MSY)",
    "Newark/New York (EWR)",
    "North Bend (OTH)",
    "Omaha (OMA)",
    "Ontario (ONT)",
    "Orlando (MCO)",
    "Palm Springs (PSP)",
    "Pasco (PSC)",
    "Philadelphia (PHL)",
    "Phoenix (PHX)",
    "Pittsburgh (PIT)",
    "Portland (PDX)",
    "Portland (PWM)",
    "Raleigh/Durham (RDU)",
    "Redding (RDD)",
    "Redmond/Bend (RDM)",
    "Reno (RNO)",
    "Sacramento (SMF)",
    "St. Louis (STL)",
    "Salt Lake City (SLC)",
    "San Antonio (SAT)",
    "San Diego (SAN)",
    "San Luis Obispo (SBP)",
    "Santa Ana/Orange County (SNA)",
    "Santa Barbara (SBA)",
    "Seattle (SEA)",
    "Spokane (GEG)",
    "Tampa (TPA)",
    "Tucson (TUS)",
    "Vail/Eagle (EGE)",
    "Washington-Dulles (IAD)",
    "Washington-National (DCA)",
]

def _pick_ua_sfo_arrival_city() -> str:
    import random
    return random.choice(UA_SFO_US_DESTINATIONS)


EXPENSE_DESCRIPTIONS = list(CONFIG['EXPENSE_CODES'].keys())
OTHER_EXPENSE_DESCRIPTIONS = [desc for desc in EXPENSE_DESCRIPTIONS if CONFIG['EXPENSE_CODES'][desc] != "E101"]

# --- Helper Functions ---
def _find_timekeeper_by_name(timekeepers: List[Dict], name: str) -> Optional[Dict]:
    """Find a timekeeper by name (case-insensitive)."""
    if not timekeepers:
        return None
    for tk in timekeepers:
        if str(tk.get("TIMEKEEPER_NAME", "")).strip().lower() == str(name).strip().lower():
            return tk
    return None

def _find_timekeeper_by_classification(timekeepers, classification: str):
    """Return the first timekeeper whose classification contains the target (case-insensitive)."""
    if not timekeepers:
        return None
    target = str(classification).strip().lower()

    def norm(s: str) -> str:
        return re.sub(r"\s+", " ", str(s).strip().lower())

    # Find candidates where the normalized classification contains the target string
    candidates = [tk for tk in timekeepers if target in norm(tk.get("TIMEKEEPER_CLASSIFICATION", ""))]
    if not candidates:
        return None

    # For deterministic results, sort by name and pick the first one
    candidates.sort(key=lambda tk: str(tk.get("TIMEKEEPER_NAME", "")).lower())
    return candidates[0]



def _get_timekeepers():
    """Return timekeepers list from session or empty list if none loaded."""
    return st.session_state.get("timekeeper_data") or []

def _is_partner_paralegal_item(name: str) -> bool:
    """True for 'Partner: Paralegal Task' or '... Tasks' (case/space tolerant, prefix match)."""
    return str(name).strip().lower().startswith("partner: paralegal")

def _force_timekeeper_on_row(row: Dict, forced_name: str, timekeepers: List[Dict]) -> Optional[Dict]:
    """
    Assign timekeeper details to a row if a match is found.
    Returns the updated row on success, or None on failure.
    """
    if row.get("EXPENSE_CODE"):
        return row

    row["TIMEKEEPER_NAME"] = forced_name
    tk = _find_timekeeper_by_name(timekeepers, forced_name)

    # If a matching timekeeper was found, populate details and return the row.
    if tk:
        row["TIMEKEEPER_ID"] = tk.get("TIMEKEEPER_ID", "")
        row["TIMEKEEPER_CLASSIFICATION"] = tk.get("TIMEKEEPER_CLASSIFICATION", "")
        try:
            row["RATE"] = float(tk.get("RATE", 0.0))
            hours = float(row.get("HOURS", 0))
            row["LINE_ITEM_TOTAL"] = round(hours * float(row["RATE"]), 2)
        except Exception as e:
            logging.error(f"Error setting timekeeper rate: {e}")
        return row

    # If no match was found, return None to signal that this row should be skipped.
    return None

def _process_description(description: str, faker_instance: Faker) -> str:
    """Process description by replacing placeholders and dates."""
    pattern = r"\b(\d{2}/\d{2}/\d{4})\b"
    if re.search(pattern, description):
        days_ago = random.randint(15, 90)
        new_date = (datetime.date.today() - datetime.timedelta(days=days_ago)).strftime("%m/%d/%Y")
        description = re.sub(pattern, new_date, description)
    description = description.replace("{NAME_PLACEHOLDER}", faker_instance.name())
    return description

def _is_valid_client_id(client_id: str) -> bool:
    """Validate Client ID format (XX-XXXXXXX)."""
    pattern = r"^\d{2}-\d{7}$"
    return bool(re.match(pattern, client_id))

def _is_valid_law_firm_id(law_firm_id: str) -> bool:
    """Validate Law Firm ID format (XX-XXXXXXX)."""
    pattern = r"^\d{2}-\d{7}$"
    return bool(re.match(pattern, law_firm_id))

def _calculate_max_fees(timekeeper_data: Optional[List[Dict]], billing_start_date: datetime.date, billing_end_date: datetime.date, max_daily_hours: int) -> int:
    """Calculate maximum feasible fee lines based on timekeeper data and billing period."""
    if not timekeeper_data:
        return 1
    num_timekeepers = len(timekeeper_data)
    delta = billing_end_date - billing_start_date
    num_days = max(1, delta.days + 1)
    max_lines = int((num_timekeepers * num_days * max_daily_hours) / 0.5)
    return max(1, min(1000, max_lines))

def _load_timekeepers(uploaded_file: Optional[Any]) -> Optional[List[Dict]]:
    """Load timekeepers from CSV file."""
    if uploaded_file is None:
        return None
    try:
        df = pd.read_csv(uploaded_file)
        required_cols = ["TIMEKEEPER_NAME", "TIMEKEEPER_CLASSIFICATION", "TIMEKEEPER_ID", "RATE"]
        if not all(col in df.columns for col in required_cols):
            st.error(f"Timekeeper CSV must contain the following columns: {', '.join(required_cols)}")
            return None
        return df.to_dict(orient='records')
    except Exception as e:
        st.error(f"Error loading timekeeper file: {e}")
        logging.error(f"Timekeeper load error: {e}")
        return None


def _load_custom_task_activity_data(uploaded_file: Optional[Any]) -> Optional[List[Tuple[str, str, str]]]:
    """Load custom task/activity data from CSV."""
    if uploaded_file is None:
        return None
    try:
        df = pd.read_csv(uploaded_file)
        required_cols = ["TASK_CODE", "ACTIVITY_CODE", "DESCRIPTION"]
        if not all(col in df.columns for col in required_cols):
            st.error(f"Custom Task/Activity CSV must contain the following columns: {', '.join(required_cols)}")
            return None
        if df.empty:
            st.warning("Custom Task/Activity CSV file is empty.")
            return []
        # NEW: remove exact duplicate task/activity/description triples
        df = df.drop_duplicates(subset=["TASK_CODE", "ACTIVITY_CODE", "DESCRIPTION"]).reset_index(drop=True)
        # (Optional but helpful) shuffle once so selection spreads across the file
        df = df.sample(frac=1, random_state=None).reset_index(drop=True)
        # Stash the full (de-duplicated) DataFrame for fee-source usage (including optional Blockbilling logic)
        try:
            st.session_state["custom_fee_df"] = df.copy()
        except Exception:
            pass
        custom_tasks = [(str(r["TASK_CODE"]), str(r["ACTIVITY_CODE"]), str(r["DESCRIPTION"])) for _, r in df.iterrows()]
        return custom_tasks
    except Exception as e:
        st.error(f"Error loading custom tasks file: {e}")
        logging.error(f"Custom tasks load error: {e}")
        return None


def _create_ledes_line_1998b(row: Dict, line_no: int, inv_total: float, bill_start: datetime.date, bill_end: datetime.date, invoice_number: str, matter_number: str) -> List[str]:
    """Create a single LEDES 1998B line."""
    try:
        date_obj = datetime.datetime.strptime(row["LINE_ITEM_DATE"], "%Y-%m-%d").date()
        hours = float(row["HOURS"])
        rate = float(row["RATE"])
        line_total = float(row["LINE_ITEM_TOTAL"])
        is_expense = bool(row["EXPENSE_CODE"])
        adj_type = "E" if is_expense else "F"
        task_code = "" if is_expense else row.get("TASK_CODE", "")
        activity_code = "" if is_expense else row.get("ACTIVITY_CODE", "")
        expense_code = row.get("EXPENSE_CODE", "") if is_expense else ""
        timekeeper_id = "" if is_expense else row.get("TIMEKEEPER_ID", "")
        timekeeper_class = "" if is_expense else row.get("TIMEKEEPER_CLASSIFICATION", "")
        timekeeper_name = "" if is_expense else row.get("TIMEKEEPER_NAME", "")
        description = str(row.get("DESCRIPTION", "")).replace("|", " - ")
        return [
            bill_end.strftime("%Y%m%d"),
            invoice_number,
            str(row.get("CLIENT_ID", "")),
            matter_number,
            f"{inv_total:.2f}",
            bill_start.strftime("%Y%m%d"),
            bill_end.strftime("%Y%m%d"),
            str(row.get("INVOICE_DESCRIPTION", "")),
            str(line_no),
            adj_type,
            f"{hours:.1f}" if adj_type == "F" else f"{int(hours)}",
            "0.00",
            f"{line_total:.2f}",
            date_obj.strftime("%Y%m%d"),
            task_code,
            expense_code,
            activity_code,
            timekeeper_id,
            description,
            str(row.get("LAW_FIRM_ID", "")),
            f"{rate:.2f}",
            timekeeper_name,
            timekeeper_class,
            matter_number
        ]
    except Exception as e:
        logging.error(f"Error creating LEDES line: {e}")
        return []

def _create_ledes_1998b_content(rows: List[Dict], inv_total: float, bill_start: datetime.date, bill_end: datetime.date, invoice_number: str, matter_number: str, is_first_invoice: bool = True) -> str:
    """Generate LEDES 1998B content from invoice rows."""
    lines = []
    if is_first_invoice:
        header = "LEDES1998B[]"
        fields = ("INVOICE_DATE|INVOICE_NUMBER|CLIENT_ID|LAW_FIRM_MATTER_ID|INVOICE_TOTAL|BILLING_START_DATE|"
                  "BILLING_END_DATE|INVOICE_DESCRIPTION|LINE_ITEM_NUMBER|EXP/FEE/INV_ADJ_TYPE|"
                  "LINE_ITEM_NUMBER_OF_UNITS|LINE_ITEM_ADJUSTMENT_AMOUNT|LINE_ITEM_TOTAL|LINE_ITEM_DATE|"
                  "LINE_ITEM_TASK_CODE|LINE_ITEM_EXPENSE_CODE|LINE_ITEM_ACTIVITY_CODE|TIMEKEEPER_ID|"
                  "LINE_ITEM_DESCRIPTION|LAW_FIRM_ID|LINE_ITEM_UNIT_COST|TIMEKEEPER_NAME|"
                  "TIMEKEEPER_CLASSIFICATION|CLIENT_MATTER_ID[]")
        lines = [header, fields]
    for i, row in enumerate(rows, start=1):
        line = _create_ledes_line_1998b(row, i, inv_total, bill_start, bill_end, invoice_number, matter_number)
        if line:
            lines.append("|".join(map(str, line)) + "[]")
    return "\n".join(lines)

def _create_ledes_line_1998biv2(row: Dict, line_no: int, inv_total: float,
                                bill_start: datetime.date, bill_end: datetime.date,
                                invoice_number: str, matter_number: str,
                                matter_name: str, po_number: str,
                                client_matter_id: str, invoice_currency: str,
                                tax_rate: float) -> List[str]:
    """Create a single LEDES 1998BIv2 line."""
    try:
        date_obj = datetime.datetime.strptime(row["LINE_ITEM_DATE"], "%Y-%m-%d").date()
        units = float(row.get("HOURS", 0) or 0)
        unit_cost = float(row.get("RATE", 0) or 0)
        line_total = float(row.get("LINE_ITEM_TOTAL", 0) or 0)

        is_expense = bool(row.get("EXPENSE_CODE", ""))
        adj_type = "E" if is_expense else "F"
        task_code = "" if is_expense else str(row.get("TASK_CODE", ""))
        activity_code = "" if is_expense else str(row.get("ACTIVITY_CODE", ""))
        expense_code = str(row.get("EXPENSE_CODE", "")) if is_expense else ""
        timekeeper_id = "" if is_expense else str(row.get("TIMEKEEPER_ID", ""))
        timekeeper_class = "" if is_expense else str(row.get("TIMEKEEPER_CLASSIFICATION", ""))
        timekeeper_name = "" if is_expense else str(row.get("TIMEKEEPER_NAME", ""))
        description = str(row.get("DESCRIPTION", "")).replace("|", " - ")

        tax_type = _resolve_line_item_tax_type(st.session_state.get("active_profile_id", ""), fallback=str(st.session_state.get("tax_type", "VAT")))

        return [
            bill_end.strftime("%Y%m%d"),
            str(invoice_number),
            str(row.get("CLIENT_ID", "")),
            str(matter_number),
            f"{inv_total:.2f}",  # tax-inclusive invoice total
            bill_start.strftime("%Y%m%d"),
            bill_end.strftime("%Y%m%d"),
            str(row.get("INVOICE_DESCRIPTION", "")),
            str(line_no),
            adj_type,
            f"{units:.1f}" if adj_type == "F" else f"{int(units)}",
            "0.00",
            f"{line_total:.2f}",
            date_obj.strftime("%Y%m%d"),
            task_code,
            expense_code,
            activity_code,
            timekeeper_id,
            description,
            str(row.get("LAW_FIRM_ID", "")),
            f"{unit_cost:.2f}",
            timekeeper_name,
            timekeeper_class,
            str(client_matter_id),
            str(matter_name),
            str(po_number),
            str(invoice_currency),
            f"{float(tax_rate):.2f}",
            tax_type,
        ]
    except Exception as e:
        logging.error(f"Error creating LEDES 1998BIv2 line: {e}")
        return []


def _create_ledes_1998biv2_content(rows: List[Dict],
                                   bill_start: datetime.date, bill_end: datetime.date,
                                   invoice_number: str, matter_number: str,
                                   matter_name: str, po_number: str,
                                   client_matter_id: str, invoice_currency: str,
                                   tax_rate: float, is_first_invoice: bool = True) -> str:
    lines: List[str] = []
    if is_first_invoice:
        header = "LEDES1998BIv2[]"
        fields = ("INVOICE_DATE|INVOICE_NUMBER|CLIENT_ID|LAW_FIRM_MATTER_ID|INVOICE_TOTAL|"
                  "BILLING_START_DATE|BILLING_END_DATE|INVOICE_DESCRIPTION|LINE_ITEM_NUMBER|"
                  "EXP/FEE/INV_ADJ_TYPE|LINE_ITEM_NUMBER_OF_UNITS|LINE_ITEM_ADJUSTMENT_AMOUNT|"
                  "LINE_ITEM_TOTAL|LINE_ITEM_DATE|LINE_ITEM_TASK_CODE|LINE_ITEM_EXPENSE_CODE|"
                  "LINE_ITEM_ACTIVITY_CODE|TIMEKEEPER_ID|LINE_ITEM_DESCRIPTION|LAW_FIRM_ID|"
                  "LINE_ITEM_UNIT_COST|TIMEKEEPER_NAME|TIMEKEEPER_CLASSIFICATION|CLIENT_MATTER_ID|"
                  "MATTER_NAME|PO_NUMBER|INVOICE_CURRENCY|TAX_RATE|LINE_ITEM_TAX_TYPE[]")
        lines = [header, fields]
    else:
        lines = []

    subtotal = sum(float(r.get("LINE_ITEM_TOTAL", 0) or 0) for r in rows)
    tax_amount = round(subtotal * float(tax_rate or 0), 2)
    grand_total = subtotal + tax_amount

    for i, row in enumerate(rows, start=1):
        line = _create_ledes_line_1998biv2(row, i, grand_total, bill_start, bill_end,
                                           invoice_number, matter_number,
                                           matter_name, po_number, client_matter_id,
                                           invoice_currency, tax_rate)
        if line:
            lines.append("|".join(map(str, line)) + "[]")
    return "\n".join(lines)


def _create_ledes_1998bi_content(rows: List[Dict],
                                 bill_start: datetime.date, bill_end: datetime.date,
                                 invoice_number: str, matter_number: str,
                                 matter_name: str, po_number: str,
                                 client_matter_id: str, invoice_currency: str,
                                 tax_rate: float, is_first_invoice: bool = True) -> str:
    header = "LEDES1998BI[]"
    fields = ("INVOICE_DATE|INVOICE_NUMBER|CLIENT_ID|LAW_FIRM_MATTER_ID|INVOICE_TOTAL|"
              "BILLING_START_DATE|BILLING_END_DATE|INVOICE_DESCRIPTION|LINE_ITEM_NUMBER|"
              "EXP/FEE/INV_ADJ_TYPE|LINE_ITEM_NUMBER_OF_UNITS|LINE_ITEM_ADJUSTMENT_AMOUNT|"
              "LINE_ITEM_TOTAL|LINE_ITEM_DATE|LINE_ITEM_TASK_CODE|LINE_ITEM_EXPENSE_CODE|"
              "LINE_ITEM_ACTIVITY_CODE|TIMEKEEPER_ID|LINE_ITEM_DESCRIPTION|LAW_FIRM_ID|"
              "LINE_ITEM_UNIT_COST|TIMEKEEPER_NAME|TIMEKEEPER_CLASSIFICATION|CLIENT_MATTER_ID|"
              "PO_NUMBER|CLIENT_TAX_ID|MATTER_NAME|INVOICE_TAX_TOTAL|INVOICE_NET_TOTAL|"
              "INVOICE_CURRENCY|TIMEKEEPER_LAST_NAME|TIMEKEEPER_FIRST_NAME|ACCOUNT_TYPE|"
              "LAW_FIRM_NAME|LAW_FIRM_ADDRESS_1|LAW_FIRM_ADDRESS_2|LAW_FIRM_CITY|"
              "LAW_FIRM_STATEorREGION|LAW_FIRM_POSTCODE|LAW_FIRM_COUNTRY|CLIENT_NAME|"
              "CLIENT_ADDRESS_1|CLIENT_ADDRESS_2|CLIENT_CITY|CLIENT_STATEorREGION|"
              "CLIENT_POSTCODE|CLIENT_COUNTRY|LINE_ITEM_TAX_RATE|LINE_ITEM_TAX_TOTAL|"
              "LINE_ITEM_TAX_TYPE[]")
    lines: List[str] = [header, fields] if is_first_invoice else []
    # Pull Law Firm / Client details from the UI session
    lf_name = st.session_state.get("law_firm_name","")
    lf_id = (st.session_state.get("pf_law_firm_id") or st.session_state.get("law_firm_id", ""))
    lf_address1 = (st.session_state.get("pf_lf_address1") or st.session_state.get("lf_address1", ""))
    lf_address2 = (st.session_state.get("pf_lf_address2") or st.session_state.get("lf_address2", ""))
    lf_city = (st.session_state.get("pf_lf_city") or st.session_state.get("lf_city", ""))
    lf_state = (st.session_state.get("pf_lf_state") or st.session_state.get("lf_state", ""))
    lf_postcode = (st.session_state.get("pf_lf_postcode") or st.session_state.get("lf_postcode", ""))
    lf_country = (st.session_state.get("pf_lf_country") or st.session_state.get("lf_country", ""))
    cl_name = st.session_state.get("client_name","")
    cl_id = st.session_state.get("client_id","")
    cl_tax_id = (st.session_state.get("pf_client_tax_id") or st.session_state.get("client_tax_id",""))
    client_id_eff = cl_tax_id or cl_id
    cl_address1 = (st.session_state.get("pf_client_address1") or st.session_state.get("client_address1", ""))
    cl_address2 = (st.session_state.get("pf_client_address2") or st.session_state.get("client_address2", ""))
    cl_city = (st.session_state.get("pf_client_city") or st.session_state.get("client_city", ""))
    cl_state = (st.session_state.get("pf_client_state") or st.session_state.get("client_state", ""))
    cl_postcode = (st.session_state.get("pf_client_postcode") or st.session_state.get("client_postcode", ""))
    cl_country = (st.session_state.get("pf_client_country") or st.session_state.get("client_country", ""))

    def _f(x):
        try:
            return float(x)
        except Exception:
            return 0.0

    # First pass: totals
    net_total = 0.0
    tax_total = 0.0
    prepped = []
    for row in rows:
        is_expense = bool(row.get("EXPENSE_CODE", ""))
        # This correctly uses the number of copies (stored in HOURS) for expenses
        units = _f(row.get("HOURS", 0))
        unit_cost = _f(row.get("RATE", 0))
        adj_amount = _f(row.get("LINE_ITEM_ADJUSTMENT_AMOUNT", 0))
        base_amount = _f(row.get("LINE_ITEM_TOTAL", units * unit_cost))
        if base_amount == 0 and units * unit_cost != 0:
            base_amount = units * unit_cost + adj_amount
        line_tax_rate = float(tax_rate or 0)
        line_tax_total = round((units * unit_cost + adj_amount) * line_tax_rate, 2) if not is_expense else 0.0
        net_total += base_amount
        tax_total += line_tax_total
        prepped.append((is_expense, units, unit_cost, adj_amount, base_amount, line_tax_rate, line_tax_total))

    invoice_total = round(net_total + tax_total, 2)

    # Profile-driven LINE_ITEM_TAX_TYPE
    line_item_tax_type = _resolve_line_item_tax_type(st.session_state.get("active_profile_id", ""), fallback=str(st.session_state.get("tax_type", "VAT")))

    # Second pass: write lines
    for i, row in enumerate(rows, start=1):
        is_expense, units, unit_cost, adj_amount, base_amount, line_tax_rate, line_tax_total = prepped[i-1]
        try:
            date_obj = datetime.datetime.strptime(str(row.get("LINE_ITEM_DATE","")), "%Y-%m-%d").date()
        except Exception:
            date_obj = bill_end

        adj_type = "E" if is_expense else "F"

        timekeeper_name = str(row.get("TIMEKEEPER_NAME",""))
        tk_first, tk_last = "", ""
        if timekeeper_name:
            parts = timekeeper_name.split()
            if len(parts) >= 2:
                tk_first = parts[0]
                tk_last = " ".join(parts[1:])
            else:
                tk_first = timekeeper_name
                tk_last = ""

        description = str(row.get("DESCRIPTION","")).replace("|", " - ")
        task_code = "" if is_expense else str(row.get("TASK_CODE",""))
        activity_code = "" if is_expense else str(row.get("ACTIVITY_CODE",""))
        expense_code = str(row.get("EXPENSE_CODE","")) if is_expense else ""
        timekeeper_id = "" if is_expense else str(row.get("TIMEKEEPER_ID",""))
        timekeeper_class = "" if is_expense else str(row.get("TIMEKEEPER_CLASSIFICATION",""))

        client_id = str(row.get("CLIENT_ID",""))
        law_firm_id = str(row.get("LAW_FIRM_ID",""))
        client_tax_id = str(row.get("CLIENT_TAX_ID",""))
        invoice_desc = str(row.get("INVOICE_DESCRIPTION",""))

        line = [
            bill_end.strftime("%Y%m%d"),
            str(invoice_number),
             (cl_id or client_id),
            str(matter_number),
            f"{invoice_total:.2f}",
            bill_start.strftime("%Y%m%d"),
            bill_end.strftime("%Y%m%d"),
            invoice_desc,
            str(i),
            adj_type,
            f"{units:.1f}" if adj_type == "F" else f"{int(units)}",
            f"{adj_amount:.2f}",
            f"{base_amount:.2f}",
            date_obj.strftime("%Y%m%d"),
            task_code,
            expense_code,
            activity_code,
            timekeeper_id,
            description,
             (lf_id or law_firm_id),
            f"{unit_cost:.2f}",
            timekeeper_name,
            timekeeper_class,
            str(client_matter_id),
            str(po_number),
             (cl_tax_id or client_tax_id),
            str(matter_name),
            f"{tax_total:.2f}",
            f"{net_total:.2f}",
            str(invoice_currency or "USD"),
            tk_last,
            tk_first,
            "O",
            lf_name, lf_address1, lf_address2, lf_city, lf_state, lf_postcode, lf_country,
            cl_name, cl_address1, cl_address2, cl_city, cl_state, cl_postcode, cl_country,
            f"{line_tax_rate:.6f}",
            f"{line_tax_total:.2f}",
            str(line_item_tax_type),
        ]
        lines.append("|".join(map(str, line)) + "[]")

    return "\n".join(lines)
def _generate_fees(fee_count: int, timekeeper_data: List[Dict], billing_start_date: datetime.date, billing_end_date: datetime.date, task_activity_desc: List[Tuple[str, str, str]], major_task_codes: set, max_hours_per_tk_per_day: int, faker_instance: Faker, client_id: str, law_firm_id: str, invoice_desc: str) -> List[Dict]:
    """Generate fee line items for an invoice."""
    rows = []
    delta = billing_end_date - billing_start_date
    num_days = max(1, delta.days + 1)
    major_items = [item for item in task_activity_desc if item[0] in major_task_codes]
    other_items = [item for item in task_activity_desc if item[0] not in major_task_codes]
    daily_hours_tracker = {}
    MAX_DAILY_HOURS = max_hours_per_tk_per_day

    used_triples = set()
    
    for _ in range(fee_count):
        if not task_activity_desc:
            break
        tk_row = random.choice(timekeeper_data)
        timekeeper_id = tk_row["TIMEKEEPER_ID"]

        attempts = 0
        while True:
            if major_items and random.random() < 0.7:
                task_code, activity_code, description = random.choice(major_items)
            elif other_items:
                task_code, activity_code, description = random.choice(other_items)
            else:
                task_code = activity_code = description = None

            if task_code is None:
                break

            triple = (task_code, activity_code, description)
            if triple not in used_triples or attempts >= 7:
                used_triples.add(triple)
                break
            attempts += 1
        if task_code is None:
            continue

        random_day_offset = random.randint(0, num_days - 1)
        line_item_date = billing_start_date + datetime.timedelta(days=random_day_offset)
        line_item_date_str = line_item_date.strftime("%Y-%m-%d")
        current_billed_hours = daily_hours_tracker.get((line_item_date_str, timekeeper_id), 0)
        remaining_hours_capacity = MAX_DAILY_HOURS - current_billed_hours
        if remaining_hours_capacity <= 0:
            continue

        hours_to_bill = round(random.uniform(0.5, min(8.0, remaining_hours_capacity)), 1)
        if hours_to_bill == 0:
            continue

        hourly_rate = tk_row["RATE"]
        line_item_total = round(hours_to_bill * hourly_rate, 2)
        daily_hours_tracker[(line_item_date_str, timekeeper_id)] = current_billed_hours + hours_to_bill
        description = _process_description(description, faker_instance)

        rows.append({
            "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id,
            "LINE_ITEM_DATE": line_item_date_str, "TIMEKEEPER_NAME": tk_row["TIMEKEEPER_NAME"],
            "TIMEKEEPER_CLASSIFICATION": tk_row["TIMEKEEPER_CLASSIFICATION"], "TIMEKEEPER_ID": timekeeper_id,
            "TASK_CODE": task_code, "ACTIVITY_CODE": activity_code, "EXPENSE_CODE": "",
            "DESCRIPTION": description, "HOURS": hours_to_bill, "RATE": hourly_rate, "LINE_ITEM_TOTAL": line_item_total
        })
    return rows


def _generate_expenses(expense_count: int, billing_start_date: datetime.date, billing_end_date: datetime.date, client_id: str, law_firm_id: str, invoice_desc: str) -> List[Dict]:
    """Generate expense line items for an invoice with realistic amounts."""
    rows: List[Dict] = []
    delta = billing_end_date - billing_start_date
    num_days = max(1, delta.days + 1)
    # Read tunable expense settings from UI
    try:
        import streamlit as st
    except Exception:
        st = None
    mileage_rate_cfg = float(st.session_state.get("mileage_rate_e109", 0.65)) if st else 0.65
    travel_rng = st.session_state.get("travel_range_e110", (100.0, 800.0)) if st else (100.0, 800.0)
    tel_rng = st.session_state.get("telephone_range_e105", (5.0, 15.0)) if st else (5.0, 15.0)
    copying_rate = float(st.session_state.get("copying_rate_e101", 0.24)) if st else 0.24
    try:
        travel_min, travel_max = float(travel_rng[0]), float(travel_rng[1])
    except Exception:
        travel_min, travel_max = 100.0, 800.0
    try:
        tel_min, tel_max = float(tel_rng[0]), float(tel_rng[1])
    except Exception:
        tel_min, tel_max = 5.0, 15.0


    # Always include some Copying (E101)
    e101_actual_count = random.randint(1, min(3, expense_count))
    for _ in range(e101_actual_count):
        description = "Photocopies"
        expense_code = "E101"
        hours = random.randint(50, 300)  # number of pages
        rate = round(copying_rate, 2)  # per-page
        random_day_offset = random.randint(0, num_days - 1)
        line_item_date = billing_start_date + datetime.timedelta(days=random_day_offset)
        line_item_total = round(hours * rate, 2)
        row = {
            "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id,
            "LINE_ITEM_DATE": line_item_date.strftime("%Y-%m-%d"), "TIMEKEEPER_NAME": "",
            "TIMEKEEPER_CLASSIFICATION": "", "TIMEKEEPER_ID": "",
            "TASK_CODE": "", "ACTIVITY_CODE": "", "EXPENSE_CODE": expense_code, "DESCRIPTION": description,
            "HOURS": hours, "RATE": rate, "LINE_ITEM_TOTAL": line_item_total
        }
        rows.append(row)

    # Remaining expenses with category-aware amounts
    for _ in range(max(0, expense_count - e101_actual_count)):
        description = random.choice(OTHER_EXPENSE_DESCRIPTIONS)
        expense_code = CONFIG['EXPENSE_CODES'][description]
        random_day_offset = random.randint(0, num_days - 1)
        line_item_date = billing_start_date + datetime.timedelta(days=random_day_offset)

        if expense_code == "E109":  # Local travel (mileage)
            miles = random.randint(5, 50)
            hours = miles  # store miles in HOURS
            rate = mileage_rate_cfg  # mileage rate from UI
            line_item_total = round(miles * rate, 2)
        elif expense_code == "E110":  # Out-of-town travel (ticket/transport)
            hours = 1
            rate = round(random.uniform(travel_min, travel_max), 2)
            line_item_total = rate
        elif expense_code == "E105":  # Telephone
            hours = 1
            rate = round(random.uniform(tel_min, tel_max), 2)
            line_item_total = rate
        elif expense_code == "E107":  # /messenger
            hours = 1
            rate = round(random.uniform(20.0, 100.0), 2)
            line_item_total = rate
        elif expense_code == "E108":  # Postage
            hours = 1
            rate = round(random.uniform(5.0, 50.0), 2)
            line_item_total = rate
        elif expense_code == "E111":  # Meals
            hours = 1
            rate = round(random.uniform(15.0, 150.0), 2)
            line_item_total = rate
        else:
            hours = random.randint(1, 5)
            rate = round(random.uniform(10.0, 150.0), 2)
            line_item_total = round(hours * rate, 2)

        row = {
            "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id,
            "LINE_ITEM_DATE": line_item_date.strftime("%Y-%m-%d"), "TIMEKEEPER_NAME": "",
            "TIMEKEEPER_CLASSIFICATION": "", "TIMEKEEPER_ID": "",
            "TASK_CODE": "", "ACTIVITY_CODE": "", "EXPENSE_CODE": expense_code, "DESCRIPTION": description,
            "HOURS": hours, "RATE": rate, "LINE_ITEM_TOTAL": line_item_total
        }
        rows.append(row)

    return rows

def _append_two_attendee_meeting_rows(rows, timekeeper_data, billing_start_date, faker_instance, client_id, law_firm_id, invoice_desc):
    """
    Appends TWO FEE rows for a meeting with identical description (same generated name),
    identical date/hours/codes, but different timekeepers (Partner vs Associate).
    Returns the same rows list (mutated).
    """
    import random as _rand
    from datetime import date as _date

    def _norm_role(s):
        s = str(s or "").strip().lower()
        if s.startswith("partner"):
            return "partner"
        if s.startswith("associate"):
            return "associate"
        return s

    # Pick Partner and Associate
    partners   = [tk for tk in (timekeeper_data or []) if _norm_role(tk.get("TIMEKEEPER_CLASSIFICATION")) == "partner"]
    associates = [tk for tk in (timekeeper_data or []) if _norm_role(tk.get("TIMEKEEPER_CLASSIFICATION")) == "associate"]
    if not partners or not associates:
        return rows  # nothing to do

    tk_p = _rand.choice(partners)
    tk_a = _rand.choice(associates)

    # One random name used for BOTH lines
    try:
        random_name = faker_instance.name()
    except Exception:
        random_name = "John Doe"

    hardcoded_desc = (
        "Participate in litigation strategy meeting with client team to analyze opposing party's "
        "recent discovery responses and prepare for the deposition of witness {NAME_PLACEHOLDER}."
    )
    desc_final = hardcoded_desc.replace("{NAME_PLACEHOLDER}", random_name)

    # Meeting date
    meeting_date = str(billing_start_date)

    # Duration (same for both)
    dur = round(_rand.uniform(0.5, 2.5), 1)

    def _mk_base_fee():
        # This no longer relies on a pre-existing row.
        r = {
            "INVOICE_DESCRIPTION": invoice_desc,
            "CLIENT_ID": client_id,
            "LAW_FIRM_ID": law_firm_id,
            "LINE_ITEM_DATE": meeting_date,
            "DESCRIPTION": desc_final,
            "HOURS": dur,
            "TASK_CODE": "L430",        # Default Task Code for a client meeting
            "ACTIVITY_CODE": "A112",    # Default Activity Code for a client meeting
            "EXPENSE_CODE": ""
        }
        return r

    row_p = _mk_base_fee()
    row_a = _mk_base_fee()

    # Stamp TK + RATE
    rp = _force_timekeeper_on_row(row_p, tk_p.get("TIMEKEEPER_NAME", ""), timekeeper_data) or row_p
    ra = _force_timekeeper_on_row(row_a, tk_a.get("TIMEKEEPER_NAME", ""), timekeeper_data) or row_a
    
    # Append the pair so they are guaranteed to be included
    rows.extend([rp, ra])
    return rows



def _get_custom_fee_source_df():
    """Return the uploaded custom line-item DataFrame, if available."""
    try:
        df = st.session_state.get("custom_fee_df_full", None)
        if df is None:
            df = st.session_state.get("custom_fee_df", None)
        return df
    except Exception:
        return None


def _find_first_column(df, candidate_names):
    """Find the first matching column name from a list of allowed aliases."""
    if df is None:
        return None
    cols_by_upper = {str(c).strip().upper(): c for c in getattr(df, "columns", [])}
    for name in candidate_names:
        key = str(name).strip().upper()
        if key in cols_by_upper:
            return cols_by_upper[key]
    return None


def _yes_mask(series):
    """Normalize Y/N style columns and return True where the value is Y."""
    return series.astype(str).str.strip().str.upper().eq("Y")


def _exclude_mismatch_rows(df):
    """Keep MISMATCH=Y rows out of normal/vague/block-billing generation.

    Those rows are intentionally injected only when the Spend Agent > Mismatch
    checkbox is selected.
    """
    if df is None or getattr(df, "empty", True):
        return df
    mismatch_col = _find_first_column(df, ["MISMATCH", "Mismatch", "mismatch"])
    if not mismatch_col:
        return df
    return df[~_yes_mask(df[mismatch_col])]


def _get_mismatch_pool_df():
    """Return custom line-item rows where MISMATCH=Y, plus a user-facing warning if unavailable."""
    df_src = _get_custom_fee_source_df()
    if df_src is None or getattr(df_src, "empty", True):
        return None, "No Custom Line Item Details CSV is loaded, so Mismatch line items could not be added."

    mismatch_col = _find_first_column(df_src, ["MISMATCH", "Mismatch", "mismatch"])
    if not mismatch_col:
        return None, "The Custom Line Item Details CSV does not contain a MISMATCH column, so Mismatch line items could not be added."

    required = {
        "TASK_CODE": _find_first_column(df_src, ["TASK_CODE", "TASK", "Task Code", "task_code"]),
        "ACTIVITY_CODE": _find_first_column(df_src, ["ACTIVITY_CODE", "ACTIVITY", "Activity Code", "activity_code"]),
        "DESCRIPTION": _find_first_column(df_src, ["DESCRIPTION", "DESC", "Description", "description"]),
    }
    missing = [label for label, col in required.items() if not col]
    if missing:
        return None, f"The Custom Line Item Details CSV is missing required column(s) for Mismatch line items: {', '.join(missing)}."

    pool_df = df_src[_yes_mask(df_src[mismatch_col])].copy()
    if pool_df.empty:
        return None, "No rows with MISMATCH = Y were found in the Custom Line Item Details CSV."
    return pool_df, ""


def _has_mismatch_pool_rows() -> bool:
    pool_df, _ = _get_mismatch_pool_df()
    return pool_df is not None and not pool_df.empty


def _append_mismatch_line_items(
    rows: List[Dict],
    timekeeper_data: List[Dict],
    invoice_desc: str,
    client_id: str,
    law_firm_id: str,
    billing_start_date: datetime.date,
    billing_end_date: datetime.date,
    faker_instance: Faker,
    mismatch_count: Optional[int] = None,
) -> Tuple[List[Dict], List[str]]:
    """Append 3-10 Spend Agent mismatch fee lines from custom rows where MISMATCH=Y."""
    messages: List[str] = []
    pool_df, warning = _get_mismatch_pool_df()
    if warning:
        return rows, [warning]
    if pool_df is None or pool_df.empty:
        return rows, ["No Mismatch line-item source rows were available."]
    if not timekeeper_data:
        return rows, ["No timekeeper data is loaded, so Mismatch fee line items could not be added."]

    try:
        n_lines = int(mismatch_count) if mismatch_count is not None else random.randint(10, 55)
    except Exception:
        n_lines = random.randint(10, 10)
    n_lines = max(10, min(55, n_lines))

    if len(pool_df) < n_lines:
        messages.append(
            f"Requested {n_lines} Mismatch line items but only {len(pool_df)} MISMATCH = Y source row(s) were available; sampling with replacement."
        )

    picks = pool_df.sample(n=n_lines, replace=(len(pool_df) < n_lines), random_state=None)
    task_col = _find_first_column(picks, ["TASK_CODE", "TASK", "Task Code", "task_code"])
    act_col = _find_first_column(picks, ["ACTIVITY_CODE", "ACTIVITY", "Activity Code", "activity_code"])
    desc_col = _find_first_column(picks, ["DESCRIPTION", "DESC", "Description", "description"])
    tk_class_col = _find_first_column(picks, ["TK_CLASSIFICATION", "TIMEKEEPER_CLASSIFICATION", "Timekeeper Classification", "TIMEKEEPER CLASSIFICATION"])

    delta_days = max(0, (billing_end_date - billing_start_date).days)

    for _, r in picks.iterrows():
        line_item_date = billing_start_date + datetime.timedelta(days=random.randint(0, delta_days) if delta_days else 0)
        target_class = str(r.get(tk_class_col, "")).strip() if tk_class_col else ""
        tk = _pick_timekeeper_by_class(timekeeper_data, target_class) if target_class else random.choice(timekeeper_data)
        if not tk:
            continue

        hours = round(random.uniform(0.5, 3.5), 1)
        rate = float(tk.get("RATE", 0.0) or 0.0)
        desc_raw = str(r.get(desc_col, "")).strip()
        row = {
            "INVOICE_DESCRIPTION": invoice_desc,
            "CLIENT_ID": client_id,
            "LAW_FIRM_ID": law_firm_id,
            "LINE_ITEM_DATE": line_item_date.strftime("%Y-%m-%d"),
            "TIMEKEEPER_NAME": tk.get("TIMEKEEPER_NAME", ""),
            "TIMEKEEPER_CLASSIFICATION": tk.get("TIMEKEEPER_CLASSIFICATION", ""),
            "TIMEKEEPER_ID": tk.get("TIMEKEEPER_ID", ""),
            "TASK_CODE": str(r.get(task_col, "")).strip(),
            "ACTIVITY_CODE": str(r.get(act_col, "")).strip(),
            "EXPENSE_CODE": "",
            "DESCRIPTION": _process_description(desc_raw, faker_instance),
            "HOURS": float(hours),
            "RATE": rate,
            "LINE_ITEM_TOTAL": round(float(hours) * rate, 2),
            "_spend_agent_mismatch": True,
        }
        rows.append(row)

        # Capture troubleshooting details so the generated invoice can be reconciled
        # against invoice-review findings without opening the LEDES/PDF output.
        try:
            st.session_state.setdefault("mismatch_line_items_summary", []).append({
                "Invoice Number": st.session_state.get("_mismatch_invoice_number", st.session_state.get("_pp_invoice_number", "")),
                "Billing Start": st.session_state.get("_mismatch_billing_start", st.session_state.get("_pp_billing_start", "")),
                "Billing End": st.session_state.get("_mismatch_billing_end", st.session_state.get("_pp_billing_end", "")),
                "Source": "Custom Line Item Details CSV",
                "MISMATCH": "Y",
                "Line Item Date": row.get("LINE_ITEM_DATE", ""),
                "Timekeeper": row.get("TIMEKEEPER_NAME", ""),
                "Timekeeper Class": row.get("TIMEKEEPER_CLASSIFICATION", ""),
                "Task Code": row.get("TASK_CODE", ""),
                "Activity Code": row.get("ACTIVITY_CODE", ""),
                "Hours": row.get("HOURS", ""),
                "Rate": row.get("RATE", ""),
                "Line Total": row.get("LINE_ITEM_TOTAL", ""),
                "Description": row.get("DESCRIPTION", ""),
            })
        except Exception:
            # Summary capture should never block invoice generation.
            pass

    return rows, messages

def _generate_invoice_data(
    fee_count: int,
    expense_count: int,
    timekeeper_data: List[Dict],
    client_id: str,
    law_firm_id: str,
    invoice_desc: str,
    billing_start_date: datetime.date,
    billing_end_date: datetime.date,
    task_activity_desc: List[Tuple[str, str, str]],
    major_task_codes: set,
    max_hours_per_tk_per_day: int,
    num_block_billed: int,
    faker_instance: Faker,
    include_vague_items: bool
) -> Tuple[List[Dict], float]:
    """Generate invoice data using ONLY the uploaded CSV:
    - Non-block fees come from rows with Blockbilling=N
    - Block-billed fees come from rows with Blockbilling=Y (no synthetic building)
    - Expenses are generated as before
    Mandatory items are appended by the caller after this returns.
    """
    rows: List[Dict] = []
    import random, datetime as _dt

    # Get uploaded source
    try:
        df_src = _get_custom_fee_source_df()
    except Exception:
        df_src = None

    # Split source df into vague and non-vague pools
    df_non_vague_pool = None
    df_vague_pool = None
    if df_src is not None:
        if "VAGUE" in df_src.columns:
            is_vague_mask = df_src["VAGUE"].astype(str).str.strip().str.upper() == "Y"
            df_vague_pool = df_src[is_vague_mask]
            df_non_vague_pool = df_src[~is_vague_mask]
        else:
            # If no VAGUE column, all items are non-vague
            df_non_vague_pool = df_src

        # MISMATCH=Y rows are reserved for Spend Agent > Mismatch and should not
        # appear in ordinary generated fee, vague, or block-billed pools.
        df_non_vague_pool = _exclude_mismatch_rows(df_non_vague_pool)
        df_vague_pool = _exclude_mismatch_rows(df_vague_pool)


    # Helper to build a fee row
    def _mk_fee_row(desc: str, tk: Dict, date_str: str, task_code: str, act_code: str, hours: float, block: bool=False) -> Dict:
        rate = float(tk.get("RATE", 0.0))
        row = {
            "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id,
            "LINE_ITEM_DATE": date_str, "TIMEKEEPER_NAME": tk.get("TIMEKEEPER_NAME",""),
            "TIMEKEEPER_CLASSIFICATION": tk.get("TIMEKEEPER_CLASSIFICATION",""), "TIMEKEEPER_ID": tk.get("TIMEKEEPER_ID",""),
            "TASK_CODE": task_code, "ACTIVITY_CODE": act_code, "EXPENSE_CODE": "",
            "DESCRIPTION": desc,
            "HOURS": float(round(hours, 2)), "RATE": rate
        }
        row["LINE_ITEM_TOTAL"] = round(float(row["HOURS"]) * rate, 2)
        if block:
            row["_is_block_billed_from_source"] = True
            row["_is_block_billed"] = True
        return row

    # Time window
    delta_days = max(0, (billing_end_date - billing_start_date).days)

    # --- Non-block fees (N) ---
    nb_picks = []
    if fee_count > 0:
        nb_picks = _select_items_from_source(df_non_vague_pool, want_block=False, k=fee_count) if df_non_vague_pool is not None else []
    for item in nb_picks:
        day = billing_start_date + _dt.timedelta(days=random.randint(0, delta_days) if delta_days else 0)
        date_str = day.strftime("%Y-%m-%d")
        tk = _pick_timekeeper_by_class(timekeeper_data, item.get("TK_CLASSIFICATION"))
        if not tk: 
            continue
        hours_cap = float(max_hours_per_tk_per_day) if max_hours_per_tk_per_day else 6.0
        hours = round(random.uniform(0.5, max(0.6, min(3.5, hours_cap))), 1)
        processed_desc = _process_description(item["DESC"], faker_instance)
        rows.append(_mk_fee_row(processed_desc, tk, date_str, item["TASK_CODE"], item["ACTIVITY_CODE"], hours, block=False))

    # --- Block-billed fees (Y) ---
    include_blocks = True
    try:
        include_blocks = bool(st.session_state.get("include_block_billed", True))
    except Exception:
        pass
    bb_picks = []
    if include_blocks and num_block_billed > 0:
        bb_picks = _select_items_from_source(df_non_vague_pool, want_block=True, k=num_block_billed) if df_non_vague_pool is not None else []
    for item in bb_picks[:num_block_billed]:
        day = billing_start_date + _dt.timedelta(days=random.randint(0, delta_days) if delta_days else 0)
        date_str = day.strftime("%Y-%m-%d")
        tk = _pick_timekeeper_by_class(timekeeper_data, item.get("TK_CLASSIFICATION"))
        if not tk: 
            continue
        hours_cap = float(max_hours_per_tk_per_day) if max_hours_per_tk_per_day else 6.0
        hours = round(random.uniform(1.0, max(1.0, min(6.0, hours_cap))), 1)
        processed_desc = _process_description(item["DESC"], faker_instance)
        rows.append(_mk_fee_row(processed_desc, tk, date_str, item["TASK_CODE"], item["ACTIVITY_CODE"], hours, block=True))

    # --- Vague Line Items ---
    if include_vague_items and df_vague_pool is not None and not df_vague_pool.empty:
        num_vague_to_add = random.randint(1, 5)
        # Convert df to the dict format expected by the loop
        vague_pool = []
        for _, r in df_vague_pool.iterrows():
            vague_pool.append({
                "TASK_CODE": str(r.get("TASK_CODE","")).strip(),
                "ACTIVITY_CODE": str(r.get("ACTIVITY_CODE","")).strip(),
                "DESC": str(r.get("DESCRIPTION","")).strip(),
                "TK_CLASSIFICATION": str(r.get("TK_CLASSIFICATION","")).strip(),
            })
        
        if len(vague_pool) >= num_vague_to_add:
            vague_picks = random.sample(vague_pool, num_vague_to_add)
        else:
            vague_picks = vague_pool # add all available if less than desired

        for item in vague_picks:
            day = billing_start_date + _dt.timedelta(days=random.randint(0, delta_days) if delta_days else 0)
            date_str = day.strftime("%Y-%m-%d")
            tk = _pick_timekeeper_by_class(timekeeper_data, item.get("TK_CLASSIFICATION"))
            if not tk: 
                continue
            hours_cap = float(max_hours_per_tk_per_day) if max_hours_per_tk_per_day else 6.0
            hours = round(random.uniform(0.5, max(0.6, min(3.5, hours_cap))), 1)
            processed_desc = _process_description(item["DESC"], faker_instance)
            rows.append(_mk_fee_row(processed_desc, tk, date_str, item["TASK_CODE"], item["ACTIVITY_CODE"], hours, block=False))

    try:
        _multi_flag = bool(st.session_state.get("multiple_attendees_meeting", False))
    except Exception:
        _multi_flag = False
    
    if _multi_flag:
        rows = _append_two_attendee_meeting_rows(
            rows,
            timekeeper_data,
            billing_start_date,
            faker_instance,
            client_id,
            law_firm_id,
            invoice_desc
        )
    
    # --- Expenses (unchanged) ---
    if expense_count > 0:
        try:
            rows.extend(_generate_expenses(expense_count, billing_start_date, billing_end_date, client_id, law_firm_id, invoice_desc))
        except Exception:
            # Fallback: no expenses on failure
            pass

    total_amount = sum(float(r.get("LINE_ITEM_TOTAL", 0.0)) for r in rows)
    return rows, total_amount

def _ensure_mandatory_lines(
    rows: List[Dict],
    timekeeper_data: List[Dict],
    invoice_desc: str,
    client_id: str,
    law_firm_id: str,
    billing_start_date: datetime.date,
    billing_end_date: datetime.date,
    selected_items: List[str],
    *,
    randomize_amounts_per_invoice: bool = False,
) -> Tuple[List[Dict], List[str]]:
    """Ensure mandatory line items are included and return a list of any skipped items.

    If ``randomize_amounts_per_invoice`` is True, Airfare/Uber (E110) amounts will be randomized per
    invoice *only when the corresponding amount field is still in auto mode*.
    """
    delta = billing_end_date - billing_start_date
    num_days = max(1, delta.days + 1)
    skipped_items = []
    faker_local = Faker()

    def _record_partner_paralegal(row_dict: Dict, item_label: str, source: str) -> None:
        """Store a UI-friendly summary entry for Partner → Paralegal lines."""
        try:
            st.session_state.setdefault("pp_partner_paralegal_summary", []).append({
                "Invoice Number": st.session_state.get("_pp_invoice_number", ""),
                "Billing Start": st.session_state.get("_pp_billing_start", ""),
                "Billing End": st.session_state.get("_pp_billing_end", ""),
                "Mandatory Item": item_label,
                "Source": source,
                "Line Item Date": row_dict.get("LINE_ITEM_DATE", ""),
                "Timekeeper": row_dict.get("TIMEKEEPER_NAME", ""),
                "Timekeeper Class": row_dict.get("TIMEKEEPER_CLASSIFICATION", ""),
                "Task Code": row_dict.get("TASK_CODE", ""),
                "Activity Code": row_dict.get("ACTIVITY_CODE", ""),
                "Hours": row_dict.get("HOURS", ""),
                "Rate": row_dict.get("RATE", ""),
                "Line Total": row_dict.get("LINE_ITEM_TOTAL", ""),
                "Description": row_dict.get("DESCRIPTION", ""),
            })
        except Exception:
            # Never let summary capture break invoice generation
            pass


    for item_name in selected_items:
        random_day_offset = random.randint(0, num_days - 1)
        line_item_date = billing_start_date + datetime.timedelta(days=random_day_offset)
        item = CONFIG['MANDATORY_ITEMS'][item_name]

        # Special handling for items requiring UI details
        if item.get('requires_details'):
            if item_name == 'Airfare E110':
                airline = st.session_state.get('airfare_airline', 'N/A')
                flight_num = st.session_state.get('airfare_flight_number', 'N/A')
                dep_city = SFO_DEPARTURE_CITY

                # Base arrival city comes from the UI selection; if it's missing/invalid, choose a valid UA-from-SFO destination.
                arr_city = st.session_state.get('airfare_arrival_city', 'N/A')
                if arr_city not in UA_SFO_US_DESTINATIONS:
                    arr_city = _pick_ua_sfo_arrival_city()

                # If multiple invoices are being generated, optionally randomize the arrival city per invoice.
                if randomize_amounts_per_invoice and st.session_state.get('airfare_randomize_arrival_per_invoice', False):
                    arr_city = _pick_ua_sfo_arrival_city()

                is_roundtrip = st.session_state.get('airfare_roundtrip', False)
                # If generating multiple invoices, optionally randomize the amount per invoice (more realistic).
                # Respect manual overrides: only randomize when the amount is still marked as "auto".
                if randomize_amounts_per_invoice and st.session_state.get('airfare_amount_auto', True):
                    amount = round(random.uniform(500.00, 14000.00), 2)
                else:
                    amount = float(st.session_state.get('airfare_amount', 0.0))
                fare_class = st.session_state.get('airfare_fare_class', 'Economy/Coach')
                trip_type = " (Roundtrip)" if is_roundtrip else ""
                description = f"Airfare ({fare_class}): {airline} {flight_num}, {dep_city} to {arr_city}{trip_type}"
                
                row = {
                    "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id,
                    "LINE_ITEM_DATE": line_item_date.strftime("%Y-%m-%d"), "TIMEKEEPER_NAME": "",
                    "TIMEKEEPER_CLASSIFICATION": "", "TIMEKEEPER_ID": "", "TASK_CODE": "",
                    "ACTIVITY_CODE": "", "EXPENSE_CODE": "E110", "DESCRIPTION": description,
                    "HOURS": 1, "RATE": amount, "LINE_ITEM_TOTAL": amount,
                    "airfare_details": {
                        "airline": airline, "flight_number": flight_num,
                        "departure_city": dep_city, "arrival_city": arr_city,
                        "is_roundtrip": is_roundtrip, "amount": amount,
                        "fare_class": fare_class
                    }
                }
                rows.append(row)
            elif item_name == 'Uber E110':
                # If generating multiple invoices, optionally randomize the amount per invoice (more realistic).
                # Respect manual overrides: only randomize when the amount is still marked as "auto".
                if randomize_amounts_per_invoice and st.session_state.get('uber_amount_auto', True):
                    amount = round(random.uniform(15.00, 65.00), 2)
                else:
                    amount = float(st.session_state.get('uber_amount', 0.0))
                description = item['desc']
                row = {
                    "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id,
                    "LINE_ITEM_DATE": line_item_date.strftime("%Y-%m-%d"), "TIMEKEEPER_NAME": "",
                    "TIMEKEEPER_CLASSIFICATION": "", "TIMEKEEPER_ID": "", "TASK_CODE": "",
                    "ACTIVITY_CODE": "", "EXPENSE_CODE": "E110", "DESCRIPTION": description,
                    "HOURS": 1, "RATE": amount, "LINE_ITEM_TOTAL": amount
                }
                rows.append(row)
        # Original logic for other items
        elif item['is_expense']:
            row = {
                "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id,
                "LINE_ITEM_DATE": line_item_date.strftime("%Y-%m-%d"), "TIMEKEEPER_NAME": "",
                "TIMEKEEPER_CLASSIFICATION": "", "TIMEKEEPER_ID": "", "TASK_CODE": "",
                "ACTIVITY_CODE": "", "EXPENSE_CODE": item['expense_code'], "DESCRIPTION": item['desc'],
                "HOURS": random.randint(1, 10), "RATE": round(random.uniform(5.0, 100.0), 2)
            }
            row["LINE_ITEM_TOTAL"] = round(row["HOURS"] * row["RATE"], 2)
            rows.append(row)
        else: # Fee items
            # Choose the timekeeper name to force
            forced_name = item['tk_name']  # default from CONFIG

            # --- Partner → Paralegal: add multiple Partner-billed lines using Paralegal-tagged source rows ---
            if _is_partner_paralegal_item(item_name):
                # Prefer a Partner from the uploaded TK CSV (if any). This is what triggers the guideline test.
                partners = [
                    tk for tk in (_get_timekeepers() or [])
                    if "partner" in str(tk.get("TIMEKEEPER_CLASSIFICATION", "")).lower()
                ]
                if partners:
                    forced_name = random.choice(partners).get("TIMEKEEPER_NAME", forced_name)
                else:
                    tk_match = _find_timekeeper_by_classification(_get_timekeepers(), "Partner")
                    if tk_match:
                        forced_name = tk_match.get("TIMEKEEPER_NAME", forced_name)

                # Determine how many Partner → Paralegal lines to add for THIS invoice.
                n_lines = int(st.session_state.get("_pp_lines_this_invoice", 0) or 0)
                if n_lines <= 0:
                    base_n = int(st.session_state.get("pp_lines_per_invoice", 1) or 1)
                    base_n = max(1, base_n)
                    if st.session_state.get("pp_randomize_count_per_invoice", False):
                        n_lines = random.randint(1, base_n)
                    else:
                        n_lines = base_n

                # Pull Paralegal-tagged tasks/descriptions from the uploaded line-item CSV (if available).
                df_src = None
                try:
                    df_src = _get_custom_fee_source_df()
                except Exception:
                    df_src = None

                def _col(df, names):
                    for n in names:
                        if n in df.columns:
                            return n
                    return None

                pool_df = None
                if df_src is not None:
                    tkc = _col(df_src, ["TK_CLASSIFICATION", "TIMEKEEPER_CLASSIFICATION", "Timekeeper Classification", "TIMEKEEPER CLASSIFICATION"])
                    task_c = _col(df_src, ["TASK_CODE", "TASK", "Task Code", "task_code"])
                    act_c = _col(df_src, ["ACTIVITY_CODE", "ACTIVITY", "Activity Code", "activity_code"])
                    desc_c = _col(df_src, ["DESCRIPTION", "DESC", "Description", "description"])
                    if tkc and task_c and act_c and desc_c:
                        tmp = df_src.copy()
                        tmp["_tkc_norm"] = tmp[tkc].astype(str).str.strip().str.lower()
                        tmp = tmp[tmp["_tkc_norm"] == "paralegal"]

                        # Optional: filter out vague and block-billed rows when those columns exist.
                        if "VAGUE" in tmp.columns:
                            tmp = tmp[tmp["VAGUE"].astype(str).str.strip().str.upper() != "Y"]
                        bbcol = _col(tmp, ["Blockbilling", "BLOCKBILLING", "Blockbilled", "BlockBilled"])
                        if bbcol:
                            tmp = tmp[tmp[bbcol].astype(str).str.strip().str.upper() != "Y"]

                        if not tmp.empty:
                            pool_df = tmp

                added_any = False

                if pool_df is not None:
                    picks = pool_df.sample(
                        n=n_lines,
                        replace=(len(pool_df) < n_lines),
                        random_state=None
                    )
                    # Re-resolve columns on the sampled frame (defensive)
                    task_c = _col(picks, ["TASK_CODE", "TASK", "Task Code", "task_code"])
                    act_c = _col(picks, ["ACTIVITY_CODE", "ACTIVITY", "Activity Code", "activity_code"])
                    desc_c = _col(picks, ["DESCRIPTION", "DESC", "Description", "description"])

                    for _, r in picks.iterrows():
                        random_day_offset = random.randint(0, num_days - 1)
                        line_item_date = billing_start_date + datetime.timedelta(days=random_day_offset)

                        desc_raw = str(r.get(desc_c, "")).strip()
                        row_template = {
                            "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id,
                            "LINE_ITEM_DATE": line_item_date.strftime("%Y-%m-%d"), "TIMEKEEPER_NAME": forced_name,
                            "TIMEKEEPER_CLASSIFICATION": "", "TIMEKEEPER_ID": "",
                            "TASK_CODE": str(r.get(task_c, "")).strip(),
                            "ACTIVITY_CODE": str(r.get(act_c, "")).strip(),
                            "EXPENSE_CODE": "",
                            "DESCRIPTION": _process_description(desc_raw, faker_local),
                            "HOURS": round(random.uniform(0.5, 3.0), 1), "RATE": 0.0
                        }

                        processed_row = _force_timekeeper_on_row(row_template, forced_name, _get_timekeepers())
                        if processed_row:
                            rows.append(processed_row)
                            _record_partner_paralegal(processed_row, item_name, "CSV Paralegal Pool")
                            added_any = True
                else:
                    # Fallback: repeat the configured mandatory item fields N times.
                    for _ in range(n_lines):
                        random_day_offset = random.randint(0, num_days - 1)
                        line_item_date = billing_start_date + datetime.timedelta(days=random_day_offset)

                        row_template = {
                            "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id,
                            "LINE_ITEM_DATE": line_item_date.strftime("%Y-%m-%d"), "TIMEKEEPER_NAME": forced_name,
                            "TIMEKEEPER_CLASSIFICATION": "", "TIMEKEEPER_ID": "", "TASK_CODE": item['task'],
                            "ACTIVITY_CODE": item['activity'], "EXPENSE_CODE": "",
                            "DESCRIPTION": _process_description(item.get('desc', ''), faker_local),
                            "HOURS": round(random.uniform(0.5, 3.0), 1), "RATE": 0.0
                        }

                        processed_row = _force_timekeeper_on_row(row_template, forced_name, _get_timekeepers())
                        if processed_row:
                            rows.append(processed_row)
                            _record_partner_paralegal(processed_row, item_name, "Fallback Mandatory Item")
                            added_any = True

                if not added_any:
                    skipped_items.append(item_name)
                continue

            # --- Default behavior for other mandatory fee items ---
            row_template = {
                "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id,
                "LINE_ITEM_DATE": line_item_date.strftime("%Y-%m-%d"), "TIMEKEEPER_NAME": forced_name,
                "TIMEKEEPER_CLASSIFICATION": "", "TIMEKEEPER_ID": "", "TASK_CODE": item['task'],
                "ACTIVITY_CODE": item['activity'], "EXPENSE_CODE": "", "DESCRIPTION": item['desc'],
                "HOURS": round(random.uniform(0.5, 8.0), 1), "RATE": 0.0
            }

            processed_row = _force_timekeeper_on_row(row_template, forced_name, _get_timekeepers())

            # Only add the row if the timekeeper was found
            if processed_row:
                rows.append(processed_row)
            else:
                skipped_items.append(item_name) # Otherwise, log it as skipped


    return rows, skipped_items

def _validate_image_bytes(image_bytes: bytes) -> bool:
    """Validate that the provided bytes represent a valid image."""
    try:
        img = PILImage.open(io.BytesIO(image_bytes))
        img.verify()
        return True
    except Exception:
        return False

def _get_logo_bytes(uploaded_logo: Optional[Any], law_firm_id: str, use_custom: bool) -> bytes:
    """Get logo bytes from uploaded file or default path."""
    if use_custom and uploaded_logo:
        try:
            logo_bytes = uploaded_logo.read()
            if _validate_image_bytes(logo_bytes):
                return logo_bytes
            st.warning("Uploaded logo is not a valid JPEG or PNG. Using default logo.")
        except Exception as e:
            logging.error(f"Error reading uploaded logo: {e}")
            st.warning("Failed to read uploaded logo. Using default logo.")
    
    logo_file_name = "nelsonmurdock2.jpg" if law_firm_id == CONFIG['DEFAULT_LAW_FIRM_ID'] else "icon.jpg"
    script_dir = os.path.dirname(__file__)
    logo_path = os.path.join(script_dir, "assets", logo_file_name)
    try:
        with open(logo_path, "rb") as f:
            logo_bytes = f.read()
        if _validate_image_bytes(logo_bytes):
            return logo_bytes
        st.warning(f"Default logo ({logo_file_name}) is not a valid JPEG or PNG. Using placeholder.")
    except Exception as e:
        logging.error(f"Logo load failed: {e}")
        st.warning(f"Logo file ({logo_file_name}) not found or invalid. Using placeholder.")
    
    img = PILImage.new("RGB", (128, 128), color="white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()
    draw.text((10, 20), "Logo", font=font, fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()


# #############################################################################
# ##### PDF CREATION FUNCTION WITH REQUESTED CHANGES ##########################
# #############################################################################
def _create_pdf_invoice(
    df: pd.DataFrame,
    total_amount: float,
    invoice_number: str,
    invoice_date: datetime.date,
    billing_start_date: datetime.date,
    billing_end_date: datetime.date,
    client_id: str,
    law_firm_id: str,
    logo_bytes: bytes | None = None,
    include_logo: bool = False,
    client_name: str = "",
    law_firm_name: str = "",
    ledes_version: str = "1998B",
    matter_name: str = "",
    po_number: str = "",
    client_matter_id: str = "",
    invoice_currency: str = "USD",
    tax_rate: float = 0.19
) -> io.BytesIO:
    """Generate a PDF invoice matching the provided format."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []
    styles = getSampleStyleSheet()

    # Styles
    header_info_style = ParagraphStyle('HeaderInfo', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=12, leading=14, alignment=TA_LEFT)
    client_info_style = ParagraphStyle('ClientInfo', parent=header_info_style, alignment=TA_RIGHT)
    table_header_style = ParagraphStyle('TableHeader', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9, leading=12, alignment=TA_CENTER, wordWrap='CJK')
    table_data_style = ParagraphStyle('TableData', parent=styles['Normal'], fontName='Helvetica', fontSize=9, leading=12, alignment=TA_LEFT, wordWrap='CJK')
    right_align_style = styles['Heading4']

    # Header info
    lf_name = law_firm_name or "Law Firm"
    cl_name = client_name or "Client"
    law_firm_info = f"{lf_name}<br/>{law_firm_id}<br/>One Park Avenue<br/>Manhattan, NY 10003"
    client_info   = f"{cl_name}<br/>{client_id}<br/>1360 Post Oak Blvd<br/>Houston, TX 77056"
    law_firm_para = Paragraph(law_firm_info, header_info_style)
    client_para = Paragraph(client_info, client_info_style)

    header_left_content = law_firm_para
    if include_logo and logo_bytes:
        try:
            if not _validate_image_bytes(logo_bytes):
                raise ValueError("Invalid logo bytes")
            #img = Image(io.BytesIO(logo_bytes), width=0.6 * inch, height=0.6 * inch, kind='direct', hAlign='LEFT')
            img = RLImage(io.BytesIO(logo_bytes), width=0.6 * inch, height=0.6 * inch, kind="direct", hAlign="LEFT")
            img._restrictSize(0.6 * inch, 0.6 * inch)
            img.alt = "Law Firm Logo"
            inner_table_data = [[img, Paragraph(law_firm_info, header_info_style)]]
            inner_table = Table(inner_table_data, colWidths=[0.7 * inch, None])
            inner_table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (1, 0), (1, 0), 6)]))
            header_left_content = inner_table
        except Exception as e:
            logging.error(f"Error adding logo to PDF: {e}")
            header_left_content = law_firm_para

    header_data = [[header_left_content, client_para]]
    header_table = Table(header_data, colWidths=[3.5 * inch, 4.0 * inch])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (0, 0), 0),
        ('RIGHTPADDING', (0, 0), (0, 0), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 0.1 * inch))

    # Invoice meta
    invoice_info = f"Invoice #: {invoice_number}<br/>Invoice Date: {invoice_date.strftime('%Y-%m-%d')}<br/>Billing Period: {billing_start_date.strftime('%Y-%m-%d')} to {billing_end_date.strftime('%Y-%m-%d')}"
    invoice_para = Paragraph(invoice_info, right_align_style)

    if ledes_version == "1998BIv2":
        tax_data = [
            [Paragraph("Matter Name:", styles['Normal']), Paragraph(matter_name or "-", styles['Normal'])],
            [Paragraph("PO Number:", styles['Normal']), Paragraph(po_number or "-", styles['Normal'])],
            [Paragraph("Client Matter ID:", styles['Normal']), Paragraph(client_matter_id or "-", styles['Normal'])],
            [Paragraph("Invoice Currency:", styles['Normal']), Paragraph(invoice_currency, styles['Normal'])],
            [Paragraph("Tax Rate:", styles['Normal']), Paragraph(f"{tax_rate:.2f}", styles['Normal'])],
        ]
        tax_table = Table(tax_data, colWidths=[1.6 * inch, 5.9 * inch])
        elements.append(tax_table)
        elements.append(Spacer(1, 0.2 * inch))

    invoice_table = Table([[invoice_para]], colWidths=[7.5 * inch])
    invoice_table.setStyle(TableStyle([('ALIGN', (0, 0), (-1, -1), 'RIGHT'), ('VALIGN', (0, 0), (-1, -1), 'TOP')]))
    elements.append(invoice_table)
    elements.append(Spacer(1, 0.1 * inch))

    # **CHANGE 1: Update table headers**
    data = [[
        Paragraph("Date", table_header_style),
        Paragraph("Type", table_header_style),
        Paragraph("Task<br/>Code", table_header_style),
        Paragraph("Activity<br/>Code", table_header_style),
        Paragraph("Exp<br/>Code", table_header_style),
        Paragraph("Timekeeper<br/>ID", table_header_style),
        Paragraph("Description", table_header_style),
        Paragraph("Hours", table_header_style),
        Paragraph("Rate", table_header_style),
        Paragraph("Total", table_header_style),
    ]]

    # **CHANGE 2: Loop through rows and populate new data structure**
    for _, row in df.iterrows():
        is_expense = bool(row.get("EXPENSE_CODE"))

        # Logic for all columns based on your requests
        date = row["LINE_ITEM_DATE"]
        line_type = "E" if is_expense else "F"
        task_code = row.get("TASK_CODE", "") if not is_expense else ""
        activity_code = row.get("ACTIVITY_CODE", "") if not is_expense else ""
        expense_code = row.get("EXPENSE_CODE", "") if is_expense else ""
        timekeeper_id = Paragraph(row.get("TIMEKEEPER_ID", "") if not is_expense else "N/A", table_data_style)
        description = Paragraph(row["DESCRIPTION"], table_data_style)
        hours = f"{row['HOURS']:.1f}" if not is_expense else f"{int(row['HOURS'])}"
        rate = f"${row['RATE']:.2f}" if row["RATE"] else "N/A"
        total = f"${row['LINE_ITEM_TOTAL']:.2f}"
        
        data.append([
            date,
            line_type,
            task_code,
            activity_code,
            expense_code,
            timekeeper_id,
            description,
            hours,
            rate,
            total
        ])

    # **CHANGE 3: Adjust column widths to fit the new table structure**
    table = Table(data, colWidths=[
        0.7 * inch,  # Date
        0.4 * inch,  # Type
        0.5 * inch,  # Task Code
        0.5 * inch,  # Activity Code
        0.5 * inch,  # Exp Code
        0.8 * inch,  # Timekeeper ID
        2.1 * inch,  # Description
        0.5 * inch,  # Hours
        0.6 * inch,  # Rate
        0.7 * inch,  # Total
    ])

    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (0, 0), (0, -1), 'CENTER'), # Date
        ('ALIGN', (1, 1), (1, -1), 'CENTER'), # Type
        ('ALIGN', (2, 1), (5, -1), 'CENTER'), # Codes & TK ID
        ('ALIGN', (7, 0), (7, -1), 'CENTER'), # Hours
        ('ALIGN', (8, 0), (9, -1), 'RIGHT'),  # Rate & Total
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    elements.append(table)

    # Totals block (right-aligned) - No changes needed here
    if 'EXPENSE_CODE' in df.columns:
        is_fee = df['EXPENSE_CODE'].fillna('').eq('')
        fees_total = df.loc[is_fee, 'LINE_ITEM_TOTAL'].sum()
        expenses_total = df.loc[~is_fee, 'LINE_ITEM_TOTAL'].sum()
    else:
        fees_total = df['LINE_ITEM_TOTAL'].sum()
        expenses_total = 0.0


    elements.append(Spacer(1, 0.2 * inch))

    totals_style_label = ParagraphStyle('TotalsLabel', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11, alignment=TA_RIGHT)
    totals_style_amt   = ParagraphStyle('TotalsAmt',   parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11, alignment=TA_RIGHT)

    totals_data = [
        [Paragraph("Total Fees:", totals_style_label), Paragraph(f"${fees_total:,.2f}", totals_style_amt)],
        [Paragraph("Total Expenses:", totals_style_label), Paragraph(f"${expenses_total:,.2f}", totals_style_amt)],
        [Paragraph("Invoice Total:", totals_style_label), Paragraph(f"${total_amount:,.2f}", totals_style_amt)],
    ]
    totals_table = Table(totals_data, colWidths=[1.6 * inch, 1.2 * inch], hAlign='RIGHT')
    totals_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    elements.append(totals_table)

    if ledes_version == "1998BIv2":
        subtotal_for_tax = df['LINE_ITEM_TOTAL'].sum()
        tax_amount_calc = round(subtotal_for_tax * float(tax_rate), 2)
        grand_total_calc = subtotal_for_tax + tax_amount_calc
        totals_data_extra = [[Paragraph('Tax:', styles['Normal']), Paragraph(f"${tax_amount_calc:,.2f}", styles['Normal'])],
                             [Paragraph('Invoice Total:', styles['Normal']), Paragraph(f"${grand_total_calc:,.2f}", styles['Normal'])]]
        totals_table_extra = Table(totals_data_extra, colWidths=[1.5*inch, 1.5*inch], hAlign='RIGHT')
        elements.append(totals_table_extra)

    doc.build(elements)
    buffer.seek(0)
    return buffer

def _create_receipt_image(expense_row: dict, faker_instance: Faker) -> Tuple[str, io.BytesIO]:
    """Enhanced realistic receipt generator (see chat notes for details)."""
    width, height = 600, 950
    bg = (252, 252, 252)
    fg = (20, 20, 20)
    faint = (90, 90, 90)
    line_y_gap = 28

    # Default receipt style values
    rcpt_scale = 1.0
    rcpt_line_weight = 1
    rcpt_dashed = False

    TAX_MAP = {
        "E111": 0.085,
        "E110": 0.000,
        "E109": 0.000,
        "E108": 0.000,
        "E115": 0.085,
        "E116": 0.085,
        "E117": 0.085,
    }

    def money(x):
        return f"${x:,.2f}"

    def mask_card():
        brands = ["VISA", "MC", "AMEX", "DISC"]
        brand = random.choice(brands)
        if brand == "AMEX":
            masked = f"{brand} ****-******-*{random.randint(1000,9999)}"
        else:
            masked = f"{brand} ****-****-****-{random.randint(1000,9999)}"
        return masked

    def auth_code():
        return f"APPROVED  AUTH {random.randint(100000, 999999)}  REF {random.randint(1000,9999)}"

    def pick_items(expense_code: str, desc: str, total: float):
        items = []
        if expense_code == "E111":
            qtys = [1, 2]
            entree_qty = random.choice(qtys)
            entree_unit = round(total * 0.45 / max(entree_qty,1), 2)
            drink_unit = round(total * 0.15, 2)
            items = [
                ("Entree", entree_qty, entree_unit, round(entree_qty*entree_unit,2)),
                ("Beverage", 1, drink_unit, drink_unit),
            ]
        elif expense_code == "E110": # This is now for generic travel like rideshare
            miles = random.randint(3, 20)
            base = round(max(2.5, total * 0.15), 2)
            per_mile = round(max(0.9, (total - base) / max(miles,1)), 2)
            items = [
                ("Base Fare", 1, base, base),
                (f"Distance {miles} mi", 1, per_mile*miles, round(per_mile*miles,2)),
            ]
        elif expense_code == "E108":
            weight = random.uniform(0.5, 4.0)
            unit = round(total, 2)
            items = [(f"USPS Priority Mail {weight:.1f} lb", 1, unit, unit)]
        elif expense_code in ("E115","E116"):
            pages = random.randint(50, 300)
            unit = round(max(2.0, min(6.0, total/pages)), 2)
            items = [(f"Transcript ({pages} pages)", pages, unit, round(pages*unit,2))]
        else:
            n = random.choice([2,3])
            remaining = total
            for i in range(n-1):
                part = round(total * random.uniform(0.2, 0.5), 2)
                remaining = round(remaining - part, 2)
                items.append((f"{desc[:20]} {i+1}", 1, part, part))
            items.append((f"{desc[:20]} {n}", 1, remaining, remaining))
        return items

    m_addr = faker_instance.address().replace("\n", ", ")
    m_phone = faker_instance.phone_number()
    
    try:
        line_item_date = datetime.datetime.strptime(expense_row["LINE_ITEM_DATE"], "%Y-%m-%d").date()
    except Exception:
        line_item_date = datetime.datetime.today().date()
    exp_code = str(expense_row.get("EXPENSE_CODE", "")).strip()
    desc = str(expense_row.get("DESCRIPTION","")).strip() or "Item"
    total_amount = float(expense_row.get("LINE_ITEM_TOTAL", 0.0))

    # Check for specific airfare details to build the receipt content
    airfare_details = expense_row.get("airfare_details")
    if isinstance(airfare_details, dict):
        merchant = airfare_details.get("airline", faker_instance.company())
        # Create realistic line items for airfare
        base_fare = round(total_amount * 0.75, 2)
        taxes_fees = round(total_amount - base_fare, 2)
        trip_type = "Roundtrip" if airfare_details.get("is_roundtrip") else "One-way"
        fare_class = airfare_details.get("fare_class", "Coach")
        flight_desc = f"Flight {airfare_details.get('flight_number', '')}"
        route_desc = f"{airfare_details.get('departure_city', '')} -> {airfare_details.get('arrival_city', '')}"
        items = [
            (f"{trip_type} Airfare: {flight_desc}", 1, base_fare, base_fare),
            (f"Class: {fare_class}", 0, 0, 0),
            (f"Route: {route_desc}", 0, 0, 0),
            ("Taxes and Carrier Fees", 1, taxes_fees, taxes_fees)
        ]
        tax = 0.0
        tip = 0.0
    else:
        # Original logic if no specific airfare details are passed
        merchant = faker_instance.company()
        items = pick_items(exp_code, desc, total_amount)
        tax_rate = TAX_MAP.get(exp_code, 0.085 if sum(i[3] for i in items) > 0 else 0.0)
        tax = round(sum(i[3] for i in items) * tax_rate, 2)

        tip = 0.0
        if exp_code in ("E111", "E110"):
            subtotal_for_tip = sum(i[3] for i in items)
            target_total = total_amount
            tip_guess = 0.15 if exp_code == "E111" else 0.10
            tip = round(subtotal_for_tip * tip_guess, 2)
            over = round((subtotal_for_tip + tax + tip) - target_total, 2)
            if over > 0:
                tip = max(0.0, round(tip - over, 2))
            else:
                tip = round(tip + abs(over), 2)
    
    subtotal = round(sum(x[3] for x in items), 2)
    grand = round(subtotal + tax + tip, 2)
    drift = round(total_amount - grand, 2)
    if abs(drift) >= 0.01 and items:
        name, qty, unit, line_total = items[-1]
        line_total = round(line_total + drift, 2)
        unit = round(line_total / max(qty, 1) if qty > 0 else line_total, 2)
        items[-1] = (name, qty, unit, line_total)
        subtotal = round(sum(x[3] for x in items), 2)
        grand = round(subtotal + tax + tip, 2)

    img = PILImage.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)

    try:
        title_font = ImageFont.truetype("arial.ttf", max(12, int(34*rcpt_scale)))
        header_font = ImageFont.truetype("arial.ttf", max(10, int(22*rcpt_scale)))
        mono_font = ImageFont.truetype("arial.ttf", max(10, int(22*rcpt_scale)))
        small_font = ImageFont.truetype("arial.ttf", max(8, int(18*rcpt_scale)))
        tiny_font = ImageFont.truetype("arial.ttf", max(8, int(15*rcpt_scale)))
    except Exception:
        title_font = ImageFont.load_default()
        header_font = ImageFont.load_default()
        mono_font = ImageFont.load_default()
        small_font = ImageFont.load_default()
        tiny_font = ImageFont.load_default()

    def draw_hr(y, pad_left=40, pad_right=40, weight=1, dashed=False):
        if dashed:
            x = pad_left
            dash = 8
            gap = 6
            while x < width - pad_right:
                x2 = min(x + dash, width - pad_right)
                draw.line([(x, y), (x2, y)], fill=faint, width=weight)
                x = x2 + gap
        else:
            draw.line([(pad_left, y), (width - pad_right, y)], fill=faint, width=weight)

    y = 30
    title = "RECEIPT"
    tw = draw.textlength(title, font=title_font)
    draw.text(((width - tw) / 2, y), title, font=title_font, fill=fg)
    y += 42

    for line in (merchant, m_addr, f"Tel: {m_phone}"):
        draw.text((40, y), line, font=header_font, fill=fg)
        y += 26
    y += 6
    draw_hr(y, weight=rcpt_line_weight, dashed=rcpt_dashed); y += 14

    rnum = f"{random.randint(100000, 999999)}-{random.randint(10,99)}"
    draw.text((40, y), f"Date: {line_item_date.strftime('%a %b %d, %Y')}", font=mono_font, fill=fg)
    draw.text((width-300, y), f"Receipt #: {rnum}", font=mono_font, fill=fg)
    y += 30
    # Cashier line removed
    draw_hr(y, weight=rcpt_line_weight, dashed=rcpt_dashed); y += 16

    draw.text((40, y), "Item", font=small_font, fill=(90,90,90))
    draw.text((width-255, y), "Qty", font=small_font, fill=(90,90,90))
    draw.text((width-180, y), "Price", font=small_font, fill=(90,90,90))
    draw.text((width-95, y), "Total", font=small_font, fill=(90,90,90))
    y += 22

    import textwrap as _tw
    for name, qty, unit, line_total in items:
        lines = _tw.wrap(name, width=32) or ["Item"]
        first = True
        for wrap_line in lines:
            draw.text((40, y), wrap_line, font=mono_font, fill=fg)
            if first:
                if qty > 0: # Only show qty/price if relevant
                    draw.text((width-245, y), str(qty), font=mono_font, fill=fg)
                    draw.text((width-180, y), money(unit), font=mono_font, fill=fg)
                draw.text((width-95, y), money(line_total), font=mono_font, fill=fg)
                first = False
            y += line_y_gap-8
        y += 2
    draw_hr(y, weight=rcpt_line_weight, dashed=rcpt_dashed); y += 14

    def right_label(label, val):
        nonlocal y
        draw.text((width-220, y), label, font=mono_font, fill=fg)
        draw.text((width-95, y), money(val), font=mono_font, fill=fg)
        y += 24

    right_label("Subtotal", subtotal)
    if tax > 0:
        right_label(f"Tax ({int(tax_rate*100)}%)", tax)
    if tip > 0:
        right_label("Tip", tip)
    draw.text((width-220, y), "TOTAL", font=header_font, fill=fg)
    draw.text((width-95, y), money(round(subtotal + tax + tip, 2)), font=header_font, fill=fg)
    y += 30
    draw_hr(y, weight=rcpt_line_weight, dashed=rcpt_dashed); y += 14

    pm = mask_card()
    draw.text((40, y), pm, font=mono_font, fill=fg)
    y += 26
    draw.text((40, y), auth_code(), font=mono_font, fill=(90,90,90))
    y += 10
    draw_hr(y, weight=rcpt_line_weight, dashed=rcpt_dashed); y += 14
    
    # Policy text removed

    y = height - 80
    x = 40
    random.seed(rnum)
    for _ in range(60):
        bar_h = random.randint(20, 50)
        bar_w = random.choice([1,1,2])
        draw.rectangle([x, y, x+bar_w, y+bar_h], fill=(90,90,90))
        x += bar_w + 3
        if x > width - 40:
            break

    img_buffer = io.BytesIO()
    img.save(img_buffer, format="PNG")
    img_buffer.seek(0)

    filename = f"Receipt_{exp_code}_{line_item_date.strftime('%Y%m%d')}.png"
    return filename, img_buffer
def _customize_email_body(matter_number: str, invoice_number: str) -> Tuple[str, str]:
    """Customize email subject and body with matter and invoice number."""
    subject = st.session_state.get("email_subject", f"LEDES Invoice for {matter_number} (Invoice #{invoice_number})")
    body = st.session_state.get("email_body", f"Please find the attached invoice files for matter {matter_number}.\n\nBest regards,\nYour Law Firm")
    subject = subject.format(matter_number=matter_number, invoice_number=invoice_number)
    body = body.format(matter_number=matter_number, invoice_number=invoice_number)
    return subject, body

def _send_email_with_attachment(recipient_email: str, subject: str, body: str, attachments: List[Tuple[str, bytes]]) -> bool:
    """Send email with attachments."""
    try:
        sender_email = st.secrets.email.email_from
        password = st.secrets.email.email_password
    except AttributeError:
        st.error("Email credentials not configured in secrets.toml")
        return False
    
    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = recipient_email
    msg['Subject'] = subject

    msg.attach(MIMEText(body, 'plain'))
    for filename, data in attachments:
        part = MIMEApplication(data, Name=filename)
        part['Content-Disposition'] = f'attachment; filename="{filename}"'
        msg.attach(part)
    
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender_email, password)
            server.send_message(msg)
        st.success(f"Email sent successfully to {recipient_email}!")
        return True
    except Exception as e:
        st.error(f"Error sending email: {e}")
        logging.error(f"Email sending failed: {e}")
        return False

# --- Streamlit App ---
st.markdown("<h1 style='color: #1E1E1E;'>LEDES Invoice Generator</h1>", unsafe_allow_html=True)
st.markdown("Generate and optionally email LEDES and PDF invoices.", unsafe_allow_html=True)

# Initialize send_email in session state
if "send_email" not in st.session_state:
    st.session_state.send_email = False

# Callback for updating send_email state
def update_send_email():
    st.session_state.send_email = st.session_state.send_email_checkbox_output
    logging.debug(f"Updated st.session_state.send_email to {st.session_state.send_email}")

st.markdown("<h3 style='color: #1E1E1E;'>Email Invoices</h3>", unsafe_allow_html=True)
st.checkbox(
    "Send Invoices via Email",
    value=st.session_state.send_email,
    key="send_email_checkbox_output",
    on_change=update_send_email
)


# --- Sidebar Reorganization ---

# Helper function to read file data for buttons
def read_file_for_download(path):
    try:
        with open(path, "rb") as fp:
            return fp.read()
    except FileNotFoundError:
        st.sidebar.error(f"File not found: {os.path.basename(path)}")
        return None

st.sidebar.markdown("## Downloads")

with st.sidebar.expander("Timekeeper Downloads"):
    # OnitX Timekeepers
    onitx_Nelson_usd_tk_data = read_file_for_download("assets/onitx_tk.csv")
    if onitx_Nelson_usd_tk_data:
        st.download_button("OnitX - Nelson - USD", onitx_Nelson_usd_tk_data, "OnitX_Nelson_USD_tk.csv", "text/csv")

    # OnitX_SS&E Timekeepers - CAD
    onitx_SSE_cad_tk_data = read_file_for_download("assets/onitx_SS&E_cad_tk.csv")
    if onitx_SSE_cad_tk_data:
        st.download_button("OnitX - SS&E - CAD", onitx_SSE_cad_tk_data, "OnitX_SS&E_CAD_tk.csv", "text/csv")
    
    # OnitX Nelson Timekeepers - EUR
    onitx_Nelson_eur_tk_data = read_file_for_download("assets/onitx_Nelson_eur_tk.csv")
    if onitx_Nelson_eur_tk_data:
        st.download_button("OnitX - Nelson - EUR", onitx_Nelson_eur_tk_data, "OnitX_Nelson_EUR_tk.csv", "text/csv")

    # OnitX Nelson Timekeepers - GBP
    onitx_Nelson_gbp_tk_data = read_file_for_download("assets/onitx_Nelson_gbp_tk.csv")
    if onitx_Nelson_gbp_tk_data:
        st.download_button("OnitX - Nelson - GBP", onitx_Nelson_eur_tk_data, "OnitX_Nelson_GBP_tk.csv", "text/csv")
    
    # Unity Timekeepers
    sl_tk_data_jdc = read_file_for_download("assets/unity_tk - JDC.csv")
    if sl_tk_data_jdc:
        st.download_button("Unity - JDC", sl_tk_data_jdc, "unity_tk - JDC.csv", "text/csv")
    
    sl_tk_data_kirkland = read_file_for_download("assets/unity_tk - Kirkland.csv")
    if sl_tk_data_kirkland:
        st.download_button("Unity - Kirkland", sl_tk_data_kirkland, "unity_tk - Kirkland.csv", "text/csv")

    sl_tk_data_latham = read_file_for_download("assets/unity_tk - Latham.csv")
    if sl_tk_data_latham:
        st.download_button("Unity - Latham", sl_tk_data_latham, "unity_tk - Latham.csv", "text/csv")

    sl_tk_data_davis = read_file_for_download("assets/unity_tk - Davis.csv")
    if sl_tk_data_davis:
        st.download_button("Unity - Davis", sl_tk_data_davis, "unity_tk - Davis.csv", "text/csv")

    sl_tk_data_cravath = read_file_for_download("assets/unity_tk - Cravath.csv")
    if sl_tk_data_cravath:
        st.download_button("Unity - Cravath", sl_tk_data_cravath, "unity_tk - Cravath.csv", "text/csv")

    sl_tk_data_whitaker = read_file_for_download("assets/unity_tk - Whitaker.csv")
    if sl_tk_data_whitaker:
        st.download_button("Unity - Whitaker", sl_tk_data_whitaker, "unity_tk - Whitaker.csv", "text/csv")

    # Unity Timekeepers
    #unity_tk_data = read_file_for_download("assets/unity_tk.csv")
    #if unity_tk_data:
    #    st.download_button("Unity", unity_tk_data, "unity_tk.csv", "text/csv")
        
with st.sidebar.expander("Line Items"):
    # Custom Line Items Files
    onit_lit_tasks_data = read_file_for_download("assets/custom_tasks.csv")
    if onit_lit_tasks_data:
        st.download_button("Litigation Line Items File", onit_lit_tasks_data, "custom_litigation_tasks.csv", "text/csv")

    onit_pat_tasks_data = read_file_for_download("assets/custom_pat_tasks.csv")
    if onit_pat_tasks_data:
        st.download_button("Patent Line Items File", onit_pat_tasks_data, "custom_patent_tasks.csv", "text/csv")

    onit_trade_tasks_data = read_file_for_download("assets/custom_trade_tasks.csv")
    if onit_trade_tasks_data:
        st.download_button("Trademark Line Items File", onit_trade_tasks_data, "custom_trademark_tasks.csv", "text/csv")

    onit_capmkt_tasks_data = read_file_for_download("assets/custom_capital_markets.csv")
    if onit_capmkt_tasks_data:
        st.download_button("Capital Market Line Items File", onit_capmkt_tasks_data, "custom_capital_market_tasks.csv", "text/csv")
    
    # Line Items Template
    sample_custom_df = pd.DataFrame({
        "TASK_CODE": ["L100", "L110", "L120"],
        "ACTIVITY_CODE": ["A101", "A101", "A102"],
        "DESCRIPTION": [
            "Legal Research: Analyze legal precedents",
            "Legal Research: Review statutes and regulations",
            "Prepare deposition chronology from client records"
        ],
        "TK_CLASSIFICATION": ["Associate", "Partner", "Associate"],
        "BLOCKBILLING": ["N", "Y", "N"],
        "VAGUE": ["N", "Y", "N"],
        "MISMATCH": ["N", "N", "Y"]
    })
    csv_custom_sample_bytes = sample_custom_df.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="Line Items Template",
        data=csv_custom_sample_bytes,
        file_name="sample_custom_tasks.csv",
        mime="text/csv"
    )
# --- FAQs moved to Sidebar (Corrected) ---
st.sidebar.markdown("---")
st.sidebar.markdown("## Help & FAQs")

with st.sidebar.expander("LEDES 1998BI - Matter Setup (VAT Profiles)"):
    bp = Image.open("assets/BP Error Message.png")
    good = Image.open("assets/Country Currency Correct.png")
    bad = Image.open("assets/Country Currency Default.png")
    matter_good = Image.open("assets/matter_good.png")
    matter_bad = Image.open("assets/matter_bad.png")
    st.markdown("""   
    How do I create a matter for LEDES 1998BI (VAT) invoices?
    - This applies to VAT-enabled profiles such as **OnitX EUR - Nelson** and **OnitX CAD - SS&E Group**. 
    - When creating a new matter, make sure to select **'Onit LLC - Belgium'** for the Legal Entity. The default is 'A Onit Inc.' 
    - When **'Onit LLC - Belgium'** is selected as the Legal Entity, the **Country** and **Matter Currency** fields change from their default values (United States and United States Dollar).
    - Make sure to update the **Country field to 'Belgium'** and the **Matter Currency field to 'Euro'**.
    """)
    st.image(bad, caption="Default Values", use_column_width=True)
    st.image(good, caption="Updated/Correct Values", use_column_width=True)
    st.markdown("""
    - If you forget to change these fields when creating the matter and then try to upload a LEDES 1998BI Invoice, you will receive the following error in BillingPoint:
    - "Tax Code is not recognized:"
    """)
    st.image(bp, caption="Billing Point Error Message", use_column_width=True)
    st.markdown("""
    - To fix this error, you will need to update the Legal Entity, Country, and Matter Currency fields within the matter.
    - Legal Entity should be **'Onit LLC - Belgium'**, Country should be **'Belgium'**, and Matter Currency should be **'Euro'** 
    """)
    st.image(matter_bad, caption="Default Values", use_column_width=True)
    st.image(matter_good, caption="Updated/Correct Values", use_column_width=True)
    
with st.sidebar.expander("Using custom Client and Vendor IDs"):
    client = Image.open("assets/client.png")
    vendor = Image.open("assets/vendor.png")
    st.markdown("""
    Where do I find Client and Vendor IDs if I need to override the preset profiles?
    - Client Names & IDs can be found in the Legal Entities app.
    - Select the client you want, and use the Legal Entity Name and Tax ID values.
    """)
    st.image(client, caption="Legal Entities - Client Name and ID", use_column_width=True)
    st.markdown("""
    - Vendor Names & IDs can be found in Billing Point.
    - Select Invoices -> Upload LEDES and use the desired Billing Office and Tax# values.
    """)
    st.image(vendor, caption="Billing Point - Vendor Name and ID", use_column_width=True)

with st.sidebar.expander("Where can I find sample files?"):
    st.markdown("""
    All necessary files are available in the **Downloads** section above.
    """)

with st.sidebar.expander('What does the "Spend Agent" checkbox do?'):
    st.markdown("""
    This option includes specific, pre-defined line items designed to trigger compliance rules and alerts in a spend management system like Onit's Spend Agent.
    """)

with st.sidebar.expander('What does the "Multiple Attendees at Same Meeting" checkbox do?'):
    st.markdown("""
    This creates two identical fee line items for a single meeting, assigned to different timekeepers. It's used to test billing guidelines against duplicate work.
    """)

with st.sidebar.expander("How do I format the timekeeper CSV?"):
    st.markdown("""
    The CSV requires a header with these exact column names:
    - `TIMEKEEPER_NAME`
    - `TIMEKEEPER_CLASSIFICATION`
    - `TIMEKEEPER_ID`
    - `RATE`
    """)

with st.sidebar.expander("How do I format the custom line items CSV?"):
    st.markdown("""
    The CSV requires the following columns:
    - `TASK_CODE`
    - `ACTIVITY_CODE`
    - `DESCRIPTION`
    - `TK_CLASSIFICATION`
    - `BLOCKBILLING` ('Y' or 'N')
    - `VAGUE` ('Y' or 'N')
    - `MISMATCH` ('Y' or 'N') — used by Spend Agent > Mismatch

    **Note:** Use `{NAME_PLACEHOLDER}` in a description to auto-insert a random name.
    """)
    
# --- Environment/Profile state (selected_env is environment; active_profile_id is derived) ---
_ensure_env_profile_state()

# --- LEDES version defaulting / resetting ---
# Apply environment rules when the ACTIVE profile OR selected environment changes:
# - SimpleLegal/Unity: default/reset to 1998B
# Otherwise, use profile-level ledes_default (if present), else fall back to 1998B.
_current_profile_for_ledes = st.session_state.get("active_profile_id", "")
_prev_profile_for_ledes = st.session_state.get("_prev_profile_for_ledes")

_current_env_for_ledes = _canonical_env(st.session_state.get("selected_env", "")) or _infer_environment(
    _current_profile_for_ledes,
    (BILLING_PROFILE_DETAILS or {}).get(_current_profile_for_ledes),
)
_prev_env_for_ledes = st.session_state.get("_prev_env_for_ledes")

if (_prev_profile_for_ledes != _current_profile_for_ledes) or (_prev_env_for_ledes != _current_env_for_ledes):
    _forced_ledes = _env_ledes_version_default(_current_env_for_ledes)
    if _forced_ledes:
        st.session_state["ledes_version"] = _forced_ledes
    elif _current_profile_for_ledes in BILLING_PROFILE_DETAILS:
        st.session_state["ledes_version"] = BILLING_PROFILE_DETAILS[_current_profile_for_ledes].get("ledes_default", "1998B")
    else:
        st.session_state.setdefault("ledes_version", "1998B")
    st.session_state["_prev_profile_for_ledes"] = _current_profile_for_ledes
    st.session_state["_prev_env_for_ledes"] = _current_env_for_ledes

# Dynamic Tabs
tabs = ["Data Sources", "Invoice Details", "Fees & Expenses", "Files & Receipts"]
# Insert Tax Fields tab before Output when LEDES 1998BIv2 is selected
if st.session_state.get("ledes_version") in ("1998BI", "1998BIv2"):
    tabs = tabs[:-1] + ["Tax Fields"] + tabs[-1:]
tab_objects = st.tabs(tabs)

with tab_objects[0]:

    st.markdown("<h3 style='color: #1E1E1E;'>Data Sources</h3>", unsafe_allow_html=True)
    uploaded_timekeeper_file = st.file_uploader("Upload Timekeepers File", type="csv")
    timekeeper_data = _load_timekeepers(uploaded_timekeeper_file)
    # Persist across reruns/tabs and always read from session thereafter
    if timekeeper_data is not None:
        st.session_state["timekeeper_data"] = timekeeper_data
    timekeeper_data = st.session_state.get("timekeeper_data")

    # Timekeeper summary + preview
    if timekeeper_data is not None:
        tk_count = len(timekeeper_data)
        st.success(f"Loaded {tk_count} timekeepers.")
        tk_df_preview = pd.DataFrame(timekeeper_data).head(10).reset_index(drop=True)
        tk_df_preview.index = tk_df_preview.index + 1
        preview_count = min(10, len(timekeeper_data))
        st.markdown(f"**{preview_count}-Row Preview**")
        st.dataframe(tk_df_preview, use_container_width=True)
        # Diagnostics: clean classification counts and Partner count
        with st.expander("Diagnostics: Timekeeper CSV", expanded=False):
            tks = _get_timekeepers()
            if tks:
                import pandas as pd
                classifications = (
                    pd.Series([str(t.get("TIMEKEEPER_CLASSIFICATION", "")).strip() for t in tks])
                    .replace({"": "(blank)"})
                )
                vc = (
                    classifications.str.title()
                    .value_counts()
                    .rename_axis("Classification")
                    .reset_index(name="Count")
                    .sort_values("Classification", kind="stable")
                    .reset_index(drop=True)
                )
                st.dataframe(vc, use_container_width=True, hide_index=True)
                partner_count = int(vc.loc[vc["Classification"].str.lower() == "partner", "Count"].sum())
                associate_count = int(vc.loc[vc["Classification"].str.lower() == "associate", "Count"].sum())
                paralegal_count = int(vc.loc[vc["Classification"].str.lower() == "paralegal", "Count"].sum())
            else:
                st.info("No timekeepers loaded yet.")
        

    use_custom_tasks = st.checkbox("Use Custom Line Item Details?", value=True)
    uploaded_custom_tasks_file = None
    if use_custom_tasks:
        uploaded_custom_tasks_file = st.file_uploader("Upload Line Items File", type="csv")

    task_activity_desc = CONFIG['DEFAULT_TASK_ACTIVITY_DESC']
    custom_tasks_data = None
    if use_custom_tasks and uploaded_custom_tasks_file:
        custom_tasks_data = _load_custom_task_activity_data(uploaded_custom_tasks_file)
        if custom_tasks_data is not None:
            li_count = len(custom_tasks_data)
            st.success(f"Loaded {li_count} custom line items.")
            if custom_tasks_data:
                task_activity_desc = custom_tasks_data

# #############################################################################
# ##### CORRECTED INVOICE DETAILS TAB #########################################
# #############################################################################
with tab_objects[1]:
    # ===== 1. GET USER INPUT THAT DRIVES LOGIC =====
    st.markdown("<h3 style='color: #1E1E1E;'>Billing Profiles</h3>", unsafe_allow_html=True)
    env_names = ENVIRONMENTS or ["OnitX", "SimpleLegal/Unity"]
    default_env = st.session_state.get("selected_env", env_names[0] if env_names else "OnitX")
    if env_names and default_env not in env_names:
        default_env = env_names[0]
    selected_env = st.selectbox("Environment", env_names, index=env_names.index(default_env) if (env_names and default_env in env_names) else 0, key="selected_env")

    

    # --- Client & Vendor selection (mix-and-match) ---
    # These are disabled when "Override values for this invoice" is enabled.
    _override_now = bool(st.session_state.get("allow_override", False))

    _client_options = list(ENV_CLIENT_OPTIONS.get(selected_env, [])) or list(CLIENT_CATALOG.keys())
    _vendor_options = list(ENV_VENDOR_OPTIONS.get(selected_env, [])) or list(VENDOR_CATALOG.keys())

    # Env-specific default pair (first-seen pair for that environment)
    _env_default_client, _env_default_vendor = ENV_DEFAULT_ENTITY_PAIR.get(selected_env, (
        _client_options[0] if _client_options else "",
        _vendor_options[0] if _vendor_options else "",
    ))

    # When the environment changes, reset the pair to that env's defaults (least-surprising behavior).
    if st.session_state.get("_prev_env_for_entity_pair") != selected_env:
        if _env_default_client:
            st.session_state["selected_client_profile"] = _env_default_client
        if _env_default_vendor:
            st.session_state["selected_vendor_profile"] = _env_default_vendor
        st.session_state["_prev_env_for_entity_pair"] = selected_env

    # Current selections (fall back to env defaults)
    _cur_client = st.session_state.get("selected_client_profile", _env_default_client)
    if _cur_client not in _client_options and _env_default_client in _client_options:
        _cur_client = _env_default_client

    _cur_vendor = st.session_state.get("selected_vendor_profile", _env_default_vendor)
    if _cur_vendor not in _vendor_options and _env_default_vendor in _vendor_options:
        _cur_vendor = _env_default_vendor

    # UI widgets
    csel1, csel2 = st.columns(2)
    with csel1:
        st.selectbox(
            "Client Profile (Legal Entity)",
            _client_options,
            index=_client_options.index(_cur_client) if (_client_options and _cur_client in _client_options) else 0,
            key="selected_client_profile",
            disabled=_override_now,
            help="Select the Client (Legal Entity) to populate Client fields on the Tax Fields tab for LEDES 1998BI/1998BIv2."
        )
    with csel2:
        st.selectbox(
            "Vendor / Law Firm Profile",
            _vendor_options,
            index=_vendor_options.index(_cur_vendor) if (_vendor_options and _cur_vendor in _vendor_options) else 0,
            key="selected_vendor_profile",
            disabled=_override_now,
            help="Select the Vendor/Law Firm profile to populate Law Firm fields on the Tax Fields tab for LEDES 1998BI/1998BIv2."
        )

# ===== 2. PERFORM ALL LOGIC AND STATE MODIFICATIONS =====
    
    # Resolve the active profile id for defaults (derived from Environment + selected Client/Vendor pair)
    _sel_client_key = st.session_state.get("selected_client_profile", "")
    _sel_vendor_key = st.session_state.get("selected_vendor_profile", "")
    active_profile_id = _resolve_active_profile_id(selected_env, _sel_client_key, _sel_vendor_key)
    st.session_state["active_profile_id"] = active_profile_id

    # Get base values from the active profile (used as a fallback when a detailed profile is present)
    prof_client_name, prof_client_id, prof_law_firm_name, prof_law_firm_id = get_profile(active_profile_id)

    # If a detailed profile exists, use its specific values to override the base ones
    if active_profile_id in BILLING_PROFILE_DETAILS and not st.session_state.get("allow_override"):
        prof = BILLING_PROFILE_DETAILS[active_profile_id]
        prof_client_name = prof.get("client", {}).get("name", prof_client_name)
        prof_law_firm_name = prof.get("law_firm", {}).get("name", prof_law_firm_name)
        prof_client_id = prof.get("client", {}).get("id", prof_client_id)
        prof_law_firm_id = prof.get("law_firm", {}).get("id", prof_law_firm_id)

    # Pre-populate session_state from the detailed profile if it exists
    if "allow_override" not in st.session_state:
        st.session_state["allow_override"] = False

    # If override is enabled, clear the defaults marker so turning override off re-applies profile defaults
    if st.session_state.get("allow_override"):
        st.session_state["_profile_defaults_sig"] = None

    if active_profile_id in BILLING_PROFILE_DETAILS and not st.session_state["allow_override"]:
        prof = BILLING_PROFILE_DETAILS[active_profile_id]
        _defaults_sig = f"{active_profile_id}|no_override"

        # Only apply profile defaults once per profile (or when override is toggled back off)
        if st.session_state.get("_profile_defaults_sig") != _defaults_sig:
            # Default LEDES version for profile
            _forced_ledes = _env_ledes_version_default(selected_env)
            if _forced_ledes:
                st.session_state["ledes_version"] = _forced_ledes
            else:
                st.session_state["ledes_version"] = prof.get("ledes_default", st.session_state.get("ledes_version", "1998B"))
            # Default invoice currency
            st.session_state["tax_invoice_currency"] = prof.get("invoice_currency", st.session_state.get("tax_invoice_currency", "USD"))

            # Law firm fields
            lf = prof.get("law_firm", {})
            st.session_state["law_firm_name"] = lf.get("name", prof_law_firm_name)
            st.session_state["law_firm_id"] = lf.get("id", prof_law_firm_id)
            st.session_state["lf_address1"] = lf.get("address1", "")
            st.session_state["lf_address2"] = lf.get("address2", "")
            st.session_state["lf_city"] = lf.get("city", "")
            st.session_state["lf_state"] = lf.get("state", "")
            st.session_state["lf_postcode"] = lf.get("postcode", "")
            st.session_state["lf_country"] = lf.get("country", "")

            # Client fields
            cl = prof.get("client", {})
            st.session_state["client_name"] = cl.get("name", prof_client_name)
            st.session_state["client_id"] = cl.get("id", prof_client_id)
            st.session_state["client_tax_id"] = cl.get("tax_id", "")
            st.session_state["client_address1"] = cl.get("address1", "")
            st.session_state["client_address2"] = cl.get("address2", "")
            st.session_state["client_city"] = cl.get("city", "")
            st.session_state["client_state"] = cl.get("state", "")
            st.session_state["client_postcode"] = cl.get("postcode", "")
            st.session_state["client_country"] = cl.get("country", "")

            # Mirror values into the 'pf_*' UI keys so the expanders display them
            st.session_state["pf_law_firm_id"] = st.session_state.get("law_firm_id", "")
            st.session_state["pf_lf_address1"] = st.session_state.get("lf_address1", "")
            st.session_state["pf_lf_address2"] = st.session_state.get("lf_address2", "")
            st.session_state["pf_lf_city"] = st.session_state.get("lf_city", "")
            st.session_state["pf_lf_state"] = st.session_state.get("lf_state", "")
            st.session_state["pf_lf_postcode"] = st.session_state.get("lf_postcode", "")
            st.session_state["pf_lf_country"] = st.session_state.get("lf_country", "")
            st.session_state["pf_client_tax_id"] = st.session_state.get("client_tax_id", "")
            st.session_state["pf_client_address1"] = st.session_state.get("client_address1", "")
            st.session_state["pf_client_address2"] = st.session_state.get("client_address2", "")
            st.session_state["pf_client_city"] = st.session_state.get("client_city", "")
            st.session_state["pf_client_state"] = st.session_state.get("client_state", "")
            st.session_state["pf_client_postcode"] = st.session_state.get("client_postcode", "")
            st.session_state["pf_client_country"] = st.session_state.get("client_country", "")

            st.session_state["_profile_defaults_sig"] = _defaults_sig

        # Sync client_id with client_tax_id if it exists (do this every run)
        if st.session_state.get("client_tax_id"):
            st.session_state["client_id"] = st.session_state["client_tax_id"]
            prof_client_id = st.session_state["client_id"] # Also update the local variable for the widget
        if _is_vat_profile(st.session_state.get("active_profile_id", "")):
            st.markdown(
        """
        **Note:** Please review the **LEDES 1998BI - Matter Setup** section in Help & FAQs.
        
        This provides details on how to properly create a matter to allow VAT invoices to be submitted through BillingPoint.

        It also provides information on the most common error when trying to submit a VAT Invoice against a matter not properly set up.
        """,
        unsafe_allow_html=False
    )

    

    # --- Apply selected Client/Vendor pair into session state ---
    # When override is OFF, keep invoice + Tax Fields in sync with the selected Client/Vendor pair.
    # We only re-apply when the selection changes, so manual edits (while override is OFF) can still persist.
    if not bool(st.session_state.get("allow_override", False)):
        _sel_client_key = st.session_state.get("selected_client_profile", "")
        _sel_vendor_key = st.session_state.get("selected_vendor_profile", "")
        _sig = f"{selected_env}|{_sel_client_key}|{_sel_vendor_key}|no_override"

        if st.session_state.get("_entity_defaults_sig") != _sig:
            _cl = CLIENT_CATALOG.get(_sel_client_key, {}) or {}
            _vf = VENDOR_CATALOG.get(_sel_vendor_key, {}) or {}

            # --- Client (Legal Entity) ---
            _cl_name = _cl.get("name", "") or st.session_state.get("client_name", "")
            _cl_id = _cl.get("id", "") or st.session_state.get("client_id", "")
            _cl_tax = _cl.get("tax_id", None)

            st.session_state["client_name"] = _cl_name
            # Prefer tax_id as the effective client_id when provided (VAT-style)
            if _cl_tax is not None and str(_cl_tax).strip() != "":
                st.session_state["client_tax_id"] = str(_cl_tax)
                st.session_state["client_id"] = str(_cl_tax)
            else:
                # Do not clear existing tax id unless explicitly provided
                st.session_state["client_id"] = _cl_id

            # Address fields (only set when present in the selected profile; otherwise keep existing)
            for _k_src, _k_dst in [
                ("address1", "client_address1"),
                ("address2", "client_address2"),
                ("city", "client_city"),
                ("state", "client_state"),
                ("postcode", "client_postcode"),
                ("country", "client_country"),
            ]:
                v = _cl.get(_k_src, None)
                if v is not None and (not isinstance(v, str) or v.strip() != ""):
                    st.session_state[_k_dst] = v

            # Mirror into pf_* fields so Tax Fields tab is pre-populated
            st.session_state["pf_client_tax_id"] = st.session_state.get("client_tax_id", "")
            st.session_state["pf_client_address1"] = st.session_state.get("client_address1", "")
            st.session_state["pf_client_address2"] = st.session_state.get("client_address2", "")
            st.session_state["pf_client_city"] = st.session_state.get("client_city", "")
            st.session_state["pf_client_state"] = st.session_state.get("client_state", "")
            st.session_state["pf_client_postcode"] = st.session_state.get("client_postcode", "")
            st.session_state["pf_client_country"] = st.session_state.get("client_country", "")

            # --- Vendor / Law Firm ---
            _vf_name = _vf.get("name", "") or st.session_state.get("law_firm_name", "")
            _vf_id = _vf.get("id", "") or st.session_state.get("law_firm_id", "")
            st.session_state["law_firm_name"] = _vf_name
            st.session_state["law_firm_id"] = _vf_id

            for _k_src, _k_dst in [
                ("address1", "lf_address1"),
                ("address2", "lf_address2"),
                ("city", "lf_city"),
                ("state", "lf_state"),
                ("postcode", "lf_postcode"),
                ("country", "lf_country"),
            ]:
                v = _vf.get(_k_src, None)
                if v is not None and (not isinstance(v, str) or v.strip() != ""):
                    st.session_state[_k_dst] = v

            # Mirror into pf_* fields
            st.session_state["pf_law_firm_id"] = st.session_state.get("law_firm_id", "")
            st.session_state["pf_lf_address1"] = st.session_state.get("lf_address1", "")
            st.session_state["pf_lf_address2"] = st.session_state.get("lf_address2", "")
            st.session_state["pf_lf_city"] = st.session_state.get("lf_city", "")
            st.session_state["pf_lf_state"] = st.session_state.get("lf_state", "")
            st.session_state["pf_lf_postcode"] = st.session_state.get("lf_postcode", "")
            st.session_state["pf_lf_country"] = st.session_state.get("lf_country", "")

            st.session_state["_entity_defaults_sig"] = _sig
    else:
        # If override is ON, clear the sig so turning override back OFF re-applies the selected pair.
        st.session_state["_entity_defaults_sig"] = None

# ===== 3. CREATE WIDGETS (now that all state is set) =====
    st.checkbox("Override values for this invoice", value=False, help="When checked, you can enter other Client & Vendor IDs without changing stored profiles. See 'Using custom Client and Vendor IDs' in the FAQ for more details", key="allow_override")    

    allow_override = bool(st.session_state.get("allow_override", False))
    # Only show these fields when override is enabled. When override is OFF, force them
    # to the selected profile values and hide the inputs.
    if not allow_override:
        # Cache any prior overrides so they can be restored if the user turns override back ON
        for _k, _prof_val, _cache_k in (
            ("client_name", prof_client_name, "_override_cache_client_name"),
            ("client_id", prof_client_id, "_override_cache_client_id"),
            ("law_firm_name", prof_law_firm_name, "_override_cache_law_firm_name"),
            ("law_firm_id", prof_law_firm_id, "_override_cache_law_firm_id"),
        ):
            _cur = st.session_state.get(_k, None)
            if _cur is not None and str(_cur).strip() != "" and _cur != _prof_val:
                st.session_state[_cache_k] = _cur
            st.session_state[_k] = _prof_val

        client_name = prof_client_name
        client_id = prof_client_id
        law_firm_name = prof_law_firm_name
        law_firm_id = prof_law_firm_id
    else:
        # Restore cached overrides (if any) when turning override back ON
        for _k, _prof_val, _cache_k in (
            ("client_name", prof_client_name, "_override_cache_client_name"),
            ("client_id", prof_client_id, "_override_cache_client_id"),
            ("law_firm_name", prof_law_firm_name, "_override_cache_law_firm_name"),
            ("law_firm_id", prof_law_firm_id, "_override_cache_law_firm_id"),
        ):
            if _cache_k in st.session_state and st.session_state.get(_k, _prof_val) == _prof_val:
                st.session_state[_k] = st.session_state.get(_cache_k, _prof_val)

        # Names
        c1, c2 = st.columns(2)
        with c1:
            client_name = st.text_input("Client Name", value=prof_client_name, key="client_name")
        with c2:
            law_firm_name = st.text_input("Law Firm Name", value=prof_law_firm_name, key="law_firm_name")

        # IDs (no format restrictions)
        c3, c4 = st.columns(2)
        with c3:
            client_id = st.text_input("Client ID", value=prof_client_id, key="client_id")
        with c4:
            law_firm_id = st.text_input("Law Firm ID", value=prof_law_firm_id, key="law_firm_id")

        st.markdown("<h3 style='color: #1E1E1E;'>Numbers & Version</h3>", unsafe_allow_html=True)

    # Environment-specific defaults:
    # - SimpleLegal/Unity: Matter Number defaults to "saturn-xxxx"; Invoice Number defaults to "YYYY-MMM-Saturn-XXXXXX"
    # - OnitX: keep existing defaults
    _env_token = _canonical_env(st.session_state.get("selected_env", ""))
    _is_sl_unity = (_env_token == ENV_SIMPLELEGAL_UNITY)

    def prior_month_stamp(today: date) -> str:
        # Go to last day of prior month (handles Jan -> Dec of previous year)
        last_day_prev_month = today.replace(day=1) - timedelta(days=1)
        yyyy = last_day_prev_month.year
        mmm = calendar.month_abbr[last_day_prev_month.month].upper()  # e.g., "DEC"
        return f"{yyyy}-{mmm}"

    # Compute the dynamic default: YYYY-MMM-... based on PRIOR month
    stamp = prior_month_stamp(date.today())

    # Matter Number default: "saturn-xxxx" for SimpleLegal/Unity, otherwise keep existing
    matter_default = "saturn-xxxx" if _is_sl_unity else "2025-XXXXXX"
    if "matter_number_base" not in st.session_state:
        st.session_state["matter_number_base"] = matter_default
        st.session_state["_matter_base_env"] = _env_token
        st.session_state["_matter_base_default"] = matter_default
    elif st.session_state.get("_matter_base_env") != _env_token:
        prev_default = st.session_state.get("_matter_base_default")
        # Only swap in the new default if the user hadn't customized the prior default
        if st.session_state.get("matter_number_base") == prev_default:
            st.session_state["matter_number_base"] = matter_default
        st.session_state["_matter_base_env"] = _env_token
        st.session_state["_matter_base_default"] = matter_default

    matter_number_base = st.text_input(
        "Matter Number:",
        key="matter_number_base",
        help=("Default is saturn-xxxx for SimpleLegal/Unity." if _is_sl_unity else "Default is 2025-XXXXXX.")
    )

    # Keep Tax Fields -> Client Matter ID synced with Invoice Details -> Matter Number
    st.session_state["tax_client_matter_id"] = matter_number_base

    # Invoice Number (Base) default:
    dynamic_default = f"{stamp}-Saturn-XXXXXX" if _is_sl_unity else f"{stamp}-XXXXXX"
    _invoice_sig = f"{_env_token}|{stamp}|{'saturn' if _is_sl_unity else 'default'}"

    # Only auto-set when first created OR when the env/month signature changes,
    # and only if the user hadn't customized away from the prior default.
    if "invoice_number_base" not in st.session_state:
        st.session_state.invoice_number_base = dynamic_default
        st.session_state._invoice_base_sig = _invoice_sig
        st.session_state._invoice_base_default = dynamic_default
    elif st.session_state.get("_invoice_base_sig") != _invoice_sig:
        prev_default = st.session_state.get("_invoice_base_default")
        if st.session_state.get("invoice_number_base") == prev_default:
            st.session_state.invoice_number_base = dynamic_default
        st.session_state._invoice_base_sig = _invoice_sig
        st.session_state._invoice_base_default = dynamic_default

    invoice_help = (
        "Format: YYYY-MMM-Saturn-XXXXXX (XXXXXX is the matter placeholder)"
        if _is_sl_unity
        else "Format: YYYY-MMM-XXXXXX (XXXXXX is the matter placeholder)"
    )
    invoice_number_base = st.text_input(
        "Invoice Number (Base):",
        key="invoice_number_base",
        help=invoice_help
    )

    LEDES_OPTIONS = ["1998B", "1998BI"]
    ledes_version = st.selectbox(
        "LEDES Version:",
        LEDES_OPTIONS,
        key="ledes_version",
        #help="XML 2.1 export is not implemented yet; please use 1998B or 1998BI."
    )

    if ledes_version == "XML 2.1":
        st.warning("This is not yet implemented - please use 1998B")

    st.markdown("<h3 style='color: #1E1E1E;'>Invoice Dates & Description</h3>", unsafe_allow_html=True)
    today = datetime.date.today()
    first_day_of_current_month = today.replace(day=1)
    last_day_of_previous_month = first_day_of_current_month - datetime.timedelta(days=1)
    first_day_of_previous_month = last_day_of_previous_month.replace(day=1)
    billing_start_date = st.date_input("Billing Start Date", value=first_day_of_previous_month)
    billing_end_date = st.date_input("Billing End Date", value=last_day_of_previous_month)
    # --- Invoice Description (auto-generated; optionally editable) ---
    # NOTE: The "Generate Multiple Invoices" / "Multiple Billing Periods" controls live in the Output tab.
    # Streamlit updates widget values in st.session_state before each rerun, so we can safely read them here.
    # We support both explicit widget keys (preferred) and legacy implicit keys (label-based).
    _generate_multiple = bool(
        st.session_state.get("generate_multiple_invoices",
            st.session_state.get("Generate Multiple Invoices", False)
        )
    )
    _multiple_periods = bool(
        st.session_state.get("multiple_billing_periods",
            st.session_state.get("Multiple Billing Periods", False)
        )
    )

    _raw_periods = (
        st.session_state.get("num_billing_periods")
        or st.session_state.get("How Many Billing Periods:")
        or st.session_state.get("How many billing periods:")
        or st.session_state.get("How Many Billing Periods")
        or st.session_state.get("How many billing periods")
        or 1
    )

    if _generate_multiple and _multiple_periods:
        try:
            desc_periods = max(1, int(_raw_periods))
        except Exception:
            desc_periods = 1
    else:
        desc_periods = 1

    desired_invoice_desc = _default_invoice_description_lines(
        "Professional Services Rendered",
        billing_end_date,
        desc_periods
    )

    allow_edit_invoice_desc = st.checkbox(
        "Allow editing Invoice Description",
        value=False,
        key="invoice_desc_edit_enabled",
        help="When unchecked, the description is auto-generated from the billing period(s) and shown read-only."
    )

    st.session_state.setdefault("invoice_desc_auto", True)
    st.session_state.setdefault("invoice_desc_text", desired_invoice_desc)

    prev_edit_state = st.session_state.get("_prev_invoice_desc_edit_enabled", False)

    # Transition: entering edit mode
    if allow_edit_invoice_desc and not prev_edit_state:
        current_text = str(st.session_state.get("invoice_desc_text", "")).strip()
        if not current_text:
            st.session_state["invoice_desc_text"] = desired_invoice_desc

    # Transition: leaving edit mode
    if not allow_edit_invoice_desc and prev_edit_state:
        current_text = str(st.session_state.get("invoice_desc_text", "")).strip()
        if st.session_state.get("invoice_desc_auto", True) or not current_text:
            st.session_state["invoice_desc_text"] = desired_invoice_desc
            st.session_state["invoice_desc_auto"] = True

    st.session_state["_prev_invoice_desc_edit_enabled"] = allow_edit_invoice_desc

    if not allow_edit_invoice_desc:
        if st.session_state.get("invoice_desc_auto", True):
            st.session_state["invoice_desc_text"] = desired_invoice_desc

        if st.button("Reset Invoice Description to Defaults", key="reset_invoice_desc_defaults_ro"):
            st.session_state["invoice_desc_auto"] = True
            st.session_state["invoice_desc_text"] = desired_invoice_desc

    else:
        if st.button("Reset Invoice Description to Defaults", key="reset_invoice_desc_defaults"):
            st.session_state["invoice_desc_auto"] = True
            st.session_state["invoice_desc_text"] = desired_invoice_desc

        invoice_desc = st.text_area(
            "Invoice Description (One per period, each on a new line)",
            key="invoice_desc_text",
            height=150,
            on_change=_mark_invoice_desc_manual,
        )

    if not allow_edit_invoice_desc:
        mode_label = "Auto-generated" if st.session_state.get("invoice_desc_auto", True) else "Locked (custom)"
        st.markdown(f"**Invoice Description ({mode_label}; one per period):**")
        _desc_text = str(st.session_state.get("invoice_desc_text", "")).strip() or desired_invoice_desc
        _lines = [ln.strip() for ln in _desc_text.splitlines() if ln.strip()]
        st.markdown("\n".join([f"- {ln}" for ln in _lines]))

        with st.expander("Copyable text"):
            st.code(_desc_text, language=None)

        invoice_desc = _desc_text

    # Ensure downstream logic always uses the latest value
    invoice_desc = st.session_state.get("invoice_desc_text", desired_invoice_desc)

    # #############################################################################

with tab_objects[2]:
    st.markdown("<h3 style='color: #1E1E1E;'>Fees & Expenses</h3>", unsafe_allow_html=True)

    # Initialize the preset dropdown and related counts before rendering the widget.
    if "invoice_preset" not in st.session_state:
        st.session_state["invoice_preset"] = DEFAULT_INVOICE_PRESET

    if "fee_slider" not in st.session_state:
        st.session_state["fee_slider"] = PRESETS[DEFAULT_INVOICE_PRESET]["fees"]

    if "expense_slider" not in st.session_state:
        st.session_state["expense_slider"] = PRESETS[DEFAULT_INVOICE_PRESET]["expenses"]

    # Make Invoice Size Presets the first and most visible control on the tab.
    st.markdown(
        """
        <div style="border: 1px solid #D0D7DE; border-radius: 10px; padding: 14px 16px; margin: 8px 0 16px 0; background-color: #F6F8FA;">
            <h3 style="color: #1E1E1E; margin: 0 0 4px 0;">Invoice Size Preset</h3>
            <p style="margin: 0; color: #4B5563;">Start here to set the standard fee and expense line-item volume for this invoice.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    preset_col, fee_preview_col, expense_preview_col = st.columns([2.4, 1, 1])
    with preset_col:
        st.selectbox(
            "Invoice Size Presets",
            options=list(PRESETS.keys()),
            key="invoice_preset",
            on_change=apply_preset,
            help="Select a preset to quickly adjust the number of fee and expense lines below."
        )
    with fee_preview_col:
        st.metric("Fee Lines", int(st.session_state.get("fee_slider", 0) or 0))
    with expense_preview_col:
        st.metric("Expense Lines", int(st.session_state.get("expense_slider", 0) or 0))

    st.markdown("---")
    st.markdown("<h4 style='color: #1E1E1E;'>Review Scenario Options</h4>", unsafe_allow_html=True)

    spend_agent = st.checkbox("Spend Agent", value=False, help="Ensures selected mandatory line items are included; configure below.")

    vague_line_items = st.checkbox("Vague Line Items", value=False, help="Randomly include 1 to 5 line items that have vague line item descriptions.")

    multiple_attendees_meeting = st.checkbox(
        "Multiple Attendees at Same Meeting",
        value=False,
        help="If checked, create two identical fee line items from 2 different timekeepers for the same meeting.",
        key="multiple_attendees_meeting",
    )
    # Block-billed controls live with the rest of Fees & Expenses so invoice-content
    # test settings stay together in the UI.
    st.session_state.setdefault("include_block_billed", True)
    st.session_state.setdefault("num_block_billed", 2)
    include_block_billed = st.checkbox(
        "Include Block Billed Line Items",
        key="include_block_billed",
        help="Include block-billed fee line items from rows marked BLOCKBILLING = Y in the custom line-item CSV.",
    )
    num_block_billed = 0
    if include_block_billed:
        num_block_billed = st.number_input(
            "Number of Block Billed Items:",
            min_value=1,
            max_value=10,
            step=1,
            key="num_block_billed",
            help="The number of block-billed items to include from the custom line-item CSV.",
        )

    # Initialize/Reset global block-billing budget whenever the UI value is set.
    st.session_state["__bb_remaining"] = int(num_block_billed)

    st.markdown("---")
    st.markdown("<h4 style='color: #1E1E1E;'>Line Item Counts</h4>", unsafe_allow_html=True)

    if timekeeper_data is None:
        st.error("Please upload a valid timekeeper CSV file to configure fee and expense settings.")
        fees = 0
        expenses = 0
    else:
        max_fees = _calculate_max_fees(timekeeper_data, billing_start_date, billing_end_date, 16)
        st.caption(f"Maximum fee lines allowed: {max_fees} (based on timekeepers and billing period)")
        
        # Fee slider state is initialized with the preset dropdown above.
        fees = st.number_input(
            "Number of Fee Line Items",
            min_value=0,
            max_value=max_fees,
            key="fee_slider",
        )
        # If no external Line Item Details CSV is loaded, disable fee line item generation.
        _has_external_line_item_details = bool(globals().get("uploaded_custom_tasks_file"))
        if not _has_external_line_item_details:
            fees = 0

        st.markdown("<h3 style='color: #1E1E1E;'>Expense Settings</h3>", unsafe_allow_html=True)
        with st.expander("Adjust Expense Amounts", expanded=False):
            st.number_input(
                "Local Travel (E109) mileage rate ($/mile)",
                min_value=0.20, max_value=2.00, value=0.65, step=0.01,
                key="mileage_rate_e109",
                help="Used to calculate E109 totals as miles × rate. Miles are stored in the HOURS column."
            )
            st.slider(
                "Out-of-town Travel (E110) amount range ($)",
                min_value=10.0, max_value=7500.0, value=(100.0, 800.0), step=10.0,
                key="travel_range_e110",
                help="Random amount for each E110 line will be drawn from this range."
            )
            st.slider(
                "Telephone (E105) amount range ($)",
                min_value=1.0, max_value=50.0, value=(5.0, 15.0), step=1.0,
                key="telephone_range_e105",
                help="Random amount for each E105 line will be drawn from this range."
            )
     
            # 1. Determine the default rate based on the selected LEDES version
            if st.session_state.get("ledes_version") == "1998BI":
                default_copy_rate = 0.10
            else:
                default_copy_rate = 0.24
        
            # 2. Use the variable as the slider's default value
            st.number_input(
                "Photocopies (E101) per-page rate ($)",
                min_value=0.04,
                max_value=1.50,
                value=default_copy_rate, 
                step=0.01,
                key="copying_rate_e101",
                help="Per-page rate used for E101 Photocopy expenses."
            )
        st.caption("Number of expense line items to generate")
        
        # Expense slider state is initialized with the preset dropdown above.
        expenses = st.number_input(
            "Number of Expense Line Items",
            min_value=0,
            max_value=500,
            key="expense_slider",
        )

        # Warn when Custom is selected but the user leaves both line item counts
        # at the Custom preset defaults. Spend Agent items may still add lines,
        # but no standard fee or expense line items will be generated from these settings.
        if (
            st.session_state.get("invoice_preset") == "Custom"
            and int(st.session_state.get("fee_slider", 0) or 0) == 0
            and int(st.session_state.get("expense_slider", 0) or 0) == 0
        ):
            st.warning(
                "Invoice Size Preset is set to Custom, but Fee Line Items and Expense Line Items are both still 0. "
                "Update at least one of these values if you want standard fee or expense lines generated.",
                icon="⚠️",
            )
    max_daily_hours = st.number_input("Max Daily Timekeeper Hours:", min_value=1, max_value=24, value=16, step=1)
    
    if spend_agent:
        st.markdown("<h3 style='color: #1E1E1E;'>Spend Agent Items</h3>", unsafe_allow_html=True)
        st.caption("Select the invoice review scenarios to include.")

        # ---- Unified Spend Agent checkbox grid ----
        # Mandatory items remain handled by _ensure_mandatory_lines().
        # Mismatch is now selected from the same Spend Agent grid, but still handled
        # by _append_mismatch_line_items() because it is sourced from MISMATCH=Y CSV rows.
        available_items = list(CONFIG["MANDATORY_ITEMS"].keys())
        mismatch_item_name = "Mismatch"
        all_spend_agent_items = available_items + [mismatch_item_name]

        def _spend_agent_checkbox_key(item_name: str) -> str:
            safe_name = re.sub(r"[^A-Za-z0-9]+", "_", str(item_name)).strip("_").lower()
            return f"spend_agent_item_{safe_name}"

        def _set_spend_agent_grid_selection(target_items):
            target_set = set(target_items or [])
            for _item_name in all_spend_agent_items:
                st.session_state[_spend_agent_checkbox_key(_item_name)] = _item_name in target_set

        # Determine initial selected items.
        # Preserve prior checkbox-grid selections when present. Fall back to the prior
        # multiselect state for backward compatibility. Initial default keeps the old
        # behavior: all mandatory items selected, Mismatch off unless previously selected.
        saved_grid_selection = st.session_state.get("spend_agent_items_default")
        legacy_mandatory_selection = st.session_state.get("mandatory_items_default")

        if saved_grid_selection is not None:
            default_spend_agent_selection = [item for item in saved_grid_selection if item in all_spend_agent_items]
        elif legacy_mandatory_selection is not None:
            default_spend_agent_selection = [item for item in legacy_mandatory_selection if item in available_items]
            if st.session_state.get("mismatch_line_items", False):
                default_spend_agent_selection.append(mismatch_item_name)
        else:
            default_spend_agent_selection = list(available_items)
            if st.session_state.get("mismatch_line_items", False):
                default_spend_agent_selection.append(mismatch_item_name)

        # Special rule for SimpleLegal/Unity: ensure Partner → Paralegal remains pre-selected if available.
        if _canonical_env(st.session_state.get("selected_env")) == ENV_SIMPLELEGAL_UNITY:
            pp_key = next((k for k in available_items if _is_partner_paralegal_item(k)), None)
            if pp_key and pp_key not in default_spend_agent_selection:
                default_spend_agent_selection.append(pp_key)

        action_cols = st.columns([1, 1, 4])
        with action_cols[0]:
            if st.button("Select All", key="spend_agent_select_all"):
                _set_spend_agent_grid_selection(all_spend_agent_items)
        with action_cols[1]:
            if st.button("Clear All", key="spend_agent_clear_all"):
                _set_spend_agent_grid_selection([])

        # Initialize checkbox states before the widgets are rendered.
        for item_name in all_spend_agent_items:
            item_key = _spend_agent_checkbox_key(item_name)
            if item_key not in st.session_state:
                st.session_state[item_key] = item_name in default_spend_agent_selection

        spend_agent_help = {
            "KBCG": "Adds the KBCG e-licensing portal / deficiency notice fee line.",
            "John Doe": "Adds the deposition transcript review and case chronology fee line.",
            "Uber E110": "Adds an E110 Uber ride expense line and displays the Uber amount controls.",
            "Partner: Paralegal Tasks": "Adds Partner-billed lines from Paralegal-classified work for guideline testing.",
            "Airfare E110": "Adds an E110 airfare expense line and displays the airfare detail controls.",
            mismatch_item_name: "Adds randomly selected custom line items where MISMATCH = Y. Used to test description/task-code mismatch review rules.",
        }

        selected_spend_agent_items = []
        grid_cols = st.columns(2)
        for idx, item_name in enumerate(all_spend_agent_items):
            with grid_cols[idx % 2]:
                if st.checkbox(
                    item_name,
                    key=_spend_agent_checkbox_key(item_name),
                    help=spend_agent_help.get(item_name, "Include this Spend Agent test item."),
                ):
                    selected_spend_agent_items.append(item_name)

        selected_items = [item for item in selected_spend_agent_items if item in available_items]
        mismatch_line_items = mismatch_item_name in selected_spend_agent_items

        # Backward-compatible state for the existing generation and summary logic.
        st.session_state["mismatch_line_items"] = bool(mismatch_line_items)
        st.session_state["mandatory_items_default"] = list(selected_items)
        st.session_state["spend_agent_items_default"] = list(selected_spend_agent_items)
        st.session_state["mandatory_items_multiselect"] = list(selected_items)

        prev_selected_items = st.session_state.get("_mandatory_items_prev", [])
        st.session_state["_mandatory_items_prev"] = list(selected_items)
        
        # Partner → Paralegal count controls (adds multiple Partner-billed lines using Paralegal-tagged source rows)
        pp_selected_key = next((k for k in selected_items if _is_partner_paralegal_item(k)), None)
        if pp_selected_key:
            st.markdown("<h4 style='color: #1E1E1E;'>Partner → Paralegal</h4>", unsafe_allow_html=True)
            st.session_state.setdefault("pp_lines_per_invoice", 3)
            st.session_state.setdefault("pp_randomize_count_per_invoice", False)

            st.number_input(
                "Partner → Paralegal lines per invoice",
                min_value=1,
                max_value=10,
                value=int(st.session_state.get("pp_lines_per_invoice", 3)),
                key="pp_lines_per_invoice",
                help="Number of fee lines to add per invoice where a Partner bills work tagged as Paralegal in the line-item CSV.",
            )
            st.checkbox(
                "Randomize Partner → Paralegal count per invoice (1..N)",
                value=bool(st.session_state.get("pp_randomize_count_per_invoice", False)),
                key="pp_randomize_count_per_invoice",
                help="When generating multiple invoices, vary how many Partner → Paralegal lines are added to each invoice.",
            )

        # Conditional UI for Airfare Details
        if 'Airfare E110' in selected_items:
            # Initialize / reset a default arrival city when first selected (or re-selected)
            if ("airfare_arrival_city" not in st.session_state) or ('Airfare E110' not in prev_selected_items):
                st.session_state["airfare_arrival_city"] = _pick_ua_sfo_arrival_city()
            # If older sessions have a value outside the allowed pool, reset safely
            if st.session_state.get("airfare_arrival_city") not in UA_SFO_US_DESTINATIONS:
                st.session_state["airfare_arrival_city"] = _pick_ua_sfo_arrival_city()

            # Auto-generate a random airfare amount when Spend Agent is enabled and the item is selected.
            # Generated once on first select (or re-select) and persists unless manually overridden.
            if ("airfare_amount" not in st.session_state) or (
                'Airfare E110' not in prev_selected_items and st.session_state.get("airfare_amount_auto", True)
            ):
                st.session_state["airfare_amount"] = round(random.uniform(500.00, 14000.00), 2)
                st.session_state["airfare_amount_auto"] = True

            def _mark_airfare_amount_manual():
                st.session_state["airfare_amount_auto"] = False

            st.markdown("<h4 style='color: #1E1E1E;'>Airfare Details</h4>", unsafe_allow_html=True)
            ac1, ac2 = st.columns(2)
            with ac1:
                st.text_input("Airline", key="airfare_airline", value="United Airlines")
                st.text_input("Departure City", key="airfare_departure_city_display", value=SFO_DEPARTURE_CITY, disabled=True)
                st.checkbox("Roundtrip", key="airfare_roundtrip", value=True)
                st.checkbox(
                    "Randomize Arrival City per invoice when generating multiple invoices",
                    key="airfare_randomize_arrival_per_invoice",
                    value=st.session_state.get("airfare_randomize_arrival_per_invoice", False),
                    help="If multiple invoices are generated, a different Arrival City will be chosen for each invoice's Airfare E110 line item."
                )
            with ac2:
                st.text_input("Flight Number", key="airfare_flight_number", value="UA123")
                st.selectbox(
                    "Arrival City (United nonstop from SFO)",
                    options=UA_SFO_US_DESTINATIONS,
                    key="airfare_arrival_city",
                )
                st.number_input(
                    "Amount",
                    min_value=500.00,
                    max_value=14000.00,
                    value=float(st.session_state.get("airfare_amount", 500.00)),
                    step=0.01,
                    key="airfare_amount",
                    on_change=_mark_airfare_amount_manual,
                    help="This amount will be used for the airfare line item total."
                )
            st.selectbox(
                "Fare Class",
                options=["First", "Business", "Premium Economy", "Economy/Coach"],
                key="airfare_fare_class",
                help="Select the standard airline fare class (e.g., First, Business, Coach). This will be added to the line item description."
            )

        # Conditional UI for Uber Details
        if 'Uber E110' in selected_items:
            # Auto-generate a random Uber amount when Spend Agent is enabled and the item is selected.
            # Generated once on first select (or re-select) and persists unless manually overridden.
            if ("uber_amount" not in st.session_state) or (
                'Uber E110' not in prev_selected_items and st.session_state.get("uber_amount_auto", True)
            ):
                st.session_state["uber_amount"] = round(random.uniform(15.00, 65.00), 2)
                st.session_state["uber_amount_auto"] = True

            def _mark_uber_amount_manual():
                st.session_state["uber_amount_auto"] = False

            st.markdown("<h4 style='color: #1E1E1E;'>Uber E110 Details</h4>", unsafe_allow_html=True)
            st.number_input(
                "Ride Amount",
                min_value=15.00,
                max_value=65.00,
                value=float(st.session_state.get("uber_amount", 15.00)),
                step=0.01,
                key="uber_amount",
                on_change=_mark_uber_amount_manual,
                help="This amount will be used for the Uber ride line item total."
            )

    else:
        selected_items = []
        mismatch_line_items = False
        st.session_state["mismatch_line_items"] = False
        st.session_state["mandatory_items_multiselect"] = []


output_tab_index = tabs.index("Files & Receipts")
with tab_objects[output_tab_index]:
    st.markdown("<h3 style='color: #1E1E1E;'>PDF Invoice, Multiple Invoices, Receipts</h3>", unsafe_allow_html=True)
    # --- Backward-compatible widget-key aliases ---
    # Older versions relied on Streamlit's implicit (label-based) widget keys.
    # Newer versions set explicit keys so other tabs (like Invoice Details) can reliably read these values.
    if "generate_multiple_invoices" not in st.session_state and "Generate Multiple Invoices" in st.session_state:
        st.session_state["generate_multiple_invoices"] = st.session_state["Generate Multiple Invoices"]
    if "multiple_billing_periods" not in st.session_state and "Multiple Billing Periods" in st.session_state:
        st.session_state["multiple_billing_periods"] = st.session_state["Multiple Billing Periods"]
    if "num_billing_periods" not in st.session_state:
        for _k in ("How many billing periods:", "How Many Billing Periods:", "How Many Billing Periods", "How many billing periods"):
            if _k in st.session_state:
                st.session_state["num_billing_periods"] = st.session_state[_k]
                break

    include_pdf = st.checkbox("Include PDF Invoice", value=False)
    
    uploaded_logo = None
    logo_width = None
    logo_height = None
    
    if include_pdf:
        include_logo = st.checkbox("Include Logo in PDF", value=True, help="Uncheck to exclude logo from PDF header, using only law firm text.")
    
    generate_multiple = st.checkbox("Generate Multiple Invoices", key="generate_multiple_invoices", help="Create more than one invoice.")
    num_invoices = 1
    multiple_periods = False
    if generate_multiple:
        combine_ledes = st.checkbox("Combine LEDES into single file", help="If checked, all generated LEDES invoices will be combined into a single file with one header.")
        multiple_periods = st.checkbox("Multiple Billing Periods", key="multiple_billing_periods", help="Backfills one invoice per prior month from the given end date, newest to oldest.")
        if multiple_periods:
            num_periods = st.number_input("How Many Billing Periods:", key="num_billing_periods", min_value=2, max_value=6, value=2, step=1, help="Number of month-long periods to create (overrides Number of Invoices).")
            num_invoices = num_periods
        else:
            num_invoices = st.number_input("Number of Invoices to Create:", min_value=1, value=1, step=1, help="Creates N invoices. When 'Multiple Billing Periods' is enabled, one invoice per period.")
    else:
        combine_ledes = False

    generate_receipts = st.checkbox("Generate Sample Receipts for Expenses?", value=False)
    zip_receipts = False
    if generate_receipts:
        zip_receipts = st.checkbox("Zip Receipts", value=True, key="zip_receipts", help="Combine all generated receipt images into a single ZIP file.")

# Email Configuration Tab (only created if send_email is True)
if st.session_state.send_email:
    email_tab_index = len(tabs) - 1
    with tab_objects[email_tab_index]:
        st.markdown("<h2 style='color: #1E1E1E;'>Email Configuration</h2>", unsafe_allow_html=True)
        recipient_email = st.text_input("Recipient Email Address:")
        try:
            sender_email = st.secrets.email.email_from
            st.caption(f"Sender Email will be from: {st.secrets.get('email', {}).get('username', 'N/A')}")
        except AttributeError:
            st.caption("Sender Email: Not configured (check secrets.toml)")
        st.text_input("Email Subject Template:", value=f"LEDES Invoice for {matter_number_base} (Invoice #{{invoice_number}})", key="email_subject")
        st.text_area("Email Body Template:", value=f"Please find the attached invoice files for matter {{matter_number}}.\n\nBest regards,\nYour Law Firm", height=150, key="email_body")
else:
    recipient_email = ""

# Validation Logic

# --- Tax Fields Tab (only if 1998BIv2 selected) ---
if "Tax Fields" in tabs:
    tax_tab_index = tabs.index("Tax Fields")
    with tab_objects[tax_tab_index]:
        st.markdown("<h2 style='color: #1E1E1E;'>Tax Fields</h2>", unsafe_allow_html=True)
        st.session_state.setdefault("tax_matter_name", "")
        st.session_state.setdefault("tax_po_number", "")
        st.session_state.setdefault("tax_client_matter_id", "")
        st.session_state.setdefault("tax_invoice_currency", "USD")
        st.session_state.setdefault("tax_rate", 0.19)

        st.text_input("Matter Name *", key="tax_matter_name")
        st.text_input("PO Number (optional)", key="tax_po_number")
        st.text_input("Client Matter ID *", key="tax_client_matter_id")
        st.selectbox("Invoice Currency *", ["USD", "AUD", "CAD", "GBP", "EUR"], index=["USD", "AUD", "CAD", "GBP", "EUR"].index(st.session_state.get("tax_invoice_currency", "USD")), key="tax_invoice_currency")
        st.number_input("Tax Rate *", min_value=0.0, max_value=1.0, step=0.01, value=st.session_state.get("tax_rate", 0.19), key="tax_rate")
        st.selectbox("Tax Type *", ["VAT","PST","QST","GST"], index=0, key="tax_type", help="Type of tax to apply to line items.")

        with st.expander("Law Firm Details"):
            st.text_input("Law Firm Address 1", key="pf_lf_address1", disabled=(_is_vat_profile(st.session_state.get("active_profile_id")) and not st.session_state.get("allow_override", False)))
            st.text_input("Law Firm Address 2", key="pf_lf_address2", disabled=(_is_vat_profile(st.session_state.get("active_profile_id")) and not st.session_state.get("allow_override", False)))
            st.text_input("Law Firm City", key="pf_lf_city", disabled=(_is_vat_profile(st.session_state.get("active_profile_id")) and not st.session_state.get("allow_override", False)))
            st.text_input("Law Firm State/Region", key="pf_lf_state", disabled=(_is_vat_profile(st.session_state.get("active_profile_id")) and not st.session_state.get("allow_override", False)))
            st.text_input("Law Firm Postcode", key="pf_lf_postcode", disabled=(_is_vat_profile(st.session_state.get("active_profile_id")) and not st.session_state.get("allow_override", False)))
            st.text_input("Law Firm Country", key="pf_lf_country", disabled=(_is_vat_profile(st.session_state.get("active_profile_id")) and not st.session_state.get("allow_override", False)))
            st.text_input("Law Firm Tax ID", key="pf_law_firm_id", disabled=(_is_vat_profile(st.session_state.get("active_profile_id")) and not st.session_state.get("allow_override", False)))

        with st.expander("Client Details"):
            st.text_input("Client Address 1", key="pf_client_address1", disabled=(_is_vat_profile(st.session_state.get("active_profile_id")) and not st.session_state.get("allow_override", False)))
            st.text_input("Client Address 2", key="pf_client_address2", disabled=(_is_vat_profile(st.session_state.get("active_profile_id")) and not st.session_state.get("allow_override", False)))
            st.text_input("Client City", key="pf_client_city", disabled=(_is_vat_profile(st.session_state.get("active_profile_id")) and not st.session_state.get("allow_override", False)))
            st.text_input("Client State/Region", key="pf_client_state", disabled=(_is_vat_profile(st.session_state.get("active_profile_id")) and not st.session_state.get("allow_override", False)))
            st.text_input("Client Postcode", key="pf_client_postcode", disabled=(_is_vat_profile(st.session_state.get("active_profile_id")) and not st.session_state.get("allow_override", False)))
            st.text_input("Client Country", key="pf_client_country", disabled=(_is_vat_profile(st.session_state.get("active_profile_id")) and not st.session_state.get("allow_override", False)))
            st.text_input("Client Tax ID", key="pf_client_tax_id", disabled=(_is_vat_profile(st.session_state.get("active_profile_id")) and not st.session_state.get("allow_override", False)))

is_valid_input = True
if timekeeper_data is None:
    st.error("Please upload a valid timekeeper CSV file.")
    is_valid_input = False
if billing_start_date >= billing_end_date:
    st.error("Billing start date must be before end date.")
    is_valid_input = False
if st.session_state.send_email and not recipient_email:
    st.error("Please provide a recipient email address.")
    is_valid_input = False
if not invoice_number_base or not matter_number_base:
    st.error("Invoice Number and Matter Number cannot be empty.")
    is_valid_input = False

# --- 1998BIv2 validation ---
if st.session_state.get("ledes_version") == "1998BIv2":
    if not st.session_state.get("tax_matter_name", "").strip():
        st.error("Matter Name is required for LEDES 1998BIv2.")
        is_valid_input = False
    if st.session_state.get("tax_invoice_currency", "USD") not in ["USD","AUD","CAD","GBP","EUR"]:
        st.error("Invoice Currency must be one of USD, AUD, CAD, GBP, EUR.")
        is_valid_input = False
    if st.session_state.get("tax_rate", 0.19) < 0:
        st.error("Tax Rate must be zero or positive.")
        is_valid_input = False

if combine_ledes and num_invoices <= 1:
    st.error("Cannot combine LEDES file if only one invoice is being generated.")
    is_valid_input = False
# --- External Line Item Details confirmation ---
_has_external_line_item_details = bool(globals().get("uploaded_custom_tasks_file"))
if not _has_external_line_item_details:
    st.warning(
        "No Line Item Details CSV is loaded. If you continue, the invoice will be created with only the Expense Line Items and any Spend Agent hard-coded fees you selected.",
        icon="⚠️"
    )
    confirm_no_line_items = st.checkbox(
        "I understand — continue without external line item details",
        key="confirm_no_line_item_details"
    )
    if not confirm_no_line_items:
        is_valid_input = False

st.markdown("---")
generate_button = st.button("Generate Invoice(s)", disabled=not is_valid_input)

# Final download/email logic
def get_mime_type(filename):
    if filename.endswith(".txt"): return "text/plain"
    if filename.endswith(".csv"): return "text/csv"
    if filename.endswith(".pdf"): return "application/pdf"
    if filename.endswith(".png"): return "image/png"
    if filename.endswith(".zip"): return "application/zip"
    return "application/octet-stream"

# Main App Logic
if generate_button:
    # Generate-time guard: if both main line-item counts are zero, make the user
    # explicitly aware before creating an invoice. If no alternate line-item source
    # is selected either, stop generation because the invoice would be empty.
    _fee_count_for_guard = int(st.session_state.get("fee_slider", fees) or 0)
    _expense_count_for_guard = int(st.session_state.get("expense_slider", expenses) or 0)

    if _fee_count_for_guard == 0 and _expense_count_for_guard == 0:
        _has_external_line_items_for_guard = bool(globals().get("uploaded_custom_tasks_file"))
        _has_block_billed_for_guard = bool(include_block_billed and int(num_block_billed or 0) > 0 and _has_external_line_items_for_guard)
        _has_vague_for_guard = bool(vague_line_items and _has_external_line_items_for_guard)
        _has_multiple_attendees_for_guard = bool(st.session_state.get("multiple_attendees_meeting", False))
        _has_spend_agent_for_guard = bool(
            spend_agent
            and (
                (selected_items if isinstance(selected_items, list) else [])
                or st.session_state.get("mismatch_line_items", False)
            )
        )

        _has_alternate_line_item_source = any([
            _has_block_billed_for_guard,
            _has_vague_for_guard,
            _has_multiple_attendees_for_guard,
            _has_spend_agent_for_guard,
        ])

        if not _has_alternate_line_item_source:
            st.warning(
                "Fee Line Items and Expense Line Items are both 0, and no other line-item source is selected. "
                "The generated invoice would not contain any line items. Increase at least one line-item count "
                "or select a Spend Agent item before generating the invoice.",
                icon="⚠️",
            )
            st.stop()

        st.warning(
            "Fee Line Items and Expense Line Items are both 0. The invoice will only contain line items from "
            "the other selected options, such as Spend Agent, block-billed, vague, or multiple-attendee items.",
            icon="⚠️",
        )

    # Reset troubleshooting summaries for this run
    st.session_state["pp_partner_paralegal_summary"] = []
    st.session_state["mismatch_line_items_summary"] = []
    try:
        _pp_items_for_flag = st.session_state.get("mandatory_items_multiselect", []) or []
        st.session_state["_pp_summary_expected"] = bool(spend_agent and any(_is_partner_paralegal_item(it) for it in _pp_items_for_flag))
    except Exception:
        st.session_state["_pp_summary_expected"] = False
    try:
        st.session_state["_mismatch_summary_expected"] = bool(spend_agent and st.session_state.get("mismatch_line_items", False))
    except Exception:
        st.session_state["_mismatch_summary_expected"] = False

    if ledes_version == "XML 2.1":
        st.error("LEDES XML 2.1 is not yet implemented. Please switch to 1998B.")
        st.stop()
    
    faker = Faker()
    descriptions = [d.strip() for d in invoice_desc.split('\n') if d.strip()]
    num_invoices = int(num_invoices)
    
    if multiple_periods and len(descriptions) != num_invoices:
        st.warning(f"You have selected to generate {num_invoices} invoices, but provided {len(descriptions)} descriptions. Please provide one description per period.")
    else:
        attachments_list = []
        receipts_by_invoice = {}  # invoice_number -> list of {"zip_path","flat_name","data"}
        receipt_manifest_rows = []  # mapping receipts back to invoices
        combined_ledes_content = ""
        zip_receipts_enabled = st.session_state.get('zip_receipts', False) if generate_receipts else False

        with st.status("Generating invoices...") as status:
            current_end_date = billing_end_date
            current_start_date = billing_start_date
            
            for i in range(num_invoices):
                if multiple_periods and i > 0:
                    current_end_date = current_start_date - datetime.timedelta(days=1)
                    current_start_date = current_end_date.replace(day=1)
                
                status.update(label=f"Generating Invoice {i+1}/{num_invoices} for period {current_start_date} to {current_end_date}")
                
                current_invoice_desc = descriptions[i] if multiple_periods and i < len(descriptions) else descriptions[0]
                
                # Adjust mandatory fee/expense counts so total line counts match user inputs.
                pp_selected = any(_is_partner_paralegal_item(it) for it in selected_items)
                pp_lines = 0
                if pp_selected:
                    base_n = int(st.session_state.get("pp_lines_per_invoice", 1) or 1)
                    base_n = max(1, base_n)
                    # If generating multiple invoices and the user enabled randomization, choose a per-invoice count.
                    if (int(num_invoices) > 1) and st.session_state.get("pp_randomize_count_per_invoice", False):
                        pp_lines = random.randint(1, base_n)
                    else:
                        pp_lines = base_n
                st.session_state["_pp_lines_this_invoice"] = int(pp_lines)

                mismatch_selected = bool(spend_agent and st.session_state.get("mismatch_line_items", False))
                mismatch_lines_to_add = random.randint(10, 55) if (mismatch_selected and _has_mismatch_pool_rows()) else 0
                st.session_state["_mismatch_lines_this_invoice"] = int(mismatch_lines_to_add)

                num_mandatory_fees = (
                    sum(
                        1
                        for item in selected_items
                        if (not CONFIG['MANDATORY_ITEMS'][item]['is_expense']) and (not _is_partner_paralegal_item(item))
                    )
                    + (pp_lines if pp_selected else 0)
                    + mismatch_lines_to_add
                )
                num_mandatory_expenses = sum(1 for item in selected_items if CONFIG['MANDATORY_ITEMS'][item]['is_expense'])

                fees_to_generate = max(0, fees - num_mandatory_fees)
                expenses_to_generate = max(0, expenses - num_mandatory_expenses)

                rows, total_amount = _generate_invoice_data(
                    fees_to_generate, expenses_to_generate, timekeeper_data, client_id, law_firm_id,
                    current_invoice_desc, current_start_date, current_end_date,
                    task_activity_desc, CONFIG['MAJOR_TASK_CODES'], max_daily_hours, num_block_billed, faker,
                    vague_line_items
                )
                # Invoice numbering (computed early so Spend Agent summaries can label rows)
                # - Single invoice: use the base as-is
                # - Multiple invoices (not Multiple Billing Periods): append -1, -2, ...
                # - Multiple Billing Periods: keep the base for the current period (i==0),
                #   and rewrite YYYY-MMM for prior periods while preserving the suffix
                if multiple_periods:
                    if i == 0:
                        current_invoice_number = str(invoice_number_base)
                    else:
                        current_invoice_number = _invoice_number_for_period(invoice_number_base, current_end_date)
                else:
                    current_invoice_number = (f"{invoice_number_base}-{i+1}" if int(num_invoices) > 1 else str(invoice_number_base))
                current_matter_number = matter_number_base

                # Store for troubleshooting summary labeling
                st.session_state["_pp_invoice_number"] = current_invoice_number
                st.session_state["_pp_billing_start"] = current_start_date.strftime("%Y-%m-%d")
                st.session_state["_pp_billing_end"] = current_end_date.strftime("%Y-%m-%d")
                st.session_state["_mismatch_invoice_number"] = current_invoice_number
                st.session_state["_mismatch_billing_start"] = current_start_date.strftime("%Y-%m-%d")
                st.session_state["_mismatch_billing_end"] = current_end_date.strftime("%Y-%m-%d")

                mismatch_warnings = []
                if spend_agent and st.session_state.get("mismatch_line_items", False):
                    rows, mismatch_warnings = _append_mismatch_line_items(
                        rows, timekeeper_data, current_invoice_desc, client_id, law_firm_id,
                        current_start_date, current_end_date, faker,
                        mismatch_count=st.session_state.get("_mismatch_lines_this_invoice") or None,
                    )

                skipped_mandatory_items = []
                if spend_agent:
                    rows, skipped_mandatory_items = _ensure_mandatory_lines(
                        rows, timekeeper_data, current_invoice_desc, client_id, law_firm_id, 
                        current_start_date, current_end_date, selected_items
                        ,
                        randomize_amounts_per_invoice=(int(num_invoices) > 1)
                    )
                
                df_invoice = pd.DataFrame(rows)
                total_amount = df_invoice["LINE_ITEM_TOTAL"].sum()
                
                if skipped_mandatory_items:
                    skipped_list = ", ".join(f"'{item}'" for item in skipped_mandatory_items)
                    st.warning(
                        f"**Mandatory Items Skipped:** The following items were not added to the invoice because their assigned timekeepers were not found in your CSV file: **{skipped_list}**"
                    )

                if mismatch_warnings:
                    st.warning("**Mismatch Line Items:** " + " ".join(str(msg) for msg in mismatch_warnings if msg))

                # Invoice numbering already computed above
                
                is_first = (i == 0) and combine_ledes
                if ledes_version == "1998BIv2":
                    ledes_content_part = _create_ledes_1998biv2_content(
                        rows,
                        current_start_date, current_end_date,
                        current_invoice_number, current_matter_number,
                        st.session_state.get('tax_matter_name',''),
                        st.session_state.get('tax_po_number',''),
                        st.session_state.get('tax_client_matter_id',''),
                        st.session_state.get('tax_invoice_currency','USD'),
                        st.session_state.get('tax_rate', 0.19),
                        is_first_invoice=not combine_ledes or is_first
                    )
                elif ledes_version == "1998BI":
                    ledes_content_part = _create_ledes_1998bi_content(
                        rows,
                        current_start_date, current_end_date,
                        current_invoice_number, current_matter_number,
                        st.session_state.get('tax_matter_name',''),
                        st.session_state.get('tax_po_number',''),
                        st.session_state.get('tax_client_matter_id',''),
                        st.session_state.get('tax_invoice_currency','USD'),
                        st.session_state.get('tax_rate', 0.19),
                        is_first_invoice=not combine_ledes or is_first
                    )
                else:
                    ledes_content_part = _create_ledes_1998b_content(
                        rows,
                        total_amount,
                        current_start_date, current_end_date,
                        current_invoice_number, current_matter_number,
                        is_first_invoice=not combine_ledes or is_first
                    )
                if combine_ledes:
                    combined_ledes_content += ledes_content_part + "\n"
                else:
                    ledes_filename = (f"LEDES_1998BI_{current_invoice_number}.txt" if ledes_version == "1998BI" else (f"LEDES_1998BIv2_{current_invoice_number}.txt" if ledes_version == "1998BIv2" else f"LEDES_1998B_{current_invoice_number}.txt"))
                    attachments_list.append((ledes_filename, ledes_content_part.encode('utf-8')))
                
                if include_pdf:
                    logo_bytes = None
                    if include_logo:
                        use_custom_logo = st.session_state.get('use_custom_logo_checkbox', False)
                        logo_bytes = _get_logo_bytes(uploaded_logo, law_firm_id, use_custom_logo)
                    
                    pdf_filename = f"Invoice_{current_invoice_number}.pdf"
                    pdf_buffer = _create_pdf_invoice(
                        df_invoice,
                        total_amount,
                        current_invoice_number,
                        current_end_date,
                        current_start_date,
                        current_end_date,
                        client_id,
                        law_firm_id,
                        logo_bytes=logo_bytes,
                        include_logo=include_logo,
                        client_name=client_name,
                        law_firm_name=law_firm_name,
                        ledes_version=ledes_version,
                        matter_name=st.session_state.get('tax_matter_name',''),
                        po_number=st.session_state.get('tax_po_number',''),
                        client_matter_id=st.session_state.get('tax_client_matter_id',''),
                        invoice_currency=st.session_state.get('tax_invoice_currency','USD'),
                        tax_rate=st.session_state.get('tax_rate', 0.19)
                    )
                    attachments_list.append((pdf_filename, pdf_buffer.getvalue()))
                
                if generate_receipts:
                    receipts_by_invoice.setdefault(current_invoice_number, [])
                    for line_no, (_, row) in enumerate(df_invoice.iterrows(), start=1):
                        if row.get('EXPENSE_CODE') and row.get('EXPENSE_CODE') != 'E101':
                            _unused_name, receipt_data_buf = _create_receipt_image(row.to_dict(), faker)
                            if receipt_data_buf:
                                exp_code = str(row.get('EXPENSE_CODE','')).strip()
                                li_date = row.get('LINE_ITEM_DATE','')
                                if isinstance(li_date, (datetime.date, datetime.datetime)):
                                    dt_str = li_date.strftime('%Y%m%d')
                                else:
                                    dt_str = str(li_date).replace('-', '')
                                unique = uuid.uuid4().hex[:6]
                                zip_path = f"receipts/{current_invoice_number}/Receipt_L{line_no}_{exp_code}_{dt_str}_{unique}.png"
                                flat_name = f"{current_invoice_number}__Receipt_L{line_no}_{exp_code}_{dt_str}_{unique}.png"
                                receipts_by_invoice[current_invoice_number].append({
                                    'zip_path': zip_path,
                                    'flat_name': flat_name,
                                    'data': receipt_data_buf.getvalue(),
                                })
                                desc = row.get('DESCRIPTION', '') or row.get('LINE_ITEM_DESCRIPTION', '')
                                receipt_manifest_rows.append({
                                    'invoice_number': current_invoice_number,
                                    'zip_path': zip_path,
                                    'flat_name': flat_name,
                                    'line_no': line_no,
                                    'expense_code': exp_code,
                                    'line_item_date': str(li_date),
                                    'amount': row.get('LINE_ITEM_TOTAL', ''),
                                    'description': desc,
                                })

            # Process receipts after loop (across ALL invoices)
            any_receipts = any(files for files in receipts_by_invoice.values())
            if any_receipts:
                if zip_receipts_enabled:
                    zip_buf = io.BytesIO()
                    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zip_file:
                        for inv_no, files in receipts_by_invoice.items():
                            for f in files:
                                zip_file.writestr(f["zip_path"], f["data"])
                        if receipt_manifest_rows:
                            out = io.StringIO()
                            writer = csv.DictWriter(out, fieldnames=list(receipt_manifest_rows[0].keys()))
                            writer.writeheader()
                            writer.writerows(receipt_manifest_rows)
                            zip_file.writestr("manifest.csv", out.getvalue().encode("utf-8"))
                    zip_buf.seek(0)
                    attachments_list.append(("receipts.zip", zip_buf.getvalue()))
                else:
                    for inv_no, files in receipts_by_invoice.items():
                        for f in files:
                            attachments_list.append((f["flat_name"], f["data"]))
                    if receipt_manifest_rows:
                        out = io.StringIO()
                        writer = csv.DictWriter(out, fieldnames=list(receipt_manifest_rows[0].keys()))
                        writer.writeheader()
                        writer.writerows(receipt_manifest_rows)
                        attachments_list.append(("receipt_manifest.csv", out.getvalue().encode("utf-8")))

            # This is inside the `if generate_button:` block
            
            # After the loop, store all generated files (except combined LEDES) in session state
            st.session_state.generated_files = attachments_list
            
            # Handle combined LEDES separately if needed
            if combine_ledes:
                st.session_state.generated_files.insert(0, ("LEDES_Combined.txt", combined_ledes_content.encode('utf-8')))

            # Handle Emailing
            if st.session_state.send_email:
                subject, body = _customize_email_body(current_matter_number, f"{invoice_number_base}-Combined" if combine_ledes else f"{current_invoice_number}")
                
                # Use the files stored in session state for the email
                if not _send_email_with_attachment(recipient_email, subject, body, st.session_state.generated_files):
                    st.error("Email failed to send. You can download the files below.")
                else:
                    # Clear the files after successful send so buttons don't linger
                    st.session_state.generated_files = [] 
            
            status.update(label="Invoice generation complete!", state="complete")


# --- New Display Block (place this AFTER the `if generate_button:` block) ---
# This block runs on every interaction, ensuring the buttons stay visible.
if "generated_files" in st.session_state and st.session_state.generated_files:
    st.subheader("Generated Files")
    # Use columns for a cleaner layout if many files are generated
    cols = st.columns(3) 
    col_idx = 0
    for filename, data in st.session_state.generated_files:
        with cols[col_idx % 3]:
            st.download_button(
                label=f"Download {filename}",
                data=data,
                file_name=filename,
                mime=get_mime_type(filename),
                key=f"download_{filename}" # Unique key is important
            )
        col_idx += 1



# --- Partner → Paralegal Summary (shown after generation, if applicable) ---
_pp_sum = st.session_state.get("pp_partner_paralegal_summary", []) or []
_pp_expected = bool(st.session_state.get("_pp_summary_expected", False))

if _pp_sum or _pp_expected:
    with st.expander("Partner → Paralegal Summary", expanded=False):
        if _pp_sum:
            try:
                df_pp = pd.DataFrame(_pp_sum)

                # A quick counts view by invoice number
                if "Invoice Number" in df_pp.columns:
                    counts = df_pp.groupby(["Invoice Number"]).size().reset_index(name="Line Count")
                    st.caption("Counts by invoice")
                    st.dataframe(counts, use_container_width=True)

                st.caption("Line item details (Partner billing Paralegal-classified work)")
                # Sort for readability when possible
                sort_cols = [c for c in ["Invoice Number", "Line Item Date"] if c in df_pp.columns]
                if sort_cols:
                    df_pp = df_pp.sort_values(sort_cols)
                # Re-number the displayed row index to be a logical 1..N list (after sorting)
                df_pp = df_pp.reset_index(drop=True)
                df_pp.index = range(1, len(df_pp) + 1)
                st.dataframe(df_pp, use_container_width=True)
            except Exception:
                st.write(_pp_sum)
        else:
            st.info(
                "No Partner → Paralegal lines were generated. This can happen if the mandatory item wasn’t selected, "
                "no Partner timekeepers were found in the TK CSV, or no Paralegal-tagged rows were found in the line item CSV."
            )


# --- Mismatch Line Items Summary (shown after generation, if applicable) ---
_mismatch_sum = st.session_state.get("mismatch_line_items_summary", []) or []
_mismatch_expected = bool(st.session_state.get("_mismatch_summary_expected", False))

if _mismatch_sum or _mismatch_expected:
    with st.expander("Mismatch Line Items Summary", expanded=False):
        if _mismatch_sum:
            try:
                df_mismatch = pd.DataFrame(_mismatch_sum)

                # A quick counts view by invoice number for invoice-review troubleshooting.
                if "Invoice Number" in df_mismatch.columns:
                    counts = df_mismatch.groupby(["Invoice Number"]).size().reset_index(name="Line Count")
                    st.caption("Counts by invoice")
                    st.dataframe(counts, use_container_width=True)

                st.caption("Line item details (MISMATCH = Y rows added by Spend Agent)")
                sort_cols = [c for c in ["Invoice Number", "Line Item Date"] if c in df_mismatch.columns]
                if sort_cols:
                    df_mismatch = df_mismatch.sort_values(sort_cols)
                df_mismatch = df_mismatch.reset_index(drop=True)
                df_mismatch.index = range(1, len(df_mismatch) + 1)
                st.dataframe(df_mismatch, use_container_width=True)
            except Exception:
                st.write(_mismatch_sum)
        else:
            st.info(
                "No Mismatch line items were generated. This can happen if Spend Agent > Mismatch was selected "
                "but no Custom Line Item Details CSV was loaded, the CSV did not include a MISMATCH column, "
                "no rows had MISMATCH = Y, or no timekeeper data was available."
            )

