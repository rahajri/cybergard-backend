# src/api/v1/client_questionnaires.py
"""
Endpoints Questionnaires côté Client.

Ce module permet aux clients de:
- Lister les questionnaires activés pour leur organisation
- Voir les détails d'un questionnaire
- Dupliquer un questionnaire (crée une ORG_VARIANT)
- Éditer leurs propres copies (ORG_VARIANT)
- Supprimer leurs propres copies (si non utilisées dans un audit)
"""

from __future__ import annotations

import logging
import uuid as uuid_lib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from src.database import get_db
from src.models.audit import User
from src.dependencies_keycloak import get_current_user_keycloak, require_permission

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/client/questionnaires", tags=["client-questionnaires"])


# ——— Helpers ———
def _to_iso(dt) -> Optional[str]:
    try:
        return dt.isoformat() if dt else None
    except Exception:
        return None


def _get_user_org_id(db: Session, user: User) -> Optional[str]:
    """Récupère l'org_id de l'utilisateur connecté."""
    if not user or not user.tenant_id:
        return None

    # Récupérer l'organisation principale du tenant
    query = text("""
        SELECT id FROM organization
        WHERE tenant_id = CAST(:tenant_id AS uuid)
        AND is_platform_owner = false
        LIMIT 1
    """)
    result = db.execute(query, {"tenant_id": str(user.tenant_id)}).fetchone()
    return str(result.id) if result else None


