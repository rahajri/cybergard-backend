"""
Schémas Pydantic pour le module de génération de rapports.

Définit les schémas de validation pour :
- Templates de rapports
- Widgets
- Rapports générés
- Jobs de génération
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from uuid import UUID
from enum import Enum


# ============================================================================
# ENUMS
# ============================================================================

class TemplateType(str, Enum):
    """Types de templates de rapports"""
    SYSTEM = "system"
    EXECUTIVE = "executive"
    TECHNICAL = "technical"
    DETAILED = "detailed"
    CUSTOM = "custom"
    EBIOS = "ebios"  # Template EBIOS RM


class PageSize(str, Enum):
    """Tailles de page disponibles"""
    A4 = "A4"
    LETTER = "Letter"
    LEGAL = "Legal"


class Orientation(str, Enum):
    """Orientations de page"""
    PORTRAIT = "portrait"
    LANDSCAPE = "landscape"


class ReportStatus(str, Enum):
    """Statuts d'un rapport généré"""
    PENDING = "pending"
    GENERATING = "generating"
    DRAFT = "draft"
    FINAL = "final"
    ERROR = "error"
    ARCHIVED = "archived"


class GenerationMode(str, Enum):
    """Modes de génération"""
    DRAFT = "draft"  # Graphes PNG, campagne en cours
    FINAL = "final"  # Graphes SVG, campagne terminée


class TemplateCategory(str, Enum):
    """
    Catégorie du template - permet de distinguer les différents types de rapports.

    - AUDIT: Templates pour les campagnes d'audit (ISO 27001, NIS2, etc.)
    - EBIOS: Templates pour les analyses de risques EBIOS RM
    - SCAN: Templates pour les rapports du scanner externe
    """
    AUDIT = "audit"
    EBIOS = "ebios"
    SCAN = "scan"


class ReportScope(str, Enum):
    """
    Scope du rapport - détermine le type de contenu généré.

    - CONSOLIDATED: Vue écosystème (multi-organismes)
        * Stats comparatives entre organismes
        * NC critiques globales
        * Plan d'action consolidé
        * Benchmarking secteur

    - ENTITY: Vue individuelle (mono-organisme)
        * Score personnalisé de l'entité
        * Analyse par domaine
        * Plan d'action dédié
        * Comparaison vs pairs

    - SCAN_INDIVIDUAL: Rapport de scan individuel
        * Détails d'un scan spécifique
        * Vulnérabilités détectées
        * Score d'exposition
        * Analyse TLS/SSL

    - SCAN_ECOSYSTEM: Vue écosystème scanner (multi-cibles)
        * Synthèse de tous les scans
        * Comparaison des organismes
        * Top vulnérabilités
        * Tendances de sécurité
    """
    CONSOLIDATED = "consolidated"  # Multi-organismes (vue écosystème)
    ENTITY = "entity"  # Mono-organisme (vue individuelle)
    SCAN_INDIVIDUAL = "scan_individual"  # Scan individuel (une cible)
    SCAN_ECOSYSTEM = "scan_ecosystem"  # Vue écosystème scanner (multi-cibles)


class JobStatus(str, Enum):
    """Statuts d'un job de génération"""
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WidgetType(str, Enum):
    """Types de widgets disponibles"""
    # Structure
    COVER = "cover"
    HEADER = "header"
    FOOTER = "footer"
    TOC = "toc"
    PAGE_BREAK = "page_break"

    # Texte
    TITLE = "title"
    PARAGRAPH = "paragraph"
    DESCRIPTION = "description"

    # Métriques
    METRICS = "metrics"
    SCORE_CARD = "score_card"

    # Graphiques
    RADAR_DOMAINS = "radar_domains"
    RADAR_CRITERIA = "radar_criteria"
    COMPARISON_CHART = "comparison_chart"
    POSITIONING_CHART = "positioning_chart"
    GAUGE = "gauge"
    BAR_CHART = "bar_chart"
    PIE_CHART = "pie_chart"

    # Tables
    PROPERTIES_TABLE = "properties_table"
    ACTIONS_TABLE = "actions_table"
    QUESTIONS_TABLE = "questions_table"
    NC_TABLE = "nc_table"
    DOCUMENTS_TABLE = "documents_table"

    # Données
    FINDINGS = "findings"
    COMMENTS = "comments"
    EVIDENCE_LIST = "evidence_list"

    # Boucles
    LOOP_DOMAINS = "loop_domains"
    LOOP_QUESTIONS = "loop_questions"
    LOOP_ENTITIES = "loop_entities"
    LOOP_FRAMEWORKS = "loop_frameworks"
    LOOP_NC = "loop_nc"

    # Scanner - Widgets spécifiques
    SCAN_SUMMARY = "scan_summary"  # Résumé du scan
    SCAN_EXPOSURE_SCORE = "scan_exposure_score"  # Score d'exposition
    SCAN_TLS_ANALYSIS = "scan_tls_analysis"  # Analyse TLS/SSL
    SCAN_VULNERABILITIES_TABLE = "scan_vulnerabilities_table"  # Table des vulnérabilités
    SCAN_SERVICES_TABLE = "scan_services_table"  # Services exposés
    SCAN_RISK_GAUGE = "scan_risk_gauge"  # Jauge de risque
    SCAN_CVSS_DISTRIBUTION = "scan_cvss_distribution"  # Distribution CVSS
    SCAN_HISTORY_CHART = "scan_history_chart"  # Historique des scans
    SCAN_RECOMMENDATIONS = "scan_recommendations"  # Recommandations
    SCAN_ECOSYSTEM_SCATTER = "scan_ecosystem_scatter"  # Nuage de points écosystème
    SCAN_TOP_VULNERABILITIES = "scan_top_vulnerabilities"  # Top vulnérabilités
    SCAN_COMPARISON_TABLE = "scan_comparison_table"  # Comparaison entités


