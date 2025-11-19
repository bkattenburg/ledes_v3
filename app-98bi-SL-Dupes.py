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

# Central boolean for sending email
st.session_state.setdefault("send_email", False)

import pandas as pd
import random
import datetime
import io
import os
import logging
import re
import smtplib
from typing import Optional, List, Dict, Any, Tuple
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from faker import Faker
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
from PIL import Image as PILImage, ImageDraw, ImageFont, Image
import zipfile

def _normalize_historic_columns(df: pd.DataFrame) -> pd.DataFrame:
    # Accept LEDES1998B-style names and map to simpler keys we’ll use downstream.
    rename_map = {
        # Descriptions are *not* used to clone, but normalizing is harmless
        "LINE_ITEM_DESCRIPTION": "DESCRIPTION",

        # Worked date
        "LINE_ITEM_WORKED_DATE": "LINE_ITEM_DATE",

        # Codes
        "LINE_ITEM_TASK_CODE": "TASK_CODE",
        "LINE_ITEM_ACTIVITY_CODE": "ACTIVITY_CODE",
        "LINE_ITEM_EXPENSE_CODE": "EXPENSE_CODE",

        # Money
        "LINE_ITEM_UNIT_COST": "TIMEKEEPER_RATE",
        "LINE_ITEM_BILLED_TOTAL": "LINE_ITEM_TOTAL",
        "BILLED_TOTAL": "LINE_ITEM_TOTAL",
        "AMOUNT": "LINE_ITEM_TOTAL",
        "CURRENCY_CODE": "LINE_ITEM_BILLED_TOTAL_CURRENCY",
        "INVOICE_CURRENCY_CODE": "LINE_ITEM_BILLED_TOTAL_CURRENCY",

        # Type
        "LINE_ITEM_TYPE": "EXP/FEE/INV_ADJ_TYPE",  # e.g., IF / F / E
    }
    present = {k: v for k, v in rename_map.items() if k in df.columns and v not in df.columns}
    if present:
        df = df.rename(columns=present)
    return df

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
    "Custom": {"fees": 20, "expenses": 5},
    "Small": {"fees": 10, "expenses": 5},
    "Medium": {"fees": 25, "expenses": 15},
    "Large": {"fees": 100, "expenses": 25},
}

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
BILLING_PROFILES = [("OnitX",    "A Onit Inc.",   "02-4388252", "Nelson & Murdock", "02-1234567"),
    ("OnitX VAT", "Onit LLC - Belgium", "", "Nelson and Murdock - Belgium", "3233384400"),
    ("SimpleLegal", "Penguin LLC",   "C004",       "JDL",               "JDL001"),
    ("Unity",       "Unity Demo",    "uniti-demo", "Gold USD",          "Gold USD"),
]

# Extended profile details (addresses, tax ids, defaults)
BILLING_PROFILE_DETAILS = {
    "OnitX VAT": {
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
            "country": "Belgium"
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
            "country": "Belgium"
        }
    }
}
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
    return max(1, min(200, max_lines))

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
        hours = float(row.get("HOURS", 0) or 0)
        rate = float(row.get("RATE", 0) or 0)
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
        # Corrected the return list to fix the indentation/syntax error
        return [
            bill_end.strftime("%Y%m%d"),
            str(invoice_number),
            str(row.get("CLIENT_ID", "")),
            str(matter_number),
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
            str(client_matter_id),
            str(matter_name),
            str(po_number),
            str(invoice_currency),
            f"{float(tax_rate):.2f}",
            str(st.session_state.get("tax_type","VAT"))]
    except Exception as e:
        logging.error(f"Error creating LEDES 1998BIv2 line: {e}")
        return []

def _create_ledes_1998biv2_content(rows: List[Dict],
                                   bill_start: datetime.date, bill_end: datetime.date,
                                   invoice_number: str, matter_number: str,
                                   matter_name: str, po_number: str,
                                   client_matter_id: str, invoice_currency: str,
                                   tax_rate: float, is_first_invoice: bool = True) -> str:
    """Generate LEDES 1998BIv2 content from invoice rows."""
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
    """Generate LEDES 1998BI content from invoice rows."""
    lines: List[str] = []
    if is_first_invoice:
        header = "LEDES1998BI[]"
        fields = ("INVOICE_DATE|INVOICE_NUMBER|CLIENT_ID|LAW_FIRM_MATTER_ID|INVOICE_TOTAL|"
                  "BILLING_START_DATE|BILLING_END_DATE|INVOICE_DESCRIPTION|LINE_ITEM_NUMBER|"
                  "EXP/FEE/INV_ADJ_TYPE|LINE_ITEM_NUMBER_OF_UNITS|LINE_ITEM_ADJUSTMENT_AMOUNT|"
                  "LINE_ITEM_TOTAL|LINE_ITEM_DATE|LINE_ITEM_TASK_CODE|LINE_ITEM_EXPENSE_CODE|"
                  "LINE_ITEM_ACTIVITY_CODE|TIMEKEEPER_ID|LINE_ITEM_DESCRIPTION|LAW_FIRM_ID|"
                  "LINE_ITEM_UNIT_COST|TIMEKEEPER_NAME|TIMEKEEPER_CLASSIFICATION|CLIENT_MATTER_ID[]")
        lines = [header, fields]
    else:
        lines = []

    subtotal = sum(float(r.get("LINE_ITEM_TOTAL", 0) or 0) for r in rows)
    tax_amount = round(subtotal * float(tax_rate or 0), 2)
    grand_total = subtotal + tax_amount

    for i, row in enumerate(rows, start=1):
        line = _create_ledes_line_1998bi(row, i, grand_total, bill_start, bill_end,
                                         invoice_number, matter_number, client_matter_id)
        if line:
            lines.append("|".join(map(str, line)) + "[]")
    return "\n".join(lines)

