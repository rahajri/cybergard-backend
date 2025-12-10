"""
API endpoints pour la gestion de la collaboration (contributeurs et mentions)
"""
from fastapi import APIRouter, Depends, HTTPException, status as http_status
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional
from uuid import UUID
import re
import logging

from src.database import get_db
from src.dependencies_keycloak import get_current_user_keycloak
from src.models.audit import AuditCollaborator, QuestionComment, CommentMention
from src.services.magic_link_service import generate_magic_link
from src.services.email_service import send_contributor_mention_email, send_magic_link_email
from src.schemas.collaboration import (
    CollaboratorAdd,
    CollaboratorCreate,
    CollaboratorResponse,
    CommentCreate,
    CommentUpdate,
    CommentResponse,
    MentionResponse,
    UnreadMentionsResponse
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/collaboration", tags=["Collaboration"])


# ============================================================================
# GESTION DES CONTRIBUTEURS
# ============================================================================

@router.post("/audits/{audit_id}/collaborators/create", response_model=CollaboratorResponse, status_code=http_status.HTTP_201_CREATED)
async def create_and_add_collaborator(
    audit_id: UUID,
    collaborator_data: CollaboratorCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_keycloak)
):
    """
    Crée un nouveau contributeur (AUDITE_CONTRIB) et l'ajoute à l'audit.
    Seul un AUDITE_RESP peut créer des contributeurs.
    Le Magic Link sera envoyé uniquement lors de la première mention.
    """
    try:
        # Support both dict and User object
        user_email = current_user.get("email") if isinstance(current_user, dict) else current_user.email


        # Pour les utilisateurs Magic Link, l'email est temporaire (audite-xxx@temp.cybergard.local)
        # Il faut retrouver le vrai email via le hash dans audit_tokens
        if user_email and user_email.endswith("@temp.cybergard.local"):
            # Extraire le campaign_id et le hash de l'email temporaire
            # Format: audite-{campaign_id}-{hash}@temp.cybergard.local
            username = user_email.split("@")[0]
            parts = username.split("-")
            # Les parties 1-5 forment l'UUID du campaign_id, la dernière partie est le hash
            if len(parts) >= 6:
                campaign_id_from_email = "-".join(parts[1:-1])  # UUID complet
                email_hash = parts[-1]  # Hash de 8 caractères

                logger.debug(f"🔗 Détection Magic Link - campaign_id: {campaign_id_from_email}, hash: {email_hash}")

                # Récupérer tous les emails de la campagne
                real_email_query = text("""
                    SELECT user_email
                    FROM audit_tokens
                    WHERE campaign_id = :campaign_id
                      AND revoked = false
                """)
                all_emails = db.execute(real_email_query, {"campaign_id": campaign_id_from_email}).fetchall()

                # Trouver l'email dont le hash correspond
                import hashlib
                real_email = user_email  # Par défaut
                for row in all_emails:
                    candidate_email = row.user_email
                    candidate_hash = hashlib.sha256(candidate_email.encode()).hexdigest()[:8]
                    if candidate_hash == email_hash:
                        real_email = candidate_email
                        logger.info(f"✅ Vrai email récupéré via hash matching: {real_email}")
                        break
                else:
                    logger.warning(f"⚠️ Impossible de trouver le vrai email pour le hash: {email_hash}")

                # Récupérer les infos du membre avec le vrai email
                current_member_query = text("""
                    SELECT id, roles, entity_id, email FROM entity_member
                    WHERE email = :email
                    LIMIT 1
                """)
                current_member = db.execute(current_member_query, {"email": real_email}).fetchone()
            else:
                logger.warning(f"⚠️ Format d'email Magic Link invalide: {user_email}")
                current_member = None
        else:
            # Récupérer l'ID et l'entity_id de l'utilisateur connecté
            current_member_query = text("""
                SELECT id, roles, entity_id, email FROM entity_member
                WHERE email = :email
                LIMIT 1
            """)
            current_member = db.execute(current_member_query, {"email": user_email}).fetchone()

        if not current_member:
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="Utilisateur non trouvé dans entity_member"
            )

        # Vérifier que l'utilisateur est AUDITE_RESP (roles est un JSONB array)
        import json
        user_roles = json.loads(current_member.roles) if isinstance(current_member.roles, str) else current_member.roles
        # Normaliser en minuscules pour la comparaison
        user_roles_lower = [role.lower() if isinstance(role, str) else role for role in user_roles]
        if not any(role in ['audite_resp', 'admin', 'super_admin'] for role in user_roles_lower):
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="Seul un AUDITE_RESP peut créer des contributeurs"
            )

        # Vérifier si l'email existe déjà
        existing_query = text("""
            SELECT id FROM entity_member
            WHERE email = :email
            LIMIT 1
        """)
        existing = db.execute(existing_query, {"email": collaborator_data.email}).fetchone()

        if existing:
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="Un utilisateur avec cet email existe déjà"
            )

        # Créer le contributeur dans entity_member
        insert_member_query = text("""
            INSERT INTO entity_member (
                entity_id, first_name, last_name, email, phone, roles, is_active, created_at, updated_at
            )
            VALUES (
                :entity_id, :first_name, :last_name, :email, :phone, '["audite_contrib"]'::jsonb, true, NOW(), NOW()
            )
            RETURNING id, entity_id, first_name, last_name, email, phone, roles
        """)

        member_result = db.execute(insert_member_query, {
            "entity_id": str(current_member.entity_id),
            "first_name": collaborator_data.first_name,
            "last_name": collaborator_data.last_name,
            "email": collaborator_data.email,
            "phone": collaborator_data.phone
        }).fetchone()

        # Ajouter le contributeur à l'audit
        insert_collaborator_query = text("""
            INSERT INTO audit_collaborator (audit_id, invited_by, collaborator_id, invited_at, is_active)
            VALUES (:audit_id, :invited_by, :collaborator_id, NOW(), true)
            RETURNING id, audit_id, invited_by, collaborator_id, invited_at, is_active
        """)

        collab_result = db.execute(insert_collaborator_query, {
            "audit_id": str(audit_id),
            "invited_by": str(current_member.id),
            "collaborator_id": str(member_result.id)
        }).fetchone()

        db.commit()

        logger.info(f"✅ Contributeur {collaborator_data.email} créé et ajouté à l'audit {audit_id} par {user_email}")

        # 🔔 ENVOYER LE MAGIC LINK AU CONTRIBUTEUR
        try:
            # Récupérer les informations de la campagne depuis l'audit
            campaign_info_query = text("""
                SELECT c.id, c.title, c.questionnaire_id, c.tenant_id
                FROM audit a
                JOIN campaign c ON a.name LIKE CONCAT('%', c.title, '%')
                WHERE a.id = :audit_id
                LIMIT 1
            """)
            campaign_info = db.execute(campaign_info_query, {"audit_id": str(audit_id)}).fetchone()

            if campaign_info:
                # Générer ou récupérer le magic link pour ce contributeur
                from src.services.magic_link_service import generate_magic_link
                magic_link, _ = generate_magic_link(
                    db=db,
                    user_email=member_result.email,
                    campaign_id=campaign_info.id,
                    questionnaire_id=campaign_info.questionnaire_id,
                    tenant_id=campaign_info.tenant_id
                )

                # Récupérer le nom de l'entité
                entity_query = text("""
                    SELECT ee.name
                    FROM ecosystem_entity ee
                    WHERE ee.id = :entity_id
                """)
                entity_result = db.execute(entity_query, {"entity_id": str(member_result.entity_id)}).fetchone()
                entity_name = entity_result.name if entity_result else "Votre organisation"

                # Récupérer le nom du tenant (organisation)
                tenant_query = text("SELECT name FROM tenant WHERE id = :tenant_id")
                tenant_result = db.execute(tenant_query, {"tenant_id": str(campaign_info.tenant_id)}).fetchone()
                organization_name = tenant_result.name if tenant_result else "CYBERGARD AI"

                # Envoyer l'email avec le magic link
                send_magic_link_email(
                    to_email=member_result.email,
                    user_name=f"{member_result.first_name} {member_result.last_name}",
                    magic_link=magic_link,
                    campaign_name=campaign_info.title,
                    entity_name=entity_name,
                    organization_name=organization_name
                )
                logger.info(f"📧 Email magic link envoyé à {member_result.email}")
            else:
                logger.warning(f"⚠️ Campagne introuvable pour l'audit {audit_id}, email non envoyé")

        except Exception as email_error:
            # Ne pas bloquer l'ajout du contributeur si l'email échoue
            logger.error(f"❌ Erreur envoi email à {member_result.email}: {email_error}")

        # Extraire le premier rôle du JSONB array pour la réponse
        import json
        member_roles = json.loads(member_result.roles) if isinstance(member_result.roles, str) else member_result.roles
        first_role = member_roles[0] if member_roles else None

        return CollaboratorResponse(
            id=collab_result.id,
            audit_id=collab_result.audit_id,
            invited_by=collab_result.invited_by,
            collaborator_id=collab_result.collaborator_id,
            invited_at=collab_result.invited_at,
            is_active=collab_result.is_active,
            first_name=member_result.first_name,
            last_name=member_result.last_name,
            email=member_result.email,
            role=first_role
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur lors de la création du contributeur: {e}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la création du contributeur: {str(e)}"
        )


