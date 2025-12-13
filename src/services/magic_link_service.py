"""
Service de génération et validation des liens magiques (Magic Links)
Utilisé pour l'accès direct aux audits sans authentification par mot de passe
"""
import jwt
import hashlib
import uuid
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import select

from src.models.audit_token import AuditToken
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# Configuration
JWT_SECRET = os.getenv("JWT_SECRET", "your-super-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
TOKEN_EXPIRY_DAYS = int(os.getenv("MAGIC_LINK_EXPIRY_DAYS", "7"))
MAX_TOKEN_USES = int(os.getenv("MAGIC_LINK_MAX_USES", "10"))


def generate_magic_link(
    db: Session,
    user_email: str,
    campaign_id: uuid.UUID,
    questionnaire_id: Optional[uuid.UUID],
    tenant_id: uuid.UUID,
    question_id: Optional[uuid.UUID] = None
) -> Tuple[str, AuditToken]:
    """
    Génère un lien magique JWT pour accès direct à un audit
    Réutilise un token existant valide si disponible pour éviter d'invalider les anciens liens

    Args:
        db: Session de base de données
        user_email: Email de l'utilisateur audité
        campaign_id: ID de la campagne d'audit
        questionnaire_id: ID du questionnaire (optionnel)
        tenant_id: ID du tenant
        question_id: ID de la question pour focus direct (optionnel)

    Returns:
        Tuple[str, AuditToken]: (URL du lien magique, objet AuditToken)
    """

    # 0. Vérifier s'il existe déjà un token valide pour cet utilisateur/campagne
    from sqlalchemy import text
    existing_token_query = text("""
        SELECT token_jti, token_hash, expires_at
        FROM audit_tokens
        WHERE user_email = :user_email
          AND campaign_id = :campaign_id
          AND revoked = false
          AND expires_at > NOW()
          AND used_count < max_uses
        ORDER BY created_at DESC
        LIMIT 1
    """)

    existing = db.execute(existing_token_query, {
        "user_email": user_email,
        "campaign_id": str(campaign_id)
    }).fetchone()

    if existing:
        # Réutiliser le token existant
        jti = existing.token_jti
        logger.info(f"♻️ Réutilisation du token existant {jti} pour {user_email} (expire: {existing.expires_at})")
    else:
        # 1. Générer un nouveau JTI unique (JWT ID)
        jti = uuid.uuid4()
        logger.info(f"✨ Génération d'un nouveau token {jti} pour {user_email}")

    # 2. Créer le payload JWT (ou réutiliser celui existant)
    if existing:
        # Récupérer le token existant complet depuis la base
        audit_token = db.query(AuditToken).filter(AuditToken.token_jti == jti).first()
        if not audit_token:
            raise ValueError(f"Token {jti} trouvé dans la requête mais introuvable dans la base")

        # Re-générer le token JWT avec le nouveau question_id si fourni
        payload = {
            "sub": user_email,
            "jti": str(jti),
            "campaign_id": str(campaign_id),
            "questionnaire_id": str(questionnaire_id) if questionnaire_id else None,
            "tenant_id": str(tenant_id),
            "question_id": str(question_id) if question_id else None,
            "exp": audit_token.expires_at,
            "iat": audit_token.created_at,
            "type": "magic_link"
        }
        token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

        # Recalculer et mettre à jour le hash du token en base
        new_token_hash = hashlib.sha256(token.encode()).hexdigest()
        if new_token_hash != audit_token.token_hash:
            logger.info(f"🔄 Mise à jour du hash du token {jti} (question_id={question_id})")
            audit_token.token_hash = new_token_hash
            db.commit()
            db.refresh(audit_token)
    else:
        # Nouveau token - générer tout de zéro
        expires_at = datetime.now(timezone.utc) + timedelta(days=TOKEN_EXPIRY_DAYS)
        payload = {
            "sub": user_email,
            "jti": str(jti),
            "campaign_id": str(campaign_id),
            "questionnaire_id": str(questionnaire_id) if questionnaire_id else None,
            "tenant_id": str(tenant_id),
            "question_id": str(question_id) if question_id else None,
            "exp": expires_at,
            "iat": datetime.now(timezone.utc),
            "type": "magic_link"
        }

        # 3. Signer le token JWT
        token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

        # 4. Calculer le hash du token pour stockage sécurisé
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        # 5. Enregistrer le token en base de données
        audit_token = AuditToken(
            token_jti=jti,
            token_hash=token_hash,
            user_email=user_email,
            campaign_id=campaign_id,
            questionnaire_id=questionnaire_id,
            tenant_id=tenant_id,
            expires_at=expires_at,
            max_uses=MAX_TOKEN_USES,
            used_count=0,
            revoked=False
        )

        db.add(audit_token)
        db.commit()
        db.refresh(audit_token)

    # 6. Construire l'URL du lien magique sécurisé (échange Keycloak)
    # L'utilisateur sera redirigé vers /audit/access qui échangera le token
    # contre un token Keycloak avant d'accéder au questionnaire
    # Si question_id est fourni, l'ajouter comme paramètre pour le focus automatique
    magic_link = f"{FRONTEND_URL}/audit/access?token={token}"
    if question_id:
        magic_link += f"&question={question_id}"

    logger.info(
        f"✨ Lien magique sécurisé généré pour {user_email} - "
        f"Campaign: {campaign_id}, JTI: {jti}, Question: {question_id or 'N/A'}, Expire: {audit_token.expires_at}"
    )

    return magic_link, audit_token


def validate_magic_token(
    db: Session,
    token: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None
) -> Dict:
    """
    Valide un token de lien magique et met à jour les statistiques d'utilisation

    Args:
        db: Session de base de données
        token: Token JWT à valider
        ip_address: Adresse IP de l'utilisateur (optionnel)
        user_agent: User-Agent du navigateur (optionnel)

    Returns:
        Dict: Payload décodé du token

    Raises:
        ValueError: Si le token est invalide, expiré ou révoqué
    """

    try:
        # 1. Décoder le token JWT
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])

        # 2. Vérifier le type de token
        if payload.get("type") != "magic_link":
            raise ValueError("Type de token invalide")

        # 3. Calculer le hash du token
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        # 4. Rechercher le token en base de données
        audit_token = db.execute(
            select(AuditToken).where(
                AuditToken.token_hash == token_hash
            )
        ).scalar_one_or_none()

        if not audit_token:
            logger.warning(f"❌ Token non trouvé en base: {token_hash[:16]}...")
            raise ValueError("Token non trouvé ou déjà utilisé")

        # 5. Vérifier si le token est révoqué
        if audit_token.revoked:
            logger.warning(f"❌ Token révoqué: {audit_token.token_jti}")
            raise ValueError("Token révoqué")

        # 6. Vérifier l'expiration
        if audit_token.expires_at < datetime.now(timezone.utc):
            logger.warning(f"❌ Token expiré: {audit_token.token_jti}")
            raise ValueError("Token expiré")

        # 7. Vérifier le nombre maximal d'utilisations
        if audit_token.used_count >= audit_token.max_uses:
            logger.warning(
                f"❌ Nombre max d'utilisations atteint: {audit_token.token_jti} "
                f"({audit_token.used_count}/{audit_token.max_uses})"
            )
            raise ValueError(f"Nombre maximal d'utilisations atteint ({audit_token.max_uses})")

        # 8. Vérifier les dates de la campagne (si la campagne est toujours active)
        campaign_id = payload.get("campaign_id")
        if campaign_id:
            from sqlalchemy import text
            campaign_query = text("""
                SELECT launch_date, due_date, frozen_date, status
                FROM campaign
                WHERE id = :campaign_id
            """)
            campaign = db.execute(campaign_query, {"campaign_id": str(campaign_id)}).fetchone()

            if campaign:
                current_date = datetime.now(timezone.utc).date()

                # Vérifier si la campagne n'a pas encore commencé
                if campaign.launch_date and current_date < campaign.launch_date:
                    logger.warning(f"❌ Campagne {campaign_id} pas encore lancée (lancement: {campaign.launch_date})")
                    raise ValueError(f"La campagne n'a pas encore démarré. Lancement prévu le {campaign.launch_date.strftime('%d/%m/%Y')}")

                # Vérifier si la campagne est terminée (frozen_date prioritaire sur due_date)
                end_date = campaign.frozen_date if campaign.frozen_date else campaign.due_date
                if end_date and current_date > end_date:
                    logger.warning(f"❌ Campagne {campaign_id} terminée (fin: {end_date})")
                    raise ValueError(f"La campagne est terminée depuis le {end_date.strftime('%d/%m/%Y')}")

                # Vérifier le statut de la campagne
                if campaign.status not in ['ongoing', 'active', 'launched']:
                    logger.warning(f"❌ Campagne {campaign_id} dans un état invalide: {campaign.status}")
                    raise ValueError(f"La campagne n'est plus active (statut: {campaign.status})")

                logger.debug(f"✅ Campagne {campaign_id} valide et active (statut: {campaign.status})")
            else:
                logger.warning(f"⚠️ Campagne {campaign_id} non trouvée en base de données")

        # 9. Mettre à jour les statistiques d'utilisation
        audit_token.used_count += 1
        audit_token.last_used_at = datetime.now(timezone.utc)

        if audit_token.used_count == 1:
            audit_token.first_used_at = datetime.now(timezone.utc)

        if ip_address:
            audit_token.last_used_ip = ip_address

        if user_agent:
            audit_token.last_user_agent = user_agent

        db.commit()

        logger.info(
            f"✅ Token validé: {audit_token.user_email} - "
            f"Utilisation {audit_token.used_count}/{audit_token.max_uses}"
        )

        return payload

    except jwt.ExpiredSignatureError:
        logger.warning("❌ Token JWT expiré")
        raise ValueError("Token expiré")

    except jwt.InvalidTokenError as e:
        logger.warning(f"❌ Token JWT invalide: {e}")
        raise ValueError("Token invalide")

    except Exception as e:
        logger.error(f"❌ Erreur validation token: {e}")
        raise ValueError(f"Erreur de validation: {str(e)}")


