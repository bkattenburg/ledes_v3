
# app-merged-biv2-tabs.py
# Streamlit app merging LEDES 1998B and LEDES 1998BI V2 functionality
# Tabs-based GUI (polished labels), expanders with help/info (expanded by default),
# required field indicators, conditional BIv2 inputs, PDF/LEDES logic, mandatory items, and block billing.

import streamlit as st
import pandas as pd
import random
import datetime
import io
import logging
import re
from typing import Optional, List, Dict, Any, Tuple
from faker import Faker
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch

# --- App Setup ---
st.set_page_config(page_title="LEDES 1998B / 1998BI V2 Invoice Generator", layout="wide")
logging.basicConfig(level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')
faker = Faker()

# --- Presets Configuration ---
PRESETS = {
    "Custom": {"fees": 20, "expenses": 5},
    "Small": {"fees": 10, "expenses": 5},
    "Medium": {"fees": 25, "expenses": 15},
    "Large": {"fees": 100, "expenses": 25},
}

# --- Billing Profiles ---
BILLING_PROFILES = [
    ("Onit ELM",    "A Onit Inc.",   "02-4388252", "Nelson & Murdock", "02-1234567"),
    ("SimpleLegal", "Penguin LLC",   "C004",       "JDL",               "JDL001"),
    ("Unity",       "Unity Demo",    "uniti-demo", "Gold USD",          "Gold USD"),
]

def get_profile(env: str):
    for p in BILLING_PROFILES:
        if p[0] == env:
            return (p[1], p[2], p[3], p[4])
    p = BILLING_PROFILES[0]
    return (p[1], p[2], p[3], p[4])

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
            'requires_details': True
        },
        'Airfare E110': {
            'desc': "Airfare",
            'expense_code': "E110",
            'is_expense': True,
            'requires_details': True
        },
    }
}

EXPENSE_DESCRIPTIONS = list(CONFIG['EXPENSE_CODES'].keys())
OTHER_EXPENSE_DESCRIPTIONS = [d for d in EXPENSE_DESCRIPTIONS if CONFIG['EXPENSE_CODES'][d] != "E101"]

# ----------------------
# Helper functions
# ----------------------

def _find_timekeeper_by_name(timekeepers: List[Dict], name: str) -> Optional[Dict]:
    if not timekeepers:
        return None
    for tk in timekeepers:
        if str(tk.get("TIMEKEEPER_NAME", "")).strip().lower() == str(name).strip().lower():
            return tk
    return None

def _force_timekeeper_on_row(row: Dict, forced_name: str, timekeepers: List[Dict], tax_rate: float) -> Optional[Dict]:
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
    pattern = r"\b(\d{2}/\d{2}/\d{4})\b"
    if re.search(pattern, description):
        days_ago = random.randint(15, 90)
        new_date = (datetime.date.today() - datetime.timedelta(days=days_ago)).strftime("%m/%d/%Y")
        description = re.sub(pattern, new_date, description)
    description = description.replace("{NAME_PLACEHOLDER}", faker_instance.name())
    return description

def _load_timekeepers(uploaded_file) -> Optional[List[Dict]]:
    if uploaded_file is None:
        return None
    try:
        df = pd.read_csv(uploaded_file)
        required = ["TIMEKEEPER_NAME", "TIMEKEEPER_CLASSIFICATION", "TIMEKEEPER_ID", "RATE"]
        if not all(c in df.columns for c in required):
            st.error(f"Timekeeper CSV must contain: {', '.join(required)}")
            return None
        return df.to_dict(orient='records')
    except Exception as e:
        st.error(f"Error loading timekeeper file: {e}")
        logging.error(f"Timekeeper load error: {e}")
        return None

def _load_custom_task_activity_data(uploaded_file) -> Optional[List[Tuple[str, str, str]]]:
    if uploaded_file is None:
        return None
    try:
        df = pd.read_csv(uploaded_file)
        required = ["TASK_CODE", "ACTIVITY_CODE", "DESCRIPTION"]
        if not all(c in df.columns for c in required):
            st.error(f"Custom Task/Activity CSV must contain: {', '.join(required)}")
            return None
        if df.empty:
            st.warning("Custom Task/Activity CSV is empty.")
            return []
        return [(str(r["TASK_CODE"]), str(r["ACTIVITY_CODE"]), str(r["DESCRIPTION"])) for _, r in df.iterrows()]
    except Exception as e:
        st.error(f"Error loading custom tasks file: {e}")
        logging.error(f"Custom tasks load error: {e}")
        return None

# ----------------------
# LEDES Generators
# ----------------------

def _create_ledes_line_1998b(row: Dict, line_no: int, inv_total: float, bill_start: datetime.date, bill_end: datetime.date, invoice_number: str, matter_number: str) -> List[str]:
    try:
        date_obj = datetime.datetime.strptime(row["LINE_ITEM_DATE"], "%Y-%m-%d").date()
        hours = float(row.get("HOURS", 0.0))
        rate = float(row.get("RATE", 0.0))
        line_total = float(row["LINE_ITEM_TOTAL"])
        is_expense = bool(row.get("EXPENSE_CODE"))
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
        logging.error(f"Error creating LEDES 1998B line: {e}")
        return []

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
        line = _create_ledes_line_1998b(row, i, inv_total, bill_start, bill_end, invoice_number, matter_number)
        if line:
            lines.append("|".join(map(str, line)) + "[]")
    return "\n".join(lines)

