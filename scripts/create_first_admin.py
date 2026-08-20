#!/usr/bin/env python3
"""
Create the first admin user on a fresh install.

Every path in app/api/users.py's create_user requires an existing admin
(current_user.role == "admin"), which is correct for day-to-day operation but
leaves no way to create the very first user through the API alone -- a
genuinely empty fim.users table has no admin to authorize the request that
would create one. This script exists solely to break that chicken-and-egg
problem, once, on a fresh database. It is NOT scripts/create_test_users.py
(that one hardcodes weak passwords like "admin123" for four different roles
and is dev/test-only -- do not use it for a real deployment).

Usage (run from the app's venv, e.g. after `alembic upgrade head`):
    venv/bin/python scripts/create_first_admin.py

Prompts for username/email/password interactively (password via getpass, so
it isn't echoed to the terminal or left in shell history). Refuses to run if
an admin already exists, so it's safe to leave in place rather than needing
to be deleted after first use.
"""
import asyncio
import getpass
import sys
import uuid

sys.path.insert(0, ".")

from sqlalchemy import select

from app.core.database import db_manager
from app.core.security import get_password_hash, validate_password_policy
from app.models import User


async def main() -> int:
    await db_manager.initialize()
    try:
        return await _run()
    finally:
        await db_manager.close()


async def _run() -> int:
    async with db_manager.async_session() as db:
        existing_admin = await db.execute(
            select(User).where(User.role == "admin", User.is_active == True)
        )
        if existing_admin.scalar_one_or_none():
            print("An active admin user already exists -- refusing to create another "
                  "via this bootstrap script. Use the Users page (as that admin) instead.")
            return 1

        username = input("Admin username: ").strip()
        email = input("Admin email: ").strip()
        full_name = input("Full name [System Administrator]: ").strip() or "System Administrator"

        if not username or not email:
            print("Username and email are required.")
            return 1

        existing = await db.execute(select(User).where(User.username == username))
        if existing.scalar_one_or_none():
            print(f"Username '{username}' already exists.")
            return 1

        while True:
            password = getpass.getpass("Admin password: ")
            confirm = getpass.getpass("Confirm password: ")
            if password != confirm:
                print("Passwords don't match -- try again.")
                continue
            is_valid, error_msg = validate_password_policy(password)
            if not is_valid:
                print(f"Password policy violation: {error_msg}")
                continue
            break

        user = User(
            id=uuid.uuid4(),
            username=username,
            email=email,
            password_hash=get_password_hash(password),
            full_name=full_name,
            role="admin",
            is_active=True,
        )
        db.add(user)
        await db.commit()
        print(f"Created admin user '{username}'. Log in via the frontend to create further users.")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