def _create_ledes_line_1998bi(row: Dict, line_no: int, inv_total: float,
                                bill_start: datetime.date, bill_end: datetime.date,
                                invoice_number: str, matter_number: str,
                                client_matter_id: str) -> List[str]:
    """Create a single LEDES 1998BI line."""
    try:
        date_obj = datetime.datetime.strptime(row["LINE_ITEM_DATE"], "%Y-%m-%d").date()
        hours = float(row.get("HOURS", 0) or 0)
        rate = float(row.get("RATE", 0) or 0)
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
        return [
            bill_end.strftime("%Y%m%d"),
            str(invoice_number),
            str(row.get("CLIENT_ID", "")),
            str(matter_number),
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
            str(client_matter_id)
        ]
    except Exception as e:
        logging.error(f"Error creating LEDES 1998BI line: {e}")
        return []

def _create_csv_content(rows: List[Dict]) -> str:
    """Generate generic CSV content from invoice rows."""
    if not rows:
        return ""
    df = pd.DataFrame(rows)
    # Select and reorder columns for a standard output
    columns = [
        "LINE_ITEM_DATE", "TIMEKEEPER_NAME", "TIMEKEEPER_CLASSIFICATION",
        "TIMEKEEPER_ID", "TASK_CODE", "ACTIVITY_CODE", "EXPENSE_CODE",
        "DESCRIPTION", "HOURS", "RATE", "LINE_ITEM_TOTAL",
        "INVOICE_DESCRIPTION", "CLIENT_ID", "LAW_FIRM_ID",
        "_is_block_billed_from_source"
    ]
    df = df.reindex(columns=[col for col in columns if col in df.columns])
    return df.to_csv(index=False)

def _create_xml_content(rows: List[Dict]) -> str:
    """Generate a simple XML representation of the invoice data."""
    if not rows:
        return "<Invoice><FeeLines/></Invoice>"
    xml_lines = ['<Invoice>']
    xml_lines.append(f'  <InvoiceDate>{datetime.date.today().strftime("%Y-%m-%d")}</InvoiceDate>')
    xml_lines.append('  <FeeLines>')
    for row in rows:
        xml_lines.append('    <LineItem>')
        for key, value in row.items():
            if key.startswith("_"): continue # Skip internal markers
            xml_lines.append(f'      <{key}>{value}</{key}>')
        xml_lines.append('    </LineItem>')
    xml_lines.append('  </FeeLines>')
    xml_lines.append('</Invoice>')
    return "\n".join(xml_lines)