@router.post("/audits/{audit_id}/collaborators", response_model=CollaboratorResponse, status_code=http_status.HTTP_201_CREATED)
async def add_collaborator(
    audit_id: UUID,
    collaborator_data: CollaboratorAdd,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_keycloak)
):
    """
    Ajoute un contributeur (AUDITE_CONTRIB) à un audit.
    Seul un AUDITE_RESP peut ajouter des contributeurs.
    """
    try:
        # Support both dict and User object
        user_email = current_user.get("email") if isinstance(current_user, dict) else current_user.email

        # Récupérer l'ID de l'utilisateur connecté depuis entity_member
        current_member_query = text("""
            SELECT id, roles FROM entity_member
            WHERE email = :email
            LIMIT 1
        """)
        current_member = db.execute(current_member_query, {"email": user_email}).fetchone()

        if not current_member:
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="Utilisateur non trouvé dans entity_member"
            )

        # Vérifier que l'utilisateur est AUDITE_RESP (roles est un JSONB array)
        import json
        current_user_roles = json.loads(current_member.roles) if isinstance(current_member.roles, str) else current_member.roles
        # Normaliser en minuscules pour la comparaison
        current_user_roles_lower = [role.lower() if isinstance(role, str) else role for role in current_user_roles]
        if not any(role in ['audite_resp', 'admin', 'super_admin'] for role in current_user_roles_lower):
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="Seul un AUDITE_RESP peut ajouter des contributeurs"
            )

        # Vérifier que le contributeur existe et a le rôle AUDITE_CONTRIB
        collaborator_query = text("""
            SELECT id, roles, first_name, last_name, email
            FROM entity_member
            WHERE id = :collaborator_id
        """)
        collaborator = db.execute(collaborator_query, {"collaborator_id": str(collaborator_data.collaborator_id)}).fetchone()

        if not collaborator:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Contributeur non trouvé"
            )

        # Vérifier que le contributeur a le rôle AUDITE_CONTRIB (roles est un JSONB array)
        import json
        collab_roles = json.loads(collaborator.roles) if isinstance(collaborator.roles, str) else collaborator.roles
        # Normaliser en minuscules pour la comparaison
        collab_roles_lower = [role.lower() if isinstance(role, str) else role for role in collab_roles]
        if 'audite_contrib' not in collab_roles_lower:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="L'utilisateur doit avoir le rôle AUDITE_CONTRIB"
            )

        # Vérifier si le contributeur n'est pas déjà ajouté
        existing_query = text("""
            SELECT id FROM audit_collaborator
            WHERE audit_id = :audit_id
              AND collaborator_id = :collaborator_id
              AND is_active = true
        """)
        existing = db.execute(existing_query, {
            "audit_id": str(audit_id),
            "collaborator_id": str(collaborator_data.collaborator_id)
        }).fetchone()

        if existing:
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="Ce contributeur est déjà ajouté à cet audit"
            )

        # Ajouter le contributeur
        insert_query = text("""
            INSERT INTO audit_collaborator (audit_id, invited_by, collaborator_id, invited_at, is_active)
            VALUES (:audit_id, :invited_by, :collaborator_id, NOW(), true)
            RETURNING id, audit_id, invited_by, collaborator_id, invited_at, is_active
        """)

        result = db.execute(insert_query, {
            "audit_id": str(audit_id),
            "invited_by": str(current_member.id),
            "collaborator_id": str(collaborator_data.collaborator_id)
        }).fetchone()

        db.commit()

        logger.info(f"✅ Contributeur {collaborator.email} ajouté à l'audit {audit_id} par {user_email}")

        # 🔔 ENVOYER LE MAGIC LINK AU CONTRIBUTEUR
        try:
            # Récupérer les informations de la campagne et de l'entité
            campaign_info_query = text("""
                SELECT c.id, c.title, c.questionnaire_id, c.tenant_id
                FROM audit a
                JOIN campaign c ON a.name LIKE CONCAT('%', c.title, '%')
                WHERE a.id = :audit_id
                LIMIT 1
            """)
            campaign_info = db.execute(campaign_info_query, {"audit_id": str(audit_id)}).fetchone()

            if campaign_info:
                # Générer ou récupérer le magic link pour ce contributeur
                magic_link, _ = generate_magic_link(
                    db=db,
                    user_email=collaborator.email,
                    campaign_id=campaign_info.id,
                    questionnaire_id=campaign_info.questionnaire_id,
                    tenant_id=campaign_info.tenant_id
                )

                # Récupérer le nom de l'entité
                entity_query = text("""
                    SELECT ee.name
                    FROM entity_member em
                    JOIN ecosystem_entity ee ON em.entity_id = ee.id
                    WHERE em.id = :member_id
                """)
                entity_result = db.execute(entity_query, {"member_id": str(collaborator_data.collaborator_id)}).fetchone()
                entity_name = entity_result.name if entity_result else "Votre organisation"

                # Récupérer le nom du tenant (organisation)
                tenant_query = text("SELECT name FROM tenant WHERE id = :tenant_id")
                tenant_result = db.execute(tenant_query, {"tenant_id": str(campaign_info.tenant_id)}).fetchone()
                organization_name = tenant_result.name if tenant_result else "CYBERGARD AI"

                # Envoyer l'email avec le magic link
                send_magic_link_email(
                    to_email=collaborator.email,
                    user_name=f"{collaborator.first_name} {collaborator.last_name}",
                    magic_link=magic_link,
                    campaign_name=campaign_info.title,
                    entity_name=entity_name,
                    organization_name=organization_name
                )
                logger.info(f"📧 Email magic link envoyé à {collaborator.email}")
            else:
                logger.warning(f"⚠️ Campagne introuvable pour l'audit {audit_id}, email non envoyé")

        except Exception as email_error:
            # Ne pas bloquer l'ajout du contributeur si l'email échoue
            logger.error(f"❌ Erreur envoi email à {collaborator.email}: {email_error}")

        # Extraire le premier rôle du JSONB array pour la réponse
        import json
        collab_roles_list = json.loads(collaborator.roles) if isinstance(collaborator.roles, str) else collaborator.roles
        first_collab_role = collab_roles_list[0] if collab_roles_list else None

        return CollaboratorResponse(
            id=result.id,
            audit_id=result.audit_id,
            invited_by=result.invited_by,
            collaborator_id=result.collaborator_id,
            invited_at=result.invited_at,
            is_active=result.is_active,
            first_name=collaborator.first_name,
            last_name=collaborator.last_name,
            email=collaborator.email,
            role=first_collab_role
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur lors de l'ajout du contributeur: {e}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de l'ajout du contributeur: {str(e)}"
        )


