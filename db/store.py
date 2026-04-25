"""SQLite persistence for emails, senders, and classification results."""
import sqlite3
from datetime import datetime, timezone
from email.utils import parseaddr
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "app.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with get_db() as conn:
        with open(SCHEMA_PATH) as f:
            conn.executescript(f.read())
        _add_column_if_missing(conn, "emails", "missing_attachment", "INTEGER DEFAULT 0")
        _add_column_if_missing(conn, "emails", "topic", "TEXT")
        _add_column_if_missing(conn, "emails", "body_html", "TEXT")
        _add_column_if_missing(conn, "emails", "summary", "TEXT")
        _add_column_if_missing(conn, "emails", "summary_route", "TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_emails_topic ON emails(topic)")


def _add_column_if_missing(conn, table: str, column: str, type_: str) -> None:
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {type_}")
    except sqlite3.OperationalError as e:
        if "duplicate column" not in str(e).lower():
            raise


def upsert_sender(conn: sqlite3.Connection, from_header: str) -> str:
    display_name, addr = parseaddr(from_header or "")
    addr = (addr or "unknown@unknown").lower()
    now = _now()
    conn.execute(
        """
        INSERT INTO senders (email, display_name, first_seen, last_seen, mail_count)
        VALUES (?, ?, ?, ?, 1)
        ON CONFLICT(email) DO UPDATE SET
            display_name = COALESCE(NULLIF(excluded.display_name, ''), display_name),
            last_seen    = excluded.last_seen,
            mail_count   = mail_count + 1
        """,
        (addr, display_name, now, now),
    )
    return addr


def upsert_email(conn: sqlite3.Connection, email: dict, result: dict) -> None:
    sender_email = upsert_sender(conn, email["sender"])
    snippet = (email.get("body") or "")[:200]
    conn.execute(
        """
        INSERT INTO emails (
            id, thread_id, sender_email, subject, body, body_html, snippet, date,
            has_attachment, missing_attachment, topic,
            label, label_reason, sensitive, llm_route, classified_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            thread_id          = excluded.thread_id,
            subject            = excluded.subject,
            body               = excluded.body,
            body_html          = excluded.body_html,
            snippet            = excluded.snippet,
            date               = excluded.date,
            has_attachment     = excluded.has_attachment,
            missing_attachment = excluded.missing_attachment,
            topic              = excluded.topic,
            label              = excluded.label,
            label_reason       = excluded.label_reason,
            sensitive          = excluded.sensitive,
            llm_route          = excluded.llm_route,
            classified_at      = excluded.classified_at
        """,
        (
            email["id"],
            email.get("thread_id", ""),
            sender_email,
            email["subject"],
            email.get("body", ""),
            email.get("body_html", "") or "",
            snippet,
            email.get("date", ""),
            1 if email.get("has_attachment") else 0,
            1 if email.get("missing_attachment") else 0,
            email.get("topic", ""),
            result["label"],
            result["reason"],
            1 if result.get("sensitive") else 0,
            result.get("route", ""),
            _now(),
        ),
    )


def query_emails(
    label: str | None = None,
    since_days: int | None = None,
    limit: int = 50,
) -> list[dict]:
    sql = "SELECT * FROM emails WHERE 1=1"
    params: list = []
    if label:
        sql += " AND UPPER(label) = UPPER(?)"
        params.append(label)
    if since_days is not None:
        sql += " AND date >= datetime('now', ?)"
        params.append(f"-{since_days} days")
    sql += " ORDER BY date DESC LIMIT ?"
    params.append(limit)
    with get_db() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def stats() -> dict:
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*)                                        AS total,
                SUM(CASE WHEN sensitive = 1 THEN 1 ELSE 0 END)  AS sensitive_count,
                SUM(CASE WHEN missing_attachment = 1 THEN 1 ELSE 0 END) AS missing,
                SUM(CASE WHEN has_attachment = 1 THEN 1 ELSE 0 END)     AS attachments
            FROM emails
            """
        ).fetchone()
    return dict(row) if row else {"total": 0, "sensitive_count": 0, "missing": 0, "attachments": 0}


def label_distribution() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT label, COUNT(*) AS n FROM emails
            WHERE label IS NOT NULL AND label != ''
            GROUP BY label
            ORDER BY n DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def awaiting_reply_emails(limit: int = 5) -> list[dict]:
    """Emails likely needing a reply: action-y labels with no sent draft yet."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT e.* FROM emails e
            LEFT JOIN drafts d
              ON d.email_id = e.id AND d.status = 'sent'
            WHERE UPPER(COALESCE(e.label, '')) IN ('IMPORTANT', 'PERSONAL', 'WORK')
              AND d.email_id IS NULL
            ORDER BY e.date DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def recent_emails(limit: int = 7) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM emails ORDER BY date DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def domain_groups() -> list[dict]:
    """Senders grouped by email domain."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT
                LOWER(SUBSTR(email, INSTR(email, '@') + 1)) AS domain,
                COUNT(*)  AS sender_count,
                SUM(mail_count) AS email_count,
                MAX(last_seen) AS last_seen
            FROM senders
            WHERE email LIKE '%@%'
            GROUP BY domain
            ORDER BY email_count DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def domain_members(domain: str) -> list[dict]:
    """Senders inside a single domain (e.g. all @vietcombank.com.vn)."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT email, display_name, mail_count, last_seen
            FROM senders
            WHERE LOWER(SUBSTR(email, INSTR(email, '@') + 1)) = LOWER(?)
            ORDER BY mail_count DESC, email ASC
            """,
            (domain,),
        ).fetchall()
    return [dict(r) for r in rows]


def awaiting_reply_count() -> int:
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n FROM emails e
            LEFT JOIN drafts d
              ON d.email_id = e.id AND d.status = 'sent'
            WHERE UPPER(COALESCE(e.label, '')) IN ('IMPORTANT', 'PERSONAL', 'WORK')
              AND d.email_id IS NULL
            """
        ).fetchone()
    return row["n"] if row else 0


