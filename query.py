"""Milestone 3 demo — query the SQLite store.

Usage:
    python query.py                    # IMPORTANT in the last 7 days
    python query.py PERSONAL           # PERSONAL in the last 7 days
    python query.py PERSONAL 30        # PERSONAL in the last 30 days
    python query.py ALL 7              # any label in the last 7 days
"""
import sys

from db.store import query_emails


def main() -> None:
    label_arg = sys.argv[1].upper() if len(sys.argv) > 1 else "IMPORTANT"
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
    label = None if label_arg == "ALL" else label_arg

    rows = query_emails(label=label, since_days=days)
    scope = label or "any label"
    if not rows:
        print(f"No {scope} emails in the last {days} days.")
        return

    print(f"{len(rows)} {scope} email(s) in the last {days} days:\n")
    for i, r in enumerate(rows, 1):
        flag = "[S]" if r["sensitive"] else "   "
        attach = " 📎" if r["has_attachment"] else ""
        print(f"{i:>2}. {flag} [{r['label']:<11}] {r['date'][:19]}  {r['sender_email']}{attach}")
        print(f"       {r['subject']}")
        if r["label_reason"]:
            print(f"       ({r['label_reason']})")
        print()


if __name__ == "__main__":
    main()
