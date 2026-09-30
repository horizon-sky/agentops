from sqlalchemy.engine import make_url

from src.config import Settings
from src.db import session as db_session


def test_neon_url_is_accepted_by_async_engine(monkeypatch) -> None:
    urls = []
    monkeypatch.setattr(db_session, "_engine", None)
    def fake_create_engine(url, **kwargs):
        urls.append(url)
        return object()

    monkeypatch.setattr(db_session, "create_async_engine", fake_create_engine)
    settings = Settings(
        _env_file=None,
        database_url=(
            "postgresql://user:secret@localhost/agentops?sslmode=require&channel_binding=require"
        ),
    )

    db_session.get_engine(settings)

    url = make_url(urls[0])
    assert url.drivername == "postgresql+asyncpg"
    assert url.query == {"ssl": "require"}
    monkeypatch.setattr(db_session, "_engine", None)
