import streamlit as st
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


# ===============================
# Billing Profiles Configuration
# ===============================
# Format: (Environment, Client Name, Client ID, Law Firm Name, Law Firm ID)
BILLING_PROFILES = [
    ("Onit ELM",    "A Onit Inc.",   "02-4388252", "Nelson & Murdock", "02-1234567"),
    ("SimpleLegal", "Penguin LLC",   "C004",       "JDL",               "JDL001"),
    ("Unity",       "Unity Demo",    "uniti-demo", "Gold USD",          "Gold USD"),
]

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
        "Copying": "E101", "Outside printing": "E102", "Word processing": "E103",
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

def _force_timekeeper_on_row(row: Dict, forced_name: str, timekeepers: List[Dict], tax_rate: float) -> Optional[Dict]:
    """Assign timekeeper details to a row if a match is found."""
    if row.get("EXPENSE_CODE"):
        return row
    row["TIMEKEEPER_NAME"] = forced_name
    tk = _find_timekeeper_by_name(timekeepers, forced_name)
    if tk:
        row["TIMEKEEPER_ID"] = tk.get("TIMEKEEPER_ID", "")
        row["TIMEKEEPER_CLASSIFICATION"] = tk.get("TIMEKEEPER_CLASSIFICATION", "")
        try:
            row["RATE"] = float(tk.get("RATE", 0.0))
            hours = float(row.get("HOURS", 0))
            line_total = round(hours * float(row["RATE"]), 2)
            row["LINE_ITEM_TOTAL"] = line_total
            row["TAX_RATE"] = tax_rate
            row["TAX_AMOUNT"] = round(line_total * tax_rate, 2)
        except Exception as e:
            logging.error(f"Error setting timekeeper rate: {e}")
        return row
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
        custom_tasks = []
        for _, row in df.iterrows():
            custom_tasks.append((str(row["TASK_CODE"]), str(row["ACTIVITY_CODE"]), str(row["DESCRIPTION"])))
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

def _create_ledes_line_1998bi(row: Dict, line_no: int, inv_total_incl_tax: float, bill_start: datetime.date, bill_end: datetime.date, invoice_number: str, matter_number: str, tax_type: str) -> List[str]:
    """Create a single LEDES 1998BI line."""
    try:
        date_obj = datetime.datetime.strptime(row["LINE_ITEM_DATE"], "%Y-%m-%d").date()
        hours = float(row.get("HOURS", 0.0))
        rate = float(row.get("RATE", 0.0))
        line_total_excl_tax = float(row["LINE_ITEM_TOTAL"])
        tax_amount = float(row.get("TAX_AMOUNT", 0.0))
        tax_rate = float(row.get("TAX_RATE", 0.0)) * 100
        line_total_incl_tax = line_total_excl_tax + tax_amount
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
            bill_end.strftime("%Y%m%d"), invoice_number, str(row.get("CLIENT_ID", "")), str(row.get("LAW_FIRM_ID", "")),
            matter_number, f"{inv_total_incl_tax:.2f}", bill_start.strftime("%Y%m%d"), bill_end.strftime("%Y%m%d"),
            str(row.get("INVOICE_DESCRIPTION", "")), str(line_no), adj_type, f"{hours:.1f}" if adj_type == "F" else f"{int(hours)}",
            "0.00", f"{line_total_excl_tax:.2f}", f"{tax_rate:.2f}", f"{tax_amount:.2f}", f"{line_total_incl_tax:.2f}",
            date_obj.strftime("%Y%m%d"), task_code, expense_code, activity_code, timekeeper_id, description,
            f"{rate:.2f}", timekeeper_name, timekeeper_class, matter_number, tax_type
        ]
    except Exception as e:
        logging.error(f"Error creating LEDES 1998BI line: {e}")
        return []

