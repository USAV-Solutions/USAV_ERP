"""Bank statement PDF parsing utilities for accounting bank-convert."""

from __future__ import annotations

import logging
import re
from io import BytesIO

import pandas as pd
import pdfplumber

# Silence noisy PDF parser internals during conversion requests.
for _logger_name in ("pdfminer", "pdfminer.pdfinterp", "pdfminer.psparser", "pdfplumber"):
    logging.getLogger(_logger_name).setLevel(logging.WARNING)


def _clean_amount(amount: str) -> str:
    return amount.replace(" ", "").replace("$", "").replace(",", "")


def _format_mismatch_if_empty(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        raise ValueError("Format does not match selected bank")
    return df


def parse_boa_v1(pdf_bytes: bytes) -> pd.DataFrame:
    date_pattern = re.compile(r"^(\d{2}/\d{2})\s+(\d{2}/\d{2})\s+(.*)")
    amount_pattern = re.compile(r"([\-\s]*\$?[\d,]+\.\d{2})$")

    extracted_data: list[list[str]] = []
    statement_year = "25"
    current_date: str | None = None
    current_desc = ""
    current_amount = ""

    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        first_page_text = pdf.pages[0].extract_text() if pdf.pages else None
        if first_page_text:
            year_matches = re.findall(r"(20\d{2})", first_page_text)
            if year_matches:
                statement_year = year_matches[-1][-2:]

        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue

            for line in text.split("\n"):
                line = line.strip()
                if not line or "Posting Date" in line or "Transaction Date" in line or "Reference Number" in line:
                    continue

                match = date_pattern.match(line)
                if match:
                    if current_date:
                        extracted_data.append([current_date, current_desc.strip(), current_amount])

                    post_date = match.group(1)
                    current_date = f"{post_date}/{statement_year}"
                    remainder = match.group(3).strip()

                    amt_match = amount_pattern.search(remainder)
                    if amt_match:
                        current_amount = _clean_amount(amt_match.group(1))
                        current_desc = remainder[: amt_match.start()].strip()
                    else:
                        current_desc = remainder
                        current_amount = ""
                    continue

                if current_date:
                    amt_match = amount_pattern.search(line)
                    if amt_match and not current_amount:
                        current_amount = _clean_amount(amt_match.group(1))
                        line_without_amount = line[: amt_match.start()].strip()
                        if line_without_amount:
                            current_desc += f" {line_without_amount}"
                    elif "TOTAL" not in line and "Page" not in line:
                        current_desc += f" {line}"

    if current_date:
        extracted_data.append([current_date, current_desc.strip(), current_amount])

    df = pd.DataFrame(extracted_data, columns=["Date", "Description", "Amount"])
    if not df.empty:
        df["Description"] = df["Description"].apply(
            lambda x: re.sub(r"\b\d{23}\b", "", str(x)).strip() if pd.notnull(x) else x
        )
        df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce")
        df = df.dropna(subset=["Amount"])
    return _format_mismatch_if_empty(df)


def parse_boa_v2(pdf_bytes: bytes) -> pd.DataFrame:
    date_pattern = re.compile(r"^(\d{2}/\d{2}/\d{2})(?:\s+(.*))?$")
    amount_pattern = re.compile(r"([\-\s]*\$?[\d,]+\.\d{2})$")

    extracted_data: list[list[str]] = []
    current_account = "Unknown Account"
    current_category = "Unknown Category"
    current_date: str | None = None
    current_desc = ""
    current_amount = ""

    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue

            for line in text.split("\n"):
                line = line.strip()
                if not line:
                    continue
                if line in ["Date", "Description", "Amount", "Date Description Amount"]:
                    continue
                if "continued on the next page" in line.lower() or "page intentionally left blank" in line.lower():
                    continue
                if "Account #" in line or (line.startswith("Page ") and " of " in line):
                    continue
                if "TOTAL" in line or "Total" in line:
                    continue

                if "Your Adv Plus Banking" in line:
                    current_account = "Adv Plus Banking"
                    continue
                if "Your Regular Savings" in line:
                    current_account = "Regular Savings"
                    continue
                if "Deposits and other additions" in line:
                    current_category = "Deposits and other additions"
                    continue
                if "ATM and debit card subtractions" in line:
                    current_category = "ATM and debit card subtractions"
                    continue
                if "Other subtractions" in line and "Withdrawals" not in line:
                    current_category = "Other subtractions"
                    continue

                match = date_pattern.match(line)
                if match:
                    if current_date and current_amount:
                        extracted_data.append(
                            [current_account, current_category, current_date, current_desc.strip(), current_amount]
                        )
                    current_date = match.group(1)
                    remainder = match.group(2)

                    if remainder:
                        remainder = remainder.strip()
                        amt_match = amount_pattern.search(remainder)
                        if amt_match:
                            current_amount = _clean_amount(amt_match.group(1))
                            current_desc = remainder[: amt_match.start()].strip()
                        else:
                            current_desc = remainder
                            current_amount = ""
                    else:
                        current_desc = ""
                        current_amount = ""
                    continue

                if current_date:
                    amt_match = amount_pattern.search(line)
                    if amt_match and not current_amount:
                        current_amount = _clean_amount(amt_match.group(1))
                        line_without_amount = line[: amt_match.start()].strip()
                        if line_without_amount:
                            current_desc += f" {line_without_amount}"
                    else:
                        current_desc += f" {line}"

    if current_date and current_amount:
        extracted_data.append([current_account, current_category, current_date, current_desc.strip(), current_amount])

    df = pd.DataFrame(extracted_data, columns=["Account", "Category", "Date", "Description", "Amount"])
    if not df.empty:
        df["Description"] = df["Description"].apply(
            lambda x: re.sub(r"\b\d{23}\b", "", str(x)).strip() if pd.notnull(x) else x
        )
        df["Description"] = df["Description"].apply(lambda x: re.sub(r"\s+", " ", str(x)))
        df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce")
        df = df.dropna(subset=["Amount"])
    return _format_mismatch_if_empty(df)


def parse_boa_v3(pdf_bytes: bytes) -> pd.DataFrame:
    date_pattern = re.compile(r"^(\d{2}/\d{2}/\d{4})\s+(.*)")
    amount_pattern = re.compile(r"([\-\s\$]*[\d,]+\.\d{2}[\-\s\$]*)$")

    extracted_data: list[list[str]] = []
    current_date: str | None = None
    current_desc = ""
    current_amount = ""

    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue

            for line in text.split("\n"):
                line = line.strip()
                if not line or ("Date" in line and "Description" in line):
                    continue
                if "Bank of America | Online Banking" in line or "secure.bankofamerica.com" in line:
                    continue

                match = date_pattern.match(line)
                if match:
                    if current_date:
                        extracted_data.append([current_date, current_desc.strip(), current_amount])

                    current_date = match.group(1)
                    remainder = match.group(2).strip()
                    amt_match = amount_pattern.search(remainder)
                    if amt_match:
                        current_amount = re.sub(r"[^\d\.\-]", "", amt_match.group(1))
                        current_desc = remainder[: amt_match.start()].strip()
                    else:
                        current_desc = remainder
                        current_amount = ""
                    continue

                if current_date:
                    amt_match = amount_pattern.search(line)
                    if amt_match and not current_amount:
                        current_amount = re.sub(r"[^\d\.\-]", "", amt_match.group(1))
                        line_without_amount = line[: amt_match.start()].strip()
                        if line_without_amount:
                            current_desc += f" {line_without_amount}"
                    elif line not in ["$", "-$"]:
                        current_desc += f" {line}"

    if current_date:
        extracted_data.append([current_date, current_desc.strip(), current_amount])

    df = pd.DataFrame(extracted_data, columns=["Date", "Description", "Amount"])
    if not df.empty:
        df["Description"] = df["Description"].apply(
            lambda x: re.sub(r"\b\d{23}\b", "", str(x)).strip() if pd.notnull(x) else x
        )
        df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce")
        df = df.dropna(subset=["Amount"])
    return _format_mismatch_if_empty(df)


def parse_apple(pdf_bytes: bytes) -> pd.DataFrame:
    date_pattern = re.compile(r"^(\d{2}/\d{2}/\d{4})\s+(.*)")
    amount_pattern = re.compile(r"([\-\s]*\$?[\d,]+\.\d{2})$")

    extracted_data: list[list[str]] = []
    current_date: str | None = None
    current_desc = ""
    current_amount = ""

    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue

            for line in text.split("\n"):
                line = line.strip()
                if not line or line in ["Date", "Description", "Amount", "Daily Cash"]:
                    continue
                if "Apple Card is issued by" in line or "Goldman Sachs" in line or "Page " in line:
                    continue
                if "Total payments" in line or "Total charges" in line or "Total Daily Cash" in line:
                    continue

                match = date_pattern.match(line)
                if match:
                    if current_date:
                        extracted_data.append([current_date, current_desc.strip(), current_amount])

                    current_date = match.group(1)
                    remainder = match.group(2).strip()
                    amt_match = amount_pattern.search(remainder)
                    if amt_match:
                        current_amount = _clean_amount(amt_match.group(1))
                        current_desc = remainder[: amt_match.start()].strip()
                    else:
                        current_desc = remainder
                        current_amount = ""
                    continue

                if current_date:
                    amt_match = amount_pattern.search(line)
                    if amt_match and not current_amount:
                        current_amount = _clean_amount(amt_match.group(1))
                        line_without_amount = line[: amt_match.start()].strip()
                        if line_without_amount:
                            current_desc += f" {line_without_amount}"
                    else:
                        current_desc += f" {line}"

    if current_date:
        extracted_data.append([current_date, current_desc.strip(), current_amount])

    df = pd.DataFrame(extracted_data, columns=["Date", "Description", "Amount"])
    if not df.empty:
        df["Description"] = df["Description"].apply(
            lambda x: re.sub(r"\$?\d+\.\d{2}\s*\d+%\s*$", "", str(x)).strip() if pd.notnull(x) else x
        )
        df["Description"] = df["Description"].apply(
            lambda x: re.sub(r"\b\d+%\s*$", "", str(x)).strip() if pd.notnull(x) else x
        )
        df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce")
        df = df.dropna(subset=["Amount"])
    return _format_mismatch_if_empty(df)


def parse_chase(pdf_bytes: bytes) -> pd.DataFrame:
    date_pattern = re.compile(r"^(\d{2}/\d{2})\s+(.*)")
    amount_pattern = re.compile(r"([\-\s]*\$?[\d,]+\.\d{2})$")

    extracted_data: list[list[str]] = []
    statement_month = "01"
    statement_year = "25"
    current_date: str | None = None
    current_desc = ""
    current_amount = ""
    in_activity_section = False

    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        first_page_text = pdf.pages[0].extract_text() if pdf.pages else None
        if first_page_text:
            date_match = re.search(r"(\d{2})/\d{2}/(\d{2})", first_page_text)
            if date_match:
                statement_month = date_match.group(1)
                statement_year = date_match.group(2)

        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue

            for line in text.split("\n"):
                line = line.strip()
                if "Merchant Name or Transaction Description" in line:
                    in_activity_section = "Rewards" not in line
                    continue
                if "Totals Year-to-Date" in line or "Year-to-Date" in line or "IINNTTEERREESSTT" in line:
                    in_activity_section = False
                if not in_activity_section:
                    continue
                if (
                    not line
                    or "Date of" in line
                    or "Transaction" in line
                    or "PAYMENTS AND OTHER CREDITS" in line
                    or line in ["PURCHASE", "PURCHASES"]
                ):
                    continue

                match = date_pattern.match(line)
                if match:
                    if current_date:
                        extracted_data.append([current_date, current_desc.strip(), current_amount])

                    post_date = match.group(1)
                    txn_month = post_date.split("/")[0]
                    txn_year = statement_year
                    if statement_month == "01" and txn_month == "12":
                        txn_year = str(int(statement_year) - 1).zfill(2)
                    current_date = f"{post_date}/20{txn_year}"

                    remainder = match.group(2).strip()
                    amt_match = amount_pattern.search(remainder)
                    if amt_match:
                        current_amount = _clean_amount(amt_match.group(1))
                        current_desc = remainder[: amt_match.start()].strip()
                    else:
                        current_desc = remainder
                        current_amount = ""
                    continue

                if current_date:
                    amt_match = amount_pattern.search(line)
                    if amt_match and not current_amount:
                        current_amount = _clean_amount(amt_match.group(1))
                        line_without_amount = line[: amt_match.start()].strip()
                        if line_without_amount:
                            current_desc += f" {line_without_amount}"
                    else:
                        current_desc += f" {line}"

    if current_date and current_amount:
        extracted_data.append([current_date, current_desc.strip(), current_amount])

    df = pd.DataFrame(extracted_data, columns=["Date", "Description", "Amount"])
    if not df.empty:
        df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce")
        df = df.dropna(subset=["Amount"])
    return _format_mismatch_if_empty(df)


def parse_amazon(pdf_bytes: bytes) -> pd.DataFrame:
    def clean_currency(value_str: str) -> float:
        clean_str = str(value_str).replace("$", "").replace(",", "").strip()
        if not clean_str:
            return 0.0
        try:
            return float(clean_str)
        except ValueError:
            return 0.0

    statement_data: dict[str, object] = {}
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        if not pdf.pages:
            raise ValueError("Format does not match selected bank")
        text = pdf.pages[0].extract_text(layout=True)
        if not text:
            raise ValueError("Format does not match selected bank")

        period_match = re.search(r"(\d{1,2}/\d{1,2}/\d{4}\s*-\s*\d{1,2}/\d{1,2}/\d{4})", text)
        if period_match:
            statement_data["Settlement Period"] = period_match.group(1)

        date_match = re.search(r"on\s+(\d{1,2}/\d{1,2}/\d{4})", text)
        if date_match:
            statement_data["Payment Date"] = date_match.group(1)

        main_categories = ["Sales", "Refunds", "Expenses"]
        current_category: str | None = None

        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue

            for cat in main_categories:
                if line.startswith(cat):
                    current_category = cat
                    break

            amounts = re.findall(r"-?\$?\s*[0-9,]+\.[0-9]{2}", line)
            if not amounts:
                continue

            amount_str = amounts[0]
            label = re.sub(r"\s+", " ", line.split(amount_str)[0].strip())
            if not label:
                continue

            value = clean_currency(amount_str)
            if label in ["Beginning Balance", "Net Proceeds", "Account Level Reserve"]:
                statement_data[label] = value
                current_category = None
            elif label in main_categories:
                statement_data[f"{label} (Total)"] = value
            else:
                col_name = f"{current_category}: {label}" if current_category else label
                statement_data[col_name] = value

    df = pd.DataFrame([statement_data]) if statement_data else pd.DataFrame()
    return _format_mismatch_if_empty(df)


BANK_CONVERT_PARSERS = {
    "boa_v1": parse_boa_v1,
    "boa_v2": parse_boa_v2,
    "boa_v3": parse_boa_v3,
    "amazon": parse_amazon,
    "apple": parse_apple,
    "chase": parse_chase,
}
