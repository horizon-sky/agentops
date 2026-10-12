"""PNG registration challenges with persisted, atomic single-attempt consumption."""

from __future__ import annotations

import asyncio
import base64
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from io import BytesIO

from fastapi import HTTPException
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import token_digest
from src.db.models import AuthCaptcha

ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def render_image(answer: str) -> str:
    image = Image.new("RGB", (220, 72), "#f4f7fc")
    draw = ImageDraw.Draw(image)
    for _ in range(5):
        draw.line(
            [(secrets.randbelow(220), secrets.randbelow(72)) for _ in range(2)],
            fill="#b7c5d9", width=1,
        )
    font = ImageFont.load_default(size=36)
    for index, char in enumerate(answer):
        glyph = Image.new("RGBA", (42, 56))
        ImageDraw.Draw(glyph).text((5, 7), char, font=font, fill="#253451")
        glyph = glyph.rotate(secrets.randbelow(25) - 12, resample=Image.Resampling.BICUBIC)
        image.paste(glyph, (7 + index * 41, 6 + secrets.randbelow(5)), glyph)
    output = BytesIO()
    image.save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")


async def issue_captcha(db: AsyncSession) -> dict[str, str]:
    now = datetime.now(UTC)
    captcha_id = uuid.uuid4()
    answer = "".join(secrets.choice(ALPHABET) for _ in range(5))
    image = await asyncio.to_thread(render_image, answer)
    expires_at = now + timedelta(minutes=5)
    await db.execute(delete(AuthCaptcha).where(AuthCaptcha.expires_at <= now))
    db.add(AuthCaptcha(
        id=captcha_id, answer_hash=token_digest(f"{captcha_id}:{answer}"), expires_at=expires_at,
    ))
    await db.commit()
    return {
        "captcha_id": str(captcha_id), "image_data_url": image,
        "expires_at": expires_at.isoformat(),
    }


async def consume_captcha(db: AsyncSession, captcha_id: uuid.UUID, answer: str) -> None:
    claimed = (await db.execute(
        delete(AuthCaptcha).where(AuthCaptcha.id == captcha_id)
        .returning(AuthCaptcha.answer_hash, AuthCaptcha.expires_at)
    )).first()
    # This transaction must survive every later failure, including an incorrect answer.
    await db.commit()
    if claimed is not None:
        digest, expires_at = claimed
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        correct = secrets.compare_digest(digest, token_digest(f"{captcha_id}:{answer.upper()}"))
        if expires_at > datetime.now(UTC) and correct:
            return
    raise HTTPException(400, "验证码错误、已过期或已使用，请刷新后重试")
