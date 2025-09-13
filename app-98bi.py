
# app-reverted-biv2-final.py
# UI matches app (1).py exactly (tabs/headers/labels/order), with ONE visible addition:
#   - A BIv2-only block under "LEDES Version" on the Invoice Details tab.
# Backend: full LEDES 1998B & 1998BIv2 generators, PDF invoice, receipts (polished), email sending.

import streamlit as st
import pandas as pd
import random
import datetime
import io
import re
import zipfile
import smtplib
from typing import List, Dict, Tuple, Optional
from faker import Faker

from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch

from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders

# ---------------- App setup ----------------
st.set_page_config(page_title="LEDES 1998B / 1998BI V2 Invoice Generator", layout="wide")
faker = Faker()

# ---------------- Data & helpers ----------------
DEFAULT_TASKS = [
    ("L110","A101","Legal Research: Review statutes and regulations"),
    ("L120","A101","Legal Research: Draft research memorandum"),
    ("L140","A102","Case Assessment: Develop case strategy"),
    ("L240","A105","Discovery: Review opposing party's discovery responses"),
    ("L260","A106","Depositions: Attend deposition"),
    ("L300","A107","Motions: Argue motion in court"),
    ("L430","A112","Client Communication: Client meeting"),
    ("L450","A112","Client Communication: Email correspondence with client"),
]

def load_timekeepers(uploaded) -> Optional[List[Dict]]:
    if not uploaded:
        return None
    try:
        df = pd.read_csv(uploaded)
        # Expecting at least: TIMEKEEPER_NAME, TIMEKEEPER_CLASSIFICATION, TIMEKEEPER_ID, RATE
        return df.to_dict(orient="records")
    except Exception:
        return None

def load_task_activity(uploaded) -> Optional[List[Tuple[str,str,str]]]:
    if not uploaded:
        return None
    try:
        df = pd.read_csv(uploaded)
        if not all(c in df.columns for c in ["TASK_CODE","ACTIVITY_CODE","DESCRIPTION"]):
            return None
        return [(str(r["TASK_CODE"]), str(r["ACTIVITY_CODE"]), str(r["DESCRIPTION"])) for _,r in df.iterrows()]
    except Exception:
        return None

def process_desc(desc: str) -> str:
    # Minor naturalization (date scramble if found)
    pattern = r"\b(\d{2}/\d{2}/\d{4})\b"
    if re.search(pattern, desc):
        days_ago = random.randint(10, 60)
        new_date = (datetime.date.today()-datetime.timedelta(days=days_ago)).strftime("%m/%d/%Y")
        desc = re.sub(pattern, new_date, desc)
    desc = desc.replace("{NAME_PLACEHOLDER}", faker.name())
    return desc

