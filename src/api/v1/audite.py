"""Endpoints API pour la vue audité"""
from typing import List, Dict, Optional
from uuid import UUID
import uuid
import hashlib
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, func, text

from src.database import get_db
from src.models.audit import Audit, Questionnaire, Question, QuestionAnswer
from src.dependencies_keycloak import get_current_user_keycloak
from src.schemas.audite import (
    QuestionAnswerCreate,
    QuestionAnswerUpdate,
    QuestionAnswerResponse,
    QuestionnaireForAuditeResponse,
    QuestionForAuditeResponse,
    DomainNode,
    SubmitAuditRequest,
    SubmitAuditResponse,
    ProgressResponse,
)
from datetime import datetime
import logging
import os
import json

from src.services.email_service import (
    send_audite_submission_email,
    send_auditeur_submission_email,
    send_chef_projet_submission_email
)

logger = logging.getLogger(__name__)

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

router = APIRouter()


# ============================================================================
# HELPER : Vérification du gel de campagne
# ============================================================================

async def check_campaign_frozen(campaign_id: UUID, db: Session) -> None:
    """
    Vérifie si une campagne est gelée (frozen).

    Lève une HTTPException 403 si la campagne est figée.

    Args:
        campaign_id: ID de la campagne à vérifier
        db: Session de base de données

    Raises:
        HTTPException 403: Si la campagne est figée (lecture seule)
    """
    from src.models.campaign import Campaign

    campaign_query = text("""
        SELECT status, frozen_date
        FROM campaign
        WHERE id = :campaign_id
    """)

    result = db.execute(campaign_query, {"campaign_id": str(campaign_id)}).fetchone()

    if result and result.status == 'frozen':
        frozen_date_str = result.frozen_date.strftime('%d/%m/%Y') if result.frozen_date else 'inconnue'
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Cette campagne est figée depuis le {frozen_date_str}. Aucune modification n'est autorisée."
        )


# ============================================================================
# RÉCUPÉRATION DU QUESTIONNAIRE COMPLET (AVEC ARBRE)
# ============================================================================

