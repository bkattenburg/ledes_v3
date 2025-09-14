
# app_streamlit_1998biv2_full.py
# Full Streamlit app to generate LEDES 1998B and 1998BIv2 invoices

import streamlit as st
import pandas as pd
import datetime
import io
from typing import List, Dict
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
from reportlab.lib.units import inch

st.set_page_config(page_title="LEDES Invoices (1998B & 1998BIv2)", layout="wide")

st.title("LEDES Invoices")
st.caption("Generate LEDES 1998B or 1998BIv2 invoices and a PDF preview.")

# -------------------------
# Helper: LEDES 1998B (basic)
# -------------------------
def _create_ledes_line_1998b(row: Dict, line_no: int, inv_total: float,
                             bill_start: datetime.date, bill_end: datetime.date,
                             invoice_number: str, matter_number: str) -> List[str]:
    date_obj = datetime.datetime.strptime(row["LINE_ITEM_DATE"], "%Y-%m-%d").date()
    hours = float(row["HOURS"])
    rate = float(row["RATE"])
    line_total = float(row["LINE_ITEM_TOTAL"])
    is_expense = bool(row.get("EXPENSE_CODE", ""))
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
        timekeeper_class
    ]

def _create_ledes_1998b_content(rows: List[Dict], inv_total: float,
                                bill_start: datetime.date, bill_end: datetime.date,
                                invoice_number: str, matter_number: str) -> str:
    header = "LEDES1998B[]"
    fields = ("INVOICE_DATE|INVOICE_NUMBER|CLIENT_ID|LAW_FIRM_MATTER_ID|INVOICE_TOTAL|"
              "BILLING_START_DATE|BILLING_END_DATE|INVOICE_DESCRIPTION|LINE_ITEM_NUMBER|"
              "EXP/FEE/INV_ADJ_TYPE|LINE_ITEM_NUMBER_OF_UNITS|LINE_ITEM_ADJUSTMENT_AMOUNT|"
              "LINE_ITEM_TOTAL|LINE_ITEM_DATE|LINE_ITEM_TASK_CODE|LINE_ITEM_EXPENSE_CODE|"
              "LINE_ITEM_ACTIVITY_CODE|TIMEKEEPER_ID|LINE_ITEM_DESCRIPTION|LAW_FIRM_ID|"
              "LINE_ITEM_UNIT_COST|TIMEKEEPER_NAME|TIMEKEEPER_CLASSIFICATION[]")
    lines = [header, fields]
    for i, row in enumerate(rows, start=1):
        line = _create_ledes_line_1998b(row, i, inv_total, bill_start, bill_end, invoice_number, matter_number)
        lines.append("|".join(map(str, line)) + "[]")
    return "\n".join(lines)

# -------------------------
# LEDES 1998BIv2
# -------------------------
def _create_ledes_line_1998biv2(row: Dict, line_no: int, inv_total: float,
                                bill_start: datetime.date, bill_end: datetime.date,
                                invoice_number: str, matter_number: str,
                                matter_name: str, po_number: str,
                                client_matter_id: str, invoice_currency: str,
                                tax_rate: float) -> List[str]:
    date_obj = datetime.datetime.strptime(row["LINE_ITEM_DATE"], "%Y-%m-%d").date()
    hours = float(row["HOURS"])
    rate = float(row["RATE"])
    line_total = float(row["LINE_ITEM_TOTAL"])
    is_expense = bool(row.get("EXPENSE_CODE", ""))
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
        client_matter_id,
        matter_name,
        po_number,
        invoice_currency,
        f"{tax_rate:.2f}"
    ]

