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
            'desc': "10-mile Uber ride to client's office",
            'expense_code': "E110",
            'is_expense': True
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

def _force_timekeeper_on_row(row: Dict, forced_name: str, timekeepers: List[Dict]) -> Dict:
    """Assign timekeeper details to a row if applicable."""
    if row.get("EXPENSE_CODE"):
        return row
    tk = _find_timekeeper_by_name(timekeepers, forced_name)
    if tk is None and timekeepers:
        tk = timekeepers[0]
    if tk is None:
        row["TIMEKEEPER_NAME"] = forced_name
        return row
    row["TIMEKEEPER_NAME"] = forced_name
    row["TIMEKEEPER_ID"] = tk.get("TIMEKEEPER_ID", row.get("TIMEKEEPER_ID", ""))
    row["TIMEKEEPER_CLASSIFICATION"] = tk.get("TIMEKEEPER_CLASSIFICATION", row.get("TIMEKEEPER_CLASSIFICATION", ""))
    try:
        row["RATE"] = float(tk.get("RATE", row.get("RATE", 0.0)))
        hours = float(row.get("HOURS", 0))
        row["LINE_ITEM_TOTAL"] = round(hours * float(row["RATE"]), 2)
    except Exception as e:
        logging.error(f"Error setting timekeeper rate: {e}")
    return row

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

def _generate_fees(fee_count: int, timekeeper_data: List[Dict], billing_start_date: datetime.date, billing_end_date: datetime.date, task_activity_desc: List[Tuple[str, str, str]], major_task_codes: set, max_hours_per_tk_per_day: int, faker_instance: Faker, client_id: str, law_firm_id: str, invoice_desc: str) -> List[Dict]:
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
        daily_hours_tracker[(line_item_date_str, timekeeper_id)] = current_billed_hours + hours_to_bill
        description = _process_description(description, faker_instance)
        row = {
            "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id,
            "LINE_ITEM_DATE": line_item_date_str, "TIMEKEEPER_NAME": tk_row["TIMEKEEPER_NAME"],
            "TIMEKEEPER_CLASSIFICATION": tk_row["TIMEKEEPER_CLASSIFICATION"],
            "TIMEKEEPER_ID": timekeeper_id, "TASK_CODE": task_code,
            "ACTIVITY_CODE": activity_code, "EXPENSE_CODE": "", "DESCRIPTION": description,
            "HOURS": hours_to_bill, "RATE": hourly_rate, "LINE_ITEM_TOTAL": line_item_total
        }
        rows.append(row)
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
        description = "Copying"
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

def _generate_invoice_data(fee_count: int, expense_count: int, timekeeper_data: List[Dict], client_id: str, law_firm_id: str, invoice_desc: str, billing_start_date: datetime.date, billing_end_date: datetime.date, task_activity_desc: List[Tuple[str, str, str]], major_task_codes: set, max_hours_per_tk_per_day: int, include_block_billed: bool, faker_instance: Faker) -> Tuple[List[Dict], float]:
    """Generate invoice data with fees and expenses."""
    rows = []
    rows.extend(_generate_fees(fee_count, timekeeper_data, billing_start_date, billing_end_date, task_activity_desc, major_task_codes, max_hours_per_tk_per_day, faker_instance, client_id, law_firm_id, invoice_desc))
    rows.extend(_generate_expenses(expense_count, billing_start_date, billing_end_date, client_id, law_firm_id, invoice_desc))
    total_amount = sum(float(row["LINE_ITEM_TOTAL"]) for row in rows)

    # Filter for fees only before creating block billed items
    fee_rows = [row for row in rows if not row.get("EXPENSE_CODE")]
    
    if include_block_billed and fee_rows:
        block_size = random.randint(2, 5)
        selected_rows = random.sample(fee_rows, min(block_size, len(fee_rows)))
        total_hours = sum(float(row["HOURS"]) for row in selected_rows)
        total_amount_block = sum(float(row["LINE_ITEM_TOTAL"]) for row in selected_rows)
        descriptions = [row["DESCRIPTION"] for row in selected_rows]
        block_description = "; ".join(descriptions)
        block_row = {
            "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id,
            "LINE_ITEM_DATE": selected_rows[0]["LINE_ITEM_DATE"], "TIMEKEEPER_NAME": selected_rows[0]["TIMEKEEPER_NAME"],
            "TIMEKEEPER_CLASSIFICATION": selected_rows[0]["TIMEKEEPER_CLASSIFICATION"],
            "TIMEKEEPER_ID": selected_rows[0]["TIMEKEEPER_ID"], "TASK_CODE": selected_rows[0]["TASK_CODE"],
            "ACTIVITY_CODE": selected_rows[0]["ACTIVITY_CODE"], "EXPENSE_CODE": "",
            "DESCRIPTION": block_description, "HOURS": total_hours, "RATE": selected_rows[0]["RATE"],
            "LINE_ITEM_TOTAL": total_amount_block
        }
        rows = [row for row in rows if row not in selected_rows]
        rows.append(block_row)
        total_amount = sum(float(row["LINE_ITEM_TOTAL"]) for row in rows)

    return rows, total_amount

