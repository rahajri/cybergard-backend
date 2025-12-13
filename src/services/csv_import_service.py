import pandas as pd
import hashlib
import time
from typing import List, Dict, Any, Optional, Tuple
from uuid import uuid4
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
import logging
from src.database import Base, SessionLocal, get_db

from ..models.framework import Framework, Requirement
from ..schemas.framework import (
    FrameworkCreate, 
    CSVValidationResult, 
    CSVImportResponse,
    RequirementCreate,
    SectionCreate
)

logger = logging.getLogger(__name__)

class CSVImportService:
    def __init__(self, db: Session):
        self.db = db
        
    async def process_csv_import(
        self, 
        csv_content: bytes,
        framework_info: FrameworkCreate,
        column_mapping: Dict[str, str]
    ) -> CSVImportResponse:
        """Process complete CSV import with validation"""
        start_time = time.time()
        
        try:
            # 1. Parse CSV
            df = self._parse_csv(csv_content)
            
            # 2. Validate data
            validation_results = self._validate_csv_data(df, column_mapping)
            
            # 3. Stop if errors
            errors = [r for r in validation_results if r.severity == 'error']
            if errors:
                return CSVImportResponse(
                    success=False,
                    validation_results=validation_results,
                    processing_time_ms=int((time.time() - start_time) * 1000)
                )
            
            # 4. Create framework
            framework = self._create_framework(framework_info)
            
            # 5. Import data
            imported_count = await self._import_requirements_and_sections(
                df, framework.id, column_mapping
            )
            
            # 6. Commit transaction
            self.db.commit()
            
            return CSVImportResponse(
                success=True,
                framework_id=framework.id,
                imported_count=imported_count,
                validation_results=validation_results,
                processing_time_ms=int((time.time() - start_time) * 1000)
            )
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"CSV import failed: {e}")
            return CSVImportResponse(
                success=False,
                validation_results=[CSVValidationResult(
                    line=0,
                    column="system",
                    message=f"Import failed: {str(e)}",
                    severity="error"
                )],
                processing_time_ms=int((time.time() - start_time) * 1000)
            )
    
    def _parse_csv(self, csv_content: bytes) -> pd.DataFrame:
        """Parse CSV content into DataFrame"""
        try:
            # Try different encodings
            for encoding in ['utf-8', 'latin-1', 'cp1252']:
                try:
                    content_str = csv_content.decode(encoding)
                    df = pd.read_csv(
                        pd.StringIO(content_str),
                        delimiter=',',
                        quotechar='"',
                        skipinitialspace=True
                    )
                    # Clean column names
                    df.columns = df.columns.str.strip().str.replace('"', '')
                    return df
                except UnicodeDecodeError:
                    continue
            
            raise ValueError("Unable to decode CSV file with supported encodings")
        except Exception as e:
            raise ValueError(f"Invalid CSV format: {e}")
    
    def _validate_csv_data(
        self, 
        df: pd.DataFrame, 
        column_mapping: Dict[str, str]
    ) -> List[CSVValidationResult]:
        """Validate CSV data against business rules"""
        results = []
        
        # Required columns check
        required_fields = [
            'section_code', 'section_title', 'section_type',
            'requirement_code', 'requirement_title', 'requirement_text'
        ]
        
        for field in required_fields:
            if field not in column_mapping or column_mapping[field] not in df.columns:
                results.append(CSVValidationResult(
                    line=0,
                    column=field,
                    message=f"Champ obligatoire manquant: {field}",
                    severity="error"
                ))
        
        # Data validation per row
        for idx, row in df.iterrows():
            line_num = idx + 2  # +2 because header + 0-indexed
            
            # Check required values
            for field in required_fields:
                mapped_col = column_mapping.get(field)
                if mapped_col and (pd.isna(row[mapped_col]) or str(row[mapped_col]).strip() == ''):
                    results.append(CSVValidationResult(
                        line=line_num,
                        column=field,
                        message=f"Valeur manquante pour {field}",
                        severity="error"
                    ))
            
            # Validate risk_level values
            risk_col = column_mapping.get('risk_level')
            if risk_col and not pd.isna(row[risk_col]):
                risk_value = str(row[risk_col]).lower().strip()
                if risk_value not in ['low', 'medium', 'high', 'critical']:
                    results.append(CSVValidationResult(
                        line=line_num,
                        column='risk_level',
                        message=f"Niveau de risque invalide: {risk_value}. Valeurs acceptées: low, medium, high, critical",
                        severity="warning"
                    ))
            
            # Check for duplicate requirement codes
            req_code_col = column_mapping.get('requirement_code')
            if req_code_col and not pd.isna(row[req_code_col]):
                req_code = str(row[req_code_col]).strip()
                duplicates = df[df[req_code_col] == req_code]
                if len(duplicates) > 1:
                    results.append(CSVValidationResult(
                        line=line_num,
                        column='requirement_code',
                        message=f"Code d'exigence en doublon: {req_code}",
                        severity="error"
                    ))
        
        return results
    
    def _create_framework(self, framework_info: FrameworkCreate) -> Framework:
        """Create framework in database"""
        # Check if framework already exists
        existing = self.db.query(Framework).filter(Framework.code == framework_info.code).first()
        if existing:
            raise ValueError(f"Framework with code '{framework_info.code}' already exists")
        
        framework = Framework(
            code=framework_info.code,
            name=framework_info.name,
            version=framework_info.version,
            publisher=framework_info.publisher,
            language=framework_info.language,
            description=framework_info.description
        )
        
        self.db.add(framework)
        self.db.flush()  # Get ID without committing
        return framework
    
    async def _import_requirements_and_sections(
        self,
        df: pd.DataFrame,
        framework_id: str,
        column_mapping: Dict[str, str]
    ) -> int:
        """Import sections and requirements from DataFrame"""
        sections_created = {}
        requirements_count = 0
        
        for idx, row in df.iterrows():
            try:
                # Create or get section
                section_code = str(row[column_mapping['section_code']]).strip()
                
                if section_code not in sections_created:
                    section = self._create_section(row, framework_id, column_mapping)
                    sections_created[section_code] = section
                else:
                    section = sections_created[section_code]
                
                # Create requirement
                requirement = self._create_requirement(row, framework_id, section.id, column_mapping)
                requirements_count += 1
                
            except Exception as e:
                logger.error(f"Error processing row {idx + 2}: {e}")
                # Continue processing other rows
                continue
        
        logger.info(f"Imported {len(sections_created)} sections and {requirements_count} requirements")
        return requirements_count
    
    def _create_section(self, row: pd.Series, framework_id: str, column_mapping: Dict[str, str]) -> Section:
        """Create section from CSV row"""
        section_code = str(row[column_mapping['section_code']]).strip()
        
        # Check if section already exists
        existing = self.db.query(Section).filter(
            Section.framework_id == framework_id,
            Section.section_code == section_code
        ).first()
        
        if existing:
            return existing
        
        section = Section(
            framework_id=framework_id,
            section_code=section_code,
            title=str(row[column_mapping['section_title']]).strip(),
            section_type=str(row[column_mapping['section_type']]).strip().lower(),
            description=str(row[column_mapping.get('section_description', '')]).strip() if column_mapping.get('section_description') else None,
            hierarchy_level=self._get_hierarchy_level(str(row[column_mapping['section_type']]).strip())
        )
        
        self.db.add(section)
        self.db.flush()
        return section
    
    def _create_requirement(
        self, 
        row: pd.Series, 
        framework_id: str, 
        section_id: str, 
        column_mapping: Dict[str, str]
    ) -> Requirement:
        """Create requirement from CSV row"""
        # Parse tags
        tags = []
        if 'tags' in column_mapping and not pd.isna(row[column_mapping['tags']]):
            tags_str = str(row[column_mapping['tags']]).strip()
            tags = [tag.strip() for tag in tags_str.split(',') if tag.strip()]
        
        requirement = Requirement(
            framework_id=framework_id,
            section_id=section_id,
            official_code=str(row[column_mapping['requirement_code']]).strip(),
            title=str(row[column_mapping['requirement_title']]).strip(),
            requirement_text=str(row[column_mapping['requirement_text']]).strip(),
            domain=str(row[column_mapping.get('domain', '')]).strip() or None,
            subdomain=str(row[column_mapping.get('subdomain', '')]).strip() or None,
            tags=tags,
            risk_level=str(row[column_mapping.get('risk_level', 'medium')]).lower().strip(),
            compliance_obligation=str(row[column_mapping.get('compliance_obligation', 'mandatory')]).lower().strip()
        )
        
        self.db.add(requirement)
        self.db.flush()
        return requirement
    
    def _get_hierarchy_level(self, section_type: str) -> int:
        """Get hierarchy level from section type"""
        hierarchy_map = {
            'chapter': 1,
            'article': 2,
            'paragraph': 3,
            'point': 4
        }
        return hierarchy_map.get(section_type.lower(), 1)