def _create_ledes_1998biv2_content(rows: List[Dict], bill_start: datetime.date, bill_end: datetime.date,
                                   invoice_number: str, matter_number: str,
                                   matter_name: str, po_number: str,
                                   client_matter_id: str, invoice_currency: str,
                                   tax_rate: float) -> str:
    header = "LEDES1998BIv2[]"
    fields = ("INVOICE_DATE|INVOICE_NUMBER|CLIENT_ID|LAW_FIRM_MATTER_ID|INVOICE_TOTAL|"
              "BILLING_START_DATE|BILLING_END_DATE|INVOICE_DESCRIPTION|LINE_ITEM_NUMBER|"
              "EXP/FEE/INV_ADJ_TYPE|LINE_ITEM_NUMBER_OF_UNITS|LINE_ITEM_ADJUSTMENT_AMOUNT|"
              "LINE_ITEM_TOTAL|LINE_ITEM_DATE|LINE_ITEM_TASK_CODE|LINE_ITEM_EXPENSE_CODE|"
              "LINE_ITEM_ACTIVITY_CODE|TIMEKEEPER_ID|LINE_ITEM_DESCRIPTION|LAW_FIRM_ID|"
              "LINE_ITEM_UNIT_COST|TIMEKEEPER_NAME|TIMEKEEPER_CLASSIFICATION|CLIENT_MATTER_ID|"
              "MATTER_NAME|PO_NUMBER|INVOICE_CURRENCY|TAX_RATE[]")
    lines = [header, fields]

    subtotal = sum(float(r["LINE_ITEM_TOTAL"]) for r in rows)
    tax_amount = round(subtotal * float(tax_rate), 2)
    grand_total = subtotal + tax_amount

    for i, row in enumerate(rows, start=1):
        line = _create_ledes_line_1998biv2(row, i, grand_total, bill_start, bill_end,
                                           invoice_number, matter_number,
                                           matter_name, po_number, client_matter_id,
                                           invoice_currency, tax_rate)
        lines.append("|".join(map(str, line)) + "[]")
    return "\n".join(lines)

# -------------------------
# PDF (corrected tax_data)
# -------------------------
def _create_pdf_invoice(
    df: pd.DataFrame,
    invoice_number: str,
    invoice_date: datetime.date,
    billing_start_date: datetime.date,
    billing_end_date: datetime.date,
    client_id: str,
    law_firm_id: str,
    client_name: str = "",
    law_firm_name: str = "",
    ledes_version: str = "1998B",
    matter_name: str = "",
    po_number: str = "",
    client_matter_id: str = "",
    invoice_currency: str = "USD",
    tax_rate: float = 0.19
) -> io.BytesIO:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
    elements = []
    styles = getSampleStyleSheet()

    law_firm_para = Paragraph(f"{law_firm_name or 'Law Firm'}<br/>{law_firm_id}", styles['Normal'])
    client_para = Paragraph(f"{client_name or 'Client'}<br/>{client_id}", styles['Normal'])
    header_table = Table([[law_firm_para, client_para]], colWidths=[3.5 * inch, 4.0 * inch])
    elements.append(header_table)
    elements.append(Spacer(1, 0.15 * inch))

    invoice_info = (f"Invoice #: {invoice_number}<br/>"
                    f"Invoice Date: {invoice_date.strftime('%Y-%m-%d')}<br/>"
                    f"Billing Period: {billing_start_date.strftime('%Y-%m-%d')} "
                    f"to {billing_end_date.strftime('%Y-%m-%d')}")
    elements.append(Paragraph(invoice_info, styles['Normal']))
    elements.append(Spacer(1, 0.15 * inch))

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

    doc.build(elements)
    buffer.seek(0)
    return buffer

# -------------------------
# GUI
# -------------------------
tabs = ["Data Sources", "Invoice Details", "Fees & Expenses", "Output"]
tab_objs = st.tabs(tabs)

