"""Run this once after changing OAuth scopes.

Deletes the old token, opens the Google consent screen in a browser, and saves
the new token. After this succeeds, start uvicorn normally.
"""
from gmail_client import TOKEN_PATH, get_service

if __name__ == "__main__":
    if TOKEN_PATH.exists():
        print(f"Removing old token: {TOKEN_PATH}")
        TOKEN_PATH.unlink()
    print("Opening browser for Google consent…")
    service = get_service()
    profile = service.users().getProfile(userId="me").execute()
    print(f"Authenticated as: {profile['emailAddress']}")
