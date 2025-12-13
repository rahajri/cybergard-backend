"""
Dependencies FastAPI pour l'authentification Keycloak
"""
from typing import Optional
from fastapi import Depends, HTTPException, status, Request, Cookie
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
import logging

from src.services.keycloak_service import get_keycloak_service, KeycloakService
from src.database import get_db
from src.models.audit import User

logger = logging.getLogger(__name__)

# Security scheme pour JWT
security = HTTPBearer(auto_error=False)


async def get_current_user_keycloak(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
    keycloak: KeycloakService = Depends(get_keycloak_service)
) -> User | dict:
    """
    Dependency FastAPI pour obtenir l'utilisateur via Keycloak.

    Supporte deux méthodes d'authentification :
    1. Header Authorization: Bearer <token>
    2. Cookie: access_token=<token>

    Args:
        request: Requête FastAPI
        credentials: Credentials du header Authorization (optionnel)
        access_token: Token depuis le cookie (optionnel)
        db: Session de base de données
        keycloak: Service Keycloak

    Returns:
        - User object: Pour les utilisateurs normaux (créé/récupéré en BDD)
        - dict: Pour les utilisateurs Magic Link temporaires (claims Keycloak)

    Raises:
        HTTPException 401: Si le token est invalide
        HTTPException 403: Si l'utilisateur est inactif
    """
    from sqlalchemy import select

    # 1. Récupérer le token depuis le header, le cookie ou le query parameter
    jwt_token = None

    if credentials:
        jwt_token = credentials.credentials
        logger.debug("✅ Token récupéré depuis Authorization header")
    else:
        # Accéder directement au cookie "token" via request.cookies
        cookie_token = request.cookies.get("token")
        if cookie_token:
            jwt_token = cookie_token
            logger.debug(f"✅ Token récupéré depuis cookie 'token' (longueur: {len(cookie_token)} chars, début: {cookie_token[:50]}...)")
        else:
            # Fallback: Query parameter (pour SSE qui ne supporte pas les headers custom)
            query_token = request.query_params.get("token")
            if query_token:
                jwt_token = query_token
                logger.debug(f"✅ Token récupéré depuis query parameter (longueur: {len(query_token)} chars)")

    if not jwt_token:
        logger.warning(f"❌ Aucun token trouvé. Cookies disponibles: {list(request.cookies.keys())}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Non authentifié. Token manquant.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 2. Valider le token avec Keycloak
    try:
        token_payload = await keycloak.verify_token(jwt_token)
        logger.debug(f"✅ Token Keycloak validé")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur validation token Keycloak: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide"
        )

    # 3. Extraire les informations utilisateur
    user_claims = keycloak.extract_user_claims(token_payload)
    email = user_claims.get("email")

    if not email:
        logger.error("❌ Token Keycloak sans email")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide: email manquant"
        )

    logger.debug(f"✅ Utilisateur authentifié via Keycloak: {email}")

    # Déterminer si c'est un utilisateur Magic Link (temporaire) ou un utilisateur normal
    is_magic_link_user = email.endswith("@temp.cybergard.local")

    if is_magic_link_user:
        # Pour les audités Magic Link (comptes temporaires), on retourne directement les claims
        # Mais on doit récupérer le vrai email depuis entity_member
        logger.debug(f"🔗 Utilisateur Magic Link temporaire: {email}")

        # Récupérer le vrai email depuis entity_member en matchant sur le keycloak_id
        # Le email temporaire Keycloak suit le format: audite-{campaign_id}-{hash}@temp.cybergard.local
        # On peut extraire le campaign_id et retrouver l'audité via les entrées entity_member
        from sqlalchemy import text

        # Chercher l'utilisateur dans entity_member dont l'email n'est pas temporaire
        # On utilise le keycloak_id (sub) pour le matching si disponible, sinon on cherche par pattern
        keycloak_sub = user_claims.get("keycloak_id")

        # Pour simplifier, on cherche tous les entity_member avec roles audite_resp
        # et on trouve celui qui correspond (pour l'instant, on prend le premier)
        # TODO: Améliorer en stockant le keycloak_id dans entity_member

        # En attendant, on retourne les claims tels quels
        # Le mapping sera géré dans les endpoints individuels
        return user_claims

    # Pour les utilisateurs normaux, on récupère/crée l'utilisateur en BDD
    from sqlalchemy import select
    user = db.execute(
        select(User).where(User.email == email)
    ).scalar_one_or_none()

    if not user:
        # Créer l'utilisateur s'il n'existe pas encore
        logger.info(f"👤 Création nouvel utilisateur: {email}")
        user = await _create_user_from_keycloak(db, user_claims)
    else:
        # Mettre à jour la dernière connexion
        from datetime import datetime, timezone
        user.last_login_at = datetime.now(timezone.utc)

        # 🔒 Synchroniser les rôles à chaque authentification
        user_roles = user_claims.get("roles", [])
        logger.debug(f"🔑 Rôles récupérés depuis user_claims pour {email}: {user_roles}")
        _sync_user_roles_from_keycloak(db, user, user_roles)

        db.commit()

        # 🔄 Recharger la relation roles après synchronisation
        db.refresh(user)

        logger.debug(f"👤 Utilisateur existant: {email} (ID: {user.id}, Rôles synchronisés: {user_roles})")
        logger.debug(f"👤 Rôles chargés depuis ORM: {[r.code for r in user.roles] if user.roles else []}")

    return user