def cached_result(conn: sqlite3.Connection, email_id: str) -> dict | None:
    """Return the stored classification if this email has one we can reuse."""
    row = conn.execute(
        "SELECT label, label_reason, sensitive, llm_route FROM emails WHERE id = ?",
        (email_id,),
    ).fetchone()
    if not row:
        return None
    label = row["label"]
    if not label or label in ("ERROR", "UNCLASSIFIED"):
        return None
    return {
        "label": label,
        "reason": row["label_reason"] or "",
        "route": row["llm_route"] or "",
        "sensitive": bool(row["sensitive"]),
    }


def groups() -> list[dict]:
    """Grouped view: (topic, sender) with count, last date, and any IMPORTANT flag."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT
                topic,
                sender_email,
                COUNT(*)                 AS n,
                MAX(date)                AS last_date,
                MAX(label)               AS any_label,
                MAX(missing_attachment)  AS any_missing_attachment,
                MAX(sensitive)           AS any_sensitive,
                subject                  AS sample_subject
            FROM emails
            WHERE topic IS NOT NULL AND topic != ''
            GROUP BY topic, sender_email
            ORDER BY last_date DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def sender_profile(email_addr: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM senders WHERE email = ?", (email_addr.lower(),)
        ).fetchone()
    return dict(row) if row else None


def get_email(email_id: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM emails WHERE id = ?", (email_id,)).fetchone()
    return dict(row) if row else None


def get_draft(email_id: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM drafts WHERE email_id = ?", (email_id,)
        ).fetchone()
    return dict(row) if row else None


def upsert_draft(email_id: str, draft_text: str, llm_route: str) -> None:
    now = _now()
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO drafts (email_id, draft_text, llm_route, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(email_id) DO UPDATE SET
                draft_text = excluded.draft_text,
                llm_route  = excluded.llm_route,
                updated_at = excluded.updated_at,
                status     = CASE WHEN status = 'sent' THEN status ELSE 'pending' END
            """,
            (email_id, draft_text, llm_route, now),
        )


def save_draft_edit(email_id: str, draft_text: str) -> None:
    now = _now()
    with get_db() as conn:
        conn.execute(
            "UPDATE drafts SET draft_text = ?, updated_at = ? WHERE email_id = ?",
            (draft_text, now, email_id),
        )


def mark_draft_sent(email_id: str) -> None:
    now = _now()
    with get_db() as conn:
        conn.execute(
            "UPDATE drafts SET status = 'sent', sent_at = ? WHERE email_id = ?",
            (now, email_id),
        )


def set_summary(email_id: str, summary: str, route: str) -> None:
    now = _now()
    with get_db() as conn:
        conn.execute(
            "UPDATE emails SET summary = ?, summary_route = ?, classified_at = COALESCE(classified_at, ?) WHERE id = ?",
            (summary, route, now, email_id),
        )


def get_setting(key: str, default: str = "") -> str:
    with get_db() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
    return row["value"] if row and row["value"] is not None else default


def set_setting(key: str, value: str) -> None:
    now = _now()
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value      = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, value, now),
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
