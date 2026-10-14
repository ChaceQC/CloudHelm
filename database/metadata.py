"""One metadata registry for the Hub business schema; DBOS owns its own schema."""

from sqlalchemy import MetaData

BUSINESS_SCHEMA = "cloudhelm"

metadata = MetaData(
    schema=BUSINESS_SCHEMA,
    naming_convention={
        "pk": "pk_%(table_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "ix": "ix_%(table_name)s_%(column_0_name)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
    },
)
