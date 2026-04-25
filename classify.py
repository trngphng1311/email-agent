"""CLI — run the sync pipeline and print per-email progress."""
from sync import sync


def main() -> None:
    processed = 0
    for record in sync(max_results=10):
        processed += 1
        email = record["email"]
        result = record["result"]
        flag = "[S]" if result.get("sensitive") else "   "
        print(f"{processed:>2}. {flag} [{result['label']}] via {result['route']}")
        print(f"     Subject: {email['subject']}")
        print(f"     From:    {email['sender']}")
        print(f"     Why:     {result['reason']}\n")
    print(f"Saved {processed} emails to app.db")


if __name__ == "__main__":
    main()