# ============================================================================
# SCHÉMAS POUR TEMPLATES
# ============================================================================

class TemplateScope(str, Enum):
    """
    Scope des templates - définit pour quel type de rapport le template est utilisable.

    CAMPAGNES D'AUDIT & EBIOS RM:
    - CONSOLIDATED: Template pour rapports consolidés (vue d'ensemble, multi-entités)
    - ENTITY: Template pour rapports individuels (mono-entité ou par scénario)
    - BOTH: Template compatible avec les deux types

    Note: La distinction entre Audit et EBIOS se fait via template_category, pas via report_scope.

    SCANNER EXTERNE:
    - SCAN_INDIVIDUAL: Template pour rapport d'un scan individuel
    - SCAN_ECOSYSTEM: Template pour rapport écosystème scanner
    - SCAN_BOTH: Template compatible avec les deux types scanner
    """
    # Campagnes d'audit & EBIOS RM (différenciés par template_category)
    CONSOLIDATED = "consolidated"
    ENTITY = "entity"
    BOTH = "both"
    # Scanner externe
    SCAN_INDIVIDUAL = "scan_individual"
    SCAN_ECOSYSTEM = "scan_ecosystem"
    SCAN_BOTH = "scan_both"


class ReportTemplateBase(BaseModel):
    """Schéma de base pour un template"""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    template_type: TemplateType = TemplateType.CUSTOM
    template_category: TemplateCategory = TemplateCategory.AUDIT  # Catégorie: audit, ebios, scan
    report_scope: TemplateScope = TemplateScope.CONSOLIDATED
    page_size: PageSize = PageSize.A4
    orientation: Orientation = Orientation.PORTRAIT
    margins: Optional[Dict[str, int]] = Field(default={
        "top": 20,
        "right": 15,
        "bottom": 20,
        "left": 15
    })
    color_scheme: Optional[Dict[str, str]] = None
    fonts: Optional[Dict[str, Dict[str, Any]]] = None
    custom_css: Optional[str] = None
    default_logo: Optional[str] = "TENANT"
    custom_logo: Optional[str] = None  # Logo personnalisé en base64 data URI


class ReportTemplateCreate(ReportTemplateBase):
    """Schéma pour créer un template"""
    structure: List[Dict[str, Any]] = Field(default=[])


class ReportTemplateUpdate(BaseModel):
    """Schéma pour mettre à jour un template"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    template_type: Optional[TemplateType] = None
    template_category: Optional[TemplateCategory] = None  # Catégorie: audit, ebios, scan
    report_scope: Optional[TemplateScope] = None
    page_size: Optional[PageSize] = None
    orientation: Optional[Orientation] = None
    margins: Optional[Dict[str, int]] = None
    color_scheme: Optional[Dict[str, str]] = None
    fonts: Optional[Dict[str, Dict[str, Any]]] = None
    custom_css: Optional[str] = None
    default_logo: Optional[str] = None
    structure: Optional[List[Dict[str, Any]]] = None
    is_default: Optional[bool] = None


class ReportTemplateResponse(ReportTemplateBase):
    """Schéma de réponse pour un template"""
    id: UUID
    tenant_id: Optional[UUID]
    parent_template_id: Optional[UUID] = None  # Lien vers le template maître
    code: Optional[str]
    is_system: bool
    is_default: bool
    structure: List[Dict[str, Any]]
    created_by: Optional[UUID]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ReportTemplateListResponse(BaseModel):
    """Liste paginée de templates"""
    items: List[ReportTemplateResponse]
    total: int
    page: int = 1
    limit: int = 20


# ============================================================================
# SCHÉMAS POUR WIDGETS
# ============================================================================

class WidgetConfigBase(BaseModel):
    """Configuration de base d'un widget"""
    pass