def revoke_magic_token(db: Session, token_jti: uuid.UUID) -> bool:
    """
    Révoque un token de lien magique

    Args:
        db: Session de base de données
        token_jti: JWT ID du token à révoquer

    Returns:
        bool: True si le token a été révoqué, False sinon
    """

    audit_token = db.execute(
        select(AuditToken).where(
            AuditToken.token_jti == token_jti
        )
    ).scalar_one_or_none()

    if not audit_token:
        logger.warning(f"❌ Token JTI non trouvé: {token_jti}")
        return False

    audit_token.revoked = True
    db.commit()

    logger.info(f"🔒 Token révoqué: {token_jti} (email: {audit_token.user_email})")
    return True


def revoke_all_campaign_tokens(db: Session, campaign_id: uuid.UUID) -> int:
    """
    Révoque tous les tokens d'une campagne (à la fin de la campagne par exemple)

    Args:
        db: Session de base de données
        campaign_id: ID de la campagne

    Returns:
        int: Nombre de tokens révoqués
    """

    tokens = db.execute(
        select(AuditToken).where(
            AuditToken.campaign_id == campaign_id,
            AuditToken.revoked == False
        )
    ).scalars().all()

    count = 0
    for token in tokens:
        token.revoked = True
        count += 1

    db.commit()

    logger.info(f"🔒 {count} token(s) révoqué(s) pour la campagne {campaign_id}")
    return count


def get_token_stats(db: Session, campaign_id: uuid.UUID) -> Dict:
    """
    Récupère les statistiques d'utilisation des tokens d'une campagne

    Args:
        db: Session de base de données
        campaign_id: ID de la campagne

    Returns:
        Dict: Statistiques des tokens
    """

    tokens = db.execute(
        select(AuditToken).where(
            AuditToken.campaign_id == campaign_id
        )
    ).scalars().all()

    total = len(tokens)
    active = sum(1 for t in tokens if t.is_valid)
    revoked = sum(1 for t in tokens if t.revoked)
    expired = sum(1 for t in tokens if t.expires_at < datetime.now(timezone.utc) and not t.revoked)
    used = sum(1 for t in tokens if t.used_count > 0)
    total_uses = sum(t.used_count for t in tokens)

    return {
        "total_tokens": total,
        "active_tokens": active,
        "revoked_tokens": revoked,
        "expired_tokens": expired,
        "used_tokens": used,
        "total_uses": total_uses,
        "avg_uses_per_token": round(total_uses / total, 2) if total > 0 else 0
    }
