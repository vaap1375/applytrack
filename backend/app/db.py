from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import settings

class Base(DeclarativeBase):
    pass

def database_url(value):
    url = make_url(value)
    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+psycopg")
    return url

engine = create_engine(database_url(settings().database_url), pool_pre_ping=True,
                       pool_size=2, max_overflow=3, pool_timeout=10,
                       pool_recycle=300, connect_args={"connect_timeout": 10}, hide_parameters=True)
SessionLocal = sessionmaker(engine)

def get_db():
    with SessionLocal() as session:
        yield session
