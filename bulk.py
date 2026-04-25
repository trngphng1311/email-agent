"""Bulk historical import, with optional date range and progress callback.

Shared by `scripts/first_sync.py` (CLI) and the dashboard's /import route.
"""
import threading
from typing import Callable, Optional

from db.store import cached_result, get_db, init_db, upsert_email
from enrich import detect_missing_attachment, normalize_subject
from gmail_client import fetch_message, list_message_ids
from sync import classify_email


def bulk_import(
    service,
    count: int = 200,
    query: Optional[str] = None,
    after: Optional[str] = None,   # YYYY-MM-DD (inclusive, Gmail-style)
    before: Optional[str] = None,  # YYYY-MM-DD (exclusive, Gmail-style)
    on_progress: Optional[Callable[[dict], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> dict:
    """Import up to `count` emails matching the criteria. Idempotent."""
    init_db()

    parts: list[str] = []
    if query:
        parts.append(query.strip())
    if after:
        parts.append(f"after:{after.replace('-', '/')}")
    if before:
        parts.append(f"before:{before.replace('-', '/')}")
    gmail_query = " ".join(p for p in parts if p).strip() or None

    page_token: Optional[str] = None
    processed = 0
    classified = 0
    skipped = 0

    def progress(current: Optional[str] = None) -> None:
        if on_progress:
            on_progress({
                "processed": processed,
                "total": count,
                "classified": classified,
                "skipped": skipped,
                "current": current,
            })

    cancelled = False
    with get_db() as conn:
        while processed < count:
            if stop_event and stop_event.is_set():
                cancelled = True
                break
            batch = min(100, count - processed)
            ids, page_token = list_message_ids(service, gmail_query, batch, page_token)
            if not ids:
                break

            for mid in ids:
                if stop_event and stop_event.is_set():
                    cancelled = True
                    break
                if processed >= count:
                    break

                cached = cached_result(conn, mid)
                email = fetch_message(service, mid)
                email["topic"] = normalize_subject(email["subject"])
                email["missing_attachment"] = detect_missing_attachment(
                    email["body"], email["has_attachment"]
                )

                if cached:
                    # Reuse classification — just refresh body/body_html/metadata.
                    upsert_email(conn, email, cached)
                    processed += 1
                    skipped += 1
                    progress(email["subject"][:80])
                    continue

                result = classify_email(email)
                upsert_email(conn, email, result)

                processed += 1
                classified += 1
                progress(email["subject"][:80])

            if cancelled or not page_token:
                break

    return {
        "processed": processed,
        "classified": classified,
        "skipped": skipped,
        "cancelled": cancelled,
    }
