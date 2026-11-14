"""One-time: let the bot read (and RSVP on) the notetaker's calendar.

Run locally, sign in as the notetaker account (notetaker@example.com) in
the browser tab it opens, and it prints the GOOGLE_CALENDAR_REFRESH_TOKEN to
put in backend/bot/.env.

    python authorize_calendar.py path/to/client_secret_....json

The client secret must be a Google OAuth client of type "Desktop app".
"""

import http.server
import json
import os
import secrets
import sys
import urllib.parse
import webbrowser

import httpx

SCOPE = "https://www.googleapis.com/auth/calendar.events"
# Any loopback port works for a Desktop OAuth client; 8765 is often taken.
PORT = int(os.environ.get("CALENDAR_AUTH_PORT", "8799"))


def main(client_secret_path: str) -> None:
    client = json.load(open(client_secret_path))
    client = client.get("installed") or client.get("web")
    redirect_uri = f"http://127.0.0.1:{PORT}"
    state = secrets.token_urlsafe(16)
    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(
        {
            "client_id": client["client_id"],
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            "access_type": "offline",
            # Forces a refresh token even if this account authorized before.
            "prompt": "consent",
            "login_hint": "notetaker@example.com",
            "state": state,
        }
    )

    received: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
            received.update(query)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Done - you can close this tab and go back to the terminal.")

        def log_message(self, *args):
            pass

    print("Opening the Google consent screen. Sign in as the NOTETAKER account.")
    print(f"If no browser opens, visit:\n{auth_url}\n")
    webbrowser.open(auth_url)
    server = http.server.HTTPServer(("127.0.0.1", PORT), Handler)
    while "code" not in received and "error" not in received:
        server.handle_request()

    if received.get("error") or received.get("state") != state:
        raise SystemExit(f"Authorization failed: {received}")

    response = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": received["code"],
            "client_id": client["client_id"],
            "client_secret": client["client_secret"],
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
    )
    response.raise_for_status()
    tokens = response.json()
    if "refresh_token" not in tokens:
        raise SystemExit(f"Google returned no refresh token: {tokens}")

    print("Add these to backend/bot/.env on the server:\n")
    print(f"GOOGLE_OAUTH_CLIENT_ID={client['client_id']}")
    print(f"GOOGLE_OAUTH_CLIENT_SECRET={client['client_secret']}")
    print(f"GOOGLE_CALENDAR_REFRESH_TOKEN={tokens['refresh_token']}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(f"Usage: python {sys.argv[0]} <client_secret.json>")
    main(sys.argv[1])