@router.get("/campaign/{campaign_id}/questionnaire/{questionnaire_id}", response_model=QuestionnaireForAuditeResponse)
async def get_questionnaire_for_campaign(
    campaign_id: UUID,
    questionnaire_id: UUID,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user_keycloak)
):
    """
    Récupère le questionnaire complet pour une campagne (via Magic Link).

    Cette route est utilisée quand l'utilisateur accède via un Magic Link.
    - Crée automatiquement un audit individuel au premier accès
    - Retourne le questionnaire avec les réponses existantes (si déjà rempli)
    """
    # Support both dict and User object
    user_email = current_user.get("email") if isinstance(current_user, dict) else current_user.email
    logger.info(f"📋 Récupération questionnaire pour campagne {campaign_id} - Utilisateur: {user_email}")

    # Si c'est un utilisateur Magic Link (email temporaire), récupérer le vrai email depuis audit_tokens
    if user_email and user_email.endswith("@temp.cybergard.local"):
        logger.debug(f"🔗 Détection Magic Link - Récupération du vrai email depuis audit_tokens")

        # Extraire le hash depuis l'email temporaire
        # Format: audite-{campaign_id}-{hash}@temp.cybergard.local
        temp_username = user_email.split("@")[0]  # audite-{campaign_id}-{hash}
        email_hash = temp_username.split("-")[-1]  # Dernier segment = hash

        # Récupérer tous les emails de la campagne et trouver celui qui correspond au hash
        real_email_query = text("""
            SELECT user_email
            FROM audit_tokens
            WHERE campaign_id = :campaign_id
              AND revoked = false
        """)
        all_emails = db.execute(real_email_query, {"campaign_id": str(campaign_id)}).fetchall()

        # Trouver l'email dont le hash correspond
        for row in all_emails:
            candidate_email = row.user_email
            candidate_hash = hashlib.sha256(candidate_email.encode()).hexdigest()[:8]
            if candidate_hash == email_hash:
                user_email = candidate_email
                logger.info(f"✅ Vrai email récupéré via hash matching: {user_email}")
                break
        else:
            logger.warning(f"⚠️  Impossible de trouver le vrai email correspondant au hash {email_hash}")

    # Vérifier que la campagne existe et récupérer les entités du scope
    campaign_query = text("""
        SELECT c.id, c.questionnaire_id, c.title, c.tenant_id, c.launch_date, c.due_date, c.status, cs.entity_ids
        FROM campaign c
        LEFT JOIN campaign_scope cs ON c.scope_id = cs.id
        WHERE c.id = :campaign_id
    """)
    campaign_result = db.execute(campaign_query, {"campaign_id": str(campaign_id)}).fetchone()

    if not campaign_result:
        logger.error(f"❌ Campagne {campaign_id} non trouvée")
        raise HTTPException(status_code=404, detail="Campagne non trouvée")

    # Vérifier que le questionnaire correspond
    if str(campaign_result.questionnaire_id) != str(questionnaire_id):
        logger.warning(f"⚠️ Questionnaire {questionnaire_id} ne correspond pas à la campagne")
        raise HTTPException(
            status_code=400,
            detail="Le questionnaire ne correspond pas à cette campagne"
        )

    # ============================================================================
    # VÉRIFICATION DES DATES DE LA CAMPAGNE
    # ============================================================================
    from datetime import datetime, date
    today = date.today()

    logger.info(f"📅 Vérification des dates - Aujourd'hui: {today}, Launch: {campaign_result.launch_date}, Due: {campaign_result.due_date}")

    # Vérifier si la campagne a démarré
    if campaign_result.launch_date:
        launch_date = campaign_result.launch_date
        # Convertir en date si c'est un datetime
        if isinstance(launch_date, datetime):
            launch_date = launch_date.date()

        if today < launch_date:
            days_until = (launch_date - today).days
            logger.warning(f"⚠️ Campagne {campaign_id} non démarrée - Début le {launch_date}")
            raise HTTPException(
                status_code=403,
                detail=f"L'audit n'a pas encore commencé. Vous pourrez accéder au questionnaire à partir du {launch_date.strftime('%d/%m/%Y')}."
            )

    # Vérifier si la campagne n'est pas expirée
    if campaign_result.due_date:
        due_date = campaign_result.due_date
        # Convertir en date si c'est un datetime
        if isinstance(due_date, datetime):
            due_date = due_date.date()

        if today > due_date:
            days_passed = (today - due_date).days
            logger.warning(f"⚠️ Campagne {campaign_id} expirée depuis {days_passed} jour(s)")
            raise HTTPException(
                status_code=403,
                detail=f"Cette campagne d'audit est clôturée. Le questionnaire n'est plus accessible depuis le {due_date.strftime('%d/%m/%Y')}."
            )

    logger.info(f"✅ Dates de campagne valides: du {campaign_result.launch_date} au {campaign_result.due_date}")

    # ============================================================================
    # VÉRIFIER SI L'UTILISATEUR EST UN AUDITEUR DE CETTE CAMPAGNE
    # ============================================================================
    # IMPORTANT: Vérifier en PREMIER si l'utilisateur est un auditeur (dans users table)
    # car un même email peut exister dans entity_member ET users
    auditor_check_query = text("""
        SELECT u.id, u.email
        FROM users u
        JOIN campaign_user cu ON u.id = cu.user_id
        WHERE u.email = :email
          AND cu.campaign_id = :campaign_id
          AND cu.role = 'auditor'
          AND cu.is_active = true
        LIMIT 1
    """)
    auditor_result = db.execute(auditor_check_query, {
        "email": user_email,
        "campaign_id": str(campaign_id)
    }).fetchone()

    is_auditor = auditor_result is not None

    if is_auditor:
        logger.info(f"👤 Utilisateur identifié comme AUDITEUR: {user_email}")
        # Pour un auditeur, on prend la PREMIÈRE entité du scope
        # L'auditeur a accès à toutes les entités de la campagne
        if campaign_result.entity_ids and len(campaign_result.entity_ids) > 0:
            entity_id = campaign_result.entity_ids[0]

            # Récupérer le nom de l'entité
            entity_name_query = text("""
                SELECT name FROM ecosystem_entity WHERE id = :entity_id
            """)
            entity_name_result = db.execute(entity_name_query, {"entity_id": str(entity_id)}).fetchone()
            entity_name = entity_name_result.name if entity_name_result else "Entité inconnue"

            logger.info(f"✅ Auditeur - Utilisation de l'entité: {entity_name} (ID: {entity_id})")
        else:
            logger.error(f"❌ Aucune entité dans le scope de la campagne")
            raise HTTPException(
                status_code=404,
                detail="Aucune entité trouvée dans le scope de cette campagne"
            )
    else:
        # ============================================================================
        # RÉCUPÉRER L'ENTITÉ DE L'UTILISATEUR VIA CAMPAIGN_SCOPE (pour audité)
        # ============================================================================
        # IMPORTANT: Utiliser la table campaign_scope pour récupérer l'entité
        # Parcours: campaign -> scope_id -> campaign_scope -> entity_ids
        entity_query = text("""
            SELECT
                em.entity_id,
                ee.name as entity_name,
                cs.id as scope_id
            FROM campaign c
            INNER JOIN campaign_scope cs ON c.scope_id = cs.id
            INNER JOIN entity_member em ON em.entity_id = ANY(cs.entity_ids)
            INNER JOIN ecosystem_entity ee ON em.entity_id = ee.id
            WHERE c.id = :campaign_id
              AND em.email = :user_email
              AND em.is_active = true
            LIMIT 1
        """)

        entity_result = db.execute(entity_query, {
            "campaign_id": str(campaign_id),
            "user_email": user_email
        }).fetchone()

        if not entity_result:
            logger.error(f"❌ Entité non trouvée pour l'utilisateur {user_email} dans la campagne {campaign_id}")
            raise HTTPException(
                status_code=404,
                detail="Entité de l'utilisateur non trouvée pour cette campagne. Assurez-vous que l'utilisateur est bien un contact d'une entité dans le périmètre de cette campagne."
            )

        entity_id = entity_result.entity_id
        entity_name = entity_result.entity_name
        scope_id = entity_result.scope_id

        logger.info(f"✅ Entité trouvée via campaign_scope: {entity_name} (ID: {entity_id}, Scope: {scope_id})")

    # Récupérer l'ID du membre dans entity_member pour filtrer les réponses
    member_id_query = text("""
        SELECT id FROM entity_member
        WHERE email = :user_email AND entity_id = :entity_id
        LIMIT 1
    """)
    member_id_result = db.execute(member_id_query, {
        "user_email": user_email,
        "entity_id": str(entity_id)
    }).fetchone()

    current_member_id = member_id_result.id if member_id_result else None
    logger.info(f"✅ Member ID pour {user_email}: {current_member_id}")

    # ============================================================================
    # CRÉER OU RÉCUPÉRER L'AUDIT PARTAGÉ PAR ENTITÉ
    # ============================================================================
    # Vérifier si un audit existe déjà pour cette campagne et cette ENTITÉ
    # TOUS les auditeurs de la même entité partagent le même audit
    audit_check_query = text("""
        SELECT id
        FROM audit
        WHERE name LIKE :name_pattern
          AND questionnaire_id = :questionnaire_id
          AND tenant_id = :tenant_id
        LIMIT 1
    """)

    audit_result = db.execute(audit_check_query, {
        "name_pattern": f"%{campaign_result.title}%{entity_name}%",
        "questionnaire_id": str(questionnaire_id),
        "tenant_id": str(campaign_result.tenant_id)
    }).fetchone()

    if audit_result:
        # Audit déjà existant - partagé par tous les auditeurs de l'entité
        audit_id = audit_result.id
        logger.info(f"✅ Audit partagé existant trouvé: {audit_id} pour l'entité {entity_name} - Accès par {user_email}")
    else:
        # Récupérer l'organization (client) du tenant
        org_query = text("""
            SELECT id FROM organization
            WHERE tenant_id = :tenant_id
            LIMIT 1
        """)
        org_result = db.execute(org_query, {"tenant_id": str(campaign_result.tenant_id)}).fetchone()

        if not org_result:
            logger.error(f"❌ Aucune organisation trouvée pour le tenant {campaign_result.tenant_id}")
            raise HTTPException(
                status_code=400,
                detail="Organisation du tenant introuvable"
            )

        # Pour un audit de campagne, l'organization (client) est à la fois owner et target
        owner_org_id = str(org_result.id)
        target_org_id = str(org_result.id)

        # Créer un nouvel audit pour cet utilisateur
        audit_id = uuid.uuid4()
        create_audit_query = text("""
            INSERT INTO audit (
                id,
                name,
                questionnaire_id,
                status,
                tenant_id,
                owner_org_id,
                target_org_id,
                created_at,
                updated_at
            ) VALUES (
                :audit_id,
                :name,
                :questionnaire_id,
                'draft',
                :tenant_id,
                :owner_org_id,
                :target_org_id,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            )
        """)

        db.execute(create_audit_query, {
            "audit_id": str(audit_id),
            "name": f"Audit - {campaign_result.title} - {entity_name}",
            "questionnaire_id": str(questionnaire_id),
            "tenant_id": str(campaign_result.tenant_id),
            "owner_org_id": owner_org_id,
            "target_org_id": target_org_id
        })
        db.commit()
        logger.info(f"✅ Nouvel audit créé: {audit_id} pour l'entité {entity_name} (ID: {entity_id}) - Accès demandé par {user_email}")

    # Récupérer le questionnaire
    questionnaire = db.query(Questionnaire).filter(
        Questionnaire.id == questionnaire_id
    ).first()

    if not questionnaire:
        logger.error(f"❌ Questionnaire {questionnaire_id} non trouvé")
        raise HTTPException(status_code=404, detail="Questionnaire non trouvé")

    # Récupérer toutes les questions avec leur requirement pour accéder au domain_id
    from sqlalchemy.orm import joinedload
    questions = db.query(Question).options(
        joinedload(Question.requirement)
    ).filter(
        Question.questionnaire_id == questionnaire_id,
        Question.is_active == True
    ).order_by(Question.sort_order).all()

    logger.info(f"✅ {len(questions)} questions trouvées pour le questionnaire")

    # ============================================================================
    # FILTRAGE DES QUESTIONS POUR LES CONTRIBUTEURS
    # ============================================================================
    # Vérifier si l'utilisateur est un contributeur (audite_contrib)
    # Si oui, ne montrer que les questions où il a été mentionné
    user_role_query = text("""
        SELECT roles FROM entity_member
        WHERE email = :user_email
        LIMIT 1
    """)
    user_role_result = db.execute(user_role_query, {"user_email": user_email}).fetchone()

    # Déterminer le rôle principal de l'utilisateur pour le frontend
    user_role = None
    if user_role_result:
        import json
        user_roles = json.loads(user_role_result.roles) if isinstance(user_role_result.roles, str) else user_role_result.roles
        user_roles_lower = [role.lower() if isinstance(role, str) else role for role in user_roles]

        # Prioriser AUDITE_RESP sur AUDITE_CONTRIB
        if 'audite_resp' in user_roles_lower:
            user_role = 'audite_resp'
        elif 'audite_contrib' in user_roles_lower:
            user_role = 'audite_contrib'

        # Si l'utilisateur est un contributeur (pas un AUDITE_RESP)
        if 'audite_contrib' in user_roles_lower and 'audite_resp' not in user_roles_lower:
            logger.info(f"🔒 Utilisateur contributeur détecté ({user_email}) - Filtrage des questions")

            # Récupérer les ID de l'utilisateur dans entity_member
            user_id_query = text("""
                SELECT id FROM entity_member
                WHERE email = :user_email
                LIMIT 1
            """)
            user_id_result = db.execute(user_id_query, {"user_email": user_email}).fetchone()

            if user_id_result:
                # Récupérer les questions où cet utilisateur a été mentionné
                mentioned_questions_query = text("""
                    SELECT DISTINCT qc.question_id
                    FROM comment_mention cm
                    JOIN question_comment qc ON cm.comment_id = qc.id
                    WHERE cm.mentioned_user_id = :user_id
                      AND qc.audit_id = :audit_id
                """)
                mentioned_questions_result = db.execute(mentioned_questions_query, {
                    "user_id": str(user_id_result.id),
                    "audit_id": str(audit_id)
                }).fetchall()

                mentioned_question_ids = {str(row.question_id) for row in mentioned_questions_result}

                # Filtrer les questions pour ne garder que celles mentionnées
                questions = [q for q in questions if str(q.id) in mentioned_question_ids]

                logger.info(f"✅ Filtrage appliqué - {len(questions)} question(s) accessible(s) pour le contributeur {user_email}")

                if len(questions) == 0:
                    logger.warning(f"⚠️  Aucune question accessible pour le contributeur {user_email}")
            else:
                logger.warning(f"⚠️  ID utilisateur non trouvé pour {user_email}")
        else:
            logger.info(f"✅ Utilisateur AUDITE_RESP ou admin - Accès complet au questionnaire")

    # ============================================================================
    # FILTRAGE DES QUESTIONS POUR LES AUDITÉS RESPONSABLES (DOMAIN SCOPE)
    # ============================================================================
    logger.info(f"🔍 [DEBUG] Début vérification filtrage domaines pour {user_email}")
    logger.info(f"🔍 [DEBUG] user_role_result existe: {user_role_result is not None}")

    # Vérifier si l'utilisateur est un AUDITE_RESP avec un périmètre de domaines défini
    if user_role_result:
        user_roles = json.loads(user_role_result.roles) if isinstance(user_role_result.roles, str) else user_role_result.roles
        user_roles_lower = [role.lower() if isinstance(role, str) else role for role in user_roles]

        logger.info(f"🔍 [DEBUG] Rôles utilisateur: {user_roles_lower}")

        # Si l'utilisateur est un AUDITE_RESP (pas seulement contributeur)
        if 'audite_resp' in user_roles_lower:
            logger.info(f"🔍 [DEBUG] Utilisateur est AUDITE_RESP - Vérification du périmètre de domaines pour ({user_email})")

            # Récupérer l'ID de l'utilisateur dans entity_member
            user_id_query = text("""
                SELECT id FROM entity_member
                WHERE email = :user_email
                LIMIT 1
            """)
            user_id_result = db.execute(user_id_query, {"user_email": user_email}).fetchone()

            if user_id_result:
                logger.info(f"🔍 [DEBUG] entity_member_id trouvé: {user_id_result.id}")

                # Récupérer le périmètre de domaines pour cet utilisateur dans cette campagne
                domain_scope_query = text("""
                    SELECT domain_ids, all_domains
                    FROM audite_domain_scope
                    WHERE campaign_id = :campaign_id
                      AND entity_member_id = :entity_member_id
                """)
                domain_scope_result = db.execute(domain_scope_query, {
                    "campaign_id": str(campaign_id),
                    "entity_member_id": str(user_id_result.id)
                }).fetchone()

                logger.info(f"🔍 [DEBUG] domain_scope_result trouvé: {domain_scope_result is not None}")

                if domain_scope_result:
                    logger.info(f"🔍 [DEBUG] Scope: all_domains={domain_scope_result.all_domains}, domain_ids={domain_scope_result.domain_ids}")
                    # Un périmètre est défini
                    if domain_scope_result.all_domains:
                        logger.info(f"✅ AUDITE_RESP a accès à TOUS les domaines (all_domains=TRUE)")
                    elif domain_scope_result.domain_ids and len(domain_scope_result.domain_ids) > 0:
                        # Filtrer les questions par domaines autorisés
                        allowed_domain_ids = set(domain_scope_result.domain_ids)
                        logger.info(f"🔒 Filtrage par domaines autorisés: {allowed_domain_ids}")

                        # Filtrer les questions dont le domain_id est dans la liste autorisée
                        # allowed_domain_ids contient les UUIDs des domaines (ex: 'c8d465d5-79de-49ac-aa7b-6851fdfecc4e')
                        filtered_questions = []
                        for q in questions:
                            # Accéder au domain_id via requirement
                            if q.requirement and q.requirement.domain_id:
                                domain_id_str = str(q.requirement.domain_id)

                                # Vérifier si le domaine est dans la liste autorisée
                                if domain_id_str in allowed_domain_ids:
                                    filtered_questions.append(q)

                        questions = filtered_questions
                        logger.info(f"✅ Filtrage domaines appliqué - {len(questions)} question(s) accessible(s)")
                    else:
                        # domain_ids est vide = aucun domaine autorisé
                        logger.warning(f"⚠️  Périmètre vide - Aucun domaine autorisé pour {user_email}")
                        questions = []
                else:
                    # Aucun périmètre défini = accès complet par défaut (backwards compatibility)
                    logger.info(f"✅ Aucun périmètre défini - Accès complet par défaut")

    # Récupérer les réponses existantes pour cet audit
    # IMPORTANT: Filtrer uniquement les réponses des membres de la même entité
    # pour éviter la contamination entre entités
    if current_member_id:
        # Récupérer tous les membres de la même entité
        entity_members_query = text("""
            SELECT id FROM entity_member
            WHERE entity_id = :entity_id AND is_active = true
        """)
        entity_members_result = db.execute(entity_members_query, {"entity_id": str(entity_id)}).fetchall()
        entity_member_ids = [row.id for row in entity_members_result]  # Garder les UUIDs, pas str()

        logger.info(f"🔍 Filtrage des réponses pour l'entité {entity_name} ({len(entity_member_ids)} membres)")
        logger.info(f"🆔 Entity ID utilisé: {entity_id}")
        logger.info(f"👥 Member IDs de l'entité: {entity_member_ids}")

        answers = db.query(QuestionAnswer).filter(
            QuestionAnswer.audit_id == audit_id,
            QuestionAnswer.is_current == True,
            QuestionAnswer.answered_by.in_(entity_member_ids)
        ).all()

        logger.info(f"📝 {len(answers)} réponses brutes trouvées pour l'audit {audit_id}")
        if len(answers) > 0:
            logger.info(f"🔍 Exemple answered_by de la première réponse: {answers[0].answered_by} (type: {type(answers[0].answered_by)})")
    else:
        # Fallback si member_id non trouvé (ne devrait pas arriver)
        answers = db.query(QuestionAnswer).filter(
            QuestionAnswer.audit_id == audit_id,
            QuestionAnswer.is_current == True
        ).all()

    # Mapper les réponses par question_id
    answers_by_question = {answer.question_id: answer for answer in answers}

    logger.info(f"📊 {len(answers_by_question)} réponses trouvées pour l'entité {entity_name} (audit {audit_id})")

    # Construire l'arbre des domaines avec chargement des options
    domain_tree, questions_by_node = _build_domain_tree(questions, answers_by_question, db)

    # Calculer les statistiques
    total_questions = len(questions)
    answered_questions = len([q for q in questions if q.id in answers_by_question])
    mandatory_questions = len([q for q in questions if q.is_required])
    mandatory_answered = len([
        q for q in questions
        if q.is_required and q.id in answers_by_question
    ])

    progress_percentage = (answered_questions / total_questions * 100) if total_questions > 0 else 0
    can_submit = mandatory_answered == mandatory_questions

    # Vérifier si l'audit a déjà été soumis
    is_submitted = any(
        answer.status == "submitted"
        for answer in answers_by_question.values()
    )

    return QuestionnaireForAuditeResponse(
        id=questionnaire.id,
        name=questionnaire.name,
        audit_id=audit_id,  # Retourner l'audit_id créé ou récupéré
        campaign_id=campaign_id,  # ID de la campagne pour tracking des réponses
        user_role=user_role,  # Rôle de l'utilisateur (audite_resp ou audite_contrib)
        domain_tree=domain_tree,
        questions_by_node=questions_by_node,
        total_questions=total_questions,
        answered_questions=answered_questions,
        mandatory_questions=mandatory_questions,
        mandatory_answered=mandatory_answered,
        progress_percentage=progress_percentage,
        can_submit=can_submit,
        is_submitted=is_submitted
    )


