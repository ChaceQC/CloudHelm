from collections.abc import Iterator

from fastapi import HTTPException, Request
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker


SessionFactory = sessionmaker[Session]


def build_database(database_url: str | None):
    if not database_url:
        return None, None

    try:
        engine = create_engine(
            database_url,
            pool_pre_ping=True,
            pool_timeout=2,
            connect_args={"connect_timeout": 2},
            hide_parameters=True,
        )
    except Exception:
        return None, None

    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def get_session(request: Request) -> Iterator[Session]:
    factory: SessionFactory | None = request.app.state.session_factory
    if factory is None:
        raise HTTPException(status_code=503, detail="database unavailable")

    session = factory()
    try:
        yield session
    except SQLAlchemyError:
        try:
            session.rollback()
        except SQLAlchemyError:
            pass
        raise HTTPException(status_code=503, detail="database unavailable") from None
    finally:
        try:
            session.close()
        except SQLAlchemyError:
            pass
