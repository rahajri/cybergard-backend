# backend/src/schemas/control_point.py
# Schémas Pydantic - Validation assouplie pour compatibilité IA

from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Dict, Any
from enum import Enum

class CriticalityLevel(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"

class ValidationStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

class RequirementInfo(BaseModel):
    """Information sur une exigence mappée - Validation assouplie"""
    id: str
    official_code: Optional[str] = None  # ✅ Rendu optionnel
    title: Optional[str] = None          # ✅ Rendu optionnel
    requirement_text: Optional[str] = None  # ✅ Rendu optionnel
    domain: Optional[str] = None
    subdomain: Optional[str] = None
    confidence_score: float = 0.8

class GeneratedControlPoint(BaseModel):
    """Point de contrôle généré par l'IA"""
    id: str
    code: str
    name: str
    description: str = ""  # ✅ Valeur par défaut
    category: str = "Autre"  # ✅ Valeur par défaut
    subcategory: Optional[str] = None
    risk_domains: List[str] = []
    estimated_effort_hours: int = 8
    criticality: Optional[str] = "MEDIUM"  # ✅ String au lieu d'Enum + optionnel
    ai_confidence: float = 0.7
    ai_explanation: str = ""  # ✅ Valeur par défaut
    mapped_requirements: List[RequirementInfo] = []
    suggested_questions: List[Dict[str, Any]] = []
    validation_status: ValidationStatus = ValidationStatus.PENDING
    existing_control_point_id: Optional[str] = None  # ✅ NOUVEAU : pour réutilisation
    
    class Config:
        # Permettre des valeurs vides pour criticality
        use_enum_values = True
        # Ignorer les champs supplémentaires de l'IA
        extra = "ignore"
    
    @field_validator('criticality', mode='before')
    @classmethod
    def validate_criticality(cls, v):
        """Normalise la criticité et gère les valeurs vides"""
        if not v or v == '':
            return 'MEDIUM'
        # Normaliser en uppercase
        v_upper = str(v).upper()
        # Valider que c'est une valeur autorisée
        if v_upper in ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']:
            return v_upper
        return 'MEDIUM'  # Défaut si invalide

class ControlPointGenerationRequest(BaseModel):
    """Requête de génération de points de contrôle"""
    framework_id: str
    max_control_points: int = 50
    min_confidence: float = 0.7
    language: str = "fr"
    merge_similar: bool = True

class ControlPointGenerationResult(BaseModel):
    """Résultat de la génération IA"""
    total_generated: int
    control_points: List[GeneratedControlPoint]
    processing_time: float
    framework_coverage: float
    avg_confidence: Optional[float] = None
    success: bool = True
    error_message: Optional[str] = None
    generation_method: Optional[str] = None  # "deepseek" ou "algorithmic"

class ControlPointFinalization(BaseModel):
    """Finalisation des points validés"""
    framework_id: str
    control_points: List[GeneratedControlPoint]
    admin_validation_comment: Optional[str] = None