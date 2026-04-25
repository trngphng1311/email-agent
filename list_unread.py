"""Milestone 1 — Gmail Hello World.

Lists the last 10 unread messages in your inbox. The first run opens a browser
so you can log in with Google and approve read-only Gmail access. A token is
then cached locally in token.json so later runs don't prompt again.
"""
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
ROOT = Path(__file__).parent
CREDS_PATH = ROOT / "credentials.json"
TOKEN_PATH = ROOT / "token.json"


def get_service():
    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDS_PATH.exists():
                raise FileNotFoundError(
                    f"Missing {CREDS_PATH}. Download the OAuth client JSON from "
                    "Google Cloud Console → APIs & Services → Credentials, and "
                    "save it here as 'credentials.json'."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_PATH), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.write_text(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def list_unread(max_results: int = 10) -> None:
    service = get_service()
    result = (
        service.users()
        .messages()
        .list(userId="me", q="is:unread", maxResults=max_results)
        .execute()
    )
    messages = result.get("messages", [])
    if not messages:
        print("No unread messages.")
        return

    print(f"Last {len(messages)} unread messages:\n")
    for i, msg in enumerate(messages, 1):
        full = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=msg["id"],
                format="metadata",
                metadataHeaders=["Subject", "From", "Date"],
            )
            .execute()
        )
        headers = {h["name"]: h["value"] for h in full["payload"]["headers"]}
        subject = headers.get("Subject", "(no subject)")
        sender = headers.get("From", "(unknown sender)")
        date = headers.get("Date", "")
        print(f"{i}. {subject}")
        print(f"   From: {sender}")
        print(f"   Date: {date}\n")


if __name__ == "__main__":
    list_unread()
