import pytest
from fastapi import HTTPException

from apps.api.src.routers.runs import _validate_approval_text
from apps.api.src.schemas.api import ResumeIn


def test_ticket_write_requires_exact_follow_up_confirmation_text():
    approval = {"tool": "create_ticket"}
    _validate_approval_text(
        approval,
        ResumeIn(ok=True, confirmation_text="确认创建"),
    )

    for text in (None, "确认创建工单", "请确认创建"):
        with pytest.raises(HTTPException) as error:
            _validate_approval_text(
                approval,
                ResumeIn(ok=True, confirmation_text=text),
            )
        assert error.value.status_code == 400


def test_rejection_does_not_require_creation_confirmation_text():
    _validate_approval_text(
        {"tool": "create_ticket"},
        ResumeIn(ok=False, confirmation_text="拒绝创建"),
    )
