"""Two-way Google Calendar sync for the Schedule tab.

Uses the OAuth "installed app" flow, which is exactly right for a local
Streamlit prototype: the first time you connect, a browser window opens, you
grant access, and a token is cached in token.json for subsequent runs.

Setup (one time):
  1. Create a Google Cloud project at https://console.cloud.google.com
  2. Enable the "Google Calendar API".
  3. Create an OAuth client ID of type "Desktop app".
  4. Download the JSON and save it as `credentials.json` next to this file.

Everything degrades gracefully if google libraries or credentials are missing —
the Schedule tab will tell the user what to do rather than crash.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

HERE = os.path.dirname(__file__)
CREDENTIALS_PATH = os.environ.get("GCAL_CREDENTIALS", os.path.join(HERE, "credentials.json"))
TOKEN_PATH = os.environ.get("GCAL_TOKEN", os.path.join(HERE, "token.json"))
SCOPES = ["https://www.googleapis.com/auth/calendar"]


def libs_available() -> bool:
    try:
        import google.auth  # noqa: F401
        import googleapiclient  # noqa: F401
        import google_auth_oauthlib  # noqa: F401
        return True
    except Exception:
        return False


def credentials_present() -> bool:
    return os.path.exists(CREDENTIALS_PATH)


def is_connected() -> bool:
    return os.path.exists(TOKEN_PATH)


def setup_hint() -> str:
    if not libs_available():
        return (
            "Google libraries aren't installed. Run:\n\n"
            "    pip install google-api-python-client google-auth-httplib2 "
            "google-auth-oauthlib"
        )
    if not credentials_present():
        return (
            f"No `credentials.json` found at {CREDENTIALS_PATH}.\n\n"
            "1. Create a Google Cloud project and enable the Google Calendar API.\n"
            "2. Create an OAuth client ID of type **Desktop app**.\n"
            "3. Download it as `credentials.json` into the app folder."
        )
    return "Ready to connect — click **Connect Google Calendar**."


def _load_service():
    """Build an authenticated Calendar service, refreshing/launching OAuth as needed."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def connect() -> None:
    """Force the OAuth flow (opens a browser) and cache the token."""
    _load_service()


def disconnect() -> None:
    if os.path.exists(TOKEN_PATH):
        os.remove(TOKEN_PATH)


def list_calendars() -> list[dict]:
    service = _load_service()
    items = service.calendarList().list().execute().get("items", [])
    return [
        {"id": c["id"], "summary": c.get("summary", c["id"]), "primary": c.get("primary", False)}
        for c in items
    ]


def _to_rfc3339(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def list_events(calendar_id: str, time_min: datetime, time_max: datetime) -> list[dict]:
    service = _load_service()
    resp = (
        service.events()
        .list(
            calendarId=calendar_id,
            timeMin=_to_rfc3339(time_min),
            timeMax=_to_rfc3339(time_max),
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    out = []
    for e in resp.get("items", []):
        start = e["start"].get("dateTime", e["start"].get("date"))
        end = e["end"].get("dateTime", e["end"].get("date"))
        out.append(
            {
                "id": e["id"],
                "summary": e.get("summary", "(no title)"),
                "location": e.get("location", ""),
                "description": e.get("description", ""),
                "start": start,
                "end": end,
                "all_day": "date" in e["start"],
                "html_link": e.get("htmlLink", ""),
            }
        )
    return out


def create_event(
    calendar_id: str,
    summary: str,
    start: datetime,
    end: datetime,
    location: str = "",
    description: str = "",
) -> dict:
    service = _load_service()
    body = {
        "summary": summary,
        "location": location,
        "description": description,
        "start": {"dateTime": _to_rfc3339(start)},
        "end": {"dateTime": _to_rfc3339(end)},
    }
    return service.events().insert(calendarId=calendar_id, body=body).execute()


def delete_event(calendar_id: str, event_id: str) -> None:
    service = _load_service()
    service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