@router.get("/{audit_id}/questionnaire/{questionnaire_id}", response_model=QuestionnaireForAuditeResponse)
async def get_questionnaire_for_audite(
    audit_id: UUID,
    questionnaire_id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_keycloak)
):
    """
    Récupère le questionnaire complet pour l'audité avec:
    - Arbre de navigation par domaines
    - Questions regroupées par noeud
    - Réponses existantes
    - Statistiques de progression

    IMPORTANT: Cette route gère AUSSI les auditeurs (dual-table identity)
    """
    # Support both dict and User object
    user_email = current_user.get("email") if isinstance(current_user, dict) else current_user.email

    # Récupérer d'abord l'audit pour avoir la campagne
    audit = db.query(Audit).filter(Audit.id == audit_id).first()
    if not audit:
        raise HTTPException(status_code=404, detail="Audit non trouvé")

    # Extraire campaign_id et informations de campagne (dates, statut)
    # Note: Il n'y a pas de FK direct audit.campaign_id, on utilise une jointure sur les noms
    campaign_query = text("""
        SELECT c.id as campaign_id, c.launch_date, c.due_date, c.status
        FROM campaign c
        JOIN audit a ON a.name LIKE ('%' || c.title || '%')
        WHERE a.id = :audit_id
        LIMIT 1
    """)
    campaign_result = db.execute(campaign_query, {"audit_id": str(audit_id)}).fetchone()

    if not campaign_result:
        logger.warning(f"Campaign not found for audit {audit_id}")
        # Continuer sans campaign_id pour compatibilité
        campaign_id = None
    else:
        campaign_id = campaign_result.campaign_id

        # Vérifier les dates de campagne (launch_date et due_date)
        from datetime import date as date_type
        today = date_type.today()

        logger.info(f"📅 Vérification des dates - Aujourd'hui: {today}, Launch: {campaign_result.launch_date}, Due: {campaign_result.due_date}, Status: {campaign_result.status}")

        # Vérifier si la campagne n'a pas encore démarré
        if campaign_result.launch_date:
            launch_date = campaign_result.launch_date
            # Convertir datetime en date si nécessaire
            if isinstance(launch_date, datetime):
                launch_date = launch_date.date()

            if today < launch_date:
                logger.warning(f"⚠️ Campagne {campaign_id} non démarrée - Début le {launch_date}")
                raise HTTPException(
                    status_code=403,
                    detail=f"L'audit n'a pas encore commencé. Vous pourrez accéder au questionnaire à partir du {launch_date.strftime('%d/%m/%Y')}."
                )

        # Vérifier si la campagne est clôturée
        if campaign_result.due_date:
            due_date = campaign_result.due_date
            # Convertir datetime en date si nécessaire
            if isinstance(due_date, datetime):
                due_date = due_date.date()

            if today > due_date:
                logger.warning(f"⚠️ Campagne {campaign_id} clôturée - Fin le {due_date}")
                raise HTTPException(
                    status_code=403,
                    detail=f"Cette campagne d'audit est clôturée. Le questionnaire n'est plus accessible depuis le {due_date.strftime('%d/%m/%Y')}."
                )

        logger.info(f"✅ Dates de campagne valides: du {campaign_result.launch_date} au {campaign_result.due_date}")

        # Vérifier si la campagne est figée (frozen)
        # Selon Créer INITIAL.md: campagne frozen = lecture seule pour tous
        is_frozen = campaign_result.status == 'frozen'
        if is_frozen:
            logger.warning(f"⚠️ Campagne {campaign_id} figée (frozen) - Accès en lecture seule")
            # Note: On autorise la lecture mais l'écriture sera bloquée dans les routes de soumission

    # VÉRIFIER SI L'UTILISATEUR EST UN AUDITEUR
    if campaign_id:
        auditor_check_query = text("""
            SELECT u.id FROM users u
            JOIN campaign_user cu ON u.id = cu.user_id
            WHERE u.email = :email
              AND cu.campaign_id = :campaign_id
              AND cu.role = 'auditor'
              AND cu.is_active = true
            LIMIT 1
        """)
        auditor_result = db.execute(auditor_check_query, {
            "email": user_email,
            "campaign_id": str(campaign_id)
        }).fetchone()

        is_auditor = auditor_result is not None
        if is_auditor:
            logger.info(f"👤 Auditeur access granted: {user_email} → audit {audit_id}")

    # Récupérer le questionnaire
    questionnaire = db.query(Questionnaire).filter(
        Questionnaire.id == questionnaire_id
    ).first()

    if not questionnaire:
        raise HTTPException(status_code=404, detail="Questionnaire non trouvé")

    # Récupérer toutes les questions avec leurs réponses
    questions = db.query(Question).filter(
        Question.questionnaire_id == questionnaire_id,
        Question.is_active == True
    ).order_by(Question.sort_order).all()

    # Récupérer toutes les réponses actuelles pour cet audit
    answers = db.query(QuestionAnswer).filter(
        QuestionAnswer.audit_id == audit_id,
        QuestionAnswer.is_current == True
    ).all()

    # Mapper les réponses par question_id
    answers_by_question = {answer.question_id: answer for answer in answers}

    # Construire l'arbre des domaines à partir des questions avec chargement des options
    domain_tree, questions_by_node = _build_domain_tree(questions, answers_by_question, db)

    # Calculer les statistiques
    total_questions = len(questions)
    answered_questions = len([q for q in questions if q.id in answers_by_question])
    mandatory_questions = len([q for q in questions if q.is_required])
    mandatory_answered = len([
        q for q in questions
        if q.is_required and q.id in answers_by_question
    ])

    progress_percentage = (answered_questions / total_questions * 100) if total_questions > 0 else 0
    can_submit = mandatory_answered == mandatory_questions

    return QuestionnaireForAuditeResponse(
        id=questionnaire.id,
        name=questionnaire.name,
        audit_id=audit_id,  # Retourner l'audit_id
        campaign_id=None,  # Pas de campagne en mode test
        domain_tree=domain_tree,
        questions_by_node=questions_by_node,
        total_questions=total_questions,
        answered_questions=answered_questions,
        mandatory_questions=mandatory_questions,
        mandatory_answered=mandatory_answered,
        progress_percentage=round(progress_percentage, 2),
        can_submit=can_submit
    )


