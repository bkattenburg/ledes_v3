
# app-reverted-biv2.py
# Exact layout of app (1).py, with a BIv2-only section inserted beneath LEDES Version
# Full LEDES 1998B & 1998BI V2 generators, PDF export, receipts, and email sending.

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
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
import zipfile

st.set_page_config(page_title="LEDES 1998B / 1998BI V2 Invoice Generator", layout="wide")
faker = Faker()
logging.basicConfig(level=logging.ERROR)

# ----------------------
# Config / defaults
# ----------------------
CONFIG = {
    'DEFAULT_TASK_ACTIVITY_DESC': [
        ("L110", "A101", "Legal Research: Review statutes and regulations"),
        ("L120", "A101", "Legal Research: Draft research memorandum"),
        ("L140", "A102", "Case Assessment: Develop case strategy"),
        ("L240", "A105", "Discovery: Review opposing party's discovery responses"),
        ("L260", "A106", "Depositions: Attend deposition"),
        ("L300", "A107", "Motions: Argue motion in court"),
        ("L430", "A112", "Client Communication: Client meeting"),
        ("L450", "A112", "Client Communication: Email correspondence with client"),
    ],
    'EXPENSE_CODES': {
        "Copying": "E101", "Telephone": "E105", "Local travel": "E109", "Out-of-town travel": "E110", "Other": "E124"
    },
    'DEFAULT_INVOICE_DESCRIPTION': "Monthly Legal Services",
}

# ----------------------
# Helpers to load files
# ----------------------
def _load_timekeepers(uploaded_file) -> Optional[List[Dict]]:
    if uploaded_file is None: return None
    try:
        df = pd.read_csv(uploaded_file)
        required = ["TIMEKEEPER_NAME","TIMEKEEPER_CLASSIFICATION","TIMEKEEPER_ID","RATE"]
        if not all(c in df.columns for c in required):
            st.error(f"Timekeeper CSV must contain: {', '.join(required)}")
            return None
        return df.to_dict(orient='records')
    except Exception as e:
        st.error(f"Error loading timekeeper file: {e}")
        return None

def _load_custom_task_activity_data(uploaded_file) -> Optional[List[Tuple[str, str, str]]]:
    if uploaded_file is None: return None
    try:
        df = pd.read_csv(uploaded_file)
        required = ["TASK_CODE","ACTIVITY_CODE","DESCRIPTION"]
        if not all(c in df.columns for c in required):
            st.error(f"Custom Task/Activity CSV must contain: {', '.join(required)}")
            return None
        return [(str(r["TASK_CODE"]), str(r["ACTIVITY_CODE"]), str(r["DESCRIPTION"])) for _, r in df.iterrows()]
    except Exception as e:
        st.error(f"Error loading custom tasks file: {e}")
        return None

# ----------------------
# LEDES 1998B & 1998BI V2
# ----------------------
def _create_ledes_line_1998b(row: Dict, line_no: int, inv_total: float, bill_start: datetime.date, bill_end: datetime.date, invoice_number: str, matter_number: str) -> List[str]:
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
        lines.append("|".join(map(str, line)) + "[]")
    return "\n".join(lines)

