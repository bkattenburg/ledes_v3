import streamlit as st


# --- Source selector helper ---
def _select_items_from_source(df_src, want_block: bool, k: int):
    import random
    if df_src is None or k <= 0:
        return []
    bbcol = None
    for name in ("Blockbilling","BlockBilling","Blockbilled","BlockBilled"):
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
    tks = [t for t in (timekeepers or []) if str(t.get("TIMEKEEPER_CLASSIFICATION","")).strip().lower() == str(target_class).strip().lower()]
    if not tks:
        tks = timekeepers or []
    return random.choice(tks) if tks else None

def _generate_fee_lines_from_source_df(df_source, fee_count, timekeeper_data, billing_start_date, billing_end_date, invoice_desc, client_id, law_firm_id, max_hours_per_tk_per_day, faker_instance):
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
from PIL import Image as PILImage, ImageDraw, ImageFont
import zipfile

#st.markdown("""
#    <style>
#        /* --- ERROR (Red) --- */
#        div[data-testid="stAlert"][data-alert-container-variant="error"] {
#            background-color: #000000;
#            color: #ff0000; /* Bright Red Text */
#            border-color: #8b0000 !important;
#        }
#
#        /* --- WARNING (Yellow) --- */
#        div[data-testid="stAlert"][data-alert-container-variant="warning"] {
#            background-color: #fff3cd;
#            color: #664d03; /* Dark Yellow/Brown Text */
#            border-color: #ffc107 !important;
#        }
#        
#        /* --- INFO (Blue) --- */
#        div[data-testid="stAlert"][data-alert-container-variant="info"] {
#            background-color: #d1ecf1;
#            color: #0c5460; /* Dark Blue/Teal Text */
#            border-color: #bee5eb !important;
#        }
#
#        /* --- SUCCESS (Green) --- */
#        div[data-testid="stAlert"][data-alert-container-variant="success"] {
#            background-color: #d4edda;
#            color: #155724; /* Dark Green Text */
#            border-color: #c3e6cb !important;
#        }
#    </style>
#""", unsafe_allow_html=True)

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
BILLING_PROFILES = [("VAT", "Onit LLC - Belgium", "", "Nelson and Murdock - Belgium", "3233384400"),
    ("Onit ELM",    "A Onit Inc.",   "02-4388252", "Nelson & Murdock", "02-1234567"),
    ("SimpleLegal", "Penguin LLC",   "C004",       "JDL",               "JDL001"),
    ("Unity",       "Unity Demo",    "uniti-demo", "Gold USD",          "Gold USD"),
]