# ----- 1998BI V2 -----

def _create_ledes_line_1998biv2(row: Dict, line_no: int, bill_start: datetime.date, bill_end: datetime.date,
                                invoice_number: str, matter_number: str, invoice_currency: str,
                                matter_name: str, po_number: str, client_matter_id: str, tax_type: str = "VAT") -> List[str]:
    try:
        date_obj = datetime.datetime.strptime(row["LINE_ITEM_DATE"], "%Y-%m-%d").date()
        hours = float(row.get("HOURS", 0.0))
        rate = float(row.get("RATE", 0.0))
        line_total_excl_tax = float(row["LINE_ITEM_TOTAL"])
        tax_amount = float(row.get("TAX_AMOUNT", 0.0))
        tax_rate = float(row.get("TAX_RATE", 0.0))
        line_total_incl_tax = line_total_excl_tax + tax_amount
        is_expense = bool(row.get("EXPENSE_CODE"))
        adj_type = "E" if is_expense else "F"

        return [
            bill_end.strftime("%Y%m%d"),                       # INVOICE_DATE
            invoice_number,                                    # INVOICE_NUMBER
            str(row.get("CLIENT_ID", "")),                     # CLIENT_ID
            str(row.get("LAW_FIRM_ID", "")),                   # LAW_FIRM_ID
            matter_number,                                     # LAW_FIRM_MATTER_ID
            str(client_matter_id or ""),                       # CLIENT_MATTER_ID
            matter_name,                                       # MATTER_NAME
            po_number,                                         # PO_NUMBER
            str(row.get("INVOICE_DESCRIPTION", "")),           # INVOICE_DESCRIPTION
            invoice_currency,                                  # INVOICE_CURRENCY
            f"{row.get('INVOICE_NET_TOTAL', 0.0):.2f}",        # INVOICE_NET_TOTAL
            f"{row.get('INVOICE_TAX_TOTAL', 0.0):.2f}",        # INVOICE_TAX_TOTAL
            f"{row.get('INVOICE_TOTAL', 0.0):.2f}",            # INVOICE_TOTAL
            f"{row.get('INVOICE_REPORTED_TAX_TOTAL', 0.0):.2f}", # INVOICE_REPORTED_TAX_TOTAL
            invoice_currency,                                  # INVOICE_TAX_CURRENCY
            str(line_no),                                      # LINE_ITEM_NUMBER
            adj_type,                                          # EXP/FEE/INV_ADJ_TYPE
            f"{hours:.1f}" if adj_type == "F" else f"{int(hours)}", # LINE_ITEM_NUMBER_OF_UNITS
            f"{rate:.2f}",                                     # LINE_ITEM_UNIT_COST
            "0.00",                                            # LINE_ITEM_ADJUSTMENT_AMOUNT
            f"{line_total_excl_tax:.2f}",                      # LINE_ITEM_TOTAL
            f"{tax_rate:.4f}",                                 # LINE_ITEM_TAX_RATE
            f"{tax_amount:.2f}",                               # LINE_ITEM_TAX_TOTAL
            f"{line_total_incl_tax:.2f}",                      # LINE_ITEM_TOTAL_INCL_TAX
            str(row.get("LINE_ITEM_TAX_TYPE", tax_type)),      # LINE_ITEM_TAX_TYPE
            date_obj.strftime("%Y%m%d"),                       # LINE_ITEM_DATE
            row.get("TASK_CODE", ""),                          # LINE_ITEM_TASK_CODE
            row.get("ACTIVITY_CODE", ""),                      # LINE_ITEM_ACTIVITY_CODE
            row.get("EXPENSE_CODE", ""),                       # LINE_ITEM_EXPENSE_CODE
            row.get("TIMEKEEPER_ID", ""),                      # TIMEKEEPER_ID
            row.get("TIMEKEEPER_NAME", ""),                    # TIMEKEEPER_NAME
            row.get("TIMEKEEPER_CLASSIFICATION", ""),          # TIMEKEEPER_CLASSIFICATION
        ]
    except Exception as e:
        logging.error(f"Error creating LEDES 1998BI V2 line: {e}")
        return []