class WidgetCreate(BaseModel):
    """Schéma pour créer un widget"""
    template_id: UUID
    widget_type: WidgetType
    widget_key: Optional[str] = None
    position: int = 0
    parent_widget_id: Optional[UUID] = None
    config: Dict[str, Any] = Field(default={})
    display_condition: Optional[Dict[str, Any]] = None


class WidgetUpdate(BaseModel):
    """Schéma pour mettre à jour un widget"""
    widget_type: Optional[WidgetType] = None
    widget_key: Optional[str] = None
    position: Optional[int] = None
    parent_widget_id: Optional[UUID] = None
    config: Optional[Dict[str, Any]] = None
    display_condition: Optional[Dict[str, Any]] = None


class WidgetResponse(BaseModel):
    """Schéma de réponse pour un widget"""
    id: UUID
    template_id: UUID
    widget_type: str
    widget_key: Optional[str]
    position: int
    parent_widget_id: Optional[UUID]
    config: Dict[str, Any]
    display_condition: Optional[Dict[str, Any]]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# SCHÉMAS POUR RAPPORTS GÉNÉRÉS
# ============================================================================

class GeneratedReportBase(BaseModel):
    """Schéma de base pour un rapport"""
    title: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None


class GenerateReportRequest(BaseModel):
    """
    Requête pour générer un rapport.

    RÈGLES DE VALIDATION :
    - Si report_scope='consolidated' : entity_id DOIT être None
    - Si report_scope='entity' : entity_id DOIT être fourni
    - Si report_scope='scan_individual' : scan_id DOIT être fourni
    - Si report_scope='scan_ecosystem' : entity_id optionnel (filtre par entité)

    Args:
        template_id: UUID du template à utiliser
        report_scope: Type de rapport (consolidated, entity, scan_individual, scan_ecosystem)
        entity_id: UUID de l'entité (obligatoire si scope='entity', optionnel pour scan_ecosystem)
        scan_id: UUID du scan (obligatoire si scope='scan_individual')
        title: Titre du rapport
        description: Description optionnelle
        options: Options de génération
    """
    template_id: UUID
    report_scope: ReportScope = ReportScope.CONSOLIDATED
    entity_id: Optional[UUID] = None  # REQUIS si scope='entity', NULL si scope='consolidated'
    scan_id: Optional[UUID] = None  # REQUIS si scope='scan_individual'
    title: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    options: Optional[Dict[str, Any]] = Field(default={
        "force_mode": None,  # null | "draft" | "final"
        "include_appendix": True,
        "include_ai_summary": True,  # Résumé IA
        "include_benchmarking": True,  # Comparaison sectorielle
        "include_positioning_chart": True,  # Graphique de positionnement
        "language": "fr"
    })

    def validate_scope_entity_consistency(self) -> None:
        """
        Valide la cohérence entre report_scope et entity_id/scan_id.

        Raises:
            ValueError: Si les règles de cohérence ne sont pas respectées
        """
        if self.report_scope == ReportScope.CONSOLIDATED and self.entity_id is not None:
            raise ValueError(
                "entity_id doit être None pour un rapport consolidé (scope='consolidated')"
            )
        if self.report_scope == ReportScope.ENTITY and self.entity_id is None:
            raise ValueError(
                "entity_id est requis pour un rapport individuel (scope='entity')"
            )
        if self.report_scope == ReportScope.SCAN_INDIVIDUAL and self.scan_id is None:
            raise ValueError(
                "scan_id est requis pour un rapport de scan individuel (scope='scan_individual')"
            )
        # scan_ecosystem: entity_id est optionnel (pour filtrer par entité)


class GenerateScanReportRequest(BaseModel):
    """
    Requête pour générer un rapport de scan (individuel ou écosystème).

    Schéma simplifié spécifique aux rapports scanner.

    Args:
        template_id: UUID du template à utiliser
        title: Titre du rapport (optionnel, généré automatiquement si absent)
        report_scope: Type de rapport (scan_individual, scan_ecosystem)
        options: Options de génération
    """
    template_id: UUID
    title: Optional[str] = Field(None, max_length=500)
    report_scope: ReportScope = ReportScope.SCAN_INDIVIDUAL
    options: Optional[Dict[str, Any]] = Field(default={
        "include_ai_summary": True,
        "include_positioning_chart": True,
        "language": "fr"
    })


