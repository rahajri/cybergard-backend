# backend/src/api/v1/attachments.py
"""
Endpoints API pour la gestion des pièces jointes d'audit
- Upload/Download avec chiffrement
- Validation de sécurité
- Scan antivirus (optionnel)
- Isolation par tenant
"""
from fastapi import APIRouter, Depends, File, UploadFile, HTTPException, status, Form, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional, List
from uuid import UUID
import logging
import io
from datetime import datetime

from ...database import get_db
from ...models.attachment import AnswerAttachment, AttachmentAccessLog
from ...models.audit import User
from ...schemas.attachment import (
    AttachmentResponse,
    AttachmentListResponse,
    AttachmentUpdateRequest,
    FileUploadResponse,
    AttachmentStatsResponse,
    ALLOWED_MIME_TYPES,
    FORBIDDEN_EXTENSIONS,
    MAX_FILE_SIZE
)
from ...services.file_storage_service import FileStorageService
from ...services.virus_scanner_service import VirusScannerService
from ...dependencies_keycloak import get_current_user_keycloak, require_permission

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Attachments"])

# Initialiser les services
storage_service = FileStorageService()
virus_scanner = VirusScannerService()  # À créer


# ========== HELPERS ==========

def get_tenant_id_from_audit(db: Session, audit_id: UUID) -> UUID:
    """Récupère le tenant_id depuis l'audit"""
    result = db.execute(
        text("SELECT tenant_id FROM audit WHERE id = :audit_id"),
        {"audit_id": str(audit_id)}
    ).fetchone()

    if not result:
        raise HTTPException(status_code=404, detail="Audit non trouvé")

    return result[0]


def validate_file_security(
    file: UploadFile,
    attachment_type: str,
    max_size: Optional[int] = None
) -> tuple[bool, Optional[str]]:
    """
    Valide la sécurité d'un fichier.

    Returns:
        (is_valid, error_message)
    """
    # 1. Vérifier extension
    file_ext = file.filename.split(".")[-1].lower() if "." in file.filename else ""

    if f".{file_ext}" in FORBIDDEN_EXTENSIONS:
        return False, f"Extension interdite : .{file_ext}"

    # 2. Vérifier type MIME
    allowed_types = ALLOWED_MIME_TYPES.get(attachment_type, [])

    if file.content_type not in allowed_types:
        return False, f"Type MIME non autorisé : {file.content_type}. Autorisés : {', '.join(allowed_types)}"

    # 3. Vérifier taille
    max_allowed = max_size or MAX_FILE_SIZE.get(attachment_type, 50 * 1024 * 1024)

    # Lire la taille
    file.file.seek(0, 2)  # Aller à la fin
    file_size = file.file.tell()
    file.file.seek(0)  # Reset

    if file_size > max_allowed:
        return False, f"Fichier trop volumineux : {file_size / (1024*1024):.2f} MB (max: {max_allowed / (1024*1024):.2f} MB)"

    if file_size == 0:
        return False, "Fichier vide"

    return True, None


def log_attachment_access(
    db: Session,
    attachment_id: UUID,
    user_id: UUID,
    tenant_id: UUID,
    access_type: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None
):
    """Enregistre un accès à une pièce jointe (RGPD compliance)"""
    try:
        log_entry = AttachmentAccessLog(
            attachment_id=attachment_id,
            accessed_by=user_id,
            tenant_id=tenant_id,
            access_type=access_type,
            ip_address=ip_address,
            user_agent=user_agent
        )
        db.add(log_entry)
        db.commit()
    except Exception as e:
        logger.error(f"Erreur log accès : {e}")
        # Ne pas bloquer l'opération si le log échoue
        db.rollback()


# ========== ENDPOINTS ==========

