from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
from app.db import Base, database_url
from app.config import settings
from app import models, gmail_models

engine = create_engine(database_url(settings().migration_database_url or settings().database_url),
                       poolclass=NullPool, hide_parameters=True, connect_args={"connect_timeout": 10})
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
