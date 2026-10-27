"""Refresh the existing Employee Work Mode worksheet from Zoho People Plus."""
import ast
import hashlib
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit

import gspread
import requests

BATCH_SIZE = 200
TAB_NAME = 'Employee Work Mode'
FIELD_ORDER = ['Employee ID', 'First Name (As per Aadhaar)', 'Last Name (As per Aadhaar)', 'Full Name', 'Designation', 'Email Address', 'Contact Number', 'Department', 'Sub Department', 'Business Unit', 'Date of Joining', 'Reporting Manager', 'Employment Type', 'Blood Group', 'Employee Status', 'Photo', 'Location', 'Company', 'Primary Program Tag', 'Secondary Program Tag', 'Employee Work Location', 'Email Signature Name', 'Email Signature Phone Number', 'Email Signature Phone Number 2', 'Include Phone Number in Email Signature?', 'ID Card Number', 'ID Card Issued to Employee', 'Finger Print Provided to Employee']

IST = timezone(timedelta(hours=5, minutes=30))


def required_secret(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing GitHub Actions secret: {name}")
    return value


def parse_field_details(value):
    if isinstance(value, list):
        return ["" if v is None else str(v).strip() for v in value]
    if isinstance(value, str):
        for parser in (json.loads, ast.literal_eval):
            try:
                parsed = parser(value)
                if isinstance(parsed, list):
                    return ["" if v is None else str(v).strip() for v in parsed]
            except (ValueError, SyntaxError):
                pass
    raise RuntimeError("Unexpected Zoho fieldDetails format; worksheet left unchanged.")


def clean_value(value):
    if value is None or str(value).strip() in ("None", "null", "[]", "", "''"):
        return ""
    value = str(value).strip().strip("\'\"")
    if ";" in value:
        value = ", ".join(v.strip() for v in value.split(";") if v.strip())
    return value


def fetch_records(cookies, csrf):
    zoho_url = required_secret("ZOHO_URL")
    form_id = required_secret("ZOHO_FORM_ID")
    view_id = required_secret("ZOHO_VIEW_ID")
    parsed_url = urlsplit(zoho_url)
    if parsed_url.scheme != "https" or parsed_url.hostname != "peopleplus.zoho.in":
        raise RuntimeError("ZOHO_URL must use HTTPS on peopleplus.zoho.in.")
    origin = f"{parsed_url.scheme}://{parsed_url.netloc}"
    referer = zoho_url.rsplit("/", 1)[0] + "/zp"
    all_records = []
    seen_pages = set()
    record_key = None
    start = 1
    with requests.Session() as session:
        session.headers.update({
            "Cookie": cookies,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": origin,
            "Referer": referer,
            "User-Agent": "Mozilla/5.0",
            "X-Requested-With": "XMLHttpRequest",
        })
        for page in range(1, 1001):
            try:
                response = session.post(zoho_url, data={
                    "formId": form_id, "viewId": view_id,
                    "isOnload": "true" if page == 1 else "false",
                    "mode": "fetchRecords", "startInd": str(start),
                    "employeeStatus": "all", "conreqcsr": csrf,
                }, timeout=(15, 90), allow_redirects=False)
                if response.status_code != 200:
                    raise RuntimeError(f"Zoho returned HTTP {response.status_code}. Refresh Zoho secrets if the session expired.")
                message = response.json()["recordDetails"]["message"]
                if not isinstance(message, dict):
                    raise ValueError("Invalid message")
            except (ValueError, KeyError, TypeError):
                raise RuntimeError("Zoho returned an unexpected response. Refresh the Zoho cookies and CSRF token.") from None
            if record_key is None:
                candidates = [(key, values) for key, values in message.items()
                              if isinstance(values, list) and values
                              and all(isinstance(item, dict) and "fieldDetails" in item for item in values)]
                if len(candidates) != 1:
                    raise RuntimeError("Cannot identify employee records unambiguously; worksheet left unchanged.")
                record_key = candidates[0][0]
            records = message.get(record_key)
            if not isinstance(records, list):
                raise RuntimeError("Employee records missing from a page; worksheet left unchanged.")
            if not records:
                if not all_records:
                    raise RuntimeError("Zoho returned no employees; worksheet left unchanged.")
                return all_records
            if not all(isinstance(item, dict) and "fieldDetails" in item for item in records):
                raise RuntimeError("Invalid employee page; worksheet left unchanged.")
            fingerprint = hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest()
            if fingerprint in seen_pages:
                raise RuntimeError("Zoho repeated a page; stopped to avoid an incomplete or duplicate export.")
            seen_pages.add(fingerprint)
            all_records.extend(records)
            print(f"Fetched page {page}: {len(records)} employees (total {len(all_records)}).")
            # Advance by the actual page length, rather than assuming the server page size.
            start += len(records)
    raise RuntimeError("Zoho exceeded the page limit; worksheet left unchanged.")


def build_values(records):
    if not records:
        raise RuntimeError("Refusing to replace the worksheet with an empty export.")
    fields = [parse_field_details(record["fieldDetails"]) for record in records]
    if any(not row for row in fields):
        raise RuntimeError("An employee has no fields; worksheet left unchanged.")
    width = max(len(FIELD_ORDER), max(map(len, fields)))
    headers = list(FIELD_ORDER) + [f"Field_{i}" for i in range(len(FIELD_ORDER), width)]
    stamp = datetime.now(IST).strftime("%d-%m-%Y %I:%M %p")
    values = [headers + [f"Last updated: {stamp} IST"]]
    for row in fields:
        values.append([clean_value(v) for v in row] + [""] * (width - len(row) + 1))
    return values


def write_values(client, values):
    spreadsheet = client.open_by_key(required_secret("GOOGLE_SHEET_ID"))
    try:
        sheet = spreadsheet.worksheet(TAB_NAME)
    except gspread.WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(title=TAB_NAME, rows=max(2000, len(values)), cols=max(30, len(values[0])))
    row_count = max(sheet.row_count, len(values))
    col_count = max(sheet.col_count, len(values[0]))
    # All values, stale-cell cleanup and formatting are committed in one atomic Sheets request.
    # Using stringValue keeps IDs, phone numbers and formula-like source text literal.
    spreadsheet.batch_update({"requests": [
        {"updateSheetProperties": {"properties": {
            "sheetId": sheet.id, "gridProperties": {"rowCount": row_count,
            "columnCount": col_count, "frozenRowCount": 1}},
            "fields": "gridProperties.rowCount,gridProperties.columnCount,gridProperties.frozenRowCount"}},
        {"updateCells": {"range": {"sheetId": sheet.id, "startRowIndex": 0,
            "endRowIndex": row_count, "startColumnIndex": 0, "endColumnIndex": col_count},
            "rows": [{"values": [{"userEnteredValue": {"stringValue": str(value)}}
                                  for value in row]} for row in values],
            "fields": "userEnteredValue"}},
        {"repeatCell": {"range": {"sheetId": sheet.id, "startRowIndex": 0,
            "endRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": len(values[0])},
            "cell": {"userEnteredFormat": {
                "backgroundColor": {"red": 0.18, "green": 0.49, "blue": 0.20},
                "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}}}},
            "fields": "userEnteredFormat.backgroundColor,userEnteredFormat.textFormat"}},
    ]})


def main():
    cookies = required_secret("ZOHO_COOKIES")
    csrf = required_secret("ZOHO_CSRF_TOKEN")
    try:
        credentials = json.loads(required_secret("GOOGLE_SERVICE_ACCOUNT_JSON"))
        client = gspread.service_account_from_dict(credentials, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    except (ValueError, KeyError):
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON must contain a valid service account JSON key.") from None
    records = fetch_records(cookies, csrf)
    values = build_values(records)
    write_values(client, values)
    print(f"Updated {len(records)} employees in '{TAB_NAME}'.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Third-party errors can contain employee data or request credentials. Keep logs generic.
        print("Sync failed. Check the seven Actions secrets, Zoho session validity, and service-account sheet access. No response bodies or employee data are logged.", file=sys.stderr)
        sys.exit(1)