def _create_ledes_1998biv2_content(rows: List[Dict], bill_start: datetime.date, bill_end: datetime.date,
                                   invoice_number: str, matter_number: str, invoice_currency: str,
                                   matter_name: str, po_number: str, client_matter_id: str, tax_type: str = "VAT") -> str:
    header = "LEDES1998BI V2[]"
    fields = ("INVOICE_DATE|INVOICE_NUMBER|CLIENT_ID|LAW_FIRM_ID|LAW_FIRM_MATTER_ID|CLIENT_MATTER_ID|"
              "MATTER_NAME|PO_NUMBER|INVOICE_DESCRIPTION|INVOICE_CURRENCY|INVOICE_NET_TOTAL|"
              "INVOICE_TAX_TOTAL|INVOICE_TOTAL|INVOICE_REPORTED_TAX_TOTAL|INVOICE_TAX_CURRENCY|"
              "LINE_ITEM_NUMBER|EXP/FEE/INV_ADJ_TYPE|LINE_ITEM_NUMBER_OF_UNITS|LINE_ITEM_UNIT_COST|"
              "LINE_ITEM_ADJUSTMENT_AMOUNT|LINE_ITEM_TOTAL|LINE_ITEM_TAX_RATE|LINE_ITEM_TAX_TOTAL|"
              "LINE_ITEM_TOTAL_INCL_TAX|LINE_ITEM_TAX_TYPE|LINE_ITEM_DATE|LINE_ITEM_TASK_CODE|"
              "LINE_ITEM_ACTIVITY_CODE|LINE_ITEM_EXPENSE_CODE|TIMEKEEPER_ID|TIMEKEEPER_NAME|"
              "TIMEKEEPER_CLASSIFICATION[]")

    total_excl_tax = sum(float(row.get("LINE_ITEM_TOTAL", 0.0)) for row in rows)
    total_tax = sum(float(row.get("TAX_AMOUNT", 0.0)) for row in rows)
    total_incl_tax = total_excl_tax + total_tax

    for row in rows:
        row["INVOICE_NET_TOTAL"] = total_excl_tax
        row["INVOICE_TAX_TOTAL"] = total_tax
        row["INVOICE_TOTAL"] = total_incl_tax
        row["INVOICE_REPORTED_TAX_TOTAL"] = total_tax

    lines = [header, fields]
    for i, row in enumerate(rows, start=1):
        line = _create_ledes_line_1998biv2(row, i, bill_start, bill_end,
                                           invoice_number, matter_number, invoice_currency,
                                           matter_name, po_number, client_matter_id, tax_type=tax_type)
        if line:
            lines.append("|".join(map(str, line)) + "[]")
    return "\n".join(lines)

# ----------------------
# Data generation
# ----------------------

def _generate_fees(fee_count: int, timekeeper_data: List[Dict], billing_start_date: datetime.date, billing_end_date: datetime.date,
                   task_activity_desc: List[Tuple[str, str, str]], major_task_codes: set, max_hours_per_tk_per_day: int,
                   faker_instance: Faker, client_id: str, law_firm_id: str, invoice_desc: str, tax_rate: float) -> List[Dict]:
    rows = []
    delta = billing_end_date - billing_start_date
    num_days = max(1, delta.days + 1)
    major_items = [item for item in task_activity_desc if item[0] in major_task_codes]
    other_items = [item for item in task_activity_desc if item[0] not in major_task_codes]
    daily_hours_tracker = {}
    for _ in range(fee_count):
        if not timekeeper_data or not task_activity_desc:
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
        key = (line_item_date_str, timekeeper_id)
        current_billed_hours = daily_hours_tracker.get(key, 0.0)
        remaining = max_hours_per_tk_per_day - current_billed_hours
        if remaining <= 0:
            continue
        hours_to_bill = round(random.uniform(0.5, min(8.0, remaining)), 1)
        if hours_to_bill == 0:
            continue
        hourly_rate = float(tk_row["RATE"])
        line_item_total = round(hours_to_bill * hourly_rate, 2)
        tax_amount = round(line_item_total * tax_rate, 2)
        daily_hours_tracker[key] = current_billed_hours + hours_to_bill
        description = _process_description(description, faker_instance)
        rows.append({
            "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id,
            "LINE_ITEM_DATE": line_item_date_str, "TIMEKEEPER_NAME": tk_row["TIMEKEEPER_NAME"],
            "TIMEKEEPER_CLASSIFICATION": tk_row["TIMEKEEPER_CLASSIFICATION"],
            "TIMEKEEPER_ID": timekeeper_id, "TASK_CODE": task_code,
            "ACTIVITY_CODE": activity_code, "EXPENSE_CODE": "", "DESCRIPTION": description,
            "HOURS": hours_to_bill, "RATE": hourly_rate, "LINE_ITEM_TOTAL": line_item_total,
            "TAX_RATE": tax_rate, "TAX_AMOUNT": tax_amount
        })
    return rows

