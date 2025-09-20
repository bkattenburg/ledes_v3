import streamlit as st

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
BILLING_PROFILES = [("VAT", "Onit LLC - Belgium", "", "Nelson and Murdock - Belgium", "3233384400"),
    ("Onit ELM",    "A Onit Inc.",   "02-4388252", "Nelson & Murdock", "02-1234567"),
    ("SimpleLegal", "Penguin LLC",   "C004",       "JDL",               "JDL001"),
    ("Unity",       "Unity Demo",    "uniti-demo", "Gold USD",          "Gold USD"),
]

BILLING_PROFILE_DETAILS = {
    "VAT": {
        "ledes_default": "1998BI",
        "invoice_currency": "EUR",
        "law_firm": {
            "name": "Nelson and Murdock - Belgium", "id": "3233384400", "address1": "Hanzestedenplaats 1",
            "address2": "", "city": "Antwerpen", "state": "", "postcode": "2000", "country": "Belgium"
        },
        "client": {
            "name": "Onit LLC - Belgium", "id": "00-4100871", "tax_id": "00-4100871", "address1": "P.O. Box 636",
            "address2": "4368 Feugiat. Avenue", "city": "Grand-Hallet", "state": "Luxemburg", "postcode": "3230", "country": "Belgium"
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
        "Photocopies": "E101", "Outside printing": "E102", "Word processing": "E103", "Facsimile": "E104",
        "Telephone": "E105", "Online research": "E106", "Delivery services/messengers": "E107", "Postage": "E108",
        "Local travel": "E109", "Out-of-town travel": "E110", "Meals": "E111", "Court fees": "E112",
        "Subpoena fees": "E113", "Witness fees": "E114", "Deposition transcripts": "E115",
        "Trial transcripts": "E116", "Trial exhibits": "E117", "Litigation support vendors": "E118",
        "Experts": "E119", "Private investigators": "E120", "Arbitrators/mediators": "E121",
        "Local counsel": "E122", "Other professionals": "E123", "Other": "E124",
    },
    'MANDATORY_ITEMS': {
        'KBCG': {
            'desc': ("Commenced data entry into the KBCG e-licensing portal for Piers Walter Vermont "
                     "form 1005 application; Drafted deficiency notice to send to client re: same; "
                     "Scheduled follow-up call with client to review application status and address outstanding deficiencies."),
            'tk_name': "Tom Delaganis", 'task': "L140", 'activity': "A107", 'is_expense': False
        },
        'John Doe': {
            'desc': ("Reviewed and summarized deposition transcript of John Doe; prepared exhibit index; "
                     "updated case chronology spreadsheet for attorney review"),
            'tk_name': "Ryan Kinsey", 'task': "L120", 'activity': "A102", 'is_expense': False
        },
        'Uber E110': {
            'desc': "Uber ride to client's office", 'expense_code': "E110", 'is_expense': True, 'requires_details': True
        },
        'Partner: Paralegal Tasks': {
            'desc': "Prepared trial binder including witness lists and exhibit summaries.",
            'tk_name': "Ryan Kinsey", 'task': "L140", 'activity': "A103", 'is_expense': False
        },
        'Airfare E110': {
            'desc': "Airfare", 'expense_code': "E110", 'is_expense': True, 'requires_details': True
        },
    }
}
EXPENSE_DESCRIPTIONS = list(CONFIG['EXPENSE_CODES'].keys())

# --- Helper Functions ---
def _find_timekeeper_by_name(timekeepers: List[Dict], name: str) -> Optional[Dict]:
    if not timekeepers: return None
    for tk in timekeepers:
        if str(tk.get("TIMEKEEPER_NAME", "")).strip().lower() == str(name).strip().lower():
            return tk
    return None

def _find_timekeeper_by_classification(timekeepers, classification: str):
    if not timekeepers: return None
    target = str(classification).strip().lower()
    def norm(s: str) -> str: return re.sub(r"\s+", " ", str(s).strip().lower())
    candidates = [tk for tk in timekeepers if target in norm(tk.get("TIMEKEEPER_CLASSIFICATION", ""))]
    if not candidates: return None
    candidates.sort(key=lambda tk: str(tk.get("TIMEKEEPER_NAME", "")).lower())
    return candidates[0]

def _get_timekeepers():
    return st.session_state.get("timekeeper_data") or []

def _is_partner_paralegal_item(name: str) -> bool:
    return str(name).strip().lower().startswith("partner: paralegal")

def _force_timekeeper_on_row(row: Dict, forced_name: str, timekeepers: List[Dict]) -> Optional[Dict]:
    if row.get("EXPENSE_CODE"): return row
    row["TIMEKEEPER_NAME"] = forced_name
    tk = _find_timekeeper_by_name(timekeepers, forced_name)
    if tk:
        row["TIMEKEEPER_ID"] = tk.get("TIMEKEEPER_ID", "")
        row["TIMEKEEPER_CLASSIFICATION"] = tk.get("TIMEKEEPER_CLASSIFICATION", "")
        try:
            row["RATE"] = float(tk.get("RATE", 0.0))
            hours = float(row.get("HOURS", 0))
            row["LINE_ITEM_TOTAL"] = round(hours * row["RATE"], 2)
        except Exception as e:
            logging.error(f"Error setting timekeeper rate: {e}")
        return row
    return None

def _load_timekeepers(uploaded_file: Optional[Any]) -> Optional[List[Dict]]:
    if uploaded_file is None: return None
    try:
        df = pd.read_csv(uploaded_file)
        required_cols = ["TIMEKEEPER_NAME", "TIMEKEEPER_CLASSIFICATION", "TIMEKEEPER_ID", "RATE"]
        if not all(col in df.columns for col in required_cols):
            st.error(f"Timekeeper CSV must contain: {', '.join(required_cols)}")
            return None
        return df.to_dict(orient='records')
    except Exception as e:
        st.error(f"Error loading timekeeper file: {e}")
        return None

def _load_custom_line_items(uploaded_file: Optional[Any]) -> Optional[List[Dict]]:
    """Loads custom line items from a CSV, expecting a 'Blockbilling' column."""
    if uploaded_file is None: return None
    try:
        df = pd.read_csv(uploaded_file)
        required_cols = ["TASK_CODE", "ACTIVITY_CODE", "DESCRIPTION", "Blockbilling"]
        if not all(col in df.columns for col in required_cols):
            st.error(f"Custom Line Items CSV must contain the columns: {', '.join(required_cols)}")
            return None
        if df.empty:
            st.warning("Custom Line Items CSV file is empty.")
            return []
        # Standardize the flag for easier checking
        df['Blockbilling'] = df['Blockbilling'].str.strip().str.upper()
        return df.to_dict(orient='records')
    except Exception as e:
        st.error(f"Error loading custom line items file: {e}")
        return None

def _generate_fees(
    fee_count: int,
    num_block_billed: int,
    custom_line_items: List[Dict],
    timekeeper_data: List[Dict],
    billing_start_date: datetime.date,
    billing_end_date: datetime.date,
    client_id: str,
    law_firm_id: str,
    invoice_desc: str
) -> List[Dict]:
    """Generates fee lines by SELECTING pre-defined line items from the provided CSV."""
    rows = []
    if not custom_line_items or not timekeeper_data:
        return rows

    # 1. Separate the loaded lines into two pools based on the 'Blockbilling' flag
    single_lines = [item for item in custom_line_items if item.get('Blockbilling') == 'N']
    block_lines = [item for item in custom_line_items if item.get('Blockbilling') == 'Y']

    # 2. Determine how many of each type to select
    num_single_to_select = max(0, fee_count - num_block_billed)
    
    # 3. Randomly select the lines from each pool
    # Use min() to prevent errors if not enough lines are available in the CSV
    selected_blocks = random.sample(block_lines, min(num_block_billed, len(block_lines)))
    selected_singles = random.sample(single_lines, min(num_single_to_select, len(single_lines)))
    
    all_selected_items = selected_blocks + selected_singles
    random.shuffle(all_selected_items)

    delta = billing_end_date - billing_start_date
    num_days = max(1, delta.days + 1)

    for item_template in all_selected_items:
        tk_row = random.choice(timekeeper_data)
        random_day_offset = random.randint(0, num_days - 1)
        line_item_date = billing_start_date + datetime.timedelta(days=random_day_offset)
        
        # For block-billed items from the file, assign a larger, more realistic hour range
        is_block = item_template.get('Blockbilling') == 'Y'
        hours_to_bill = round(random.uniform(1.5, 8.0) if is_block else random.uniform(0.2, 2.5), 1)
        
        line_item_total = round(hours_to_bill * float(tk_row["RATE"]), 2)

        rows.append({
            "INVOICE_DESCRIPTION": invoice_desc,
            "CLIENT_ID": client_id,
            "LAW_FIRM_ID": law_firm_id,
            "LINE_ITEM_DATE": line_item_date.strftime("%Y-%m-%d"),
            "TIMEKEEPER_NAME": tk_row["TIMEKEEPER_NAME"],
            "TIMEKEEPER_CLASSIFICATION": tk_row["TIMEKEEPER_CLASSIFICATION"],
            "TIMEKEEPER_ID": tk_row["TIMEKEEPER_ID"],
            "TASK_CODE": item_template.get("TASK_CODE", ""),
            "ACTIVITY_CODE": item_template.get("ACTIVITY_CODE", ""),
            "DESCRIPTION": item_template.get("DESCRIPTION", ""),
            "HOURS": hours_to_bill,
            "RATE": float(tk_row["RATE"]),
            "LINE_ITEM_TOTAL": line_item_total,
            "EXPENSE_CODE": ""
        })
        
    return rows

def _generate_expenses(expense_count: int, billing_start_date: datetime.date, billing_end_date: datetime.date, client_id: str, law_firm_id: str, invoice_desc: str) -> List[Dict]:
    """Generates random expense line items."""
    rows: List[Dict] = []
    if expense_count == 0: return rows
    delta = billing_end_date - billing_start_date
    num_days = max(1, delta.days + 1)
    
    for _ in range(expense_count):
        description = random.choice(EXPENSE_DESCRIPTIONS)
        expense_code = CONFIG['EXPENSE_CODES'][description]
        random_day_offset = random.randint(0, num_days - 1)
        line_item_date = billing_start_date + datetime.timedelta(days=random_day_offset)
        
        hours = random.randint(1, 5)
        rate = round(random.uniform(10.0, 150.0), 2)
        line_item_total = round(hours * rate, 2)
        
        rows.append({ "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id, "LINE_ITEM_DATE": line_item_date.strftime("%Y-%m-%d"), "TIMEKEEPER_NAME": "", "TIMEKEEPER_CLASSIFICATION": "", "TIMEKEEPER_ID": "", "TASK_CODE": "", "ACTIVITY_CODE": "", "EXPENSE_CODE": expense_code, "DESCRIPTION": description, "HOURS": hours, "RATE": rate, "LINE_ITEM_TOTAL": line_item_total })
    return rows

def _append_two_attendee_meeting_rows(rows, timekeeper_data, billing_start_date, faker_instance, client_id, law_firm_id, invoice_desc):
    """Appends two fee rows for a single meeting with a Partner and an Associate."""
    def _norm_role(s):
        s = str(s or "").strip().lower()
        if s.startswith("partner"): return "partner"
        if s.startswith("associate"): return "associate"
        return s

    partners = [tk for tk in (timekeeper_data or []) if _norm_role(tk.get("TIMEKEEPER_CLASSIFICATION")) == "partner"]
    associates = [tk for tk in (timekeeper_data or []) if _norm_role(tk.get("TIMEKEEPER_CLASSIFICATION")) == "associate"]
    if not partners or not associates: return rows

    tk_p, tk_a = random.choice(partners), random.choice(associates)
    random_name = faker_instance.name()
    desc_final = f"Participate in litigation strategy meeting with client team to analyze opposing party's recent discovery responses and prepare for the deposition of witness {random_name}."
    dur = round(random.uniform(0.5, 2.5), 1)

    def _mk_base_fee():
        return { "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id, "LINE_ITEM_DATE": str(billing_start_date), "DESCRIPTION": desc_final, "HOURS": dur, "TASK_CODE": "L430", "ACTIVITY_CODE": "A112", "EXPENSE_CODE": "" }

    row_p = _force_timekeeper_on_row(_mk_base_fee(), tk_p.get("TIMEKEEPER_NAME", ""), timekeeper_data)
    row_a = _force_timekeeper_on_row(_mk_base_fee(), tk_a.get("TIMEKEEPER_NAME", ""), timekeeper_data)
    
    if row_p and row_a:
        rows.extend([row_p, row_a])
    return rows

def _generate_invoice_data(
    fees: int,
    expenses: int,
    num_block_billed: int,
    custom_line_items: List[Dict],
    timekeeper_data: List[Dict],
    client_id: str,
    law_firm_id: str,
    invoice_desc: str,
    billing_start_date: datetime.date,
    billing_end_date: datetime.date,
    faker_instance: Faker
) -> Tuple[List[Dict], float]:
    """Assembles the final list of invoice rows based on user selections."""
    rows = []
    
    rows.extend(_generate_fees(fees, num_block_billed, custom_line_items, timekeeper_data, billing_start_date, billing_end_date, client_id, law_firm_id, invoice_desc))
    rows.extend(_generate_expenses(expenses, billing_start_date, billing_end_date, client_id, law_firm_id, invoice_desc))

    if st.session_state.get("multiple_attendees_meeting", False):
        rows = _append_two_attendee_meeting_rows(rows, timekeeper_data, billing_start_date, faker_instance, client_id, law_firm_id, invoice_desc)
    
    total_amount = sum(float(row.get("LINE_ITEM_TOTAL", 0)) for row in rows)
    return rows, total_amount

def _ensure_mandatory_lines(rows: List[Dict], timekeeper_data: List[Dict], invoice_desc: str, client_id: str, law_firm_id: str, billing_start_date: datetime.date, billing_end_date: datetime.date, selected_items: List[str]) -> Tuple[List[Dict], List[str]]:
    delta = billing_end_date - billing_start_date
    num_days = max(1, delta.days + 1)
    skipped_items = []

    for item_name in selected_items:
        random_day_offset = random.randint(0, num_days - 1)
        line_item_date = billing_start_date + datetime.timedelta(days=random_day_offset)
        item = CONFIG['MANDATORY_ITEMS'][item_name]

        if item.get('requires_details'):
            if item_name == 'Airfare E110':
                amount = float(st.session_state.get('airfare_amount', 0.0))
                description = f"Airfare ({st.session_state.get('airfare_fare_class', 'N/A')}): {st.session_state.get('airfare_airline', 'N/A')} {st.session_state.get('airfare_flight_number', 'N/A')}"
                row = { "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id, "LINE_ITEM_DATE": line_item_date.strftime("%Y-%m-%d"), "TIMEKEEPER_NAME": "", "TIMEKEEPER_CLASSIFICATION": "", "TIMEKEEPER_ID": "", "TASK_CODE": "", "ACTIVITY_CODE": "", "EXPENSE_CODE": "E110", "DESCRIPTION": description, "HOURS": 1, "RATE": amount, "LINE_ITEM_TOTAL": amount }
                rows.append(row)
            elif item_name == 'Uber E110':
                amount = float(st.session_state.get('uber_amount', 0.0))
                row = { "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id, "LINE_ITEM_DATE": line_item_date.strftime("%Y-%m-%d"), "TIMEKEEPER_NAME": "", "TIMEKEEPER_CLASSIFICATION": "", "TIMEKEEPER_ID": "", "TASK_CODE": "", "ACTIVITY_CODE": "", "EXPENSE_CODE": "E110", "DESCRIPTION": item['desc'], "HOURS": 1, "RATE": amount, "LINE_ITEM_TOTAL": amount }
                rows.append(row)
        elif item['is_expense']:
            rate = round(random.uniform(5.0, 100.0), 2)
            hours = random.randint(1, 10)
            row = { "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id, "LINE_ITEM_DATE": line_item_date.strftime("%Y-%m-%d"), "TIMEKEEPER_NAME": "", "TIMEKEEPER_CLASSIFICATION": "", "TIMEKEEPER_ID": "", "TASK_CODE": "", "ACTIVITY_CODE": "", "EXPENSE_CODE": item['expense_code'], "DESCRIPTION": item['desc'], "HOURS": hours, "RATE": rate, "LINE_ITEM_TOTAL": round(hours * rate, 2) }
            rows.append(row)
        else: 
            forced_name = item['tk_name']
            if _is_partner_paralegal_item(item_name) and st.session_state.get("selected_env", "") == "Unity":
                tk_match = _find_timekeeper_by_classification(_get_timekeepers(), "Partner")
                if tk_match:
                    forced_name = tk_match.get("TIMEKEEPER_NAME", forced_name)
            
            row_template = { "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id, "LINE_ITEM_DATE": line_item_date.strftime("%Y-%m-%d"), "TIMEKEEPER_NAME": forced_name, "TIMEKEEPER_CLASSIFICATION": "", "TIMEKEEPER_ID": "", "TASK_CODE": item['task'], "ACTIVITY_CODE": item['activity'], "EXPENSE_CODE": "", "DESCRIPTION": item['desc'], "HOURS": round(random.uniform(0.5, 8.0), 1), "RATE": 0.0 }
            processed_row = _force_timekeeper_on_row(row_template, forced_name, _get_timekeepers())
            if processed_row:
                rows.append(processed_row)
            else:
                skipped_items.append(item_name)
            
    return rows, skipped_items

def _create_ledes_1998b_content(rows: List[Dict], inv_total: float, bill_start: datetime.date, bill_end: datetime.date, invoice_number: str, matter_number: str, is_first_invoice: bool = True) -> str:
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
        try:
            date_obj = datetime.datetime.strptime(row["LINE_ITEM_DATE"], "%Y-%m-%d").date()
            is_expense = bool(row.get("EXPENSE_CODE", ""))
            adj_type = "E" if is_expense else "F"
            hours = float(row["HOURS"])
            rate = float(row["RATE"])
            line_total = float(row["LINE_ITEM_TOTAL"])
            
            line = [
                bill_end.strftime("%Y%m%d"), invoice_number, str(row.get("CLIENT_ID", "")), matter_number,
                f"{inv_total:.2f}", bill_start.strftime("%Y%m%d"), bill_end.strftime("%Y%m%d"),
                str(row.get("INVOICE_DESCRIPTION", "")), str(i), adj_type,
                f"{hours:.1f}" if adj_type == "F" else f"{int(hours)}", "0.00", f"{line_total:.2f}",
                date_obj.strftime("%Y%m%d"),
                "" if is_expense else row.get("TASK_CODE", ""),
                row.get("EXPENSE_CODE", "") if is_expense else "",
                "" if is_expense else row.get("ACTIVITY_CODE", ""),
                "" if is_expense else row.get("TIMEKEEPER_ID", ""),
                str(row.get("DESCRIPTION", "")).replace("|", " - "),
                str(row.get("LAW_FIRM_ID", "")), f"{rate:.2f}",
                "" if is_expense else row.get("TIMEKEEPER_NAME", ""),
                "" if is_expense else row.get("TIMEKEEPER_CLASSIFICATION", ""),
                matter_number
            ]
            lines.append("|".join(map(str, line)) + "[]")
        except Exception as e:
            logging.error(f"Error creating LEDES line for row {row}: {e}")
    return "\n".join(lines)

def _create_pdf_invoice(df: pd.DataFrame, total_amount: float, invoice_number: str, invoice_date: datetime.date, billing_start_date: datetime.date, billing_end_date: datetime.date, client_id: str, law_firm_id: str, client_name: str, law_firm_name: str) -> io.BytesIO:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []
    styles = getSampleStyleSheet()
    
    header_data = [
        [Paragraph(f"<b>{law_firm_name}</b><br/>{law_firm_id}", styles['Normal']), Paragraph(f"<b>{client_name}</b><br/>{client_id}", styles['Normal'])]
    ]
    elements.append(Table(header_data, colWidths=[3.5 * inch, 3.5 * inch]))
    elements.append(Spacer(1, 0.25 * inch))
    
    meta_data = [
        [Paragraph(f"<b>Invoice #:</b> {invoice_number}"), Paragraph(f"<b>Invoice Date:</b> {invoice_date.strftime('%Y-%m-%d')}")],
        [Paragraph(f"<b>Billing Period:</b> {billing_start_date.strftime('%Y-%m-%d')} to {billing_end_date.strftime('%Y-%m-%d')}")],
    ]
    elements.append(Table(meta_data, colWidths=[3.5 * inch, 3.5 * inch]))
    elements.append(Spacer(1, 0.25 * inch))

    table_data = [["Date", "Timekeeper", "Description", "Hours", "Rate", "Total"]]
    for _, row in df.iterrows():
        table_data.append([
            row["LINE_ITEM_DATE"],
            row.get("TIMEKEEPER_NAME") or "N/A",
            Paragraph(row.get("DESCRIPTION", ""), styles['Normal']),
            f"{float(row.get('HOURS', 0)):.1f}" if not row.get("EXPENSE_CODE") else str(int(row.get('HOURS',0))),
            f"${float(row.get('RATE', 0)):,.2f}",
            f"${float(row.get('LINE_ITEM_TOTAL', 0)):,.2f}"
        ])
    
    table = Table(table_data, colWidths=[0.7*inch, 1*inch, 3.3*inch, 0.5*inch, 0.7*inch, 0.8*inch])
    table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.grey), ('GRID', (0, 0), (-1, -1), 1, colors.black), ('VALIGN', (0,0), (-1,-1), 'TOP')]))
    elements.append(table)
    elements.append(Spacer(1, 0.25 * inch))
    
    total_para = Paragraph(f"<b>Total Amount: ${total_amount:,.2f}</b>", styles['h3'])
    total_para.hAlign = 'RIGHT'
    elements.append(total_para)
    
    doc.build(elements)
    buffer.seek(0)
    return buffer

# --- Streamlit App UI ---

st.set_page_config(layout="wide")
st.markdown("<h1 style='color: #1E1E1E;'>LEDES Invoice Generator</h1>", unsafe_allow_html=True)

with st.expander("Help & FAQs"):
    st.markdown("""
    ### How This App Works
    - **Custom Line Item CSV is Key:** The generator relies on your custom line item CSV file.
    - **Add a 'Blockbilling' Column:** You must add a column named `Blockbilling` to this CSV. 
      - Mark rows with `Y` if they are pre-formatted block-billed tasks.
      - Mark rows with `N` if they are single, individual tasks.
    - **The Sliders are Selectors:** The sliders on the "Fees & Expenses" tab control how many lines are **randomly selected** from the `N` (single) and `Y` (block-billed) pools in your CSV.
    """)

st.sidebar.markdown("<h2 style='color: #1E1E1E;'>Quick Links</h2>", unsafe_allow_html=True)
sample_timekeeper = pd.DataFrame({"TIMEKEEPER_NAME": ["Tom Delaganis", "Ryan Kinsey"],"TIMEKEEPER_CLASSIFICATION": ["Partner", "Associate"],"TIMEKEEPER_ID": ["TD001", "RK001"],"RATE": [250.0, 200.0]})
st.sidebar.download_button("Download Sample Timekeeper CSV", sample_timekeeper.to_csv(index=False).encode('utf-8'), "sample_timekeeper.csv", "text/csv")

sample_custom = pd.DataFrame({"TASK_CODE": ["L100", "L190"], "ACTIVITY_CODE": ["A101", "A104"], "DESCRIPTION": ["Single task description.", "Block-billed task; with a second part."], "Blockbilling": ["N", "Y"]})
st.sidebar.download_button("Download Sample Custom Items CSV", sample_custom.to_csv(index=False).encode('utf-8'), "sample_custom_items.csv", "text/csv")

# --- UI Tabs ---
tabs = ["Data Sources", "Invoice Details", "Fees & Expenses", "Output"]
tab_objects = st.tabs(tabs)

with tab_objects[0]:
    st.header("Data Sources")
    uploaded_timekeeper_file = st.file_uploader("Upload Timekeeper CSV", type="csv")
    if uploaded_timekeeper_file:
        timekeeper_data = _load_timekeepers(uploaded_timekeeper_file)
        if timekeeper_data:
            st.session_state["timekeeper_data"] = timekeeper_data
            st.success(f"Loaded {len(timekeeper_data)} timekeepers.")
    
    uploaded_custom_items_file = st.file_uploader("Upload Custom Line Items CSV (with Blockbilling column)", type="csv")
    if uploaded_custom_items_file:
        custom_line_items = _load_custom_line_items(uploaded_custom_items_file)
        if custom_line_items is not None:
            st.session_state["custom_line_items"] = custom_line_items
            st.success(f"Loaded {len(custom_line_items)} custom line items.")

with tab_objects[1]:
    st.header("Invoice Details")
    prof_client_name, prof_client_id, prof_law_firm_name, prof_law_firm_id = get_profile(st.selectbox("Environment / Profile", [p[0] for p in BILLING_PROFILES]))
    
    col1, col2 = st.columns(2)
    with col1:
        client_name = st.text_input("Client Name", value=prof_client_name)
        client_id = st.text_input("Client ID", value=prof_client_id)
        matter_number_base = st.text_input("Matter Number:", "MATTER-001")
        billing_start_date = st.date_input("Billing Start Date", value=(datetime.date.today().replace(day=1) - datetime.timedelta(days=1)).replace(day=1))
    with col2:
        law_firm_name = st.text_input("Law Firm Name", value=prof_law_firm_name)
        law_firm_id = st.text_input("Law Firm ID", value=prof_law_firm_id)
        invoice_number_base = st.text_input("Invoice Number (Base):", f"INV-{datetime.date.today().year}-001")
        billing_end_date = st.date_input("Billing End Date", value=datetime.date.today().replace(day=1) - datetime.timedelta(days=1))
        
    invoice_desc = st.text_area("Invoice Description", value="Professional Services Rendered")
    ledes_version = st.selectbox("LEDES Version:", ["1998B", "1998BI", "1998BIv2"], key="ledes_version")

with tab_objects[2]:
    st.header("Fees & Expenses")
    st.selectbox("Invoice Size Presets", options=list(PRESETS.keys()), key="invoice_preset", on_change=apply_preset)

    if not st.session_state.get("timekeeper_data") or not st.session_state.get("custom_line_items"):
        st.error("Please upload Timekeeper and Custom Line Item CSV files on the 'Data Sources' tab.")
    else:
        fees = st.slider("Total Number of Fee Line Items", min_value=0, max_value=200, key="fee_slider", value=st.session_state.get("fee_slider", 20))
        
        num_block_billed = st.slider(
            "Number of Block Billed Items (to select from file)", 
            min_value=0, 
            max_value=fees, 
            value=min(2, fees), 
            help="This many items will be randomly selected from lines marked 'Y' in your CSV."
        )

        expenses = st.slider("Number of Expense Line Items", min_value=0, max_value=50, key="expense_slider", value=st.session_state.get("expense_slider", 5))
        st.checkbox("Include Two-Attendee Meeting", key="multiple_attendees_meeting")
        
        spend_agent = st.checkbox("Spend Agent Mode (add mandatory items)")
        if spend_agent:
            selected_items = st.multiselect("Select Mandatory Items", options=list(CONFIG["MANDATORY_ITEMS"].keys()))
            if 'Airfare E110' in selected_items:
                st.number_input("Airfare Amount", key="airfare_amount", value=450.75)
            if 'Uber E110' in selected_items:
                st.number_input("Uber Amount", key="uber_amount", value=25.50)

with tab_objects[3]:
    st.header("Output")
    include_pdf = st.checkbox("Include PDF Invoice", value=True)
    generate_multiple = st.checkbox("Generate Multiple Invoices")
    num_invoices = 1
    if generate_multiple:
        num_invoices = st.number_input("Number of Invoices", min_value=1, value=2)

# --- Generate Button Logic ---
if st.button("Generate Invoice(s)"):
    if not st.session_state.get("timekeeper_data") or not st.session_state.get("custom_line_items"):
        st.error("Missing required CSV files from 'Data Sources' tab.")
    else:
        faker = Faker()
        with st.status("Generating invoice(s)...") as status:
            for i in range(num_invoices):
                status.update(label=f"Generating Invoice {i+1}/{num_invoices}...")
                invoice_number = f"{invoice_number_base}-{i+1}"
                
                rows, total_amount = _generate_invoice_data(
                    fees=st.session_state.fee_slider,
                    expenses=st.session_state.expense_slider,
                    num_block_billed=num_block_billed,
                    custom_line_items=st.session_state.custom_line_items,
                    timekeeper_data=st.session_state.timekeeper_data,
                    client_id=client_id,
                    law_firm_id=law_firm_id,
                    invoice_desc=invoice_desc,
                    billing_start_date=billing_start_date,
                    billing_end_date=billing_end_date,
                    faker_instance=faker
                )
                
                if 'spend_agent' in locals() and spend_agent and 'selected_items' in locals() and selected_items:
                    rows, _ = _ensure_mandatory_lines(rows, st.session_state.timekeeper_data, invoice_desc, client_id, law_firm_id, billing_start_date, billing_end_date, selected_items)
                    total_amount = sum(float(r.get("LINE_ITEM_TOTAL", 0)) for r in rows)

                st.success(f"Invoice {invoice_number} generated with {len(rows)} line items. Total: ${total_amount:,.2f}")
                
                # --- File Downloads ---
                c1, c2 = st.columns(2)
                
                ledes_content = _create_ledes_1998b_content(rows, total_amount, billing_start_date, billing_end_date, invoice_number, matter_number_base)
                c1.download_button(
                    label=f"Download LEDES for {invoice_number}",
                    data=ledes_content.encode('utf-8'),
                    file_name=f"LEDES_{invoice_number}.txt",
                    mime="text/plain",
                    key=f"ledes_dl_{i}"
                )

                if include_pdf:
                    pdf_buffer = _create_pdf_invoice(pd.DataFrame(rows), total_amount, invoice_number, billing_end_date, billing_start_date, billing_end_date, client_id, law_firm_id, client_name, law_firm_name)
                    c2.download_button(
                        label=f"Download PDF for {invoice_number}",
                        data=pdf_buffer.getvalue(),
                        file_name=f"Invoice_{invoice_number}.pdf",
                        mime="application/pdf",
                        key=f"pdf_dl_{i}"
                    )
                
                with st.expander(f"Preview Data for Invoice {invoice_number}"):
                    st.dataframe(pd.DataFrame(rows))
            
            status.update(label="All invoices generated!", state="complete")
