# backend/src/schemas/external_scan.py
"""
Schémas Pydantic pour le module Scan Externe (ASM).

Définit les modèles de requête et réponse pour l'API.
"""

from datetime import datetime
from typing import Optional, Any
from uuid import UUID
from enum import Enum

from pydantic import BaseModel, Field, field_validator


# ==============================================================================
# ENUMS
# ==============================================================================

class ExternalTargetType(str, Enum):
    """Types de cibles externes."""
    DOMAIN = "DOMAIN"
    SUBDOMAIN = "SUBDOMAIN"
    IP = "IP"
    IP_RANGE = "IP_RANGE"
    EMAIL_DOMAIN = "EMAIL_DOMAIN"


class ScanFrequency(str, Enum):
    """Fréquence de scan automatique."""
    MANUAL = "MANUAL"
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"


class ScanStatus(str, Enum):
    """Statut du dernier scan."""
    NEVER = "NEVER"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"


class ScanExecutionStatus(str, Enum):
    """Statut d'exécution d'un scan."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    CANCELLED = "CANCELLED"


class SeverityLevel(str, Enum):
    """Niveau de sévérité."""
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class VulnerabilityType(str, Enum):
    """Type de vulnérabilité."""
    PORT_EXPOSED = "PORT_EXPOSED"
    SERVICE_VULN = "SERVICE_VULN"
    TLS_WEAK = "TLS_WEAK"
    CERT_ISSUE = "CERT_ISSUE"
    HEADER_MISSING = "HEADER_MISSING"
    MISCONFIGURATION = "MISCONFIGURATION"


# ==============================================================================
# BASE SCHEMAS
# ==============================================================================

class ExternalTargetBase(BaseModel):
    """Base pour les cibles externes."""
    type: ExternalTargetType
    value: str = Field(..., min_length=1, max_length=255)
    label: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    scan_frequency: ScanFrequency = ScanFrequency.MANUAL
    is_active: bool = True
    entity_id: Optional[UUID] = Field(None, description="ID de l'entité liée (null = scan interne)")

    @field_validator("value")
    @classmethod
    def validate_value(cls, v: str, info) -> str:
        """Valide la valeur selon le type."""
        v = v.strip().lower()
        # Validation basique - des validations plus poussées peuvent être ajoutées
        if not v:
            raise ValueError("La valeur ne peut pas être vide")
        return v


class ExternalScanBase(BaseModel):
    """Base pour les scans."""
    trigger_type: str = "manual"


# ==============================================================================
# REQUEST SCHEMAS
# ==============================================================================

class ExternalTargetCreate(ExternalTargetBase):
    """Création d'une cible externe."""
    pass


class ExternalTargetUpdate(BaseModel):
    """Mise à jour d'une cible externe."""
    label: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    scan_frequency: Optional[ScanFrequency] = None
    is_active: Optional[bool] = None
    entity_id: Optional[UUID] = Field(None, description="ID de l'entité liée (null pour scan interne)")


class ScanLaunchRequest(BaseModel):
    """Requête pour lancer un scan."""
    ports: Optional[str] = Field(
        None,
        description="Ports à scanner (ex: '22,80,443' ou '1-1000')"
    )
    scan_all_ports: bool = Field(
        False,
        description="Scanner tous les ports (plus long)"
    )
    enable_tls_audit: bool = Field(
        True,
        description="Activer l'audit TLS"
    )
    enable_cve_enrichment: bool = Field(
        True,
        description="Enrichir avec les CVE"
    )


class VulnerabilityMarkRemediated(BaseModel):
    """Marquer une vulnérabilité comme remédiée."""
    is_remediated: bool = True
    notes: Optional[str] = None


# ==============================================================================
# RESPONSE SCHEMAS
# ==============================================================================

class ExternalTargetResponse(ExternalTargetBase):
    """Réponse pour une cible externe."""
    id: UUID
    tenant_id: UUID
    last_scan_at: Optional[datetime] = None
    last_scan_status: ScanStatus = ScanStatus.NEVER
    last_exposure_score: Optional[int] = None
    created_by: Optional[UUID] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    # Nom de l'entité (résolu depuis entity_id)
    entity_name: Optional[str] = None

    class Config:
        from_attributes = True


class ExternalTargetListResponse(BaseModel):
    """Liste de cibles externes."""
    items: list[ExternalTargetResponse]
    total: int
    limit: int
    offset: int


class ScanSummary(BaseModel):
    """Résumé d'un scan."""
    nb_services_exposed: int = 0
    nb_vuln_critical: int = 0
    nb_vuln_high: int = 0
    nb_vuln_medium: int = 0
    nb_vuln_low: int = 0
    nb_vuln_info: int = 0
    nb_vuln_total: int = 0
    exposure_score: int = 0
    risk_level: Optional[str] = None
    tls_grade: Optional[str] = None
    ports_scanned: int = 0
    scan_duration_seconds: float = 0


class TargetInfo(BaseModel):
    """Info minimale sur la cible pour inclusion dans les réponses scan."""
    value: Optional[str] = None
    type: Optional[str] = None
    label: Optional[str] = None


class ExternalScanResponse(BaseModel):
    """Réponse pour un scan."""
    id: UUID
    external_target_id: UUID
    tenant_id: UUID
    status: ScanExecutionStatus
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error_message: Optional[str] = None
    summary: Optional[ScanSummary] = None
    report_generated: bool = False
    report_id: Optional[UUID] = None
    triggered_by: Optional[UUID] = None
    trigger_type: str = "manual"
    created_at: datetime
    target: Optional[TargetInfo] = None  # Info cible optionnelle
    # Entité liée (si scan externe)
    entity_id: Optional[UUID] = None
    entity_name: Optional[str] = None

    class Config:
        from_attributes = True


