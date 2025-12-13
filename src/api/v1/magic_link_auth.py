"""
Endpoint API pour l'authentification via Magic Link avec Keycloak
Architecture sécurisée : Magic Token (BDD) → Token Keycloak → Accès Questionnaire
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Dict
from uuid import UUID
import hashlib
import logging

from src.database import get_db
from src.services.magic_link_service import validate_magic_token
from src.services.keycloak_service import get_keycloak_service, KeycloakService
from src.models.audit_token import AuditToken

logger = logging.getLogger(__name__)
router = APIRouter()


class MagicLinkExchangeRequest(BaseModel):
    """Requête pour échanger un magic token contre un token Keycloak"""
    magic_token: str


class MagicLinkExchangeResponse(BaseModel):
    """Réponse avec le token Keycloak et les infos d'audit"""
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str = "Bearer"

    # Informations pour redirection
    audit_id: str
    questionnaire_id: str
    campaign_id: str
    user_email: str


@router.post("/exchange", response_model=MagicLinkExchangeResponse)
async def exchange_magic_link_for_keycloak_token(
    request: Request,
    payload: MagicLinkExchangeRequest,
    db: Session = Depends(get_db),
    keycloak: KeycloakService = Depends(get_keycloak_service)
):
    """
    Échange un magic token contre un token Keycloak sécurisé

    Flow :
    1. Valide le magic_token (JWT custom)
    2. Vérifie en BDD que le token est valide/non-révoqué
    3. Crée/Récupère un compte Keycloak temporaire pour l'audité
    4. Génère un token Keycloak pour ce compte
    5. Retourne le token Keycloak + infos de redirection

    Args:
        payload: Contient le magic_token à échanger
        db: Session de base de données
        keycloak: Service Keycloak

    Returns:
        Token Keycloak + informations pour accéder au questionnaire

    Raises:
        HTTPException: Si le token est invalide, expiré ou révoqué
    """
    try:
        # 1. Récupérer l'IP et User-Agent pour audit trail
        client_ip = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")

        logger.info(f"🔐 Tentative d'échange magic link - IP: {client_ip}")

        # 2. Valider le magic token (JWT + BDD)
        try:
            magic_payload = validate_magic_token(
                db=db,
                token=payload.magic_token,
                ip_address=client_ip,
                user_agent=user_agent
            )
        except ValueError as e:
            logger.warning(f"❌ Magic token invalide: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Lien d'invitation invalide : {str(e)}"
            )

        # 3. Extraire les informations du payload
        user_email = magic_payload.get("sub")
        campaign_id = magic_payload.get("campaign_id")
        questionnaire_id = magic_payload.get("questionnaire_id")
        tenant_id = magic_payload.get("tenant_id")

        logger.info(f"✅ Magic token valide pour {user_email} - Campaign: {campaign_id}")

        # 3.5 Vérifier les dates de la campagne AVANT d'authentifier l'utilisateur
        from datetime import datetime, date
        from sqlalchemy import text

        campaign_dates_query = text("""
            SELECT launch_date, due_date, status, title
            FROM campaign
            WHERE id = :campaign_id
        """)
        campaign_result = db.execute(campaign_dates_query, {"campaign_id": campaign_id}).fetchone()

        if not campaign_result:
            logger.error(f"❌ Campagne {campaign_id} non trouvée lors de l'échange magic link")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La campagne associée à ce lien n'existe pas"
            )

        today = date.today()

        # Vérifier si la campagne a démarré
        if campaign_result.launch_date:
            launch_date = campaign_result.launch_date
            if isinstance(launch_date, datetime):
                launch_date = launch_date.date()

            if today < launch_date:
                days_until = (launch_date - today).days
                logger.warning(f"⚠️ Accès refusé: campagne {campaign_id} non démarrée - Début le {launch_date}")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"L'audit n'a pas encore commencé. Vous pourrez accéder au questionnaire à partir du {launch_date.strftime('%d/%m/%Y')}."
                )

        # Vérifier si la campagne n'est pas expirée
        if campaign_result.due_date:
            due_date = campaign_result.due_date
            if isinstance(due_date, datetime):
                due_date = due_date.date()

            if today > due_date:
                days_passed = (today - due_date).days
                logger.warning(f"⚠️ Accès refusé: campagne {campaign_id} expirée depuis {days_passed} jour(s)")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Cette campagne d'audit est clôturée. Le questionnaire n'est plus accessible depuis le {due_date.strftime('%d/%m/%Y')}."
                )

        logger.info(f"✅ Dates de campagne valides pour {campaign_id}")

        # 4. Note : Dans ce système, campaign_id sert d'audit_id
        # Le magic link donne accès à un questionnaire dans le contexte d'une campagne
        audit_id = campaign_id

        # 5. Créer ou récupérer le compte Keycloak temporaire pour cet audité
        # Username unique : audite-{campaign_id}-{user_email_hash}
        email_hash = hashlib.sha256(user_email.encode()).hexdigest()[:8]
        keycloak_username = f"audite-{campaign_id}-{email_hash}"
        keycloak_email = f"{keycloak_username}@temp.cybergard.local"

        # Mot de passe temporaire (sera utilisé pour obtenir le token)
        # Format complexe pour respecter les politiques de sécurité Keycloak
        temp_password = f"TempAudit2025!{email_hash.upper()}_{campaign_id[:8]}"

        logger.info(f"🔑 Création/récupération compte Keycloak: {keycloak_username}")

        # 6. Obtenir un token admin pour créer/modifier l'utilisateur Keycloak
        admin_token = await keycloak.get_admin_token()
        if not admin_token:
            logger.error("❌ Impossible d'obtenir le token admin Keycloak")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Erreur de configuration du serveur d'authentification"
            )

        # 7. Vérifier si l'utilisateur Keycloak existe déjà
        existing_user = await keycloak.get_user_by_email(admin_token, keycloak_email)

        if not existing_user:
            # Créer le compte Keycloak temporaire
            logger.info(f"➕ Création nouveau compte Keycloak pour {user_email}")

            # Préparer les données utilisateur au format Keycloak (camelCase)
            user_data = {
                "username": keycloak_username,
                "email": keycloak_email,
                "firstName": "Audité",
                "lastName": "Externe",
                "enabled": True,
                "emailVerified": True,
                "attributes": {
                    "campaign_id": [campaign_id],
                    "questionnaire_id": [questionnaire_id or ""],
                    "tenant_id": [tenant_id],
                    "real_email": [user_email],
                    "role": ["AUDITE_EXTERNE"],
                    "temporary_account": ["true"]
                }
            }

            user_id = await keycloak.create_user(
                admin_token=admin_token,
                user_data=user_data
            )

            if not user_id:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Impossible de créer le compte d'accès"
                )

            # Définir le mot de passe temporaire
            await keycloak.set_user_password(
                admin_token=admin_token,
                user_id=user_id,
                password=temp_password,
                temporary=False
            )

            logger.info(f"✅ Compte Keycloak créé avec succès: {user_id}")
        else:
            logger.info(f"♻️ Compte Keycloak existant réutilisé pour {user_email}")
            # NE PAS réinitialiser le mot de passe si l'utilisateur existe déjà
            # Le mot de passe est déjà défini et fonctionne
            logger.debug(f"ℹ️ Réutilisation du mot de passe existant pour {keycloak_username}")

        # 8. Obtenir un token Keycloak pour cet utilisateur (grant_type=password)
        logger.info(f"🎫 Génération token Keycloak pour {keycloak_username}")

        # IMPORTANT: Utiliser l'email pour l'authentification (plus fiable que username dans Keycloak)
        # Après un reset de mot de passe, attendre un court instant pour la synchronisation
        import asyncio
        await asyncio.sleep(0.5)  # Attendre 500ms pour que Keycloak synchronise le mot de passe

        logger.debug(f"🔐 Authentification avec email: {keycloak_email} et password: {temp_password[:10]}...")

        token_response = await keycloak.exchange_code_for_token(
            code=None,  # Pas de code OAuth, on utilise password grant
            redirect_uri=None,
            username=keycloak_email,  # Toujours utiliser l'email
            password=temp_password,
            grant_type="password"
        )

        if not token_response:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Impossible d'obtenir le token d'accès"
            )

        logger.info(f"✅ Token Keycloak généré avec succès pour {user_email}")

        # 9. Créer/vérifier l'entrée entity_member pour l'audité
        from sqlalchemy import text

        # Récupérer tous les entity_ids depuis la campagne (via campaign_scope)
        entity_query = text("""
            SELECT cs.entity_ids
            FROM campaign c
            JOIN campaign_scope cs ON c.scope_id = cs.id
            WHERE c.id = :campaign_id
            LIMIT 1
        """)
        entity_result = db.execute(entity_query, {"campaign_id": campaign_id}).fetchone()

        if entity_result:
            campaign_entity_ids = entity_result.entity_ids

            # Vérifier si l'utilisateur existe dans entity_member pour l'une des entités de la campagne
            member_check_query = text("""
                SELECT id, entity_id FROM entity_member
                WHERE email = :email AND entity_id = ANY(:entity_ids)
                LIMIT 1
            """)
            existing_member = db.execute(member_check_query, {
                "email": user_email,
                "entity_ids": campaign_entity_ids
            }).fetchone()

            if existing_member:
                # L'utilisateur existe déjà dans une des entités de la campagne - OK !
                entity_id = existing_member.entity_id
                logger.debug(f"✅ Utilisateur {user_email} trouvé dans l'entité {entity_id} (fait partie du scope de la campagne)")
            else:
                # L'utilisateur n'existe dans aucune des entités de la campagne
                # Vérifier s'il existe dans une autre entité (hors scope de la campagne)
                global_email_check = text("""
                    SELECT em.id, em.entity_id, ee.name as entity_name
                    FROM entity_member em
                    LEFT JOIN ecosystem_entity ee ON em.entity_id = ee.id
                    WHERE em.email = :email AND em.entity_id != ALL(:entity_ids)
                    LIMIT 1
                """)
                existing_in_other_entity = db.execute(global_email_check, {
                    "email": user_email,
                    "entity_ids": campaign_entity_ids
                }).fetchone()

                if existing_in_other_entity:
                    logger.error(
                        f"❌ DUPLICATION DÉTECTÉE: {user_email} existe déjà dans l'entité "
                        f"'{existing_in_other_entity.entity_name}' ({existing_in_other_entity.entity_id}). "
                        f"Cette entité ne fait pas partie du scope de la campagne."
                    )
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"Cet email est déjà associé à une autre entité ({existing_in_other_entity.entity_name})"
                    )

                # 🔒 SÉCURITÉ: Le magic link ne doit PAS créer automatiquement un entity_member
                # L'utilisateur DOIT déjà exister dans entity_member (ajouté lors du lancement de campagne)
                logger.error(
                    f"🚨 ACCÈS REFUSÉ: {user_email} n'existe pas dans entity_member pour aucune entité du scope de la campagne. "
                    f"Le magic link ne peut pas créer automatiquement un utilisateur."
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Accès non autorisé. Votre email n'est pas enregistré pour cette campagne."
                )

            logger.debug(f"✅ Entrée entity_member validée pour {user_email}")

        # 10. Retourner le token Keycloak + infos de redirection
        return MagicLinkExchangeResponse(
            access_token=token_response["access_token"],
            refresh_token=token_response["refresh_token"],
            expires_in=token_response.get("expires_in", 300),
            audit_id=audit_id,
            questionnaire_id=questionnaire_id or "",
            campaign_id=campaign_id,
            user_email=user_email
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur lors de l'échange magic link: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de l'authentification: {str(e)}"
        )