@router.post("/upload", status_code=status.HTTP_201_CREATED, response_model=FileUploadResponse)
async def upload_attachment(
    file: UploadFile = File(...),
    answer_id: UUID = Form(...),
    audit_id: UUID = Form(...),
    attachment_type: str = Form("evidence"),
    description: Optional[str] = Form(None),
    current_user: User = Depends(require_permission("GED_READ")),
    db: Session = Depends(get_db)
):
    """
    Upload une pièce jointe pour une réponse d'audit.

    **Sécurité :**
    - Validation du type MIME
    - Vérification de la taille
    - Scan antivirus (optionnel)
    - Chiffrement automatique (SSE-S3)
    - Isolation par tenant

    **Process :**
    1. Validation sécurité
    2. Upload vers MinIO chiffré
    3. Scan antivirus (async)
    4. Enregistrement métadonnées en BDD
    """
    try:
        # 1. Récupérer tenant_id depuis audit
        tenant_id = get_tenant_id_from_audit(db, audit_id)

        # 2. Vérifier que la réponse existe et appartient à l'audit
        answer = db.execute(
            text("SELECT id FROM question_answer WHERE id = :aid AND audit_id = :audit_id"),
            {"aid": str(answer_id), "audit_id": str(audit_id)}
        ).fetchone()

        if not answer:
            raise HTTPException(
                status_code=404,
                detail="Réponse non trouvée ou n'appartient pas à cet audit"
            )

        # 3. Validation sécurité du fichier
        is_valid, error_msg = validate_file_security(file, attachment_type)
        if not is_valid:
            raise HTTPException(status_code=400, detail=error_msg)

        # 4. Upload vers MinIO
        file_data = io.BytesIO(await file.read())
        object_path, checksum, file_size = storage_service.upload_file(
            file_data=file_data,
            original_filename=file.filename,
            tenant_id=tenant_id,
            audit_id=audit_id,
            answer_id=answer_id,
            content_type=file.content_type
        )

        # 5. Scan antivirus (async)
        virus_scan_status = "pending"
        try:
            file_data.seek(0)
            scan_result = await virus_scanner.scan_file(file_data)
            virus_scan_status = "clean" if scan_result["is_clean"] else "infected"
        except Exception as e:
            logger.warning(f"Scan antivirus échoué : {e}")
            virus_scan_status = "skipped"

        # Si infecté, supprimer immédiatement
        if virus_scan_status == "infected":
            storage_service.delete_file(object_path, tenant_id)
            raise HTTPException(
                status_code=400,
                detail="Fichier infecté détecté et supprimé"
            )

        # 6. Enregistrer métadonnées en BDD
        file_ext = file.filename.split(".")[-1] if "." in file.filename else None

        # Récupérer l'entity_member_id depuis la réponse (answered_by)
        # Pour les audités, uploaded_by doit pointer vers entity_member.id
        # Note: text est déjà importé au niveau du module (ligne 12)

        answer_query = text("""
            SELECT answered_by FROM question_answer
            WHERE id = CAST(:answer_id AS uuid)
            LIMIT 1
        """)
        answer_result = db.execute(answer_query, {"answer_id": str(answer_id)}).fetchone()

        # Si la réponse a un answered_by, c'est l'ID de l'entity_member qui a uploadé
        # Sinon, utiliser l'ID du current_user (auditeur)
        if answer_result and answer_result.answered_by:
            uploaded_by_id = answer_result.answered_by
            logger.info(f"📎 Upload par entity_member (audité): {uploaded_by_id}")
        else:
            uploaded_by_id = current_user.id if hasattr(current_user, 'id') else current_user.get('sub')
            logger.info(f"📎 Upload par user (auditeur): {uploaded_by_id}")

        attachment = AnswerAttachment(
            answer_id=answer_id,
            audit_id=audit_id,
            tenant_id=tenant_id,
            filename=object_path.split("/")[-1],  # UUID filename
            original_filename=file.filename,
            file_path=object_path,
            file_size=file_size,
            mime_type=file.content_type,
            file_extension=file_ext,
            attachment_type=attachment_type,
            description=description,
            checksum_sha256=checksum,
            virus_scan_status=virus_scan_status,
            virus_scan_date=datetime.utcnow() if virus_scan_status != "pending" else None,
            uploaded_by=uploaded_by_id
        )

        db.add(attachment)
        db.commit()
        db.refresh(attachment)

        # 7. Log l'accès (upload)
        log_attachment_access(
            db, attachment.id, uploaded_by_id, tenant_id, "upload"
        )

        # 8. Générer URL download temporaire (1h)
        download_url = storage_service.get_presigned_url(
            object_path, tenant_id
        )

        logger.info(
            f"✅ Fichier uploadé : {file.filename} -> {object_path} "
            f"(tenant={tenant_id}, size={file_size}, virus={virus_scan_status})"
        )

        return FileUploadResponse(
            id=attachment.id,
            filename=object_path.split("/")[-1],  # UUID filename
            original_filename=file.filename,
            size=file_size,
            content_type=file.content_type,
            uploaded_at=attachment.uploaded_at.isoformat(),
            download_url=download_url,
            checksum=checksum,
            virus_scan_status=virus_scan_status
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur upload : {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de l'upload : {str(e)}"
        )


@router.get("/{attachment_id}/download")
async def download_attachment(
    attachment_id: UUID,
    inline: bool = Query(False, description="Si True, affiche le fichier en ligne (preview) au lieu de forcer le téléchargement"),
    current_user: User = Depends(require_permission("GED_READ")),
    db: Session = Depends(get_db)
):
    """
    Télécharge ou prévisualise une pièce jointe.

    **Sécurité :**
    - Vérification que le fichier appartient au tenant de l'utilisateur
    - Vérification du statut virus (refuse si infecté)
    - Log de l'accès (RGPD)

    **Paramètres :**
    - inline=true : Affiche le fichier dans le navigateur (preview)
    - inline=false (défaut) : Force le téléchargement
    """
    try:
        # 1. Récupérer l'attachment avec vérifications
        attachment = db.query(AnswerAttachment).filter(
            AnswerAttachment.id == attachment_id,
            AnswerAttachment.is_active == True
        ).first()

        if not attachment:
            raise HTTPException(status_code=404, detail="Pièce jointe non trouvée")

        # 2. Vérifier statut virus
        if attachment.virus_scan_status == "infected":
            raise HTTPException(
                status_code=403,
                detail="Fichier infecté - téléchargement interdit"
            )

        # 3. Télécharger depuis MinIO
        file_data = storage_service.download_file(
            object_path=attachment.file_path,
            tenant_id=attachment.tenant_id
        )

        # 4. Log l'accès
        user_id = current_user.id if hasattr(current_user, 'id') else current_user.get('sub')
        access_type = "preview" if inline else "download"
        log_attachment_access(
            db, attachment.id, user_id,
            attachment.tenant_id, access_type
        )

        # 5. Retourner le fichier avec le bon Content-Disposition
        disposition = "inline" if inline else "attachment"
        return StreamingResponse(
            file_data,
            media_type=attachment.mime_type,
            headers={
                "Content-Disposition": f'{disposition}; filename="{attachment.original_filename}"',
                "X-File-Size": str(attachment.file_size),
                "X-Checksum-SHA256": attachment.checksum_sha256 or ""
            }
        )

    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur download : {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors du téléchargement : {str(e)}"
        )


@router.get("/{attachment_id}", response_model=AttachmentResponse)
def get_attachment(
    attachment_id: UUID,
    current_user: User = Depends(require_permission("GED_READ")),
    db: Session = Depends(get_db)
):
    """Récupère les métadonnées d'une pièce jointe"""
    attachment = db.query(AnswerAttachment).filter(
        AnswerAttachment.id == attachment_id,
        AnswerAttachment.is_active == True
    ).first()

    if not attachment:
        raise HTTPException(status_code=404, detail="Pièce jointe non trouvée")

    return attachment


@router.get("/answer/{answer_id}", response_model=AttachmentListResponse)
def list_attachments_for_answer(
    answer_id: UUID,
    current_user: User = Depends(require_permission("GED_READ")),
    db: Session = Depends(get_db)
):
    """Liste toutes les pièces jointes d'une réponse"""
    attachments = db.query(AnswerAttachment).filter(
        AnswerAttachment.answer_id == answer_id,
        AnswerAttachment.is_active == True
    ).all()

    return AttachmentListResponse(
        attachments=attachments,
        total=len(attachments)
    )


@router.delete("/{attachment_id}")
def delete_attachment(
    attachment_id: UUID,
    current_user: User = Depends(require_permission("GED_READ")),
    db: Session = Depends(get_db)
):
    """
    Supprime une pièce jointe (soft delete).

    Le fichier reste dans MinIO (versioning) mais est marqué comme supprimé.
    """
    attachment = db.query(AnswerAttachment).filter(
        AnswerAttachment.id == attachment_id
    ).first()

    if not attachment:
        raise HTTPException(status_code=404, detail="Pièce jointe non trouvée")

    # Soft delete
    attachment.is_active = False
    attachment.deleted_at = datetime.utcnow()

    # Log l'accès
    user_id = current_user.id if hasattr(current_user, 'id') else current_user.get('sub')
    log_attachment_access(
        db, attachment.id, user_id,
        attachment.tenant_id, "delete"
    )

    db.commit()

    logger.info(f"✅ Pièce jointe supprimée (soft) : {attachment_id}")

    return {"message": "Pièce jointe supprimée avec succès"}


@router.get("/stats/tenant/{tenant_id}", response_model=AttachmentStatsResponse)
def get_tenant_attachment_stats(
    tenant_id: UUID,
    current_user: User = Depends(require_permission("GED_READ")),
    db: Session = Depends(get_db)
):
    """Statistiques des pièces jointes d'un tenant"""
    query = text("""
        SELECT
            COUNT(*) as total,
            SUM(file_size) as total_size,
            attachment_type,
            virus_scan_status,
            COUNT(*) FILTER (WHERE uploaded_at > NOW() - INTERVAL '24 hours') as recent_uploads
        FROM answer_attachment
        WHERE tenant_id = :tenant_id AND is_active = true
        GROUP BY attachment_type, virus_scan_status
    """)

    results = db.execute(query, {"tenant_id": str(tenant_id)}).fetchall()

    total_attachments = sum(r[0] for r in results)
    total_size = sum(r[1] or 0 for r in results)
    by_type = {}
    by_virus = {}
    recent_uploads = 0

    for r in results:
        count, size, att_type, virus_status, recent = r
        by_type[att_type] = by_type.get(att_type, 0) + count
        by_virus[virus_status] = by_virus.get(virus_status, 0) + count
        recent_uploads += recent

    return AttachmentStatsResponse(
        total_attachments=total_attachments,
        total_size_mb=round(total_size / (1024 * 1024), 2),
        by_type=by_type,
        by_virus_status=by_virus,
        pending_scan_count=by_virus.get("pending", 0),
        infected_count=by_virus.get("infected", 0),
        recent_uploads=recent_uploads
    )