@router.get("/audits/{audit_id}/collaborators", response_model=List[CollaboratorResponse])
async def list_collaborators(
    audit_id: UUID,
    question_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_keycloak)
):
    """
    Liste toutes les personnes tagables pour les @mentions:
    - AUDITE_RESP (responsables d'audit de l'entité)
    - AUDITE_CONTRIB (contributeurs de l'entité)
    - AUDITEUR (auditeur de la campagne)

    Pour les auditeurs: si question_id est fourni, filtre par domaine de la question
    """
    try:
        # Support both dict and User object
        user_email = current_user.get("email") if isinstance(current_user, dict) else current_user.email

        # Resoudre l'email reel pour les utilisateurs Magic Link
        real_email = user_email
        campaign_id_from_email = None
        if real_email and real_email.endswith('@temp.cybergard.local'):
            username = real_email.split('@')[0]
            parts = username.split('-')
            if len(parts) >= 6:
                campaign_id_from_email = '-'.join(parts[1:-1])
                email_hash = parts[-1]
                real_email_query = text("""
                    SELECT user_email
                    FROM audit_tokens
                    WHERE campaign_id = :campaign_id
                      AND revoked = false
                """)
                all_emails = db.execute(real_email_query, {"campaign_id": campaign_id_from_email}).fetchall()
                import hashlib
                for row in all_emails:
                    candidate_email = row.user_email
                    candidate_hash = hashlib.sha256(candidate_email.encode()).hexdigest()[:8]
                    if candidate_hash == email_hash:
                        real_email = candidate_email
                        break
                else:
                    logger.warning(f"[mentions] Email reel introuvable pour {user_email}")
            else:
                logger.warning(f"[mentions] Format email Magic Link invalide: {user_email}")

        # Récupérer l'utilisateur connecté (entity_member OU users/auditeur)
        # IMPORTANT: Si Magic Link, vérifier d'abord si c'est un auditeur de la campagne
        current_member = None
        is_auditor = False

        if campaign_id_from_email:
            # Vérifier si c'est un auditeur de cette campagne
            auditor_check = text("""
                SELECT u.id, NULL as entity_id, NULL as roles, 'auditor' as user_type
                FROM users u
                JOIN campaign_user cu ON u.id = cu.user_id
                WHERE u.email = :email
                  AND cu.campaign_id = :campaign_id
                  AND cu.role = 'auditor'
                  AND cu.is_active = true
                LIMIT 1
            """)
            current_member = db.execute(auditor_check, {
                "email": real_email,
                "campaign_id": campaign_id_from_email
            }).fetchone()

            if current_member:
                is_auditor = True
                logger.info(f"👤 Utilisateur identifié comme AUDITEUR pour collaborators: {real_email}")

        # Si pas auditeur, chercher dans entity_member
        if not current_member:
            current_member_query = text("""
                SELECT id, entity_id, roles, 'entity_member' as user_type
                FROM entity_member
                WHERE email = :email
                LIMIT 1
            """)
            current_member = db.execute(current_member_query, {"email": real_email}).fetchone()

        # Si toujours pas trouvé, chercher dans users (auditeurs sans contexte de campagne)
        if not current_member:
            auditor_query = text("""
                SELECT id, NULL as entity_id, NULL as roles, 'auditor' as user_type
                FROM users
                WHERE email = :email
                LIMIT 1
            """)
            current_member = db.execute(auditor_query, {"email": real_email}).fetchone()
            is_auditor = True

        if not current_member:
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="Utilisateur non trouvé"
            )

        entity_id = current_member.entity_id if not is_auditor else None
        current_member_id = current_member.id

        # Récupérer l'audit
        audit_info_query = text("""
            SELECT a.id, a.name
            FROM audit a
            WHERE a.id = :audit_id
        """)
        audit_info = db.execute(audit_info_query, {"audit_id": str(audit_id)}).fetchone()

        if not audit_info:
            logger.warning(f"⚠️ Audit {audit_id} introuvable")
            return []

        # Extraire le titre de campagne depuis le nom de l'audit (format: "Audit - Campaign Title - Entity")
        audit_name_parts = audit_info.name.split(" - ")
        if len(audit_name_parts) < 2:
            logger.warning(f"⚠️ Format de nom d'audit invalide: {audit_info.name}")
            return []

        campaign_title = audit_name_parts[1].strip()

        # Récupérer le campaign_id depuis la table campaign
        campaign_query = text("""
            SELECT id, title FROM campaign WHERE title = :title LIMIT 1
        """)
        campaign_result = db.execute(campaign_query, {"title": campaign_title}).fetchone()

        if not campaign_result:
            logger.warning(f"⚠️ Campaign introuvable pour le titre: {campaign_title}")
            return []

        campaign_id = campaign_result.id

        # Si l'utilisateur est un auditeur, retourner les acteurs filtrés par domaine
        if is_auditor:
            # Récupérer TOUTES les entités du scope de la campagne
            entities_query = text("""
                SELECT cs.entity_ids
                FROM audit a
                JOIN campaign c ON a.name LIKE CONCAT('%', c.title, '%')
                JOIN campaign_scope cs ON cs.id = c.scope_id
                WHERE a.id = :audit_id
                LIMIT 1
            """)
            entities_result = db.execute(entities_query, {"audit_id": str(audit_id)}).fetchone()

            if not entities_result or not entities_result.entity_ids:
                logger.warning(f"⚠️ Impossible de déterminer les entités pour l'audit {audit_id}")
                return []

            # Convertir les UUIDs en strings pour la requête SQL
            entity_ids = [str(eid) for eid in entities_result.entity_ids]
            logger.info(f"👤 Auditeur - {len(entity_ids)} entité(s) dans le scope")

            # Si question_id fourni, récupérer le domaine de la question via requirement
            question_domain_id = None
            if question_id:
                question_domain_query = text("""
                    SELECT r.domain_id
                    FROM question q
                    JOIN requirement r ON q.requirement_id = r.id
                    WHERE q.id = :question_id
                    LIMIT 1
                """)
                question_domain = db.execute(question_domain_query, {"question_id": str(question_id)}).fetchone()
                if question_domain and question_domain.domain_id:
                    question_domain_id = question_domain.domain_id
                    logger.info(f"👤 Auditeur - Filtrage par domaine de la question: {question_domain_id}")
                else:
                    logger.warning(f"⚠️ Domaine non trouvé pour question {question_id}")
            else:
                logger.info(f"👤 Auditeur - Pas de question_id, affichage de tous les acteurs")

            # Récupérer les entity_members filtrés par domaine
            if question_domain_id:
                # Filtrer: contributeurs transverses + responsables du domaine de la question
                contributors_query = text("""
                    SELECT DISTINCT
                        em.id as collaborator_id,
                        em.first_name,
                        em.last_name,
                        em.email,
                        em.roles
                    FROM entity_member em
                    LEFT JOIN audite_domain_scope ads ON ads.entity_member_id = em.id
                        AND ads.campaign_id = :campaign_id
                    WHERE em.entity_id = ANY(CAST(:entity_ids AS uuid[]))
                      AND em.is_active = true
                      AND (
                          em.roles::jsonb ? 'audite_contrib'
                          OR (
                              em.roles::jsonb ? 'audite_resp'
                              AND ads.domain_ids IS NOT NULL
                              AND CAST(:domain_id AS uuid) = ANY(CAST(ads.domain_ids AS uuid[]))
                          )
                      )
                    ORDER BY em.last_name, em.first_name
                """)

                contributors = db.execute(contributors_query, {
                    "entity_ids": entity_ids,
                    "campaign_id": str(campaign_id),
                    "domain_id": str(question_domain_id)
                }).fetchall()
            else:
                # Pas de filtrage par domaine : tous les acteurs
                contributors_query = text("""
                    SELECT DISTINCT
                        em.id as collaborator_id,
                        em.first_name,
                        em.last_name,
                        em.email,
                        em.roles
                    FROM entity_member em
                    WHERE em.entity_id = ANY(CAST(:entity_ids AS uuid[]))
                      AND em.is_active = true
                      AND (em.roles::jsonb ? 'audite_contrib' OR em.roles::jsonb ? 'audite_resp')
                    ORDER BY em.last_name, em.first_name
                """)

                contributors = db.execute(contributors_query, {
                    "entity_ids": entity_ids
                }).fetchall()

            import json
            collaborators = []
            for row in contributors:
                row_roles = json.loads(row.roles) if isinstance(row.roles, str) else row.roles
                row_first_role = row_roles[0] if row_roles else None

                collaborators.append(CollaboratorResponse(
                    id=row.collaborator_id,
                    audit_id=None,
                    invited_by=None,
                    collaborator_id=row.collaborator_id,
                    invited_at=None,
                    is_active=True,
                    first_name=row.first_name,
                    last_name=row.last_name,
                    email=row.email,
                    role=row_first_role
                ))

            logger.info(f"✅ {len(collaborators)} contributeur(s) tagable(s) par l'auditeur")
            return collaborators

        # Recuperer le nom de l'entite de l'utilisateur courant
        entity_name_query = text("""
            SELECT name FROM ecosystem_entity
            WHERE id = :entity_id
            LIMIT 1
        """)
        entity_result = db.execute(entity_name_query, {"entity_id": str(entity_id)}).fetchone()

        if not entity_result:
            logger.warning(f"?? Entit? introuvable pour l'utilisateur {user_email}")
            return []

        entity_name_from_user = entity_result.name
        logger.info(f"?? R?cup?ration des personnes tagables - Entit?: {entity_name_from_user}, Campagne: {campaign_title}")

        # RÈGLE: Un utilisateur voit dans la liste @mention:
        # - Tous les AUDITE_CONTRIB de son entité (trans-scope)
        # - Les AUDITE_RESP de son entité qui partagent au moins un domaine
        # - L'auditeur de la campagne
        # - MAIS PAS lui-même

        # Récupérer les domaines de l'utilisateur connecté depuis audite_domain_scope
        user_domains_query = text("""
            SELECT domain_ids
            FROM audite_domain_scope
            WHERE campaign_id = :campaign_id
              AND entity_member_id = :entity_member_id
            LIMIT 1
        """)
        user_domains_result = db.execute(user_domains_query, {
            "campaign_id": str(campaign_id),
            "entity_member_id": str(current_member_id)
        }).fetchone()

        user_domain_ids = user_domains_result.domain_ids if user_domains_result else []
        logger.info(f"🎯 Domaines de l'utilisateur connecté: {user_domain_ids}")

        # Convertir les UUID en strings pour la comparaison SQL
        user_domain_ids_str = [str(domain_id) for domain_id in user_domain_ids]

        # RÈGLE FINALE:
        # 1. Toujours afficher l'auditeur (déjà géré après)
        # 2. Afficher les personnes qui m'ont tagué
        # 3. Afficher les personnes qui partagent au moins un domaine avec moi (si j'ai des domaines)

        if not user_domain_ids_str:
            # Pas de domaines : afficher uniquement ceux qui m'ont tagué
            logger.info(f"👤 L'utilisateur {current_member_id} n'a pas de domaines, affichage des personnes qui l'ont tagué")
            entity_members_query = text("""
                SELECT DISTINCT
                    em.id as collaborator_id,
                    em.first_name, em.last_name, em.email, em.roles,
                    COALESCE(ac.id, NULL) as id,
                    COALESCE(ac.audit_id, NULL) as audit_id,
                    COALESCE(ac.invited_by, NULL) as invited_by,
                    COALESCE(ac.invited_at, NOW()) as invited_at,
                    COALESCE(ac.is_active, true) as is_active,
                    ads.domain_ids
                FROM entity_member em
                LEFT JOIN audit_collaborator ac ON ac.collaborator_id = em.id
                    AND ac.audit_id = :audit_id
                    AND ac.is_active = true
                LEFT JOIN audite_domain_scope ads ON ads.entity_member_id = em.id
                    AND ads.campaign_id = :campaign_id
                WHERE em.entity_id = :entity_id
                  AND em.is_active = true
                  AND em.id != :current_member_id
                  AND (em.roles::jsonb ? 'audite_contrib' OR em.roles::jsonb ? 'audite_resp')
                  AND em.id IN (
                      SELECT qc.author_id
                      FROM question_comment qc
                      JOIN comment_mention cm ON cm.comment_id = qc.id
                      WHERE cm.mentioned_user_id = :current_member_id
                        AND qc.audit_id = :audit_id
                        AND qc.is_deleted = false
                  )
                ORDER BY em.last_name, em.first_name
            """)

            entity_members = db.execute(entity_members_query, {
                "audit_id": str(audit_id),
                "campaign_id": str(campaign_id),
                "entity_id": str(entity_id),
                "current_member_id": str(current_member_id)
            }).fetchall()
        else:
            # A des domaines : afficher ceux qui partagent au moins un domaine OU qui m'ont tagué
            # IMPORTANT: Les AUDITE_CONTRIB sont toujours visibles (transverses)
            entity_members_query = text("""
                SELECT DISTINCT
                    em.id as collaborator_id,
                    em.first_name, em.last_name, em.email, em.roles,
                    COALESCE(ac.id, NULL) as id,
                    COALESCE(ac.audit_id, NULL) as audit_id,
                    COALESCE(ac.invited_by, NULL) as invited_by,
                    COALESCE(ac.invited_at, NOW()) as invited_at,
                    COALESCE(ac.is_active, true) as is_active,
                    ads.domain_ids
                FROM entity_member em
                LEFT JOIN audit_collaborator ac ON ac.collaborator_id = em.id
                    AND ac.audit_id = :audit_id
                    AND ac.is_active = true
                LEFT JOIN audite_domain_scope ads ON ads.entity_member_id = em.id
                    AND ads.campaign_id = :campaign_id
                WHERE em.entity_id = :entity_id
                  AND em.is_active = true
                  AND em.id != :current_member_id
                  AND (em.roles::jsonb ? 'audite_contrib' OR em.roles::jsonb ? 'audite_resp')
                  AND (
                      em.roles::jsonb ? 'audite_contrib'
                      OR (ads.domain_ids IS NOT NULL AND ads.domain_ids::text[] && :user_domain_ids)
                      OR em.id IN (
                          SELECT qc.author_id
                          FROM question_comment qc
                          JOIN comment_mention cm ON cm.comment_id = qc.id
                          WHERE cm.mentioned_user_id = :current_member_id
                            AND qc.audit_id = :audit_id
                            AND qc.is_deleted = false
                      )
                  )
                ORDER BY em.last_name, em.first_name
            """)

            entity_members = db.execute(entity_members_query, {
                "audit_id": str(audit_id),
                "campaign_id": str(campaign_id),
                "entity_id": str(entity_id),
                "current_member_id": str(current_member_id),
                "user_domain_ids": user_domain_ids_str
            }).fetchall()

        # Récupérer l'auditeur de la campagne depuis campaign_user (table users)
        # L'auditeur peut taguer et être tagué par toutes les entités de la campagne
        auditor_query = text("""
            SELECT DISTINCT
                u.id as collaborator_id,
                u.first_name,
                u.last_name,
                u.email,
                'auditeur' as role
            FROM campaign c
            JOIN campaign_user cu ON c.id = cu.campaign_id
            JOIN users u ON cu.user_id = u.id
            WHERE c.title = :campaign_title
              AND cu.role = 'auditor'
              AND cu.is_active = true
        """)

        auditors = db.execute(auditor_query, {
            "campaign_title": campaign_title
        }).fetchall()

        import json
        collaborators = []

        # Ajouter les membres de l'entité (AUDITE_RESP + AUDITE_CONTRIB)
        for row in entity_members:
            row_roles = json.loads(row.roles) if isinstance(row.roles, str) else row.roles
            row_first_role = row_roles[0] if row_roles else None

            # Utiliser collaborator_id comme id si l'entrée audit_collaborator n'existe pas encore
            collab_id = row.id if row.id else row.collaborator_id

            collaborators.append(CollaboratorResponse(
                id=collab_id,
                audit_id=row.audit_id if row.audit_id else None,
                invited_by=row.invited_by,
                collaborator_id=row.collaborator_id,
                invited_at=row.invited_at if row.invited_at else None,
                is_active=row.is_active,
                first_name=row.first_name,
                last_name=row.last_name,
                email=row.email,
                role=row_first_role
            ))

        # Ajouter l'auditeur de la campagne (depuis table users via campaign_user)
        for auditor in auditors:
            # Vérifier qu'il n'est pas déjà dans la liste (éviter doublons)
            if not any(c.email == auditor.email for c in collaborators):
                collaborators.append(CollaboratorResponse(
                    id=auditor.collaborator_id,
                    audit_id=None,
                    invited_by=None,
                    collaborator_id=auditor.collaborator_id,
                    invited_at=None,
                    is_active=True,
                    first_name=auditor.first_name,
                    last_name=auditor.last_name,
                    email=auditor.email,
                    role='auditeur'  # Rôle fixe pour l'auditeur de la campagne
                ))

        # Exclure l'utilisateur connecté de la liste (on ne se tag pas soi-même)
        collaborators = [c for c in collaborators if c.email != real_email]

        logger.info(f"✅ {len(collaborators)} personne(s) tagable(s) (AUDITE_RESP + AUDITE_CONTRIB + AUDITEUR)")

        # Log détaillé pour debug
        for c in collaborators:
            logger.info(f"   → {c.first_name} {c.last_name} ({c.email}) - Role: {c.role}")

        return collaborators

    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération des personnes tagables: {e}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération: {str(e)}"
        )


