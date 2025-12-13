from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID

class FrameworkBase(BaseModel):
    code: str = Field(..., min_length=2, max_length=50)
    name: str = Field(..., min_length=5, max_length=255)
    version: Optional[str] = Field(None, max_length=50)
    publisher: Optional[str] = Field(None, max_length=255)
    language: str = Field(default='fr', regex='^(fr|en|de|es|ar)$')
    description: Optional[str] = None

class FrameworkCreate(FrameworkBase):
    pass

class FrameworkResponse(FrameworkBase):
    id: UUID
    is_active: bool
    created_at: datetime
    import_date: datetime
    
    class Config:
        from_attributes = True

class CSVUploadRequest(BaseModel):
    framework_info: FrameworkCreate
    column_mapping: Dict[str, str]
    
class CSVValidationResult(BaseModel):
    line: int
    column: str
    message: str
    severity: str  # 'error' | 'warning'

class CSVImportResponse(BaseModel):
    success: bool
    framework_id: Optional[UUID] = None
    imported_count: int = 0
    validation_results: List[CSVValidationResult] = []
    processing_time_ms: int
    
class RequirementCreate(BaseModel):
    official_code: str
    title: str
    requirement_text: str
    section_code: str
    domain: Optional[str] = None
    subdomain: Optional[str] = None
    tags: List[str] = []
    risk_level: str = 'medium'
    compliance_obligation: str = 'mandatory'
    
    @validator('tags', pre=True)
    def parse_tags(cls, v):
        if isinstance(v, str):
            return [tag.strip() for tag in v.split(',') if tag.strip()]
        return v

class SectionCreate(BaseModel):
    section_code: str
    title: str
    description: Optional[str] = None
    section_type: str  # chapter, article, paragraph
    parent_code: Optional[str] = None