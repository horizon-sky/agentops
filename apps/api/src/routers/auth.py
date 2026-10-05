"""Public signup, email verification, revocable login and password recovery."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.src.deps import (
    Principal,
    auth_db,
    client_ip,
    current_user,
    require_gateway,
    settings_dep,
)
from src.auth import (
    consume_mail_token,
    hash_password,
    issue_mail_token,
    rate_limit,
    token_digest,
    verify_password,
)
from src.config import Settings
from src.db.models import AuthSession, AuthToken, User

router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(require_gateway)])
MAIL_MESSAGE = "如果该邮箱符合条件，我们已发送邮件，请检查收件箱。"


class EmailIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr = Field(max_length=254)

    @field_validator("email", mode="after")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()


class LoginIn(EmailIn):
    password: str = Field(min_length=1, max_length=128)


class RegisterIn(LoginIn):
    password: str = Field(min_length=12, max_length=128)
    display_name: str = Field(min_length=1, max_length=80)

    @field_validator("display_name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("display name must not be blank")
        return value


class TokenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=1, max_length=256)


class ResetIn(TokenIn):
    password: str = Field(min_length=12, max_length=128)


def user_payload(user: User) -> dict[str, str]:
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role,
    }


def throttle(request: Request, settings: Settings, action: str, email: str = "") -> None:
    rate_limit(f"auth:{client_ip(request, settings)}", 100)
    if email:
        rate_limit(f"auth:{action}:{email}", 5 if action == "mail" else 10)


@router.post("/register", status_code=202)
async def register(
    payload: RegisterIn,
    request: Request,
    db: AsyncSession = Depends(auth_db),
    settings: Settings = Depends(settings_dep),
):
    throttle(request, settings, "mail", payload.email)
    user = await db.scalar(select(User).where(User.email == payload.email))
    if user is None:
        user = User(
            email=payload.email,
            password_hash=await hash_password(payload.password),
            display_name=payload.display_name,
        )
        db.add(user)
        try:
            await db.flush()
        except IntegrityError:
            # A concurrent signup won the unique-email constraint.
            await db.rollback()
            return {"message": MAIL_MESSAGE}
    if user.is_active and user.verified_at is None:
        await issue_mail_token(db, user, "verify", settings)
        await db.commit()
    return {"message": MAIL_MESSAGE}


@router.post("/resend-verification", status_code=202)
async def resend_verification(
    payload: EmailIn,
    request: Request,
    db: AsyncSession = Depends(auth_db),
    settings: Settings = Depends(settings_dep),
):
    throttle(request, settings, "mail", payload.email)
    user = await db.scalar(select(User).where(User.email == payload.email))
    if user and user.is_active and user.verified_at is None:
        await issue_mail_token(db, user, "verify", settings)
        await db.commit()
    return {"message": MAIL_MESSAGE}


@router.post("/verify-email")
async def verify_email(
    payload: TokenIn,
    request: Request,
    db: AsyncSession = Depends(auth_db),
    settings: Settings = Depends(settings_dep),
):
    throttle(request, settings, "verify")
    user = await consume_mail_token(db, payload.token, "verify")
    user.verified_at = datetime.now(UTC)
    await db.commit()
    return {"message": "邮箱验证成功，请登录。"}


@router.post("/login")
async def login(
    payload: LoginIn,
    request: Request,
    db: AsyncSession = Depends(auth_db),
    settings: Settings = Depends(settings_dep),
):
    throttle(request, settings, "login", payload.email)
    user = await db.scalar(select(User).where(User.email == payload.email).with_for_update())
    valid = await verify_password(payload.password, user.password_hash if user else None)
    if not user or not valid or not user.is_active:
        raise HTTPException(401, "邮箱或密码错误")
    if user.verified_at is None:
        raise HTTPException(403, "请先验证邮箱", headers={"X-Auth-Reason": "email_unverified"})
    token = secrets.token_urlsafe(32)
    ttl_seconds = max(1, min(settings.auth_session_hours, 24)) * 3600
    db.add(
        AuthSession(
            user_id=user.id,
            token_hash=token_digest(token),
            expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
        )
    )
    await db.commit()
    return {"user": user_payload(user), "token": token, "expires_in": ttl_seconds}


@router.get("/session")
async def session(identity: Principal = Depends(current_user)):
    return {"user": user_payload(identity.user)}


@router.post("/logout")
async def logout(identity: Principal = Depends(current_user), db: AsyncSession = Depends(auth_db)):
    identity.session.revoked_at = datetime.now(UTC)
    await db.commit()
    return {"message": "已退出登录。"}


@router.post("/forgot-password", status_code=202)
async def forgot_password(
    payload: EmailIn,
    request: Request,
    db: AsyncSession = Depends(auth_db),
    settings: Settings = Depends(settings_dep),
):
    throttle(request, settings, "mail", payload.email)
    user = await db.scalar(select(User).where(User.email == payload.email))
    if user and user.is_active and user.verified_at is not None:
        await issue_mail_token(db, user, "reset", settings)
        await db.commit()
    return {"message": MAIL_MESSAGE}


@router.post("/reset-password")
async def reset_password(
    payload: ResetIn,
    request: Request,
    db: AsyncSession = Depends(auth_db),
    settings: Settings = Depends(settings_dep),
):
    throttle(request, settings, "reset")
    user = await consume_mail_token(db, payload.token, "reset")
    user.password_hash = await hash_password(payload.password)
    now = datetime.now(UTC)
    await db.execute(
        update(AuthSession).where(AuthSession.user_id == user.id).values(revoked_at=now)
    )
    await db.execute(update(AuthToken).where(AuthToken.user_id == user.id).values(used_at=now))
    await db.commit()
    return {"message": "密码已更新，请重新登录。"}
