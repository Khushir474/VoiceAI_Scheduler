#!/usr/bin/env python3
"""
Setup messaging: iMessage Bridge (primary) with Twilio fallback.

This script:
1. Tries to set up and test iMessage bridge
2. Falls back to Twilio if iMessage fails
3. Automatically updates .env with working configuration

Usage:
    python setup_messaging.py
"""

import os
import subprocess
import sys
import requests
import time
import re
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

class MessagingSetup:
    def __init__(self):
        self.imessage_url = "http://localhost:8001"
        self.imessage_repo = "imessage-rest"
        self.env_file = ".env"

    def print_header(self, text):
        """Print formatted header."""
        print("\n" + "=" * 70)
        print(text)
        print("=" * 70 + "\n")

    def print_step(self, step_num, text):
        """Print numbered step."""
        print(f"[{step_num}] {text}")

    def run_command(self, cmd, description=""):
        """Run shell command and return success status."""
        try:
            if description:
                print(f"  → {description}...")
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=10
            )
            return result.returncode == 0, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return False, "", "Timeout"
        except Exception as e:
            return False, "", str(e)

    def check_imessage_installed(self):
        """Check if imessage-rest is installed."""
        success, _, _ = self.run_command(
            "pip list | grep imessage-rest",
            "Checking if imessage-rest is installed"
        )
        return success

    def clone_imessage_bridge(self):
        """Clone imessage-rest repository."""
        self.print_step("A", "Cloning iMessage bridge repository")

        # Try multiple repositories
        repos = [
            ("https://github.com/ReagentX/imessage-rest.git", "ReagentX/imessage-rest"),
            ("https://github.com/dteviot/imessage-rest.git", "dteviot/imessage-rest"),
            ("https://github.com/EricBagwell/PyiMessageAccount.git", "EricBagwell/PyiMessageAccount"),
        ]

        for repo_url, repo_name in repos:
            print(f"  → Trying {repo_name}...")
            success, out, err = self.run_command(
                f"git clone {repo_url} imessage_bridge 2>/dev/null",
                ""
            )
            if success:
                print(f"  ✅ Cloned {repo_name}")
                return True

        print("  ❌ All repositories failed to clone")
        print("  ℹ️  Alternative: Install pre-built bridge with: pip install imessage-rest")
        return False

    def install_imessage_dependencies(self):
        """Install imessage-rest dependencies."""
        self.print_step("B", "Installing dependencies")

        # Check if requirements.txt exists
        if not Path("imessage_bridge/requirements.txt").exists():
            print("  ⚠️  requirements.txt not found, trying pip install imessage-rest")
            success, out, err = self.run_command(
                "pip install imessage-rest",
                "Installing imessage-rest via pip"
            )
        else:
            success, out, err = self.run_command(
                "pip install -r imessage_bridge/requirements.txt",
                "Installing from requirements.txt"
            )

        if success:
            print("  ✅ Dependencies installed")
            return True
        else:
            print(f"  ❌ Failed to install: {err}")
            return False

    def start_imessage_bridge(self):
        """Start iMessage bridge in background."""
        self.print_step("C", "Starting iMessage bridge")

        # Kill any existing process on port 8001
        self.run_command("lsof -ti:8001 | xargs kill -9 2>/dev/null", "Stopping any existing bridge")

        # Start in background
        print("  → Starting bridge on port 8001...")
        self.run_command(
            "nohup python imessage_bridge/server.py > imessage_bridge.log 2>&1 &",
            "Starting background process"
        )

        # Wait for it to start
        time.sleep(3)

        # Check if it's running
        success, _, _ = self.run_command(
            "lsof -ti:8001",
            "Checking if bridge is running"
        )

        if success:
            print("  ✅ iMessage bridge started on port 8001")
            return True
        else:
            print("  ❌ Failed to start iMessage bridge")
            return False

    def test_imessage_bridge(self):
        """Test iMessage bridge connectivity."""
        self.print_step("D", "Testing iMessage bridge")

        try:
            response = requests.get(f"{self.imessage_url}/", timeout=5)
            if response.status_code in [200, 404]:  # 404 is fine for GET on /
                print(f"  ✅ iMessage bridge is responding")
                return True
        except requests.exceptions.ConnectionError:
            print(f"  ❌ Cannot connect to {self.imessage_url}")
        except Exception as e:
            print(f"  ❌ Error testing bridge: {e}")

        return False

    def setup_twilio(self):
        """Load Twilio credentials from .env or prompt."""
        self.print_header("TWILIO SETUP (Fallback Messaging)")

        # Check if credentials already in .env
        account_sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
        auth_token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
        twilio_phone = os.getenv("TWILIO_PHONE_NUMBER", "").strip()
        user_phone = os.getenv("USER_PHONE_NUMBER", "").strip()

        # Filter out placeholder values
        if all([
            account_sid and account_sid != "your-account-sid",
            auth_token and auth_token != "your-auth-token",
            twilio_phone and twilio_phone != "+1234567890",
            user_phone and user_phone != "+1234567890"
        ]):
            print("✅ Found existing Twilio credentials in .env")
            print(f"   Account SID: {account_sid[:10]}...")
            print(f"   Phone: {twilio_phone}")
            return {
                "account_sid": account_sid,
                "auth_token": auth_token,
                "twilio_phone": twilio_phone,
                "user_phone": user_phone
            }

        print("Twilio credentials not found or incomplete in .env\n")
        print("Get your Twilio credentials:")
        print("1. Sign up at https://www.twilio.com/ (free trial)")
        print("2. Verify your phone number")
        print("3. Get your Account SID, Auth Token, and phone number\n")

        try:
            account_sid = input("Enter TWILIO_ACCOUNT_SID (or press Enter to skip): ").strip()
            if not account_sid:
                print("⚠️  Skipping Twilio setup")
                return None

            auth_token = input("Enter TWILIO_AUTH_TOKEN: ").strip()
            twilio_phone = input("Enter TWILIO_PHONE_NUMBER (e.g., +1234567890): ").strip()
            user_phone = input("Enter USER_PHONE_NUMBER (your phone): ").strip()

            if all([account_sid, auth_token, twilio_phone, user_phone]):
                print("\n✅ Twilio credentials received")
                return {
                    "account_sid": account_sid,
                    "auth_token": auth_token,
                    "twilio_phone": twilio_phone,
                    "user_phone": user_phone
                }
            else:
                print("❌ Missing Twilio credentials")
                return None
        except EOFError:
            print("⚠️  Non-interactive mode detected, using existing .env credentials")
            return None

    def update_env_file(self, imessage_success, twilio_creds=None):
        """Update .env with messaging configuration."""
        if not Path(self.env_file).exists():
            print(f"❌ {self.env_file} not found")
            return False

        with open(self.env_file, 'r') as f:
            content = f.read()

        updates = {}

        if imessage_success:
            updates['IMESSAGE_BRIDGE_URL'] = 'http://localhost:8001'
            print("✅ Configured iMessage as primary messaging")

        if twilio_creds:
            updates['TWILIO_ACCOUNT_SID'] = twilio_creds['account_sid']
            updates['TWILIO_AUTH_TOKEN'] = twilio_creds['auth_token']
            updates['TWILIO_PHONE_NUMBER'] = twilio_creds['twilio_phone']
            updates['USER_PHONE_NUMBER'] = twilio_creds['user_phone']
            print("✅ Configured Twilio as fallback messaging")

        # Update or add each variable
        for key, value in updates.items():
            pattern = rf'^{key}=.*$'
            if re.search(pattern, content, re.MULTILINE):
                content = re.sub(pattern, f'{key}={value}', content, flags=re.MULTILINE)
            else:
                content += f'\n{key}={value}\n'

        with open(self.env_file, 'w') as f:
            f.write(content)

        return True

    def run(self):
        """Main setup flow."""
        self.print_header("DAILYOPS AI – MESSAGING SETUP")
        print("This script will set up messaging with:")
        print("  • Primary: iMessage Bridge (if available)")
        print("  • Fallback: Twilio SMS (recommended)\n")

        # Check if on Mac
        success, _, _ = self.run_command("uname | grep Darwin", "Checking if running on Mac")
        if not success:
            print("⚠️  Not running on macOS. iMessage bridge requires macOS.")
            print("   Proceeding with Twilio-only setup...\n")
            imessage_success = False
        else:
            print("✅ Running on macOS – iMessage bridge is available\n")
            imessage_success = self._setup_imessage()

        # Setup Twilio fallback (will use existing creds if found)
        twilio_creds = self.setup_twilio()

        # Validate we have at least one option
        if not imessage_success and not twilio_creds:
            # Check if Twilio already in .env
            existing_sid = os.getenv("TWILIO_ACCOUNT_SID", "")
            if existing_sid and existing_sid != "your-account-sid":
                print("✅ Using existing Twilio credentials from .env")
                twilio_creds = {"existing": True}
            else:
                print("\n❌ No messaging configured. Please set up Twilio.")
                return False

        # Update .env
        self.print_header("UPDATING CONFIGURATION")
        if self.update_env_file(imessage_success, twilio_creds):
            print("✅ .env updated successfully")
        else:
            return False

        # Print summary
        self._print_summary(imessage_success, twilio_creds)
        return True

    def _setup_imessage(self):
        """Try to set up iMessage bridge."""
        self.print_header("IMESSAGE BRIDGE SETUP")

        # Check if already cloned
        if Path("imessage_bridge").exists():
            print("imessage_bridge directory already exists")
        else:
            if not self.clone_imessage_bridge():
                print("⚠️  Skipping iMessage bridge (clone failed)")
                return False

        if not self.install_imessage_dependencies():
            print("⚠️  Skipping iMessage bridge (install failed)")
            return False

        if not self.start_imessage_bridge():
            print("⚠️  Could not start iMessage bridge")
            return False

        if not self.test_imessage_bridge():
            print("⚠️  iMessage bridge test failed")
            return False

        return True

    def _print_summary(self, imessage_success, twilio_creds):
        """Print configuration summary."""
        self.print_header("CONFIGURATION SUMMARY")

        print("Messaging Configuration:")
        if imessage_success:
            print("  ✅ iMessage Bridge: http://localhost:8001 (PRIMARY)")
            print("     → Summaries will be sent via iMessage")
        else:
            print("  ⚠️  iMessage Bridge: Not configured")

        if twilio_creds:
            print(f"  ✅ Twilio SMS: {twilio_creds['twilio_phone']} (FALLBACK)")
            print(f"     → Will be used if iMessage fails or is unavailable")
        else:
            print("  ⚠️  Twilio SMS: Not configured")

        print("\nFlow:")
        if imessage_success and twilio_creds:
            print("  1. Try to send via iMessage bridge")
            print("  2. If bridge is down → Fall back to Twilio SMS")
        elif imessage_success:
            print("  → Use iMessage bridge only")
        elif twilio_creds:
            print("  → Use Twilio SMS only")

        print("\n✅ Setup complete! .env updated.")
        print("\nTo start using DailyOps:")
        print("  1. If using iMessage bridge: keep 'python imessage_bridge/server.py' running")
        print("  2. Start the backend: python -m app.main")
        print("  3. Visit http://localhost:3000")

if __name__ == "__main__":
    setup = MessagingSetup()
    success = setup.run()
    sys.exit(0 if success else 1)