def _create_ledes_line_1998biv2(row: Dict, line_no: int, bill_start: datetime.date, bill_end: datetime.date,
                                invoice_number: str, matter_number: str, invoice_currency: str,
                                matter_name: str, po_number: str, client_matter_id: str, tax_type: str = "VAT") -> List[str]:
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
        bill_end.strftime("%Y%m%d"),
        invoice_number,
        str(row.get("CLIENT_ID", "")),
        str(row.get("LAW_FIRM_ID", "")),
        matter_number,
        str(client_matter_id or ""),
        matter_name,
        po_number,
        str(row.get("INVOICE_DESCRIPTION", "")),
        invoice_currency,
        f"{row.get('INVOICE_NET_TOTAL', 0.0):.2f}",
        f"{row.get('INVOICE_TAX_TOTAL', 0.0):.2f}",
        f"{row.get('INVOICE_TOTAL', 0.0):.2f}",
        f"{row.get('INVOICE_REPORTED_TAX_TOTAL', 0.0):.2f}",
        invoice_currency,
        str(line_no),
        adj_type,
        f"{hours:.1f}" if adj_type == "F" else f"{int(hours)}",
        f"{rate:.2f}",
        "0.00",
        f"{line_total_excl_tax:.2f}",
        f"{tax_rate:.4f}",
        f"{tax_amount:.2f}",
        f"{line_total_incl_tax:.2f}",
        str(row.get("LINE_ITEM_TAX_TYPE", tax_type)),
        date_obj.strftime("%Y%m%d"),
        row.get("TASK_CODE", ""),
        row.get("ACTIVITY_CODE", ""),
        row.get("EXPENSE_CODE", ""),
        row.get("TIMEKEEPER_ID", ""),
        row.get("TIMEKEEPER_NAME", ""),
        row.get("TIMEKEEPER_CLASSIFICATION", ""),
    ]

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
        line = _create_ledes_line_1998biv2(row, i, bill_start, bill_end, invoice_number, matter_number, invoice_currency, matter_name, po_number, client_matter_id, tax_type=tax_type)
        lines.append("|".join(map(str, line)) + "[]")
    return "\n".join(lines)

# ----------------------
# Data generation
# ----------------------
def _process_description(description: str, faker_instance: Faker) -> str:
    pattern = r"\b(\d{2}/\d{2}/\d{4})\b"
    if re.search(pattern, description):
        days_ago = random.randint(15, 90)
        new_date = (datetime.date.today() - datetime.timedelta(days=days_ago)).strftime("%m/%d/%Y")
        description = re.sub(pattern, new_date, description)
    description = description.replace("{NAME_PLACEHOLDER}", faker_instance.name())
    return description

def _generate_invoice_data(fee_count: int, expense_count: int, timekeepers: List[Dict], client_id: str, law_firm_id: str,
                           invoice_desc: str, billing_start_date: datetime.date, billing_end_date: datetime.date,
                           task_pool: List[Tuple[str, str, str]], tax_rate: float) -> Tuple[List[Dict], float, float, float]:
    rows: List[Dict] = []
    delta = billing_end_date - billing_start_date
    num_days = max(1, delta.days + 1)

    # Fees
    for _ in range(fee_count):
        if not timekeepers or not task_pool: break
        tk = random.choice(timekeepers)
        task_code, activity_code, description = random.choice(task_pool)
        random_day_offset = random.randint(0, num_days - 1)
        line_item_date = billing_start_date + datetime.timedelta(days=random_day_offset)
        hours = round(random.uniform(0.5, 8.0), 1)
        rate = float(tk["RATE"])
        total = round(hours * rate, 2)
        tax_amount = round(total * tax_rate, 2)
        rows.append({
            "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id,
            "LINE_ITEM_DATE": line_item_date.strftime("%Y-%m-%d"), "TIMEKEEPER_NAME": tk["TIMEKEEPER_NAME"],
            "TIMEKEEPER_CLASSIFICATION": tk["TIMEKEEPER_CLASSIFICATION"], "TIMEKEEPER_ID": tk["TIMEKEEPER_ID"],
            "TASK_CODE": task_code, "ACTIVITY_CODE": activity_code, "EXPENSE_CODE": "",
            "DESCRIPTION": _process_description(description, faker), "HOURS": hours, "RATE": rate,
            "LINE_ITEM_TOTAL": total, "TAX_RATE": tax_rate, "TAX_AMOUNT": tax_amount
        })

    # Expenses (simple mix)
    for _ in range(expense_count):
        exp_name = random.choice(list(CONFIG['EXPENSE_CODES'].keys()))
        exp_code = CONFIG['EXPENSE_CODES'][exp_name]
        random_day_offset = random.randint(0, num_days - 1)
        line_item_date = billing_start_date + datetime.timedelta(days=random_day_offset)
        if exp_code == "E101":  # copying
            qty = random.randint(50, 300); rate = 0.24; total = round(qty * rate, 2); hours = qty
        elif exp_code == "E109":  # mileage
            miles = random.randint(5, 50); rate = 0.65; total = round(miles * rate, 2); hours = miles
        elif exp_code == "E110":  # travel
            rate = round(random.uniform(100.0, 800.0), 2); total = rate; hours = 1
        elif exp_code == "E105":  # telephone
            rate = round(random.uniform(5.0, 15.0), 2); total = rate; hours = 1
        else:
            hours = random.randint(1, 3); rate = round(random.uniform(10.0, 150.0), 2); total = round(hours * rate, 2)
        tax_amount = round(total * tax_rate, 2)
        rows.append({
            "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id,
            "LINE_ITEM_DATE": line_item_date.strftime("%Y-%m-%d"), "TIMEKEEPER_NAME": "",
            "TIMEKEEPER_CLASSIFICATION": "", "TIMEKEEPER_ID": "", "TASK_CODE": "", "ACTIVITY_CODE": "",
            "EXPENSE_CODE": exp_code, "DESCRIPTION": exp_name, "HOURS": hours, "RATE": rate,
            "LINE_ITEM_TOTAL": total, "TAX_RATE": tax_rate, "TAX_AMOUNT": tax_amount
        })

    total_excl = sum(float(r.get("LINE_ITEM_TOTAL", 0.0)) for r in rows)
    total_tax = sum(float(r.get("TAX_AMOUNT", 0.0)) for r in rows)
    total_incl = total_excl + total_tax
    return rows, total_excl, total_tax, total_incl