def _generate_invoice_rows(fee_count: int, expense_count: int, timekeeper_data: List[Dict],
                           billing_start_date: datetime.date, billing_end_date: datetime.date,
                           invoice_desc: str, client_id: str, law_firm_id: str,
                           custom_task_data: Optional[List[Tuple[str, str, str]]],
                           max_hours_per_tk_per_day: int,
                           faker_instance: Faker,
                           source_df: Optional[pd.DataFrame] = None,
                           max_block_billed: Optional[int] = None) -> List[Dict]:
    """Generates the main list of fee and expense line items."""
    import random
    rows = []

    # 1. Handle Mandatory/Forced Items (e.g., Duplicates, specific test cases)
    mandatory_items_to_add = {}
    if st.session_state.get("add_duplicate_items", False):
        mandatory_items_to_add.update({
            'KBCG_1': CONFIG['MANDATORY_ITEMS']['KBCG'],
            'John Doe_1': CONFIG['MANDATORY_ITEMS']['John Doe'],
            'Partner: Paralegal Tasks_1': CONFIG['MANDATORY_ITEMS']['Partner: Paralegal Tasks'],
        })
    if st.session_state.get("add_blockbilling_error", False):
        # A single entry that looks like block billing to enforce the check
        desc = "Block billing entry: Researched case law, drafted memorandum, and client call."
        mandatory_items_to_add['Forced Block Bill'] = {
            'desc': desc, 'tk_name': "Tom Delaganis", 'task': "L140", 'activity': "A107",
            'is_expense': False
        }
    if st.session_state.get("add_partner_paralegal", False):
        mandatory_items_to_add.update({
            'Partner: Paralegal Tasks_A': CONFIG['MANDATORY_ITEMS']['Partner: Paralegal Tasks'],
            'Partner: Paralegal Tasks_B': CONFIG['MANDATORY_ITEMS']['Partner: Paralegal Tasks'],
        })

    # Add mandatory items *first*
    for name, m_item in mandatory_items_to_add.items():
        if m_item['is_expense']:
            # Expense row creation for mandatory items
            row = {
                "INVOICE_DESCRIPTION": invoice_desc,
                "CLIENT_ID": client_id,
                "LAW_FIRM_ID": law_firm_id,
                "LINE_ITEM_DATE": billing_end_date.strftime("%Y-%m-%d"),
                "TIMEKEEPER_NAME": "", "TIMEKEEPER_CLASSIFICATION": "", "TIMEKEEPER_ID": "",
                "TASK_CODE": "", "ACTIVITY_CODE": "",
                "EXPENSE_CODE": m_item['expense_code'],
                "DESCRIPTION": _process_description(m_item['desc'], faker_instance),
                "HOURS": 1.0, # Not strictly hours, but units (e.g., quantity)
                "RATE": round(random.uniform(5.0, 500.0), 2),
                "LINE_ITEM_TOTAL": round(1.0 * random.uniform(5.0, 500.0), 2),
            }
        else:
            # Fee row creation for mandatory items
            # Pick a timekeeper based on the mandatory item's desired name
            tk_name = m_item['tk_name']
            tk = _find_timekeeper_by_name(timekeeper_data, tk_name)

            if tk is None:
                # If the specified timekeeper name isn't found, pick a random one
                tk = random.choice(timekeeper_data) if timekeeper_data else None
                if tk:
                    tk_name = tk.get("TIMEKEEPER_NAME", "")
                else:
                    continue # Skip if no timekeepers loaded
            
            hours = round(random.uniform(0.5, 3.0), 1)
            rate = float(tk.get("RATE", 0.0))
            
            row = {
                "INVOICE_DESCRIPTION": invoice_desc,
                "CLIENT_ID": client_id,
                "LAW_FIRM_ID": law_firm_id,
                "LINE_ITEM_DATE": billing_end_date.strftime("%Y-%m-%d"),
                "TIMEKEEPER_NAME": tk_name,
                "TIMEKEEPER_CLASSIFICATION": tk.get("TIMEKEEPER_CLASSIFICATION", ""),
                "TIMEKEEPER_ID": tk.get("TIMEKEEPER_ID", ""),
                "TASK_CODE": m_item['task'],
                "ACTIVITY_CODE": m_item['activity'],
                "EXPENSE_CODE": "",
                "DESCRIPTION": _process_description(m_item['desc'], faker_instance),
                "HOURS": hours,
                "RATE": rate,
                "LINE_ITEM_TOTAL": round(hours * rate, 2),
            }
        
        rows.append(row)
        # Decrement counts to account for mandatory items
        if not m_item['is_expense'] and fee_count > 0:
            fee_count -= 1
        elif m_item['is_expense'] and expense_count > 0:
            expense_count -= 1

    # 2. Generate Fee Lines
    if source_df is not None and not source_df.empty and st.session_state.get("use_custom_fees_with_bb", False):
        # Apply block billing limit to the source data *before* using it for generation
        df_enforced = _enforce_block_billed_limit_df(source_df, max_block_billed)

        # Generate fee lines from the source data
        fee_rows = _generate_fee_lines_from_source_df(
            df_enforced, fee_count, timekeeper_data, billing_start_date, billing_end_date,
            invoice_desc, client_id, law_firm_id, max_hours_per_tk_per_day, faker_instance
        )
        rows.extend(fee_rows)
        fee_count = 0 # All fee slots are now filled or exhausted by the source logic
    else:
        # Generate fee lines using standard random logic
        
        # Track hours per (date, tk_id)
        daily_hours = {}
        delta_days = (billing_end_date - billing_start_date).days
        if delta_days < 0:
            delta_days = 0

        for _ in range(fee_count):
            if not timekeeper_data:
                break # Can't generate fee lines without timekeepers

            # Pick a date
            day_offset = random.randint(0, delta_days) if delta_days > 0 else 0
            date_obj = billing_start_date + datetime.timedelta(days=day_offset)
            date_str = date_obj.strftime("%Y-%m-%d")

            # Pick timekeeper
            tk = random.choice(timekeeper_data)
            timekeeper_id = tk.get("TIMEKEEPER_ID", "")
            tk_name = tk.get("TIMEKEEPER_NAME", "")
            tk_class = tk.get("TIMEKEEPER_CLASSIFICATION", "")
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

            # Pick task/activity/description
            if custom_task_data:
                task_code, activity_code, description = random.choice(custom_task_data)
            else:
                task_code, activity_code, description = random.choice(CONFIG['DEFAULT_TASK_ACTIVITY_DESC'])
            
            description = _process_description(description, faker_instance)

            row = {
                "INVOICE_DESCRIPTION": invoice_desc,
                "CLIENT_ID": client_id,
                "LAW_FIRM_ID": law_firm_id,
                "LINE_ITEM_DATE": date_str,
                "TIMEKEEPER_NAME": tk_name,
                "TIMEKEEPER_CLASSIFICATION": tk_class,
                "TIMEKEEPER_ID": timekeeper_id,
                "TASK_CODE": task_code,
                "ACTIVITY_CODE": activity_code,
                "EXPENSE_CODE": "",
                "DESCRIPTION": description,
                "HOURS": hours,
                "RATE": rate,
                "LINE_ITEM_TOTAL": round(hours * rate, 2),
                "_is_block_billed_from_source": False, # Always false for randomly generated
            }
            rows.append(row)
            daily_hours[(date_str, timekeeper_id)] = daily_hours.get((date_str, timekeeper_id), 0.0) + hours


    # 3. Generate Expense Lines
    delta_days = (billing_end_date - billing_start_date).days
    if delta_days < 0:
        delta_days = 0

    for _ in range(expense_count):
        # Pick a date
        day_offset = random.randint(0, delta_days) if delta_days > 0 else 0
        date_obj = billing_start_date + datetime.timedelta(days=day_offset)
        date_str = date_obj.strftime("%Y-%m-%d")

        # Pick expense
        desc_key = random.choice(EXPENSE_DESCRIPTIONS)
        expense_code = CONFIG['EXPENSE_CODES'][desc_key]

        # Generate random amount
        amount = round(random.uniform(5.0, 500.0), 2)
        
        # Units/Quantity is usually 1 for most expenses, but can vary
        units = 1
        if expense_code in ["E101", "E102"]: # Copies/Printing might have higher quantities
            units = random.randint(1, 100)
            rate = round(amount / units, 2) if units > 0 else amount
        else:
            rate = amount
        
        # Use description key as a base description
        description = desc_key
        if desc_key in ["Telephone", "Online research"]:
            # Add some minor variation to the description
            description += f": call to {faker_instance.name()}"
        
        row = {
            "INVOICE_DESCRIPTION": invoice_desc,
            "CLIENT_ID": client_id,
            "LAW_FIRM_ID": law_firm_id,
            "LINE_ITEM_DATE": date_str,
            "TIMEKEEPER_NAME": "", "TIMEKEEPER_CLASSIFICATION": "", "TIMEKEEPER_ID": "",
            "TASK_CODE": "", "ACTIVITY_CODE": "",
            "EXPENSE_CODE": expense_code,
            "DESCRIPTION": description,
            "HOURS": float(units), # Using HOURS field for Unit Count in expense line
            "RATE": float(rate), # Using RATE field for Unit Cost in expense line
            "LINE_ITEM_TOTAL": round(amount, 2),
            "_is_block_billed_from_source": False,
        }
        rows.append(row)

    # 4. Final Processing and Sorting
    random.shuffle(rows) # Shuffle all rows for a natural appearance
    return rows

