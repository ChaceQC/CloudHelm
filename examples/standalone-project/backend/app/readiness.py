from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text


def database_matches_head(engine: Engine | None, alembic_ini: Path) -> bool:
    if engine is None:
        return False

    try:
        script = ScriptDirectory.from_config(Config(str(alembic_ini)))
        heads = script.get_heads()
        if len(heads) != 1:
            return False

        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            revisions = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalars().all()
        return revisions == heads
    except Exception:
        return False