# ----------------------
# PDF Invoice (polished table)
# ----------------------
def _create_pdf_invoice(df: pd.DataFrame, total_excl: float, total_tax: float, total_incl: float,
                        invoice_number: str, invoice_date: datetime.date, billing_start_date: datetime.date,
                        billing_end_date: datetime.date, client_id: str, law_firm_id: str,
                        client_name: str = "", law_firm_name: str = "") -> io.BytesIO:
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
        Paragraph("Date", th), Paragraph("Type", th), Paragraph("Task", th), Paragraph("Act.", th),
        Paragraph("Exp.", th), Paragraph("Timekeeper", th), Paragraph("Description", th),
        Paragraph("Units", th), Paragraph("Rate", th), Paragraph("Tax", th),
        Paragraph("Total (excl)", th), Paragraph("Total (incl)", th),
    ]]

    for _, r in df.iterrows():
        is_expense = bool(r.get("EXPENSE_CODE"))
        typ = "Expense" if is_expense else "Fee"
        total_ex = float(r.get("LINE_ITEM_TOTAL", 0.0))
        tax = float(r.get("TAX_AMOUNT", 0.0))
        total_in = total_ex + tax
        desc = str(r.get("DESCRIPTION", ""))[:2000]
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
    table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#333333')),
        ('GRID', (0,0), (-1,-1), 0.25, colors.grey),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('ALIGN', (7,1), (11,-1), 'RIGHT'),
        ('LEFTPADDING', (0,0), (-1,-1), 4), ('RIGHTPADDING', (0,0), (-1,-1), 4),
        ('TOPPADDING', (0,0), (-1,-1), 2), ('BOTTOMPADDING', (0,0), (-1,-1), 2),
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
# Receipts (polished)
# ----------------------
def generate_airfare_receipt(airline, flight_no, dep_city, arr_city, fare_class, amount, roundtrip):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    elems = [Paragraph("<b>Airfare Receipt</b>", styles['Heading2']), Spacer(1,6)]
    details = [
        ["Airline", airline], ["Flight #", flight_no], ["From", dep_city], ["To", arr_city],
        ["Fare Class", fare_class], ["Roundtrip", "Yes" if roundtrip else "No"], ["Amount", f"${amount:.2f}"]
    ]
    data = [[Paragraph(k, styles['Normal']), Paragraph(str(v), styles['Normal'])] for k,v in details]
    table = Table(data, colWidths=[1.5*inch, 3.8*inch])
    table.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.25,colors.grey), ('VALIGN',(0,0),(-1,-1),'TOP')]))
    elems += [table, Spacer(1,12), Paragraph("Generated for demonstration purposes only.", styles['Italic'])]
    doc.build(elems); buf.seek(0); return buf.getvalue()

