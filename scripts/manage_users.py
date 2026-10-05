"""Manage a verified account; never create a default or plaintext administrator password."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update

from src.config import get_settings
from src.db.models import AuthSession, Document, Session, User
from src.db.session import dispose_engine, get_session_factory

ARCHIVE_ID = UUID("00000000-0000-0000-0000-000000000001")


async def manage(args: argparse.Namespace) -> None:
    factory = get_session_factory(get_settings())
    if factory is None:
        raise RuntimeError("DATABASE_URL is required")
    try:
        async with factory() as db:
            user = await db.scalar(
                select(User).where(User.email == args.email.lower()).with_for_update()
            )
            if user is None or user.verified_at is None or user.id == ARCHIVE_ID:
                raise RuntimeError("A verified, non-archive account is required")
            if args.role:
                user.role = args.role
            if args.disable:
                user.is_active = False
            if args.enable:
                user.is_active = True
            if args.claim_legacy:
                if user.role != "admin":
                    raise RuntimeError("Only an administrator can claim archived resources")
                for model in (Session, Document):
                    await db.execute(
                        update(model).where(model.owner_id == ARCHIVE_ID).values(owner_id=user.id)
                    )
            await db.execute(
                update(AuthSession)
                .where(AuthSession.user_id == user.id)
                .values(revoked_at=datetime.now(UTC))
            )
            await db.commit()
            print("[ OK ] Account updated; existing login sessions revoked")
    finally:
        await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--role", choices=["admin", "member"])
    state = parser.add_mutually_exclusive_group()
    state.add_argument("--disable", action="store_true")
    state.add_argument("--enable", action="store_true")
    parser.add_argument("--claim-legacy", action="store_true")
    args = parser.parse_args()
    if not (args.role or args.disable or args.enable or args.claim_legacy):
        parser.error("choose --role, --disable, --enable or --claim-legacy")
    asyncio.run(manage(args))


if __name__ == "__main__":
    main()
