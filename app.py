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
    'FARE_CLASSES': {
        'F': 'First Class',
        'J': 'Business Class',
        'Y': 'Economy/Coach Class',
        'W': 'Premium Economy',
        'P': 'Premium First',
        'A': 'First Class Discounted',
        'C': 'Business Class',
        'D': 'Business Class Discounted',
        'I': 'Business Class Discounted',
        'Z': 'Business Class Discounted',
        'S': 'Economy/Coach Class',
        'T': 'Economy/Coach Class',
        'V': 'Economy/Coach Class',
        'L': 'Economy/Coach Class',
        'K': 'Economy/Coach Class',
        'H': 'Economy/Coach Class',
        'Q': 'Economy/Coach Class',
        'M': 'Economy/Coach Class',
        'E': 'Economy/Coach Class',
        'U': 'Economy/Coach Class',
        'G': 'Economy/Coach Class',
        'B': 'Economy/Coach Class',
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
            'desc': "Partner-level review and organization of case files, tasks typically handled by a paralegal.",
            'tk_name': "Tom Delaganis",
            'task': "L350",
            'activity': "A109",
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
    fare_classes = CONFIG.get('FARE_CLASSES', {})
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
                fare_class_code = st.session_state.get('airfare_fare_class', 'Y') # Default to Economy
                fare_class_name = fare_classes.get(fare_class_code, 'Unknown')

                trip_type = " (Roundtrip)" if is_roundtrip else ""
                description = f"Airfare: {fare_class_name}, {airline} {flight_num}, {dep_city} to {arr_city}{trip_type}"
                
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
                        "fare_class": fare_class_code
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
    logo_bytes: bytes | None = None,
    include_logo: bool = False,
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
    totals_style_amt = ParagraphStyle('TotalsAmt', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11, alignment=TA_RIGHT)

    totals_data = [
        [Paragraph("Total Fees:", totals_style_label), Paragraph(f"${fees_total:,.2f}", totals_style_amt)],
        [Paragraph("Total Expenses:", totals_style_label), Paragraph(f"${expenses_total:,.2f}", totals_style_amt)],
        [Paragraph("Invoice Total:", totals_style_label), Paragraph(f"${total_amount:,.2f}", totals_style_amt)],
    ]
    totals_table = Table(totals_data, colWidths=[4 * inch, 3.5 * inch])
    totals_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
    ]))
    elements.append(totals_table)

    doc.build(elements)
    buffer.seek(0)
    return buffer

def _create_image_receipt(item_desc: str, item_amount: float) -> io.BytesIO:
    """Create a simple image receipt."""
    img_size = (400, 200)
    img = PILImage.new('RGB', img_size, color = 'white')
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 15)
    except IOError:
        font = ImageFont.load_default()
    
    text_color = "black"
    draw.text((20, 20), "Receipt", fill=text_color, font=font)
    draw.text((20, 50), f"Item: {item_desc}", fill=text_color, font=font)
    draw.text((20, 80), f"Amount: ${item_amount:.2f}", fill=text_color, font=font)
    draw.text((20, 110), f"Date: {datetime.date.today().strftime('%Y-%m-%d')}", fill=text_color, font=font)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf

# ===============================
# Streamlit UI
# ===============================
st.set_page_config(layout="wide")
st.title("Invoice Generator for Billing Systems")

st.markdown("""
This app generates mock invoices for testing billing systems.
""")

col1, col2 = st.columns(2)