class ExternalScanListResponse(BaseModel):
    """Liste de scans."""
    items: list[ExternalScanResponse]
    total: int
    limit: int
    offset: int


class ScanLaunchResponse(BaseModel):
    """Réponse au lancement d'un scan."""
    scan_id: UUID
    target_id: UUID
    status: ScanExecutionStatus = ScanExecutionStatus.PENDING
    message: str = "Scan en cours de traitement"
    task_id: Optional[str] = None


class VulnerabilityResponse(BaseModel):
    """Réponse pour une vulnérabilité."""
    id: UUID
    external_scan_id: UUID
    tenant_id: UUID
    port: Optional[int] = None
    protocol: Optional[str] = None
    service_name: Optional[str] = None
    service_version: Optional[str] = None
    service_banner: Optional[str] = None
    vulnerability_type: VulnerabilityType
    severity: SeverityLevel
    cve_ids: Optional[list[str]] = None
    cvss_score: Optional[float] = None
    cvss_vector: Optional[str] = None
    title: str
    description: Optional[str] = None
    recommendation: Optional[str] = None
    references: Optional[list[str]] = None
    is_remediated: bool = False
    remediated_at: Optional[datetime] = None
    remediated_by: Optional[UUID] = None
    created_at: datetime

    class Config:
        from_attributes = True


class VulnerabilityListResponse(BaseModel):
    """Liste de vulnérabilités."""
    items: list[VulnerabilityResponse]
    total: int
    limit: int
    offset: int
    # Compteurs par sévérité
    by_severity: dict[str, int] = {}


class ServiceResponse(BaseModel):
    """Réponse pour un service détecté."""
    port: int
    protocol: str
    service_name: str
    service_version: Optional[str] = None
    service_product: Optional[str] = None
    service_banner: Optional[str] = None
    cpe: Optional[str] = None
    is_risky: bool = False
    vulnerabilities_count: int = 0


class TLSProtocols(BaseModel):
    """Protocoles TLS supportés."""
    ssl2: bool = False
    ssl3: bool = False
    tls10: bool = False
    tls11: bool = False
    tls12: bool = False
    tls13: bool = False


class TLSCertificate(BaseModel):
    """Information sur le certificat SSL/TLS."""
    subject: Optional[str] = None
    issuer: Optional[str] = None
    serial_number: Optional[str] = None
    not_before: Optional[str] = None
    not_after: Optional[str] = None
    is_expired: bool = False
    days_until_expiry: Optional[int] = None
    is_self_signed: bool = False
    signature_algorithm: Optional[str] = None
    public_key_algorithm: Optional[str] = None
    public_key_size: Optional[int] = None
    san_domains: list[str] = []


class TLSCiphers(BaseModel):
    """Cipher suites TLS."""
    strong: list[str] = []
    weak: list[str] = []


class TLSDetails(BaseModel):
    """Détails complets de l'audit TLS."""
    protocols: Optional[TLSProtocols] = None
    certificate: Optional[TLSCertificate] = None
    ciphers: Optional[TLSCiphers] = None
    grade: Optional[str] = None
    error: Optional[str] = None


class InfrastructureInfo(BaseModel):
    """Informations sur l'infrastructure détectée."""
    os_name: Optional[str] = None
    os_family: Optional[str] = None
    os_vendor: Optional[str] = None
    os_version: Optional[str] = None
    os_accuracy: int = 0
    os_type: Optional[str] = None
    os_cpe: Optional[str] = None
    ip_address: Optional[str] = None
    hostname: Optional[str] = None
    web_server: Optional[str] = None
    technologies: list[str] = []


class ScanData(BaseModel):
    """Données complètes du scan."""
    services: list[dict] = []
    tls_details: Optional[TLSDetails] = None
    infrastructure: Optional[InfrastructureInfo] = None
    raw_command: Optional[str] = None


class ScanDetailResponse(BaseModel):
    """Détail complet d'un scan."""
    scan: ExternalScanResponse
    target: ExternalTargetResponse
    services: list[ServiceResponse] = []
    vulnerabilities: list[VulnerabilityResponse] = []
    summary: Optional[ScanSummary] = None
    scan_data: Optional[ScanData] = None


# ==============================================================================
# DASHBOARD / STATS SCHEMAS
# ==============================================================================

class ExposureStats(BaseModel):
    """Statistiques d'exposition pour le dashboard."""
    total_targets: int = 0
    targets_scanned: int = 0
    targets_never_scanned: int = 0
    total_scans: int = 0
    scans_last_30_days: int = 0
    average_exposure_score: float = 0
    critical_vulnerabilities: int = 0
    high_vulnerabilities: int = 0
    medium_vulnerabilities: int = 0
    low_vulnerabilities: int = 0
    targets_by_type: dict[str, int] = {}
    exposure_trend: list[dict[str, Any]] = []


class TopVulnerableTarget(BaseModel):
    """Cible la plus vulnérable."""
    target_id: UUID
    target_value: str
    target_type: ExternalTargetType
    exposure_score: int
    critical_count: int
    high_count: int
    last_scan_at: Optional[datetime] = None


class DashboardResponse(BaseModel):
    """Réponse pour le dashboard scanner."""
    stats: ExposureStats
    top_vulnerable_targets: list[TopVulnerableTarget] = []
    recent_scans: list[ExternalScanResponse] = []
    critical_findings: list[VulnerabilityResponse] = []
