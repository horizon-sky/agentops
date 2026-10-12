"""Publish a reviewed summary to the DATABASE_URL target; never run evaluations here."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from src.config import get_settings
from src.db.eval_reports import publish_report
from src.db.session import dispose_engine, get_session_factory
from src.eval_report import CompletedEvalReport


async def publish(path: Path, email: str) -> bool:
    report = CompletedEvalReport.model_validate_json(path.read_text(encoding="utf-8"))
    factory = get_session_factory(get_settings())
    if factory is None:
        raise ValueError("DATABASE_URL is required for publication")
    try:
        async with factory() as db:
            return await publish_report(db, report, email)
    finally:
        await dispose_engine()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument(
        "--email", required=True, help="Verified administrator in the target database",
    )
    args = parser.parse_args()
    try:
        changed = asyncio.run(publish(args.report, args.email))
    except ValidationError:
        print("[FAIL] Invalid or incomplete report; generate a versioned report", file=sys.stderr)
        return 1
    except SQLAlchemyError:
        print("[FAIL] Database publication failed; report was not published", file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        # Do not print filesystem or connection details from system exceptions.
        message = str(exc) if isinstance(exc, ValueError) else "Cannot read report file"
        print(f"[FAIL] {message}", file=sys.stderr)
        return 1
    print("[ OK ] Report published" if changed else "[ OK ] Identical report already published")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
