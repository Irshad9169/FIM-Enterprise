from pydantic import BaseModel, UUID4
from datetime import date, datetime
from typing import Optional, List, Dict, Any

class DailyReportSummary(BaseModel):
    added_files: int = 0
    removed_files: int = 0
    changed_files: int = 0

class DailyReportResponse(BaseModel):
    id: UUID4
    report_date: date
    agents: Optional[List[str]] = []
    summary: DailyReportSummary
    status: Optional[str] = "pending"
    total_changes: int = 0
    created_at: datetime
    
    class Config:
        from_attributes = True

class ReportChangeDetail(BaseModel):
    file_path: str
    agent_hostname: Optional[str] = None
    baseline_mtime: Optional[str] = None
    current_mtime: Optional[str] = None
    baseline_hash: Optional[str] = None
    current_hash: Optional[str] = None
    baseline_size: Optional[int] = None
    current_size: Optional[int] = None

class TicketDetail(BaseModel):
    source: str
    external_id: str
    summary: str
    url: str
    agent_hostname: str

class DailyReportDetail(DailyReportResponse):
    changes: Dict[str, List[str]] = {"added": [], "removed": [], "changed": []}
    details: List[ReportChangeDetail] = []
    linked_tickets: List[TicketDetail] = []
    
    class Config:
        from_attributes = True

class GenerateReportRequest(BaseModel):
    report_date: Optional[date] = None

class UpdateNotesRequest(BaseModel):
    analyst_notes: str

class UpdateStatusRequest(BaseModel):
    status: str