def generate_uber_receipt(amount):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    elems = [Paragraph("<b>Uber Ride Receipt</b>", styles['Heading2']), Spacer(1,6)]
    details = [["Driver", faker.name()], ["Date", datetime.date.today().strftime("%Y-%m-%d")],
               ["Pickup", faker.city()], ["Dropoff", faker.city()], ["Amount", f"${amount:.2f}"]]
    data = [[Paragraph(k, styles['Normal']), Paragraph(str(v), styles['Normal'])] for k,v in details]
    table = Table(data, colWidths=[1.5*inch, 3.8*inch])
    table.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.25,colors.grey), ('VALIGN',(0,0),(-1,-1),'TOP')]))
    elems += [table, Spacer(1,12), Paragraph("Generated for demonstration purposes only.", styles['Italic'])]
    doc.build(elems); buf.seek(0); return buf.getvalue()

def zip_receipts(receipts: Dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        for name, data in receipts.items():
            zf.writestr(name, data)
    buf.seek(0); return buf.getvalue()

# ----------------------
# Email
# ----------------------
def send_email(sender, recipient, subject, body, password, smtp_server, smtp_port, attachments: Dict[str, bytes]):
    msg = MIMEMultipart(); msg['From']=sender; msg['To']=recipient; msg['Subject']=subject
    msg.attach(MIMEText(body, 'plain'))
    for fname, data in attachments.items():
        part = MIMEBase('application','octet-stream'); part.set_payload(data); encoders.encode_base64(part)
        part.add_header('Content-Disposition', f'attachment; filename={fname}'); msg.attach(part)
    try:
        with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
            server.login(sender, password); server.sendmail(sender, recipient, msg.as_string())
        return True, None
    except Exception as e:
        return False, str(e)

# ----------------------
# UI (exact layout names/headers as app (1).py)
# ----------------------
def main():
    st.title("LEDES 1998B / 1998BI V2 Invoice Generator")

    tab1, tab2, tab3, tab4 = st.tabs(["Invoice Details","Data Sources","Mandatory Items","Export"])

    # -------- Invoice Details --------
    with tab1:
        st.header("Invoice Details")
        ledes_version = st.selectbox("LEDES Version",["1998B","1998BI V2"])
        invoice_number = st.text_input("Invoice Number","INV-1001")
        matter_number = st.text_input("Law Firm Matter ID","MAT-2001")

        # BIv2 only block (positioned right after LEDES Version & IDs)
        if ledes_version == "1998BI V2":
            st.subheader("BIv2 Additional Fields")
            matter_name = st.text_input("Matter Name *","General Litigation")
            po_number = st.text_input("PO Number (optional)","")
            client_matter_id = st.text_input("Client Matter ID (optional)","")
            invoice_currency = st.selectbox("Invoice Currency (ISO 4217) *",["USD","AUD","CAD","GBP","EUR"], index=0)
            tax_rate = st.number_input("Tax Rate (decimal)",min_value=0.0,max_value=1.0,value=0.19,step=0.01,format="%0.2f")
            st.session_state["__biv2"] = dict(matter_name=matter_name, po_number=po_number, client_matter_id=client_matter_id,
                                              invoice_currency=invoice_currency, tax_rate=tax_rate)
        else:
            st.session_state["__biv2"] = None

        start_date = st.date_input("Billing Start Date",datetime.date.today().replace(day=1))
        end_date = st.date_input("Billing End Date",datetime.date.today())
        invoice_desc = st.text_input("Invoice Description", CONFIG['DEFAULT_INVOICE_DESCRIPTION'])

        # Minimal client/firm IDs for export context (kept simple to preserve layout)
        client_id = st.text_input("Client ID","CLIENT001")
        law_firm_id = st.text_input("Law Firm ID","LF001")
        client_name = st.text_input("Client Name","Client")
        law_firm_name = st.text_input("Law Firm Name","Law Firm")

        # Line counts (kept here to avoid changing tab layout elsewhere)
        st.subheader("Line Counts")
        fee_count = st.slider("# Fee Lines", 0, 200, 20)
        expense_count = st.slider("# Expense Lines", 0, 200, 5)

    # -------- Data Sources --------
    with tab2:
        st.header("Data Sources")
        tk_file = st.file_uploader("Upload Timekeepers CSV", type=["csv"])
        task_file = st.file_uploader("Upload Custom Task/Activity CSV (optional)", type=["csv"])
        st.session_state["__tk_file"] = tk_file
        st.session_state["__task_file"] = task_file

    # -------- Mandatory Items --------
    with tab3:
        st.header("Mandatory Items")
        mand_options = ["Airfare E110","Uber E110"]
        selected_mandatory = st.multiselect("Include mandatory items",mand_options,default=[])
        if "Airfare E110" in selected_mandatory:
            st.subheader("Airfare Details")
            st.session_state['airfare_airline'] = st.text_input("Airline","Delta")
            st.session_state['airfare_flight_number'] = st.text_input("Flight #","DL123")
            st.session_state['airfare_departure_city'] = st.text_input("Departure City","SFO")
            st.session_state['airfare_arrival_city'] = st.text_input("Arrival City","JFK")
            st.session_state['airfare_fare_class'] = st.selectbox("Fare Class",["Economy/Coach","Premium Economy","Business","First"],index=0)
            st.session_state['airfare_roundtrip'] = st.checkbox("Roundtrip",value=True)
            st.session_state['airfare_amount'] = st.number_input("Airfare Amount",0.0,20000.0,650.0,1.0)
        if "Uber E110" in selected_mandatory:
            st.subheader("Uber Details")
            st.session_state['uber_amount'] = st.number_input("Uber Amount",0.0,2000.0,35.0,0.5)

        st.subheader("Receipts")
        if "Airfare E110" in selected_mandatory:
            st.session_state['gen_airfare_receipt'] = st.checkbox("Generate Airfare Receipt",value=False)
        if "Uber E110" in selected_mandatory:
            st.session_state['gen_uber_receipt'] = st.checkbox("Generate Uber Receipt",value=False)

        st.session_state["__mandatory"] = selected_mandatory

    # -------- Export --------
    with tab4:
        st.header("Export")

        # Generate lines (kept on Export tab to preserve feel)
        st.subheader("Generate Lines")
        if st.button("Generate Lines"):
            timekeepers = _load_timekeepers(st.session_state.get("__tk_file")) or [
                {"TIMEKEEPER_NAME": "Smith, John", "TIMEKEEPER_CLASSIFICATION": "PT", "TIMEKEEPER_ID": "TK001", "RATE": 200.0},
                {"TIMEKEEPER_NAME": "Doe, Jane", "TIMEKEEPER_CLASSIFICATION": "AS", "TIMEKEEPER_ID": "TK002", "RATE": 150.0},
                {"TIMEKEEPER_NAME": "Lee, Chris", "TIMEKEEPER_CLASSIFICATION": "PL", "TIMEKEEPER_ID": "TK003", "RATE": 95.0},
            ]
            task_pool = _load_custom_task_activity_data(st.session_state.get("__task_file")) or CONFIG['DEFAULT_TASK_ACTIVITY_DESC']
            effective_tax_rate = st.session_state["__biv2"]["tax_rate"] if (ledes_version == "1998BI V2" and st.session_state.get("__biv2")) else 0.0
            rows, total_excl, total_tax, total_incl = _generate_invoice_data(
                fee_count, expense_count, timekeepers, client_id, law_firm_id, invoice_desc, start_date, end_date, task_pool, effective_tax_rate
            )

            # Mandatory items added at end (simple append using entered details)
            if "Airfare E110" in st.session_state.get("__mandatory", []):
                amount = float(st.session_state.get('airfare_amount', 0.0))
                tax_amt = round(amount * effective_tax_rate, 2)
                rows.append({
                    "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id,
                    "LINE_ITEM_DATE": end_date.strftime("%Y-%m-%d"), "TIMEKEEPER_NAME": "",
                    "TIMEKEEPER_CLASSIFICATION": "", "TIMEKEEPER_ID": "", "TASK_CODE": "", "ACTIVITY_CODE": "",
                    "EXPENSE_CODE": "E110", "DESCRIPTION": f"Airfare ({st.session_state.get('airfare_fare_class','Economy')}): "
                                                            f"{st.session_state.get('airfare_airline','')} "
                                                            f"{st.session_state.get('airfare_flight_number','')}, "
                                                            f"{st.session_state.get('airfare_departure_city','')} to "
                                                            f"{st.session_state.get('airfare_arrival_city','')}{' (Roundtrip)' if st.session_state.get('airfare_roundtrip', False) else ''}",
                    "HOURS": 1, "RATE": amount, "LINE_ITEM_TOTAL": amount, "TAX_RATE": effective_tax_rate, "TAX_AMOUNT": tax_amt
                })
                total_excl += amount; total_tax += tax_amt; total_incl = total_excl + total_tax

            if "Uber E110" in st.session_state.get("__mandatory", []):
                amount = float(st.session_state.get('uber_amount', 0.0))
                tax_amt = round(amount * effective_tax_rate, 2)
                rows.append({
                    "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id,
                    "LINE_ITEM_DATE": end_date.strftime("%Y-%m-%d"), "TIMEKEEPER_NAME": "", "TIMEKEEPER_CLASSIFICATION": "",
                    "TIMEKEEPER_ID": "", "TASK_CODE": "", "ACTIVITY_CODE": "", "EXPENSE_CODE": "E110",
                    "DESCRIPTION": "Uber ride to client's office", "HOURS": 1, "RATE": amount,
                    "LINE_ITEM_TOTAL": amount, "TAX_RATE": effective_tax_rate, "TAX_AMOUNT": tax_amt
                })
                total_excl += amount; total_tax += tax_amt; total_incl = total_excl + total_tax

            df = pd.DataFrame(rows)
            st.session_state['invoice_df'] = df
            st.session_state['totals'] = (total_excl, total_tax, total_incl)
            st.session_state['ledes_version'] = ledes_version
            st.session_state['ids_ctx'] = (client_id, law_firm_id, client_name, law_firm_name)
            st.success(f"Generated {len(df)} lines.")
            st.dataframe(df, use_container_width=True, height=380)

            # Generate receipts (if toggled)
            receipts = {}
            if st.session_state.get('gen_airfare_receipt'):
                receipts["airfare_receipt.pdf"] = generate_airfare_receipt(
                    st.session_state.get('airfare_airline','Airline'),
                    st.session_state.get('airfare_flight_number','XX000'),
                    st.session_state.get('airfare_departure_city','Origin'),
                    st.session_state.get('airfare_arrival_city','Destination'),
                    st.session_state.get('airfare_fare_class','Economy'),
                    float(st.session_state.get('airfare_amount', 0.0)),
                    bool(st.session_state.get('airfare_roundtrip', False))
                )
            if st.session_state.get('gen_uber_receipt'):
                receipts["uber_receipt.pdf"] = generate_uber_receipt(float(st.session_state.get('uber_amount', 0.0)))
            st.session_state['__receipts_zip'] = zip_receipts(receipts) if receipts else None

        # Export Files
        st.subheader("Export Files")
        df = st.session_state.get('invoice_df')
        totals = st.session_state.get('totals')
        if df is not None and totals is not None:
            client_id, law_firm_id, client_name, law_firm_name = st.session_state.get('ids_ctx', ("","","",""))
            total_excl, total_tax, total_incl = totals
            if st.session_state.get('ledes_version') == "1998BI V2" and st.session_state.get('__biv2'):
                b = st.session_state['__biv2']
                content = _create_ledes_1998biv2_content(
                    df.to_dict(orient='records'), start_date, end_date, invoice_number, matter_number,
                    b['invoice_currency'], b['matter_name'], b['po_number'], b['client_matter_id'], tax_type="VAT"
                )
                fname = f"{invoice_number}_LEDES_1998BIV2.txt"
            else:
                content = _create_ledes_1998b_content(
                    df.to_dict(orient='records'), total_excl, start_date, end_date, invoice_number, matter_number, is_first_invoice=True
                )
                fname = f"{invoice_number}_LEDES_1998B.txt"

            st.download_button("Download LEDES File", data=content, file_name=fname, mime="text/plain", key="download_ledes")

            pdf_buf = _create_pdf_invoice(
                df, total_excl, total_tax, total_incl, invoice_number, end_date, start_date, end_date,
                client_id, law_firm_id, client_name=client_name, law_firm_name=law_firm_name
            )
            st.download_button("Download PDF Invoice", data=pdf_buf.getvalue(), file_name=f"{invoice_number}.pdf", mime="application/pdf", key="download_pdf")

            st.session_state['__export_ledes_bytes'] = content.encode('utf-8')
            st.session_state['__export_pdf_bytes'] = pdf_buf.getvalue()
        else:
            st.info("Generate lines to enable exports.")

        # Send via Email
        st.subheader("Send via Email")
        sender = st.text_input("From Email")
        recipient = st.text_input("To Email")
        subject = st.text_input("Subject", f"Invoice {invoice_number}")
        body = st.text_area("Body","Please find attached the invoice.")
        smtp_server = st.text_input("SMTP Server","smtp.gmail.com")
        smtp_port = st.number_input("SMTP Port",min_value=1,max_value=65535,value=465)
        password = st.text_input("Email Password", type="password")
        attach_ledes = st.checkbox("Attach LEDES File", value=True)
        attach_pdf = st.checkbox("Attach PDF Invoice", value=True)
        attach_receipts = st.checkbox("Attach Receipts (zipped)", value=False)

        if st.button("Send Email"):
            attachments = {}
            if attach_ledes and st.session_state.get('__export_ledes_bytes'):
                out_name = f"{invoice_number}_LEDES_1998B.txt"
                if st.session_state.get('ledes_version') == "1998BI V2": out_name = f"{invoice_number}_LEDES_1998BIV2.txt"
                attachments[out_name] = st.session_state['__export_ledes_bytes']
            if attach_pdf and st.session_state.get('__export_pdf_bytes'):
                attachments[f"{invoice_number}.pdf"] = st.session_state['__export_pdf_bytes']
            if attach_receipts and st.session_state.get('__receipts_zip'):
                attachments["receipts.zip"] = st.session_state['__receipts_zip']

            if not attachments:
                st.error("No attachments selected or available. Generate lines and try again.")
            elif not sender or not recipient or not password:
                st.error("Please fill From, To, and Email Password.")
            else:
                ok, err = send_email(sender, recipient, subject, body, password, smtp_server, int(smtp_port), attachments)
                if ok: st.success("Email sent successfully!")
                else: st.error(f"Email failed: {err}")

if __name__=="__main__":
    main()
