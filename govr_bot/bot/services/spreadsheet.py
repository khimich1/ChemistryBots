import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import os

SPREADSHEET_NAME = "Ответы по химии"
CREDENTIALS_FILE = "credentials.json"
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

def _get_sheet():
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, SCOPE)
    client = gspread.authorize(creds)
    return client.open(SPREADSHEET_NAME).sheet1

def save_answer(user_id: int, fullname: str, topic: str, transcript: str, feedback: str):
    sheet = _get_sheet()
    sheet.append_row([
        fullname,
        str(user_id),
        topic,
        transcript,
        feedback,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ])

def fetch_user_records(user_id: int) -> list[dict]:
    sheet = _get_sheet()
    rows = sheet.get_all_records()
    return [r for r in rows if str(r["Telegram ID"]) == str(user_id)]