async def _create_user_from_keycloak(db: Session, user_claims: dict) -> User:
    """
    Crée un utilisateur dans la base de données locale à partir des claims Keycloak

    Args:
        db: Session de base de données
        user_claims: Claims extraits du token Keycloak

    Returns:
        Nouvel utilisateur créé
    """
    from src.models.tenant import Tenant
    from src.models.organization import Organization
    import uuid

    # 🔒 SÉCURITÉ : Récupérer le tenant depuis Keycloak
    tenant_id = user_claims.get("tenant_id")
    user_roles = user_claims.get("roles", [])

    # Vérifier si l'utilisateur est super-admin (exemption de tenant)
    is_super_admin = "super_admin" in user_roles or "platform_admin" in user_roles

    if not tenant_id and not is_super_admin:
        # 🔒 CRITIQUE : Refuser l'authentification si tenant_id manque
        # Au lieu de créer un tenant "default" qui viole l'isolation
        logger.error(f"❌ Refus d'authentification pour {user_claims['email']}: tenant_id manquant et utilisateur non super-admin")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Votre compte n'est pas correctement configuré. Contactez l'administrateur pour vous assigner à un tenant."
        )

    # Super-admin: tenant_id peut être NULL
    if is_super_admin and not tenant_id:
        tenant_id = None
        logger.info(f"✅ Super-admin détecté: {user_claims['email']} (tenant_id=NULL autorisé)")

    # Créer l'utilisateur
    user = User(
        id=uuid.uuid4(),
        email=user_claims["email"],
        first_name=user_claims.get("first_name", ""),
        last_name=user_claims.get("last_name", ""),
        keycloak_id=user_claims["keycloak_id"],
        tenant_id=tenant_id,
        is_active=True,
        is_email_verified=user_claims.get("email_verified", False),
        password_hash=""  # Pas de mot de passe local, géré par Keycloak
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    # 🔒 Synchroniser les rôles depuis Keycloak
    _sync_user_roles_from_keycloak(db, user, user_roles)

    logger.info(f"✅ Nouvel utilisateur créé: {user.email} (ID: {user.id}, Rôles: {user_roles})")
    return user


def _sync_user_roles_from_keycloak(db: Session, user: User, keycloak_roles: list[str]) -> None:
    """
    Synchronise les rôles de l'utilisateur depuis Keycloak vers la base de données.

    🔄 COMPORTEMENT HYBRIDE (Post-réinitialisation Keycloak):
    - Si Keycloak renvoie des rôles → On synchronise (remplace les rôles DB par ceux de Keycloak)
    - Si Keycloak ne renvoie RIEN → On CONSERVE les rôles assignés via l'UI RBAC en base

    Cela permet de :
    - Fonctionner après une réinitialisation de Keycloak (rôles gérés côté DB)
    - Conserver la possibilité de synchroniser depuis Keycloak si les rôles y sont configurés

    Args:
        db: Session de base de données
        user: Utilisateur à synchroniser
        keycloak_roles: Liste des codes de rôles depuis Keycloak (peut être vide)
    """
    from src.models.role import Role, user_role
    from sqlalchemy import select, delete

    # Mapper les noms de rôles Keycloak vers les codes en base
    # Keycloak peut renvoyer: "super_admin", "chef_projet", "admin", etc.
    role_mapping = {
        "admin": "ADMIN",
        "super_admin": "SUPER_ADMIN",
        "platform_admin": "SUPER_ADMIN",
        "chef_projet": "CHEF_PROJET",
        "rssi": "RSSI",
        "dir_conformite_dpo": "DIR_CONFORMITE_DPO",
        "dpo_externe": "DPO_EXTERNE",
        "rssi_externe": "RSSI_EXTERNE",
        "auditeur": "AUDITEUR",
        "audite_resp": "AUDITE_RESP",
        "audite_contrib": "AUDITE_CONTRIB",
    }

    # Normaliser les rôles Keycloak
    normalized_roles = []
    for kc_role in keycloak_roles:
        kc_role_lower = kc_role.lower()
        if kc_role_lower in role_mapping:
            normalized_roles.append(role_mapping[kc_role_lower])
        elif kc_role.upper() in ["ADMIN", "SUPER_ADMIN", "CHEF_PROJET", "RSSI", "DIR_CONFORMITE_DPO", "AUDITEUR", "AUDITE_RESP", "AUDITE_CONTRIB"]:
            normalized_roles.append(kc_role.upper())

    # 🔄 COMPORTEMENT HYBRIDE : Si Keycloak ne renvoie RIEN, on CONSERVE les rôles en base
    # Cela permet de fonctionner après une réinitialisation de Keycloak
    if not normalized_roles:
        # Vérifier si l'utilisateur a déjà des rôles en base
        existing_roles = db.execute(
            select(user_role).where(user_role.c.user_id == user.id)
        ).fetchall()

        if existing_roles:
            logger.info(f"ℹ️  Keycloak ne renvoie pas de rôles pour {user.email}, conservation des rôles DB existants ({len(existing_roles)} rôle(s))")
            return  # On garde les rôles existants en base
        else:
            logger.warning(f"⚠️  Aucun rôle pour {user.email} (ni Keycloak, ni DB)")
            return

    # Si Keycloak a des rôles, on synchronise (comportement normal)
    # Supprimer les anciens rôles
    db.execute(delete(user_role).where(user_role.c.user_id == user.id))

    # Récupérer les rôles existants en base
    role_objects = db.execute(
        select(Role).where(Role.code.in_(normalized_roles))
    ).scalars().all()

    role_dict = {role.code: role for role in role_objects}

    # Vérifier les rôles manquants
    missing_roles = set(normalized_roles) - set(role_dict.keys())
    if missing_roles:
        logger.warning(f"⚠️  Rôles manquants en base pour {user.email}: {missing_roles}")

    # Assigner les nouveaux rôles
    for role_code in normalized_roles:
        if role_code in role_dict:
            from datetime import datetime
            db.execute(
                user_role.insert().values(
                    user_id=user.id,
                    role_id=role_dict[role_code].id,
                    assigned_at=datetime.utcnow(),
                    assigned_by=None  # Auto-assigné depuis Keycloak
                )
            )

    db.commit()
    logger.info(f"✅ Rôles synchronisés depuis Keycloak pour {user.email}: {normalized_roles}")


async def get_current_active_admin(
    current_user: User = Depends(get_current_user_keycloak)
) -> User:
    """
    Dependency pour vérifier que l'utilisateur a le rôle admin

    Args:
        current_user: Utilisateur actuel (depuis get_current_user_keycloak)

    Returns:
        Utilisateur si admin

    Raises:
        HTTPException 403: Si l'utilisateur n'est pas admin
    """
    # TODO: Vérifier les rôles depuis le token ou la base de données
    # Pour l'instant, on vérifie juste un attribut
    if not hasattr(current_user, "is_superuser") or not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permissions insuffisantes"
        )
    return current_user


