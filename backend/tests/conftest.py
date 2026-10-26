import os
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

# Explicit test DB required; never default to the application database.
TEST_URL = os.environ.get('TEST_DATABASE_URL')
from app.main import app
from app.db import get_db
from app.auth import current_owner

OWNER = uuid.UUID('11111111-1111-4111-8111-111111111111')
OTHER = uuid.UUID('22222222-2222-4222-8222-222222222222')

@pytest.fixture
def db():
    if not TEST_URL:
        pytest.fail('Set TEST_DATABASE_URL to a migrated, disposable PostgreSQL database')
    engine = create_engine(TEST_URL)
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
            yield session
        transaction.rollback()
    engine.dispose()

@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[current_owner] = lambda: OWNER
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