# ---------------- Invoice generation ----------------
def generate_lines(fee_count: int, expense_count: int, tks: List[Dict], client_id: str, law_firm_id: str,
                   invoice_desc: str, start: datetime.date, end: datetime.date,
                   tasks: List[Tuple[str,str,str]], tax_rate: float) -> Tuple[List[Dict], float, float, float]:
    rows: List[Dict] = []
    span = (end-start).days + 1
    span = max(1, span)

    # Fees
    for _ in range(max(0, fee_count)):
        if not (tks and tasks): break
        tk = random.choice(tks)
        task_code, activity_code, desc = random.choice(tasks)
        date = start + datetime.timedelta(days=random.randint(0, span-1))
        hours = round(random.uniform(0.5, 8.0), 1)
        rate = float(tk.get("RATE", 0.0))
        total = round(hours*rate, 2)
        tax_amt = round(total*tax_rate, 2)

        rows.append({
            "INVOICE_DESCRIPTION": invoice_desc,
            "CLIENT_ID": client_id,
            "LAW_FIRM_ID": law_firm_id,
            "LINE_ITEM_DATE": date.strftime("%Y-%m-%d"),
            "TIMEKEEPER_NAME": tk.get("TIMEKEEPER_NAME",""),
            "TIMEKEEPER_CLASSIFICATION": tk.get("TIMEKEEPER_CLASSIFICATION",""),
            "TIMEKEEPER_ID": tk.get("TIMEKEEPER_ID",""),
            "TASK_CODE": task_code, "ACTIVITY_CODE": activity_code,
            "EXPENSE_CODE": "",
            "DESCRIPTION": process_desc(desc),
            "HOURS": hours, "RATE": rate,
            "LINE_ITEM_TOTAL": total,
            "TAX_RATE": tax_rate, "TAX_AMOUNT": tax_amt
        })

    # Expenses (simple variety)
    for _ in range(max(0, expense_count)):
        date = start + datetime.timedelta(days=random.randint(0, span-1))
        exp_code = random.choice(["E101","E105","E109","E110","E124"])
        if exp_code == "E101":   # Copying per page
            qty = random.randint(25, 250); rate = 0.24; total = round(qty*rate,2); units = qty
            desc = "Copying"
        elif exp_code == "E105": # Telephone
            units = 1; rate = round(random.uniform(5.0, 15.0),2); total = rate; desc = "Telephone"
        elif exp_code == "E109": # Mileage
            miles = random.randint(5, 60); units = miles; rate = 0.65; total = round(miles*rate,2); desc = "Local travel"
        elif exp_code == "E110": # Out-of-town travel
            units = 1; rate = round(random.uniform(100.0, 800.0),2); total = rate; desc = "Out-of-town travel"
        else:
            units = 1; rate = round(random.uniform(20.0, 200.0),2); total = rate; desc = "Other"
        tax_amt = round(total*tax_rate, 2)
        rows.append({
            "INVOICE_DESCRIPTION": invoice_desc,
            "CLIENT_ID": client_id,
            "LAW_FIRM_ID": law_firm_id,
            "LINE_ITEM_DATE": date.strftime("%Y-%m-%d"),
            "TIMEKEEPER_NAME": "", "TIMEKEEPER_CLASSIFICATION": "", "TIMEKEEPER_ID": "",
            "TASK_CODE": "", "ACTIVITY_CODE": "",
            "EXPENSE_CODE": exp_code,
            "DESCRIPTION": desc,
            "HOURS": units, "RATE": rate,
            "LINE_ITEM_TOTAL": total,
            "TAX_RATE": tax_rate, "TAX_AMOUNT": tax_amt
        })

    total_excl = sum(float(r.get("LINE_ITEM_TOTAL",0.0)) for r in rows)
    total_tax  = sum(float(r.get("TAX_AMOUNT",0.0))      for r in rows)
    total_incl = total_excl + total_tax
    return rows, total_excl, total_tax, total_incl

# ---------------- LEDES exporters ----------------
def ledes_1998b_content(rows: List[Dict], inv_total: float, start: datetime.date, end: datetime.date,
                        invoice_number: str, matter_number: str) -> str:
    header = "LEDES1998B[]"
    fields = ("INVOICE_DATE|INVOICE_NUMBER|CLIENT_ID|LAW_FIRM_MATTER_ID|INVOICE_TOTAL|BILLING_START_DATE|"
              "BILLING_END_DATE|INVOICE_DESCRIPTION|LINE_ITEM_NUMBER|EXP/FEE/INV_ADJ_TYPE|"
              "LINE_ITEM_NUMBER_OF_UNITS|LINE_ITEM_ADJUSTMENT_AMOUNT|LINE_ITEM_TOTAL|LINE_ITEM_DATE|"
              "LINE_ITEM_TASK_CODE|LINE_ITEM_EXPENSE_CODE|LINE_ITEM_ACTIVITY_CODE|TIMEKEEPER_ID|"
              "LINE_ITEM_DESCRIPTION|LAW_FIRM_ID|LINE_ITEM_UNIT_COST|TIMEKEEPER_NAME|"
              "TIMEKEEPER_CLASSIFICATION|CLIENT_MATTER_ID[]")
    out = [header, fields]
    for i, r in enumerate(rows, start=1):
        is_expense = bool(r.get("EXPENSE_CODE"))
        adj_type = "E" if is_expense else "F"
        hours = r.get("HOURS", 0)
        hours_str = f"{float(hours):.1f}" if not is_expense else f"{int(float(hours))}"
        line = [
            end.strftime("%Y%m%d"),
            invoice_number,
            str(r.get("CLIENT_ID","")),
            matter_number,
            f"{float(inv_total):.2f}",
            start.strftime("%Y%m%d"),
            end.strftime("%Y%m%d"),
            str(r.get("INVOICE_DESCRIPTION","")),
            str(i),
            adj_type,
            hours_str,
            "0.00",
            f"{float(r.get('LINE_ITEM_TOTAL',0.0)):.2f}",
            datetime.datetime.strptime(r.get("LINE_ITEM_DATE"), "%Y-%m-%d").strftime("%Y%m%d"),
            "" if is_expense else str(r.get("TASK_CODE","")),
            str(r.get("EXPENSE_CODE","")) if is_expense else "",
            "" if is_expense else str(r.get("ACTIVITY_CODE","")),
            "" if is_expense else str(r.get("TIMEKEEPER_ID","")),
            str(r.get("DESCRIPTION","")).replace("|"," - "),
            str(r.get("LAW_FIRM_ID","")),
            f"{float(r.get('RATE',0.0)):.2f}" if not is_expense else f"{float(r.get('RATE',0.0)):.2f}",
            "" if is_expense else str(r.get("TIMEKEEPER_NAME","")),
            "" if is_expense else str(r.get("TIMEKEEPER_CLASSIFICATION","")),
            matter_number
        ]
        out.append("|".join(map(str,line))+"[]")
    return "\n".join(out)