def _generate_expenses(expense_count: int, billing_start_date: datetime.date, billing_end_date: datetime.date,
                       client_id: str, law_firm_id: str, invoice_desc: str, tax_rate: float) -> List[Dict]:
    rows = []
    delta = billing_end_date - billing_start_date
    num_days = max(1, delta.days + 1)
    mileage_rate_cfg = float(st.session_state.get("mileage_rate_e109", 0.65))
    travel_rng = st.session_state.get("travel_range_e110", (100.0, 800.0))
    tel_rng = st.session_state.get("telephone_range_e105", (5.0, 15.0))
    copying_rate = float(st.session_state.get("copying_rate_e101", 0.24))
    travel_min, travel_max = float(travel_rng[0]), float(travel_rng[1])
    tel_min, tel_max = float(tel_rng[0]), float(tel_rng[1])

    # Always include some Copying (E101) if any expenses
    e101_actual_count = random.randint(1, min(3, expense_count)) if expense_count > 0 else 0
    for _ in range(e101_actual_count):
        description = "Copying"
        expense_code = "E101"
        hours = random.randint(50, 300)  # number of pages
        rate = round(copying_rate, 2)    # per-page
        random_day_offset = random.randint(0, num_days - 1)
        line_item_date = billing_start_date + datetime.timedelta(days=random_day_offset)
        line_item_total = round(hours * rate, 2)
        tax_amount = round(line_item_total * tax_rate, 2)
        rows.append({
            "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id,
            "LINE_ITEM_DATE": line_item_date.strftime("%Y-%m-%d"), "TIMEKEEPER_NAME": "",
            "TIMEKEEPER_CLASSIFICATION": "", "TIMEKEEPER_ID": "",
            "TASK_CODE": "", "ACTIVITY_CODE": "", "EXPENSE_CODE": expense_code, "DESCRIPTION": description,
            "HOURS": hours, "RATE": rate, "LINE_ITEM_TOTAL": line_item_total,
            "TAX_RATE": tax_rate, "TAX_AMOUNT": tax_amount
        })

    for _ in range(max(0, expense_count - e101_actual_count)):
        description = random.choice(OTHER_EXPENSE_DESCRIPTIONS)
        expense_code = CONFIG['EXPENSE_CODES'][description]
        random_day_offset = random.randint(0, num_days - 1)
        line_item_date = billing_start_date + datetime.timedelta(days=random_day_offset)

        if expense_code == "E109":  # mileage
            miles = random.randint(5, 50)
            hours = miles
            rate = mileage_rate_cfg
            line_item_total = round(miles * rate, 2)
        elif expense_code == "E110":  # travel
            hours = 1
            rate = round(random.uniform(travel_min, travel_max), 2)
            line_item_total = rate
        elif expense_code == "E105":  # telephone
            hours = 1
            rate = round(random.uniform(tel_min, tel_max), 2)
            line_item_total = rate
        else:
            hours = random.randint(1, 5)
            rate = round(random.uniform(10.0, 150.0), 2)
            line_item_total = round(hours * rate, 2)

        tax_amount = round(line_item_total * tax_rate, 2)
        rows.append({
            "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id,
            "LINE_ITEM_DATE": line_item_date.strftime("%Y-%m-%d"), "TIMEKEEPER_NAME": "",
            "TIMEKEEPER_CLASSIFICATION": "", "TIMEKEEPER_ID": "",
            "TASK_CODE": "", "ACTIVITY_CODE": "", "EXPENSE_CODE": expense_code, "DESCRIPTION": description,
            "HOURS": hours, "RATE": rate, "LINE_ITEM_TOTAL": line_item_total,
            "TAX_RATE": tax_rate, "TAX_AMOUNT": tax_amount
        })
    return rows

def _ensure_mandatory_lines(rows: List[Dict], timekeeper_data: List[Dict], invoice_desc: str, client_id: str, law_firm_id: str,
                            billing_start_date: datetime.date, billing_end_date: datetime.date, selected_items: List[str],
                            tax_rate: float) -> Tuple[List[Dict], List[str]]:
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
                rows.append({
                    "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id,
                    "LINE_ITEM_DATE": line_item_date.strftime("%Y-%m-%d"), "TIMEKEEPER_NAME": "",
                    "TIMEKEEPER_CLASSIFICATION": "", "TIMEKEEPER_ID": "",
                    "TASK_CODE": "", "ACTIVITY_CODE": "", "EXPENSE_CODE": "E110", "DESCRIPTION": description,
                    "HOURS": 1, "RATE": amount, "LINE_ITEM_TOTAL": amount,
                    "TAX_RATE": tax_rate, "TAX_AMOUNT": tax_amount
                })
            elif item_name == 'Uber E110':
                amount = float(st.session_state.get('uber_amount', 0.0))
                description = item['desc']
                tax_amount = round(amount * tax_rate, 2)
                rows.append({
                    "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id,
                    "LINE_ITEM_DATE": line_item_date.strftime("%Y-%m-%d"), "TIMEKEEPER_NAME": "",
                    "TIMEKEEPER_CLASSIFICATION": "", "TIMEKEEPER_ID": "",
                    "TASK_CODE": "", "ACTIVITY_CODE": "", "EXPENSE_CODE": "E110", "DESCRIPTION": description,
                    "HOURS": 1, "RATE": amount, "LINE_ITEM_TOTAL": amount,
                    "TAX_RATE": tax_rate, "TAX_AMOUNT": tax_amount
                })
        elif item['is_expense']:
            hours = random.randint(1, 10)
            rate = round(random.uniform(5.0, 100.0), 2)
            total = round(hours * rate, 2)
            tax_amount = round(total * tax_rate, 2)
            rows.append({
                "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id,
                "LINE_ITEM_DATE": line_item_date.strftime("%Y-%m-%d"), "TIMEKEEPER_NAME": "",
                "TIMEKEEPER_CLASSIFICATION": "", "TIMEKEEPER_ID": "",
                "TASK_CODE": "", "ACTIVITY_CODE": "", "EXPENSE_CODE": item['expense_code'], "DESCRIPTION": item['desc'],
                "HOURS": hours, "RATE": rate, "LINE_ITEM_TOTAL": total,
                "TAX_RATE": tax_rate, "TAX_AMOUNT": tax_amount
            })
        else:
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