# ============================================================================
# GESTION DES COMMENTAIRES ET MENTIONS
# ============================================================================

def extract_mentions(content: str) -> List[str]:
    """Extrait les mentions @utilisateur d'un contenu"""
    # Pattern pour matcher @prenom.nom ou @email
    pattern = r'@([\w\.\-]+(?:@[\w\.\-]+)?)'
    mentions = re.findall(pattern, content)
    return mentions


@router.post("/comments", response_model=CommentResponse, status_code=http_status.HTTP_201_CREATED)
async def create_comment(
    comment_data: CommentCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_keycloak)
):
    """
    Crée un commentaire sur une question avec support des @mentions
    """
    try:
        # Support both dict and User object
        user_email = current_user.get("email") if isinstance(current_user, dict) else current_user.email

        # Pour les utilisateurs Magic Link, l'email est temporaire (audite-xxx@temp.cybergard.local)
        # Il faut retrouver le vrai email via le hash dans audit_tokens
        if user_email and user_email.endswith("@temp.cybergard.local"):
            # Extraire le campaign_id et le hash de l'email temporaire
            # Format: audite-{campaign_id}-{hash}@temp.cybergard.local
            username = user_email.split("@")[0]
            parts = username.split("-")
            # Les parties 1-5 forment l'UUID du campaign_id, la dernière partie est le hash
            if len(parts) >= 6:
                campaign_id_from_email = "-".join(parts[1:-1])  # UUID complet
                email_hash = parts[-1]  # Hash de 8 caractères

                logger.debug(f"🔗 Détection Magic Link - campaign_id: {campaign_id_from_email}, hash: {email_hash}")

                # Récupérer tous les emails de la campagne
                real_email_query = text("""
                    SELECT user_email
                    FROM audit_tokens
                    WHERE campaign_id = :campaign_id
                      AND revoked = false
                """)
                all_emails = db.execute(real_email_query, {"campaign_id": campaign_id_from_email}).fetchall()

                # Trouver l'email dont le hash correspond
                import hashlib
                real_email = user_email  # Par défaut
                for row in all_emails:
                    candidate_email = row.user_email
                    candidate_hash = hashlib.sha256(candidate_email.encode()).hexdigest()[:8]
                    if candidate_hash == email_hash:
                        real_email = candidate_email
                        logger.info(f"✅ Vrai email récupéré via hash matching: {real_email}")
                        break
                else:
                    logger.warning(f"⚠️ Impossible de trouver le vrai email pour le hash: {email_hash}")
            else:
                logger.warning(f"⚠️ Format d'email Magic Link invalide: {user_email}")
                real_email = user_email

            # Récupérer l'auteur avec le vrai email
            author_query = text("""
                SELECT id, first_name, last_name, email FROM entity_member
                WHERE email = :email
                LIMIT 1
            """)
            author = db.execute(author_query, {"email": real_email}).fetchone()
        else:
            # Récupérer l'ID de l'utilisateur connecté (utilisateur normal)
            author_query = text("""
                SELECT id, first_name, last_name, email FROM entity_member
                WHERE email = :email
                LIMIT 1
            """)
            author = db.execute(author_query, {"email": user_email}).fetchone()

        if not author:
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="Utilisateur non trouvé"
            )

        # Créer le commentaire
        insert_comment_query = text("""
            INSERT INTO question_comment (question_id, audit_id, author_id, content, created_at, updated_at)
            VALUES (:question_id, :audit_id, :author_id, :content, NOW(), NOW())
            RETURNING id, question_id, audit_id, author_id, content, created_at, updated_at, is_deleted
        """)

        comment_result = db.execute(insert_comment_query, {
            "question_id": str(comment_data.question_id),
            "audit_id": str(comment_data.audit_id),
            "author_id": str(author.id),
            "content": comment_data.content
        }).fetchone()

        # Extraire et créer les mentions
        mentions_text = extract_mentions(comment_data.content)
        mention_responses = []

        for mention_text in mentions_text:
            # Trouver l'utilisateur mentionné
            # Chercher d'abord dans entity_member, puis dans users (auditeurs)
            mentioned_user = None

            # Essayer d'abord par email complet
            if '@' in mention_text:
                # Chercher dans entity_member
                mentioned_user_query = text("""
                    SELECT id, first_name, last_name, email FROM entity_member
                    WHERE email = :email
                    LIMIT 1
                """)
                mentioned_user = db.execute(mentioned_user_query, {"email": mention_text}).fetchone()

                # Si pas trouvé, chercher dans users (auditeurs)
                if not mentioned_user:
                    mentioned_user_query = text("""
                        SELECT id, first_name, last_name, email FROM users
                        WHERE email = :email
                        LIMIT 1
                    """)
                    mentioned_user = db.execute(mentioned_user_query, {"email": mention_text}).fetchone()
            else:
                # Sinon chercher par prénom.nom dans entity_member
                mentioned_user_query = text("""
                    SELECT id, first_name, last_name, email FROM entity_member
                    WHERE LOWER(CONCAT(first_name, '.', last_name)) = LOWER(:name)
                    LIMIT 1
                """)
                mentioned_user = db.execute(mentioned_user_query, {"name": mention_text}).fetchone()

                # Si pas trouvé, chercher dans users (auditeurs)
                if not mentioned_user:
                    mentioned_user_query = text("""
                        SELECT id, first_name, last_name, email FROM users
                        WHERE LOWER(CONCAT(first_name, '.', last_name)) = LOWER(:name)
                        LIMIT 1
                    """)
                    mentioned_user = db.execute(mentioned_user_query, {"name": mention_text}).fetchone()

            if mentioned_user:
                # Vérifier si c'est un entity_member ou un user (auditeur)
                is_entity_member = db.execute(text("""
                    SELECT 1 FROM entity_member WHERE id = :user_id LIMIT 1
                """), {"user_id": str(mentioned_user.id)}).fetchone() is not None

                # Créer la mention pour TOUS les utilisateurs (entity_member ET auditeurs)
                mention_result = None
                insert_mention_query = text("""
                    INSERT INTO comment_mention (comment_id, mentioned_user_id, is_read, created_at)
                    VALUES (:comment_id, :mentioned_user_id, false, NOW())
                    ON CONFLICT (comment_id, mentioned_user_id) DO NOTHING
                    RETURNING id, comment_id, mentioned_user_id, is_read, created_at
                """)

                mention_result = db.execute(insert_mention_query, {
                    "comment_id": str(comment_result.id),
                    "mentioned_user_id": str(mentioned_user.id)
                }).fetchone()

                if mention_result:
                    mention_responses.append(MentionResponse(
                        id=mention_result.id,
                        comment_id=mention_result.comment_id,
                        mentioned_user_id=mention_result.mentioned_user_id,
                        is_read=mention_result.is_read,
                        created_at=mention_result.created_at,
                        first_name=mentioned_user.first_name,
                        last_name=mentioned_user.last_name,
                        email=mentioned_user.email
                    ))

                # Envoyer une notification avec Magic Link à tous les utilisateurs mentionnés
                # (entity_member ET auditeurs from users table)
                try:
                    # Récupérer les infos de la campagne, de l'audit et de l'entité
                    # Pour entity_member, récupérer leur entité
                    # Pour users (auditeurs), utiliser l'entité de l'auteur du commentaire
                    if is_entity_member:
                        campaign_query = text("""
                            SELECT c.id, c.title, a.questionnaire_id, c.tenant_id,
                                   ee.name as entity_name, t.name as organization_name,
                                   c.launch_date, c.due_date
                            FROM audit a
                            JOIN campaign c ON a.name LIKE CONCAT('%', c.title, '%')
                            JOIN entity_member em ON em.id = :mentioned_user_id
                            JOIN ecosystem_entity ee ON ee.id = em.entity_id
                            LEFT JOIN tenant t ON t.id = c.tenant_id
                            WHERE a.id = :audit_id
                            ORDER BY c.created_at DESC
                            LIMIT 1
                        """)
                        campaign_info = db.execute(campaign_query, {
                            "audit_id": str(comment_data.audit_id),
                            "mentioned_user_id": str(mentioned_user.id)
                        }).fetchone()
                    else:
                        # Pour les auditeurs, pas d'entité spécifique
                        campaign_query = text("""
                            SELECT c.id, c.title, a.questionnaire_id, c.tenant_id,
                                   'Auditeur' as entity_name, t.name as organization_name,
                                   c.launch_date, c.due_date
                            FROM audit a
                            JOIN campaign c ON a.name LIKE CONCAT('%', c.title, '%')
                            LEFT JOIN tenant t ON t.id = c.tenant_id
                            WHERE a.id = :audit_id
                            ORDER BY c.created_at DESC
                            LIMIT 1
                        """)
                        campaign_info = db.execute(campaign_query, {
                            "audit_id": str(comment_data.audit_id)
                        }).fetchone()

                    if campaign_info:
                        # Pour entity_member: Magic Link (authentification temporaire)
                        # Pour auditeurs: URL normale (authentification Keycloak requise)
                        if is_entity_member:
                            magic_link, _ = generate_magic_link(
                                db=db,
                                user_email=mentioned_user.email,
                                campaign_id=campaign_info.id,
                                questionnaire_id=campaign_info.questionnaire_id,
                                tenant_id=campaign_info.tenant_id,
                                question_id=comment_data.question_id
                            )
                        else:
                            # Pour les auditeurs: URL normale sans Magic Link
                            # Format: /audite/{audit_id}/{questionnaire_id}?question={question_id}
                            frontend_url = "http://localhost:3000"  # TODO: Mettre dans config
                            magic_link = f"{frontend_url}/audite/{comment_data.audit_id}/{campaign_info.questionnaire_id}?question={comment_data.question_id}"
                            logger.info(f"🔗 URL normale générée pour auditeur: {magic_link}")

                        # Envoyer l'email adapté selon le type d'utilisateur
                        if is_entity_member:
                            # Email pour contributeur/resp d'entité
                            send_contributor_mention_email(
                                to_email=mentioned_user.email,
                                user_name=f"{mentioned_user.first_name} {mentioned_user.last_name}",
                                magic_link=magic_link,
                                mentioned_by_name=f"{author.first_name} {author.last_name}",
                                question_text=comment_data.content[:200] + "..." if len(comment_data.content) > 200 else comment_data.content,
                                campaign_name=campaign_info.title,
                                entity_name=campaign_info.entity_name,
                                organization_name=campaign_info.organization_name or "CYBERGARD AI"
                            )
                            logger.info(f"✅ Notification contributeur envoyée à {mentioned_user.email}")
                        else:
                            # Email pour auditeur
                            from src.services.email_service import send_auditor_message_notification_email

                            # Formater les dates si disponibles
                            start_date_str = None
                            end_date_str = None
                            if hasattr(campaign_info, 'launch_date') and campaign_info.launch_date:
                                start_date_str = campaign_info.launch_date.strftime("%d/%m/%Y") if hasattr(campaign_info.launch_date, 'strftime') else str(campaign_info.launch_date)
                            if hasattr(campaign_info, 'due_date') and campaign_info.due_date:
                                end_date_str = campaign_info.due_date.strftime("%d/%m/%Y") if hasattr(campaign_info.due_date, 'strftime') else str(campaign_info.due_date)

                            send_auditor_message_notification_email(
                                to_email=mentioned_user.email,
                                auditor_name=f"{mentioned_user.first_name} {mentioned_user.last_name}",
                                magic_link=magic_link,
                                contributor_name=f"{author.first_name} {author.last_name}",
                                campaign_name=campaign_info.title,
                                client_name=campaign_info.organization_name or "Client",
                                campaign_start_date=start_date_str,
                                campaign_end_date=end_date_str,
                                organization_name="CYBERGARD AI"
                            )
                            logger.info(f"✅ Notification auditeur envoyée à {mentioned_user.email}")
                except Exception as e:
                    logger.error(f"❌ Erreur envoi notification à {mentioned_user.email}: {e}")
                    # Ne pas bloquer la création du commentaire si l'email échoue

        db.commit()

        logger.info(f"✅ Commentaire créé par {user_email} avec {len(mention_responses)} mention(s)")

        return CommentResponse(
            id=comment_result.id,
            question_id=comment_result.question_id,
            audit_id=comment_result.audit_id,
            author_id=comment_result.author_id,
            content=comment_result.content,
            created_at=comment_result.created_at,
            updated_at=comment_result.updated_at,
            is_deleted=comment_result.is_deleted,
            author_first_name=author.first_name,
            author_last_name=author.last_name,
            author_email=author.email,
            mentions=mention_responses
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur lors de la création du commentaire: {e}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la création du commentaire: {str(e)}"
        )


