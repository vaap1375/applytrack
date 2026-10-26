from uuid import UUID
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from .config import settings
from .db import get_db, engine
from .auth import current_owner
from .models import Application, Event, STATUSES, now
from .schemas import Create, Patch, ApplicationOut, EventOut, Status

from .job_import import router as job_import_router

@asynccontextmanager
async def lifespan(app):
    yield
    engine.dispose()

app = FastAPI(title="ApplyTrack", lifespan=lifespan,
              docs_url=None if settings().app_env == "production" else "/docs",
              redoc_url=None if settings().app_env == "production" else "/redoc",
              openapi_url=None if settings().app_env == "production" else "/openapi.json")
app.include_router(job_import_router)
from .reminders import router as reminders_router
app.include_router(reminders_router)
from .gmail import router as gmail_router, GmailCallbackPrivacy
app.include_router(gmail_router)
app.add_middleware(GmailCallbackPrivacy)
origins = [x.strip() for x in settings().cors_origins.split(",") if x.strip()]
if "*" in origins:
    raise RuntimeError("Explicit CORS origins required")
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type"])

@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"error": {"message": str(exc.detail)}}, headers=exc.headers)

@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"error": {"message": "Invalid request", "fields": [".".join(map(str, e["loc"])) + ": " + e["msg"] for e in exc.errors()]}})

@app.exception_handler(IntegrityError)
async def database_error(request: Request, exc: IntegrityError):
    return JSONResponse(status_code=409, content={"error": {"message": "Database constraint violation"}})

@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"error": {"message": "An unexpected server error occurred"}})

def owned(db, owner, id, lock=False):
    query = select(Application).where(Application.id == id, Application.owner_id == owner)
    if lock:
        query = query.with_for_update()
    item = db.scalar(query)
    if item is None:
        raise HTTPException(404, "Application not found")
    return item

def values(data):
    result = data.model_dump(exclude_unset=True)
    if result.get("job_url") is not None:
        result["job_url"] = str(result["job_url"])
    return result

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/api/applications")
def listing(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), status: Status | None = None, search: str = Query("", max_length=200), owner: UUID = Depends(current_owner), db: Session = Depends(get_db)):
    query = select(Application).where(Application.owner_id == owner)
    if status:
        query = query.where(Application.status == status)
    if search.strip():
        term = "%" + search.strip().replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
        query = query.where(or_(Application.company_name.ilike(term, escape="!"), Application.job_title.ilike(term, escape="!")))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    items = db.scalars(query.order_by(Application.updated_at.desc(), Application.id).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [ApplicationOut.model_validate(x) for x in items], "total": total, "page": page, "page_size": page_size}

@app.post("/api/applications", response_model=ApplicationOut, status_code=201)
def create(data: Create, owner: UUID = Depends(current_owner), db: Session = Depends(get_db)):
    item = Application(owner_id=owner, status_changed_at=now(), status_manual_at=now(), **values(data))
    db.add(item)
    db.flush()
    db.add(Event(application_id=item.id, event_type="created", new_status=item.status))
    db.commit()
    db.refresh(item)
    return item

@app.get("/api/applications/{id}", response_model=ApplicationOut)
def detail(id: UUID, owner: UUID = Depends(current_owner), db: Session = Depends(get_db)):
    return owned(db, owner, id)

@app.patch("/api/applications/{id}", response_model=ApplicationOut)
def update(id: UUID, data: Patch, owner: UUID = Depends(current_owner), db: Session = Depends(get_db)):
    item = owned(db, owner, id, lock=True)
    updates = values(data)
    old = item.status
    if "status" in updates:
        item.status_revision += 1
        item.status_changed_at = now()
        item.status_manual_at = now()
    for key, value in updates.items():
        setattr(item, key, value)
    if old != item.status:
        db.add(Event(application_id=id, event_type="status_changed", old_status=old, new_status=item.status))
    elif updates:
        db.add(Event(application_id=id, event_type="updated"))
    db.commit()
    db.refresh(item)
    return item

@app.delete("/api/applications/{id}", status_code=204)
def delete(id: UUID, owner: UUID = Depends(current_owner), db: Session = Depends(get_db)):
    db.delete(owned(db, owner, id, lock=True))
    db.commit()

@app.get("/api/applications/{id}/events", response_model=list[EventOut])
def events(id: UUID, owner: UUID = Depends(current_owner), db: Session = Depends(get_db)):
    owned(db, owner, id)
    return db.scalars(select(Event).where(Event.application_id == id).order_by(Event.created_at.desc(), Event.id)).all()

@app.get("/api/dashboard/summary")
def summary(owner: UUID = Depends(current_owner), db: Session = Depends(get_db)):
    counts = dict(db.execute(select(Application.status, func.count()).where(Application.owner_id == owner).group_by(Application.status)).all())
    return {"total": sum(counts.values()), "by_status": {s: counts.get(s, 0) for s in STATUSES}}


# Install the frontend last: an API miss must never return the SPA document.
from .hosting import install_hosting
install_hosting(app, settings())