async def get_optional_current_user_keycloak(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
    keycloak: KeycloakService = Depends(get_keycloak_service)
) -> Optional[User]:
    """
    Version optionnelle de get_current_user_keycloak qui retourne None si non authentifié
    au lieu de lever une exception 401.

    Utile pour les endpoints qui ont un comportement différent selon l'authentification
    mais qui ne la requièrent pas forcément.
    """
    try:
        return await get_current_user_keycloak(request, credentials, db, keycloak)
    except HTTPException as e:
        # Si erreur d'authentification, retourner None au lieu de lever l'exception
        if e.status_code in [401, 403]:
            logger.debug(f"🔓 Requête non authentifiée (mode optionnel): {e.detail}")
            return None
        raise
    except Exception as e:
        logger.error(f"🔓 Erreur d'authentification (mode optionnel): {e}", exc_info=True)
        return None


def require_role(required_role: str):
    """
    Decorator pour exiger un rôle spécifique

    Usage:
        @router.get("/admin")
        async def admin_route(
            user: User = Depends(require_role("super_admin"))
        ):
            ...
    """
    async def role_checker(
        request: Request,
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
        keycloak: KeycloakService = Depends(get_keycloak_service)
    ) -> dict:
        # Récupérer le token depuis le header ou le cookie
        jwt_token = None
        if credentials:
            jwt_token = credentials.credentials
        else:
            jwt_token = request.cookies.get("token")

        if not jwt_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Non authentifié"
            )

        # Valider et extraire les rôles
        token_payload = await keycloak.verify_token(jwt_token)
        user_claims = keycloak.extract_user_claims(token_payload)
        roles = user_claims.get("roles", [])

        # Vérifier le rôle
        if required_role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Rôle requis: {required_role}"
            )

        return user_claims

    return role_checker


