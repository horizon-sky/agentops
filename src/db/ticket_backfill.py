"""Conservative, repeatable import of legacy successful tool snapshots."""

from __future__ import annotations

import re
import uuid
from collections import defaultdict

from pydantic import ValidationError
from sqlalchemy import select

from src.db.models import Run, Session, Ticket
from src.tickets import TicketFields


def backfill_tickets(connection) -> dict[str, int]:
    report = {"imported": 0, "existing": 0, "invalid": 0, "conflicts": 0}
    rows = connection.execute(
        select(Run.id, Run.tool_results, Run.started_at, Session.owner_id)
        .join(Session)
        .order_by(Run.started_at, Run.id)
    ).mappings()
    groups = defaultdict(list)
    for row in rows:
        for result in row["tool_results"] or []:
            if not isinstance(result, dict):
                report["invalid"] += 1
                continue
            if result.get("name") != "create_ticket" or result.get("ok") is not True:
                continue
            output = result.get("output")
            args = result.get("args")
            if not isinstance(output, dict):
                report["invalid"] += 1
                continue
            args = args if isinstance(args, dict) else {}
            number = output.get("ticket_id")
            try:
                if not isinstance(number, str) or not re.fullmatch(r"OPS-[\w-]{1,60}", number):
                    raise ValueError("Invalid ticket number")
                fields = TicketFields(
                    title=output.get("title", args.get("title", "")),
                    detail=output.get("detail", args.get("detail", "")),
                    severity=output.get("severity", args.get("severity", "P2")),
                )
                if output.get("status", "created") != "created":
                    raise ValueError("Unexpected legacy status")
            except (ValueError, ValidationError):
                report["invalid"] += 1
                continue
            groups[(row["owner_id"], number)].append((fields.model_dump(), row))
    for (owner_id, number), candidates in groups.items():
        fields, row = candidates[0]
        key = f"legacy:{number}"
        existing = connection.execute(
            select(Ticket.id).where(
                Ticket.owner_id == owner_id,
                (Ticket.idempotency_key == key) | (Ticket.ticket_id == number),
            )
        ).first()
        if existing:
            report["existing"] += 1
            continue
        if any(other != fields for other, _ in candidates):
            report["conflicts"] += 1
            continue
        connection.execute(
            Ticket.__table__.insert().values(
                id=uuid.uuid4(),
                ticket_id=number,
                owner_id=owner_id,
                run_id=row["id"],
                idempotency_key=key,
                status="created",
                created_at=row["started_at"],
                updated_at=row["started_at"],
                **fields,
            )
        )
        report["imported"] += 1
    return report