def _generate_invoice_data(fee_count: int, expense_count: int, timekeeper_data: List[Dict], client_id: str, law_firm_id: str,
                           invoice_desc: str, billing_start_date: datetime.date, billing_end_date: datetime.date,
                           task_activity_desc: List[Tuple[str, str, str]], major_task_codes: set,
                           max_hours_per_tk_per_day: int, include_block_billed: bool, faker_instance: Faker,
                           tax_rate: float, mandatory_items: List[str]) -> Tuple[List[Dict], float, float, float, List[str]]:
    rows: List[Dict] = []
    rows.extend(_generate_fees(fee_count, timekeeper_data, billing_start_date, billing_end_date, task_activity_desc,
                               major_task_codes, max_hours_per_tk_per_day, faker_instance, client_id, law_firm_id, invoice_desc, tax_rate))
    rows.extend(_generate_expenses(expense_count, billing_start_date, billing_end_date, client_id, law_firm_id, invoice_desc, tax_rate))

    # Optional: block billing consolidation (simple variant)
    if include_block_billed:
        from collections import defaultdict
        fee_rows = [r for r in rows if not r.get("EXPENSE_CODE")]
        daily_tk_groups = defaultdict(list)
        for r in fee_rows:
            key = (r["TIMEKEEPER_ID"], r["LINE_ITEM_DATE"])
            daily_tk_groups[key].append(r)
        candidates = [grp for grp in daily_tk_groups.values() if len(grp) > 1]
        if candidates:
            selected = random.choice(candidates)
            total_hours = sum(float(r["HOURS"]) for r in selected)
            total_amount = sum(float(r["LINE_ITEM_TOTAL"]) for r in selected)
            total_tax = sum(float(r.get("TAX_AMOUNT", 0.0)) for r in selected)
            descriptions = "; ".join(r["DESCRIPTION"] for r in selected)
            first = selected[0]
            block_row = {
                "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id,
                "LINE_ITEM_DATE": first["LINE_ITEM_DATE"], "TIMEKEEPER_NAME": first["TIMEKEEPER_NAME"],
                "TIMEKEEPER_CLASSIFICATION": first["TIMEKEEPER_CLASSIFICATION"], "TIMEKEEPER_ID": first["TIMEKEEPER_ID"],
                "TASK_CODE": first["TASK_CODE"], "ACTIVITY_CODE": first["ACTIVITY_CODE"], "EXPENSE_CODE": "",
                "DESCRIPTION": descriptions, "HOURS": round(total_hours, 1), "RATE": first["RATE"],
                "LINE_ITEM_TOTAL": round(total_amount, 2), "TAX_RATE": tax_rate, "TAX_AMOUNT": round(total_tax, 2)
            }
            ids_to_remove = {id(r) for r in selected}
            rows = [r for r in rows if id(r) not in ids_to_remove] + [block_row]

    # Mandatory lines
    if mandatory_items:
        rows, skipped = _ensure_mandatory_lines(rows, timekeeper_data, invoice_desc, client_id, law_firm_id,
                                                billing_start_date, billing_end_date, mandatory_items, tax_rate)
    else:
        skipped = []

    total_excl_tax = sum(float(r.get("LINE_ITEM_TOTAL", 0.0)) for r in rows)
    total_tax = sum(float(r.get("TAX_AMOUNT", 0.0)) for r in rows)
    total_incl_tax = total_excl_tax + total_tax
    return rows, total_excl_tax, total_tax, total_incl_tax, skipped

# ----------------------
# PDF generation
# ----------------------