def _create_ledes_1998bi_content(rows: List[Dict], bill_start: datetime.date, bill_end: datetime.date, invoice_number: str, matter_number: str, tax_type: str) -> str:
    """Generate LEDES 1998BI content from invoice rows."""
    header = "LEDES1998BI[]"
    fields = ("INVOICE_DATE|INVOICE_NUMBER|CLIENT_ID|LAW_FIRM_ID|LAW_FIRM_MATTER_ID|INVOICE_TOTAL_INCL_TAX|"
              "BILLING_START_DATE|BILLING_END_DATE|INVOICE_DESCRIPTION|LINE_ITEM_NUMBER|EXP/FEE/INV_ADJ_TYPE|"
              "LINE_ITEM_NUMBER_OF_UNITS|LINE_ITEM_ADJUSTMENT_AMOUNT|LINE_ITEM_TOTAL|LINE_ITEM_TAX_RATE|"
              "LINE_ITEM_TAX_AMOUNT|LINE_ITEM_TOTAL_INCL_TAX|LINE_ITEM_DATE|LINE_ITEM_TASK_CODE|"
              "LINE_ITEM_EXPENSE_CODE|LINE_ITEM_ACTIVITY_CODE|TIMEKEEPER_ID|LINE_ITEM_DESCRIPTION|"
              "LINE_ITEM_UNIT_COST|TIMEKEEPER_NAME|TIMEKEEPER_CLASSIFICATION|CLIENT_MATTER_ID|LINE_ITEM_TAX_TYPE[]")
    total_excl_tax = sum(float(row["LINE_ITEM_TOTAL"]) for row in rows)
    total_tax = sum(float(row.get("TAX_AMOUNT", 0.0)) for row in rows)
    total_incl_tax = total_excl_tax + total_tax
    lines = [header, fields]
    for i, row in enumerate(rows, start=1):
        line = _create_ledes_line_1998bi(row, i, total_incl_tax, bill_start, bill_end, invoice_number, matter_number, tax_type)
        if line:
            lines.append("|".join(map(str, line)) + "[]")
    return "\n".join(lines)


def _generate_fees(fee_count: int, timekeeper_data: List[Dict], billing_start_date: datetime.date, billing_end_date: datetime.date, task_activity_desc: List[Tuple[str, str, str]], major_task_codes: set, max_hours_per_tk_per_day: int, faker_instance: Faker, client_id: str, law_firm_id: str, invoice_desc: str, tax_rate: float) -> List[Dict]:
    """Generate fee line items for an invoice."""
    rows = []
    delta = billing_end_date - billing_start_date
    num_days = max(1, delta.days + 1)
    major_items = [item for item in task_activity_desc if item[0] in major_task_codes]
    other_items = [item for item in task_activity_desc if item[0] not in major_task_codes]
    daily_hours_tracker = {}
    MAX_DAILY_HOURS = max_hours_per_tk_per_day

    for _ in range(fee_count):
        if not task_activity_desc:
            break
        tk_row = random.choice(timekeeper_data)
        timekeeper_id = tk_row["TIMEKEEPER_ID"]
        if major_items and random.random() < 0.7:
            task_code, activity_code, description = random.choice(major_items)
        elif other_items:
            task_code, activity_code, description = random.choice(other_items)
        else:
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
        tax_amount = round(line_item_total * tax_rate, 2)
        daily_hours_tracker[(line_item_date_str, timekeeper_id)] = current_billed_hours + hours_to_bill
        description = _process_description(description, faker_instance)
        row = {
            "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id,
            "LINE_ITEM_DATE": line_item_date_str, "TIMEKEEPER_NAME": tk_row["TIMEKEEPER_NAME"],
            "TIMEKEEPER_CLASSIFICATION": tk_row["TIMEKEEPER_CLASSIFICATION"],
            "TIMEKEEPER_ID": timekeeper_id, "TASK_CODE": task_code,
            "ACTIVITY_CODE": activity_code, "EXPENSE_CODE": "", "DESCRIPTION": description,
            "HOURS": hours_to_bill, "RATE": hourly_rate, "LINE_ITEM_TOTAL": line_item_total,
            "TAX_RATE": tax_rate, "TAX_AMOUNT": tax_amount
        }
        rows.append(row)
    return rows