def _ensure_mandatory_lines(rows: List[Dict], timekeeper_data: List[Dict], invoice_desc: str, client_id: str, law_firm_id: str, billing_start_date: datetime.date, billing_end_date: datetime.date, selected_items: List[str]) -> List[Dict]:
    """Ensure mandatory line items are included."""
    delta = billing_end_date - billing_start_date
    num_days = max(1, delta.days + 1)
    for item_name in selected_items:
        item = CONFIG['MANDATORY_ITEMS'][item_name]
        random_day_offset = random.randint(0, num_days - 1)
        line_item_date = billing_start_date + datetime.timedelta(days=random_day_offset)
        if item['is_expense']:
            row = {
                "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id,
                "LINE_ITEM_DATE": line_item_date.strftime("%Y-%m-%d"), "TIMEKEEPER_NAME": "",
                "TIMEKEEPER_CLASSIFICATION": "", "TIMEKEEPER_ID": "", "TASK_CODE": "",
                "ACTIVITY_CODE": "", "EXPENSE_CODE": item['expense_code'], "DESCRIPTION": item['desc'],
                "HOURS": random.randint(1, 10), "RATE": round(random.uniform(5.0, 100.0), 2)
            }
            row["LINE_ITEM_TOTAL"] = round(row["HOURS"] * row["RATE"], 2)
        else:
            row = {
                "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id,
                "LINE_ITEM_DATE": line_item_date.strftime("%Y-%m-%d"), "TIMEKEEPER_NAME": item['tk_name'],
                "TIMEKEEPER_CLASSIFICATION": "", "TIMEKEEPER_ID": "", "TASK_CODE": item['task'],
                "ACTIVITY_CODE": item['activity'], "EXPENSE_CODE": "", "DESCRIPTION": item['desc'],
                "HOURS": round(random.uniform(0.5, 8.0), 1), "RATE": 0.0
            }
            row = _force_timekeeper_on_row(row, item['tk_name'], timekeeper_data)
        rows.append(row)
    return rows

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
    logo_bytes: bytes,
    include_logo: bool = True,
    client_name: str = "",
    law_firm_name: str = ""
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

    # Header: law firm (left) / client (right)
    lf_name = law_firm_name or "Law Firm"
    cl_name = client_name or "Client"
    law_firm_info = f"{lf_name}<br/>{law_firm_id}<br/>One Park Avenue<br/>Manhattan, NY 10003"
    client_info   = f"{cl_name}<br/>{client_id}<br/>1360 Post Oak Blvd<br/>Houston, TX 77056"

    law_firm_para = Paragraph(law_firm_info, header_info_style)
    client_para = Paragraph(client_info, client_info_style)

    header_left_content = law_firm_para
    if include_logo:
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

    # Invoice info
    invoice_info = f"Invoice #: {invoice_number}<br/>Invoice Date: {invoice_date.strftime('%Y-%m-%d')}<br/>Billing Period: {billing_start_date.strftime('%Y-%m-%d')} to {billing_end_date.strftime('%Y-%m-%d')}"
    invoice_para = Paragraph(invoice_info, right_align_style)
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

    elements.append(Spacer(1, 0.25 * inch))
    total_para = Paragraph(f"Total: ${total_amount:.2f}", right_align_style)
    elements.append(total_para)

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

    
    # === Receipt Settings read from UI ===
    try:
        import streamlit as st
    except Exception:
        st = None
    rcpt_scale = (st.session_state.get("rcpt_scale", 1.0) if st else 1.0)
    rcpt_line_weight = int(st.session_state.get("rcpt_line_weight", 1)) if st else 1
    rcpt_dashed = bool(st.session_state.get("rcpt_dashed", False)) if st else False
    
    show_policy_map = {
        "travel": bool(st.session_state.get("rcpt_show_policy_travel", True)) if st else True,
        "meal": bool(st.session_state.get("rcpt_show_policy_meal", True)) if st else True,
        "mileage": bool(st.session_state.get("rcpt_show_policy_mileage", True)) if st else True,
        "supplies": bool(st.session_state.get("rcpt_show_policy_supplies", True)) if st else True,
        "generic": bool(st.session_state.get("rcpt_show_policy_generic", True)) if st else True,
        "delivery": True,
        "postage": True,
        "rideshare": True,
    }
    
    travel_overrides = {
        "carrier": (st.session_state.get("rcpt_travel_carrier", "") if st else ""),
        "flight": (st.session_state.get("rcpt_travel_flight", "") if st else ""),
        "seat": (st.session_state.get("rcpt_travel_seat", "") if st else ""),
        "fare": (st.session_state.get("rcpt_travel_fare", "") if st else ""),
        "from": (st.session_state.get("rcpt_travel_from", "") if st else ""),
        "to": (st.session_state.get("rcpt_travel_to", "") if st else ""),
        "autogen": bool(st.session_state.get("rcpt_travel_autogen", True)) if st else True,
    }
    
    meal_overrides = {
        "table": (st.session_state.get("rcpt_meal_table", "") if st else ""),
        "server": (st.session_state.get("rcpt_meal_server", "") if st else ""),
        "show_cashier": bool(st.session_state.get("rcpt_meal_show_cashier", True)) if st else True,
    }
    

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
        return f"APPROVED  AUTH {random.randint(100000,999999)}  REF {random.randint(1000,9999)}"

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
        elif expense_code == "E110":
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

    merchant = faker_instance.company()
    m_addr = faker_instance.address().replace("\n", ", ")
    m_phone = faker_instance.phone_number()
    cashier = faker_instance.first_name()

    try:
        line_item_date = datetime.datetime.strptime(expense_row["LINE_ITEM_DATE"], "%Y-%m-%d").date()
    except Exception:
        line_item_date = datetime.datetime.today().date()
    exp_code = str(expense_row.get("EXPENSE_CODE", "")).strip()
    desc = str(expense_row.get("DESCRIPTION","")).strip() or "Item"
    total_amount = float(expense_row.get("LINE_ITEM_TOTAL", 0.0))

    items = pick_items(exp_code, desc, total_amount)
    subtotal = round(sum(x[3] for x in items), 2)

    tax_rate = TAX_MAP.get(exp_code, 0.085 if subtotal>0 else 0.0)
    tax = round(subtotal * tax_rate, 2)

    tip = 0.0
    if exp_code in ("E111","E110"):
        target_total = total_amount
        tip_guess = 0.15 if exp_code=="E111" else 0.10
        tip = round(subtotal * tip_guess, 2)
        over = round((subtotal + tax + tip) - target_total, 2)
        if over > 0:
            tip = max(0.0, round(tip - over, 2))
        else:
            tip = round(tip + abs(over), 2)

    grand = round(subtotal + tax + tip, 2)
    drift = round(total_amount - grand, 2)
    if abs(drift) >= 0.01 and items:
        name, qty, unit, line_total = items[-1]
        line_total = round(line_total + drift, 2)
        unit = round(line_total / max(qty,1), 2)
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
    draw.text((40, y), f"Cashier: {cashier}", font=mono_font, fill=(90,90,90))
    y += 10
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

    policy = "Returns within 30 days with receipt. Items must be unused and in original packaging."
    for line in _tw.wrap(policy, width=70):
        draw.text((40, y), line, font=tiny_font, fill=(90,90,90))
        y += 20

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
    st.session_state.send_email = st.session_state.send_email_checkbox
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

