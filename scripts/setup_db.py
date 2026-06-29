#!/usr/bin/env python3
"""
DailyOps AI — Database Setup Script

Runs all migrations against your Supabase Postgres database and seeds a
test user so /api/test-run works immediately.

Usage:
    python scripts/setup_db.py

Requirements:
    DATABASE_URL must be set in backend/.env
    Get it from: Supabase dashboard → Project Settings → Database → URI
    Format: postgresql://postgres.PROJECT_REF:PASSWORD@HOST:PORT/postgres
"""

import asyncio
import os
import sys
from pathlib import Path

# ── Resolve paths ──────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent           # VoiceAI_Scheduler/
BACKEND = ROOT / "backend"
MIGRATIONS_DIR = ROOT / "migrations"

sys.path.insert(0, str(BACKEND))

# ── Load .env ──────────────────────────────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv(BACKEND / ".env")

DATABASE_URL = os.getenv("DATABASE_URL", "")

# ── Migration files in order ───────────────────────────────────────────────────
MIGRATION_FILES = [
    "001_initial_schema.sql",
    "002_conversation_state.sql",
]

# Fixed UUID for the dev/test user so test-run always links to a real row
TEST_USER_UUID = "00000000-0000-0000-0000-000000000001"
TEST_USER_EMAIL = "dev@dailyops.local"

SEED_SQL = f"""
INSERT INTO users (id, email, phone_number, full_name, home_address, work_address, timezone)
VALUES (
    '{TEST_USER_UUID}',
    '{TEST_USER_EMAIL}',
    '+10000000000',
    'Dev User',
    '123 Main St, New York, NY',
    '456 Work Ave, New York, NY',
    'America/New_York'
)
ON CONFLICT (id) DO NOTHING;

INSERT INTO user_preferences (user_id)
VALUES ('{TEST_USER_UUID}')
ON CONFLICT (user_id) DO NOTHING;
"""


def check_database_url() -> str:
    if not DATABASE_URL or DATABASE_URL.startswith("postgresql://postgres.PROJECT_REF"):
        print("\n❌  DATABASE_URL is not set in backend/.env")
        print("\nTo get it:")
        print("  1. Open your Supabase project dashboard")
        print("  2. Go to Project Settings → Database")
        print("  3. Copy the 'URI' under 'Connection String' (Transaction Pooler or Direct)")
        print("  4. Add to backend/.env:")
        print("     DATABASE_URL=postgresql://postgres.YOURREF:PASSWORD@HOST:PORT/postgres\n")
        sys.exit(1)
    return DATABASE_URL


async def run_migrations(conn) -> None:
    print("\n── Running migrations ──────────────────────────────────────────────")
    for filename in MIGRATION_FILES:
        path = MIGRATIONS_DIR / filename
        if not path.exists():
            print(f"  ⚠  Skipping {filename} (not found)")
            continue

        sql = path.read_text()
        print(f"  ▶  {filename} …", end=" ", flush=True)
        try:
            await conn.execute(sql)
            print("✓")
        except Exception as e:
            err = str(e)
            # Tolerate "already exists" errors so the script is idempotent
            if "already exists" in err or "duplicate" in err.lower():
                print(f"✓  (already exists, skipped)")
            else:
                print(f"\n  ✗  Failed: {err}")
                raise


async def seed_test_user(conn) -> None:
    print("\n── Seeding test user ───────────────────────────────────────────────")
    print(f"  UUID  : {TEST_USER_UUID}")
    print(f"  Email : {TEST_USER_EMAIL}")
    try:
        await conn.execute(SEED_SQL)
        print("  ✓  Test user ready")
    except Exception as e:
        print(f"  ⚠  Seed skipped: {e}")


def print_next_steps() -> None:
    print("\n── Next steps ──────────────────────────────────────────────────────")
    print(f"  Test user UUID: {TEST_USER_UUID}")
    print("  Trigger a run:")
    print("    curl -X POST 'http://localhost:8888/api/test-run?user_id=" + TEST_USER_UUID + "'")
    print("\n  Or set USER_ID in backend/.env and use the default test endpoint.\n")


async def main() -> None:
    import asyncpg

    url = check_database_url()
    print(f"\nConnecting to Supabase Postgres …")

    try:
        conn = await asyncio.wait_for(
            asyncpg.connect(url, ssl="require"),
            timeout=15,
        )
    except asyncio.TimeoutError:
        print("\n❌  Connection timed out. Check your DATABASE_URL and network.")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌  Could not connect: {e}")
        print("\nCommon fixes:")
        print("  • Wrong password in DATABASE_URL")
        print("  • Use the 'Transaction Pooler' URL (port 6543), not direct (5432)")
        print("    if you are on IPv4 only. Transaction pooler works everywhere.")
        sys.exit(1)

    try:
        await run_migrations(conn)
        await seed_test_user(conn)
    finally:
        await conn.close()

    print("\n✅  Setup complete!")
    print_next_steps()


if __name__ == "__main__":
    asyncio.run(main())
