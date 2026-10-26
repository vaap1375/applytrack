from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, AwareDatetime, field_validator

Status = Literal["Saved", "Applied", "Assessment", "Interview", "Offer", "Rejected", "Withdrawn"]
class Fields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    company_name: str = Field(min_length=1, max_length=200)
    job_title: str = Field(min_length=1, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    job_url: HttpUrl | None = Field(default=None, max_length=2048)
    external_job_id: str | None = Field(default=None, max_length=200)
    status: Status = "Saved"
    applied_at: AwareDatetime | None = None
    notes: str | None = Field(default=None, max_length=30000)

class Create(Fields):
    pass

class Patch(Fields):
    company_name: str | None = Field(default=None, min_length=1, max_length=200)
    job_title: str | None = Field(default=None, min_length=1, max_length=200)
    status: Status | None = None
    @field_validator("company_name", "job_title", "status")
    @classmethod
    def not_null(cls, value):
        if value is None:
            raise ValueError("Field cannot be null")
        return value

class ApplicationOut(Fields):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    status_revision: int
    created_at: datetime
    updated_at: datetime

class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    event_type: str
    source: str
    source_message_id: str | None
    source_timestamp: datetime | None
    old_status: str | None
    new_status: str | None
    notes: str | None
    created_at: datetime
