"""Milestone 4/5/6 — FastAPI dashboard, manual sync, email detail + reply.

Run with:
    .venv/bin/uvicorn server:app --reload
Then open http://localhost:8000
"""
import threading
from datetime import date, datetime, timedelta
from email.utils import parseaddr

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from bulk import bulk_import
from db.store import (
    awaiting_reply_count,
    awaiting_reply_emails,
    domain_groups,
    domain_members,
    get_db,
    get_draft,
    get_email,
    get_setting,
    groups as load_groups,
    init_db,
    mark_draft_sent,
    recent_emails,
    save_draft_edit,
    sender_profile,
    set_setting,
    stats as load_stats,
)
from drafting import compute_reply_status, ensure_draft, ensure_summary
from gmail_client import fetch_thread_full, get_service, get_user_email, send_reply
from sync import sync

app = FastAPI(title="Email Agent")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
init_db()

THEMES = [
    {"key": "default", "name": "Slate · Teal",    "primary": "#1E293B", "accent": "#0891B2"},
    {"key": "amber",   "name": "Charcoal · Amber","primary": "#1F2937", "accent": "#D97706"},
    {"key": "indigo",  "name": "Indigo · Cyan",   "primary": "#1E1B4B", "accent": "#06B6D4"},
    {"key": "forest",  "name": "Forest · Lime",   "primary": "#14532D", "accent": "#65A30D"},
    {"key": "plum",    "name": "Plum · Rose",     "primary": "#4A044E", "accent": "#DB2777"},
]

# Make theme + background URL available to every template.
templates.env.globals["get_background"] = lambda: get_setting("background_url", "")
templates.env.globals["get_theme"] = lambda: get_setting("theme", "default") or "default"

LABELS = ["IMPORTANT", "PERSONAL", "WORK", "NEWSLETTER", "PROMOTIONAL", "SPAM"]

_sync_lock = threading.Lock()
_last_sync: str | None = None
_cached_user_email: str | None = None

_bulk_lock = threading.Lock()
_bulk_state: dict = {"state": "idle"}
_bulk_stop = threading.Event()


def _user_email(service) -> str:
    global _cached_user_email
    if _cached_user_email is None:
        _cached_user_email = get_user_email(service)
    return _cached_user_email


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    s = load_stats()
    s["awaiting"] = awaiting_reply_count()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "stats": s,
            "ai_suggestions": awaiting_reply_emails(5),
            "recent": recent_emails(7),
            "top_senders": _sender_sidebar()[:5],
            "top_domains": domain_groups()[:5],
            "last_sync": _last_sync,
        },
    )


@app.get("/inbox", response_class=HTMLResponse)
def inbox(
    request: Request,
    label: str | None = None,
    sender: str | None = None,
    topic: str | None = None,
    q: str | None = None,
):
    rows = _filtered(label, sender, topic, q)
    profile = sender_profile(sender) if sender else None
    return templates.TemplateResponse(
        request,
        "inbox.html",
        {
            "rows": rows,
            "labels": LABELS,
            "senders": _sender_sidebar(),
            "label": label or "",
            "sender": sender or "",
            "topic": topic or "",
            "q": q or "",
            "count": len(rows),
            "last_sync": _last_sync,
            "profile": profile,
        },
    )


@app.get("/rows", response_class=HTMLResponse)
def rows(
    request: Request,
    label: str | None = None,
    sender: str | None = None,
    topic: str | None = None,
    q: str | None = None,
):
    matched = _filtered(label, sender, topic, q)
    return templates.TemplateResponse(
        request,
        "_rows.html",
        {"rows": matched, "count": len(matched)},
    )


@app.get("/groups", response_class=HTMLResponse)
def groups_page(request: Request, domain: str | None = None):
    expanded = domain_members(domain) if domain else None
    return templates.TemplateResponse(
        request,
        "groups.html",
        {
            "groups": load_groups(),
            "domains": domain_groups(),
            "selected_domain": domain or "",
            "domain_members": expanded,
        },
    )


@app.get("/import", response_class=HTMLResponse)
def import_page(request: Request):
    today = date.today()
    status = _bulk_state if _bulk_state.get("state") != "idle" else None
    return templates.TemplateResponse(
        request,
        "import.html",
        {
            "status": status,
            "default_after": (today - timedelta(days=30)).isoformat(),
            "default_before": today.isoformat(),
        },
    )