# ==========================================
# GET /client/questionnaires - Liste
# ==========================================
@router.get("/", status_code=status.HTTP_200_OK)
async def list_client_questionnaires(
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    search: Optional[str] = Query(default=None),
    questionnaire_status: Optional[str] = Query(default=None, alias="status"),
    current_user: User = Depends(require_permission("QUESTIONNAIRE_READ")),
    db: Session = Depends(get_db),
):
    """
    Liste les questionnaires accessibles au client.

    Retourne:
    - Les questionnaires MASTER activés pour l'organisation
    - Les questionnaires ORG_VARIANT appartenant à l'organisation
    """
    try:
        if not current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Utilisateur sans tenant associé"
            )

        tenant_id = str(current_user.tenant_id)
        org_id = _get_user_org_id(db, current_user)

        logger.info(f"🔍 Liste questionnaires client pour tenant: {tenant_id}, org: {org_id}")

        # Vérifier si les colonnes client existent (migration appliquée ou non)
        check_columns = text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'questionnaire' AND column_name = 'owner_org_id'
        """)
        has_client_columns = db.execute(check_columns).fetchone() is not None

        if has_client_columns:
            # Version avec colonnes client (après migration)
            sql = """
            WITH question_stats AS (
              SELECT
                questionnaire_id,
                COUNT(*) AS question_count,
                BOOL_OR(COALESCE(ai_generated, false)) AS has_ai_questions,
                COUNT(DISTINCT qe.question_id) AS embeddings_count
              FROM question q
              LEFT JOIN question_embeddings qe ON q.id = qe.question_id
              WHERE questionnaire_id IS NOT NULL
              GROUP BY questionnaire_id
            )
            SELECT DISTINCT
              q.id,
              q.name,
              q.status,
              q.created_at,
              q.source_type,
              q.ai_model,
              q.parent_questionnaire_id,
              q.owner_org_id,
              COALESCE(qs.question_count, 0) AS questions_count,
              COALESCE(qs.has_ai_questions, false) AS ai_generated,
              COALESCE(qs.embeddings_count, 0) AS embeddings_count,
              CASE
                WHEN COALESCE(qs.question_count, 0) > 0
                 AND COALESCE(qs.embeddings_count, 0) = COALESCE(qs.question_count, 0)
                THEN true
                ELSE false
              END AS has_embeddings,
              (q.source_type = 'ORG_VARIANT' OR q.owner_org_id IS NOT NULL) AS is_org_copy
            FROM questionnaire q
            LEFT JOIN question_stats qs ON qs.questionnaire_id = q.id
            LEFT JOIN organization_questionnaire_activation oqa ON q.id = oqa.questionnaire_id
            LEFT JOIN organization org ON oqa.org_id = org.id
            WHERE (
              (oqa.active = true AND org.tenant_id::text = :tenant_id)
              OR
              (q.owner_org_id IS NOT NULL AND q.owner_org_id::text = :org_id)
            )
            {where}
            ORDER BY q.created_at DESC NULLS LAST, q.name ASC
            LIMIT :limit OFFSET :offset
            """
        else:
            # Version sans colonnes client (avant migration) - uniquement questionnaires activés
            sql = """
            WITH question_stats AS (
              SELECT
                questionnaire_id,
                COUNT(*) AS question_count,
                BOOL_OR(COALESCE(ai_generated, false)) AS has_ai_questions,
                COUNT(DISTINCT qe.question_id) AS embeddings_count
              FROM question q
              LEFT JOIN question_embeddings qe ON q.id = qe.question_id
              WHERE questionnaire_id IS NOT NULL
              GROUP BY questionnaire_id
            )
            SELECT DISTINCT
              q.id,
              q.name,
              q.status,
              q.created_at,
              q.source_type,
              q.ai_model,
              NULL::uuid AS parent_questionnaire_id,
              NULL::uuid AS owner_org_id,
              COALESCE(qs.question_count, 0) AS questions_count,
              COALESCE(qs.has_ai_questions, false) AS ai_generated,
              COALESCE(qs.embeddings_count, 0) AS embeddings_count,
              CASE
                WHEN COALESCE(qs.question_count, 0) > 0
                 AND COALESCE(qs.embeddings_count, 0) = COALESCE(qs.question_count, 0)
                THEN true
                ELSE false
              END AS has_embeddings,
              (q.source_type = 'ORG_VARIANT') AS is_org_copy
            FROM questionnaire q
            LEFT JOIN question_stats qs ON qs.questionnaire_id = q.id
            JOIN organization_questionnaire_activation oqa ON q.id = oqa.questionnaire_id
            JOIN organization org ON oqa.org_id = org.id
            WHERE oqa.active = true AND org.tenant_id::text = :tenant_id
            {where}
            ORDER BY q.created_at DESC NULLS LAST, q.name ASC
            LIMIT :limit OFFSET :offset
            """

        params = {
            "limit": limit,
            "offset": offset,
            "tenant_id": tenant_id,
            "org_id": org_id or ""
        }
        where_clauses = []

        if search:
            where_clauses.append("q.name ILIKE :search")
            params["search"] = f"%{search}%"

        if questionnaire_status:
            where_clauses.append("q.status = :status")
            params["status"] = questionnaire_status

        where = "AND " + " AND ".join(where_clauses) if where_clauses else ""
        final_sql = sql.format(where=where)

        rows = db.execute(text(final_sql), params).fetchall()
        logger.info(f"✅ {len(rows)} questionnaires trouvés pour le client")

        return [
            {
                "id": str(r.id),
                "name": r.name,
                "status": r.status,
                "source_type": r.source_type,
                "ai_model": r.ai_model,
                "created_at": _to_iso(r.created_at),
                "questions_count": int(getattr(r, "questions_count", 0) or 0),
                "ai_generated": bool(getattr(r, "ai_generated", False)),
                "embeddings_count": int(getattr(r, "embeddings_count", 0) or 0),
                "has_embeddings": bool(getattr(r, "has_embeddings", False)),
                "is_org_copy": bool(getattr(r, "is_org_copy", False)),
                "parent_questionnaire_id": str(r.parent_questionnaire_id) if r.parent_questionnaire_id else None,
                "owner_org_id": str(r.owner_org_id) if r.owner_org_id else None,
            }
            for r in rows
        ]

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Erreur list_client_questionnaires")
        raise HTTPException(status_code=500, detail="Erreur serveur") from e


# ==========================================
# GET /client/questionnaires/stats
# ==========================================
@router.get("/stats", status_code=status.HTTP_200_OK)
async def get_client_questionnaires_stats(
    current_user: User = Depends(require_permission("QUESTIONNAIRE_READ")),
    db: Session = Depends(get_db),
):
    """Statistiques des questionnaires pour le client."""
    try:
        if not current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Utilisateur sans tenant associé"
            )

        tenant_id = str(current_user.tenant_id)
        org_id = _get_user_org_id(db, current_user)

        # Vérifier si les colonnes client existent (migration appliquée ou non)
        check_columns = text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'questionnaire' AND column_name = 'owner_org_id'
        """)
        has_client_columns = db.execute(check_columns).fetchone() is not None

        if has_client_columns:
            sql = text("""
                SELECT
                    COUNT(DISTINCT q.id) AS total,
                    COUNT(DISTINCT CASE WHEN q.status = 'published' THEN q.id END) AS published,
                    COALESCE(SUM(
                        (SELECT COUNT(*) FROM question WHERE questionnaire_id = q.id)
                    ), 0) AS total_questions,
                    COUNT(DISTINCT CASE WHEN q.owner_org_id IS NOT NULL THEN q.id END) AS org_copies
                FROM questionnaire q
                LEFT JOIN organization_questionnaire_activation oqa ON q.id = oqa.questionnaire_id
                LEFT JOIN organization org ON oqa.org_id = org.id
                WHERE (
                    (oqa.active = true AND org.tenant_id::text = :tenant_id)
                    OR
                    (q.owner_org_id IS NOT NULL AND q.owner_org_id::text = :org_id)
                )
            """)
        else:
            # Version sans colonnes client (avant migration)
            sql = text("""
                SELECT
                    COUNT(DISTINCT q.id) AS total,
                    COUNT(DISTINCT CASE WHEN q.status = 'published' THEN q.id END) AS published,
                    COALESCE(SUM(
                        (SELECT COUNT(*) FROM question WHERE questionnaire_id = q.id)
                    ), 0) AS total_questions,
                    0 AS org_copies
                FROM questionnaire q
                JOIN organization_questionnaire_activation oqa ON q.id = oqa.questionnaire_id
                JOIN organization org ON oqa.org_id = org.id
                WHERE oqa.active = true AND org.tenant_id::text = :tenant_id
            """)

        result = db.execute(sql, {"tenant_id": tenant_id, "org_id": org_id or ""}).fetchone()

        return {
            "total": int(result.total) if result else 0,
            "published": int(result.published) if result else 0,
            "total_questions": int(result.total_questions) if result else 0,
            "org_copies": int(result.org_copies) if result else 0,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Erreur get_client_questionnaires_stats")
        raise HTTPException(status_code=500, detail="Erreur serveur") from e


# ==========================================
# GET /client/questionnaires/{id}
# ==========================================
@router.get("/{questionnaire_id}", status_code=status.HTTP_200_OK)
async def get_client_questionnaire(
    questionnaire_id: str,
    include_questions: bool = Query(False),
    current_user: User = Depends(require_permission("QUESTIONNAIRE_READ")),
    db: Session = Depends(get_db),
):
    """Récupère un questionnaire accessible au client."""
    try:
        if not current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Utilisateur sans tenant associé"
            )

        tenant_id = str(current_user.tenant_id)
        org_id = _get_user_org_id(db, current_user)

        # Vérifier si les colonnes client existent (migration appliquée ou non)
        check_columns = text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'questionnaire' AND column_name = 'owner_org_id'
        """)
        has_client_columns = db.execute(check_columns).fetchone() is not None

        # Vérifier l'accès au questionnaire
        if has_client_columns:
            # is_org_copy basé sur source_type OU owner_org_id
            access_check = text("""
                SELECT q.id, q.name, q.status, q.source_type, q.ai_model,
                       q.created_at, q.framework_id, q.parent_questionnaire_id, q.owner_org_id,
                       (q.source_type = 'ORG_VARIANT' OR q.owner_org_id IS NOT NULL) AS is_org_copy
                FROM questionnaire q
                LEFT JOIN organization_questionnaire_activation oqa ON q.id = oqa.questionnaire_id
                LEFT JOIN organization org ON oqa.org_id = org.id
                WHERE q.id = CAST(:qid AS uuid)
                AND (
                    (oqa.active = true AND org.tenant_id::text = :tenant_id)
                    OR
                    (q.owner_org_id IS NOT NULL AND q.owner_org_id::text = :org_id)
                )
                LIMIT 1
            """)
        else:
            # Version sans colonnes client (avant migration)
            # is_org_copy déterminé par source_type = 'ORG_VARIANT'
            access_check = text("""
                SELECT q.id, q.name, q.status, q.source_type, q.ai_model,
                       q.created_at, q.framework_id,
                       NULL::uuid AS parent_questionnaire_id,
                       NULL::uuid AS owner_org_id,
                       (q.source_type = 'ORG_VARIANT') AS is_org_copy
                FROM questionnaire q
                JOIN organization_questionnaire_activation oqa ON q.id = oqa.questionnaire_id
                JOIN organization org ON oqa.org_id = org.id
                WHERE q.id = CAST(:qid AS uuid)
                AND oqa.active = true AND org.tenant_id::text = :tenant_id
                LIMIT 1
            """)

        row = db.execute(access_check, {
            "qid": questionnaire_id,
            "tenant_id": tenant_id,
            "org_id": org_id or ""
        }).fetchone()

        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Questionnaire introuvable ou non accessible"
            )

        result = {
            "id": str(row.id),
            "name": row.name,
            "status": row.status or "draft",
            "source_type": row.source_type,
            "ai_model": row.ai_model,
            "created_at": _to_iso(row.created_at),
            "framework_id": str(row.framework_id) if row.framework_id else None,
            "parent_questionnaire_id": str(row.parent_questionnaire_id) if row.parent_questionnaire_id else None,
            "owner_org_id": str(row.owner_org_id) if row.owner_org_id else None,
            "is_org_copy": bool(row.is_org_copy),
            "can_edit": bool(row.is_org_copy),  # Seules les copies peuvent être éditées
            "can_delete": bool(row.is_org_copy),  # Seules les copies peuvent être supprimées
        }

        # Ajouter les questions si demandé
        if include_questions:
            questions_query = text("""
                SELECT q.id, q.question_text, q.response_type, q.is_required,
                       q.help_text, q.sort_order, q.ai_generated,
                       q.requirement_id, q.control_point_id, q.framework_id,
                       d.title as domain
                FROM question q
                LEFT JOIN requirement r ON q.requirement_id = r.id
                LEFT JOIN domain d ON r.domain_id = d.id
                WHERE q.questionnaire_id = CAST(:qid AS uuid)
                ORDER BY q.sort_order ASC NULLS LAST
            """)
            questions = db.execute(questions_query, {"qid": questionnaire_id}).fetchall()
            result["questions"] = [
                {
                    "id": str(q.id),
                    "question_text": q.question_text,
                    "response_type": q.response_type,
                    "is_required": q.is_required,
                    "help_text": q.help_text,
                    "sort_order": q.sort_order,
                    "ai_generated": q.ai_generated,
                    "domain": q.domain,
                }
                for q in questions
            ]

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Erreur get_client_questionnaire")
        raise HTTPException(status_code=500, detail="Erreur serveur") from e


# ==========================================
# POST /client/questionnaires/duplicate
# ==========================================
@router.post("/duplicate", status_code=status.HTTP_201_CREATED)
async def duplicate_questionnaire(
    source_questionnaire_id: str = Query(..., description="ID du questionnaire à dupliquer"),
    new_name: Optional[str] = Query(None, description="Nouveau nom (optionnel)"),
    current_user: User = Depends(require_permission("QUESTIONNAIRE_CREATE")),
    db: Session = Depends(get_db),
):
    """
    Duplique un questionnaire pour le client.

    - Si duplication d'un MASTER → création d'un ORG_VARIANT lié au MASTER
    - Si duplication d'une ORG_VARIANT → création liée au même parent MASTER
    """
    try:
        if not current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Utilisateur sans tenant associé"
            )

        tenant_id = str(current_user.tenant_id)
        org_id = _get_user_org_id(db, current_user)

        if not org_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Organisation non trouvée pour cet utilisateur"
            )

        # Vérifier si les colonnes client existent (migration appliquée ou non)
        check_columns = text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'questionnaire' AND column_name = 'owner_org_id'
        """)
        has_client_columns = db.execute(check_columns).fetchone() is not None

        if not has_client_columns:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="La fonctionnalité de duplication n'est pas encore disponible. Migration de base de données requise."
            )

        # Vérifier l'accès au questionnaire source
        source_query = text("""
            SELECT q.id, q.name, q.status, q.source_type, q.ai_model,
                   q.framework_id, q.parent_questionnaire_id, q.owner_org_id
            FROM questionnaire q
            LEFT JOIN organization_questionnaire_activation oqa ON q.id = oqa.questionnaire_id
            LEFT JOIN organization org ON oqa.org_id = org.id
            WHERE q.id = CAST(:qid AS uuid)
            AND (
                (oqa.active = true AND org.tenant_id::text = :tenant_id)
                OR
                (q.owner_org_id IS NOT NULL AND q.owner_org_id::text = :org_id)
            )
            LIMIT 1
        """)

        source = db.execute(source_query, {
            "qid": source_questionnaire_id,
            "tenant_id": tenant_id,
            "org_id": org_id
        }).fetchone()

        if not source:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Questionnaire source introuvable ou non accessible"
            )

        # Déterminer le parent_questionnaire_id
        # Si c'est un MASTER → le parent est le MASTER lui-même
        # Si c'est une ORG_VARIANT → le parent est le même que celui de la source
        if source.parent_questionnaire_id:
            parent_id = str(source.parent_questionnaire_id)
        else:
            parent_id = str(source.id)

        # Générer le nouveau nom
        if not new_name:
            new_name = f"{source.name} (Copie)"

        # Créer le nouveau questionnaire
        new_id = str(uuid_lib.uuid4())
        insert_query = text("""
            INSERT INTO questionnaire (
                id, name, status, source_type, ai_model, framework_id,
                parent_questionnaire_id, owner_org_id, created_at
            ) VALUES (
                CAST(:id AS uuid),
                :name,
                'draft',
                'ORG_VARIANT',
                :ai_model,
                CAST(:framework_id AS uuid),
                CAST(:parent_id AS uuid),
                CAST(:org_id AS uuid),
                NOW()
            )
            RETURNING id
        """)

        db.execute(insert_query, {
            "id": new_id,
            "name": new_name,
            "ai_model": source.ai_model,
            "framework_id": str(source.framework_id) if source.framework_id else None,
            "parent_id": parent_id,
            "org_id": org_id
        })

        # Dupliquer les questions
        copy_questions_query = text("""
            INSERT INTO question (
                id, questionnaire_id, question_text, response_type, is_required,
                help_text, sort_order, ai_generated, status, requirement_id,
                control_point_id, framework_id, estimated_time_minutes
            )
            SELECT
                uuid_generate_v4(),
                CAST(:new_qid AS uuid),
                question_text,
                response_type,
                is_required,
                help_text,
                sort_order,
                ai_generated,
                'draft',
                requirement_id,
                control_point_id,
                framework_id,
                estimated_time_minutes
            FROM question
            WHERE questionnaire_id = CAST(:source_qid AS uuid)
        """)

        db.execute(copy_questions_query, {
            "new_qid": new_id,
            "source_qid": source_questionnaire_id
        })

        # Activer le questionnaire pour l'organisation
        activate_query = text("""
            INSERT INTO organization_questionnaire_activation (
                id, org_id, questionnaire_id, active, inherit_to_children, created_at
            ) VALUES (
                uuid_generate_v4(),
                CAST(:org_id AS uuid),
                CAST(:qid AS uuid),
                true,
                false,
                NOW()
            )
            ON CONFLICT (org_id, questionnaire_id) DO UPDATE SET active = true
        """)

        db.execute(activate_query, {"org_id": org_id, "qid": new_id})

        db.commit()

        logger.info(f"✅ Questionnaire dupliqué: {source.name} → {new_name} (ID: {new_id})")

        return {
            "id": new_id,
            "name": new_name,
            "source_type": "ORG_VARIANT",
            "parent_questionnaire_id": parent_id,
            "owner_org_id": org_id,
            "message": "Questionnaire dupliqué avec succès"
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Erreur duplicate_questionnaire")
        raise HTTPException(status_code=500, detail=f"Erreur lors de la duplication: {str(e)}") from e


# ==========================================
# DELETE /client/questionnaires/{id}
# ==========================================
@router.delete("/{questionnaire_id}", status_code=status.HTTP_200_OK)
async def delete_client_questionnaire(
    questionnaire_id: str,
    current_user: User = Depends(require_permission("QUESTIONNAIRE_DELETE")),
    db: Session = Depends(get_db),
):
    """
    Supprime un questionnaire ORG_VARIANT appartenant au client.

    Règles:
    - Seuls les ORG_VARIANT peuvent être supprimés
    - Le questionnaire doit appartenir à l'organisation du client
    - Le questionnaire ne doit pas être utilisé dans un audit actif
    """
    try:
        if not current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Utilisateur sans tenant associé"
            )

        org_id = _get_user_org_id(db, current_user)

        if not org_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Organisation non trouvée pour cet utilisateur"
            )

        # Vérifier si les colonnes client existent (migration appliquée ou non)
        check_columns = text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'questionnaire' AND column_name = 'owner_org_id'
        """)
        has_client_columns = db.execute(check_columns).fetchone() is not None

        if not has_client_columns:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="La fonctionnalité de suppression n'est pas encore disponible. Migration de base de données requise."
            )

        # Vérifier que le questionnaire existe et appartient au client
        check_query = text("""
            SELECT id, name, source_type, owner_org_id
            FROM questionnaire
            WHERE id = CAST(:qid AS uuid)
        """)

        questionnaire = db.execute(check_query, {"qid": questionnaire_id}).fetchone()

        if not questionnaire:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Questionnaire introuvable"
            )

        # Vérifier que c'est une ORG_VARIANT appartenant au client
        if questionnaire.source_type != 'ORG_VARIANT':
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Seules les copies de questionnaires peuvent être supprimées"
            )

        if str(questionnaire.owner_org_id) != org_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Ce questionnaire n'appartient pas à votre organisation"
            )

        # Vérifier que le questionnaire n'est pas utilisé dans un audit
        audit_check = text("""
            SELECT COUNT(*) as count
            FROM audit
            WHERE questionnaire_id = CAST(:qid AS uuid)
        """)

        audit_result = db.execute(audit_check, {"qid": questionnaire_id}).fetchone()

        if audit_result and audit_result.count > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Ce questionnaire est utilisé dans {audit_result.count} audit(s). Suppression impossible."
            )

        # Supprimer l'activation
        db.execute(text("""
            DELETE FROM organization_questionnaire_activation
            WHERE questionnaire_id = CAST(:qid AS uuid)
        """), {"qid": questionnaire_id})

        # Supprimer les questions
        db.execute(text("""
            DELETE FROM question
            WHERE questionnaire_id = CAST(:qid AS uuid)
        """), {"qid": questionnaire_id})

        # Supprimer le questionnaire
        db.execute(text("""
            DELETE FROM questionnaire
            WHERE id = CAST(:qid AS uuid)
        """), {"qid": questionnaire_id})

        db.commit()

        logger.info(f"✅ Questionnaire supprimé: {questionnaire.name} (ID: {questionnaire_id})")

        return {
            "message": "Questionnaire supprimé avec succès",
            "deleted_id": questionnaire_id
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Erreur delete_client_questionnaire")
        raise HTTPException(status_code=500, detail=f"Erreur lors de la suppression: {str(e)}") from e
