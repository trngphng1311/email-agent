"""Thin Groq wrapper for email classification."""
import os

from dotenv import load_dotenv
from groq import Groq

from llm.prompt import build, build_draft, build_draft_with_instruction, build_summary, parse

load_dotenv()

MODEL = "llama-3.3-70b-versatile"
BODY_CAP = 2000
_client: Groq | None = None


def _get_client() -> Groq:
    global _client
    if _client is None:
        key = os.environ.get("GROQ_API_KEY")
        if not key or key.startswith("paste_"):
            raise RuntimeError("GROQ_API_KEY missing — set it in .env")
        _client = Groq(api_key=key)
    return _client


def classify(subject: str, body: str, sender: str) -> tuple[str, str]:
    resp = _get_client().chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": build(subject, body, sender, BODY_CAP)}],
        temperature=0.1,
        max_tokens=120,
    )
    return parse(resp.choices[0].message.content.strip())


def summarize(subject: str, body: str, sender: str) -> str:
    resp = _get_client().chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": build_summary(subject, body, sender, BODY_CAP)}],
        temperature=0.2,
        max_tokens=120,
    )
    return resp.choices[0].message.content.strip()


def draft(subject: str, body: str, sender: str, instruction: str | None = None) -> str:
    if instruction:
        prompt = build_draft_with_instruction(subject, body, sender, instruction, BODY_CAP)
    else:
        prompt = build_draft(subject, body, sender, BODY_CAP)
    resp = _get_client().chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=250,
    )
    return resp.choices[0].message.content.strip()