@app.get("/import/status", response_class=HTMLResponse)
def import_status(request: Request):
    status = _bulk_state if _bulk_state.get("state") != "idle" else None
    return templates.TemplateResponse(
        request,
        "_import_status.html",
        {"status": status},
    )


@app.post("/import")
def import_submit(
    after: str = Form(""),
    before: str = Form(""),
    count: int = Form(100),
    query: str = Form(""),
):
    if not _bulk_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Import already in progress")

    _bulk_stop.clear()
    _bulk_state.clear()
    _bulk_state.update({
        "state": "running",
        "processed": 0,
        "total": count,
        "classified": 0,
        "skipped": 0,
        "current": None,
    })

    def work() -> None:
        try:
            service = get_service()
            result = bulk_import(
                service,
                count=count,
                query=query.strip() or None,
                after=after.strip() or None,
                before=before.strip() or None,
                on_progress=lambda p: _bulk_state.update(p),
                stop_event=_bulk_stop,
            )
            final_state = "cancelled" if result.get("cancelled") else "done"
            _bulk_state.update({"state": final_state, **result})
        except Exception as e:
            _bulk_state.update({"state": "error", "error": str(e)[:200]})
        finally:
            _bulk_lock.release()

    threading.Thread(target=work, daemon=True).start()
    return RedirectResponse(url="/import", status_code=303)


@app.post("/import/cancel")
def import_cancel():
    if _bulk_state.get("state") == "running":
        _bulk_stop.set()
        _bulk_state["state"] = "cancelling"
    return RedirectResponse(url="/import", status_code=303)


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "signature": get_setting("signature", ""),
            "background_url": get_setting("background_url", ""),
            "theme": get_setting("theme", "default") or "default",
            "themes": THEMES,
            "saved": request.query_params.get("saved") == "1",
        },
    )


@app.post("/settings")
def settings_save(
    signature: str = Form(""),
    background_url: str = Form(""),
    theme: str = Form("default"),
):
    set_setting("signature", signature.strip())
    set_setting("background_url", background_url.strip())
    set_setting("theme", (theme.strip() or "default"))
    return RedirectResponse(url="/settings?saved=1", status_code=303)


@app.post("/sync", response_class=HTMLResponse)
def trigger_sync(request: Request):
    global _last_sync
    if not _sync_lock.acquire(blocking=False):
        return HTMLResponse(
            "<div class='p-4 text-amber-700 bg-amber-50 border-b border-amber-200'>"
            "Sync already in progress — wait for it to finish.</div>",
            status_code=409,
        )
    try:
        processed = 0
        new_sensitive = 0
        for record in sync(max_results=10):
            processed += 1
            if record["result"].get("sensitive"):
                new_sensitive += 1
        _last_sync = datetime.now().strftime("%H:%M:%S")
    finally:
        _sync_lock.release()

    matched = _filtered(None, None)
    return templates.TemplateResponse(
        request,
        "_rows.html",
        {
            "rows": matched,
            "count": len(matched),
            "banner": f"Synced {processed} emails at {_last_sync} "
                      f"({new_sensitive} sensitive → local).",
        },
    )


@app.get("/email/{email_id}", response_class=HTMLResponse)
def email_detail(
    request: Request,
    email_id: str,
    reply_anyway: int | None = None,
):
    email = get_email(email_id)
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")

    service = get_service()
    user = _user_email(service)

    try:
        thread = fetch_thread_full(service, email["thread_id"])
    except Exception:
        thread = []

    thread.sort(key=lambda m: m.get("date", ""))
    for m in thread:
        _, from_addr = parseaddr(m.get("sender", ""))
        m["is_me"] = from_addr.lower() == user.lower()

    no_reply_labels = {"NEWSLETTER", "PROMOTIONAL", "SPAM"}
    if (email.get("label") or "").upper() in no_reply_labels:
        reply_status = "no_reply_needed"
    elif thread and thread[-1]["is_me"]:
        reply_status = "replied"
    else:
        reply_status = "awaiting_reply"

    forced = False
    if reply_anyway and reply_status == "no_reply_needed":
        reply_status = "awaiting_reply"
        forced = True

    draft = get_draft(email_id)
    signature = get_setting("signature", "")
    bulk_busy = _bulk_state.get("state") in ("running", "cancelling")

    return templates.TemplateResponse(
        request,
        "detail.html",
        {
            "email": email,
            "thread": thread,
            "reply_status": reply_status,
            "draft": draft,
            "forced": forced,
            "bulk_busy": bulk_busy,
            "signature": signature,
            "can_send": reply_status == "awaiting_reply"
                         and draft
                         and draft["status"] != "sent",
        },
    )