sample_custom = pd.DataFrame({
    "TASK_CODE": ["L100"],
    "ACTIVITY_CODE": ["A101"],
    "DESCRIPTION": ["Legal Research: Analyze legal precedents"]
})
csv_custom = sample_custom.to_csv(index=False).encode('utf-8')
st.sidebar.download_button("Download Sample Custom Tasks CSV", csv_custom, "sample_custom_tasks.csv", "text/csv")

# Dynamic Tabs
tabs = ["Data Sources", "Invoice Details", "Fees & Expenses", "Output"]
# Email settings will live under the Output tab.
tab_objects = st.tabs(tabs)

with tab_objects[0]:
    st.markdown("<h3 style='color: #1E1E1E;'>Data Sources</h3>", unsafe_allow_html=True)
    uploaded_timekeeper_file = st.file_uploader("Upload Timekeeper CSV (tk_info.csv)", type="csv")
    timekeeper_data = _load_timekeepers(uploaded_timekeeper_file)

    use_custom_tasks = st.checkbox("Use Custom Line Item Details?", value=True)
    uploaded_custom_tasks_file = None
    if use_custom_tasks:
        uploaded_custom_tasks_file = st.file_uploader("Upload Custom Line Items CSV (custom_details.csv)", type="csv")
    
    task_activity_desc = CONFIG['DEFAULT_TASK_ACTIVITY_DESC']
    if use_custom_tasks and uploaded_custom_tasks_file:
        custom_tasks_data = _load_custom_task_activity_data(uploaded_custom_tasks_file)
        if custom_tasks_data:
            task_activity_desc = custom_tasks_data