def ledes_1998biv2_content(rows: List[Dict], start: datetime.date, end: datetime.date,
                           invoice_number: str, matter_number: str,
                           currency: str, matter_name: str, po_number: str, client_matter_id: str,
                           tax_type: str = "VAT") -> str:
    header = "LEDES1998BI V2[]"
    fields = ("INVOICE_DATE|INVOICE_NUMBER|CLIENT_ID|LAW_FIRM_ID|LAW_FIRM_MATTER_ID|CLIENT_MATTER_ID|"
              "MATTER_NAME|PO_NUMBER|INVOICE_DESCRIPTION|INVOICE_CURRENCY|INVOICE_NET_TOTAL|"
              "INVOICE_TAX_TOTAL|INVOICE_TOTAL|INVOICE_REPORTED_TAX_TOTAL|INVOICE_TAX_CURRENCY|"
              "LINE_ITEM_NUMBER|EXP/FEE/INV_ADJ_TYPE|LINE_ITEM_NUMBER_OF_UNITS|LINE_ITEM_UNIT_COST|"
              "LINE_ITEM_ADJUSTMENT_AMOUNT|LINE_ITEM_TOTAL|LINE_ITEM_TAX_RATE|LINE_ITEM_TAX_TOTAL|"
              "LINE_ITEM_TOTAL_INCL_TAX|LINE_ITEM_TAX_TYPE|LINE_ITEM_DATE|LINE_ITEM_TASK_CODE|"
              "LINE_ITEM_ACTIVITY_CODE|LINE_ITEM_EXPENSE_CODE|TIMEKEEPER_ID|TIMEKEEPER_NAME|"
              "TIMEKEEPER_CLASSIFICATION[]")
    total_excl = sum(float(r.get("LINE_ITEM_TOTAL",0.0)) for r in rows)
    total_tax  = sum(float(r.get("TAX_AMOUNT",0.0))      for r in rows)
    total_incl = total_excl + total_tax

    out = [header, fields]
    for i, r in enumerate(rows, start=1):
        is_expense = bool(r.get("EXPENSE_CODE"))
        adj_type = "E" if is_expense else "F"
        units = r.get("HOURS", 0)
        units_str = f"{float(units):.1f}" if not is_expense else f"{int(float(units))}"
        date_str = datetime.datetime.strptime(r.get("LINE_ITEM_DATE"), "%Y-%m-%d").strftime("%Y%m%d")
        rate = float(r.get("RATE",0.0))
        total = float(r.get("LINE_ITEM_TOTAL",0.0))
        tax_rate = float(r.get("TAX_RATE",0.0))
        tax_amt  = float(r.get("TAX_AMOUNT",0.0))
        total_incl_line = total + tax_amt
        line = [
            end.strftime("%Y%m%d"),           # INVOICE_DATE
            invoice_number,                   # INVOICE_NUMBER
            str(r.get("CLIENT_ID","")),       # CLIENT_ID
            str(r.get("LAW_FIRM_ID","")),     # LAW_FIRM_ID
            matter_number,                    # LAW_FIRM_MATTER_ID
            str(client_matter_id or ""),      # CLIENT_MATTER_ID
            matter_name,                      # MATTER_NAME
            po_number,                        # PO_NUMBER
            str(r.get("INVOICE_DESCRIPTION","")),   # INVOICE_DESCRIPTION
            currency,                         # INVOICE_CURRENCY
            f"{total_excl:.2f}",              # INVOICE_NET_TOTAL
            f"{total_tax:.2f}",               # INVOICE_TAX_TOTAL
            f"{total_incl:.2f}",              # INVOICE_TOTAL
            f"{total_tax:.2f}",               # INVOICE_REPORTED_TAX_TOTAL
            currency,                         # INVOICE_TAX_CURRENCY
            str(i),                           # LINE_ITEM_NUMBER
            adj_type,                         # EXP/FEE/INV_ADJ_TYPE
            units_str,                        # LINE_ITEM_NUMBER_OF_UNITS
            f"{rate:.2f}",                    # LINE_ITEM_UNIT_COST
            "0.00",                           # LINE_ITEM_ADJUSTMENT_AMOUNT
            f"{total:.2f}",                   # LINE_ITEM_TOTAL
            f"{tax_rate:.4f}",                # LINE_ITEM_TAX_RATE
            f"{tax_amt:.2f}",                 # LINE_ITEM_TAX_TOTAL
            f"{total_incl_line:.2f}",         # LINE_ITEM_TOTAL_INCL_TAX
            tax_type,                         # LINE_ITEM_TAX_TYPE
            date_str,                         # LINE_ITEM_DATE
            "" if is_expense else str(r.get("TASK_CODE","")),      # LINE_ITEM_TASK_CODE
            "" if is_expense else str(r.get("ACTIVITY_CODE","")),  # LINE_ITEM_ACTIVITY_CODE
            str(r.get("EXPENSE_CODE","")) if is_expense else "",   # LINE_ITEM_EXPENSE_CODE
            "" if is_expense else str(r.get("TIMEKEEPER_ID","")),  # TIMEKEEPER_ID
            "" if is_expense else str(r.get("TIMEKEEPER_NAME","")),# TIMEKEEPER_NAME
            "" if is_expense else str(r.get("TIMEKEEPER_CLASSIFICATION","")), # TIMEKEEPER_CLASSIFICATION
        ]
        out.append("|".join(map(str,line))+"[]")
    return "\n".join(out)