def _build_domain_tree(
    questions: List[Question],
    answers_by_question: Dict[UUID, QuestionAnswer],
    db: Session = None
) -> tuple[List[DomainNode], Dict[str, List[QuestionForAuditeResponse]]]:
    """
    Construit l'arbre des domaines et regroupe les questions par noeud

    Stratégie simplifiée pour MVP:
    - Grouper par requirement_id (niveau 1)
    - Si pas de requirement_id, grouper dans "Non classé"
    """
    # Charger toutes les options pour toutes les questions du questionnaire
    options_by_question = {}
    if db and questions:
        question_ids = [str(q.id) for q in questions]

        # Requête pour récupérer toutes les options avec leurs traductions
        # Cast explicite en UUID pour éviter l'erreur "operator does not exist: uuid = text"
        options_query = text("""
            SELECT
                qo.id,
                qo.question_id,
                qo.sort_order,
                qo.custom_value,
                o.value_key,
                o.default_value
            FROM question_option qo
            LEFT JOIN option o ON qo.option_id = o.id
            WHERE qo.question_id::text = ANY(:question_ids)
              AND qo.is_active = true
            ORDER BY qo.question_id, qo.sort_order
        """)

        result = db.execute(options_query, {"question_ids": question_ids})

        for row in result:
            q_id = row.question_id
            if q_id not in options_by_question:
                options_by_question[q_id] = []

            # Format de l'option pour le frontend
            option_data = {
                "id": str(row.id),
                "value": row.custom_value if row.custom_value else row.value_key,
                "label": row.custom_value if row.custom_value else row.default_value,
                "sort_order": row.sort_order
            }
            options_by_question[q_id].append(option_data)

    # Charger les noms des domaines depuis la BDD
    domain_names = {}
    if db and questions:
        domain_ids = [str(q.requirement.domain_id) for q in questions if q.requirement and q.requirement.domain_id]
        if domain_ids:
            domain_query = text("""
                SELECT d.id, COALESCE(dt.title, d.title, d.code) as name
                FROM domain d
                LEFT JOIN domain_title dt ON dt.domain_id = d.id AND dt.language = 'fr' AND dt.is_primary = true
                WHERE d.id::text = ANY(:domain_ids)
            """)
            domain_result = db.execute(domain_query, {"domain_ids": domain_ids})
            for row in domain_result:
                domain_names[row.id] = row.name

    # Grouper les questions par domain_id (via requirement.domain_id)
    questions_by_domain: Dict[str, List[Question]] = {}

    for question in questions:
        # Récupérer le domain_id via requirement
        if question.requirement and question.requirement.domain_id:
            domain_id = str(question.requirement.domain_id)
        else:
            domain_id = "unclassified"

        if domain_id not in questions_by_domain:
            questions_by_domain[domain_id] = []
        questions_by_domain[domain_id].append(question)

    # Construire les noeuds de l'arbre
    domain_tree = []
    questions_by_node = {}

    for idx, (domain_id, domain_questions) in enumerate(sorted(questions_by_domain.items())):
        # Compter les questions répondues
        answered_count = len([q for q in domain_questions if q.id in answers_by_question])
        has_mandatory_unanswered = any(
            q.is_required and q.id not in answers_by_question
            for q in domain_questions
        )

        # Utiliser le vrai nom du domaine ou un nom par défaut
        if domain_id == "unclassified":
            node_name = "Non classé"
        else:
            domain_uuid = uuid.UUID(domain_id)
            node_name = domain_names.get(domain_uuid, f"Domaine {idx + 1}")

        # Créer un noeud enfant pour chaque question
        question_nodes = []
        for q_idx, q in enumerate(domain_questions):
            is_answered = q.id in answers_by_question
            question_node = DomainNode(
                id=f"{domain_id}_q_{q.id}",  # ID unique : domainId_q_questionId
                name=f"Q{q_idx + 1}: {q.question_text[:50]}...",  # Texte tronqué
                type="question",
                order_index=q_idx,
                children=[],
                question_count=1,
                answered_count=1 if is_answered else 0,
                has_mandatory_unanswered=q.is_required and not is_answered
            )
            question_nodes.append(question_node)

        node = DomainNode(
            id=domain_id,
            name=node_name,
            type="domain",
            order_index=idx,
            children=question_nodes,  # Ajouter les questions comme enfants
            question_count=len(domain_questions),
            answered_count=answered_count,
            has_mandatory_unanswered=has_mandatory_unanswered
        )

        domain_tree.append(node)

        # Convertir les questions en réponse API
        questions_by_node[domain_id] = []
        for q in domain_questions:
            # Parser upload_conditions
            parsed_upload_conditions = None
            if q.upload_conditions:
                try:
                    if isinstance(q.upload_conditions, str):
                        parsed_upload_conditions = json.loads(q.upload_conditions)
                    elif isinstance(q.upload_conditions, dict):
                        parsed_upload_conditions = q.upload_conditions
                except json.JSONDecodeError as e:
                    logger.error(f"❌ Erreur parsing upload_conditions pour question {q.id}: {e}")

            questions_by_node[domain_id].append(
                QuestionForAuditeResponse(
                    id=q.id,
                    question_text=q.question_text,
                    response_type=q.response_type,
                    is_required=q.is_required,
                    help_text=q.help_text,
                    options=options_by_question.get(q.id, []),
                    upload_conditions=parsed_upload_conditions,
                    order_index=q.sort_order,
                    current_answer=QuestionAnswerResponse.model_validate(answers_by_question[q.id])
                    if q.id in answers_by_question else None
                )
            )

    return domain_tree, questions_by_node