def _create_pdf_invoice(
    df: pd.DataFrame,
    total_excl: float,
    total_tax: float,
    total_incl: float,
    invoice_number: str,
    invoice_date: datetime.date,
    billing_start_date: datetime.date,
    billing_end_date: datetime.date,
    client_id: str,
    law_firm_id: str,
    client_name: str = "",
    law_firm_name: str = "",
) -> io.BytesIO:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], alignment=TA_LEFT, fontSize=14, spaceAfter=8)
    meta_style = ParagraphStyle('Meta', parent=styles['Normal'], alignment=TA_LEFT, fontSize=9, spaceAfter=4)
    th = ParagraphStyle('TH', parent=styles['Normal'], alignment=TA_CENTER, fontSize=8, textColor=colors.white)
    td = ParagraphStyle('TD', parent=styles['Normal'], alignment=TA_LEFT, fontSize=8, leading=10, wordWrap='CJK')

    elements = []
    elements.append(Paragraph("Invoice", title_style))
    elements.append(Paragraph(f"Invoice #: <b>{invoice_number}</b>", meta_style))
    elements.append(Paragraph(f"Invoice Date: <b>{invoice_date.strftime('%Y-%m-%d')}</b>", meta_style))
    elements.append(Paragraph(f"Billing Period: <b>{billing_start_date.strftime('%Y-%m-%d')}</b> to <b>{billing_end_date.strftime('%Y-%m-%d')}</b>", meta_style))
    elements.append(Paragraph(f"Client: <b>{client_name or 'Client'}</b> ({client_id})", meta_style))
    elements.append(Paragraph(f"Law Firm: <b>{law_firm_name or 'Law Firm'}</b> ({law_firm_id})", meta_style))
    elements.append(Spacer(1, 6))

    data = [[
        Paragraph("Date", th),
        Paragraph("Type", th),
        Paragraph("Task", th),
        Paragraph("Act.", th),
        Paragraph("Exp.", th),
        Paragraph("Timekeeper", th),
        Paragraph("Description", th),
        Paragraph("Units", th),
        Paragraph("Rate", th),
        Paragraph("Tax", th),
        Paragraph("Total (excl)", th),
        Paragraph("Total (incl)", th),
    ]]

    for _, r in df.iterrows():
        is_expense = bool(r.get("EXPENSE_CODE"))
        typ = "Expense" if is_expense else "Fee"
        total_ex = float(r.get("LINE_ITEM_TOTAL", 0.0))
        tax = float(r.get("TAX_AMOUNT", 0.0))
        total_in = total_ex + tax
        desc = str(r.get("DESCRIPTION", ""))
        if len(desc) > 2000:
            desc = desc[:2000] + "…"
        data.append([
            Paragraph(str(r.get("LINE_ITEM_DATE", "")), td),
            Paragraph(typ, td),
            Paragraph(str(r.get("TASK_CODE", "")), td),
            Paragraph(str(r.get("ACTIVITY_CODE", "")), td),
            Paragraph(str(r.get("EXPENSE_CODE", "")), td),
            Paragraph(str(r.get("TIMEKEEPER_NAME", "")), td),
            Paragraph(desc, td),
            Paragraph(str(r.get("HOURS", "")), td),
            Paragraph(f"{float(r.get('RATE', 0.0)):.2f}", td),
            Paragraph(f"{tax:.2f}", td),
            Paragraph(f"{total_ex:.2f}", td),
            Paragraph(f"{total_in:.2f}", td),
        ])

    table = Table(
        data,
        colWidths=[0.7*inch, 0.7*inch, 0.6*inch, 0.5*inch, 0.6*inch, 1.1*inch, 2.6*inch, 0.55*inch, 0.7*inch, 0.7*inch, 0.9*inch, 0.9*inch]
    )
    table.hAlign = 'LEFT'
    table.repeatRows = 1
    table.splitByRow = 1
    table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#333333')),
        ('GRID', (0,0), (-1,-1), 0.25, colors.grey),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('ALIGN', (7,1), (11,-1), 'RIGHT'),
        ('LEFTPADDING', (0,0), (-1,-1), 4),
        ('RIGHTPADDING', (0,0), (-1,-1), 4),
        ('TOPPADDING', (0,0), (-1,-1), 2),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
    ]))

    elements.append(table)
    elements.append(Spacer(1, 8))
    elements.append(Paragraph(f"Subtotal (excl. tax): <b>{total_excl:.2f}</b>", meta_style))
    elements.append(Paragraph(f"Tax total: <b>{total_tax:.2f}</b>", meta_style))
    elements.append(Paragraph(f"Invoice total (incl. tax): <b>{total_incl:.2f}</b>", meta_style))

    doc.build(elements)
    buffer.seek(0)
    return buffer

# ----------------------
# UI Tabs (polished names)
# ----------------------