# ---------------- PDF invoice ----------------
def build_invoice_pdf(df: pd.DataFrame, subtotal: float, tax_total: float, grand_total: float,
                      invoice_number: str, invoice_date: datetime.date,
                      start: datetime.date, end: datetime.date,
                      client_id: str, law_firm_id: str,
                      client_name: str = "", law_firm_name: str = "") -> io.BytesIO:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    title = ParagraphStyle('Title', parent=styles['Heading1'], alignment=TA_LEFT, fontSize=14, spaceAfter=8)
    meta  = ParagraphStyle('Meta', parent=styles['Normal'], fontSize=9, spaceAfter=4)
    th = ParagraphStyle('TH', parent=styles['Normal'], alignment=TA_CENTER, fontSize=8, textColor=colors.white)
    td = ParagraphStyle('TD', parent=styles['Normal'], alignment=TA_LEFT, fontSize=8, leading=10, wordWrap='CJK')

    elems = []
    elems.append(Paragraph("Invoice", title))
    elems.append(Paragraph(f"Invoice #: <b>{invoice_number}</b>", meta))
    elems.append(Paragraph(f"Invoice Date: <b>{invoice_date:%Y-%m-%d}</b>", meta))
    elems.append(Paragraph(f"Billing Period: <b>{start:%Y-%m-%d}</b> to <b>{end:%Y-%m-%d}</b>", meta))
    elems.append(Paragraph(f"Client: <b>{client_name or 'Client'}</b> ({client_id})", meta))
    elems.append(Paragraph(f"Law Firm: <b>{law_firm_name or 'Law Firm'}</b> ({law_firm_id})", meta))
    elems.append(Spacer(1, 6))

    header = ["Date","Type","Task","Act.","Exp.","Timekeeper","Description","Units","Rate","Tax","Total (excl)","Total (incl)"]
    data = [[Paragraph(h, th) for h in header]]

    for _, r in df.iterrows():
        is_expense = bool(r.get("EXPENSE_CODE"))
        typ = "Expense" if is_expense else "Fee"
        total_ex = float(r.get("LINE_ITEM_TOTAL",0.0))
        tax = float(r.get("TAX_AMOUNT",0.0))
        desc = str(r.get("DESCRIPTION",""))
        if len(desc) > 2000: desc = desc[:2000]+"…"
        row = [
            Paragraph(str(r.get("LINE_ITEM_DATE","")), td),
            Paragraph(typ, td),
            Paragraph("" if is_expense else str(r.get("TASK_CODE","")), td),
            Paragraph("" if is_expense else str(r.get("ACTIVITY_CODE","")), td),
            Paragraph(str(r.get("EXPENSE_CODE","")) if is_expense else "", td),
            Paragraph("" if is_expense else str(r.get("TIMEKEEPER_NAME","")), td),
            Paragraph(desc, td),
            Paragraph(f"{float(r.get('HOURS',0.0)):.1f}" if not is_expense else f"{int(float(r.get('HOURS',0.0)))}", td),
            Paragraph(f"{float(r.get('RATE',0.0)):.2f}", td),
            Paragraph(f"{tax:.2f}", td),
            Paragraph(f"{total_ex:.2f}", td),
            Paragraph(f"{(total_ex+tax):.2f}", td),
        ]
        data.append(row)

    table = Table(
        data,
        colWidths=[0.7*inch,0.7*inch,0.6*inch,0.5*inch,0.6*inch,1.1*inch,2.6*inch,0.55*inch,0.7*inch,0.7*inch,0.9*inch,0.9*inch]
    )
    table.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#333333')),
        ('TEXTCOLOR',(0,0),(-1,0),colors.white),
        ('GRID',(0,0),(-1,-1),0.25,colors.grey),
        ('VALIGN',(0,0),(-1,-1),'TOP'),
        ('ALIGN',(7,1),(11,-1),'RIGHT'),
        ('LEFTPADDING',(0,0),(-1,-1),4),
        ('RIGHTPADDING',(0,0),(-1,-1),4),
        ('TOPPADDING',(0,0),(-1,-1),2),
        ('BOTTOMPADDING',(0,0),(-1,-1),2),
    ]))

    elems.append(table)
    elems.append(Spacer(1,8))
    elems.append(Paragraph(f"Subtotal (excl. tax): <b>{subtotal:.2f}</b>", meta))
    elems.append(Paragraph(f"Tax total: <b>{tax_total:.2f}</b>", meta))
    elems.append(Paragraph(f"Invoice total (incl. tax): <b>{grand_total:.2f}</b>", meta))

    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
    doc.build(elems)
    buf.seek(0)
    return buf