# ============================================================================
# SAUVEGARDER UNE RÉPONSE (BROUILLON)
# ============================================================================

@router.post("/answers", response_model=QuestionAnswerResponse)
async def save_answer(
    answer_data: QuestionAnswerCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user_keycloak)
):
    """
    Sauvegarde ou met à jour une réponse (brouillon)
    Crée une nouvelle version si la réponse existe déjà
    """
    # Récupérer l'ID de l'utilisateur connecté depuis entity_member
    # Support both dict and User object
    user_email = current_user.get("email") if isinstance(current_user, dict) else current_user.email
    answered_by_id = None

    # Pour les utilisateurs Magic Link, récupérer le vrai email
    if user_email and user_email.endswith("@temp.cybergard.local"):
        # Extraire le campaign_id et le hash de l'email temporaire
        # Format: audite-{campaign_id}-{hash}@temp.cybergard.local
        username = user_email.split("@")[0]
        parts = username.split("-")
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
            for row in all_emails:
                candidate_email = row.user_email
                candidate_hash = hashlib.sha256(candidate_email.encode()).hexdigest()[:8]
                if candidate_hash == email_hash:
                    user_email = candidate_email
                    logger.info(f"✅ Vrai email récupéré via hash matching: {user_email}")
                    break
            else:
                logger.warning(f"⚠️ Impossible de trouver le vrai email pour le hash: {email_hash}")

    if user_email:
        user_query = text("""
            SELECT id, roles FROM entity_member
            WHERE email = :email
            LIMIT 1
        """)
        user_result = db.execute(user_query, {"email": user_email}).fetchone()
        if user_result:
            answered_by_id = user_result.id

            # ============================================================================
            # VÉRIFICATION DES PERMISSIONS POUR LES CONTRIBUTEURS
            # ============================================================================
            # Si l'utilisateur est un contributeur, vérifier qu'il a été mentionné sur cette question
            import json
            user_roles = json.loads(user_result.roles) if isinstance(user_result.roles, str) else user_result.roles
            user_roles_lower = [role.lower() if isinstance(role, str) else role for role in user_roles]

            # Si c'est un contributeur (pas un AUDITE_RESP)
            if 'audite_contrib' in user_roles_lower and 'audite_resp' not in user_roles_lower:
                logger.info(f"🔒 Vérification des permissions contributeur pour {user_email} sur question {answer_data.question_id}")

                # Vérifier si l'utilisateur a été mentionné sur cette question
                permission_query = text("""
                    SELECT COUNT(*) as mention_count
                    FROM comment_mention cm
                    JOIN question_comment qc ON cm.comment_id = qc.id
                    WHERE cm.mentioned_user_id = :user_id
                      AND qc.question_id = :question_id
                      AND qc.audit_id = :audit_id
                """)
                permission_result = db.execute(permission_query, {
                    "user_id": str(answered_by_id),
                    "question_id": str(answer_data.question_id),
                    "audit_id": str(answer_data.audit_id)
                }).fetchone()

                if permission_result.mention_count == 0:
                    logger.warning(f"❌ Contributeur {user_email} tente de répondre à une question où il n'a pas été mentionné (question {answer_data.question_id})")
                    raise HTTPException(
                        status_code=403,
                        detail="Vous n'avez pas l'autorisation de répondre à cette question. Seules les questions où vous avez été mentionné sont accessibles."
                    )

                logger.info(f"✅ Permission accordée - Contributeur {user_email} autorisé sur question {answer_data.question_id}")

    # ============================================================================
    # VÉRIFICATION DU STATUT DE LA CAMPAGNE (FROZEN = LECTURE SEULE)
    # ============================================================================
    if answer_data.campaign_id:
        campaign_status_query = text("""
            SELECT status, frozen_date
            FROM campaign
            WHERE id = :campaign_id
            LIMIT 1
        """)
        campaign_status = db.execute(campaign_status_query, {
            "campaign_id": str(answer_data.campaign_id)
        }).fetchone()

        if campaign_status and campaign_status.status == 'frozen':
            logger.warning(f"❌ Tentative d'écriture sur campagne figée (frozen): {answer_data.campaign_id}")
            raise HTTPException(
                status_code=403,
                detail=f"Cette campagne est figée depuis le {campaign_status.frozen_date.strftime('%d/%m/%Y') if campaign_status.frozen_date else 'N/A'}. Aucune modification n'est possible."
            )

    # ============================================================================
    # CALCULER LE COMPLIANCE_STATUS AUTOMATIQUEMENT
    # ============================================================================
    # Récupérer la question pour obtenir le requirement.risk_level
    from src.models.audit import Requirement

    question_query = db.query(Question).filter(Question.id == answer_data.question_id).first()
    compliance_status = None

    if answer_data.answer_value and question_query:
        # Extraire le choix depuis le JSONB answer_value
        choice_value = answer_data.answer_value.get('choice', '').lower() if isinstance(answer_data.answer_value, dict) else None

        if choice_value:
            # Récupérer le risk_level du requirement
            requirement = db.query(Requirement).filter(Requirement.id == question_query.requirement_id).first()
            risk_level = requirement.risk_level.lower() if requirement and requirement.risk_level else None

            # Calculer le compliance_status en fonction du choice et risk_level
            if choice_value == 'non':
                # Non conforme
                if risk_level in ['high', 'critical', 'major', 'medium', 'moderate']:
                    compliance_status = 'non_compliant_major'
                elif risk_level in ['low', 'minor']:
                    compliance_status = 'non_compliant_minor'
                else:
                    # Par défaut conservateur
                    compliance_status = 'non_compliant_major'
            elif choice_value in ['partiellement', 'partiel']:
                # Partiellement conforme => Non-conformité mineure (approche conservatrice)
                compliance_status = 'non_compliant_minor'
            elif choice_value == 'oui':
                # Conforme
                compliance_status = 'compliant'
            elif choice_value in ['na', 'n/a', 'non applicable']:
                # Non applicable
                compliance_status = 'not_applicable'

            logger.debug(f"✅ Compliance status calculé: {compliance_status} (choice: {choice_value}, risk_level: {risk_level})")

    # Vérifier si une réponse actuelle existe
    existing_answer = db.query(QuestionAnswer).filter(
        QuestionAnswer.question_id == answer_data.question_id,
        QuestionAnswer.audit_id == answer_data.audit_id,
        QuestionAnswer.is_current == True
    ).first()

    if existing_answer:
        # Archiver l'ancienne version
        existing_answer.is_current = False
        db.add(existing_answer)

        # Créer une nouvelle version
        new_answer = QuestionAnswer(
            question_id=answer_data.question_id,
            audit_id=answer_data.audit_id,
            campaign_id=answer_data.campaign_id,
            answered_by=answered_by_id,
            answer_value=answer_data.answer_value,
            status=answer_data.status,
            compliance_status=compliance_status,  # ✅ Ajout du compliance_status
            version=existing_answer.version + 1,
            is_current=True,
            answered_at=datetime.utcnow()
        )
    else:
        # Créer la première version
        new_answer = QuestionAnswer(
            question_id=answer_data.question_id,
            audit_id=answer_data.audit_id,
            campaign_id=answer_data.campaign_id,
            answered_by=answered_by_id,
            answer_value=answer_data.answer_value,
            status=answer_data.status,
            compliance_status=compliance_status,  # ✅ Ajout du compliance_status
            version=1,
            is_current=True,
            answered_at=datetime.utcnow()
        )

    db.add(new_answer)
    db.commit()
    db.refresh(new_answer)

    return QuestionAnswerResponse.model_validate(new_answer)


