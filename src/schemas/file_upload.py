"""
Schémas Pydantic pour l'upload de fichiers
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class FileMetadata(BaseModel):
    """Métadonnées d'un fichier uploadé"""
    id: str = Field(..., description="ID unique du fichier (UUID)")
    filename: str = Field(..., description="Nom du fichier dans MinIO")
    original_filename: str = Field(..., description="Nom original du fichier")
    size: int = Field(..., description="Taille du fichier en bytes")
    content_type: str = Field(..., description="Type MIME du fichier")
    uploaded_at: str = Field(..., description="Date/heure d'upload (ISO format)")

    class Config:
        from_attributes = True


class FileUploadResponse(FileMetadata):
    """Réponse après upload d'un fichier"""
    audit_id: str = Field(..., description="ID de l'audit")
    question_id: str = Field(..., description="ID de la question")
    answer_id: str = Field(..., description="ID de la réponse")
    download_url: Optional[str] = Field(None, description="URL de téléchargement (pré-signée)")


class FileUploadRequest(BaseModel):
    """Requête d'upload de fichier"""
    question_id: str = Field(..., description="ID de la question")
    audit_id: str = Field(..., description="ID de l'audit")
    answer_id: Optional[str] = Field(None, description="ID de la réponse (créé automatiquement si absent)")