# ============================================================================
# VÉRIFICATION DES PERMISSIONS (Architecture 3 couches)
# ============================================================================
#
# Architecture de permissions:
# 1. Matrice de droits (DB) = Référentiel fonctionnel géré via UI RBAC
# 2. Keycloak = Source technique d'autorisation (tokens avec rôles)
# 3. Application = Simple consommateur des droits du token
#
# La vérification utilise PRIORITAIREMENT le token Keycloak (client roles),
# avec fallback sur la BDD pendant la phase de transition.
# ============================================================================

# Rôles qui ont TOUTES les permissions automatiquement
SUPERUSER_ROLES = ['ADMIN', 'SUPER_ADMIN', 'super_admin', 'platform_admin']

# Préfixe des permissions dans Keycloak
PERMISSION_PREFIX = "app."


def _check_permission_in_token(token_roles: list, required_permission: str) -> bool:
    """
    Vérifie si une permission est présente dans les rôles du token Keycloak.

    Les permissions dans Keycloak sont préfixées par "app." (ex: "app.CAMPAIGN_READ")

    Args:
        token_roles: Liste des rôles du token (realm + client roles)
        required_permission: Code de la permission requise (ex: "CAMPAIGN_READ")

    Returns:
        True si la permission est trouvée
    """
    # Vérifier la permission avec le préfixe Keycloak
    keycloak_permission = f"{PERMISSION_PREFIX}{required_permission}"

    # Vérifier dans les rôles du token
    return (
        keycloak_permission in token_roles or
        keycloak_permission.lower() in [r.lower() for r in token_roles] or
        required_permission in token_roles or
        required_permission.lower() in [r.lower() for r in token_roles]
    )