@router.get("/questions/{question_id}/comments", response_model=List[CommentResponse])
async def list_comments(
    question_id: UUID,
    audit_id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_keycloak)
):
    """
    Liste tous les commentaires d'une question pour un audit donné
    """
    try:
        query = text("""
            SELECT
                qc.id, qc.question_id, qc.audit_id, qc.author_id, qc.content,
                qc.created_at, qc.updated_at, qc.is_deleted,
                em.first_name as author_first_name,
                em.last_name as author_last_name,
                em.email as author_email
            FROM question_comment qc
            JOIN entity_member em ON qc.author_id = em.id
            WHERE qc.question_id = :question_id
              AND qc.audit_id = :audit_id
              AND qc.is_deleted = false
            ORDER BY qc.created_at ASC
        """)

        comments = db.execute(query, {
            "question_id": str(question_id),
            "audit_id": str(audit_id)
        }).fetchall()

        result = []
        for comment in comments:
            # Récupérer les mentions pour ce commentaire
            mentions_query = text("""
                SELECT
                    cm.id, cm.comment_id, cm.mentioned_user_id, cm.is_read, cm.created_at,
                    em.first_name, em.last_name, em.email
                FROM comment_mention cm
                JOIN entity_member em ON cm.mentioned_user_id = em.id
                WHERE cm.comment_id = :comment_id
            """)

            mentions = db.execute(mentions_query, {"comment_id": str(comment.id)}).fetchall()

            mention_responses = [
                MentionResponse(
                    id=m.id,
                    comment_id=m.comment_id,
                    mentioned_user_id=m.mentioned_user_id,
                    is_read=m.is_read,
                    created_at=m.created_at,
                    first_name=m.first_name,
                    last_name=m.last_name,
                    email=m.email
                )
                for m in mentions
            ]

            result.append(CommentResponse(
                id=comment.id,
                question_id=comment.question_id,
                audit_id=comment.audit_id,
                author_id=comment.author_id,
                content=comment.content,
                created_at=comment.created_at,
                updated_at=comment.updated_at,
                is_deleted=comment.is_deleted,
                author_first_name=comment.author_first_name,
                author_last_name=comment.author_last_name,
                author_email=comment.author_email,
                mentions=mention_responses
            ))

        return result

    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération des commentaires: {e}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération des commentaires: {str(e)}"
        )