def main():
    st.title("LEDES 1998B & 1998BI V2 Invoice Generator (Tabbed)")

    tab1, tab2, tab3, tab4 = st.tabs([
        "Invoice & Billing", "Data Sources & Timekeepers", "Required Items", "Preview & Export"
    ])

    # ---------------- Invoice & Billing ----------------
    with tab1:
        with st.expander("Billing Party Details", expanded=True):
            st.info("Select billing environment and enter identifiers for invoice and matter.")
            env = st.selectbox("Environment *", [p[0] for p in BILLING_PROFILES], index=0)
            client_name, client_id, law_firm_name, law_firm_id = get_profile(env)
            format_choice = st.radio("LEDES Export Format *", ["1998B", "1998BI V2"], index=0)
            invoice_number = st.text_input("Invoice Number *", "INV-1001")
            matter_number = st.text_input("Law Firm Matter ID *", "MAT-2001")

            # BIv2-only
            matter_name = po_number = client_matter_id = invoice_currency = ""
            if format_choice == "1998BI V2":
                st.markdown("**BIv2 Fields**")
                matter_name = st.text_input("Matter Name *", "General Litigation")
                po_number = st.text_input("PO Number (optional)", "")
                client_matter_id = st.text_input("Client Matter ID (optional)", "")
                invoice_currency = st.text_input("Invoice Currency (ISO 4217) *", "USD")

        with st.expander("Invoice Period & Description", expanded=True):
            st.info("Set the billing period included on this invoice and a brief description.")
            today = datetime.date.today()
            start_date = st.date_input("Billing Start Date *", today.replace(day=1))
            end_date = st.date_input("Billing End Date *", today)
            invoice_desc = st.text_input("Invoice Description *", CONFIG['DEFAULT_INVOICE_DESCRIPTION'])

        with st.expander("Line Items & Options", expanded=True):
            st.info("Choose the number of fee and expense lines, hours per timekeeper per day, and optional block billing.")
            preset = st.selectbox("Preset", list(PRESETS.keys()), index=1)
            fee_count = st.slider("# Fee Lines", 0, 200, PRESETS[preset]["fees"])
            expense_count = st.slider("# Expense Lines", 0, 200, PRESETS[preset]["expenses"])
            max_daily_hours = st.slider("Max Hours per TK per Day", 1, 12, 8)
            include_block_billed = st.checkbox("Enable Block-Billed Consolidation", value=False)
            # Tax only relevant to BIv2
            tax_rate = 0.0
            if format_choice == "1998BI V2":
                tax_rate = st.number_input("Tax Rate (decimal)", min_value=0.0, max_value=1.0, value=0.0, step=0.01, format="%0.4f")

    # ---------------- Data Sources & Timekeepers ----------------
    with tab2:
        with st.expander("Upload Data Sources", expanded=True):
            st.info("Upload Timekeepers and/or custom Task/Activity CSVs to override defaults.")
            tk_file = st.file_uploader("Upload Timekeepers CSV", type=["csv"])
            task_file = st.file_uploader("Upload Custom Task/Activity CSV (optional)", type=["csv"])
            # Save for later steps
            st.session_state["__tk_file"] = tk_file
            st.session_state["__task_file"] = task_file

        with st.expander("Expense Tunables", expanded=True):
            st.info("Fine-tune expense generation parameters for E101, E105, E109, and E110.")
            st.session_state["copying_rate_e101"] = st.number_input("Copying Rate (E101) per page", 0.01, 5.0, 0.24, 0.01)
            st.session_state["mileage_rate_e109"] = st.number_input("Mileage Rate (E109) per mile", 0.01, 5.0, 0.65, 0.01)
            travel_min = st.number_input("Travel (E110) Min", 10.0, 5000.0, 100.0, 10.0)
            travel_max = st.number_input("Travel (E110) Max", 10.0, 5000.0, 800.0, 10.0)
            st.session_state["travel_range_e110"] = (travel_min, travel_max)
            tel_min = st.number_input("Telephone (E105) Min", 1.0, 100.0, 5.0, 1.0)
            tel_max = st.number_input("Telephone (E105) Max", 1.0, 100.0, 15.0, 1.0)
            st.session_state["telephone_range_e105"] = (tel_min, tel_max)

    # ---------------- Required Items ----------------
    with tab3:
        with st.expander("Select Mandatory Items", expanded=True):
            st.info("Add specific fee/expense items that must appear on this invoice.")
            mand_options = list(CONFIG['MANDATORY_ITEMS'].keys())
            selected_mandatory = st.multiselect("Include mandatory items", mand_options, default=[])

        if 'Airfare E110' in selected_mandatory:
            with st.expander("Airfare Details", expanded=True):
                st.session_state['airfare_airline'] = st.text_input("Airline", "Delta")
                st.session_state['airfare_flight_number'] = st.text_input("Flight #", "DL123")
                st.session_state['airfare_departure_city'] = st.text_input("Departure City", "SFO")
                st.session_state['airfare_arrival_city'] = st.text_input("Arrival City", "JFK")
                st.session_state['airfare_fare_class'] = st.selectbox("Fare Class", ["Economy/Coach", "Premium Economy", "Business", "First"], index=0)
                st.session_state['airfare_roundtrip'] = st.checkbox("Roundtrip", value=True)
                st.session_state['airfare_amount'] = st.number_input("Airfare Amount", 0.0, 20000.0, 650.00, 1.0)

        if 'Uber E110' in selected_mandatory:
            with st.expander("Uber Details", expanded=True):
                st.session_state['uber_amount'] = st.number_input("Uber Amount", 0.0, 2000.0, 35.00, 0.5)

        # Save for use later
        st.session_state["__mandatory"] = selected_mandatory

    # ---------------- Preview & Export ----------------
    
    # ---------------- Preview & Export ----------------
    with tab4:
        # Collapsible on-screen summary (standalone)
        with st.expander("Invoice Summary", expanded=True):
            fmt = "1998BI V2" if format_choice == "1998BI V2" else "1998B"
            rows = []
            rows.append(("Invoice Number", invoice_number))
            rows.append(("Law Firm Matter ID", matter_number))
            if fmt == "1998BI V2":
                rows.append(("Client Matter ID", client_matter_id or "—"))
                rows.append(("Matter Name", matter_name or "—"))
                rows.append(("Currency", (invoice_currency or "USD")))
            rows.append(("LEDES Format", fmt))
            rows.append(("Billing Period", f"{start_date} → {end_date}"))
            summary_df = pd.DataFrame(rows, columns=["Field", "Value"])
            st.table(summary_df)

        # Main generation/export expander
        with st.expander("Generate, Preview & Export", expanded=True):
            st.info("Generate the invoice line items, review a preview table, and export to LEDES text or PDF files.")
            # Load uploads or defaults
            tk_file = st.session_state.get("__tk_file")
            task_file = st.session_state.get("__task_file")
            timekeepers = _load_timekeepers(tk_file) or [
                {"TIMEKEEPER_NAME": "Smith, John", "TIMEKEEPER_CLASSIFICATION": "PT", "TIMEKEEPER_ID": "TK001", "RATE": 200.0},
                {"TIMEKEEPER_NAME": "Doe, Jane", "TIMEKEEPER_CLASSIFICATION": "AS", "TIMEKEEPER_ID": "TK002", "RATE": 150.0},
                {"TIMEKEEPER_NAME": "Lee, Chris", "TIMEKEEPER_CLASSIFICATION": "PL", "TIMEKEEPER_ID": "TK003", "RATE": 95.0},
            ]
            custom_tasks = _load_custom_task_activity_data(task_file)
            task_pool = custom_tasks if custom_tasks is not None and len(custom_tasks) > 0 else CONFIG['DEFAULT_TASK_ACTIVITY_DESC']
            mandatory_items = st.session_state.get("__mandatory", [])

            if st.button("Generate Lines"):
                effective_tax_rate = tax_rate if format_choice == "1998BI V2" else 0.0
                rows, total_excl, total_tax, total_incl, skipped = _generate_invoice_data(
                    fee_count, expense_count, timekeepers, client_id, law_firm_id, invoice_desc,
                    start_date, end_date, task_pool, CONFIG['MAJOR_TASK_CODES'], max_daily_hours,
                    include_block_billed, faker, effective_tax_rate, mandatory_items
                )
                if skipped:
                    st.warning("Mandatory items skipped (timekeeper not found): " + ", ".join(skipped))

                if not rows:
                    st.error("No rows were generated. Check inputs and try again.")
                else:
                    df = pd.DataFrame(rows)
                    st.session_state['invoice_df'] = df
                    st.session_state['totals'] = (total_excl, total_tax, total_incl)
                    st.session_state['format_choice'] = format_choice
                    st.success(f"Generated {len(df)} lines. Subtotal: {total_excl:.2f} | Tax: {total_tax:.2f} | Total: {total_incl:.2f}")
                    st.dataframe(df, use_container_width=True, height=400)

            # Export buttons
            df = st.session_state.get('invoice_df')
            totals = st.session_state.get('totals')
            current_format = st.session_state.get('format_choice', format_choice)
            if df is not None and totals is not None:
                total_excl, total_tax, total_incl = totals
                if current_format == "1998BI V2":
                    content = _create_ledes_1998biv2_content(
                        df.to_dict(orient='records'),
                        start_date, end_date, invoice_number, matter_number, (invoice_currency or "USD"),
                        (matter_name or "Matter"), (po_number or ""), (client_matter_id or ""), tax_type="VAT"
                    )
                    fname = f"{invoice_number}_LEDES_1998BIV2.txt"
                else:
                    content = _create_ledes_1998b_content(
                        df.to_dict(orient='records'), total_excl, start_date, end_date, invoice_number, matter_number, is_first_invoice=True
                    )
                    fname = f"{invoice_number}_LEDES_1998B.txt"

                if not content or content.strip() == "":
                    st.error("The LEDES content appears empty. Please regenerate lines and try again.")
                else:
                    st.download_button("Download LEDES File", data=content, file_name=fname, mime="text/plain")

                pdf_buf = _create_pdf_invoice(
                    df, total_excl, total_tax, total_incl,
                    invoice_number, end_date, start_date, end_date,
                    client_id, law_firm_id, client_name=client_name, law_firm_name=law_firm_name
                )
                st.download_button("Download PDF Invoice", data=pdf_buf.getvalue(), file_name=f"{invoice_number}.pdf", mime="application/pdf")
            else:
                st.info("Generate lines to enable exports.")

