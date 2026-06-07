import re
from datetime import datetime
from ipaddress import ip_address
from typing import Any, Generic, Literal, TypeVar
from pydantic import BaseModel, Field, field_validator

T = TypeVar("T")


class StandardResponse(BaseModel, Generic[T]):
    success: bool = True
    data: T | None = None
    message: str | None = None


class PaginatedData(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    size: int


# ---------------------------------------------------------------------------
# Issue models
# ---------------------------------------------------------------------------

class IssueCreate(BaseModel):
    priority: Literal["P0", "P1", "P2", "P3"] = "P1"
    component: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1, max_length=2000)
    department: str = Field(..., min_length=1, max_length=100)
    assignee: str | None = Field(default=None, max_length=50)
    part_system: str | None = Field(default=None, max_length=200)
    sub_system: str | None = Field(default=None, max_length=200)
    root_cause: str | None = None
    short_term_action: str | None = None
    long_term_action: str | None = None
    cutoff_point: str | None = None
    action_plan: str | None = None
    source: str | None = "manual"
    source_file: str | None = None


class IssueUpdate(BaseModel):
    priority: Literal["P0", "P1", "P2", "P3"] | None = None
    component: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, min_length=1, max_length=2000)
    department: str | None = Field(default=None, min_length=1, max_length=100)
    status: Literal["open", "in_progress", "resolved", "closed"] | None = None
    assignee: str | None = Field(default=None, max_length=50)
    part_system: str | None = Field(default=None, max_length=200)
    sub_system: str | None = Field(default=None, max_length=200)
    root_cause: str | None = None
    short_term_action: str | None = None
    long_term_action: str | None = None
    cutoff_point: str | None = None
    action_plan: str | None = None
    source: str | None = None
    source_file: str | None = None


class IssueOut(BaseModel):
    id: str
    priority: str
    component: str
    description: str
    department: str
    status: str
    assignee: str | None = None
    part_system: str | None = None
    sub_system: str | None = None
    root_cause: str | None = None
    short_term_action: str | None = None
    long_term_action: str | None = None
    cutoff_point: str | None = None
    action_plan: str | None = None
    source: str | None = "manual"
    source_file: str | None = None
    created_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# Issue stats
# ---------------------------------------------------------------------------

class DepartmentStat(BaseModel):
    department: str
    closed_rate: int
    total_issues: int


class TrendPoint(BaseModel):
    date: str
    count: int


class IssueStats(BaseModel):
    total_open: int
    new_this_week: int
    closed_this_week: int
    high_risk_count: int
    department_stats: list[DepartmentStat]
    trend: list[TrendPoint]


# ---------------------------------------------------------------------------
# Milestone
# ---------------------------------------------------------------------------

class Milestone(BaseModel):
    id: int | None = None
    name: str = Field(..., min_length=1, max_length=200)
    category: str = Field(..., min_length=1, max_length=100)
    percentage: int = Field(default=0, ge=0, le=100)
    target_date: str | None = None
    actual_date: str | None = None
    actual_percentage: int = Field(default=0, ge=0, le=100)


class MilestoneCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    category: str = Field(..., min_length=1, max_length=100)
    percentage: int = Field(default=0, ge=0, le=100)
    target_date: str | None = None
    actual_date: str | None = None
    actual_percentage: int = Field(default=0, ge=0, le=100)


class MilestoneUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = Field(default=None, min_length=1, max_length=100)
    percentage: int | None = Field(default=None, ge=0, le=100)
    target_date: str | None = None
    actual_date: str | None = None
    actual_percentage: int | None = Field(default=None, ge=0, le=100)


# ---------------------------------------------------------------------------
# Mail / Feishu
# ---------------------------------------------------------------------------

class Mail(BaseModel):
    id: str
    sender: str
    subject: str
    preview: str | None = None
    content: str | None = None
    category: str | None = None
    is_read: bool = False
    is_starred: bool = False
    has_attachment: bool = False
    received_at: str


