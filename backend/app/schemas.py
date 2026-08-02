"""Pydantic response/request contracts shared by the API layer."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# --- Auth ---
class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    niche: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    email: str
    niche: str | None
    is_verified: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MessageResponse(BaseModel):
    message: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    password: str = Field(min_length=6, max_length=128)


# --- Channels ---
class TrackChannelRequest(BaseModel):
    url: str = Field(description="Channel URL, @handle, or raw UC... id")
    type: Literal["own", "competitor"] = "competitor"


class OnboardingRequest(BaseModel):
    own_channel: str
    # Generous cap here on purpose: the endpoint trims to settings.max_competitors
    # itself so it can accept "too many" gracefully instead of a hard 422. This
    # bound only exists to stop an absurd payload, not to enforce the real limit.
    competitors: list[str] = Field(default_factory=list, max_length=50)
    niche: str | None = None


class ChannelOut(BaseModel):
    id: int
    youtube_channel_id: str
    name: str
    handle: str | None
    url: str
    thumbnail_url: str | None
    subscriber_count: int
    total_views: int
    video_count: int
    last_upload_at: datetime | None
    last_ingested_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class TrackedChannelOut(ChannelOut):
    tracked_id: int
    type: str
    # Derived roll-ups so the competitor list is useful without a second call.
    median_views: int = 0
    videos_last_30d: int = 0
    breakouts_last_30d: int = 0
    upload_cadence_days: float | None = None
    top_topics: list[str] = Field(default_factory=list)


# --- Videos ---
class VideoIntelligenceOut(BaseModel):
    topic: str | None = None
    subtopic: str | None = None
    format: str | None = None
    angle: str | None = None
    performance_ratio: float | None = None
    performance_score: int | None = None
    baseline_views: int | None = None
    is_breakout: bool = False

    model_config = ConfigDict(from_attributes=True)


class VideoOut(BaseModel):
    id: int
    youtube_video_id: str
    channel_id: int
    channel_name: str | None = None
    title: str
    published_at: datetime
    views: int
    likes: int
    comments: int
    duration_seconds: int
    thumbnail_url: str | None
    url: str
    intelligence: VideoIntelligenceOut | None = None

    model_config = ConfigDict(from_attributes=True)


# --- Trends ---
class TrendOut(BaseModel):
    id: int
    topic: str
    subtopic: str | None
    trend_score: int
    volume_growth: float
    video_velocity: float
    avg_performance: float
    creator_count: int
    video_count: int
    breakout_count: int
    top_format: str | None
    components: dict[str, Any]
    detected_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --- Briefs ---
class BriefOut(BaseModel):
    id: int
    brief_date: date
    content: dict[str, Any]
    generated_by: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RefreshResponse(BaseModel):
    channels_ingested: int
    videos_ingested: int
    videos_classified: int
    trends_detected: int
    breakouts_detected: int
    brief_date: date | None = None
    duration_seconds: float
