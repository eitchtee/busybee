import os
import pickle
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


def get_calendar_service(account_name, credentials_file, credentials_dir="credentials"):
    token_file = os.path.join(credentials_dir, f"{account_name}.pickle")
    creds = None

    if os.path.exists(token_file):
        with open(token_file, "rb") as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
            creds = flow.run_local_server(
                port=0,
                success_message=f"Success! You are now logged in as '{account_name}'.",
            )

        with open(token_file, "wb") as token:
            pickle.dump(creds, token)

    return build("calendar", "v3", credentials=creds)