## 7. API Endpoints (src/api/v1/frameworks.py)
```python
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import List
import json
import logging

from ...database import get_db
from ...schemas.framework import (
    FrameworkResponse, 
    FrameworkCreate,
    CSVImportResponse,
    CSVUploadRequest
)
from ...services.csv_import_service import CSVImportService
from ...models.framework import Framework

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/upload", response_model=CSVImportResponse)
async def upload_csv_framework(
    file: UploadFile = File(...),
    framework_info: str = Form(...),
    column_mapping: str = Form(...),
    db: Session = Depends(get_db)
):
    """Upload and import CSV framework"""
    
    # Validate file
    if not file.filename.lower().endswith('.csv'):
        raise HTTPException(status_code=400, detail="Only CSV files are allowed")
    
    if file.size > 10 * 1024 * 1024:  # 10MB limit
        raise HTTPException(status_code=400, detail="File too large. Maximum 10MB allowed")
    
    try:
        # Parse form data
        framework_data = json.loads(framework_info)
        mapping_data = json.loads(column_mapping)
        
        framework_create = FrameworkCreate(**framework_data)
        
        # Read file content
        csv_content = await file.read()
        
        # Process import
        import_service = CSVImportService(db)
        result = await import_service.process_csv_import(
            csv_content=csv_content,
            framework_info=framework_create,
            column_mapping=mapping_data
        )
        
        if result.success:
            logger.info(f"Successfully imported framework {framework_create.code} with {result.imported_count} requirements")
        else:
            logger.warning(f"Failed to import framework {framework_create.code}")
        
        return result
        
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON in form data: {e}")
    except Exception as e:
        logger.error(f"CSV upload failed: {e}")
        raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}")

@router.get("/", response_model=List[FrameworkResponse])
async def list_frameworks(
    skip: int = 0,
    limit: int = 100,
    active_only: bool = True,
    db: Session = Depends(get_db)
):
    """List all frameworks"""
    query = db.query(Framework)
    
    if active_only:
        query = query.filter(Framework.is_active == True)
    
    frameworks = query.offset(skip).limit(limit).all()
    return frameworks

@router.get("/{framework_id}", response_model=FrameworkResponse)
async def get_framework(
    framework_id: str,
    db: Session = Depends(get_db)
):
    """Get framework by ID"""
    framework = db.query(Framework).filter(Framework.id == framework_id).first()
    
    if not framework:
        raise HTTPException(status_code=404, detail="Framework not found")
    
    return framework

@router.delete("/{framework_id}")
async def delete_framework(
    framework_id: str,
    db: Session = Depends(get_db)
):
    """Delete framework (soft delete)"""
    framework = db.query(Framework).filter(Framework.id == framework_id).first()
    
    if not framework:
        raise HTTPException(status_code=404, detail="Framework not found")
    
    framework.is_active = False
    db.commit()
    
    return {"message": "Framework deleted successfully"}

@router.get("/{framework_id}/stats")
async def get_framework_stats(
    framework_id: str,
    db: Session = Depends(get_db)
):
    """Get framework statistics"""
    framework = db.query(Framework).filter(Framework.id == framework_id).first()
    
    if not framework:
        raise HTTPException(status_code=404, detail="Framework not found")
    
    # Count sections and requirements
    sections_count = len(framework.sections)
    requirements_count = len(framework.requirements)
    
    # Count by domain
    domain_stats = {}
    for req in framework.requirements:
        domain = req.domain or 'Unknown'
        domain_stats[domain] = domain_stats.get(domain, 0) + 1
    
    return {
        "framework_id": framework_id,
        "total_sections": sections_count,
        "total_requirements": requirements_count,
        "domain_breakdown": domain_stats,
        "risk_level_breakdown": {
            level: sum(1 for req in framework.requirements if req.risk_level == level)
            for level in ['low', 'medium', 'high', 'critical']
        }
    }