def _check_permission_in_db(db, user_id: str, required_permission: str) -> bool:
    """
    Fallback: Vérifie une permission dans la BDD (role_permission).

    Args:
        db: Session de base de données
        user_id: UUID de l'utilisateur
        required_permission: Code de la permission

    Returns:
        True si l'utilisateur a la permission
    """
    from sqlalchemy import text

    permission_query = text("""
        SELECT COUNT(*) as count
        FROM role_permission rp
        JOIN role r ON rp.role_id = r.id
        JOIN permission p ON rp.permission_id = p.id
        JOIN user_role ur ON ur.role_id = r.id
        WHERE ur.user_id = :user_id
        AND p.code = :permission_code
    """)

    result = db.execute(permission_query, {
        "user_id": user_id,
        "permission_code": required_permission
    }).scalar()

    return result and result > 0


def require_permission(required_permission: str):
    """
    Dependency pour exiger une permission spécifique.

    Architecture 3 couches:
    1. Vérifie d'abord dans le token Keycloak (source d'autorité)
    2. Fallback sur la BDD pendant la phase de transition
    3. Les rôles ADMIN/SUPER_ADMIN ont automatiquement toutes les permissions

    Usage:
        @router.get("/campaigns")
        async def list_campaigns(
            user: User = Depends(require_permission("CAMPAIGN_READ"))
        ):
            ...

    Args:
        required_permission: Code de la permission requise (ex: "CAMPAIGN_READ")

    Returns:
        User object si l'utilisateur a la permission

    Raises:
        HTTPException 403: Si l'utilisateur n'a pas la permission
    """
    async def permission_checker(
        request: Request,
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
        db: Session = Depends(get_db),
        keycloak: KeycloakService = Depends(get_keycloak_service)
    ) -> User:
        # 1. Récupérer l'utilisateur authentifié
        user = await get_current_user_keycloak(request, credentials, db, keycloak)

        # 2. Si c'est un dict (Magic Link user), refuser l'accès aux fonctions admin
        if isinstance(user, dict):
            logger.warning(f"❌ Utilisateur Magic Link tente d'accéder à une ressource protégée: {required_permission}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Accès refusé. Cette fonctionnalité n'est pas disponible pour les utilisateurs temporaires."
            )

        # 3. Récupérer les rôles de l'utilisateur (depuis la BDD synchronisée avec Keycloak)
        user_roles = [role.code for role in user.roles] if user.roles else []
        logger.debug(f"🔑 Vérification permission '{required_permission}' pour {user.email} (rôles: {user_roles})")

        # 4. Les super-admins ont toutes les permissions
        if any(role in SUPERUSER_ROLES for role in user_roles):
            logger.debug(f"✅ Utilisateur {user.email} est SUPERUSER - accès accordé")
            return user

        # 5. Vérifier dans la BDD (role_permission) - PAS DE FALLBACK
        if _check_permission_in_db(db, str(user.id), required_permission):
            logger.debug(f"✅ Permission '{required_permission}' trouvée dans BDD pour {user.email}")
            return user

        # 6. Permission refusée
        logger.warning(f"❌ Permission '{required_permission}' refusée pour {user.email}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission insuffisante. Vous n'avez pas le droit '{required_permission}'."
        )

    return permission_checker