def _generate_pdf_invoice(rows: List[Dict],
                         invoice_number: str,
                         matter_id: str,
                         bill_start: datetime.date,
                         bill_end: datetime.date,
                         client_name: str,
                         law_firm_name: str,
                         profile_detail: Dict[str, Any]) -> io.BytesIO:
    """Generates a professional PDF invoice using ReportLab."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter,
                            topMargin=0.5 * inch, bottomMargin=0.5 * inch,
                            leftMargin=0.5 * inch, rightMargin=0.5 * inch)
    styles = getSampleStyleSheet()

    # Define custom styles
    styles.add(ParagraphStyle(name='Heading1', fontSize=18, leading=22, alignment=TA_CENTER, fontName='Helvetica-Bold'))
    styles.add(ParagraphStyle(name='Heading2', fontSize=14, leading=18, fontName='Helvetica-Bold'))
    styles.add(ParagraphStyle(name='NormalCenter', alignment=TA_CENTER))
    styles.add(ParagraphStyle(name='NormalRight', alignment=TA_RIGHT))
    styles.add(ParagraphStyle(name='NormalLeft', alignment=TA_LEFT))
    styles.add(ParagraphStyle(name='DataHeader', fontSize=10, leading=12, fontName='Helvetica-Bold', alignment=TA_CENTER))
    styles.add(ParagraphStyle(name='DataBody', fontSize=10, leading=12, fontName='Helvetica'))

    elements = []
    invoice_currency = profile_detail.get('invoice_currency', 'USD')
    tax_rate = profile_detail.get('tax_rate', 0.0)
    tax_type = profile_detail.get('tax_type', 'VAT')

    # --- Header ---
    elements.append(Paragraph("INVOICE", styles['Heading1']))
    elements.append(Spacer(1, 0.2 * inch))

    # --- Firm and Client Info Table ---
    firm_info = profile_detail.get('law_firm', {})
    client_info = profile_detail.get('client', {})

    law_firm_data = [
        [Paragraph(f"<b>Law Firm:</b> {law_firm_name}", styles['NormalLeft']), Paragraph(f"<b>Client:</b> {client_name}", styles['NormalLeft'])],
        [Paragraph(firm_info.get('address1', 'Law Firm Address 1'), styles['NormalLeft']), Paragraph(client_info.get('address1', 'Client Address 1'), styles['NormalLeft'])],
        [Paragraph(f"{firm_info.get('city', '')}, {firm_info.get('postcode', '')} {firm_info.get('country', '')}", styles['NormalLeft']),
         Paragraph(f"{client_info.get('city', '')}, {client_info.get('postcode', '')} {client_info.get('country', '')}", styles['NormalLeft'])],
        [Paragraph(f"Tax ID: {firm_info.get('tax_id', 'N/A')}", styles['NormalLeft']), Paragraph(f"Tax ID: {client_info.get('tax_id', 'N/A')}", styles['NormalLeft'])],
    ]

    info_table = Table(law_firm_data, colWidths=[3.5 * inch, 3.5 * inch])
    info_table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.25, colors.grey),
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 0.2 * inch))

    # --- Invoice Details Table ---
    details_data = [
        ["Invoice Number:", invoice_number],
        ["Matter ID:", matter_id],
        ["Billing Period:", f"{bill_start.strftime('%Y-%m-%d')} - {bill_end.strftime('%Y-%m-%d')}"],
        ["Invoice Date:", datetime.date.today().strftime('%Y-%m-%d')],
    ]
    details_table = Table(details_data, colWidths=[2 * inch, 5 * inch])
    details_table.setStyle(TableStyle([
        ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
        ('FONTNAME', (1,0), (1,-1), 'Helvetica'),
        ('ALIGN', (1,0), (1,-1), 'RIGHT'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
    ]))
    elements.append(details_table)
    elements.append(Spacer(1, 0.3 * inch))

    # --- Line Item Table ---
    table_data = []
    # Header Row
    table_data.append([
        Paragraph("Date", styles['DataHeader']),
        Paragraph("Timekeeper", styles['DataHeader']),
        Paragraph("Code (T/A/E)", styles['DataHeader']),
        Paragraph("Description", styles['DataHeader']),
        Paragraph("Units/Hrs", styles['DataHeader']),
        Paragraph("Rate/Cost", styles['DataHeader']),
        Paragraph(f"Total ({invoice_currency})", styles['DataHeader'])
    ])

    subtotal = 0.0

    for row in rows:
        is_expense = bool(row.get("EXPENSE_CODE", ""))
        date_str = row.get("LINE_ITEM_DATE", "")
        tk_name = row.get("TIMEKEEPER_NAME", "") if not is_expense else ""
        task_code = row.get("TASK_CODE", "")
        activity_code = row.get("ACTIVITY_CODE", "")
        expense_code = row.get("EXPENSE_CODE", "")
        description = row.get("DESCRIPTION", "")
        units = row.get("HOURS", 0.0)
        rate = row.get("RATE", 0.0)
        total = row.get("LINE_ITEM_TOTAL", 0.0)

        # Determine the code column content
        if is_expense:
            code_str = expense_code
        else:
            code_str = f"{task_code}/{activity_code}"

        table_data.append([
            Paragraph(date_str, styles['DataBody']),
            Paragraph(tk_name, styles['DataBody']),
            Paragraph(code_str, styles['DataBody']),
            Paragraph(description, styles['DataBody']),
            Paragraph(f"{units:.1f}" if not is_expense else f"{int(units)}", styles['DataBody']),
            Paragraph(f"{rate:.2f}", styles['DataBody']),
            Paragraph(f"{total:.2f}", styles['NormalRight']) # Right align money
        ])
        subtotal += float(total)

    # Calculate Totals
    tax_amount = round(subtotal * float(tax_rate), 2)
    grand_total = subtotal + tax_amount

    # Create the table object
    col_widths = [0.8 * inch, 1.0 * inch, 0.7 * inch, 2.5 * inch, 0.7 * inch, 0.7 * inch, 0.7 * inch]
    item_table = Table(table_data, colWidths=col_widths)

    # Style the table
    item_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.Color(0.85, 0.85, 0.85)), # Light gray header
        ('GRID', (0, 0), (-1, -1), 0.25, colors.black),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (4, 1), (6, -1), 'RIGHT'), # Align numerical columns to the right
        ('ALIGN', (0, 1), (3, -1), 'LEFT'), # Align text columns to the left
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
    ]))
    elements.append(item_table)
    elements.append(Spacer(1, 0.2 * inch))

    # --- Summary Table ---
    summary_data = [
        ["SUBTOTAL:", f"{subtotal:.2f}"],
        [f"{tax_type} ({tax_rate * 100:.2f}%):", f"{tax_amount:.2f}"],
        ["TOTAL DUE:", f"{grand_total:.2f}"],
    ]
    summary_table = Table(summary_data, colWidths=[5.5 * inch, 1.5 * inch])
    summary_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica'),
        ('FONTNAME', (1, -1), (1, -1), 'Helvetica-Bold'),
        ('BACKGROUND', (0, -1), (-1, -1), colors.Color(0.9, 0.9, 0.9)),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
    ]))
    elements.append(summary_table)

    doc.build(elements)
    buffer.seek(0)
    return buffer

def _send_email_with_attachment(recipient_email: str, subject: str, body: str, attachments: List[Tuple[str, io.BytesIO]]) -> bool:
    """Sends an email with attachments."""
    # NOTE: This is a placeholder function as Streamlit/Code Interpreter cannot send live email.
    # We will pretend to send, and then save the email details to a file for 'download'.
    
    # Check if a mail server is configured (not possible in this environment, but good practice)
    if not os.environ.get("EMAIL_HOST") or not os.environ.get("EMAIL_USER"):
        logging.warning("Email environment variables not configured. Skipping actual email send.")
        
        # Simulate success for the user if they requested an email
        st.success(f"Successfully generated files and simulated 'sending' email to {recipient_email} with attachments.")
        
        # Create a log file of the simulated email
        email_log = io.BytesIO()
        email_log_content = (
            f"--- SIMULATED EMAIL LOG ---\n"
            f"To: {recipient_email}\n"
            f"Subject: {subject}\n"
            f"Body:\n{body}\n\n"
            f"Attachments: {', '.join([name for name, _ in attachments])}\n"
            f"--- END LOG ---\n"
        ).encode('utf-8')
        email_log.write(email_log_content)
        email_log.seek(0)
        
        # Append the log to the generated files list so the user can download it
        attachments.append( ("simulated_email_log.txt", email_log) )
        st.session_state.generated_files = attachments
        return True # Simulate success

    # Actual (theoretical) email sending logic:
    try:
        msg = MIMEMultipart()
        msg['From'] = os.environ.get("EMAIL_USER")
        msg['To'] = recipient_email
        msg['Subject'] = subject

        msg.attach(MIMEText(body, 'plain'))

        for filename, data in attachments:
            part = MIMEApplication(data.getvalue(), Name=filename)
            part['Content-Disposition'] = f'attachment; filename="{filename}"'
            msg.attach(part)

        with smtplib.SMTP_SSL(os.environ["EMAIL_HOST"], int(os.environ["EMAIL_PORT"])) as server:
            server.login(os.environ["EMAIL_USER"], os.environ["EMAIL_PASS"])
            server.sendmail(os.environ["EMAIL_USER"], recipient_email, msg.as_string())
        return True
    except Exception as e:
        logging.error(f"Email send failed: {e}")
        return False

def get_mime_type(filename: str) -> str:
    """Determines the MIME type for download buttons."""
    if filename.endswith('.txt') or filename.endswith('.ledes'):
        return 'text/plain'
    if filename.endswith('.csv'):
        return 'text/csv'
    if filename.endswith('.pdf'):
        return 'application/pdf'
    if filename.endswith('.zip'):
        return 'application/zip'
    return 'application/octet-stream'

# ==============================================================================
# Streamlit UI
# ==============================================================================
st.set_page_config(layout="wide", page_title="Invoice Generator")

# --- Initialize session state ---
st.session_state.setdefault("timekeeper_data", [])
st.session_state.setdefault("custom_task_data", [])
st.session_state.setdefault("custom_fee_df", pd.DataFrame()) # Holds the source data for block-billing
st.session_state.setdefault("generated_files", [])

st.title("InVoice / LEDES Generator")

# --- Sidebar: Configuration & Uploads ---
with st.sidebar:
    st.header("Configuration")

    # Environment/Billing Profile Selector
    env_options = [p[0] for p in BILLING_PROFILES]
    st.session_state.current_env = st.selectbox("Select Environment Profile", env_options, key='env_select')
    
    # Load profile details
    client_name, client_id, law_firm_name, law_firm_id = get_profile(st.session_state.current_env)
    profile_detail = BILLING_PROFILE_DETAILS.get(st.session_state.current_env, {})
    
    # Default values from profile
    ledes_default = profile_detail.get('ledes_default', '1998B')
    invoice_currency = profile_detail.get('invoice_currency', 'USD')
    tax_rate_default = profile_detail.get('tax_rate', 0.0)

    # General Invoice Fields
    st.subheader("Invoice Details")
    st.session_state.invoice_number_base = st.text_input("Invoice Number (Base)", value="123456", key='inv_num_base')
    st.session_state.matter_number = st.text_input("Matter ID (Law Firm)", value="MATT001", key='matter_num')
    st.session_state.client_matter_id = st.text_input("Matter ID (Client)", value="CLIENTMATT001", key='client_matter_id')
    st.session_state.matter_name = st.text_input("Matter Name", value="General Litigation", key='matter_name')
    st.session_state.po_number = st.text_input("PO Number", value="PO12345", key='po_num')
    st.session_state.invoice_desc = st.text_input("Invoice Description", value=CONFIG['DEFAULT_INVOICE_DESCRIPTION'], key='inv_desc')
    st.session_state.invoice_currency = st.text_input("Invoice Currency", value=invoice_currency, key='inv_currency')
    
    # Dates
    today = datetime.date.today()
    st.session_state.billing_end_date = st.date_input("Billing End Date", value=today, key='bill_end_date')
    st.session_state.billing_start_date = st.date_input("Billing Start Date", value=st.session_state.billing_end_date - datetime.timedelta(days=30), key='bill_start_date')
    
    # LEDES Format & Tax
    st.subheader("Output Options")
    st.session_state.ledes_format = st.selectbox("LEDES Format", ["1998BIv2", "1998BI", "1998B"], index=["1998BIv2", "1998BI", "1998B"].index(ledes_default) if ledes_default in ["1998BIv2", "1998BI", "1998B"] else 0, key='ledes_format')
    st.session_state.tax_rate = st.number_input("Tax Rate (0.00 to 1.00)", min_value=0.0, max_value=1.0, value=tax_rate_default, step=0.01, format="%.2f", key='tax_rate')
    st.session_state.tax_type = st.text_input("Line Item Tax Type", value=profile_detail.get('tax_type', 'VAT'), key='tax_type')
    
    # File Uploads
    st.subheader("File Uploads")
    timekeeper_file = st.file_uploader("Upload Timekeeper CSV", type=['csv'], key='tk_upload')
    custom_tasks_file = st.file_uploader("Upload Custom Task/Activity CSV", type=['csv'], key='tasks_upload')

    # Load uploaded data
    timekeeper_data = _load_timekeepers(timekeeper_file)
    if timekeeper_data:
        st.session_state.timekeeper_data = timekeeper_data
        st.success(f"Loaded {len(timekeeper_data)} Timekeepers.")
    else:
        st.session_state.timekeeper_data = []
        st.warning("No timekeepers loaded. Fee lines cannot be generated.")

    custom_task_data = _load_custom_task_activity_data(custom_tasks_file)
    if custom_task_data is not None:
        st.session_state.custom_task_data = custom_task_data
        st.session_state.custom_fee_df = st.session_state.get("custom_fee_df", pd.DataFrame())
        st.success(f"Loaded {len(custom_task_data)} unique Custom Task/Activity lines.")
        
        # Block Billing Feature Toggle
        if not st.session_state.custom_fee_df.empty:
            bb_col = _get_blockbilling_col(st.session_state.custom_fee_df)
            if bb_col:
                st.session_state.custom_fee_df = _normalize_blockbilling(st.session_state.custom_fee_df, bb_col)
                block_count = st.session_state.custom_fee_df["is_block_billed"].sum()
                st.info(f"Detected Block Billing column '{bb_col}'. {int(block_count)} lines are marked as block-billed.")
                st.session_state.use_custom_fees_with_bb = st.checkbox(
                    "Use Custom Fees with Block Billing Logic (will respect max block lines)",
                    value=False, key='use_custom_bb_logic'
                )
                if st.session_state.use_custom_fees_with_bb:
                    st.session_state.max_block_billed = st.number_input(
                        "Max Block-Billed Lines Allowed (set to 0 to block all)",
                        min_value=0, value=int(block_count), key='max_block_billed_input'
                    )
                else:
                    st.session_state.max_block_billed = None
            else:
                st.session_state.use_custom_fees_with_bb = False
                st.session_state.max_block_billed = None
    else:
        st.session_state.custom_task_data = []
        st.session_state.custom_fee_df = pd.DataFrame()
        st.session_state.use_custom_fees_with_bb = False
        st.session_state.max_block_billed = None

# --- Main Content ---
st.subheader("Invoice Line Items Generation")

# Presets & Counts
col1, col2, col3 = st.columns(3)
with col1:
    st.selectbox("Invoice Size Preset", list(PRESETS.keys()), key='invoice_preset', index=0, on_change=apply_preset)
with col2:
    max_fees = _calculate_max_fees(st.session_state.timekeeper_data, st.session_state.billing_start_date, st.session_state.billing_end_date, st.session_state.get("max_daily_hours", 10))
    st.session_state.fee_count = st.slider("Number of Fee Lines", min_value=0, max_value=max_fees, value=st.session_state.get("fee_slider", 20), key='fee_slider')
with col3:
    st.session_state.expense_count = st.slider("Number of Expense Lines", min_value=0, max_value=100, value=st.session_state.get("expense_slider", 5), key='expense_slider')

st.session_state.max_daily_hours = st.number_input("Max Hours per Timekeeper per Day", min_value=1, max_value=24, value=10, key='max_daily_hours')

# Error/Validation Toggles
st.subheader("Error Injection (Optional)")
col4, col5, col6 = st.columns(3)
with col4:
    st.session_state.num_invoices = st.number_input("Number of Invoices to Generate", min_value=1, max_value=10, value=1, key='num_invoices')
    combine_ledes = st.checkbox("Combine LEDES into one file", value=False, key='combine_ledes')
with col5:
    st.session_state.add_duplicate_items = st.checkbox("Add duplicate fee lines (for testing duplicate detection)", value=False, key='add_dupes')
    st.session_state.add_partner_paralegal = st.checkbox("Add Partner doing Paralegal Tasks", value=False, key='add_partner_paralegal')
with col6:
    st.session_state.add_blockbilling_error = st.checkbox("Add a block-billing description", value=False, key='add_block_bill')
    st.session_state.send_email_toggle = st.checkbox("Send via Email (Simulated)", value=False, key='send_email_toggle')
    if st.session_state.send_email_toggle:
        st.session_state.recipient_email = st.text_input("Recipient Email", value="test@example.com", key='recipient_email')
    else:
        st.session_state.recipient_email = None

# --- Generate Button ---
generate_button = st.button("Generate Invoice(s)")

if generate_button:
    if not st.session_state.timekeeper_data and st.session_state.fee_count > 0:
        st.error("Cannot generate fee lines without timekeeper data. Please upload the Timekeeper CSV.")
    else:
        status = st.status("Generating Invoices...", expanded=True)
        st.session_state.generated_files = [] # Reset files

        # Initialize Faker for generating dynamic data
        faker = Faker()

        all_ledes_lines = []
        is_first_ledes_file = True

        for i in range(st.session_state.num_invoices):
            # Increment invoice number if generating multiple
            current_invoice_number = f"{st.session_state.invoice_number_base}-{i+1:02d}"

            status.write(f"Generating invoice {i+1} of {st.session_state.num_invoices}...")

            # 1. Generate Invoice Data
            invoice_rows = _generate_invoice_rows(
                fee_count=st.session_state.fee_count,
                expense_count=st.session_state.expense_count,
                timekeeper_data=st.session_state.timekeeper_data,
                billing_start_date=st.session_state.billing_start_date,
                billing_end_date=st.session_state.billing_end_date,
                invoice_desc=st.session_state.invoice_desc,
                client_id=client_id,
                law_firm_id=law_firm_id,
                custom_task_data=st.session_state.custom_task_data,
                max_hours_per_tk_per_day=st.session_state.max_daily_hours,
                faker_instance=faker,
                source_df=st.session_state.custom_fee_df if st.session_state.get("use_custom_fees_with_bb", False) else None,
                max_block_billed=st.session_state.max_block_billed
            )

            if not invoice_rows:
                status.warning(f"Invoice {i+1}: No line items generated. Skipping.")
                continue

            # 2. Finalize Totals
            total_subtotal = sum(float(r.get("LINE_ITEM_TOTAL", 0) or 0) for r in invoice_rows)
            total_tax_amount = round(total_subtotal * float(st.session_state.tax_rate), 2)
            total_grand_total = total_subtotal + total_tax_amount

            # 3. Generate LEDES Content
            ledes_content = ""
            ledes_filename = f"{current_invoice_number}.ledes"
            
            if st.session_state.ledes_format == "1998BIv2":
                ledes_content = _create_ledes_1998biv2_content(
                    rows=invoice_rows,
                    bill_start=st.session_state.billing_start_date,
                    bill_end=st.session_state.billing_end_date,
                    invoice_number=current_invoice_number,
                    matter_number=st.session_state.matter_number,
                    matter_name=st.session_state.matter_name,
                    po_number=st.session_state.po_number,
                    client_matter_id=st.session_state.client_matter_id,
                    invoice_currency=st.session_state.invoice_currency,
                    tax_rate=st.session_state.tax_rate,
                    is_first_invoice=is_first_ledes_file
                )
            elif st.session_state.ledes_format == "1998BI":
                 ledes_content = _create_ledes_1998bi_content(
                    rows=invoice_rows,
                    bill_start=st.session_state.billing_start_date,
                    bill_end=st.session_state.billing_end_date,
                    invoice_number=current_invoice_number,
                    matter_number=st.session_state.matter_number,
                    matter_name=st.session_state.matter_name, # Not used in 1998BI, but passed for consistency
                    po_number=st.session_state.po_number, # Not used in 1998BI, but passed for consistency
                    client_matter_id=st.session_state.client_matter_id,
                    invoice_currency=st.session_state.invoice_currency, # Not used in 1998BI, but passed for consistency
                    tax_rate=st.session_state.tax_rate, # Not used in 1998BI, but passed for consistency
                    is_first_invoice=is_first_ledes_file
                )
            elif st.session_state.ledes_format == "1998B":
                ledes_content = _create_ledes_1998b_content(
                    rows=invoice_rows,
                    inv_total=total_grand_total,
                    bill_start=st.session_state.billing_start_date,
                    bill_end=st.session_state.billing_end_date,
                    invoice_number=current_invoice_number,
                    matter_number=st.session_state.matter_number,
                    is_first_invoice=is_first_ledes_file
                )
            
            # For combined LEDES, append lines (skipping the header after the first file)
            if combine_ledes:
                if ledes_content:
                    lines = ledes_content.split('\n')
                    # Skip the first two lines (header and field names) for subsequent files
                    if is_first_ledes_file:
                        all_ledes_lines.extend(lines)
                    else:
                        all_ledes_lines.extend(lines[2:])
                is_first_ledes_file = False
            else:
                # Store individual LEDES file
                if ledes_content:
                    data_io = io.BytesIO(ledes_content.encode('utf-8'))
                    st.session_state.generated_files.append((ledes_filename, data_io))

            # 4. Generate CSV/PDF
            csv_content = _create_csv_content(invoice_rows)
            csv_filename = f"{current_invoice_number}.csv"
            if csv_content:
                data_io = io.BytesIO(csv_content.encode('utf-8'))
                st.session_state.generated_files.append((csv_filename, data_io))

            # Generate PDF only for the first invoice or if not combining
            if i == 0 or st.session_state.num_invoices == 1 or not combine_ledes:
                pdf_filename = f"{current_invoice_number}.pdf"
                pdf_buffer = _generate_pdf_invoice(
                    rows=invoice_rows,
                    invoice_number=current_invoice_number,
                    matter_id=st.session_state.matter_number,
                    bill_start=st.session_state.billing_start_date,
                    bill_end=st.session_state.billing_end_date,
                    client_name=client_name,
                    law_firm_name=law_firm_name,
                    profile_detail=profile_detail
                )
                st.session_state.generated_files.append((pdf_filename, pdf_buffer))

        # Handle Combined LEDES file
        if combine_ledes and all_ledes_lines:
            combined_content = "\n".join(all_ledes_lines)
            data_io = io.BytesIO(combined_content.encode('utf-8'))
            combined_filename = f"{st.session_state.invoice_number_base}-Combined.ledes"
            st.session_state.generated_files.append((combined_filename, data_io))

        # --- Email Sending Logic ---
        if st.session_state.send_email_toggle and st.session_state.recipient_email:
            recipient_email = st.session_state.recipient_email
            subject = f"Invoice Attached: {st.session_state.invoice_number_base}"
            body = (f"Dear Client,\n\nPlease find the attached invoice(s) for the billing period "
                    f"{st.session_state.billing_start_date} to {st.session_state.billing_end_date}.\n\n"
                    f"Total Grand Total: {total_grand_total:.2f} {st.session_state.invoice_currency}\n\n"
                    f"Regards,\n{law_firm_name}")
            
            # Create a zip of all generated files for the email attachment
            zip_buffer = io.BytesIO()
            zip_filename = f"Invoice_{st.session_state.invoice_number_base}-Combined.zip"
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                for filename, data_io in st.session_state.generated_files:
                    # Reset the pointer to the start of the buffer before zipping
                    data_io.seek(0)
                    # Use a unique name for the zip (prevents issues if all files are just '123456.ledes')
                    name_in_zip = filename
                    if filename.startswith(f"{st.session_state.invoice_number_base}-"):
                        # If a combined invoice, make the name clean in the zip
                        name_in_zip = filename 
                    elif st.session_state.num_invoices > 1:
                        # For multi-invoice, ensure the number is in the name
                        name_in_zip = filename
                    
                    zip_file.writestr(name_in_zip, data_io.read())
            
            zip_buffer.seek(0)
            
            # Temporarily replace generated_files with just the zip for the email function
            email_attachments = [(zip_filename, zip_buffer)]

            # Use the files stored in session state for the email
            if not _send_email_with_attachment(recipient_email, subject, body, email_attachments):
                st.error("Email failed to send. You can download the files below.")
            else:
                # Clear the files after successful send so buttons don't linger
                # Note: _send_email_with_attachment updates generated_files with a simulated log.
                pass # Do not clear here, let the simulated log show up in the download section
        
        status.update(label="Invoice generation complete!", state="complete")

# --- New Display Block (place this AFTER the `if generate_button:` block) ---
# This block runs on every interaction, ensuring the buttons stay visible.
st.subheader("Generated Files")
if "generated_files" in st.session_state and st.session_state.generated_files:
    # Use columns for a cleaner layout if many files are generated
    cols = st.columns(3) 
    col_idx = 0
    for filename, data in st.session_state.generated_files:
        with cols[col_idx % 3]:
            # Reset the pointer to the start of the buffer before reading
            data.seek(0) 
            st.download_button(
                label=f"Download {filename}",
                data=data.getvalue(),
                file_name=filename,
                mime=get_mime_type(filename),
                key=f"download_{filename}" # Unique key is important
            )
        col_idx += 1
else:
    st.info("Click 'Generate Invoice(s)' to create files.")