@router.get("/mentions/unread", response_model=UnreadMentionsResponse)
async def get_unread_mentions(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_keycloak)
):
    """
    Récupère toutes les mentions non lues pour l'utilisateur connecté
    avec les détails complets (commentaire, question, auteur)
    """
    try:
        # Gérer les deux types de current_user (dict ou objet User)
        if isinstance(current_user, dict):
            user_email = current_user.get("email")
        else:
            user_email = getattr(current_user, "email", None)

        # Pour les utilisateurs Magic Link, récupérer le vrai email
        user = None
        if user_email and user_email.endswith("@temp.cybergard.local"):
            username = user_email.split("@")[0]
            parts = username.split("-")
            if len(parts) >= 6:
                campaign_id_from_email = "-".join(parts[1:-1])
                email_hash = parts[-1]

                real_email_query = text("""
                    SELECT user_email
                    FROM audit_tokens
                    WHERE campaign_id = :campaign_id
                      AND revoked = false
                """)
                all_emails = db.execute(real_email_query, {"campaign_id": campaign_id_from_email}).fetchall()

                import hashlib
                real_email = user_email
                for row in all_emails:
                    candidate_email = row.user_email
                    candidate_hash = hashlib.sha256(candidate_email.encode()).hexdigest()[:8]
                    if candidate_hash == email_hash:
                        real_email = candidate_email
                        break

                user_email = real_email

                # Si Magic Link, vérifier si c'est un auditeur de cette campagne
                # IMPORTANT: Vérifier en PREMIER si l'utilisateur est auditeur pour cette campagne
                # car un même email peut exister dans entity_member ET users
                auditor_check = text("""
                    SELECT u.id
                    FROM users u
                    JOIN campaign_user cu ON u.id = cu.user_id
                    WHERE u.email = :email
                      AND cu.campaign_id = :campaign_id
                      AND cu.role = 'auditor'
                      AND cu.is_active = true
                    LIMIT 1
                """)
                auditor_result = db.execute(auditor_check, {
                    "email": user_email,
                    "campaign_id": campaign_id_from_email
                }).fetchone()

                if auditor_result:
                    # C'est un auditeur connecté via Magic Link pour cette campagne
                    user = type('obj', (object,), {'id': auditor_result.id, 'user_type': 'auditor'})()
                    logger.info(f"👤 Utilisateur identifié comme AUDITEUR: {user_email}")
                else:
                    # Chercher dans entity_member
                    user_query_em = text("""
                        SELECT id, 'entity_member' as user_type FROM entity_member WHERE email = :email LIMIT 1
                    """)
                    user = db.execute(user_query_em, {"email": user_email}).fetchone()
        else:
            # Pas de Magic Link: TOUJOURS vérifier auditeur EN PREMIER (dual-table priority)
            # IMPORTANT: Chercher d'abord dans users (auditeurs) car prioritaire
            user_query_u = text("""
                SELECT id, 'auditor' as user_type FROM users WHERE email = :email LIMIT 1
            """)
            user = db.execute(user_query_u, {"email": user_email}).fetchone()

            # Si pas trouvé dans users, chercher dans entity_member
            if not user:
                user_query_em = text("""
                    SELECT id, 'entity_member' as user_type FROM entity_member WHERE email = :email LIMIT 1
                """)
                user = db.execute(user_query_em, {"email": user_email}).fetchone()

        if not user:
            logger.warning(f"⚠️ Utilisateur non trouvé pour email: {user_email}")
            return UnreadMentionsResponse(total_unread=0, mentions=[])

        # Récupérer les mentions non lues avec TOUS les détails
        # L'auteur peut être dans entity_member OU users (auditeurs)
        query = text("""
            SELECT
                cm.id as mention_id,
                cm.comment_id,
                cm.mentioned_user_id,
                cm.is_read,
                cm.created_at as mention_created_at,
                qc.question_id,
                qc.audit_id,
                qc.content as comment_content,
                qc.created_at as comment_created_at,
                COALESCE(em_author.id, u_author.id) as author_id,
                COALESCE(em_author.first_name, u_author.first_name) as author_first_name,
                COALESCE(em_author.last_name, u_author.last_name) as author_last_name,
                COALESCE(em_author.email, u_author.email) as author_email,
                q.question_text,
                q.sort_order as question_order,
                a.questionnaire_id,
                c.id as campaign_id
            FROM comment_mention cm
            JOIN question_comment qc ON cm.comment_id = qc.id
            LEFT JOIN entity_member em_author ON qc.author_id = em_author.id
            LEFT JOIN users u_author ON qc.author_id = u_author.id
            JOIN question q ON qc.question_id = q.id
            JOIN audit a ON qc.audit_id = a.id
            LEFT JOIN campaign c ON a.name LIKE CONCAT('%', c.title, '%')
            WHERE cm.mentioned_user_id = :user_id
              AND cm.is_read = false
              AND qc.is_deleted = false
            ORDER BY cm.created_at DESC
        """)

        mentions = db.execute(query, {"user_id": str(user.id)}).fetchall()

        mention_responses = [
            MentionResponse(
                id=m.mention_id,
                comment_id=m.comment_id,
                mentioned_user_id=m.mentioned_user_id,
                is_read=m.is_read,
                created_at=m.mention_created_at,
                # Détails du commentaire
                comment_content=m.comment_content,
                comment_created_at=m.comment_created_at,
                # Détails de l'auteur
                author_id=m.author_id,
                author_first_name=m.author_first_name,
                author_last_name=m.author_last_name,
                author_email=m.author_email,
                # Détails de la question
                question_id=m.question_id,
                question_text=m.question_text,
                question_order=m.question_order,
                audit_id=m.audit_id,
                questionnaire_id=m.questionnaire_id,
                # Type d'utilisateur et campaign_id
                user_type=user.user_type,
                campaign_id=m.campaign_id
            )
            for m in mentions
        ]

        return UnreadMentionsResponse(
            total_unread=len(mention_responses),
            mentions=mention_responses
        )

    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération des mentions non lues: {e}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération des mentions: {str(e)}"
        )


