# backend/src/schemas/attachment.py
"""
Schémas Pydantic pour la gestion des pièces jointes
"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Literal
from datetime import datetime
from uuid import UUID


class AttachmentBase(BaseModel):
    """Schéma de base pour les pièces jointes"""
    original_filename: str = Field(..., min_length=1, max_length=255)
    attachment_type: Literal["evidence", "screenshot", "policy", "report", "certificate", "log", "other"] = "evidence"
    description: Optional[str] = None


class AttachmentUploadRequest(AttachmentBase):
    """Requête pour uploader une pièce jointe"""
    answer_id: UUID
    audit_id: UUID

    @field_validator("original_filename")
    @classmethod
    def validate_filename(cls, v: str) -> str:
        """Valide le nom de fichier"""
        # Interdire les caractères dangereux
        forbidden_chars = ["<", ">", ":", '"', "/", "\\", "|", "?", "*", "\x00"]
        for char in forbidden_chars:
            if char in v:
                raise ValueError(f"Le nom de fichier contient un caractère interdit: {char}")

        # Vérifier l'extension
        if "." not in v:
            raise ValueError("Le fichier doit avoir une extension")

        return v


class AttachmentResponse(AttachmentBase):
    """Réponse contenant les métadonnées d'une pièce jointe"""
    id: UUID
    answer_id: UUID
    audit_id: UUID
    tenant_id: UUID
    filename: str
    file_path: str
    file_size: int
    mime_type: str
    file_extension: Optional[str]
    checksum_sha256: Optional[str]
    virus_scan_status: Literal["pending", "clean", "infected", "error", "skipped"]
    virus_scan_date: Optional[datetime]
    version: int
    is_current: bool
    replaced_by: Optional[UUID]
    uploaded_by: Optional[UUID]
    uploaded_at: datetime
    updated_at: datetime
    is_active: bool

    # Propriétés calculées
    file_size_mb: Optional[float] = None
    is_safe: Optional[bool] = None
    uploaded_by_email: Optional[str] = None
    uploaded_by_name: Optional[str] = None

    class Config:
        from_attributes = True


class AttachmentListResponse(BaseModel):
    """Liste paginée de pièces jointes"""
    attachments: List[AttachmentResponse]
    total: int = 0
    page: int = 1
    page_size: int = 50


class AttachmentUpdateRequest(BaseModel):
    """Requête pour mettre à jour une pièce jointe"""
    description: Optional[str] = None
    attachment_type: Optional[Literal["evidence", "screenshot", "policy", "report", "certificate", "log", "other"]] = None


class AttachmentAccessLogResponse(BaseModel):
    """Réponse pour un log d'accès"""
    id: UUID
    attachment_id: UUID
    accessed_by: UUID
    access_type: Literal["view", "download", "preview", "delete", "update"]
    accessed_at: datetime
    ip_address: Optional[str]
    user_agent: Optional[str]
    accessed_by_email: Optional[str]
    accessed_by_name: Optional[str]

    class Config:
        from_attributes = True


class AttachmentStatsResponse(BaseModel):
    """Statistiques sur les pièces jointes"""
    total_attachments: int = 0
    total_size_mb: float = 0.0
    by_type: dict[str, int] = Field(default_factory=dict)
    by_virus_status: dict[str, int] = Field(default_factory=dict)
    pending_scan_count: int = 0
    infected_count: int = 0
    recent_uploads: int = 0  # Dernières 24h


class FileUploadResponse(BaseModel):
    """Réponse après upload d'un fichier - Format compatible frontend"""
    id: UUID  # Correspond à attachment_id
    filename: str  # Nom de fichier chiffré (UUID)
    original_filename: str  # Nom original du fichier
    size: int  # Taille en bytes (file_size)
    content_type: str  # Type MIME (mime_type)
    uploaded_at: str  # Date d'upload (ISO format)
    download_url: Optional[str] = None

    # Champs supplémentaires utiles (optionnels)
    checksum: Optional[str] = None
    virus_scan_status: Optional[str] = None


class FileValidationError(BaseModel):
    """Erreur de validation de fichier"""
    field: str
    error: str
    details: Optional[str] = None


# Configuration des types MIME autorisés par catégorie
ALLOWED_MIME_TYPES = {
    "evidence": [
        "application/pdf",
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
        "text/csv",
    ],
    "screenshot": [
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
        "image/bmp",
    ],
    "policy": [
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
    ],
    "report": [
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "text/html",
    ],
    "certificate": [
        "application/pdf",
        "application/x-x509-ca-cert",
        "application/pkix-cert",
    ],
    "log": [
        "text/plain",
        "text/csv",
        "application/json",
        "application/xml",
    ],
    "other": [
        "application/pdf",
        "image/jpeg",
        "image/png",
        "text/plain",
        "application/zip",
        "application/x-7z-compressed",
    ],
}

# Extensions interdites (exécutables, scripts)
FORBIDDEN_EXTENSIONS = [
    ".exe", ".dll", ".bat", ".cmd", ".com", ".scr", ".pif",
    ".vbs", ".js", ".jse", ".wsf", ".wsh", ".ps1", ".psm1",
    ".sh", ".bash", ".zsh", ".app", ".deb", ".rpm",
]

# Taille maximale par type (en bytes)
MAX_FILE_SIZE = {
    "evidence": 50 * 1024 * 1024,  # 50 MB
    "screenshot": 10 * 1024 * 1024,  # 10 MB
    "policy": 25 * 1024 * 1024,  # 25 MB
    "report": 50 * 1024 * 1024,  # 50 MB
    "certificate": 5 * 1024 * 1024,  # 5 MB
    "log": 20 * 1024 * 1024,  # 20 MB
    "other": 50 * 1024 * 1024,  # 50 MB
}