def _generate_expenses(expense_count: int, billing_start_date: datetime.date, billing_end_date: datetime.date, client_id: str, law_firm_id: str, invoice_desc: str, tax_rate: float) -> List[Dict]:
    """Generate expense line items for an invoice with realistic amounts."""
    rows: List[Dict] = []
    delta = billing_end_date - billing_start_date
    num_days = max(1, delta.days + 1)
    mileage_rate_cfg = float(st.session_state.get("mileage_rate_e109", 0.65))
    travel_rng = st.session_state.get("travel_range_e110", (100.0, 800.0))
    tel_rng = st.session_state.get("telephone_range_e105", (5.0, 15.0))
    copying_rate = float(st.session_state.get("copying_rate_e101", 0.24))
    
    travel_min, travel_max = float(travel_rng[0]), float(travel_rng[1])
    tel_min, tel_max = float(tel_rng[0]), float(tel_rng[1])


    e101_actual_count = random.randint(1, min(3, expense_count)) if expense_count > 0 else 0
    for _ in range(e101_actual_count):
        description = "Copying"
        expense_code = "E101"
        hours = random.randint(50, 300)
        rate = round(copying_rate, 2)
        random_day_offset = random.randint(0, num_days - 1)
        line_item_date = billing_start_date + datetime.timedelta(days=random_day_offset)
        line_item_total = round(hours * rate, 2)
        tax_amount = round(line_item_total * tax_rate, 2)
        row = {
            "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id,
            "LINE_ITEM_DATE": line_item_date.strftime("%Y-%m-%d"), "TIMEKEEPER_NAME": "",
            "TIMEKEEPER_CLASSIFICATION": "", "TIMEKEEPER_ID": "",
            "TASK_CODE": "", "ACTIVITY_CODE": "", "EXPENSE_CODE": expense_code, "DESCRIPTION": description,
            "HOURS": hours, "RATE": rate, "LINE_ITEM_TOTAL": line_item_total,
            "TAX_RATE": tax_rate, "TAX_AMOUNT": tax_amount
        }
        rows.append(row)

    for _ in range(max(0, expense_count - e101_actual_count)):
        description = random.choice(OTHER_EXPENSE_DESCRIPTIONS)
        expense_code = CONFIG['EXPENSE_CODES'][description]
        random_day_offset = random.randint(0, num_days - 1)
        line_item_date = billing_start_date + datetime.timedelta(days=random_day_offset)

        if expense_code == "E109":
            miles = random.randint(5, 50)
            hours = miles
            rate = mileage_rate_cfg
            line_item_total = round(miles * rate, 2)
        elif expense_code == "E110":
            hours = 1
            rate = round(random.uniform(travel_min, travel_max), 2)
            line_item_total = rate
        elif expense_code == "E105":
            hours = 1
            rate = round(random.uniform(tel_min, tel_max), 2)
            line_item_total = rate
        else:
            hours = random.randint(1, 5)
            rate = round(random.uniform(10.0, 150.0), 2)
            line_item_total = round(hours * rate, 2)

        tax_amount = round(line_item_total * tax_rate, 2)
        row = {
            "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id,
            "LINE_ITEM_DATE": line_item_date.strftime("%Y-%m-%d"), "TIMEKEEPER_NAME": "",
            "TIMEKEEPER_CLASSIFICATION": "", "TIMEKEEPER_ID": "",
            "TASK_CODE": "", "ACTIVITY_CODE": "", "EXPENSE_CODE": expense_code, "DESCRIPTION": description,
            "HOURS": hours, "RATE": rate, "LINE_ITEM_TOTAL": line_item_total,
            "TAX_RATE": tax_rate, "TAX_AMOUNT": tax_amount
        }
        rows.append(row)
    return rows

def _generate_invoice_data(fee_count: int, expense_count: int, timekeeper_data: List[Dict], client_id: str, law_firm_id: str, invoice_desc: str, billing_start_date: datetime.date, billing_end_date: datetime.date, task_activity_desc: List[Tuple[str, str, str]], major_task_codes: set, max_hours_per_tk_per_day: int, include_block_billed: bool, faker_instance: Faker, tax_rate: float) -> Tuple[List[Dict], float]:
    """Generate invoice data with fees and expenses."""
    rows = []
    rows.extend(_generate_fees(fee_count, timekeeper_data, billing_start_date, billing_end_date, task_activity_desc, major_task_codes, max_hours_per_tk_per_day, faker_instance, client_id, law_firm_id, invoice_desc, tax_rate))
    rows.extend(_generate_expenses(expense_count, billing_start_date, billing_end_date, client_id, law_firm_id, invoice_desc, tax_rate))
    
    fee_rows = [row for row in rows if not row.get("EXPENSE_CODE")]
    
    if include_block_billed and fee_rows:
        from collections import defaultdict
        daily_tk_groups = defaultdict(list)
        for row in fee_rows:
            key = (row["TIMEKEEPER_ID"], row["LINE_ITEM_DATE"])
            daily_tk_groups[key].append(row)
            
        eligible_groups = []
        for key, group_rows in daily_tk_groups.items():
            if len(group_rows) > 1:
                total_hours = sum(float(r["HOURS"]) for r in group_rows)
                if total_hours <= max_hours_per_tk_per_day:
                    eligible_groups.append(group_rows)

        if eligible_groups:
            selected_rows = random.choice(eligible_groups)
            
            total_hours = sum(float(row["HOURS"]) for row in selected_rows)
            total_amount_block = sum(float(row["LINE_ITEM_TOTAL"]) for row in selected_rows)
            total_tax_block = sum(float(row.get("TAX_AMOUNT", 0.0)) for row in selected_rows)
            descriptions = [row["DESCRIPTION"] for row in selected_rows]
            block_description = "; ".join(descriptions)
            
            first_row = selected_rows[0]
            
            block_row = {
                "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id,
                "LINE_ITEM_DATE": first_row["LINE_ITEM_DATE"], "TIMEKEEPER_NAME": first_row["TIMEKEEPER_NAME"],
                "TIMEKEEPER_CLASSIFICATION": first_row["TIMEKEEPER_CLASSIFICATION"],
                "TIMEKEEPER_ID": first_row["TIMEKEEPER_ID"], "TASK_CODE": first_row["TASK_CODE"],
                "ACTIVITY_CODE": first_row["ACTIVITY_CODE"], "EXPENSE_CODE": "",
                "DESCRIPTION": block_description, "HOURS": round(total_hours, 2), "RATE": first_row["RATE"],
                "LINE_ITEM_TOTAL": round(total_amount_block, 2),
                "TAX_RATE": tax_rate, "TAX_AMOUNT": round(total_tax_block, 2)
            }
            
            rows_to_remove_ids = {id(row) for row in selected_rows}
            new_rows = [row for row in rows if id(row) not in rows_to_remove_ids]
            new_rows.append(block_row)
            rows = new_rows

    total_amount_excl_tax = sum(float(row["LINE_ITEM_TOTAL"]) for row in rows)
    return rows, total_amount_excl_tax