with col1:
    st.header("Invoice Generation Settings")
    st.markdown("---")

    env_selection = st.selectbox(
        'Select Billing Profile',
        [p[0] for p in BILLING_PROFILES]
    )

    client_name, client_id, law_firm_name, law_firm_id = get_profile(env_selection)

    if env_selection == "Onit ELM":
        st.info("Using Onit ELM environment settings.")
    elif env_selection == "SimpleLegal":
        st.info("Using SimpleLegal environment settings.")
    elif env_selection == "Unity":
        st.info("Using Unity environment settings.")

    st.subheader("General Invoice Info")
    invoice_number = st.text_input("Invoice Number", value="INV-00123")
    invoice_desc = st.text_input("Invoice Description", value=CONFIG['DEFAULT_INVOICE_DESCRIPTION'])
    st.session_state['invoice_desc'] = invoice_desc

    invoice_date = st.date_input("Invoice Date", datetime.date.today())

    billing_col1, billing_col2 = st.columns(2)
    with billing_col1:
        billing_start_date = st.date_input("Billing Start Date", datetime.date.today() - datetime.timedelta(days=30))
    with billing_col2:
        billing_end_date = st.date_input("Billing End Date", datetime.date.today() - datetime.timedelta(days=1))

    num_invoices = st.number_input("Number of Invoices", min_value=1, max_value=5, value=1)
    
    col_fees, col_expenses = st.columns(2)
    with col_fees:
        num_fee_lines = st.number_input("Number of Fee Lines per Invoice", min_value=1, value=5)
    with col_expenses:
        num_expense_lines = st.number_input("Number of Expense Lines per Invoice", min_value=0, value=2)

    timekeeper_file = st.file_uploader("Upload Timekeeper CSV", type=['csv'])
    custom_tasks_file = st.file_uploader("Upload Custom Task/Activity CSV", type=['csv'])

    generate_ledes = st.checkbox("Generate LEDES 1998B", value=True)
    generate_pdf = st.checkbox("Generate PDF Invoice", value=True)
    generate_receipts = st.checkbox("Generate Receipts", value=False)
    zip_receipts = st.checkbox("Zip Receipts", value=False, disabled=not generate_receipts, help="Provides receipts as a single ZIP file for easy emailing.")

    col_logos, col_block = st.columns(2)
    with col_logos:
        include_logo_pdf = st.checkbox("Include Law Firm Logo in PDF", value=False)
        custom_logo = st.file_uploader("Upload Custom Logo (JPEG/PNG)", type=['jpeg', 'png'], disabled=not include_logo_pdf)
    with col_block:
        include_block_billed = st.checkbox("Include Block Billed Item", value=False)

    st.subheader("Tunable Expenses (E109, E110, E105)")
    mileage_rate_e109 = st.slider("Mileage Rate (E109)", min_value=0.5, max_value=1.0, value=0.65, step=0.01)
    st.session_state["mileage_rate_e109"] = mileage_rate_e109
    
    copying_rate_e101 = st.slider("Copying Rate per Page (E101)", min_value=0.1, max_value=0.5, value=0.24, step=0.01)
    st.session_state["copying_rate_e101"] = copying_rate_e101

    travel_range_e110 = st.slider("Out-of-Town Travel Range (E110)", min_value=50, max_value=1500, value=(100, 800))
    st.session_state["travel_range_e110"] = travel_range_e110
    
    telephone_range_e105 = st.slider("Telephone Range (E105)", min_value=1, max_value=100, value=(5, 15))
    st.session_state["telephone_range_e105"] = telephone_range_e105