# ---------------- Receipts ----------------
def build_airfare_receipt(airline, flight_no, dep_city, arr_city, fare_class, amount, roundtrip):
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

def build_uber_receipt(amount):
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

def zip_receipts(files: Dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    buf.seek(0)
    return buf.getvalue()

# ---------------- Email ----------------
def send_email(sender, recipient, subject, body, password, smtp_server, smtp_port, attachments: Dict[str, bytes]):
    msg = MIMEMultipart()
    msg['From'] = sender; msg['To'] = recipient; msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))
    for fname, data in attachments.items():
        part = MIMEBase('application','octet-stream')
        part.set_payload(data); encoders.encode_base64(part)
        part.add_header('Content-Disposition', f'attachment; filename={fname}')
        msg.attach(part)
    try:
        with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
            server.login(sender, password)
            server.sendmail(sender, recipient, msg.as_string())
        return True, None
    except Exception as e:
        return False, str(e)

# ---------------- Main UI (exact layout) ----------------
def main():
    st.title("LEDES 1998B / 1998BI V2 Invoice Generator")

    tab1, tab2, tab3, tab4 = st.tabs(["Invoice Details","Data Sources","Mandatory Items","Export"])

    # ---------- Invoice Details ----------
    with tab1:
        st.header("Invoice Details")
        ledes_version = st.selectbox("LEDES Version",["1998B","1998BI V2"])
        invoice_number = st.text_input("Invoice Number","INV-1001")
        matter_number = st.text_input("Law Firm Matter ID","MAT-2001")

        # BIv2-only fields block (sole visible change; inserted here)
        if ledes_version == "1998BI V2":
            st.subheader("BIv2 Additional Fields")
            matter_name = st.text_input("Matter Name *","General Litigation")
            po_number = st.text_input("PO Number (optional)","")
            client_matter_id = st.text_input("Client Matter ID (optional)","")
            invoice_currency = st.selectbox("Invoice Currency (ISO 4217) *", ["USD","AUD","CAD","GBP","EUR"], index=0)
            tax_rate_biv2 = st.number_input("Tax Rate (decimal)", min_value=0.0, max_value=1.0, value=0.19, step=0.01, format="%0.2f")
            st.session_state["biv2"] = dict(matter_name=matter_name, po_number=po_number, client_matter_id=client_matter_id,
                                            invoice_currency=invoice_currency, tax_rate=tax_rate_biv2)
        else:
            st.session_state["biv2"] = None

        start_date = st.date_input("Billing Start Date", datetime.date.today().replace(day=1))
        end_date = st.date_input("Billing End Date", datetime.date.today())
        invoice_desc = st.text_input("Invoice Description","Monthly Legal Services")
        client_id = st.text_input("Client ID","CLIENT001")
        law_firm_id = st.text_input("Law Firm ID","LF001")

        fee_count = st.slider("Fee line count", 0, 200, 20)
        expense_count = st.slider("Expense line count", 0, 200, 5)

        client_name = st.text_input("Client Name","Client")
        law_firm_name = st.text_input("Law Firm Name","Law Firm")

    # ---------- Data Sources ----------
    with tab2:
        st.header("Data Sources")
        tk_file = st.file_uploader("Upload Timekeepers CSV", type=["csv"])
        task_file = st.file_uploader("Upload Task/Activity CSV", type=["csv"])
        st.session_state["tk_file"] = tk_file
        st.session_state["task_file"] = task_file

    # ---------- Mandatory Items ----------
    with tab3:
        st.header("Mandatory Items")
        selected = st.multiselect("Mandatory Items", ["Airfare E110","Uber E110"], [])
        if "Airfare E110" in selected:
            st.subheader("Airfare Details")
            st.session_state['airline']    = st.text_input("Airline","Delta")
            st.session_state['flight_no']  = st.text_input("Flight #","DL123")
            st.session_state['dep_city']   = st.text_input("Departure","SFO")
            st.session_state['arr_city']   = st.text_input("Arrival","JFK")
            st.session_state['fare_class'] = st.text_input("Fare Class","Economy/Coach")
            st.session_state['roundtrip']  = st.checkbox("Roundtrip", True)
            st.session_state['airfare_amt']= st.number_input("Airfare Amount", 0.0, 20000.0, 650.0, 1.0)
        if "Uber E110" in selected:
            st.subheader("Uber Details")
            st.session_state['uber_amt'] = st.number_input("Uber Amount", 0.0, 2000.0, 35.0, 0.5)

        if "Airfare E110" in selected:
            st.session_state['gen_airfare'] = st.checkbox("Generate Airfare Receipt", False)
        if "Uber E110" in selected:
            st.session_state['gen_uber'] = st.checkbox("Generate Uber Receipt", False)

        st.session_state["mandatory"] = selected

    # ---------- Export ----------
    with tab4:
        st.header("Export")

        # Generate Lines
        st.subheader("Generate Lines")
        if st.button("Generate Lines"):
            tks = load_timekeepers(st.session_state.get("tk_file")) or [
                {"TIMEKEEPER_NAME":"Smith, John","TIMEKEEPER_CLASSIFICATION":"PT","TIMEKEEPER_ID":"TK001","RATE":200.0},
                {"TIMEKEEPER_NAME":"Doe, Jane","TIMEKEEPER_CLASSIFICATION":"AS","TIMEKEEPER_ID":"TK002","RATE":150.0},
                {"TIMEKEEPER_NAME":"Lee, Chris","TIMEKEEPER_CLASSIFICATION":"PL","TIMEKEEPER_ID":"TK003","RATE":95.0},
            ]
            tasks = load_task_activity(st.session_state.get("task_file")) or DEFAULT_TASKS
            effective_tax = st.session_state["biv2"]["tax_rate"] if (ledes_version=="1998BI V2" and st.session_state.get("biv2")) else 0.0

            rows, subtotal, tax_total, grand_total = generate_lines(
                fee_count, expense_count, tks, client_id, law_firm_id, invoice_desc,
                start_date, end_date, tasks, effective_tax
            )

            # Append mandatory items based on chosen selections
            if "Airfare E110" in st.session_state.get("mandatory", []):
                amt = float(st.session_state.get("airfare_amt", 0.0)); tax_amt = round(amt*effective_tax, 2)
                rows.append({
                    "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id,
                    "LINE_ITEM_DATE": end_date.strftime("%Y-%m-%d"),
                    "TIMEKEEPER_NAME":"", "TIMEKEEPER_CLASSIFICATION":"", "TIMEKEEPER_ID":"",
                    "TASK_CODE":"", "ACTIVITY_CODE":"", "EXPENSE_CODE":"E110",
                    "DESCRIPTION": f"Airfare ({st.session_state.get('fare_class','Economy/Coach')}): "
                                   f"{st.session_state.get('airline','')} {st.session_state.get('flight_no','')}, "
                                   f"{st.session_state.get('dep_city','')} to {st.session_state.get('arr_city','')}"
                                   f"{' (Roundtrip)' if st.session_state.get('roundtrip',False) else ''}",
                    "HOURS":1, "RATE":amt, "LINE_ITEM_TOTAL":amt, "TAX_RATE":effective_tax, "TAX_AMOUNT":tax_amt
                })
                subtotal += amt; tax_total += tax_amt; grand_total = subtotal + tax_total

            if "Uber E110" in st.session_state.get("mandatory", []):
                amt = float(st.session_state.get("uber_amt", 0.0)); tax_amt = round(amt*effective_tax, 2)
                rows.append({
                    "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id,
                    "LINE_ITEM_DATE": end_date.strftime("%Y-%m-%d"),
                    "TIMEKEEPER_NAME":"", "TIMEKEEPER_CLASSIFICATION":"", "TIMEKEEPER_ID":"",
                    "TASK_CODE":"", "ACTIVITY_CODE":"", "EXPENSE_CODE":"E110",
                    "DESCRIPTION": "Uber ride to client's office",
                    "HOURS":1, "RATE":amt, "LINE_ITEM_TOTAL":amt, "TAX_RATE":effective_tax, "TAX_AMOUNT":tax_amt
                })
                subtotal += amt; tax_total += tax_amt; grand_total = subtotal + tax_total

            df = pd.DataFrame(rows)
            st.session_state["df"] = df
            st.session_state["totals"] = (subtotal, tax_total, grand_total)
            st.session_state["ctx"] = (invoice_number, matter_number, client_id, law_firm_id, client_name, law_firm_name, ledes_version)
            st.success(f"Generated {len(df)} lines.")
            st.dataframe(df, use_container_width=True, height=380)

            # Generate receipts on-demand and keep in memory for email
            receipts = {}
            if st.session_state.get("gen_airfare"):
                receipts["airfare_receipt.pdf"] = build_airfare_receipt(
                    st.session_state.get("airline","Airline"),
                    st.session_state.get("flight_no","XX000"),
                    st.session_state.get("dep_city","Origin"),
                    st.session_state.get("arr_city","Destination"),
                    st.session_state.get("fare_class","Economy/Coach"),
                    float(st.session_state.get("airfare_amt", 0.0)),
                    bool(st.session_state.get("roundtrip", False))
                )
            if st.session_state.get("gen_uber"):
                receipts["uber_receipt.pdf"] = build_uber_receipt(float(st.session_state.get("uber_amt", 0.0)))
            st.session_state["receipts_zip"] = zip_receipts(receipts) if receipts else None

        # Export Files
        st.subheader("Export Files")
        df = st.session_state.get("df")
        totals = st.session_state.get("totals")
        ctx = st.session_state.get("ctx")
        if df is not None and totals is not None and ctx is not None:
            invoice_number, matter_number, client_id, law_firm_id, client_name, law_firm_name, ledes_version_cached = ctx
            subtotal, tax_total, grand_total = totals

            if ledes_version_cached == "1998BI V2" and st.session_state.get("biv2"):
                b = st.session_state["biv2"]
                ledes_text = ledes_1998biv2_content(
                    df.to_dict(orient="records"),
                    start_date, end_date,
                    invoice_number, matter_number,
                    b["invoice_currency"], b["matter_name"], b["po_number"], b["client_matter_id"],
                    tax_type="VAT"
                )
                ledes_name = f"{invoice_number}_LEDES_1998BIV2.txt"
            else:
                ledes_text = ledes_1998b_content(
                    df.to_dict(orient="records"),
                    subtotal, start_date, end_date, invoice_number, matter_number
                )
                ledes_name = f"{invoice_number}_LEDES_1998B.txt"

            st.download_button("Download LEDES", data=ledes_text, file_name=ledes_name, mime="text/plain", key="dl_ledes")
            pdf_buf = build_invoice_pdf(
                df, subtotal, tax_total, grand_total,
                invoice_number, end_date, start_date, end_date,
                client_id, law_firm_id, client_name=client_name, law_firm_name=law_firm_name
            )
            st.download_button("Download PDF", data=pdf_buf.getvalue(), file_name=f"{invoice_number}.pdf", mime="application/pdf", key="dl_pdf")
            st.session_state["export_ledes_bytes"] = ledes_text.encode("utf-8")
            st.session_state["export_pdf_bytes"] = pdf_buf.getvalue()
        else:
            st.write("Generate lines to enable exports.")

        # Send via Email
        st.subheader("Send via Email")
        sender = st.text_input("From")
        recipient = st.text_input("To")
        subject = st.text_input("Subject", f"Invoice {st.session_state.get('ctx',[invoice_number])[0]}")
        body = st.text_area("Body", "Please find attached.")
        smtp_server = st.text_input("SMTP", "smtp.gmail.com")
        smtp_port = st.number_input("Port", min_value=1, max_value=65535, value=465)
        password = st.text_input("Password", type="password")
        attach_ledes = st.checkbox("Attach LEDES", True)
        attach_pdf   = st.checkbox("Attach PDF", True)
        attach_zip   = st.checkbox("Attach Receipts (zipped)", False)

        if st.button("Send Email"):
            atts: Dict[str, bytes] = {}
            if attach_ledes and st.session_state.get("export_ledes_bytes"):
                name = "invoice.ledes.txt"
                if st.session_state.get("ctx",["","", "", "", "", "", "1998B"])[6] == "1998BI V2":
                    name = f"{st.session_state.get('ctx')[0]}_LEDES_1998BIV2.txt"
                else:
                    name = f"{st.session_state.get('ctx')[0]}_LEDES_1998B.txt"
                atts[name] = st.session_state["export_ledes_bytes"]
            if attach_pdf and st.session_state.get("export_pdf_bytes"):
                atts[f"{st.session_state.get('ctx',[invoice_number])[0]}.pdf"] = st.session_state["export_pdf_bytes"]
            if attach_zip and st.session_state.get("receipts_zip"):
                atts["receipts.zip"] = st.session_state["receipts_zip"]

            if not atts:
                st.error("No attachments selected or available. Generate and export first.")
            elif not (sender and recipient and password):
                st.error("Please fill From, To, and Password.")
            else:
                ok, err = send_email(sender, recipient, subject, body, password, smtp_server, int(smtp_port), atts)
                if ok: st.success("Email sent successfully!")
                else:  st.error(f"Email failed: {err}")

if __name__ == "__main__":
    main()
