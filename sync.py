"""Shared sync pipeline: fetch unread → classify → persist.

Speed optimizations:
- Cache hit: emails already classified (label set, not ERROR) are skipped.
- Parallelism: non-sensitive emails hit Groq concurrently via a thread pool;
  sensitive emails run serially through Ollama (the local model is single-threaded).
"""
from concurrent.futures import ThreadPoolExecutor, as_completed

from db.store import cached_result, get_db, init_db, upsert_email
from enrich import detect_missing_attachment, normalize_subject
from gmail_client import fetch_unread, get_service
from llm import groq_client, ollama_client
from privacy.router import is_sensitive
from privacy.scrubber import scrub


def sync(max_results: int = 10):
    """Generator yielding per-email records in the original fetch order."""
    init_db()
    service = get_service()
    emails = fetch_unread(service, max_results=max_results)

    for email in emails:
        email["topic"] = normalize_subject(email["subject"])
        email["missing_attachment"] = detect_missing_attachment(
            email["body"], email["has_attachment"]
        )

    results: dict[str, tuple[dict, bool]] = {}

    with get_db() as conn:
        sensitive_emails = []
        groq_emails = []
        for email in emails:
            cached = cached_result(conn, email["id"])
            if cached:
                results[email["id"]] = (cached, True)
            elif is_sensitive(email["subject"], email["body"], email["sender"]):
                sensitive_emails.append(email)
            else:
                groq_emails.append(email)

        # Kick off Groq in parallel; run Ollama serially in the meantime.
        workers = max(1, len(groq_emails))
        with ThreadPoolExecutor(max_workers=workers) as groq_ex:
            groq_futs = {groq_ex.submit(_classify_groq, e): e["id"] for e in groq_emails}

            for email in sensitive_emails:
                try:
                    results[email["id"]] = (_classify_ollama(email), False)
                except Exception as e:
                    results[email["id"]] = (_error_result(e), False)

            for fut in as_completed(groq_futs):
                eid = groq_futs[fut]
                try:
                    results[eid] = (fut.result(), False)
                except Exception as e:
                    results[eid] = (_error_result(e), False)

        for email in emails:
            result, was_cached = results[email["id"]]
            upsert_email(conn, email, result)
            yield {"email": email, "result": result, "cached": was_cached}


def classify_email(email: dict) -> dict:
    """Classify a single pre-enriched email (used by bulk_import)."""
    if is_sensitive(email["subject"], email["body"], email["sender"]):
        try:
            return _classify_ollama(email)
        except Exception as e:
            return _error_result(e)
    try:
        return _classify_groq(email)
    except Exception as e:
        return _error_result(e)


def _classify_groq(email: dict) -> dict:
    scrubbed = scrub(email["body"])
    label, reason = groq_client.classify(email["subject"], scrubbed, email["sender"])
    return {"label": label, "reason": reason, "route": "groq", "sensitive": False}


def _classify_ollama(email: dict) -> dict:
    scrubbed = scrub(email["body"])
    if ollama_client.is_available():
        label, reason = ollama_client.classify(
            email["subject"], scrubbed, email["sender"]
        )
        return {"label": label, "reason": reason, "route": "ollama", "sensitive": True}
    return {
        "label": "SENSITIVE",
        "reason": "Ollama unavailable — skipped LLM",
        "route": "local-skip",
        "sensitive": True,
    }


def _error_result(e: Exception) -> dict:
    return {"label": "ERROR", "reason": str(e)[:150], "route": "-", "sensitive": False}