class MailOut(BaseModel):
    id: str
    sender: str
    subject: str
    preview: str | None = None
    date: str
    is_read: bool
    is_starred: bool
    has_attachment: bool
    category: str | None = None


class Todo(BaseModel):
    id: str
    content: str
    source: str | None = None
    deadline: str | None = None
    completed: bool = False
    created_at: str | None = None


# ---------------------------------------------------------------------------
# PPT
# ---------------------------------------------------------------------------

class TemplateInfo(BaseModel):
    id: str
    name: str
    description: str
    slides: int


class WeeklyPPTRequest(BaseModel):
    week_start: str | None = None
    project_name: str | None = None
    author: str | None = None

    @field_validator("week_start")
    @classmethod
    def validate_week_start(cls, v: str | None) -> str | None:
        if v is None:
            return None
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError('week_start must be in format "YYYY-MM-DD"')
        return v


class DeliverablePPTRequest(BaseModel):
    deliverable_name: str = Field(..., min_length=1, max_length=200)
    responsible: str | None = Field(default=None, max_length=100)


class PPTResult(BaseModel):
    file_path: str
    file_name: str
    week_date: str | None = None


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------

class ExcelRenameRequest(BaseModel):
    folder: str = Field(..., min_length=1)
    pattern: str = Field(..., min_length=1)
    replacement: str

    @field_validator("folder")
    @classmethod
    def validate_folder(cls, v: str) -> str:
        if ".." in v:
            raise ValueError("folder path cannot contain '..'")
        return v


class ExcelRenameResult(BaseModel):
    renamed_files: list[dict[str, str]]
    skipped_files: list[str]
    count: int


class ExcelMergeResult(BaseModel):
    file_path: str
    file_name: str
    sheet_count: int


class ExcelMergeSameResult(BaseModel):
    file_path: str
    file_name: str
    row_count: int


# ---------------------------------------------------------------------------
# Crawler
# ---------------------------------------------------------------------------

class CrawlerFetchRequest(BaseModel):
    url: str = Field(..., min_length=1)

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not re.match(r"^https?://", v):
            raise ValueError("URL must start with http:// or https://")
        hostname = v.split("/")[2].split(":")[0].split("@")[-1]
        try:
            addr = ip_address(hostname)
            if addr.is_private or addr.is_loopback or addr.is_link_local:
                raise ValueError("Private/internal IP addresses are not allowed")
        except ValueError:
            pass
        return v


class CrawlerFetchResult(BaseModel):
    url: str
    title: str
    content: str
    browser_used: str


class CrawlerTableRequest(BaseModel):
    url: str = Field(..., min_length=1)
    xpath: str = "//table"

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not re.match(r"^https?://", v):
            raise ValueError("URL must start with http:// or https://")
        hostname = v.split("/")[2].split(":")[0].split("@")[-1]
        try:
            addr = ip_address(hostname)
            if addr.is_private or addr.is_loopback or addr.is_link_local:
                raise ValueError("Private/internal IP addresses are not allowed")
        except ValueError:
            pass
        return v


class CrawlerTableResult(BaseModel):
    headers: list[str]
    rows: list[list[str]]
    row_count: int


# ---------------------------------------------------------------------------
# Feishu sync
# ---------------------------------------------------------------------------

class TodoToggleRequest(BaseModel):
    id: str = Field(..., min_length=1, max_length=50)


class FeishuSyncResult(BaseModel):
    synced_count: int
    new_count: int
    demo: bool = False


class TodoToggleResult(BaseModel):
    id: str
    completed: bool


# ---------------------------------------------------------------------------
# Deliverable Categories
# ---------------------------------------------------------------------------

class DeliverableCategoryOut(BaseModel):
    id: str
    name: str
    icon: str | None = None
    sort_order: int = 0
    is_visible: bool = True


class DeliverableCategoryCreate(BaseModel):
    id: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=100)
    icon: str | None = None
    sort_order: int = 0


class DeliverableCategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    icon: str | None = None
    sort_order: int | None = None
    is_visible: bool | None = None


# ---------------------------------------------------------------------------
# Dashboard Layouts
# ---------------------------------------------------------------------------

class LayoutCardIn(BaseModel):
    page_key: str
    card_id: str
    card_type: str
    x: int = 0
    y: int = 0
    w: int = 1
    h: int = 1
    config: str | None = None


class LayoutCardOut(LayoutCardIn):
    id: int


# ---------------------------------------------------------------------------
# Dashboard Overview
# ---------------------------------------------------------------------------

class DashboardOverviewOut(BaseModel):
    total_issues: int
    open_issues: int
    closed_rate: float
    high_risk_count: int
    new_this_week: int
    closed_this_week: int
    milestone_progress: list
    completion_pie: list
    department_bar: list
    trend: list
    deliverable_counts: dict


# ---------------------------------------------------------------------------
# EWO/NCR
# ---------------------------------------------------------------------------

class EWOCreate(BaseModel):
    type: Literal["EWO", "NCR"] = "EWO"
    title: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    severity: Literal["critical", "major", "minor"] = "major"
    status: Literal["open", "investigating", "resolved", "closed"] = "open"
    department: str | None = None
    assignee: str | None = None
    raised_date: str | None = None
    target_date: str | None = None
    source: str | None = "manual"
    source_file: str | None = None


class EWOUpdate(BaseModel):
    type: Literal["EWO", "NCR"] | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    severity: Literal["critical", "major", "minor"] | None = None
    status: Literal["open", "investigating", "resolved", "closed"] | None = None
    department: str | None = None
    assignee: str | None = None
    raised_date: str | None = None
    target_date: str | None = None
    source: str | None = None
    source_file: str | None = None


class EWOOut(BaseModel):
    id: str
    type: str
    title: str
    description: str | None = None
    severity: str
    status: str
    department: str | None = None
    assignee: str | None = None
    raised_date: str | None = None
    target_date: str | None = None
    source: str | None = "manual"
    source_file: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


# ---------------------------------------------------------------------------
# TIR
# ---------------------------------------------------------------------------

class TIRCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    category: str | None = None
    status: Literal["draft", "submitted", "approved", "rejected"] = "draft"
    department: str | None = None
    assignee: str | None = None
    test_date: str | None = None
    result: str | None = None
    source: str | None = "manual"
    source_file: str | None = None


class TIRUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    category: str | None = None
    status: Literal["draft", "submitted", "approved", "rejected"] | None = None
    department: str | None = None
    assignee: str | None = None
    test_date: str | None = None
    result: str | None = None
    source: str | None = None
    source_file: str | None = None


class TIROut(BaseModel):
    id: str
    title: str
    description: str | None = None
    category: str | None = None
    status: str
    department: str | None = None
    assignee: str | None = None
    test_date: str | None = None
    result: str | None = None
    source: str | None = "manual"
    source_file: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


# ---------------------------------------------------------------------------
# Lookup - 零件总成
# ---------------------------------------------------------------------------

class PartSystemOut(BaseModel):
    part_system: str
    sub_system: str


class PartSystemCreate(BaseModel):
    part_system: str = Field(..., min_length=1, max_length=200)
    sub_system: str = Field(..., min_length=1, max_length=200)


# ---------------------------------------------------------------------------
# Lookup - 工程师
# ---------------------------------------------------------------------------

class EngineerOut(BaseModel):
    name: str
    department: str


class EngineerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    department: str = Field(..., min_length=1, max_length=100)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

class SettingUpdate(BaseModel):
    value: str = Field(..., min_length=1, max_length=500)


# ---------------------------------------------------------------------------
# Excel Import Result
# ---------------------------------------------------------------------------

class ExcelImportResult(BaseModel):
    created: int = 0
    skipped: int = 0
    errors: list[str] = []
