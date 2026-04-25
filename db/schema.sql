CREATE TABLE IF NOT EXISTS senders (
    email          TEXT PRIMARY KEY,
    display_name   TEXT,
    category       TEXT,
    first_seen     TEXT,
    last_seen      TEXT,
    mail_count     INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS emails (
    id                 TEXT PRIMARY KEY,
    thread_id          TEXT,
    sender_email       TEXT,
    subject            TEXT,
    body               TEXT,            -- plain text (stripped) used by the LLM
    body_html          TEXT,            -- original HTML kept for dashboard display
    snippet            TEXT,
    date               TEXT,            -- ISO8601 UTC (from Gmail internalDate)
    has_attachment     INTEGER DEFAULT 0,
    missing_attachment INTEGER DEFAULT 0,  -- body mentions an attachment but none present
    topic              TEXT,            -- normalized subject for grouping
    label              TEXT,
    label_reason       TEXT,
    sensitive          INTEGER DEFAULT 0,
    llm_route          TEXT,
    classified_at      TEXT,
    created_at         TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_emails_label  ON emails(label);
CREATE INDEX IF NOT EXISTS idx_emails_date   ON emails(date);
CREATE INDEX IF NOT EXISTS idx_emails_sender ON emails(sender_email);
CREATE INDEX IF NOT EXISTS idx_emails_thread ON emails(thread_id);
-- idx_emails_topic created in init_db after the migration adds the column

CREATE TABLE IF NOT EXISTS drafts (
    email_id    TEXT PRIMARY KEY,
    draft_text  TEXT,
    status      TEXT DEFAULT 'pending',     -- pending|sent|discarded
    llm_route   TEXT,
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at  TEXT,
    sent_at     TEXT,
    FOREIGN KEY (email_id) REFERENCES emails(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value       TEXT,
    updated_at  TEXT
);