with col2:
    st.header("Mandatory Line Items")
    st.markdown("---")
    
    st.subheader("Mandatory Items")
    mandatory_items = st.multiselect(
        "Select Mandatory Line Items to Include:",
        options=list(CONFIG['MANDATORY_ITEMS'].keys())
    )
    
    for item_name in mandatory_items:
        if item_name == 'Airfare E110':
            with st.expander("Airfare Details"):
                st.session_state['airfare_airline'] = st.text_input("Airline", value="Southwest", key="airline_input")
                st.session_state['airfare_flight_number'] = st.text_input("Flight Number", value="WN 1234", key="flight_num_input")
                st.session_state['airfare_departure_city'] = st.text_input("Departure City", value="HOU", key="dep_city_input")
                st.session_state['airfare_arrival_city'] = st.text_input("Arrival City", value="DAL", key="arr_city_input")
                st.session_state['airfare_roundtrip'] = st.checkbox("Roundtrip", value=True, key="roundtrip_input")
                
                fare_class_options = list(CONFIG['FARE_CLASSES'].keys())
                fare_class_display = [f"{code} ({name})" for code, name in CONFIG['FARE_CLASSES'].items()]
                
                selected_fare_class_display = st.selectbox(
                    "Fare Class",
                    options=fare_class_display,
                    help="Select the fare class. Common fare codes: Y (Economy), J (Business), F (First).",
                    key="fare_class_selectbox"
                )
                
                # Extract the code from the selected string
                selected_fare_class_code = selected_fare_class_display.split(' ')[0]
                st.session_state['airfare_fare_class'] = selected_fare_class_code

                st.session_state['airfare_amount'] = st.number_input("Amount", min_value=0.0, value=250.0, step=1.0, key="airfare_amount_input")
        elif item_name == 'Uber E110':
            with st.expander("Uber Details"):
                st.session_state['uber_amount'] = st.number_input("Amount", min_value=0.0, value=25.0, step=1.0, key="uber_amount_input")

    st.markdown("---")
    if st.button("Generate Invoices"):
        status = st.status("Generating invoices...", expanded=True)
        status.update(label="Loading timekeepers...", state="running")
        timekeeper_data = _load_timekeepers(timekeeper_file)
        custom_tasks_data = _load_custom_task_activity_data(custom_tasks_file)
        if custom_tasks_data is not None:
            task_activity_desc = custom_tasks_data
        else:
            task_activity_desc = CONFIG['DEFAULT_TASK_ACTIVITY_DESC']
            
        if not timekeeper_data:
            st.error("Timekeeper data is required to generate fee lines. Please upload a valid CSV.")
            status.update(label="Failed to generate invoices.", state="error")
            st.stop()

        faker = Faker()
        attachments_list = []
        
        status.update(label="Generating invoice data...", state="running")
        
        for i in range(1, num_invoices + 1):
            invoice_num_str = f"{invoice_number}-{str(i).zfill(2)}"
            matter_number = f"MATTER-{str(i).zfill(2)}"
            
            # Generate primary invoice data
            invoice_rows, total_amount = _generate_invoice_data(
                num_fee_lines, num_expense_lines, timekeeper_data, client_id, law_firm_id,
                invoice_desc, billing_start_date, billing_end_date, task_activity_desc,
                CONFIG['MAJOR_TASK_CODES'], st.session_state.get("max_hours_per_tk_per_day", 8),
                include_block_billed, faker
            )

            # Add mandatory lines if selected
            if mandatory_items:
                mandatory_rows = _ensure_mandatory_lines(
                    [], timekeeper_data, invoice_desc, client_id, law_firm_id,
                    billing_start_date, billing_end_date, mandatory_items
                )
                invoice_rows.extend(mandatory_rows)
                total_amount = sum(float(row["LINE_ITEM_TOTAL"]) for row in invoice_rows)
            
            df_invoice = pd.DataFrame(invoice_rows)
            
            if generate_pdf:
                status.update(label=f"Creating PDF for {invoice_num_str}...", state="running")
                logo_bytes = _get_logo_bytes(custom_logo, law_firm_id, include_logo_pdf)
                pdf_bytes = _create_pdf_invoice(df_invoice, total_amount, invoice_num_str, invoice_date,
                                                 billing_start_date, billing_end_date, client_id,
                                                 law_firm_id, logo_bytes, include_logo_pdf, client_name,
                                                 law_firm_name)
                attachments_list.append((f"{invoice_num_str}.pdf", pdf_bytes.getvalue()))
                
            if generate_ledes:
                status.update(label=f"Creating LEDES file for {invoice_num_str}...", state="running")
                ledes_content = _create_ledes_1998b_content(invoice_rows, total_amount, billing_start_date,
                                                            billing_end_date, invoice_num_str, matter_number,
                                                            is_first_invoice=True)
                attachments_list.append((f"{invoice_num_str}.txt", ledes_content.encode('utf-8')))

            if generate_receipts and any(r.get("airfare_details") or "Uber" in r.get("DESCRIPTION", "") for r in invoice_rows):
                status.update(label=f"Creating receipts for {invoice_num_str}...", state="running")
                for row in invoice_rows:
                    if row.get("airfare_details"):
                        receipt_bytes = _create_image_receipt("Airfare", float(row["LINE_ITEM_TOTAL"]))
                        attachments_list.append((f"{invoice_num_str}-AirfareReceipt.png", receipt_bytes.getvalue()))
                    if "Uber" in row.get("DESCRIPTION", ""):
                        receipt_bytes = _create_image_receipt("Uber", float(row["LINE_ITEM_TOTAL"]))
                        attachments_list.append((f"{invoice_num_str}-UberReceipt.png", receipt_bytes.getvalue()))

        st.subheader("Download Files")
        if not attachments_list:
            st.warning("No files were generated based on your selections.")
        else:
            if generate_pdf and generate_ledes and generate_receipts and zip_receipts:
                zip_buf = io.BytesIO()
                with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                    for filename, data in attachments_list:
                        zip_file.writestr(filename, data)
                zip_buf.seek(0)
                st.download_button(
                    label="Download Invoices and Receipts as ZIP",
                    data=zip_buf.getvalue(),
                    file_name="invoices_and_receipts.zip",
                    mime="application/zip",
                    key="download_pdf_zip"
                )
            elif generate_receipts and zip_receipts:
                receipt_list = [item for item in attachments_list if "Receipt" in item[0]]
                if receipt_list:
                    zip_buf = io.BytesIO()
                    with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                        for filename, data in receipt_list:
                            zip_file.writestr(filename, data)
                    zip_buf.seek(0)
                    st.download_button(
                        label="Download Receipts as ZIP",
                        data=zip_buf.getvalue(),
                        file_name="receipts.zip",
                        mime="application/zip",
                        key="download_receipts_zip"
                    )
                else:
                    st.warning("No receipts were generated to zip.")
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