# Data Sources
with tab_objs[0]:
    uploaded = st.file_uploader("Upload CSV of line items", type=["csv"])
    if uploaded:
        df = pd.read_csv(uploaded)
    else:
        df = pd.DataFrame([
            {"LINE_ITEM_DATE":"2025-09-01","HOURS":5.0,"RATE":200.0,"LINE_ITEM_TOTAL":1000.0,"EXPENSE_CODE":"","TASK_CODE":"L100","ACTIVITY_CODE":"A101","TIMEKEEPER_ID":"TK1","TIMEKEEPER_CLASSIFICATION":"Partner","TIMEKEEPER_NAME":"John Smith","DESCRIPTION":"Research and drafting","CLIENT_ID":"CL001","LAW_FIRM_ID":"LF001","INVOICE_DESCRIPTION":"Monthly legal services"},
            {"LINE_ITEM_DATE":"2025-09-02","HOURS":1.0,"RATE":500.0,"LINE_ITEM_TOTAL":500.0,"EXPENSE_CODE":"E110","TASK_CODE":"","ACTIVITY_CODE":"","TIMEKEEPER_ID":"","TIMEKEEPER_CLASSIFICATION":"","TIMEKEEPER_NAME":"","DESCRIPTION":"Airfare receipt","CLIENT_ID":"CL001","LAW_FIRM_ID":"LF001","INVOICE_DESCRIPTION":"Monthly legal services"}
        ])
    st.dataframe(df)

# Invoice Details
with tab_objs[1]:
    ledes_version = st.selectbox("LEDES Version:", ["1998B", "1998BIv2"])
    invoice_number = st.text_input("Invoice Number", value="INV-1001")
    matter_number = st.text_input("Law Firm Matter ID", value="MAT-123")
    client_id = st.text_input("Client ID", value="CL001")
    law_firm_id = st.text_input("Law Firm ID", value="LF001")
    client_name = st.text_input("Client Name", value="Test Client")
    law_firm_name = st.text_input("Law Firm Name", value="Test Law Firm")
    billing_start_date = st.date_input("Billing Start Date", value=datetime.date(2025,9,1))
    billing_end_date = st.date_input("Billing End Date", value=datetime.date(2025,9,30))
    invoice_date = st.date_input("Invoice Date", value=datetime.date.today())

# Fees & Expenses
with tab_objs[2]:
    st.metric("Rows", len(df))
    st.write("Totals in CSV: $", float(df["LINE_ITEM_TOTAL"].sum()))

# Output
with tab_objs[3]:
    if ledes_version == "1998BIv2":
        st.subheader("Tax Fields")
        matter_name = st.text_input("Matter Name *", value="Sample Matter")
        po_number = st.text_input("PO Number (optional)", value="PO-789")
        client_matter_id = st.text_input("Client Matter ID (optional)", value="CM-456")
        invoice_currency = st.selectbox("Invoice Currency", ["USD","AUD","CAD","GBP","EUR"], index=0)
        tax_rate = st.number_input("Tax Rate", min_value=0.0, max_value=1.0, step=0.01, value=0.19)
    else:
        matter_name = po_number = client_matter_id = ""
        invoice_currency = "USD"; tax_rate = 0.0

    if st.button("Download LEDES"):
        rows = df.to_dict(orient="records")
        if ledes_version == "1998BIv2":
            ledes_text = _create_ledes_1998biv2_content(rows, billing_start_date, billing_end_date,
                                                        invoice_number, matter_number,
                                                        matter_name, po_number, client_matter_id,
                                                        invoice_currency, tax_rate)
        else:
            inv_total = float(df["LINE_ITEM_TOTAL"].sum())
            ledes_text = _create_ledes_1998b_content(rows, inv_total, billing_start_date, billing_end_date,
                                                     invoice_number, matter_number)
        st.download_button("Save LEDES File", data=ledes_text, file_name=f"{invoice_number}_{ledes_version}.txt", mime="text/plain")

    if st.button("Download PDF"):
        pdf_buf = _create_pdf_invoice(df, invoice_number=invoice_number, invoice_date=invoice_date,
                                      billing_start_date=billing_start_date, billing_end_date=billing_end_date,
                                      client_id=client_id, law_firm_id=law_firm_id,
                                      client_name=client_name, law_firm_name=law_firm_name,
                                      ledes_version=ledes_version, matter_name=matter_name, po_number=po_number,
                                      client_matter_id=client_matter_id, invoice_currency=invoice_currency, tax_rate=tax_rate)
        st.download_button("Save PDF", data=pdf_buf.getvalue(), file_name=f"{invoice_number}_{ledes_version}.pdf", mime="application/pdf")