@app.get("/email/{email_id}/summary", response_class=HTMLResponse)
def email_summary(request: Request, email_id: str, force: int | None = None):
    email = get_email(email_id)
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")

    bulk_busy = _bulk_state.get("state") in ("running", "cancelling")
    if bulk_busy and not email.get("summary"):
        # Don't fight bulk import for Ollama; show placeholder, no LLM call.
        return templates.TemplateResponse(
            request,
            "_summary.html",
            {"email": email, "summary": None, "route": None, "paused": True},
        )

    result = ensure_summary(email, force=bool(force))
    return templates.TemplateResponse(
        request,
        "_summary.html",
        {
            "email": email,
            "summary": result["summary"],
            "route": result["route"],
            "paused": False,
        },
    )


@app.post("/email/{email_id}/regenerate")
def regenerate_draft(email_id: str, instruction: str = Form("")):
    email = get_email(email_id)
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    instr = instruction.strip() or None
    ensure_draft(email, force=True, instruction=instr)
    suffix = "?reply_anyway=1" if _is_no_reply(email) else ""
    return RedirectResponse(url=f"/email/{email_id}{suffix}", status_code=303)


def _is_no_reply(email: dict) -> bool:
    return (email.get("label") or "").upper() in {"NEWSLETTER", "PROMOTIONAL", "SPAM"}


@app.post("/email/{email_id}/save")
def save_draft(email_id: str, draft_text: str = Form(...)):
    if not get_email(email_id):
        raise HTTPException(status_code=404, detail="Email not found")
    save_draft_edit(email_id, draft_text)
    return RedirectResponse(url=f"/email/{email_id}", status_code=303)


@app.post("/email/{email_id}/send")
def send_draft(
    email_id: str,
    draft_text: str = Form(...),
    include_signature: str = Form(""),
    bcc: str = Form(""),
):
    email = get_email(email_id)
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")

    save_draft_edit(email_id, draft_text)

    final_text = draft_text
    if include_signature:
        sig = get_setting("signature", "").strip()
        if sig:
            final_text = draft_text.rstrip() + "\n\n--\n" + sig

    service = get_service()
    _, to_addr = parseaddr(email["sender_email"] or "")
    if not to_addr:
        raise HTTPException(status_code=400, detail="Missing recipient address")

    # Pull Message-Id from stored email (used for threading headers).
    with get_db() as conn:
        row = conn.execute(
            "SELECT body, subject, thread_id FROM emails WHERE id = ?", (email_id,)
        ).fetchone()
    original = dict(row) if row else {}

    # Re-fetch Message-Id header from Gmail (we didn't persist it).
    full = service.users().messages().get(
        userId="me", id=email_id, format="metadata",
        metadataHeaders=["Message-Id", "Message-ID"]
    ).execute()
    headers = {h["name"].lower(): h["value"] for h in full["payload"]["headers"]}
    in_reply_to = headers.get("message-id", "")

    send_reply(
        service,
        to=to_addr,
        subject=original.get("subject", ""),
        body_text=final_text,
        thread_id=original.get("thread_id", ""),
        in_reply_to=in_reply_to,
        bcc=bcc.strip(),
    )
    mark_draft_sent(email_id)
    return RedirectResponse(url=f"/email/{email_id}?sent=1", status_code=303)


def _filtered(
    label: str | None,
    sender: str | None,
    topic: str | None = None,
    q: str | None = None,
) -> list[dict]:
    sql = "SELECT * FROM emails WHERE 1=1"
    params: list = []
    if label:
        sql += " AND UPPER(label) = UPPER(?)"
        params.append(label)
    if sender:
        sql += " AND LOWER(sender_email) LIKE ?"
        params.append(f"%{sender.lower()}%")
    if topic:
        sql += " AND topic = ?"
        params.append(topic)
    if q:
        sql += " AND (LOWER(subject) LIKE ? OR LOWER(sender_email) LIKE ? OR LOWER(body) LIKE ?)"
        like = f"%{q.lower()}%"
        params.extend([like, like, like])
    sql += " ORDER BY date DESC LIMIT 200"
    with get_db() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _sender_sidebar() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT email, display_name, mail_count FROM senders "
            "ORDER BY mail_count DESC, email ASC LIMIT 50"
        ).fetchall()
    return [dict(r) for r in rows]