def _ensure_mandatory_lines(rows: List[Dict], timekeeper_data: List[Dict], invoice_desc: str, client_id: str, law_firm_id: str, billing_start_date: datetime.date, billing_end_date: datetime.date, selected_items: List[str], tax_rate: float) -> Tuple[List[Dict], List[str]]:
    """Ensure mandatory line items are included and return a list of any skipped items."""
    delta = billing_end_date - billing_start_date
    num_days = max(1, delta.days + 1)
    skipped_items = []

    for item_name in selected_items:
        random_day_offset = random.randint(0, num_days - 1)
        line_item_date = billing_start_date + datetime.timedelta(days=random_day_offset)
        item = CONFIG['MANDATORY_ITEMS'][item_name]

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
                tax_amount = round(amount * tax_rate, 2)
                
                row = {
                    "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id,
                    "LINE_ITEM_DATE": line_item_date.strftime("%Y-%m-%d"), "TIMEKEEPER_NAME": "",
                    "TIMEKEEPER_CLASSIFICATION": "", "TIMEKEEPER_ID": "", "TASK_CODE": "",
                    "ACTIVITY_CODE": "", "EXPENSE_CODE": "E110", "DESCRIPTION": description,
                    "HOURS": 1, "RATE": amount, "LINE_ITEM_TOTAL": amount,
                    "TAX_RATE": tax_rate, "TAX_AMOUNT": tax_amount,
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
                tax_amount = round(amount * tax_rate, 2)
                row = {
                    "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id,
                    "LINE_ITEM_DATE": line_item_date.strftime("%Y-%m-%d"), "TIMEKEEPER_NAME": "",
                    "TIMEKEEPER_CLASSIFICATION": "", "TIMEKEEPER_ID": "", "TASK_CODE": "",
                    "ACTIVITY_CODE": "", "EXPENSE_CODE": "E110", "DESCRIPTION": description,
                    "HOURS": 1, "RATE": amount, "LINE_ITEM_TOTAL": amount,
                    "TAX_RATE": tax_rate, "TAX_AMOUNT": tax_amount,
                }
                rows.append(row)
        elif item['is_expense']:
            row = {
                "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id,
                "LINE_ITEM_DATE": line_item_date.strftime("%Y-%m-%d"), "TIMEKEEPER_NAME": "",
                "TIMEKEEPER_CLASSIFICATION": "", "TIMEKEEPER_ID": "", "TASK_CODE": "",
                "ACTIVITY_CODE": "", "EXPENSE_CODE": item['expense_code'], "DESCRIPTION": item['desc'],
                "HOURS": random.randint(1, 10), "RATE": round(random.uniform(5.0, 100.0), 2)
            }
            line_total = round(row["HOURS"] * row["RATE"], 2)
            row["LINE_ITEM_TOTAL"] = line_total
            row["TAX_RATE"] = tax_rate
            row["TAX_AMOUNT"] = round(line_total * tax_rate, 2)
            rows.append(row)
        else: # Fee items
            row_template = {
                "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id,
                "LINE_ITEM_DATE": line_item_date.strftime("%Y-%m-%d"), "TIMEKEEPER_NAME": item['tk_name'],
                "TIMEKEEPER_CLASSIFICATION": "", "TIMEKEEPER_ID": "", "TASK_CODE": item['task'],
                "ACTIVITY_CODE": item['activity'], "EXPENSE_CODE": "", "DESCRIPTION": item['desc'],
                "HOURS": round(random.uniform(0.5, 8.0), 1), "RATE": 0.0
            }
            processed_row = _force_timekeeper_on_row(row_template, item['tk_name'], timekeeper_data, tax_rate)
            
            if processed_row:
                rows.append(processed_row)
            else:
                skipped_items.append(item_name)
            
    return rows, skipped_items

def _validate_image_bytes(image_bytes: bytes) -> bool:
    """Validate that the provided bytes represent a valid image."""
    try:
        img = PILImage.open(io.BytesIO(image_bytes))
        img.verify()
        return True
    except Exception:
        return False

def _get_logo_bytes(uploaded_logo: Optional[Any], law_firm_id: str, use_custom: bool) -> Optional[bytes]:
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
    script_dir = os.path.dirname(os.path.abspath(__file__)) if '__file__' in locals() else '.'
    logo_path = os.path.join(script_dir, "assets", logo_file_name)
    try:
        with open(logo_path, "rb") as f:
            return f.read()
    except Exception as e:
        logging.error(f"Logo load failed: {e}")
        st.warning(f"Default logo file not found or invalid. No logo will be used.")
    return None


def _create_pdf_invoice(df: pd.DataFrame, invoice_number: str, invoice_date: datetime.date, billing_start_date: datetime.date, billing_end_date: datetime.date, client_id: str, law_firm_id: str, logo_bytes: Optional[bytes] = None, include_logo: bool = False, client_name: str = "", law_firm_name: str = "", tax_rate_percent: float = 0.0) -> io.BytesIO:
    """Generate a PDF invoice, optionally with tax."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, leftMargin=0.5*inch, rightMargin=0.5*inch, topMargin=0.5*inch, bottomMargin=0.5*inch)
    elements = []
    styles = getSampleStyleSheet()
    styles['Normal'].fontSize = 8
    styles['Normal'].leading = 10
    
    header_info_style = ParagraphStyle('HeaderInfo', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, leading=12)
    right_align_style = ParagraphStyle('RightAlign', parent=styles['Normal'], alignment=TA_RIGHT)
    
    # Header logic remains the same...

    # Table headers
    header_cols = ["Date", "Task", "Act", "Timekeeper", "Description", "Hours", "Rate", "Subtotal"]
    col_widths = [0.6*inch, 0.4*inch, 0.4*inch, 0.9*inch, 2.3*inch, 0.5*inch, 0.5*inch, 0.6*inch]
    
    if tax_rate_percent > 0:
        header_cols.insert(-1, f"Tax")
        col_widths.insert(-1, 0.5*inch)
        col_widths[4] -= 0.5*inch
    header_cols.append("Total")
    col_widths.append(0.7*inch)

    data = [[Paragraph(h, styles['Normal']) for h in header_cols]]
    
    for _, row in df.iterrows():
        subtotal_val = float(row['LINE_ITEM_TOTAL'])
        tax_val = float(row.get('TAX_AMOUNT', 0.0))
        total_val = subtotal_val + tax_val
        
        row_data = [
            Paragraph(row["LINE_ITEM_DATE"], styles['Normal']),
            Paragraph(row.get("TASK_CODE", ""), styles['Normal']),
            Paragraph(row.get("ACTIVITY_CODE", ""), styles['Normal']),
            Paragraph(row.get("TIMEKEEPER_NAME", ""), styles['Normal']),
            Paragraph(row["DESCRIPTION"], styles['Normal']),
            Paragraph(f"{row.get('HOURS', 0):.1f}" if not row.get("EXPENSE_CODE") else str(int(row.get('HOURS', 0))), styles['Normal']),
            Paragraph(f"${row.get('RATE', 0):.2f}", styles['Normal']),
            Paragraph(f"${subtotal_val:,.2f}", right_align_style)
        ]
        
        if tax_rate_percent > 0:
            row_data.append(Paragraph(f"${tax_val:,.2f}", right_align_style))
        
        row_data.append(Paragraph(f"${total_val:,.2f}", right_align_style))
        data.append(row_data)

    table = Table(data, colWidths=col_widths)
    elements.append(table)
    
    # Totals block
    is_fee = df['EXPENSE_CODE'].fillna('').eq('')
    fees_total = df.loc[is_fee, 'LINE_ITEM_TOTAL'].sum()
    expenses_total = df.loc[~is_fee, 'LINE_ITEM_TOTAL'].sum()
    tax_total = df['TAX_AMOUNT'].sum() if 'TAX_AMOUNT' in df.columns and tax_rate_percent > 0 else 0.0
    total_incl_tax = fees_total + expenses_total + tax_total

    totals_data = [
        [Paragraph("Subtotal Fees:", styles['Normal']), Paragraph(f"${fees_total:,.2f}", right_align_style)],
        [Paragraph("Subtotal Expenses:", styles['Normal']), Paragraph(f"${expenses_total:,.2f}", right_align_style)],
    ]
    if tax_total > 0:
        totals_data.append([Paragraph(f"Total Tax ({tax_rate_percent:.1f}%):", styles['Normal']), Paragraph(f"${tax_total:,.2f}", right_align_style)])
    totals_data.append([Paragraph("Invoice Total:", styles['Normal']), Paragraph(f"${total_incl_tax:,.2f}", right_align_style)])
    
    totals_table = Table(totals_data, colWidths=[1.5*inch, 1.0*inch], hAlign='RIGHT')
    elements.append(totals_table)

    doc.build(elements)
    buffer.seek(0)
    return buffer

def _create_receipt_image(expense_row: dict, faker_instance: Faker) -> Tuple[str, io.BytesIO]:
    """Enhanced realistic receipt generator."""
    # This function remains unchanged
    img = PILImage.new("RGB", (600, 800), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 20)
    except IOError:
        font = ImageFont.load_default()
    draw.text((10, 10), f"Receipt for {expense_row['DESCRIPTION']}", font=font, fill=(0,0,0))
    draw.text((10, 40), f"Total: ${expense_row['LINE_ITEM_TOTAL']:.2f}", font=font, fill=(0,0,0))
    
    img_buffer = io.BytesIO()
    img.save(img_buffer, format="PNG")
    img_buffer.seek(0)
    
    filename = f"Receipt_{expense_row.get('EXPENSE_CODE', 'NA')}_{expense_row['LINE_ITEM_DATE']}.png"
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
    except (AttributeError, KeyError):
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
    st.session_state.send_email = st.session_state.send_email_checkbox

with st.expander("Help & FAQs"):
    st.markdown("""
    ### FAQs
    - **What is Spend Agent mode?** Ensures specific mandatory line items are included.
    - **How to format timekeeper CSV?** Columns: TIMEKEEPER_NAME, TIMEKEEPER_CLASSIFICATION, TIMEKEEPER_ID, RATE
    """)

st.markdown("<h3 style='color: #1E1E1E;'>Output & Delivery Options</h3>", unsafe_allow_html=True)
st.checkbox(
    "Send Invoices via Email",
    value=st.session_state.send_email,
    key="send_email_checkbox",
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

# Dynamic Tabs
tabs = ["Data Sources", "Invoice Details", "Fees & Expenses", "Output"]
if st.session_state.send_email:
    tabs.append("Email Configuration")

tab_objects = st.tabs(tabs)
recipient_email = ""


with tab_objects[0]: # Data Sources
    st.markdown("<h3 style='color: #1E1E1E;'>Data Sources</h3>", unsafe_allow_html=True)
    uploaded_timekeeper_file = st.file_uploader("Upload Timekeeper CSV (tk_info.csv)", type="csv")
    timekeeper_data = _load_timekeepers(uploaded_timekeeper_file)
    if timekeeper_data is not None:
        st.success(f"Loaded {len(timekeeper_data)} timekeepers.")
    
    use_custom_tasks = st.checkbox("Use Custom Line Item Details?", value=True)
    if use_custom_tasks:
        uploaded_custom_tasks_file = st.file_uploader("Upload Custom Line Items CSV (custom_details.csv)", type="csv")
        task_activity_desc = _load_custom_task_activity_data(uploaded_custom_tasks_file) or CONFIG['DEFAULT_TASK_ACTIVITY_DESC']
    else:
        task_activity_desc = CONFIG['DEFAULT_TASK_ACTIVITY_DESC']


with tab_objects[1]: # Invoice Details
    st.markdown("<h2 style='color: #1E1E1E;'>Invoice Details</h2>", unsafe_allow_html=True)
    env_names = [p[0] for p in BILLING_PROFILES]
    selected_env = st.selectbox("Environment / Profile", env_names, key="selected_env")
    prof_client_name, prof_client_id, prof_law_firm_name, prof_law_firm_id = get_profile(selected_env)

    client_id = st.text_input("Client ID", prof_client_id)
    law_firm_id = st.text_input("Law Firm ID", prof_law_firm_id)
    client_name = st.text_input("Client Name", prof_client_name)
    law_firm_name = st.text_input("Law Firm Name", prof_law_firm_name)


    matter_number_base = st.text_input("Matter Number:", "2025-XXXXXX")
    invoice_number_base = st.text_input("Invoice Number (Base):", "2025MMM-XXXXXX")

    LEDES_OPTIONS = ["1998B", "1998BI", "XML 2.1"]
    ledes_version = st.selectbox("LEDES Version:", LEDES_OPTIONS, key="ledes_version")
    
    if ledes_version == "1998BI":
        st.number_input(
            "VAT / Tax Rate (%)", min_value=0.0, max_value=100.0, value=19.0,
            step=0.1, key="tax_rate_input", help="Enter the tax rate for 1998BI invoices."
        )
        st.text_input("Tax Type", value="VAT", key="tax_type", help="e.g., VAT, GST")

    
    today = datetime.date.today()
    billing_start_date = st.date_input("Billing Start Date", value=today.replace(day=1) - datetime.timedelta(days=30))
    billing_end_date = st.date_input("Billing End Date", value=today.replace(day=1) - datetime.timedelta(days=1))
    invoice_desc = st.text_area("Invoice Description", "Professional Services Rendered")


with tab_objects[2]: # Fees & Expenses
    st.markdown("<h2 style='color: #1E1E1E;'>Fees & Expenses</h2>", unsafe_allow_html=True)
    spend_agent = st.checkbox("Spend Agent", value=False)
    if timekeeper_data is None:
        st.error("Please upload a timekeeper CSV on the 'Data Sources' tab to continue.")
    else:
        max_fees = _calculate_max_fees(timekeeper_data, billing_start_date, billing_end_date, 16)
        fees = st.slider("Number of Fee Line Items", 1, max_fees, min(20, max_fees))
        expenses = st.slider("Number of Expense Line Items", 0, 50, 5)
        max_daily_hours = st.number_input("Max Daily Timekeeper Hours:", 1, 24, 16)
    
        if spend_agent:
            st.markdown("<h3 style='color: #1E1E1E;'>Mandatory Items</h3>", unsafe_allow_html=True)
            all_mandatory_items = list(CONFIG['MANDATORY_ITEMS'].keys())
            if selected_env == 'SimpleLegal':
                available_items = [name for name, details in CONFIG['MANDATORY_ITEMS'].items() if details.get('is_expense')]
                st.info("For 'SimpleLegal' profile, only expense-based mandatory items are available.")
                default_items = available_items
            else:
                available_items = all_mandatory_items
                default_items = all_mandatory_items
            
            selected_items = st.multiselect("Select Mandatory Items", options=available_items, default=default_items)

            if 'Airfare E110' in selected_items:
                st.text_input("Airline", "United Airlines", key="airfare_airline")
                st.number_input("Amount", 0.0, 10000.0, 450.75, key="airfare_amount")
            if 'Uber E110' in selected_items:
                st.number_input("Ride Amount", 0.0, 1000.0, 25.50, key="uber_amount")

with tab_objects[3]: # Output
    st.markdown("<h2 style='color: #1E1E1E;'>Output</h2>", unsafe_allow_html=True)
    include_block_billed = st.checkbox("Include Block Billed Line Items", value=True)
    include_pdf = st.checkbox("Include PDF Invoice", value=True)
    if include_pdf:
        include_logo = st.checkbox("Include Logo in PDF", value=True)
        if include_logo:
            use_custom_logo = st.checkbox("Use Custom Logo", value=False)
            if use_custom_logo:
                uploaded_logo = st.file_uploader("Upload Custom Logo", type=["jpg", "png"])
            else:
                uploaded_logo = None
    
    generate_multiple = st.checkbox("Generate Multiple Invoices")
    num_invoices = 1
    if generate_multiple:
        num_invoices = st.number_input("Number of Invoices", 1, 10, 1)

    generate_receipts = st.checkbox("Generate Sample Receipts for Expenses?")
    zip_receipts = False
    if generate_receipts:
        zip_receipts = st.checkbox("Zip Receipts", value=True)

if st.session_state.send_email and len(tabs) > 4:
    with tab_objects[4]: # Email Configuration
        st.markdown("<h2 style='color: #1E1E1E;'>Email Configuration</h2>", unsafe_allow_html=True)
        recipient_email = st.text_input("Recipient Email Address:")
        st.text_input("Email Subject Template:", f"LEDES Invoice for {matter_number_base} (Invoice #{{invoice_number}})", key="email_subject")
        st.text_area("Email Body Template:", f"Please find attached the invoice files for matter {{matter_number}}.", height=150, key="email_body")


# --- Main App Logic ---
generate_button = st.button("Generate Invoice(s)")
if generate_button:
    if timekeeper_data is None:
        st.error("Cannot generate invoice. Please upload a timekeeper file.")
    else:
        faker = Faker()
        tax_rate_percent = st.session_state.get("tax_rate_input", 0.0) if ledes_version == "1998BI" else 0.0
        tax_rate_decimal = tax_rate_percent / 100.0
        tax_type = st.session_state.get("tax_type", "") if ledes_version == "1998BI" else ""

        attachments_list = []
        receipt_files = []

        with st.spinner("Generating invoices..."):
            for i in range(num_invoices):
                current_invoice_number = f"{invoice_number_base}-{i+1}"
                current_matter_number = matter_number_base
                
                rows, total_amount_excl_tax = _generate_invoice_data(
                    fees, expenses, timekeeper_data, client_id, law_firm_id,
                    invoice_desc, billing_start_date, billing_end_date,
                    task_activity_desc, CONFIG['MAJOR_TASK_CODES'], max_daily_hours, include_block_billed, faker,
                    tax_rate=tax_rate_decimal
                )
                
                skipped_items = []
                if spend_agent:
                    rows, skipped_items = _ensure_mandatory_lines(
                        rows, timekeeper_data, invoice_desc, client_id, law_firm_id,
                        billing_start_date, billing_end_date, selected_items, tax_rate_decimal
                    )
                
                df_invoice = pd.DataFrame(rows)
                total_amount_excl_tax = df_invoice["LINE_ITEM_TOTAL"].sum()
                
                if skipped_items:
                    st.warning(f"Skipped mandatory items because timekeeper was not found: {', '.join(skipped_items)}")
                
                if ledes_version == "1998B":
                    ledes_content_part = _create_ledes_1998b_content(df_invoice.to_dict('records'), total_amount_excl_tax, billing_start_date, billing_end_date, current_invoice_number, current_matter_number)
                    ledes_filename = f"LEDES_1998B_{current_invoice_number}.txt"
                elif ledes_version == "1998BI":
                    ledes_content_part = _create_ledes_1998bi_content(df_invoice.to_dict('records'), billing_start_date, billing_end_date, current_invoice_number, current_matter_number, tax_type)
                    ledes_filename = f"LEDES_1998BI_{current_invoice_number}.txt"
                else:
                    st.warning("XML 2.1 is not yet implemented.")
                    continue
                
                attachments_list.append((ledes_filename, ledes_content_part.encode('utf-8')))

                if include_pdf:
                    logo_bytes = None
                    if 'include_logo' in locals() and include_logo:
                        current_use_custom = use_custom_logo if 'use_custom_logo' in locals() else False
                        current_uploaded_logo = uploaded_logo if 'uploaded_logo' in locals() else None
                        logo_bytes = _get_logo_bytes(current_uploaded_logo, law_firm_id, current_use_custom)
                    pdf_buffer = _create_pdf_invoice(
                        df_invoice, current_invoice_number, billing_end_date,
                        billing_start_date, billing_end_date, client_id, law_firm_id,
                        logo_bytes, include_logo if 'include_logo' in locals() else False, client_name, law_firm_name, tax_rate_percent
                    )
                    attachments_list.append((f"Invoice_{current_invoice_number}.pdf", pdf_buffer.getvalue()))

                if generate_receipts:
                    for _, row in df_invoice.iterrows():
                        if row.get("EXPENSE_CODE"):
                            receipt_filename, receipt_data = _create_receipt_image(row.to_dict(), faker)
                            receipt_files.append((receipt_filename, receipt_data.getvalue()))

            if receipt_files:
                if zip_receipts:
                    zip_buffer = io.BytesIO()
                    with zipfile.ZipFile(zip_buffer, 'w') as zf:
                        for name, data in receipt_files:
                            zf.writestr(name, data)
                    attachments_list.append(("receipts.zip", zip_buffer.getvalue()))
                else:
                    attachments_list.extend(receipt_files)

            if st.session_state.send_email:
                subject, body = _customize_email_body(matter_number_base, invoice_number_base)
                if _send_email_with_attachment(recipient_email, subject, body, attachments_list):
                    st.success("Email sent successfully!")
                else:
                    st.error("Failed to send email.")
            else:
                for filename, data in attachments_list:
                    st.download_button(
                        label=f"Download {filename}",
                        data=data,
                        file_name=filename,
                        mime="application/octet-stream"
                    )
        st.success("Invoice generation complete!")

