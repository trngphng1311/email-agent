"""Gmail auth + fetch helpers shared across the project."""
import base64
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]  # read + send + label
ROOT = Path(__file__).parent
CREDS_PATH = ROOT / "credentials.json"
TOKEN_PATH = ROOT / "token.json"


def get_service():
    creds = None
    if TOKEN_PATH.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
            if not set(SCOPES).issubset(set(creds.scopes or [])):
                creds = None
        except Exception:
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDS_PATH.exists():
                raise FileNotFoundError(
                    f"Missing {CREDS_PATH}. Download OAuth client JSON from "
                    "Google Cloud Console → APIs & Services → Credentials."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_PATH), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.write_text(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def get_user_email(service) -> str:
    profile = service.users().getProfile(userId="me").execute()
    return profile.get("emailAddress", "")


def fetch_thread(service, thread_id: str) -> dict:
    return (
        service.users()
        .threads()
        .get(userId="me", id=thread_id, format="metadata",
             metadataHeaders=["From", "To", "Date", "Subject"])
        .execute()
    )


def fetch_thread_full(service, thread_id: str) -> list[dict]:
    """Return every message in a thread, each parsed into our dict shape."""
    thread = (
        service.users()
        .threads()
        .get(userId="me", id=thread_id, format="full")
        .execute()
    )
    return [_parse(m) for m in thread.get("messages", [])]


def send_reply(
    service,
    to: str,
    subject: str,
    body_text: str,
    thread_id: str,
    in_reply_to: str,
    bcc: str = "",
) -> dict:
    """Send a reply that threads under the original message.

    Args:
        to: primary recipient (parsed From header of original message)
        subject: original subject (will be prefixed with 'Re: ' if missing)
        body_text: plain-text reply body
        thread_id: Gmail thread ID to attach reply to
        in_reply_to: original message's Message-Id header (with angle brackets)
        bcc: optional comma-separated BCC addresses
    """
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["To"] = to
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"
    msg["Subject"] = subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    if bcc.strip():
        msg["Bcc"] = bcc.strip()
    msg.set_content(body_text)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    return (
        service.users()
        .messages()
        .send(userId="me", body={"raw": raw, "threadId": thread_id})
        .execute()
    )


def fetch_unread(service, max_results: int = 10) -> list[dict]:
    result = (
        service.users()
        .messages()
        .list(userId="me", q="is:unread", maxResults=max_results)
        .execute()
    )
    ids = [m["id"] for m in result.get("messages", [])]
    emails = []
    for mid in ids:
        emails.append(fetch_message(service, mid))
    return emails


def list_message_ids(service, query: str | None, max_results: int, page_token: str | None):
    """Return (ids, next_page_token). Used by the bulk-import script."""
    req = {"userId": "me", "maxResults": max_results}
    if query:
        req["q"] = query
    if page_token:
        req["pageToken"] = page_token
    result = service.users().messages().list(**req).execute()
    ids = [m["id"] for m in result.get("messages", [])]
    return ids, result.get("nextPageToken")


def fetch_message(service, message_id: str) -> dict:
    """Fetch + parse a single email by ID."""
    full = (
        service.users()
        .messages()
        .get(userId="me", id=message_id, format="full")
        .execute()
    )
    return _parse(full)


def _parse(msg: dict) -> dict:
    headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
    plain = _walk(msg["payload"], "text/plain")
    html = _walk(msg["payload"], "text/html")
    body = plain or _strip_html(html)  # stripped text for the LLM
    internal_ms = int(msg.get("internalDate", 0))
    dt = datetime.fromtimestamp(internal_ms / 1000, tz=timezone.utc)
    return {
        "id": msg["id"],
        "thread_id": msg.get("threadId", ""),
        "subject": headers.get("Subject", "(no subject)"),
        "sender": headers.get("From", ""),
        "message_id_header": headers.get("Message-Id") or headers.get("Message-ID", ""),
        "date": dt.isoformat(),
        "date_human": headers.get("Date", ""),
        "has_attachment": _has_attachment(msg["payload"]),
        "body": body,
        "body_html": html,  # original HTML for dashboard display
    }


def _walk(payload: dict, target_mime: str) -> str:
    if payload.get("mimeType") == target_mime and payload.get("body", {}).get("data"):
        return _decode(payload["body"]["data"])
    for part in payload.get("parts", []):
        found = _walk(part, target_mime)
        if found:
            return found
    return ""


def _has_attachment(payload: dict) -> bool:
    if payload.get("filename"):
        return True
    for part in payload.get("parts", []):
        if _has_attachment(part):
            return True
    return False


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data + "===").decode("utf-8", errors="replace")


class _TextExtractor(HTMLParser):
    """Drop tags, scripts, and styles; keep visible text."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in ("script", "style", "head"):
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "head") and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            text = data.strip()
            if text:
                self._parts.append(text)

    def text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self._parts)).strip()


def _strip_html(html_str: str) -> str:
    if not html_str:
        return ""
    parser = _TextExtractor()
    parser.feed(html_str)
    return parser.text()