# Export buttons
            df = st.session_state.get('invoice_df')
            totals = st.session_state.get('totals')
            current_format = st.session_state.get('format_choice', format_choice)
            if df is not None and totals is not None:
                total_excl, total_tax, total_incl = totals
                if current_format == "1998BI V2":
                    content = _create_ledes_1998biv2_content(
                        df.to_dict(orient='records'),
                        start_date, end_date, invoice_number, matter_number, (invoice_currency or "USD"),
                        (matter_name or "Matter"), (po_number or ""), (client_matter_id or ""), tax_type="VAT"
                    )
                    fname = f"{invoice_number}_LEDES_1998BIV2.txt"
                else:
                    content = _create_ledes_1998b_content(
                        df.to_dict(orient='records'), total_excl, start_date, end_date, invoice_number, matter_number, is_first_invoice=True
                    )
                    fname = f"{invoice_number}_LEDES_1998B.txt"

                if not content or content.strip() == "":
                    st.error("The LEDES content appears empty. Please regenerate lines and try again.")
                else:
                    st.download_button("Download LEDES File", data=content, file_name=fname, mime="text/plain")

                pdf_buf = _create_pdf_invoice(
                    df, total_excl, total_tax, total_incl,
                    invoice_number, end_date, start_date, end_date,
                    client_id, law_firm_id, client_name=client_name, law_firm_name=law_firm_name
                )
                st.download_button("Download PDF Invoice", data=pdf_buf.getvalue(), file_name=f"{invoice_number}.pdf", mime="application/pdf")
            else:
                st.info("Generate lines to enable exports.")

if __name__ == "__main__":
    main()
