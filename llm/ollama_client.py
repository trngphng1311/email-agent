"""Thin Ollama wrapper for local LLM classification."""
import os

import requests
from dotenv import load_dotenv

from llm.prompt import build, build_draft, build_draft_with_instruction, build_summary, parse

load_dotenv()

URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:latest")
BODY_CAP = 800
CLASSIFY_TIMEOUT = 90
DRAFT_TIMEOUT = 60
TIMEOUT = CLASSIFY_TIMEOUT  # backwards-compat alias if referenced elsewhere


def is_available() -> bool:
    try:
        return requests.get(f"{URL}/api/tags", timeout=2).ok
    except requests.RequestException:
        return False


def classify(subject: str, body: str, sender: str) -> tuple[str, str]:
    r = requests.post(
        f"{URL}/api/generate",
        json={
            "model": MODEL,
            "prompt": build(subject, body, sender, BODY_CAP),
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 120},
        },
        timeout=CLASSIFY_TIMEOUT,
    )
    r.raise_for_status()
    return parse(r.json()["response"].strip())


def summarize(subject: str, body: str, sender: str) -> str:
    r = requests.post(
        f"{URL}/api/generate",
        json={
            "model": MODEL,
            "prompt": build_summary(subject, body, sender, BODY_CAP),
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": 120},
        },
        timeout=DRAFT_TIMEOUT,
    )
    r.raise_for_status()
    return r.json()["response"].strip()


def draft(subject: str, body: str, sender: str, instruction: str | None = None) -> str:
    if instruction:
        prompt = build_draft_with_instruction(subject, body, sender, instruction, BODY_CAP)
    else:
        prompt = build_draft(subject, body, sender, BODY_CAP)
    r = requests.post(
        f"{URL}/api/generate",
        json={
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 250},
        },
        timeout=DRAFT_TIMEOUT,
    )
    r.raise_for_status()
    return r.json()["response"].strip()