@router.get("/validate")
async def validate_magic_link_token(
    token: str,
    db: Session = Depends(get_db)
):
    """
    Endpoint pour valider rapidement un magic token (sans l'échanger)
    Utile pour vérifier si un lien est encore valide avant de l'utiliser

    Args:
        token: Magic token à valider
        db: Session de base de données

    Returns:
        Informations sur la validité du token
    """
    try:
        # Valider sans incrémenter le compteur d'utilisation
        # (on ne fait que vérifier, pas consommer)
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        audit_token = db.query(AuditToken).filter(
            AuditToken.token_hash == token_hash
        ).first()

        if not audit_token:
            return {
                "valid": False,
                "reason": "Token non trouvé"
            }

        if audit_token.revoked:
            return {
                "valid": False,
                "reason": "Token révoqué"
            }

        from datetime import datetime
        if audit_token.expires_at < datetime.utcnow():
            return {
                "valid": False,
                "reason": "Token expiré"
            }

        if audit_token.used_count >= audit_token.max_uses:
            return {
                "valid": False,
                "reason": f"Nombre maximal d'utilisations atteint ({audit_token.max_uses})"
            }

        return {
            "valid": True,
            "user_email": audit_token.user_email,
            "campaign_id": str(audit_token.campaign_id),
            "uses_remaining": audit_token.max_uses - audit_token.used_count,
            "expires_at": audit_token.expires_at.isoformat()
        }

    except Exception as e:
        logger.error(f"❌ Erreur validation magic link: {e}")
        return {
            "valid": False,
            "reason": f"Erreur: {str(e)}"
        }
