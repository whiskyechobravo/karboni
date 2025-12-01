from typing import Any

import sqlalchemy
from sqlalchemy.engine import Engine


def create_engine(database_url: str) -> Engine:
    engine = sqlalchemy.create_engine(database_url)

    if engine.dialect.name == "sqlite":

        @sqlalchemy.event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection: Any, _: Any) -> None:
            # Raise IntegrityError on foreign key violations. Otherwise SQLite
            # fails silently by default, and we can end up with missing data.
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine
