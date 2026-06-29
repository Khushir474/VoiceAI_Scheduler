#!/usr/bin/env python3
"""
Get Google Calendar OAuth Refresh Token.

This script will:
1. Load credentials from .env
2. Open your browser to Google login
3. You authorize the app
4. Automatically update .env with REFRESH_TOKEN

Usage:
    pip install google-auth-oauthlib google-auth-httplib2 python-dotenv
    python get_refresh_token.py
"""

from google_auth_oauthlib.flow import InstalledAppFlow
from dotenv import load_dotenv
import os
import re

SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

def load_env_vars():
    """Load credentials from .env file."""
    load_dotenv()
    client_id = os.getenv('GOOGLE_CALENDAR_CLIENT_ID')
    client_secret = os.getenv('GOOGLE_CALENDAR_CLIENT_SECRET')

    if not client_id or not client_secret:
        print("❌ Error: Missing GOOGLE_CALENDAR_CLIENT_ID or GOOGLE_CALENDAR_CLIENT_SECRET in .env")
        exit(1)

    return client_id, client_secret

def update_env_file(refresh_token):
    """Update .env file with refresh token."""
    env_path = '.env'

    with open(env_path, 'r') as f:
        content = f.read()

    # Replace or add GOOGLE_CALENDAR_REFRESH_TOKEN
    pattern = r'GOOGLE_CALENDAR_REFRESH_TOKEN=.*'
    new_line = f'GOOGLE_CALENDAR_REFRESH_TOKEN={refresh_token}'

    if re.search(pattern, content):
        content = re.sub(pattern, new_line, content)
    else:
        content += f'\n{new_line}\n'

    with open(env_path, 'w') as f:
        f.write(content)

    print(f"✅ Updated .env with refresh token")

def get_refresh_token():
    """Run OAuth flow and get refresh token."""
    client_id, client_secret = load_env_vars()

    print("\n" + "="*70)
    print("GOOGLE CALENDAR OAUTH FLOW")
    print("="*70)
    print("1. Your browser will open")
    print("2. Sign in with your Google account")
    print("3. Click 'Allow' to authorize calendar access")
    print("4. You'll be redirected - this script will capture the token")
    print("="*70 + "\n")

    try:
        # Create OAuth flow from client credentials
        flow = InstalledAppFlow.from_client_config(
            {
                "installed": {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": ["http://localhost:8080/"],
                }
            },
            scopes=SCOPES
        )

        # Run local server - opens browser automatically
        creds = flow.run_local_server(port=8888)

        refresh_token = creds.refresh_token

        if not refresh_token:
            print("❌ Error: No refresh token received")
            exit(1)

        print("\n" + "="*70)
        print("✅ SUCCESS! Refresh token obtained")
        print("="*70)
        print(f"\nRefresh Token:\n{refresh_token}\n")

        # Update .env file
        update_env_file(refresh_token)
        print("\n✅ .env file updated successfully!")
        print("\nYou can now use DailyOps AI with Google Calendar!")

    except Exception as e:
        print(f"\n❌ Error during OAuth flow: {e}")
        print("\nTroubleshooting:")
        print("  1. Check GOOGLE_CALENDAR_CLIENT_ID in .env")
        print("  2. Check GOOGLE_CALENDAR_CLIENT_SECRET in .env")
        print("  3. Verify the credentials are valid on https://console.cloud.google.com/")
        exit(1)

if __name__ == "__main__":
    get_refresh_token()