# ============================================================================
# SOUMETTRE L'AUDIT
# ============================================================================

@router.post("/{audit_id}/submit", response_model=SubmitAuditResponse)
async def submit_audit(
    audit_id: UUID,
    request: SubmitAuditRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user_keycloak)
):
    """
    Soumet toutes les réponses de l'audit
    Vérifie que toutes les questions mandatory sont répondues
    Envoie les notifications par email aux parties prenantes
    """
    # Support both dict and User object
    user_email = current_user.get("email") if isinstance(current_user, dict) else current_user.email
    logger.info(f"📤 Soumission de l'audit {audit_id} par {user_email}")

    # 🔗 MAGIC LINK: Résoudre le vrai email si c'est un utilisateur temporaire
    real_user_email = user_email
    if user_email and user_email.endswith("@temp.cybergard.local"):
        logger.debug(f"🔗 Magic Link détecté - Récupération du vrai email depuis audit_tokens")

        # Extraire le hash depuis l'email temporaire
        # Format: audite-{campaign_id}-{hash}@temp.cybergard.local
        temp_username = user_email.split("@")[0]
        email_hash = temp_username.split("-")[-1]

        # Récupérer tous les emails de la campagne et trouver celui qui correspond au hash
        real_email_query = text("""
            SELECT user_email FROM audit_tokens
            WHERE revoked = false
            LIMIT 100
        """)

        token_results = db.execute(real_email_query).fetchall()

        # Chercher l'email dont le hash correspond
        import hashlib
        for row in token_results:
            candidate_email = row.user_email
            candidate_hash = hashlib.sha256(candidate_email.encode()).hexdigest()[:8]

            if candidate_hash == email_hash:
                real_user_email = candidate_email
                logger.info(f"✅ Magic Link résolu: {user_email} → {real_user_email}")
                break

        if real_user_email == user_email:
            logger.warning(f"⚠️ Impossible de résoudre le Magic Link: {user_email}")

    # Récupérer l'audit et vérifier le statut de la campagne
    audit = db.query(Audit).filter(Audit.id == audit_id).first()
    if not audit:
        raise HTTPException(status_code=404, detail="Audit non trouvé")

    # Vérifier le statut de la campagne associée
    campaign_query = text("""
        SELECT c.id as campaign_id, c.status, c.frozen_date
        FROM campaign c
        JOIN audit a ON a.name LIKE CONCAT('%', c.title, '%')
        WHERE a.id = :audit_id
        LIMIT 1
    """)
    campaign_result = db.execute(campaign_query, {"audit_id": str(audit_id)}).fetchone()

    if campaign_result and campaign_result.status == 'frozen':
        logger.warning(f"❌ Tentative de soumission sur campagne figée (frozen): {campaign_result.campaign_id}")
        raise HTTPException(
            status_code=403,
            detail=f"Cette campagne est figée depuis le {campaign_result.frozen_date.strftime('%d/%m/%Y') if campaign_result.frozen_date else 'N/A'}. Aucune soumission n'est possible."
        )

    # Récupérer toutes les réponses actuelles
    answers = db.query(QuestionAnswer).filter(
        QuestionAnswer.audit_id == audit_id,
        QuestionAnswer.is_current == True
    ).all()

    if not answers:
        raise HTTPException(
            status_code=400,
            detail="Aucune réponse trouvée pour cet audit"
        )

    # Récupérer le questionnaire pour vérifier les questions mandatory
    # On assume que toutes les questions sont du même questionnaire
    first_question = db.query(Question).filter(
        Question.id == answers[0].question_id
    ).first()

    if not first_question:
        raise HTTPException(status_code=404, detail="Question non trouvée")

    questionnaire_id = first_question.questionnaire_id

    # 🔐 IMPORTANT: Vérifier les questions mandatory UNIQUEMENT dans le périmètre de l'utilisateur
    # Un utilisateur avec périmètre limité ne doit pas être bloqué par des questions hors périmètre

    # Récupérer la campaign_id depuis les réponses
    campaign_id_from_answers = answers[0].campaign_id if answers else None

    # Récupérer le périmètre de l'utilisateur (domain_ids)
    user_domain_scope_query = text("""
        SELECT
            COALESCE(ads.all_domains, false) as all_domains,
            ads.domain_ids,
            em.id as member_id
        FROM entity_member em
        LEFT JOIN audite_domain_scope ads
            ON ads.entity_member_id = em.id
            AND ads.campaign_id = CAST(:campaign_id AS uuid)
        WHERE em.email = :user_email
          AND em.is_active = true
        LIMIT 1
    """)

    domain_scope_result = db.execute(
        user_domain_scope_query,
        {
            "user_email": real_user_email,  # ✅ Utiliser le vrai email résolu
            "campaign_id": str(campaign_id_from_answers) if campaign_id_from_answers else None
        }
    ).fetchone()

    logger.info(f"🔍 Scope check: user={real_user_email}, all_domains={domain_scope_result.all_domains if domain_scope_result else 'N/A'}, domain_ids={domain_scope_result.domain_ids if domain_scope_result else 'N/A'}")

    # Si l'utilisateur a un périmètre limité, filtrer les questions obligatoires
    if domain_scope_result and not domain_scope_result.all_domains and domain_scope_result.domain_ids:
        # Filtrer questions dans le périmètre de l'utilisateur
        accessible_domain_ids = domain_scope_result.domain_ids
        logger.info(f"🔒 Vérification périmètre soumission - Domaines accessibles: {accessible_domain_ids}")

        mandatory_questions_query = text("""
            SELECT DISTINCT q.id
            FROM question q
            JOIN requirement r ON q.requirement_id = r.id
            WHERE q.questionnaire_id = CAST(:questionnaire_id AS uuid)
              AND q.is_required = true
              AND q.is_active = true
              AND CAST(r.domain_id AS uuid) = ANY(CAST(:domain_ids AS uuid[]))
        """)

        mandatory_results = db.execute(
            mandatory_questions_query,
            {
                "questionnaire_id": str(questionnaire_id),
                "domain_ids": [str(d) for d in accessible_domain_ids]
            }
        ).fetchall()

        mandatory_question_ids = {row.id for row in mandatory_results}
        logger.info(f"✅ {len(mandatory_question_ids)} questions obligatoires dans le périmètre utilisateur")
    else:
        # Utilisateur avec accès complet ou admin
        mandatory_questions = db.query(Question).filter(
            Question.questionnaire_id == questionnaire_id,
            Question.is_required == True,
            Question.is_active == True
        ).all()
        mandatory_question_ids = {q.id for q in mandatory_questions}
        logger.info(f"✅ {len(mandatory_question_ids)} questions obligatoires (accès complet)")

    answered_question_ids = {answer.question_id for answer in answers}

    unanswered_mandatory = mandatory_question_ids - answered_question_ids

    if unanswered_mandatory:
        logger.warning(f"❌ {len(unanswered_mandatory)} questions obligatoires non répondues: {unanswered_mandatory}")
        raise HTTPException(
            status_code=400,
            detail=f"{len(unanswered_mandatory)} question(s) obligatoire(s) non répondue(s) dans votre périmètre"
        )

    # Marquer toutes les réponses comme soumises
    submitted_at = datetime.utcnow()
    for answer in answers:
        answer.status = "submitted"
        answer.submitted_at = submitted_at
        db.add(answer)

    db.commit()

    # ============================================================================
    # ENVOI DES EMAILS DE NOTIFICATION
    # ============================================================================
    logger.info(f"📧 Envoi des emails de notification pour la soumission de l'audit {audit_id}")

    # Récupérer les informations de la campagne via campaign_id des réponses
    campaign_id = answers[0].campaign_id if answers[0].campaign_id else None

    if campaign_id:
        # Récupérer les informations complètes de la campagne
        campaign_info_query = text("""
            SELECT
                c.id as campaign_id,
                c.title as campaign_name,
                c.launch_date,
                c.due_date,
                c.tenant_id,
                o.name as client_name,
                q.name as questionnaire_name,
                f.name as framework_name
            FROM campaign c
            LEFT JOIN organization o ON o.tenant_id = c.tenant_id
            LEFT JOIN questionnaire q ON q.id = c.questionnaire_id
            LEFT JOIN framework f ON q.framework_id = f.id
            WHERE c.id = :campaign_id
        """)
        campaign_info = db.execute(campaign_info_query, {"campaign_id": str(campaign_id)}).fetchone()

        if campaign_info:
            # Récupérer les informations de l'audité qui soumet
            # D'abord, gérer le cas du Magic Link (email temporaire)
            actual_user_email = user_email
            if user_email and user_email.endswith("@temp.cybergard.local"):
                # Extraire le hash et retrouver le vrai email
                temp_username = user_email.split("@")[0]
                email_hash = temp_username.split("-")[-1]

                real_email_query = text("""
                    SELECT user_email
                    FROM audit_tokens
                    WHERE campaign_id = :campaign_id
                      AND revoked = false
                """)
                all_emails = db.execute(real_email_query, {"campaign_id": str(campaign_id)}).fetchall()

                import hashlib
                for row in all_emails:
                    candidate_email = row.user_email
                    candidate_hash = hashlib.sha256(candidate_email.encode()).hexdigest()[:8]
                    if candidate_hash == email_hash:
                        actual_user_email = candidate_email
                        logger.info(f"✅ Email réel récupéré: {actual_user_email}")
                        break

            # Récupérer les infos de l'audité
            audite_info_query = text("""
                SELECT id, first_name, last_name, email
                FROM entity_member
                WHERE email = :email
                LIMIT 1
            """)
            audite_info = db.execute(audite_info_query, {"email": actual_user_email}).fetchone()

            if audite_info:
                audite_name = f"{audite_info.first_name} {audite_info.last_name}"
                submission_date_str = submitted_at.strftime("%d/%m/%Y à %H:%M")
                total_questions = len(mandatory_question_ids)  # On utilise le total des questions obligatoires
                answered_questions = len(answers)
                framework_name = campaign_info.framework_name or "Non spécifié"
                client_name = campaign_info.client_name or "Non spécifié"
                campaign_name = campaign_info.campaign_name

                # ============================================================================
                # 1. EMAIL À L'AUDITÉ (confirmation de soumission)
                # ============================================================================
                try:
                    send_audite_submission_email(
                        to_email=actual_user_email,
                        audite_name=audite_name,
                        campaign_name=campaign_name,
                        client_name=client_name,
                        submission_date=submission_date_str,
                        total_questions=total_questions,
                        answered_questions=answered_questions,
                        framework_name=framework_name
                    )
                    logger.info(f"✅ Email de confirmation envoyé à l'audité {actual_user_email}")
                except Exception as e:
                    logger.error(f"❌ Erreur envoi email audité: {e}")

                # ============================================================================
                # 2. EMAIL AUX AUDITEURS (notification de revue)
                # ============================================================================
                # Récupérer les auditeurs de la campagne (role = 'auditor' dans campaign_user)
                auditeurs_query = text("""
                    SELECT u.id, u.email, u.first_name, u.last_name
                    FROM campaign_user cu
                    JOIN users u ON cu.user_id = u.id
                    WHERE cu.campaign_id = :campaign_id
                      AND cu.role = 'auditor'
                      AND cu.is_active = true
                """)
                auditeurs = db.execute(auditeurs_query, {"campaign_id": str(campaign_id)}).fetchall()

                for auditeur in auditeurs:
                    try:
                        auditeur_name = f"{auditeur.first_name} {auditeur.last_name}"
                        review_url = f"{FRONTEND_URL}/client/campagnes/{campaign_id}"

                        send_auditeur_submission_email(
                            to_email=auditeur.email,
                            auditeur_name=auditeur_name,
                            audite_name=audite_name,
                            campaign_name=campaign_name,
                            client_name=client_name,
                            submission_date=submission_date_str,
                            total_questions=total_questions,
                            answered_questions=answered_questions,
                            framework_name=framework_name,
                            review_url=review_url
                        )
                        logger.info(f"✅ Email de notification envoyé à l'auditeur {auditeur.email}")
                    except Exception as e:
                        logger.error(f"❌ Erreur envoi email auditeur {auditeur.email}: {e}")

                # ============================================================================
                # 3. EMAIL AU CHEF DE PROJET (mise à jour de la campagne)
                # ============================================================================
                # Récupérer le chef de projet (role = 'manager' ou 'owner' dans campaign_user)
                chefs_projet_query = text("""
                    SELECT u.id, u.email, u.first_name, u.last_name
                    FROM campaign_user cu
                    JOIN users u ON cu.user_id = u.id
                    WHERE cu.campaign_id = :campaign_id
                      AND cu.role IN ('owner', 'manager')
                      AND cu.is_active = true
                """)
                chefs_projet = db.execute(chefs_projet_query, {"campaign_id": str(campaign_id)}).fetchall()

                # Calculer le nombre total d'audités et le nombre ayant soumis
                total_audites_query = text("""
                    SELECT COUNT(DISTINCT em.id) as total
                    FROM entity_member em
                    JOIN campaign_scope cs ON cs.id = (SELECT scope_id FROM campaign WHERE id = :campaign_id)
                    WHERE em.entity_id = ANY(cs.entity_ids)
                      AND em.roles::jsonb @> '"AUDITE_RESP"'
                """)
                total_audites_result = db.execute(total_audites_query, {"campaign_id": str(campaign_id)}).fetchone()
                total_audites = total_audites_result.total if total_audites_result else 1

                # Compter les audits soumis pour cette campagne
                submitted_audites_query = text("""
                    SELECT COUNT(DISTINCT qa.audit_id) as submitted
                    FROM question_answer qa
                    WHERE qa.campaign_id = :campaign_id
                      AND qa.status = 'submitted'
                      AND qa.is_current = true
                """)
                submitted_audites_result = db.execute(submitted_audites_query, {"campaign_id": str(campaign_id)}).fetchone()
                submitted_audites = submitted_audites_result.submitted if submitted_audites_result else 1

                for chef_projet in chefs_projet:
                    try:
                        chef_projet_name = f"{chef_projet.first_name} {chef_projet.last_name}"
                        campaign_url = f"{FRONTEND_URL}/client/campagnes/{campaign_id}"

                        send_chef_projet_submission_email(
                            to_email=chef_projet.email,
                            chef_projet_name=chef_projet_name,
                            audite_name=audite_name,
                            campaign_name=campaign_name,
                            client_name=client_name,
                            submission_date=submission_date_str,
                            total_questions=total_questions,
                            answered_questions=answered_questions,
                            framework_name=framework_name,
                            campaign_url=campaign_url,
                            total_audites=total_audites,
                            submitted_audites=submitted_audites
                        )
                        logger.info(f"✅ Email de mise à jour envoyé au chef de projet {chef_projet.email}")
                    except Exception as e:
                        logger.error(f"❌ Erreur envoi email chef de projet {chef_projet.email}: {e}")

            else:
                logger.warning(f"⚠️ Informations de l'audité non trouvées pour {actual_user_email}")
        else:
            logger.warning(f"⚠️ Informations de la campagne non trouvées pour {campaign_id}")
    else:
        logger.info("ℹ️ Pas de campaign_id - mode test, pas d'envoi d'emails")

    return SubmitAuditResponse(
        success=True,
        message="Audit soumis avec succès",
        submitted_at=submitted_at,
        total_answers=len(answers),
        audit_id=audit_id
    )


