"""Google Sheets access with a service account (key in GOOGLE_SERVICE_ACCOUNT_JSON)."""
from __future__ import annotations

import json
import os
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials

from . import config

# Most useful columns first. "Priority" (1 direct ask ... 4 marketing hiring) keeps the tab sorted.
BRAND_HEADERS = ["Brand / Company", "Signal", "Why Added", "Why Kept", "Market", "Looking For", "Source", "Post / Job URL",
                 "Posted On", "Added At (IST)", "Company LinkedIn", "Posted By", "Poster Profile", "Poster Headline",
                 "Platforms Mentioned", "Matched Text", "Post Text", "Agencies in Comments", "Creators in Comments",
                 "Priority"]
REMOVED_HEADERS = ["Removed At (IST)", "From Tab", "Reason Removed"] + [h for h in BRAND_HEADERS if h != "Why Kept"]
PEOPLE_HEADERS = ["Added At (IST)", "Name", "Company (from comment)", "Public Contact", "Profile", "Headline", "Page Type",
                  "Country", "Found Via", "Comment / Post", "Brand", "Brand Post URL"]


def fmt_time(dt: datetime | None) -> str:
    return dt.astimezone(config.IST).strftime("%Y-%m-%d %H:%M") if dt else ""


def fmt_date(dt: datetime | None) -> str:
    return dt.astimezone(config.IST).strftime("%Y-%m-%d") if dt else ""


def _client() -> gspread.Client:
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    info = json.loads(raw) if raw else json.load(open("service_account.json"))
    creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    return gspread.authorize(creds)


class Tab:
    """A worksheet addressed by header names; created with its headers if missing. Writes are RAW."""

    def __init__(self, book: gspread.Spreadsheet, title: str, headers: list[str]):
        try:
            self.ws = book.worksheet(title)
        except gspread.WorksheetNotFound:
            self.ws = book.add_worksheet(title=title, rows=1000, cols=len(headers))
        current = self.ws.row_values(1)
        if not any(current):
            self.ws.update(values=[headers], range_name="A1", value_input_option="RAW")
            self.ws.freeze(rows=1)
            current = list(headers)
        missing = [h for h in headers if h not in current]
        if missing:
            current += missing
            if self.ws.col_count < len(current):
                self.ws.add_cols(len(current) - self.ws.col_count)
            self.ws.update(values=[current], range_name="A1", value_input_option="RAW")
        self.headers = current

    def rows(self) -> list[dict]:
        """Every non-empty row as {header: value}, plus "_row" (its sheet row number)."""
        values = self.ws.get_all_values()
        return [{**{h: (r[i] if i < len(r) else "") for i, h in enumerate(self.headers)}, "_row": n}
                for n, r in enumerate(values[1:], start=2) if any(r)]

    def set_cells(self, updates: list[tuple[int, str, str]]):
        """(sheet row, header, value) cell writes, sent in batches."""
        from gspread.utils import rowcol_to_a1
        data = [{"range": rowcol_to_a1(row, self.headers.index(h) + 1), "values": [[v]]} for row, h, v in updates]
        for i in range(0, len(data), 500):
            self.ws.batch_update(data[i:i + 500], value_input_option="RAW")

    def sort_rows(self, *by: tuple[str, str]):
        """Sort the data rows (header stays on top), e.g. sort_rows(("Priority", "asc"), ("Added At (IST)", "des"))."""
        from gspread.utils import rowcol_to_a1
        last = rowcol_to_a1(max(self.ws.row_count, 2), len(self.headers))
        self.ws.sort(*[(self.headers.index(h) + 1, d) for h, d in by], range=f"A2:{last}")

    def append(self, records: list[dict]):
        if records:
            self.ws.append_rows([[str(r.get(h, ""))[:5000] for h in self.headers] for r in records],
                                value_input_option="RAW", insert_data_option="INSERT_ROWS", table_range="A1")


class Book:
    def __init__(self, sheet_id: str = config.SHEET_ID):
        book = _client().open_by_key(sheet_id)
        self.brands = Tab(book, config.BRANDS_TAB, BRAND_HEADERS)
        self.agencies = Tab(book, config.AGENCIES_TAB, PEOPLE_HEADERS)
        self.creators = Tab(book, config.CREATORS_TAB, PEOPLE_HEADERS)
        self.removed = Tab(book, config.REMOVED_TAB, REMOVED_HEADERS)