class GenerateReportResponse(BaseModel):
    """Réponse après démarrage de génération"""
    job_id: UUID
    report_id: UUID
    status: JobStatus = JobStatus.QUEUED
    estimated_time_seconds: Optional[int] = 30

    class Config:
        json_schema_extra = {
            "example": {
                "job_id": "550e8400-e29b-41d4-a716-446655440000",
                "report_id": "550e8400-e29b-41d4-a716-446655440001",
                "status": "queued",
                "estimated_time_seconds": 30
            }
        }


class GeneratedReportResponse(GeneratedReportBase):
    """Schéma de réponse pour un rapport généré"""
    id: UUID
    tenant_id: UUID
    campaign_id: Optional[UUID]
    audit_id: Optional[UUID]
    scan_id: Optional[UUID] = None  # Pour rapports scanner
    template_id: Optional[UUID]
    report_scope: ReportScope
    entity_id: Optional[UUID]
    entity_name: Optional[str] = None  # Nom de l'entité (pour affichage)
    scan_target: Optional[str] = None  # Cible du scan (pour affichage)
    status: ReportStatus
    generation_mode: GenerationMode
    file_path: Optional[str]
    file_name: Optional[str]
    file_size_bytes: Optional[int]
    file_mime_type: str
    page_count: Optional[int]
    generation_time_ms: Optional[int]
    error_message: Optional[str]
    version: int
    is_latest: bool
    previous_version_id: Optional[UUID]
    generated_by: Optional[UUID]
    generated_at: Optional[datetime]
    downloaded_count: int
    last_downloaded_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class GeneratedReportListResponse(BaseModel):
    """Liste de rapports générés"""
    items: List[GeneratedReportResponse]
    total: int


# ============================================================================
# SCHÉMAS POUR JOBS DE GÉNÉRATION
# ============================================================================

class ReportGenerationJobResponse(BaseModel):
    """Schéma de réponse pour un job de génération"""
    id: UUID
    job_id: UUID  # Alias de id pour compatibilité
    report_id: UUID
    status: JobStatus
    progress_percent: int
    current_step: Optional[str]
    total_steps: Optional[int]
    current_step_number: Optional[int]
    queued_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    worker_id: Optional[str]
    retry_count: int
    error_message: Optional[str]

    class Config:
        from_attributes = True

    def __init__(self, **data):
        # Créer un alias job_id = id
        if 'id' in data and 'job_id' not in data:
            data['job_id'] = data['id']
        super().__init__(**data)


# ============================================================================
# SCHÉMAS POUR DONNÉES DE GRAPHIQUES
# ============================================================================

class ChartDataRequest(BaseModel):
    """Requête pour obtenir les données d'un graphique"""
    chart_type: str
    entity_id: Optional[UUID] = None
    domain_id: Optional[UUID] = None
    framework_id: Optional[UUID] = None


class ChartDataResponse(BaseModel):
    """Réponse avec les données d'un graphique"""
    chart_type: str
    data: Dict[str, Any]
    generated_at: datetime

    class Config:
        json_schema_extra = {
            "example": {
                "chart_type": "radar_domains",
                "data": {
                    "labels": ["Politique sécurité", "Gestion des actifs", "Contrôle d'accès"],
                    "evaluated": [75, 60, 80],
                    "sector": [70, 65, 75],
                    "campaign": [72, 62, 78]
                },
                "generated_at": "2025-11-24T14:00:00Z"
            }
        }


# ============================================================================
# SCHÉMAS POUR LISTE DES TYPES DE WIDGETS
# ============================================================================

class WidgetTypeInfo(BaseModel):
    """Informations sur un type de widget"""
    type: str
    label: str
    icon: str
    category: str
    description: Optional[str] = None


class WidgetCategoryInfo(BaseModel):
    """Catégorie de widgets"""
    name: str
    widgets: List[WidgetTypeInfo]


class WidgetTypesResponse(BaseModel):
    """Liste des types de widgets disponibles"""
    categories: List[WidgetCategoryInfo]


class WidgetDefaultConfigResponse(BaseModel):
    """Configuration par défaut d'un widget"""
    widget_type: str
    default_config: Dict[str, Any]
    schema: Optional[Dict[str, Any]] = None  # JSON Schema pour validation