# ============================================================================
# PROGRESSION
# ============================================================================

@router.get("/{audit_id}/progress/{questionnaire_id}", response_model=ProgressResponse)
async def get_progress(
    audit_id: UUID,
    questionnaire_id: UUID,
    db: Session = Depends(get_db)
):
    """
    Récupère la progression de l'audit
    """
    # Récupérer toutes les questions
    questions = db.query(Question).filter(
        Question.questionnaire_id == questionnaire_id,
        Question.is_active == True
    ).all()

    # Récupérer les réponses
    answers = db.query(QuestionAnswer).filter(
        QuestionAnswer.audit_id == audit_id,
        QuestionAnswer.is_current == True
    ).all()

    answered_question_ids = {answer.question_id for answer in answers}

    total_questions = len(questions)
    answered_questions = len(answers)
    mandatory_questions = len([q for q in questions if q.is_required])
    mandatory_answered = len([
        q for q in questions
        if q.is_required and q.id in answered_question_ids
    ])

    progress_percentage = (answered_questions / total_questions * 100) if total_questions > 0 else 0
    can_submit = mandatory_answered == mandatory_questions

    last_updated = max([a.updated_at for a in answers]) if answers else None

    return ProgressResponse(
        audit_id=audit_id,
        questionnaire_id=questionnaire_id,
        total_questions=total_questions,
        answered_questions=answered_questions,
        mandatory_questions=mandatory_questions,
        mandatory_answered=mandatory_answered,
        progress_percentage=round(progress_percentage, 2),
        can_submit=can_submit,
        last_updated=last_updated
    )