with tab_objects[1]:
    st.markdown("<h2 style='color: #1E1E1E;'>Invoice Details</h2>", unsafe_allow_html=True)

    # ===== Billing Profiles =====
    st.markdown("<h3 style='color: #1E1E1E;'>Billing Profiles</h3>", unsafe_allow_html=True)
    env_names = [p[0] for p in BILLING_PROFILES]
    default_env = st.session_state.get("selected_env", env_names[0])
    if default_env not in env_names:
        default_env = env_names[0]
    selected_env = st.selectbox("Environment / Profile", env_names, index=env_names.index(default_env), key="selected_env")
    allow_override = st.checkbox("Override values for this invoice", value=False, help="When checked, you can type custom values without changing stored profiles.")

    prof_client_name, prof_client_id, prof_law_firm_name, prof_law_firm_id = get_profile(selected_env)

    # Side-by-side names
    c1, c2 = st.columns(2)
    with c1:
        client_name = st.text_input("Client Name", value=prof_client_name, disabled=not allow_override, key="client_name")
    with c2:
        law_firm_name = st.text_input("Law Firm Name", value=prof_law_firm_name, disabled=not allow_override, key="law_firm_name")

    c3, c4 = st.columns(2)
    with c3:
        client_id = st.text_input("Client ID", value=prof_client_id, disabled=not allow_override, key="client_id")
    with c4:
        law_firm_id = st.text_input("Law Firm ID", value=prof_law_firm_id, disabled=not allow_override, key="law_firm_id")

    # Status footer (always shows the stored profile values)
    status_html = f"""
    <div style="margin-top:0.25rem;font-size:0.92rem;color:#444">
      Using: <strong>{selected_env}</strong>
      &nbsp;—&nbsp; Client ID: <span style="color:#15803d">{prof_client_id}</span>
      &nbsp;•&nbsp; Law Firm ID: <span style="color:#15803d">{prof_law_firm_id}</span>
    </div>
    """
    st.markdown(status_html, unsafe_allow_html=True)

    # Other invoice details
    matter_number_base = st.text_input("Matter Number:", "2025-XXXXXX")
    invoice_number_base = st.text_input("Invoice Number (Base):", "2025MMM-XXXXXX")

    LEDES_OPTIONS = ["1998B", "XML 2.1"]
    ledes_version = st.selectbox(
        "LEDES Version:",
        LEDES_OPTIONS,
        key="ledes_version",
        help="XML 2.1 export is not implemented yet; please use 1998B."
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
    
    if timekeeper_data is None:
        st.error("Please upload a valid timekeeper CSV file to configure fee and expense settings.")
        fees = 0
        expenses = 0
    else:
        max_fees = _calculate_max_fees(timekeeper_data, billing_start_date, billing_end_date, 16)
        st.caption(f"Maximum fee lines allowed: {max_fees} (based on timekeepers and billing period)")
        fees = st.slider(
            "Number of Fee Line Items",
            min_value=1,
            max_value=max_fees,
            value=min(20, max_fees),
            format="%d"
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
                "Copying (E101) per-page rate ($)",
                min_value=0.05, max_value=1.50, value=0.24, step=0.01,
                key="copying_rate_e101",
                help="Per-page rate used for E101 Copying expenses."
            )
        st.caption("Number of expense line items to generate")
        expenses = st.slider(
            "Number of Expense Line Items",
            min_value=0,
            max_value=50,
            value=5,
            format="%d"
        )
    max_daily_hours = st.number_input("Max Daily Timekeeper Hours:", min_value=1, max_value=24, value=16, step=1)
    
    if spend_agent:
        st.markdown("<h3 style='color: #1E1E1E;'>Mandatory Items</h3>", unsafe_allow_html=True)
        selected_items = st.multiselect("Select Mandatory Items to Include", list(CONFIG['MANDATORY_ITEMS'].keys()), default=list(CONFIG['MANDATORY_ITEMS'].keys()))
    else:
        selected_items = []


with tab_objects[3]:
    st.markdown("<h2 style='color: #1E1E1E;'>Output</h2>", unsafe_allow_html=True)
 #1E1E1E;'>Output Settings</h3>", unsafe_allow_html=True)
    include_block_billed = st.checkbox("Include Block Billed Line Items", value=True)
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
if generate_receipts:
    receipt_tabs = st.tabs(["Receipt Settings"])
    with receipt_tabs[0]:
        st.caption("These settings affect only the generated sample receipts.")
        with st.expander("Global Style", expanded=False):
            st.slider(
                "Receipt scale (affects font sizes)",
                min_value=0.8, max_value=1.4, value=1.0, step=0.05,
                key="rcpt_scale"
            )
            st.slider(
                "Divider line weight",
                min_value=1, max_value=4, value=1, step=1,
                key="rcpt_line_weight"
            )
            st.checkbox(
                "Use dashed dividers",
                value=False,
                key="rcpt_dashed"
            )
        with st.expander("Footer Policy Visibility", expanded=False):
            st.checkbox("Show policy on Travel (E110)", value=True, key="rcpt_show_policy_travel")
            st.checkbox("Show policy on Meals (E111)", value=True, key="rcpt_show_policy_meal")
            st.checkbox("Show policy on Mileage (E109)", value=True, key="rcpt_show_policy_mileage")
            st.checkbox("Show policy on Supplies/Other (E124)", value=True, key="rcpt_show_policy_supplies")
            st.checkbox("Show policy on Other (generic)", value=True, key="rcpt_show_policy_generic")
        with st.expander("Travel Details (E110)", expanded=False):
            st.text_input("Carrier code (e.g., AA, UA)", value="", key="rcpt_travel_carrier")
            st.text_input("Flight number", value="", key="rcpt_travel_flight")
            st.text_input("Seat", value="", key="rcpt_travel_seat")
            st.text_input("Fare class", value="", key="rcpt_travel_fare")
            st.text_input("From (city)", value="", key="rcpt_travel_from")
            st.text_input("To (city)", value="", key="rcpt_travel_to")
            st.checkbox("Auto-generate blank travel fields", value=True, key="rcpt_travel_autogen")
        with st.expander("Meal Details (E111)", expanded=False):
            st.text_input("Table #", value="", key="rcpt_meal_table")
            st.text_input("Server ID", value="", key="rcpt_meal_server")
            st.checkbox("Include cashier line", value=True, key="rcpt_meal_show_cashier")



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
if combine_ledes and num_invoices <= 1:
    st.error("Cannot combine LEDES file if only one invoice is being generated.")
    is_valid_input = False
st.markdown("---")
generate_button = st.button("Generate Invoice(s)", disabled=not is_valid_input)

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
        combined_ledes_content = ""
        with st.status("Generating invoices...") as status:
            current_end_date = billing_end_date
            current_start_date = billing_start_date
            
            for i in range(num_invoices):
                if multiple_periods and i > 0:
                    current_end_date = current_start_date - datetime.timedelta(days=1)
                    current_start_date = current_end_date.replace(day=1)
                
                status.update(label=f"Generating Invoice {i+1}/{num_invoices} for period {current_start_date} to {current_end_date}")
                
                current_invoice_desc = descriptions[i] if multiple_periods and i < len(descriptions) else descriptions[0]
                fees_used = max(0, fees - (2 if spend_agent and selected_items else 0))
                expenses_used = max(0, expenses - (1 if spend_agent and 'Uber E110' in selected_items else 0))
                
                rows, total_amount = _generate_invoice_data(
                    fees_used, expenses_used, timekeeper_data, client_id, law_firm_id,
                    current_invoice_desc, current_start_date, current_end_date,
                    task_activity_desc, CONFIG['MAJOR_TASK_CODES'], max_daily_hours, include_block_billed, faker
                )
                if spend_agent:
                    rows = _ensure_mandatory_lines(rows, timekeeper_data, current_invoice_desc, client_id, law_firm_id, current_start_date, current_end_date, selected_items)
                
                df_invoice = pd.DataFrame(rows)
                current_invoice_number = f"{invoice_number_base}-{i+1}"
                current_matter_number = matter_number_base
                
                is_first = (i == 0) and combine_ledes
                ledes_content_part = _create_ledes_1998b_content(df_invoice.to_dict(orient='records'), total_amount, current_start_date, current_end_date, current_invoice_number, current_matter_number, is_first_invoice=not combine_ledes or is_first)
                
                if combine_ledes:
                    combined_ledes_content += ledes_content_part + "\n"
                else:
                    ledes_filename = f"LEDES_1998B_{current_invoice_number}.txt"
                    attachments_list.append((ledes_filename, ledes_content_part.encode('utf-8')))
                
                if include_pdf:
                    use_custom_logo = st.session_state.get('use_custom_logo_checkbox', False)
                    logo_bytes = _get_logo_bytes(uploaded_logo, law_firm_id, use_custom_logo)
                    pdf_buffer = _create_pdf_invoice(df_invoice, total_amount, current_invoice_number, current_end_date, current_start_date, current_end_date, client_id, law_firm_id, logo_bytes, include_logo, client_name, law_firm_name)
                    pdf_filename = f"Invoice_{current_invoice_number}.pdf"
                    attachments_list.append((pdf_filename, pdf_buffer.getvalue()))
                
                if generate_receipts:
                    for row in rows:
                        if row.get("EXPENSE_CODE") and row.get("EXPENSE_CODE") != "E101":  # Exclude Copying (E101)
                            receipt_filename, receipt_data_buf = _create_receipt_image(row, faker)
                            if receipt_data_buf:
                                attachments_list.append((receipt_filename, receipt_data_buf.getvalue()))

            # Final download/email logic
            if st.session_state.send_email:
                subject, body = _customize_email_body(current_matter_number, f"{invoice_number_base}-Combined" if combine_ledes else f"{current_invoice_number}")
                
                if combine_ledes:
                    attachments_to_send = [("LEDES_Combined.txt", combined_ledes_content.encode('utf-8'))]
                    attachments_to_send.extend([item for item in attachments_list if item[0].endswith(".pdf") or item[0].endswith(".png")])
                    if not _send_email_with_attachment(recipient_email, subject, body, attachments_to_send):
                        st.subheader("Invoice(s) Failed to Email - Download below:")
                        for filename, data in attachments_to_send:
                            st.download_button(label=f"Download {filename}", data=data, file_name=filename, mime="text/plain" if filename.endswith(".txt") else ("application/pdf" if filename.endswith(".pdf") else "image/png"), key=f"download_failed_{filename}")
                else:
                    if not _send_email_with_attachment(recipient_email, subject, body, attachments_list):
                        st.subheader("Invoice(s) Failed to Email - Download below:")
                        for filename, data in attachments_list:
                            st.download_button(label=f"Download {filename}", data=data, file_name=filename, mime="text/plain" if filename.endswith(".txt") else ("application/pdf" if filename.endswith(".pdf") else "image/png"), key=f"download_failed_{filename}")
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
                    pdf_and_receipt_attachments = [item for item in attachments_list if item[0].endswith(".pdf") or item[0].endswith(".png")]
                    if pdf_and_receipt_attachments:
                        zip_buf = io.BytesIO()
                        with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                            for filename, data in pdf_and_receipt_attachments:
                                zip_file.writestr(filename, data)
                        zip_buf.seek(0)
                        st.download_button(
                            label="Download All PDF Invoices & Receipts as ZIP",
                            data=zip_buf.getvalue(),
                            file_name="invoices_and_receipts.zip",
                            mime="application/zip",
                            key="download_pdf_zip"
                        )
                elif num_invoices > 1:
                    zip_buf = io.BytesIO()
                    with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                        for filename, data in attachments_list:
                            zip_file.writestr(filename, data)
                    zip_buf.seek(0)
                    st.download_button(
                        label="Download All Invoices as ZIP",
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
                            mime="text/plain" if filename.endswith(".txt") else ("application/pdf" if filename.endswith(".pdf") else "image/png"),
                            key=f"download_{filename}"
                        )
            status.update(label="Invoice generation complete!", state="complete")
