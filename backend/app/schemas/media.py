from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class InvestigationCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Title cannot be blank")
        return value.strip()


class InvestigationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    description: str | None
    status: str
    created_at: datetime


class InvestigationCreated(InvestigationRead):
    """Investigation response; access token is shown only at creation/rotation."""

    access_token: str


class InvestigationAccessToken(BaseModel):
    investigation_id: UUID
    access_token: str


class MediaAssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    investigation_id: UUID
    original_filename: str
    sha256: str
    mime_type: str
    size_bytes: int
    created_at: datetime


class InvestigationListItem(InvestigationRead):
    """Investigation summary for the trusted workspace dashboard."""

    media_asset_count: int = 0
