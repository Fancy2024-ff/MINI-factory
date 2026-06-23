"""core.shared.models — 跨域共享数据模型（pydantic）。

只放 truly shared 的 schema/枚举。
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class AppSource(str, Enum):
    APP_STORE = "app_store"
    GOOGLE_PLAY = "google_play"


class MiniProgramPlatform(str, Enum):
    WECHAT = "wechat"
    ALIPAY = "alipay"
    DOUYIN = "douyin"
    BAIDU = "baidu"
    TELEGRAM = "telegram"
    LINE = "line"


class AppInfo(BaseModel):
    """An app discovered from app stores."""

    name: str
    app_id: str
    source: AppSource
    category: str
    description: str = ""
    downloads: int = 0
    rating: float = 0.0
    review_count: int = 0
    developer: str = ""
    features: list[str] = Field(default_factory=list)
    ai_related: bool = True
    discovered_at: datetime = Field(default_factory=datetime.now)


class GapOpportunity(BaseModel):
    """An app that exists in app stores but NOT in mini-program platforms."""

    app: AppInfo
    missing_platforms: list[MiniProgramPlatform] = Field(default_factory=list)
    gap_score: float = 0.0  # 0-100, higher = bigger opportunity
    competition_level: str = "low"  # low/medium/high
    estimated_difficulty: str = "medium"  # easy/medium/hard
    reason: str = ""


class PRDDocument(BaseModel):
    """Product Requirements Document produced by the PRD generation step (core.generator)."""

    app_name: str
    target_platforms: list[MiniProgramPlatform]
    summary: str = ""
    core_features: list[dict] = Field(default_factory=list)
    user_scenarios: list[str] = Field(default_factory=list)
    tech_requirements: list[str] = Field(default_factory=list)
    monetization: str = ""
    feasibility_score: float = 0.0  # 0-100
    estimated_dev_hours: int = 0
    created_at: datetime = Field(default_factory=datetime.now)


class ProjectStatus(str, Enum):
    DISCOVERED = "discovered"
    ANALYZING = "analyzing"
    PRD_READY = "prd_ready"
    CODING = "coding"
    CODE_READY = "code_ready"
    SUBMITTING = "submitting"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    LIVE = "live"


class MiniAppProject(BaseModel):
    """A mini-program project in the pipeline."""

    id: str
    app_name: str
    status: ProjectStatus = ProjectStatus.DISCOVERED
    opportunity: Optional[GapOpportunity] = None
    prd: Optional[PRDDocument] = None
    project_path: str = ""
    target_platforms: list[MiniProgramPlatform] = Field(default_factory=list)
    submission_results: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
