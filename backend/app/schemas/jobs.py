from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AnalysisJobCreate(BaseModel):
    analysis_type: Literal[
        "integrity_check", "metadata_extract", "perceptual_hash"
    ] = "integrity_check"


class AnalysisJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    media_asset_id: UUID
    analysis_type: str
    status: str
    result: dict[str, Any] | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class AnalysisJobEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    analysis_job_id: UUID
    event_type: str
    status: str
    message: str
    created_at: datetime
