# Email Agent

> A local-first AI email assistant for Gmail only. Triages your inbox, drafts replies,
> groups senders, and keeps sensitive content on your own machine.

Runs as a FastAPI web app on `localhost:8000`. Nothing is hosted; all data lives
in a single SQLite file on your Mac.

---

## Features

- **AI classification** — every email is labeled IMPORTANT / PERSONAL / WORK / NEWSLETTER / PROMOTIONAL / SPAM.
- **AI summary on demand** — click to get a one-line summary of any email.
- **AI reply drafting** — click to generate a draft, optionally with a custom instruction (*"make it formal"*, *"ask about deadline"*).
- **Privacy router** — bank, medical, and password-related mail stays on your local Ollama. Everything else goes to the free Groq cloud after PII redaction.
- **Bento dashboard** — stats, AI suggestions, recent inbox, top sender domains, and quick actions.
- **Full-text search** across subject, sender, and body.
- **Conversation thread view** — your sent replies appear side-by-side with incoming messages.
- **BCC support** with one-click "Copy emails" from any domain group.
- **Bulk import** with date range, query, and live cancellable progress.
- **Reply signature** + 5 color themes + uploadable blurred-image background.

---

## Tech stack

| Layer    | Tech |
|----------|------|
| Backend  | Python 3.10+ · FastAPI · Uvicorn · SQLite · Jinja2 |
| LLM cloud| Groq API · `llama-3.3-70b-versatile` |
| LLM local| Ollama · `llama3.2:latest` |
| Email    | Gmail API · OAuth 2.0 (`gmail.modify` scope) |
| Frontend | HTMX · custom CSS · Geist Sans + Inter + JetBrains Mono |
| Privacy  | scrubadub + custom regex for PII redaction |

---

## Prerequisites

- macOS or Linux
- Python 3.10 or newer
- A Google account with Gmail
- A Groq API key — sign up free at <https://console.groq.com>
- Ollama installed locally — <https://ollama.com>

---

## Setup

### 1. Clone and install dependencies

```bash
git clone <your-repo-url>
cd email-agent
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 2. Set up Google OAuth

1. Go to <https://console.cloud.google.com/> and create a new project.
2. Enable the **Gmail API** in **APIs & Services → Library**.
3. Configure the **OAuth consent screen**:
   - User Type: **External**
   - Add your own Gmail address as a **Test user** (otherwise the app will be blocked).
4. Create credentials in **APIs & Services → Credentials**:
   - **Create Credentials → OAuth client ID**
   - Application type: **Desktop app**
   - Download the JSON.
5. Save the downloaded JSON as `credentials.json` in the project root.

### 3. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and paste your Groq key. Keep the Ollama defaults unless you've changed them.

### 4. Install Ollama and pull the model

```bash
brew install ollama       # or download from ollama.com
ollama pull llama3.2:latest
```

### 5. First-time Google authentication

```bash
.venv/bin/python reauth.py
```

A browser tab opens. Sign in with your Google account, click **Allow**. The
script saves a token to `token.json` so you don't need to log in again.

---

## Running

You need two terminals:

**Terminal 1 — Ollama** (keep running)
```bash
ollama serve
```

**Terminal 2 — the app**
```bash
.venv/bin/uvicorn server:app --reload
```

Open <http://localhost:8000>.

---

## Daily use

1. **Click "Sync now"** in the header to pull the latest 10 unread emails. After the first sync, subsequent syncs are near-instant because already-classified emails are cached.
2. **Open an email** — you see the conversation thread, classification, and a button to generate the AI summary.
3. **Click "Generate draft"** to have AI write a reply. Edit it, optionally include your signature, and click **Send reply**. Your reply threads under the original message.
4. **Filter the inbox** by label, sender, topic, or full-text search.
5. **Browse Groups** to see senders grouped by email domain. Copy a group's addresses to BCC them in your next reply.
6. **Bulk-import history** from the Import page — pick a date range and let it run in the background.

### CLI shortcuts

```bash
# Classify the 10 newest unread via terminal
.venv/bin/python classify.py

# Bulk-import historical mail with a date range
.venv/bin/python scripts/first_sync.py 200 '' 2026-03-01 2026-04-01

# Quick query the local store
.venv/bin/python query.py IMPORTANT 7
```

---

## How privacy routing works

Every email body passes through three checks before any LLM sees it:

1. **Sensitivity router** — keyword + sender heuristics. Hits like `bank`,
   `OTP`, `mật khẩu`, `vietcombank`, etc. force the email through your local
   Ollama. The cloud never sees it.
2. **Scrubber** — for non-sensitive mail going to Groq, scrubadub plus custom
   regex redacts emails, phone numbers, account numbers, API keys, and money
   amounts before sending.
3. **Routing** — sensitive → Ollama (local), non-sensitive → Groq (free cloud).
   If Ollama is offline, sensitive mail is flagged but never falls back to
   cloud.

You can tune the sensitivity rules in `privacy/router.py` and the redaction
patterns in `privacy/scrubber.py`.

---

## Project structure

```
email-agent/
├── server.py              # FastAPI routes + bento dashboard
├── sync.py                # fetch → scrub → classify → persist
├── bulk.py                # historical bulk import with cancellation
├── drafting.py            # reply-status, draft, summary helpers
├── enrich.py              # subject normalization, attachment heuristics
├── gmail_client.py        # OAuth + fetch + send via Gmail API
├── llm/                   # Groq + Ollama clients, prompt templates
├── privacy/               # sensitivity router + PII scrubber
├── db/                    # SQLite schema + helpers
├── templates/             # Jinja2 + HTMX UI
├── static/style.css       # design tokens + components
└── scripts/first_sync.py  # CLI bulk-import wrapper
```

---

## Customization

Open **Settings** in the app to change:
- Color theme (5 palettes)
- Background image URL (blurred behind content)
- Reply signature (plain text, multi-line)

---

## License

Personal use. No warranty — this is a hobby tool. Don't deploy it as a
multi-user service without serious changes.
