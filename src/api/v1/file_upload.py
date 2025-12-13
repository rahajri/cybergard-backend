"""
API endpoints pour l'upload de fichiers (pièces jointes des questionnaires)
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from sqlalchemy.orm import Session
from typing import Optional, List
from uuid import UUID
from datetime import datetime
import uuid
import logging

from src.database import get_db
from src.services.file_storage_service import FileStorageService
from src.models.audit import QuestionAnswer
from src.schemas.file_upload import FileUploadResponse, FileMetadata
import base64

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/audite", tags=["File Upload"])

# Instance du service de stockage
file_storage = FileStorageService()


def decode_original_filename(metadata: dict, fallback: str) -> str:
    """Décode le nom de fichier original depuis les métadonnées MinIO"""
    minio_metadata = metadata.get('metadata', {})

    # Nouveau format (base64)
    if 'original-filename-b64' in minio_metadata:
        try:
            encoded = minio_metadata['original-filename-b64']
            return base64.b64decode(encoded).decode('utf-8')
        except Exception as e:
            logger.warning(f"⚠️ Erreur décodage base64 filename: {e}")

    # Ancien format (ASCII uniquement) - pour compatibilité
    if 'original-filename' in minio_metadata:
        return minio_metadata['original-filename']

    # Fallback
    return fallback


@router.post("/upload", response_model=FileUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_file(
    file: UploadFile = File(...),
    question_id: str = Form(...),
    audit_id: str = Form(...),
    answer_id: Optional[str] = Form(None),
    tenant_id: Optional[str] = Form(None),  # TODO: Récupérer depuis l'auth
    db: Session = Depends(get_db)
):
    """
    Upload un fichier en pièce jointe pour une question.

    Args:
        file: Fichier à uploader
        question_id: ID de la question
        audit_id: ID de l'audit
        answer_id: ID de la réponse (optionnel, créé automatiquement si absent)
        tenant_id: ID du tenant (pour isolation)

    Returns:
        FileUploadResponse avec métadonnées du fichier
    """
    try:
        # Valider la taille du fichier (10MB max)
        MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
        file_content = await file.read()
        file_size = len(file_content)

        if file_size > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Le fichier dépasse la taille maximale de 10 MB (taille: {file_size / (1024*1024):.2f} MB)"
            )

        # Remettre le curseur au début pour l'upload
        await file.seek(0)

        # Créer ou récupérer l'answer_id
        if not answer_id:
            # Créer une réponse temporaire pour stocker les fichiers
            # TODO: Implémenter la logique de création d'answer
            answer_id = str(uuid.uuid4())

        # Utiliser un tenant_id par défaut si non fourni
        if not tenant_id:
            tenant_id = "00000000-0000-0000-0000-000000000000"  # Default tenant

        logger.info(f"📤 Upload fichier: {file.filename} ({file_size} bytes) pour question {question_id}")

        # Upload vers MinIO
        object_path, checksum, uploaded_size = file_storage.upload_file(
            file_data=file.file,
            original_filename=file.filename,
            tenant_id=UUID(tenant_id),
            audit_id=UUID(audit_id),
            answer_id=UUID(answer_id),
            content_type=file.content_type or "application/octet-stream"
        )

        logger.info(f"✅ Fichier uploadé: {object_path}")

        # Retourner les métadonnées
        # Note: On utilise object_path comme ID pour pouvoir le récupérer ensuite
        return FileUploadResponse(
            id=object_path,  # Chemin complet utilisé comme ID
            filename=object_path.split('/')[-1],
            original_filename=file.filename,
            size=uploaded_size,
            content_type=file.content_type or "application/octet-stream",
            uploaded_at=datetime.utcnow().isoformat(),
            audit_id=audit_id,
            question_id=question_id,
            answer_id=answer_id
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur upload fichier: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de l'upload du fichier: {str(e)}"
        )


@router.get("/upload/{file_path:path}/download")
async def download_file(
    file_path: str,
    tenant_id: Optional[str] = None,  # TODO: Récupérer depuis l'auth
    db: Session = Depends(get_db)
):
    """
    Télécharge un fichier via son chemin (object_path).

    Args:
        file_path: Chemin complet du fichier dans MinIO (object_path)
        tenant_id: ID du tenant (pour vérification d'accès)

    Returns:
        StreamingResponse avec le fichier
    """
    try:
        from fastapi.responses import StreamingResponse

        # Utiliser un tenant_id par défaut si non fourni
        if not tenant_id:
            tenant_id = "00000000-0000-0000-0000-000000000000"

        logger.info(f"📥 Téléchargement fichier: {file_path}")

        # Récupérer le fichier depuis MinIO
        response = file_storage.download_file(
            object_path=file_path,
            tenant_id=UUID(tenant_id)
        )

        # Récupérer les métadonnées pour avoir original_filename et content_type
        metadata_info = file_storage.get_file_metadata(
            object_path=file_path,
            tenant_id=UUID(tenant_id)
        )

        # Extraire original filename depuis les métadonnées MinIO (décodage base64 si nécessaire)
        original_filename = decode_original_filename(metadata_info, file_path.split('/')[-1])
        content_type = metadata_info.get('content_type', 'application/octet-stream')

        logger.info(f"✅ Fichier téléchargé: {file_path} ({original_filename})")

        # Retourner le fichier en streaming
        return StreamingResponse(
            response.stream(),
            media_type=content_type,
            headers={
                'Content-Disposition': f'attachment; filename="{original_filename}"'
            }
        )

    except PermissionError as e:
        logger.error(f"❌ Accès non autorisé: {file_path}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès non autorisé à ce fichier"
        )
    except Exception as e:
        logger.error(f"❌ Erreur téléchargement fichier: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND if "NoSuchKey" in str(e) else status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors du téléchargement: {str(e)}"
        )


@router.delete("/upload/{file_path:path}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    file_path: str,
    tenant_id: Optional[str] = None,  # TODO: Récupérer depuis l'auth
    db: Session = Depends(get_db)
):
    """
    Supprime un fichier.

    Args:
        file_path: Chemin complet du fichier dans MinIO
        tenant_id: ID du tenant (pour vérification d'accès)
    """
    try:
        # Utiliser un tenant_id par défaut si non fourni
        if not tenant_id:
            tenant_id = "00000000-0000-0000-0000-000000000000"

        logger.info(f"🗑️  Suppression fichier: {file_path}")

        # Supprimer depuis MinIO
        success = file_storage.delete_file(
            object_path=file_path,
            tenant_id=UUID(tenant_id)
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Fichier introuvable: {file_path}"
            )

        logger.info(f"✅ Fichier supprimé: {file_path}")
        return

    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès non autorisé à ce fichier"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur suppression fichier: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la suppression: {str(e)}"
        )


@router.get("/upload/audit/{audit_id}", response_model=List[FileMetadata])
async def list_files_by_audit(
    audit_id: str,
    tenant_id: Optional[str] = None,  # TODO: Récupérer depuis l'auth
    db: Session = Depends(get_db)
):
    """
    Liste tous les fichiers uploadés pour un audit.

    Args:
        audit_id: ID de l'audit
        tenant_id: ID du tenant

    Returns:
        Liste des métadonnées des fichiers
    """
    try:
        # Utiliser un tenant_id par défaut si non fourni
        if not tenant_id:
            tenant_id = "00000000-0000-0000-0000-000000000000"

        logger.info(f"📋 Liste fichiers pour audit: {audit_id}")

        # Liste depuis MinIO
        files = file_storage.list_files(
            tenant_id=UUID(tenant_id),
            audit_id=UUID(audit_id)
        )

        logger.info(f"✅ {len(files)} fichier(s) trouvé(s)")

        # Récupérer les métadonnées de chaque fichier
        result = []
        for f in files:
            if f['is_dir']:
                continue  # Ignorer les dossiers

            try:
                # Récupérer métadonnées détaillées
                metadata = file_storage.get_file_metadata(
                    object_path=f['object_name'],
                    tenant_id=UUID(tenant_id)
                )

                # Extraire original_filename depuis metadata (décodage base64 si nécessaire)
                original_filename = decode_original_filename(metadata, f['object_name'].split('/')[-1])

                result.append(FileMetadata(
                    id=f['object_name'],  # Utiliser object_path comme ID
                    filename=f['object_name'].split('/')[-1],
                    original_filename=original_filename,
                    size=f['size'],
                    content_type=metadata.get('content_type', 'application/octet-stream'),
                    uploaded_at=f['last_modified'].isoformat() if f['last_modified'] else datetime.utcnow().isoformat()
                ))
            except Exception as e:
                logger.warning(f"Erreur récupération métadonnées pour {f['object_name']}: {e}")
                continue

        return result

    except Exception as e:
        logger.error(f"❌ Erreur liste fichiers: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération des fichiers: {str(e)}"
        )
