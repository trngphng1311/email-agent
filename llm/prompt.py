"""Shared classification prompt template and response parser."""

VALID_LABELS = {"IMPORTANT", "PERSONAL", "WORK", "NEWSLETTER", "PROMOTIONAL", "SPAM"}

_TEMPLATE = """You are an email triager. Classify the email into exactly ONE of:

- IMPORTANT: urgent action, deadlines, security/account alerts, things that block the user.
- PERSONAL: personal finance (bank receipts, transfers, statements), family, friends, non-work life.
- WORK: colleagues, clients, employers, projects, meetings, job applications.
- NEWSLETTER: subscribed updates, digests, blog posts — informational, not selling.
- PROMOTIONAL: marketing, discounts, sales, ads, "you might like…".
- SPAM: unsolicited, phishing, scams.

Notes:
- Bank transfer receipts and statements are PERSONAL, not WORK.
- Coupon/discount emails from services are PROMOTIONAL, not NEWSLETTER.

Reply in EXACTLY two lines, no preamble:
LABEL: <one of: IMPORTANT, PERSONAL, WORK, NEWSLETTER, PROMOTIONAL, SPAM>
REASON: <one short sentence>

From: {sender}
Subject: {subject}
Body: {body}"""


def build(subject: str, body: str, sender: str, body_cap: int) -> str:
    return _TEMPLATE.format(sender=sender, subject=subject, body=body[:body_cap])


def parse(text: str) -> tuple[str, str]:
    """Extract (label, reason). Falls back to scanning for any valid label."""
    label: str | None = None
    reason = ""
    for line in text.splitlines():
        upper = line.upper()
        if upper.startswith("LABEL:"):
            candidate = line.split(":", 1)[1].strip().upper()
            if candidate in VALID_LABELS:
                label = candidate
        elif upper.startswith("REASON:"):
            reason = line.split(":", 1)[1].strip()

    if label is None:
        upper = text.upper()
        for valid in VALID_LABELS:
            if valid in upper:
                label = valid
                break
    return label or "UNCLASSIFIED", reason


_DRAFT_TEMPLATE = """You are drafting a reply to the email below.

Rules:
- Match the sender's tone and formality.
- Keep the reply under 80 words.
- If information is missing (dates, amounts, names), insert a [TODO: ...] placeholder.
- Do NOT write a greeting (Hi, Dear) or a closing (Thanks, Best) — the user will add those.
- Do NOT include a subject line.
- Reply in the same language as the incoming email.

Incoming email:
From: {sender}
Subject: {subject}
Body: {body}

Your reply (body only, no greeting or closing):"""


def build_draft(subject: str, body: str, sender: str, body_cap: int) -> str:
    return _DRAFT_TEMPLATE.format(
        sender=sender, subject=subject, body=body[:body_cap]
    )


_DRAFT_WITH_INSTRUCTION_TEMPLATE = """You are drafting a reply to the email below.

The user has given you a SPECIFIC INSTRUCTION — this takes precedence over the default rules:
{instruction}

Default rules (apply unless the instruction overrides):
- Match the sender's tone and formality.
- Keep the reply under 80 words.
- Insert [TODO: ...] placeholders for missing information.
- Do NOT write a greeting or closing.
- Do NOT include a subject line.
- Reply in the same language as the incoming email.

Incoming email:
From: {sender}
Subject: {subject}
Body: {body}

Your reply (body only, no greeting or closing):"""


def build_draft_with_instruction(
    subject: str, body: str, sender: str, instruction: str, body_cap: int
) -> str:
    return _DRAFT_WITH_INSTRUCTION_TEMPLATE.format(
        sender=sender,
        subject=subject,
        body=body[:body_cap],
        instruction=instruction.strip(),
    )


_SUMMARY_TEMPLATE = """Summarize the email below in 1–2 sentences.

Focus on:
- What action (if any) the sender wants from the recipient.
- Key facts: amounts, dates, names, references.
- The overall intent (informational, request, confirmation, alert, etc.).

Rules:
- No greeting, no closing, no preamble like "This email is about…".
- Reply in the same language as the email.
- Maximum 40 words.

Email:
From: {sender}
Subject: {subject}
Body: {body}

Summary:"""


def build_summary(subject: str, body: str, sender: str, body_cap: int) -> str:
    return _SUMMARY_TEMPLATE.format(
        sender=sender, subject=subject, body=body[:body_cap]
    )