@router.patch("/mentions/{mention_id}/read", response_model=MentionResponse)
async def mark_mention_as_read(
    mention_id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_keycloak)
):
    """
    Marque une mention comme lue
    """
    try:
        query = text("""
            UPDATE comment_mention
            SET is_read = true
            WHERE id = :mention_id
            RETURNING id, comment_id, mentioned_user_id, is_read, created_at
        """)

        result = db.execute(query, {"mention_id": str(mention_id)}).fetchone()

        if not result:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Mention non trouvée"
            )

        db.commit()

        return MentionResponse(
            id=result.id,
            comment_id=result.comment_id,
            mentioned_user_id=result.mentioned_user_id,
            is_read=result.is_read,
            created_at=result.created_at
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur lors de la mise à jour de la mention: {e}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la mise à jour de la mention: {str(e)}"
        )


@router.get("/mentions/{mention_id}/access-link")
async def get_mention_access_link(
    mention_id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_keycloak)
):
    """
    Génère un Magic Link pour accéder à l'audit contenant la mention
    Permet à un utilisateur d'accéder à un audit différent via une mention
    """
    try:
        # Gérer les deux types de current_user (dict ou objet User)
        if isinstance(current_user, dict):
            user_email = current_user.get("email")
        else:
            user_email = getattr(current_user, "email", None)

        # Pour les utilisateurs Magic Link, récupérer le vrai email
        if user_email and user_email.endswith("@temp.cybergard.local"):
            username = user_email.split("@")[0]
            parts = username.split("-")
            if len(parts) >= 6:
                campaign_id_from_email = "-".join(parts[1:-1])
                email_hash = parts[-1]

                real_email_query = text("""
                    SELECT user_email
                    FROM audit_tokens
                    WHERE campaign_id = :campaign_id
                      AND revoked = false
                """)
                all_emails = db.execute(real_email_query, {"campaign_id": campaign_id_from_email}).fetchall()

                import hashlib
                real_email = user_email
                for row in all_emails:
                    candidate_email = row.user_email
                    candidate_hash = hashlib.sha256(candidate_email.encode()).hexdigest()[:8]
                    if candidate_hash == email_hash:
                        real_email = candidate_email
                        break

                user_email = real_email

        # Récupérer les infos de la mention et de l'audit
        mention_query = text("""
            SELECT
                cm.id,
                qc.audit_id,
                qc.question_id,
                a.questionnaire_id,
                c.id as campaign_id,
                c.tenant_id
            FROM comment_mention cm
            JOIN question_comment qc ON cm.comment_id = qc.id
            JOIN audit a ON qc.audit_id = a.id
            JOIN campaign c ON a.name LIKE CONCAT('%', c.title, '%')
            WHERE cm.id = :mention_id
              AND cm.mentioned_user_id = (SELECT id FROM entity_member WHERE email = :user_email LIMIT 1)
            LIMIT 1
        """)

        mention_data = db.execute(mention_query, {
            "mention_id": str(mention_id),
            "user_email": user_email
        }).fetchone()

        if not mention_data:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Mention non trouvée ou accès refusé"
            )

        # Générer le Magic Link pour cet audit spécifique
        magic_link, _ = generate_magic_link(
            db=db,
            user_email=user_email,
            campaign_id=mention_data.campaign_id,
            questionnaire_id=mention_data.questionnaire_id,
            tenant_id=mention_data.tenant_id,
            question_id=mention_data.question_id
        )

        logger.info(f"✅ Magic Link généré pour mention {mention_id} - utilisateur {user_email}")

        return {"magic_link": magic_link}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur lors de la génération du Magic Link pour mention: {e}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la génération du lien d'accès: {str(e)}"
        )
