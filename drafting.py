"""Reply-status detection + on-demand draft + summary generation."""
from email.utils import parseaddr

from db.store import get_draft, set_summary, upsert_draft
from gmail_client import fetch_thread
from llm import groq_client, ollama_client
from privacy.router import is_sensitive
from privacy.scrubber import scrub

NO_REPLY_LABELS = {"NEWSLETTER", "PROMOTIONAL", "SPAM"}


def compute_reply_status(service, email_row: dict, user_email: str) -> str:
    """Classify: awaiting_reply | replied | no_reply_needed."""
    if email_row["label"].upper() in NO_REPLY_LABELS:
        return "no_reply_needed"
    thread = fetch_thread(service, email_row["thread_id"])
    messages = thread.get("messages", [])
    if not messages:
        return "awaiting_reply"
    last = messages[-1]
    headers = {h["name"]: h["value"] for h in last.get("payload", {}).get("headers", [])}
    _, last_from = parseaddr(headers.get("From", ""))
    if last_from.lower() == user_email.lower():
        return "replied"
    return "awaiting_reply"


def ensure_draft(
    email_row: dict,
    *,
    force: bool = False,
    instruction: str | None = None,
) -> dict:
    """Return a draft row, generating (or regenerating) via LLM as needed.

    - force=False, no existing draft → generate.
    - force=False, existing draft → reuse.
    - force=True (or instruction given) → always regenerate.
    """
    existing = get_draft(email_row["id"])
    if existing and existing["draft_text"] and not force and not instruction:
        return existing

    subject = email_row["subject"]
    body = email_row["body"] or ""
    sender = email_row["sender_email"]
    sensitive = bool(email_row.get("sensitive"))

    scrubbed = scrub(body)
    if sensitive or is_sensitive(subject, body, sender):
        if ollama_client.is_available():
            text = ollama_client.draft(subject, scrubbed, sender, instruction=instruction)
            route = "ollama"
        else:
            text = "[TODO: Ollama offline — write reply manually]"
            route = "local-skip"
    else:
        text = groq_client.draft(subject, scrubbed, sender, instruction=instruction)
        route = "groq"

    upsert_draft(email_row["id"], text, route)
    return get_draft(email_row["id"])


def ensure_summary(email_row: dict, *, force: bool = False) -> dict:
    """Generate (or fetch cached) AI summary of the email body."""
    existing = email_row.get("summary")
    if existing and not force:
        return {"summary": existing, "route": email_row.get("summary_route", "")}

    subject = email_row["subject"]
    body = email_row["body"] or ""
    sender = email_row["sender_email"]
    sensitive = bool(email_row.get("sensitive"))

    if not body.strip():
        text, route = "(Empty body — nothing to summarize.)", "skip"
    else:
        scrubbed = scrub(body)
        try:
            if sensitive or is_sensitive(subject, body, sender):
                if ollama_client.is_available():
                    text = ollama_client.summarize(subject, scrubbed, sender)
                    route = "ollama"
                else:
                    text = "Ollama offline — sensitive email cannot be summarized in cloud."
                    route = "local-skip"
            else:
                text = groq_client.summarize(subject, scrubbed, sender)
                route = "groq"
        except Exception as e:
            text = f"Summary failed: {str(e)[:100]}"
            route = "error"

    set_summary(email_row["id"], text, route)
    return {"summary": text, "route": route}
