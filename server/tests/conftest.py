import os
from collections.abc import Iterator

import pytest

# Settings and the SQLAlchemy engine are constructed during app import. Keep tests on a named,
# shared in-memory database so authorization integration tests never touch server/wxzy.db.
os.environ["DATABASE_URL"] = (
    "sqlite+pysqlite:///file:wxzy-p0-tests?mode=memory&cache=shared&uri=true"
)
os.environ["API_TOKEN"] = "test-token"


@pytest.fixture(scope="session", autouse=True)
def database_schema() -> Iterator[None]:
    """Create the isolated test schema explicitly; production startup never creates tables."""
    from app import models
    from app.db import Base, engine

    assert models.Base.metadata is Base.metadata
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