def require_any_permission(*required_permissions: str):
    """
    Dependency pour exiger AU MOINS UNE des permissions spécifiées.

    Usage:
        @router.get("/reports")
        async def get_reports(
            user: User = Depends(require_any_permission("REPORT_READ", "CAMPAIGN_READ"))
        ):
            ...

    Args:
        required_permissions: Codes des permissions (l'utilisateur doit avoir AU MOINS une)

    Returns:
        User object si l'utilisateur a au moins une des permissions

    Raises:
        HTTPException 403: Si l'utilisateur n'a aucune des permissions
    """
    async def permission_checker(
        request: Request,
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
        db: Session = Depends(get_db),
        keycloak: KeycloakService = Depends(get_keycloak_service)
    ) -> User:
        # 1. Récupérer l'utilisateur authentifié
        user = await get_current_user_keycloak(request, credentials, db, keycloak)

        # 2. Si c'est un dict (Magic Link user), refuser
        if isinstance(user, dict):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Accès refusé. Cette fonctionnalité n'est pas disponible pour les utilisateurs temporaires."
            )

        # 3. Récupérer les rôles de l'utilisateur
        user_roles = [role.code for role in user.roles] if user.roles else []

        # 4. Les super-admins ont toutes les permissions
        if any(role in SUPERUSER_ROLES for role in user_roles):
            return user

        # 5. Vérifier dans la BDD (role_permission) - PAS DE FALLBACK
        from sqlalchemy import text

        permission_query = text("""
            SELECT COUNT(*) as count
            FROM role_permission rp
            JOIN role r ON rp.role_id = r.id
            JOIN permission p ON rp.permission_id = p.id
            JOIN user_role ur ON ur.role_id = r.id
            WHERE ur.user_id = :user_id
            AND p.code = ANY(:permission_codes)
        """)

        result = db.execute(permission_query, {
            "user_id": str(user.id),
            "permission_codes": list(required_permissions)
        }).scalar()

        if result and result > 0:
            return user

        # 6. Permission refusée
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission insuffisante. Vous avez besoin d'au moins une de ces permissions: {', '.join(required_permissions)}"
        )

    return permission_checker


async def get_user_permissions(user: User, db: Session) -> list[str]:
    """
    Récupère toutes les permissions d'un utilisateur.

    Args:
        user: Utilisateur authentifié
        db: Session de base de données

    Returns:
        Liste des codes de permissions
    """
    from sqlalchemy import text

    # Les super-admins ont toutes les permissions
    user_roles = [role.code for role in user.roles] if user.roles else []
    if any(role in SUPERUSER_ROLES for role in user_roles):
        # Retourner toutes les permissions existantes
        all_perms_query = text("SELECT code FROM permission")
        result = db.execute(all_perms_query).fetchall()
        return [row[0] for row in result]

    # Pour les autres, récupérer via role_permission
    permission_query = text("""
        SELECT DISTINCT p.code
        FROM role_permission rp
        JOIN role r ON rp.role_id = r.id
        JOIN permission p ON rp.permission_id = p.id
        JOIN user_role ur ON ur.role_id = r.id
        WHERE ur.user_id = :user_id
    """)

    result = db.execute(permission_query, {"user_id": str(user.id)}).fetchall()
    return [row[0] for row in result]


def get_user_permissions_from_db(db: Session, user: User) -> list[str]:
    """
    Version synchrone de get_user_permissions.
    Récupère toutes les permissions d'un utilisateur depuis la base de données.

    Args:
        db: Session de base de données
        user: Utilisateur authentifié

    Returns:
        Liste des codes de permissions
    """
    from sqlalchemy import text

    # Les super-admins ont toutes les permissions
    user_roles = [role.code for role in user.roles] if user.roles else []
    if any(role in SUPERUSER_ROLES for role in user_roles):
        # Retourner toutes les permissions existantes
        all_perms_query = text("SELECT code FROM permission")
        result = db.execute(all_perms_query).fetchall()
        return [row[0] for row in result]

    # Pour les autres, récupérer via role_permission
    permission_query = text("""
        SELECT DISTINCT p.code
        FROM role_permission rp
        JOIN role r ON rp.role_id = r.id
        JOIN permission p ON rp.permission_id = p.id
        JOIN user_role ur ON ur.role_id = r.id
        WHERE ur.user_id = :user_id
    """)

    result = db.execute(permission_query, {"user_id": str(user.id)}).fetchall()
    return [row[0] for row in result]
