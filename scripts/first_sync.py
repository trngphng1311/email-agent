"""Bulk-import historical mail into app.db from the terminal.

Usage:
    .venv/bin/python scripts/first_sync.py                       # default 200 mails
    .venv/bin/python scripts/first_sync.py 500                   # custom count
    .venv/bin/python scripts/first_sync.py 100 'is:unread'       # with a query
    .venv/bin/python scripts/first_sync.py 200 '' 2026-03-01 2026-04-01   # date range

Resumable: re-running skips already-classified emails.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bulk import bulk_import
from gmail_client import get_service


def _print_progress(p: dict) -> None:
    cur = p.get("current")
    prefix = f"[{p['processed']:>4}/{p['total']}]"
    stats = f"({p['classified']} classified, {p['skipped']} cached)"
    if cur:
        print(f"{prefix} {stats}  {cur}")


def main() -> None:
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    query = sys.argv[2] if len(sys.argv) > 2 else None
    after = sys.argv[3] if len(sys.argv) > 3 else None
    before = sys.argv[4] if len(sys.argv) > 4 else None

    service = get_service()
    result = bulk_import(
        service,
        count=count,
        query=query or None,
        after=after or None,
        before=before or None,
        on_progress=_print_progress,
    )
    print(
        f"\nDone. {result['classified']} newly classified, "
        f"{result['skipped']} already cached."
    )


if __name__ == "__main__":
    main()