# Extended profile details (addresses, tax ids, defaults)
BILLING_PROFILE_DETAILS = {
    "VAT": {
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
        return [
            bill_end.strftime("%Y%m%d"),
            str(invoice_number),
            str(row.get("CLIENT_ID", "")),
            str(matter_number),
            f"{inv_total:.2f}",  # tax-inclusive
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
            f"{float(tax_rate):.2f}"
        ,
            matter_name,
            po_number,
            invoice_currency,
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
    lf_id = (st.session_state.get("pf_law_firm_id") if st.session_state.get("allow_override") else st.session_state.get("law_firm_id", ""))
    lf_address1 = (st.session_state.get("pf_lf_address1") if st.session_state.get("allow_override") else st.session_state.get("lf_address1", ""))
    lf_address2 = (st.session_state.get("pf_lf_address2") if st.session_state.get("allow_override") else st.session_state.get("lf_address2", ""))
    lf_city = (st.session_state.get("pf_lf_city") if st.session_state.get("allow_override") else st.session_state.get("lf_city", ""))
    lf_state = (st.session_state.get("pf_lf_state") if st.session_state.get("allow_override") else st.session_state.get("lf_state", ""))
    lf_postcode = (st.session_state.get("pf_lf_postcode") if st.session_state.get("allow_override") else st.session_state.get("lf_postcode", ""))
    lf_country = (st.session_state.get("pf_lf_country") if st.session_state.get("allow_override") else st.session_state.get("lf_country", ""))
    cl_name = st.session_state.get("client_name","")
    cl_id = st.session_state.get("client_id","")
    cl_tax_id = (st.session_state.get("pf_client_tax_id") or st.session_state.get("client_tax_id",""))
    client_id_eff = cl_tax_id or cl_id
    cl_address1 = (st.session_state.get("pf_client_address1") if st.session_state.get("allow_override") else st.session_state.get("client_address1", ""))
    cl_address2 = (st.session_state.get("pf_client_address2") if st.session_state.get("allow_override") else st.session_state.get("client_address2", ""))
    cl_city = (st.session_state.get("pf_client_city") if st.session_state.get("allow_override") else st.session_state.get("client_city", ""))
    cl_state = (st.session_state.get("pf_client_state") if st.session_state.get("allow_override") else st.session_state.get("client_state", ""))
    cl_postcode = (st.session_state.get("pf_client_postcode") if st.session_state.get("allow_override") else st.session_state.get("client_postcode", ""))
    cl_country = (st.session_state.get("pf_client_country") if st.session_state.get("allow_override") else st.session_state.get("client_country", ""))

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
        units = _f(row.get("HOURS", 0)) if not is_expense else _f(row.get("LINE_ITEM_NUMBER_OF_UNITS", 1) or 1)
        unit_cost = _f(row.get("RATE", 0)) if not is_expense else _f(row.get("LINE_ITEM_UNIT_COST", 0))
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
            str(st.session_state.get("tax_type","VAT")),
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

    used_triples = set()  # NEW
    
    for _ in range(fee_count):
        if not task_activity_desc:
            break
        tk_row = random.choice(timekeeper_data)
        timekeeper_id = tk_row["TIMEKEEPER_ID"]
        # NEW: try up to 7 times to get a new triple not already used
        attempts = 0
        while True:
            if major_items and random.random() < 0.7:
                task_code, activity_code, description = random.choice(major_items)
            elif other_items:
                task_code, activity_code, description = random.choice(other_items)
            else:
                # no candidates
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
        elif expense_code == "E107":  # Delivery/messenger
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


#def _generate_invoice_data(
#    fee_count: int,
#    expense_count: int,
#    timekeeper_data: List[Dict],
#    client_id: str,
#    law_firm_id: str,
#    invoice_desc: str,
#    billing_start_date: datetime.date,
#    billing_end_date: datetime.date,
#    task_activity_desc: List[Tuple[str, str, str]],
#    major_task_codes: set,
#    max_hours_per_tk_per_day: int,
#    num_block_billed: int,               # <-- kept for compatibility; not used inside
#    faker_instance: Faker
#) -> Tuple[List[Dict], float]:
#    """Generate invoice data with fees and expenses."""
#    rows = []
#    rows.extend(_generate_fees(
#        fee_count, timekeeper_data, billing_start_date, billing_end_date,
#        task_activity_desc, major_task_codes, max_hours_per_tk_per_day,
#        faker_instance, client_id, law_firm_id, invoice_desc
#    ))
#    rows.extend(_generate_expenses(
#        expense_count, billing_start_date, billing_end_date, client_id, law_firm_id, invoice_desc
#    ))

    # Read remaining global block-billing budget (set by UI)
#    allowed_blocks = int(st.session_state.get("__bb_remaining", 0))

    # --- Source-driven blockbilling branch (uses uploaded CSV Blockbilling flags) ---
#    try:
#        # Prefer full, non-deduped upload if available
#        df_source = (
#            st.session_state.get("custom_fee_df_full", None)
#            or st.session_state.get("custom_fee_df", None)
#        )
#    except Exception:
#        df_source = None

#    bbcol = _get_blockbilling_col(df_source) if df_source is not None else None

#    if df_source is not None and bbcol:
#        try:
#            df_src_norm = _normalize_blockbilling(df_source, bbcol)
            # Optional pre-trim by remaining global budget to reduce work:
            # (still enforced again after generation)
#            df_src_norm = _enforce_block_billed_limit_df(df_src_norm, allowed_blocks)

            # Keep existing expenses; regenerate fees from source only
#            rows = [r for r in rows if r.get("EXPENSE_CODE")]
#            fee_rows_from_src = _generate_fee_lines_from_source_df(
#                df_source=df_src_norm,
#                fee_count=fee_count,
#                timekeeper_data=timekeeper_data,
#                billing_start_date=billing_start_date,
#                billing_end_date=billing_end_date,
#                invoice_desc=invoice_desc,
#                client_id=client_id,
#                law_firm_id=law_firm_id,
#                max_hours_per_tk_per_day=max_hours_per_tk_per_day,
#                faker_instance=faker_instance
#            )

            # Enforce global remaining cap on source-driven rows
#            created_here = 0
#            for r in fee_rows_from_src:
#                if r.get("_is_block_billed_from_source"):
#                    if created_here < allowed_blocks:
#                        created_here += 1
#                    else:
#                        r["_is_block_billed_from_source"] = False

            # Update global remaining
#            try:
#                st.session_state["__bb_remaining"] = max(0, allowed_blocks - created_here)
#            except Exception:
#                pass

#            rows.extend(fee_rows_from_src)
#            total_amount = sum(float(row["LINE_ITEM_TOTAL"]) for row in rows)
#            return rows, total_amount
#        except Exception as _e:
            # Fall back to legacy grouping logic on error
#            pass
    # --- End source-driven branch ---

    # Legacy grouping path (consolidate multiple tasks per TK/day)
#    fee_rows = [row for row in rows if not row.get("EXPENSE_CODE")]
    
#    if allowed_blocks > 0 and fee_rows:
#        from collections import defaultdict
#        daily_tk_groups = defaultdict(list)
#        for row in fee_rows:
#            key = (row["TIMEKEEPER_ID"], row["LINE_ITEM_DATE"])
#            daily_tk_groups[key].append(row)
            
#        eligible_groups = []
#        for key, group_rows in daily_tk_groups.items():
#            if len(group_rows) > 1:
#                total_hours = sum(float(r["HOURS"]) for r in group_rows)
#                if total_hours <= max_hours_per_tk_per_day:
#                    eligible_groups.append(group_rows)
        
#        random.shuffle(eligible_groups)
        
#        consolidated_row_ids = set()
#        new_blocks = []
#        blocks_created = 0

#        for group in eligible_groups:
#            if blocks_created >= allowed_blocks:
#                break
            
#            if any(id(row) in consolidated_row_ids for row in group):
#                continue

#            total_hours = sum(float(row["HOURS"]) for row in group)
#            total_amount_block = sum(float(row["LINE_ITEM_TOTAL"]) for row in group)
#            descriptions = [row["DESCRIPTION"] for row in group]
#            block_description = "; ".join(descriptions)
            
#            first_row = group[0]
#            block_row = {
#                "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id,
#                "LINE_ITEM_DATE": first_row["LINE_ITEM_DATE"], "TIMEKEEPER_NAME": first_row["TIMEKEEPER_NAME"],
#                "TIMEKEEPER_CLASSIFICATION": first_row["TIMEKEEPER_CLASSIFICATION"],
#                "TIMEKEEPER_ID": first_row["TIMEKEEPER_ID"], "TASK_CODE": first_row["TASK_CODE"],
#                "ACTIVITY_CODE": first_row["ACTIVITY_CODE"], "EXPENSE_CODE": "",
#                "DESCRIPTION": block_description, "HOURS": round(total_hours, 2), "RATE": first_row["RATE"],
#                "LINE_ITEM_TOTAL": round(total_amount_block, 2)
#            }
#            new_blocks.append(block_row)
#            for row in group:
#                consolidated_row_ids.add(id(row))
#            blocks_created += 1

#        if consolidated_row_ids:
#            rows = [row for row in rows if id(row) not in consolidated_row_ids]
#            rows.extend(new_blocks)

        # Update global remaining
#        try:
#            st.session_state["__bb_remaining"] = max(0, allowed_blocks - blocks_created)
#        except Exception:
#            pass
    
#    total_amount = sum(float(row["LINE_ITEM_TOTAL"]) for row in rows)
#    return rows, total_amount


def _ensure_mandatory_lines(rows: List[Dict], timekeeper_data: List[Dict], invoice_desc: str, client_id: str, law_firm_id: str, billing_start_date: datetime.date, billing_end_date: datetime.date, selected_items: List[str]) -> Tuple[List[Dict], List[str]]:
    """Ensure mandatory line items are included and return a list of any skipped items."""
    delta = billing_end_date - billing_start_date
    num_days = max(1, delta.days + 1)
    skipped_items = []

    for item_name in selected_items:
        random_day_offset = random.randint(0, num_days - 1)
        line_item_date = billing_start_date + datetime.timedelta(days=random_day_offset)
        item = CONFIG['MANDATORY_ITEMS'][item_name]

        # Special handling for items requiring UI details
        if item.get('requires_details'):
            if item_name == 'Airfare E110':
                airline = st.session_state.get('airfare_airline', 'N/A')
                flight_num = st.session_state.get('airfare_flight_number', 'N/A')
                dep_city = st.session_state.get('airfare_departure_city', 'N/A')
                arr_city = st.session_state.get('airfare_arrival_city', 'N/A')
                is_roundtrip = st.session_state.get('airfare_roundtrip', False)
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
            
            # If Unity + Partner: Paralegal Tasks, prefer a Partner from tk_csv
            if _is_partner_paralegal_item(item_name) and st.session_state.get("selected_env", "") == "Unity":
                tk_match = _find_timekeeper_by_classification(_get_timekeepers(), "Partner")
                if tk_match:
                    forced_name = tk_match.get("TIMEKEEPER_NAME", forced_name)
            
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
    table_header_style = ParagraphStyle('TableHeader', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, leading=12, alignment=TA_CENTER, wordWrap='CJK')
    table_data_style = ParagraphStyle('TableData', parent=styles['Normal'], fontName='Helvetica', fontSize=10, leading=12, alignment=TA_LEFT, wordWrap='CJK')
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
            img = Image(io.BytesIO(logo_bytes), width=0.6 * inch, height=0.6 * inch, kind='direct', hAlign='LEFT')
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

    # --- 1998BIv2 Tax Header Block ---
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

    # Table headers
    data = [[
        Paragraph("Date", table_header_style),
        Paragraph("Task<br/>Code", table_header_style),
        Paragraph("Activity<br/>Code", table_header_style),
        Paragraph("Timekeeper", table_header_style),
        Paragraph("Description", table_header_style),
        Paragraph("Hours", table_header_style),
        Paragraph("Rate", table_header_style),
        Paragraph("Total", table_header_style),
    ]]

    # Rows
    for _, row in df.iterrows():
        date = row["LINE_ITEM_DATE"]
        timekeeper = Paragraph(row["TIMEKEEPER_NAME"] if row["TIMEKEEPER_NAME"] else "N/A", table_data_style)
        task_code = row.get("TASK_CODE", "") if not row["EXPENSE_CODE"] else ""
        activity_code = row.get("ACTIVITY_CODE", "") if not row["EXPENSE_CODE"] else ""
        description = Paragraph(row["DESCRIPTION"], table_data_style)
        hours = f"{row['HOURS']:.1f}" if not row["EXPENSE_CODE"] else f"{int(row['HOURS'])}"
        rate = f"${row['RATE']:.2f}" if row["RATE"] else "N/A"
        total = f"${row['LINE_ITEM_TOTAL']:.2f}"
        data.append([date, task_code, activity_code, timekeeper, description, hours, rate, total])

    table = Table(data, colWidths=[0.8 * inch, 0.7 * inch, 0.7 * inch, 1.3 * inch, 1.8 * inch, 0.8 * inch, 0.8 * inch, 0.8 * inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (0, 0), (0, -1), 'CENTER'),
        ('ALIGN', (1, 1), (2, -1), 'CENTER'),
        ('ALIGN', (5, 0), (5, -1), 'CENTER'),
        ('ALIGN', (6, 0), (6, -1), 'RIGHT'),
        ('ALIGN', (7, 0), (7, -1), 'RIGHT'),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    elements.append(table)

    # Totals block (right-aligned)
    if 'EXPENSE_CODE' in df.columns:
        # Create a boolean mask for fees. Fees are where EXPENSE_CODE is empty or NaN.
        is_fee = df['EXPENSE_CODE'].fillna('').eq('')
        fees_total = df.loc[is_fee, 'LINE_ITEM_TOTAL'].sum()
        expenses_total = df.loc[~is_fee, 'LINE_ITEM_TOTAL'].sum()
    else:
        # If no 'EXPENSE_CODE' column, all are fees
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

        # --- 1998BIv2 Tax Totals Block ---
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

with st.expander("Help & FAQs"):
    st.markdown("""
    ### FAQs
    - **What is Spend Agent mode?** Ensures specific mandatory line items (e.g., KBCG, John Doe, Uber E110) are included for testing or compliance. Select items in the Advanced Settings tab.
    - **How to format timekeeper CSV?** Columns: TIMEKEEPER_NAME, TIMEKEEPER_CLASSIFICATION, TIMEKEEPER_ID, RATE  
      Example: "John Doe,Partner,TK001,300.0"
    - **How to format custom tasks CSV?** Columns: TASK_CODE, ACTIVITY_CODE, DESCRIPTION  
      Example: "L100,A101,Legal Research: Analyze legal precedents"
    - **How to use a custom logo?** Upload a valid JPG or PNG image file in the Advanced Settings tab when PDF output is enabled. Only JPEG and PNG formats are supported. Other formats (e.g., GIF, BMP) will be converted to PNG. Maximum file size is 5MB. Ensure the image is not corrupted and displays correctly in an image viewer. If no logo is uploaded, the default logo (assets/nelsonmurdock2.jpg or assets/icon.jpg) or a placeholder will be used.
    - **What if my logo doesn’t appear in the PDF?** Check that the file is a valid JPEG or PNG, not corrupted, and under 5MB. Try re-saving the image using an image editor. If issues persist, enable logging to debug (see Advanced Settings for custom default logo path).
    """)

st.markdown("<h3 style='color: #1E1E1E;'>Output & Delivery Options</h3>", unsafe_allow_html=True)
st.checkbox(
    "Send Invoices via Email",
    value=st.session_state.send_email,
    key="send_email_checkbox_output",
    on_change=update_send_email
)

# Sidebar
st.sidebar.markdown("<h2 style='color: #1E1E1E;'>Quick Links</h2>", unsafe_allow_html=True)
sample_timekeeper = pd.DataFrame({
    "TIMEKEEPER_NAME": ["Tom Delaganis", "Ryan Kinsey"],
    "TIMEKEEPER_CLASSIFICATION": ["Partner", "Associate"],
    "TIMEKEEPER_ID": ["TD001", "RK001"],
    "RATE": [250.0, 200.0]
})
csv_timekeeper = sample_timekeeper.to_csv(index=False).encode('utf-8')
st.sidebar.download_button("Download Sample Timekeeper CSV", csv_timekeeper, "sample_timekeeper.csv", "text/csv")

sample_custom = pd.DataFrame({
    "TASK_CODE": ["L100"],
    "ACTIVITY_CODE": ["A101"],
    "DESCRIPTION": ["Legal Research: Analyze legal precedents"]
})
csv_custom = sample_custom.to_csv(index=False).encode('utf-8')
st.sidebar.download_button("Download Sample Custom Tasks CSV", csv_custom, "sample_custom_tasks.csv", "text/csv")

# Dynamic Tabs
tabs = ["Data Sources", "Invoice Details", "Fees & Expenses", "Output"]
# Insert Tax Fields tab before Output when LEDES 1998BIv2 is selected
if st.session_state.get("ledes_version") in ("1998BI", "1998BIv2"):
    tabs = tabs[:-1] + ["Tax Fields"] + tabs[-1:]
# Email settings will live under the Output tab.
tab_objects = st.tabs(tabs)

with tab_objects[0]:

    st.markdown("<h3 style='color: #1E1E1E;'>Data Sources</h3>", unsafe_allow_html=True)
    uploaded_timekeeper_file = st.file_uploader("Upload Timekeeper CSV (tk_info.csv)", type="csv")
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
                st.dataframe(vc, use_container_width=True)
                partner_count = int(vc.loc[vc["Classification"].str.lower() == "partner", "Count"].sum())
                st.write(f"Partners detected: {partner_count}")
            else:
                st.info("No timekeepers loaded yet.")
        

    use_custom_tasks = st.checkbox("Use Custom Line Item Details?", value=True)
    uploaded_custom_tasks_file = None
    if use_custom_tasks:
        uploaded_custom_tasks_file = st.file_uploader("Upload Custom Line Items CSV (custom_details.csv)", type="csv")

    task_activity_desc = CONFIG['DEFAULT_TASK_ACTIVITY_DESC']
    if use_custom_tasks and uploaded_custom_tasks_file:
        custom_tasks_data = _load_custom_task_activity_data(uploaded_custom_tasks_file)
        if custom_tasks_data is not None:
            li_count = len(custom_tasks_data)
            st.success(f"Loaded {li_count} custom line items.")
            if custom_tasks_data:
                task_activity_desc = custom_tasks_data

with tab_objects[1]:
    st.markdown("<h2 style='color: #1E1E1E;'>Invoice Details</h2>", unsafe_allow_html=True)

    # ===== Billing Profiles =====
    st.markdown("<h3 style='color: #1E1E1E;'>Billing Profiles</h3>", unsafe_allow_html=True)
    env_names = [p[0] for p in BILLING_PROFILES]
    default_env = st.session_state.get("selected_env", "Onit ELM")
    if default_env not in env_names:
        default_env = env_names[0]
    selected_env = st.selectbox("Environment / Profile", env_names, index=env_names.index(default_env), key="selected_env")
    # Pre-populate from profile details when not overriding
    if "allow_override" not in st.session_state:
        st.session_state["allow_override"] = False
    if selected_env in BILLING_PROFILE_DETAILS and not st.session_state["allow_override"]:
        prof = BILLING_PROFILE_DETAILS[selected_env]
        # Default LEDES version for profile
        st.session_state["ledes_version"] = prof.get("ledes_default", st.session_state.get("ledes_version", "1998B"))
        # Default invoice currency
        st.session_state["tax_invoice_currency"] = prof.get("invoice_currency", st.session_state.get("tax_invoice_currency", "USD"))
        # Law firm fields
        lf = prof.get("law_firm", {})
        st.session_state["law_firm_name"] = lf.get("name", st.session_state.get("law_firm_name", ""))
        st.session_state["law_firm_id"] = lf.get("id", st.session_state.get("law_firm_id", ""))
        st.session_state["lf_address1"] = lf.get("address1", st.session_state.get("lf_address1", ""))
        st.session_state["lf_address2"] = lf.get("address2", st.session_state.get("lf_address2", ""))
        st.session_state["lf_city"] = lf.get("city", st.session_state.get("lf_city", ""))
        st.session_state["lf_state"] = lf.get("state", st.session_state.get("lf_state", ""))
        st.session_state["lf_postcode"] = lf.get("postcode", st.session_state.get("lf_postcode", ""))
        st.session_state["lf_country"] = lf.get("country", st.session_state.get("lf_country", ""))
        # Client fields
        cl = prof.get("client", {})
        st.session_state["client_name"] = cl.get("name", st.session_state.get("client_name", ""))
        st.session_state["client_id"] = cl.get("id", st.session_state.get("client_id", ""))
        st.session_state["client_tax_id"] = cl.get("tax_id", st.session_state.get("client_tax_id", ""))
        st.session_state["client_address1"] = cl.get("address1", st.session_state.get("client_address1", ""))
        st.session_state["client_address2"] = cl.get("address2", st.session_state.get("client_address2", ""))
        st.session_state["client_city"] = cl.get("city", st.session_state.get("client_city", ""))
        st.session_state["client_state"] = cl.get("state", st.session_state.get("client_state", ""))
        st.session_state["client_postcode"] = cl.get("postcode", st.session_state.get("client_postcode", ""))
        st.session_state["client_country"] = cl.get("country", st.session_state.get("client_country", ""))
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

    # Ensure base keys reflect identical Client ID and Client Tax ID (safe before widgets instantiate)
    if st.session_state.get("client_tax_id"):
        st.session_state["client_id"] = st.session_state["client_tax_id"]


    # Ensure base keys also reflect identical Client ID and Client Tax ID
    if st.session_state.get("client_tax_id"):
        st.session_state["client_id"] = st.session_state["client_tax_id"]

    allow_override = st.checkbox("Override values for this invoice", value=False, help="When checked, you can type custom values without changing stored profiles.", key="allow_override")

    prof_client_name, prof_client_id, prof_law_firm_name, prof_law_firm_id = get_profile(selected_env)

    # Names
    c1, c2 = st.columns(2)
    with c1:
        client_name = st.text_input("Client Name", value=prof_client_name, disabled=not allow_override, key="client_name")
    with c2:
        law_firm_name = st.text_input("Law Firm Name", value=prof_law_firm_name, disabled=not allow_override, key="law_firm_name")

    # IDs (no format restrictions)
    c3, c4 = st.columns(2)
    with c3:
        client_id = st.text_input("Client ID", value=prof_client_id, disabled=not allow_override, key="client_id")
    with c4:
        law_firm_id = st.text_input("Law Firm ID", value=prof_law_firm_id, disabled=not allow_override, key="law_firm_id")

    # Status footer
    status_html = f"""
    <div style="margin-top:0.25rem;font-size:0.92rem;color:#444">
      Using: <strong>{selected_env}</strong>
      &nbsp;—&nbsp; Client ID: <span style="color:#15803d">{prof_client_id}</span>
      &nbsp;•&nbsp; Law Firm ID: <span style="color:#15803d">{prof_law_firm_id}</span>
    </div>
    """
    st.markdown(status_html, unsafe_allow_html=True)

    st.write("Timekeeper classifications found:", sorted({str(tk.get("TIMEKEEPER_CLASSIFICATION","")) for tk in _get_timekeepers()}))
    
    # Other invoice details
    matter_number_base = st.text_input("Matter Number:", "2025-XXXXXX")
    invoice_number_base = st.text_input("Invoice Number (Base):", "2025MMM-XXXXXX")

    LEDES_OPTIONS = ["1998B", "1998BI", "1998BIv2", "XML 2.1"]
    ledes_version = st.selectbox(
        "LEDES Version:",
        LEDES_OPTIONS,
        key="ledes_version",
        help="XML 2.1 export is not implemented yet; please use 1998B or 1998BIv2."
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
    invoice_desc = st.text_area(
        "Invoice Description (One per period, each on a new line)",
        value="Professional Services Rendered",
        height=150
    )

with tab_objects[2]:
    st.markdown("<h2 style='color: #1E1E1E;'>Fees & Expenses</h2>", unsafe_allow_html=True)
    spend_agent = st.checkbox("Spend Agent", value=False, help="Ensures selected mandatory line items are included; configure below.")

    multiple_attendees_meeting = st.checkbox(
        "Multiple Attendees at Same Meeting",
        value=False,
        help="If checked, create two identical FEE line items for the same meeting: one Partner and one Associate.",
        key="multiple_attendees_meeting",
    )

    # In the "Fees & Expenses" tab, before the sliders
    st.selectbox(
        "Invoice Size Presets",
        options=list(PRESETS.keys()),
        key="invoice_preset",
        on_change=apply_preset,
        help="Select a preset to quickly adjust the number of fee and expense lines below."
    )
    
    if timekeeper_data is None:
        st.error("Please upload a valid timekeeper CSV file to configure fee and expense settings.")
        fees = 0
        expenses = 0
    else:
        max_fees = _calculate_max_fees(timekeeper_data, billing_start_date, billing_end_date, 16)
        st.caption(f"Maximum fee lines allowed: {max_fees} (based on timekeepers and billing period)")
        fees = st.slider(
            "Number of Fee Line Items",
            min_value=0,
            max_value=max_fees,
            key="fee_slider",  # Add key
            value=st.session_state.get("fee_slider", min(20, max_fees)) # Change value
        )
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
            st.slider(
                "Photocopies (E101) per-page rate ($)",
                min_value=0.05, max_value=1.50, value=0.24, step=0.01,
                key="copying_rate_e101",
                help="Per-page rate used for E101 Photocopy expenses."
            )
        st.caption("Number of expense line items to generate")
        expenses = st.slider(
            "Number of Expense Line Items",
            min_value=0,
            max_value=50,
            key="expense_slider",  # Add key
            value=st.session_state.get("expense_slider", 5) # Change value
        )
    max_daily_hours = st.number_input("Max Daily Timekeeper Hours:", min_value=1, max_value=24, value=16, step=1)
    
    if spend_agent:
        st.markdown("<h3 style='color: #1E1E1E;'>Mandatory Items</h3>", unsafe_allow_html=True)
        
        # ---- CORRECTED AND CONSOLIDATED MANDATORY ITEMS LOGIC ----
        
        # Base list of all possible items
        all_items = list(CONFIG["MANDATORY_ITEMS"].keys())

        # Determine the items available for selection based on the environment
        if st.session_state.get("selected_env") == 'SimpleLegal':
            available_items = [
                name for name, details in CONFIG['MANDATORY_ITEMS'].items()
                if details.get('is_expense') and details.get('expense_code') == 'E110'
            ]
            st.info("For the 'SimpleLegal' profile, only E110 mandatory expenses are available.")
        else:
            available_items = all_items

        # Determine the default selected items
        saved_selection = st.session_state.get("mandatory_items_default")
        if saved_selection is not None:
            # Use last selection if saved, but only include items currently available
            default_selection = [item for item in saved_selection if item in available_items]
        else:
            # Otherwise, determine initial defaults based on environment.
            if st.session_state.get("selected_env") == 'SimpleLegal':
                # For SimpleLegal, all available items are selected by default.
                default_selection = list(available_items)
            else:
                # For other environments, default to all items
                default_selection = list(available_items)
        
        # Special rule for 'Unity': ensure 'Partner: Paralegal Task' is pre-selected if available.
        if st.session_state.get("selected_env") == "Unity":
            pp_key = next((k for k in available_items if _is_partner_paralegal_item(k)), None)
            if pp_key and pp_key not in default_selection:
                default_selection.append(pp_key)
        
        # Render the multiselect widget
        selected_items = st.multiselect(
            "Select Mandatory Items to Include",
            options=available_items,
            default=default_selection,
            key="mandatory_items_multiselect",
        )

        # Persist the user's selection so it survives reruns.
        st.session_state["mandatory_items_default"] = list(selected_items)
        
        # Conditional UI for Airfare Details
        if 'Airfare E110' in selected_items:
            st.markdown("<h4 style='color: #1E1E1E;'>Airfare Details</h4>", unsafe_allow_html=True)
            ac1, ac2 = st.columns(2)
            with ac1:
                st.text_input("Airline", key="airfare_airline", value="United Airlines")
                st.text_input("Departure City", key="airfare_departure_city", value="Newark")
                st.checkbox("Roundtrip", key="airfare_roundtrip", value=True)
            with ac2:
                st.text_input("Flight Number", key="airfare_flight_number", value="UA123")
                st.text_input("Arrival City", key="airfare_arrival_city", value="Los Angeles")
                st.number_input("Amount", min_value=0.0, value=450.75, step=0.01, key="airfare_amount", help="This amount will be used for the airfare line item total.")
            st.selectbox(
                "Fare Class",
                options=["First", "Business", "Premium Economy", "Economy/Coach"],
                key="airfare_fare_class",
                help="Select the standard airline fare class (e.g., First, Business, Coach). This will be added to the line item description."
            )
        
        # Conditional UI for Uber Details
        if 'Uber E110' in selected_items:
            st.markdown("<h4 style='color: #1E1E1E;'>Uber E110 Details</h4>", unsafe_allow_html=True)
            st.number_input("Ride Amount", min_value=0.0, value=25.50, step=0.01, key="uber_amount", help="This amount will be used for the Uber ride line item total.")

    else:
        selected_items = []


output_tab_index = tabs.index("Output")
with tab_objects[output_tab_index]:
    st.markdown("<h2 style='color: #1E1E1E;'>Output</h2>", unsafe_allow_html=True)
    include_block_billed = st.checkbox("Include Block Billed Line Items", value=True)
    num_block_billed = 0
    if include_block_billed:
        num_block_billed = st.number_input("Number of Block Billed Items:", min_value=1, max_value=10, value=2, step=1, help="The number of block billed items to create by consolidating multiple tasks from the same timekeeper on the same day.")

    # Initialize/Reset global block-billing budget whenever the UI value is set
    st.session_state["__bb_remaining"] = int(num_block_billed)

    include_pdf = st.checkbox("Include PDF Invoice", value=False)
    
    uploaded_logo = None
    logo_width = None
    logo_height = None
    
    if include_pdf:
        include_logo = st.checkbox("Include Logo in PDF", value=True, help="Uncheck to exclude logo from PDF header, using only law firm text.")
        if include_logo:
            use_custom_logo = st.checkbox("Use Custom Logo", value=False)
            if use_custom_logo:
                default_logo_path = st.text_input("Custom Default Logo Path (Optional):", help="Enter the path to a custom default logo (JPEG/PNG). Leave blank to use assets/nelsonmurdock2.jpg or assets/icon.jpg.")
                uploaded_logo = st.file_uploader(
                    "Upload Custom Logo (JPG/PNG)",
                    type=["jpg", "png", "jpeg"],
                    help="Upload a valid JPG or PNG image file (e.g., logo.jpg or logo.png). Only JPEG and PNG formats are supported."
                )
                logo_width = st.slider("Logo Width (inches):", 0.5, 2.0, 0.6, step=0.1)
                logo_height = st.slider("Logo Height (inches):", 0.5, 2.0, 0.6, step=0.1)
    
    generate_multiple = st.checkbox("Generate Multiple Invoices", help="Create more than one invoice.")
    num_invoices = 1
    multiple_periods = False
    if generate_multiple:
        combine_ledes = st.checkbox("Combine LEDES into single file", help="If checked, all generated LEDES invoices will be combined into a single file with one header.")
        multiple_periods = st.checkbox("Multiple Billing Periods", help="Backfills one invoice per prior month from the given end date, newest to oldest.")
        if multiple_periods:
            num_periods = st.number_input("How Many Billing Periods:", min_value=2, max_value=6, value=2, step=1, help="Number of month-long periods to create (overrides Number of Invoices).")
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
        st.text_input("Client Matter ID (optional)", key="tax_client_matter_id")
        st.selectbox("Invoice Currency", ["USD", "AUD", "CAD", "GBP", "EUR"], index=["USD", "AUD", "CAD", "GBP", "EUR"].index(st.session_state.get("tax_invoice_currency", "USD")), key="tax_invoice_currency")
        st.number_input("Tax Rate", min_value=0.0, max_value=1.0, step=0.01, value=st.session_state.get("tax_rate", 0.19), key="tax_rate")
        st.selectbox("Tax Type", ["VAT","PST","QST","GST"], index=0, key="tax_type", help="Type of tax to apply to line items.")

        with st.expander("Law Firm Details"):
            st.text_input("Law Firm Address 1", key="pf_lf_address1", disabled=not st.session_state.get("allow_override", False))
            st.text_input("Law Firm Address 2", key="pf_lf_address2", disabled=not st.session_state.get("allow_override", False))
            st.text_input("Law Firm City", key="pf_lf_city", disabled=not st.session_state.get("allow_override", False))
            st.text_input("Law Firm State/Region", key="pf_lf_state", disabled=not st.session_state.get("allow_override", False))
            st.text_input("Law Firm Postcode", key="pf_lf_postcode", disabled=not st.session_state.get("allow_override", False))
            st.text_input("Law Firm Country", key="pf_lf_country", disabled=not st.session_state.get("allow_override", False))
            st.text_input("Law Firm Tax ID", key="pf_law_firm_id", disabled=not st.session_state.get("allow_override", False))

        with st.expander("Client Details"):
            st.text_input("Client Address 1", key="pf_client_address1", disabled=not st.session_state.get("allow_override", False))
            st.text_input("Client Address 2", key="pf_client_address2", disabled=not st.session_state.get("allow_override", False))
            st.text_input("Client City", key="pf_client_city", disabled=not st.session_state.get("allow_override", False))
            st.text_input("Client State/Region", key="pf_client_state", disabled=not st.session_state.get("allow_override", False))
            st.text_input("Client Postcode", key="pf_client_postcode", disabled=not st.session_state.get("allow_override", False))
            st.text_input("Client Country", key="pf_client_country", disabled=not st.session_state.get("allow_override", False))
            st.text_input("Client Tax ID", key="pf_client_tax_id", disabled=not st.session_state.get("allow_override", False))





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
st.markdown("---")
generate_button = st.button("Generate Invoice(s)", disabled=not is_valid_input)

# Main App Logic
# Main App Logic
if generate_button:
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
        receipt_files = []
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
                
                # --- FIX: Correctly calculate the number of fees/expenses to generate ---
                # This ensures mandatory items don't add to the total count requested by the user.
                num_mandatory_fees = sum(1 for item in selected_items if not CONFIG['MANDATORY_ITEMS'][item]['is_expense'])
                num_mandatory_expenses = len(selected_items) - num_mandatory_fees
                
                fees_to_generate = max(0, fees - num_mandatory_fees)
                expenses_to_generate = max(0, expenses - num_mandatory_expenses)

                rows, total_amount = _generate_invoice_data(
                    fees_to_generate, expenses_to_generate, timekeeper_data, client_id, law_firm_id,
                    current_invoice_desc, current_start_date, current_end_date,
                    task_activity_desc, CONFIG['MAJOR_TASK_CODES'], max_daily_hours, num_block_billed, faker
                )

                skipped_mandatory_items = []
                if spend_agent:
                    rows, skipped_mandatory_items = _ensure_mandatory_lines(
                        rows, timekeeper_data, current_invoice_desc, client_id, law_firm_id, 
                        current_start_date, current_end_date, selected_items
                    )
                
                df_invoice = pd.DataFrame(rows)
                # Recalculate total amount after adding/skipping mandatory lines
                total_amount = df_invoice["LINE_ITEM_TOTAL"].sum()
                
                if skipped_mandatory_items:
                    skipped_list = ", ".join(f"'{item}'" for item in skipped_mandatory_items)
                    st.warning(
                        f"**Mandatory Items Skipped:** The following items were not added to the invoice because their assigned timekeepers were not found in your CSV file: **{skipped_list}**"
                    )

                current_invoice_number = f"{invoice_number_base}-{i+1}"
                current_matter_number = matter_number_base
                
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
                    for _, row in df_invoice.iterrows():
                        if row.get("EXPENSE_CODE") and row.get("EXPENSE_CODE") != "E101":
                            receipt_filename, receipt_data_buf = _create_receipt_image(row.to_dict(), faker)
                            if receipt_data_buf:
                                receipt_files.append((receipt_filename, receipt_data_buf.getvalue()))

            # Process receipts after loop
            if receipt_files:
                if zip_receipts_enabled:
                    zip_buf = io.BytesIO()
                    with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                        for filename, data in receipt_files:
                            zip_file.writestr(filename, data)
                    zip_buf.seek(0)
                    attachments_list.append(("receipts.zip", zip_buf.getvalue()))
                else:
                    attachments_list.extend(receipt_files)

            # Final download/email logic
            def get_mime_type(filename):
                if filename.endswith(".txt"): return "text/plain"
                if filename.endswith(".pdf"): return "application/pdf"
                if filename.endswith(".png"): return "image/png"
                if filename.endswith(".zip"): return "application/zip"
                return "application/octet-stream"

            if st.session_state.send_email:
                subject, body = _customize_email_body(current_matter_number, f"{invoice_number_base}-Combined" if combine_ledes else f"{current_invoice_number}")
                
                if combine_ledes:
                    attachments_to_send = [("LEDES_Combined.txt", combined_ledes_content.encode('utf-8'))]
                    attachments_to_send.extend(attachments_list) # attachments_list already has PDFs and receipts (zipped or not)
                    if not _send_email_with_attachment(recipient_email, subject, body, attachments_to_send):
                        st.subheader("Invoice(s) Failed to Email - Download below:")
                        for filename, data in attachments_to_send:
                            st.download_button(label=f"Download {filename}", data=data, file_name=filename, mime=get_mime_type(filename), key=f"download_failed_{filename}")
                else:
                    if not _send_email_with_attachment(recipient_email, subject, body, attachments_list):
                        st.subheader("Invoice(s) Failed to Email - Download below:")
                        for filename, data in attachments_list:
                            st.download_button(label=f"Download {filename}", data=data, file_name=filename, mime=get_mime_type(filename), key=f"download_failed_{filename}")
            else:
                if combine_ledes:
                    st.subheader("Generated Combined LEDES Invoice")
                    st.download_button(
                        label="Download Combined LEDES File",
                        data=combined_ledes_content.encode('utf-8'),
                        file_name="LEDES_Combined.txt",
                        mime="text/plain",
                        key="download_combined_ledes"
                    )
                    other_attachments = attachments_list
                    if other_attachments:
                        zip_buf = io.BytesIO()
                        with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                            for filename, data in other_attachments:
                                zip_file.writestr(filename, data)
                        zip_buf.seek(0)
                        st.download_button(
                            label="Download All PDFs & Receipts as ZIP",
                            data=zip_buf.getvalue(),
                            file_name="invoices_and_receipts.zip",
                            mime="application/zip",
                            key="download_pdf_zip"
                        )
                elif num_invoices > 1 or (generate_receipts and zip_receipts_enabled):
                    zip_buf = io.BytesIO()
                    with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                        for filename, data in attachments_list:
                            zip_file.writestr(filename, data)
                    zip_buf.seek(0)
                    st.download_button(
                        label="Download All Files as ZIP",
                        data=zip_buf.getvalue(),
                        file_name="invoices.zip",
                        mime="application/zip",
                        key="download_zip"
                    )
                else:
                    st.subheader("Generated Invoice(s)")
                    for filename, data in attachments_list:
                        st.download_button(
                            label=f"Download {filename}",
                            data=data,
                            file_name=filename,
                            mime=get_mime_type(filename),
                            key=f"download_{filename}"
                        )
            status.update(label="Invoice generation complete!", state="complete")




# === Override: source-only fee generation using Blockbilling column ===
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
    faker_instance: Faker
) -> Tuple[List[Dict], float]:
    """Generate invoice data using ONLY the uploaded CSV:
    - Non-block fees come from rows with Blockbilling=N
    - Block-billed fees come from rows with Blockbilling=Y (no synthetic building)
    - Expenses are generated as before
    Mandatory items are appended by the caller after this returns.
    """
    rows: List[Dict] = []

    # Get uploaded source
    try:
        df_src = st.session_state.get("custom_fee_df_full") or st.session_state.get("custom_fee_df")
    except Exception:
        df_src = None

    # Helper to build a fee row
    def _mk_fee_row(desc: str, tk: Dict, date_str: str, task_code: str, act_code: str, hours: float, block: bool=False) -> Dict:
        rate = float(tk.get("RATE", 0.0))
        row = {
            "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id,
            "LINE_ITEM_DATE": date_str, "TIMEKEEPER_NAME": tk.get("TIMEKEEPER_NAME",""),
            "TIMEKEEPER_CLASSIFICATION": tk.get("TIMEKEEPER_CLASSIFICATION",""), "TIMEKEEPER_ID": tk.get("TIMEKEEPER_ID",""),
            "TASK_CODE": task_code, "ACTIVITY_CODE": act_code, "EXPENSE_CODE": "",
            "DESCRIPTION": ("[BLOCK] " + desc) if block else desc,
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
    import random, datetime as _dt
    nb_picks = []
    if fee_count > 0:
        nb_picks = _select_items_from_source(df_src, want_block=False, k=fee_count) if df_src is not None else []
    for item in nb_picks:
        day = billing_start_date + _dt.timedelta(days=random.randint(0, delta_days) if delta_days else 0)
        date_str = day.strftime("%Y-%m-%d")
        tk = _pick_timekeeper_by_class(timekeeper_data, item.get("TK_CLASSIFICATION"))
        if not tk: 
            continue
        hours_cap = float(max_hours_per_tk_per_day) if max_hours_per_tk_per_day else 6.0
        hours = round(random.uniform(0.5, max(0.6, min(3.5, hours_cap))), 1)
        rows.append(_mk_fee_row(item["DESC"], tk, date_str, item["TASK_CODE"], item["ACTIVITY_CODE"], hours, block=False))

    # --- Block-billed fees (Y) ---
    include_blocks = True
    try:
        include_blocks = bool(st.session_state.get("include_block_billed", True))
    except Exception:
        pass
    bb_picks = []
    if include_blocks and num_block_billed > 0:
        bb_picks = _select_items_from_source(df_src, want_block=True, k=num_block_billed) if df_src is not None else []
    for item in bb_picks[:num_block_billed]:
        day = billing_start_date + _dt.timedelta(days=random.randint(0, delta_days) if delta_days else 0)
        date_str = day.strftime("%Y-%m-%d")
        tk = _pick_timekeeper_by_class(timekeeper_data, item.get("TK_CLASSIFICATION"))
        if not tk: 
            continue
        hours_cap = float(max_hours_per_tk_per_day) if max_hours_per_tk_per_day else 6.0
        hours = round(random.uniform(1.0, max(1.0, min(6.0, hours_cap))), 1)
        rows.append(_mk_fee_row(item["DESC"], tk, date_str, item["TASK_CODE"], item["ACTIVITY_CODE"], hours, block=True))

        # --- FIX: Add multiple attendee rows BEFORE block billing ---
        # This ensures they can be included in the block billing consolidation.
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


