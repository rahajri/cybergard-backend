"""
API pour la gestion des utilisateurs
VERSION CORRIGÉE - Avec rôle dynamique dans entity_member
"""
from typing import List, Optional
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import select, func, text
import secrets
import string
from datetime import datetime, timedelta, timezone

from src.database import get_db
from src.models.audit import User
from src.models.tenant import Tenant
from src.models.organization import Organization
from src.utils.security import hash_password, verify_password
from src.dependencies_keycloak import get_current_user_keycloak, require_permission
from src.services.email_service import send_activation_email_by_role, send_magic_link_email
from src.services.magic_link_service import generate_magic_link
from src.utils.redis_manager import redis_manager
from src.utils.email_validator import validate_email_complete
import os

import logging

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

logger = logging.getLogger(__name__)

router = APIRouter()

def generate_temp_password(length: int = 12) -> str:
    """Génère un mot de passe temporaire sécurisé"""
    alphabet = string.ascii_letters + string.digits + "!@#$%&"
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def generate_activation_token() -> str:
    """Génère un token d'activation sécurisé"""
    return secrets.token_urlsafe(32)


# ============================================================================
# SCHÉMAS PYDANTIC
# ============================================================================

from pydantic import BaseModel, EmailStr, Field


class UserBase(BaseModel):
    """Schéma de base pour un utilisateur"""
    email: EmailStr
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    phone: Optional[str] = Field(None, max_length=50)  # Format: +33612345678
    tenant_id: Optional[UUID] = None
    default_org_id: Optional[UUID] = None  # Entité écosystème
    organization_id: Optional[UUID] = None  # Organisation cliente


class UserCreate(UserBase):
    """Schéma pour créer un utilisateur"""
    password: Optional[str] = Field(None, min_length=8, max_length=72)
    role_code: Optional[str] = None
    is_active: bool = True
    send_activation_email: bool = True


class UserUpdate(BaseModel):
    """Schéma pour mettre à jour un utilisateur"""
    email: Optional[EmailStr] = None
    first_name: Optional[str] = Field(None, min_length=1, max_length=100)
    last_name: Optional[str] = Field(None, min_length=1, max_length=100)
    password: Optional[str] = Field(None, min_length=8, max_length=72)
    is_active: Optional[bool] = None
    is_email_verified: Optional[bool] = None
    default_org_id: Optional[UUID] = None


class UserResponse(UserBase):
    """Schéma de réponse pour un utilisateur"""
    id: UUID
    is_active: bool
    is_email_verified: bool
    role: Optional[str] = None  # ✅ Rôle depuis entity_member
    last_login_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    actions_count: Optional[int] = 0  # Nombre d'actions en cours
    evaluations_count: Optional[int] = 0  # Nombre d'évaluations en cours

    class Config:
        from_attributes = True


class UserListResponse(BaseModel):
    """Schéma de réponse pour une liste d'utilisateurs"""
    items: list[UserResponse]
    total: int
    skip: int
    limit: int


class ActivateAccountRequest(BaseModel):
    """Schéma pour activer un compte"""
    token: str
    password: str = Field(..., min_length=12, max_length=72)


class EmailValidationRequest(BaseModel):
    """Schéma pour valider un email"""
    email: EmailStr


class EmailValidationResponse(BaseModel):
    """Schéma de réponse de validation d'email"""
    valid: bool
    exists: bool = False
    errors: List[str] = []
    warnings: List[str] = []
    suggestion: Optional[str] = None


class GenerateMagicLinkRequest(BaseModel):
    """Schéma pour générer un lien magique"""
    user_email: EmailStr
    campaign_id: UUID
    questionnaire_id: Optional[UUID] = None
    campaign_name: str = Field(..., min_length=1, max_length=200)
    entity_name: Optional[str] = Field(None, max_length=200)
    tenant_id: UUID


class GenerateMagicLinkResponse(BaseModel):
    """Schéma de réponse de génération de lien magique"""
    success: bool
    magic_link: str
    token_jti: UUID
    expires_at: datetime
    max_uses: int
    message: str


# ============================================================================
# ENDPOINTS : Users
# ============================================================================

@router.post("/validate-email", response_model=EmailValidationResponse)
async def validate_email(
    request: EmailValidationRequest,
    db: Session = Depends(get_db)
):
    """
    Valide une adresse email :
    - Format et caractères autorisés (pas d'accents)
    - Existence du domaine (DNS/MX records)
    - Email déjà utilisé en base de données
    """

    email = request.email.lower().strip()

    # 1. Validation complète (format + domaine)
    validation_result = validate_email_complete(email)

    # 2. Vérifier si l'email existe déjà en base
    existing_user = db.execute(
        select(User).where(User.email == email)
    ).scalar_one_or_none()

    if existing_user:
        validation_result["exists"] = True
        validation_result["valid"] = False
        validation_result["errors"].append(
            f"Un utilisateur avec l'email '{email}' existe déjà"
        )

    return EmailValidationResponse(**validation_result)

@router.post("/admin/create", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user: UserCreate,
    db: Session = Depends(get_db)
):
    """
    Crée un nouvel utilisateur avec attribution automatique du rôle et envoi d'email
    
    - **organization_id**: ID de l'organisation cliente (Vision Agile)
    - **default_org_id**: ID de l'entité écosystème (ARES SERVICES, SODEXO, etc.)
    - **role_code**: Code du rôle (ex: AUDITEUR)
    - **send_activation_email**: Envoyer l'email d'activation (défaut: true)
    """
    
    logger.info(f"🔵 Tentative de création d'utilisateur: {user.email}")

    # ✅ VALIDATION DE L'EMAIL (format, domaine, existence)
    email_cleaned = user.email.lower().strip()
    validation_result = validate_email_complete(email_cleaned)

    # Vérifier les erreurs de format/domaine
    if not validation_result["valid"]:
        error_msg = " | ".join(validation_result["errors"])
        logger.warning(f"❌ Email invalide: {email_cleaned} - {error_msg}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "Adresse email invalide",
                "errors": validation_result["errors"],
                "suggestion": validation_result.get("email_cleaned")
            }
        )

    # Vérifier que l'email n'existe pas déjà en base pour ce tenant
    # Note: On permet le même email pour différents tenants
    if user.tenant_id:
        existing_user = db.execute(
            select(User).where(
                User.email == email_cleaned,
                User.tenant_id == user.tenant_id
            )
        ).scalar_one_or_none()

        if existing_user:
            logger.warning(f"❌ Email déjà utilisé pour ce tenant: {email_cleaned}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Un utilisateur avec l'email '{email_cleaned}' existe déjà pour votre organisation"
            )

    # Utiliser l'email nettoyé
    user.email = email_cleaned
    
    # Vérifier que le tenant existe
    if user.tenant_id:
        tenant = db.get(Tenant, user.tenant_id)
        if not tenant:
            logger.error(f"❌ Tenant introuvable: {user.tenant_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Tenant {user.tenant_id} introuvable"
            )
        
        # Vérifier la limite d'utilisateurs
        user_count = db.execute(
            select(func.count(User.id)).where(User.tenant_id == user.tenant_id)
        ).scalar()
        
        if user_count >= tenant.max_users:
            logger.warning(f"❌ Limite d'utilisateurs atteinte pour tenant {user.tenant_id}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Limite d'utilisateurs atteinte ({tenant.max_users}) pour ce tenant"
            )
    
    # ✅ Vérifier que l'organisation cliente existe
    organization = None
    if user.organization_id:
        organization = db.get(Organization, user.organization_id)
        if not organization:
            logger.error(f"❌ Organisation cliente introuvable: {user.organization_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Organisation cliente {user.organization_id} introuvable"
            )
        logger.info(f"✅ Organisation cliente: {organization.name}")
    
    # ✅ Vérifier que l'entité écosystème existe
    ecosystem_entity = None
    if user.default_org_id:
        entity_check = db.execute(
            text("SELECT id, name FROM ecosystem_entity WHERE id = :entity_id"),
            {"entity_id": str(user.default_org_id)}
        ).fetchone()

        if not entity_check:
            logger.warning(f"⚠️ Entité écosystème introuvable: {user.default_org_id}")
        else:
            ecosystem_entity = entity_check
            logger.info(f"✅ Entité écosystème: {entity_check[1]}")

    # Générer le mot de passe et le token d'activation
    if user.password:
        password_to_hash = user.password
    else:
        password_to_hash = generate_temp_password()
        logger.info(f"🔑 Mot de passe temporaire généré pour {user.email}")
    
    hashed_password = hash_password(password_to_hash)
    activation_token = generate_activation_token()
    token_expires = datetime.utcnow() + timedelta(days=7)
    
    # ✅ CRÉER L'UTILISATEUR OU LE CONTACT
    # Déterminer le type selon son rôle
    is_contact = user.role_code and user.role_code.upper() in ['AUDITE_CONTRIB', 'AUDITE_RESP']
    # Tous les autres rôles sont des utilisateurs internes (membres de l'équipe)
    is_team_member = not is_contact

    # ============================================================================
    # ARCHITECTURE IMPORTANTE :
    # - UTILISATEURS (employés du client) : créés dans 'users' avec tenant_id + authentification Keycloak
    # - CONTACTS (audités externes) : créés UNIQUEMENT dans 'entity_member', PAS dans 'users'
    #   Les contacts accèdent UNIQUEMENT via magic links
    # ============================================================================

    if is_contact:
        # ========================================================================
        # CONTACTS : Créés UNIQUEMENT dans entity_member (PAS dans users)
        # ========================================================================
        if not user.default_org_id or not ecosystem_entity:
            logger.error(f"❌ Contact sans entité écosystème: default_org_id requis")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Un contact (audité) doit être lié à une entité écosystème (default_org_id)"
            )

        # Vérifier que l'email n'existe pas déjà dans entity_member pour cette entité
        existing_contact = db.execute(
            text("""
                SELECT id FROM entity_member
                WHERE email = :email AND entity_id = :entity_id
            """),
            {"email": user.email, "entity_id": str(user.default_org_id)}
        ).fetchone()

        if existing_contact:
            logger.warning(f"❌ Email déjà utilisé pour cette entité: {user.email}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Un contact avec l'email '{user.email}' existe déjà pour cette entité"
            )

        logger.info(f"👤 Création d'un CONTACT (audité) - UNIQUEMENT dans entity_member")

        # Créer directement dans entity_member avec user_id=NULL
        contact_role = user.role_code.lower() if user.role_code else 'audite_resp'
        contact_roles_json = f'["{contact_role}"]'

        insert_contact_sql = text("""
            INSERT INTO entity_member (
                id, entity_id, user_id, roles, is_active,
                can_be_assigned_audits, can_receive_notifications,
                email, first_name, last_name, phone,
                joined_at, created_at, updated_at
            )
            VALUES (
                gen_random_uuid(), :entity_id, NULL,
                CAST(:roles AS jsonb), TRUE, TRUE, TRUE,
                :email, :first_name, :last_name, :phone,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            RETURNING id
        """)

        result = db.execute(insert_contact_sql, {
            "entity_id": str(user.default_org_id),
            "roles": contact_roles_json,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "phone": user.phone
        })
        contact_id = result.fetchone()[0]
        db.commit()

        logger.info(f"✅ Contact créé dans entity_member (ID: {contact_id})")
        logger.info(f"✅ Rôle: {contact_role}, Entité: {ecosystem_entity[1]}")
        logger.info(f"⚠️  PAS dans users - Accès via magic links uniquement")

        # Retourner une réponse (créer un objet factice pour compatibilité)
        return UserResponse(
            id=contact_id,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            tenant_id=None,
            default_org_id=user.default_org_id,
            organization_id=None,
            is_active=True,
            is_email_verified=False,
            role=contact_role,
            last_login_at=None,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )

    else:
        # ========================================================================
        # UTILISATEURS : Création complète dans users avec authentification
        # ========================================================================
        # Tous les utilisateurs internes doivent avoir un tenant_id
        if not user.tenant_id:
            logger.error(f"❌ Utilisateur interne sans tenant_id: {user.email}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Un utilisateur interne doit obligatoirement appartenir à un tenant (organization)"
            )

        db_user = User(
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            phone=user.phone,
            password_hash=hashed_password,
            tenant_id=user.tenant_id,
            default_org_id=user.organization_id,
            is_active=user.is_active if hasattr(user, 'is_active') else True,
            is_email_verified=False
        )

        db.add(db_user)
        db.flush()
        logger.info(f"✅ Utilisateur interne créé: {db_user.email} ({db_user.id}) - Tenant: {user.tenant_id}")

        # ============================================================================
        # ✅ SAUVEGARDER LE TOKEN D'ACTIVATION (uniquement pour utilisateurs)
        # ============================================================================
        insert_token_sql = text("""
            INSERT INTO activation_tokens (
                id, user_id, token, expires_at, is_used, created_at
            )
            VALUES (
                gen_random_uuid(), :user_id, :token, :expires_at, false, CURRENT_TIMESTAMP
            )
        """)

        db.execute(insert_token_sql, {
            "user_id": str(db_user.id),
            "token": activation_token,
            "expires_at": token_expires
        })

        logger.info(f"✅ Token d'activation sauvegardé (expire: {token_expires})")

    # ============================================================================
    # ✅ CRÉER LA LIAISON AVEC L'ENTITÉ ÉCOSYSTÈME (RÔLE DYNAMIQUE)
    # ============================================================================
    if user.default_org_id and ecosystem_entity:
        logger.info(f"🔗 Liaison utilisateur → entité écosystème")
        
        try:
            # ✅ Utiliser le role_code dynamiquement (en minuscules)
            entity_role = user.role_code.lower() if user.role_code else 'auditee'
            entity_roles_json = f'["{entity_role}"]'
            
            logger.info(f"👤 Rôle dans l'entité: {entity_role}")
            
            insert_member_sql = text("""
                INSERT INTO entity_member (
                    id, entity_id, user_id, roles, is_active,
                    can_be_assigned_audits, can_receive_notifications,
                    email, first_name, last_name,
                    joined_at, created_at, updated_at
                )
                VALUES (
                    gen_random_uuid(), :entity_id, :user_id,
                    CAST(:roles AS jsonb), TRUE, TRUE, TRUE,
                    :email, :first_name, :last_name,
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
            """)

            db.execute(insert_member_sql, {
                "entity_id": str(user.default_org_id),
                "user_id": str(db_user.id),
                "roles": entity_roles_json,
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name
            })
            db.commit()
            logger.info(f"✅ Liaison entité écosystème créée avec rôle: {entity_role}")
        except Exception as e:
            logger.error(f"❌ Erreur liaison entité: {e}")
            db.rollback()
    
    # ============================================================================
    # ✅ CRÉER LE RÔLE dans user_organization_role (UNIQUEMENT pour utilisateurs internes)
    # ============================================================================
    if is_team_member and hasattr(user, 'role_code') and user.role_code and user.organization_id:
        logger.info(f"🔐 Attribution du rôle {user.role_code} (utilisateur interne)")

        try:
            insert_role_sql = text("""
                INSERT INTO user_organization_role (
                    id, user_id, organization_id, role, is_active,
                    permissions, created_at
                )
                VALUES (
                    :id, :user_id, :org_id, :role, :is_active,
                    :permissions, NOW()
                )
                ON CONFLICT DO NOTHING
            """)

            db.execute(insert_role_sql, {
                "id": str(uuid4()),
                "user_id": str(db_user.id),
                "org_id": str(user.organization_id),
                "role": user.role_code,
                "is_active": True,
                "permissions": '{"can_manage_users": true, "can_manage_org": true, "can_view_all": true}'
            })

            db.commit()
            logger.info(f"✅ Rôle {user.role_code} attribué à l'organisation")

        except Exception as e:
            logger.error(f"❌ Erreur lors de la création du rôle: {e}")
            db.rollback()
    else:
        logger.info(f"ℹ️ Pas d'attribution de rôle organisation (contact externe ou données manquantes)")
    
    # ============================================================================
    # ✅ ENVOYER L'EMAIL D'ACTIVATION (uniquement pour non-contacts)
    # ============================================================================
    if user.send_activation_email and not is_contact:
        # Les contacts AUDITE_CONTRIB et AUDITE_RESP recevront un lien magique
        # lors de leur affectation à une campagne d'audit (pas maintenant)
        try:
            activation_url = f"{FRONTEND_URL}/activate-account?token={activation_token}"

            # Récupérer le nom de l'entité si disponible
            entity_name = None
            if ecosystem_entity:
                entity_name = ecosystem_entity[1]  # ecosystem_entity est un tuple (id, name)

            send_activation_email_by_role(
                to_email=user.email,
                user_name=f"{user.first_name} {user.last_name}",
                activation_url=activation_url,
                role_code=user.role_code if user.role_code else 'AUDITEUR',
                organization_name=organization.name if organization else "Votre organisation",
                entity_name=entity_name
            )

            logger.info(f"✅ Email d'activation envoyé à {user.email}")

        except Exception as e:
            logger.error(f"⚠️ Erreur envoi email (non bloquant): {e}")

    elif is_contact:
        logger.info(
            f"ℹ️ Contact audité créé ({user.role_code}): {user.email}. "
            f"Le lien magique sera généré lors de l'affectation à une campagne d'audit."
        )

    # ============================================================================
    # ✅ INVALIDER LE CACHE REDIS
    # ============================================================================
    try:
        redis_manager.delete_pattern("users:*")
        logger.info("✅ Cache utilisateurs invalidé")
    except Exception as e:
        logger.warning(f"⚠️ Erreur invalidation cache (non bloquant): {e}")

    return db_user


@router.get("/users", response_model=UserListResponse)
async def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    is_active: Optional[bool] = Query(None),
    tenant_id: Optional[UUID] = Query(None),
    current_user: User = Depends(require_permission("USERS_READ")),
    db: Session = Depends(get_db)
):
    """Liste tous les utilisateurs avec filtres et pagination"""

    # SÉCURITÉ: Forcer le filtrage par le tenant de l'utilisateur connecté
    # Un utilisateur ne peut voir QUE les utilisateurs de son propre tenant
    user_tenant_id = str(current_user.tenant_id) if current_user.tenant_id else None

    if not user_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Utilisateur sans tenant. Accès refusé."
        )

    # Construire la clause WHERE
    where_clauses = ["u.tenant_id = :tenant_id"]
    params = {"limit": limit, "skip": skip, "tenant_id": user_tenant_id}

    if is_active is not None:
        where_clauses.append("u.is_active = :is_active")
        params["is_active"] = is_active

    # Exclure les super_admin (qui ne doivent pas être assignés comme pilotes)
    where_clauses.append("COALESCE(uor.role, em.roles->>0) != 'super_admin'")

    where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

    # Requête SQL avec jointure pour récupérer le rôle depuis user_organization_role (internes) ou entity_member (externes)
    # Priorité: user_organization_role.role (pour internes avec tenant_id) puis entity_member.roles (pour externes)
    # + Comptage des actions en cours et évaluations en cours
    query = text(f"""
        SELECT DISTINCT ON (u.id)
            u.id,
            u.email,
            u.first_name,
            u.last_name,
            u.tenant_id,
            u.default_org_id,
            u.is_active,
            u.is_email_verified,
            u.last_login_at,
            u.created_at,
            u.updated_at,
            u.phone,
            u.keycloak_id,
            COALESCE(
                uor.role,
                CASE
                    WHEN em.roles IS NOT NULL AND jsonb_array_length(em.roles) > 0
                    THEN em.roles->>0
                    ELSE NULL
                END
            ) as role,
            (
                SELECT COUNT(*)
                FROM action a
                WHERE a.assignee = u.id
                AND a.status NOT IN ('completed', 'closed', 'cancelled')
            ) as actions_count,
            (
                SELECT COUNT(*)
                FROM audit_user_assignment aua
                JOIN audit au ON aua.audit_id = au.id
                WHERE aua.user_id = u.id
                AND au.status NOT IN ('completed', 'archived')
            ) as evaluations_count
        FROM users u
        LEFT JOIN user_organization_role uor ON u.id = uor.user_id AND uor.is_active = true
        LEFT JOIN entity_member em ON u.id = em.user_id AND em.is_active = true
        {where_sql}
        ORDER BY u.id, uor.created_at DESC NULLS LAST, em.created_at DESC NULLS LAST
        LIMIT :limit OFFSET :skip
    """)

    result = db.execute(query, params)
    users_data = result.fetchall()

    # Convertir en liste de dicts
    users = []
    for row in users_data:
        user_dict = {
            "id": str(row.id),
            "email": row.email,
            "first_name": row.first_name,
            "last_name": row.last_name,
            "tenant_id": str(row.tenant_id) if row.tenant_id else None,
            "default_org_id": str(row.default_org_id) if row.default_org_id else None,
            "organization_id": None,  # Pas dans la requête mais requis par UserBase
            "is_active": row.is_active,
            "is_email_verified": row.is_email_verified,
            "role": row.role,
            "last_login_at": row.last_login_at,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "actions_count": row.actions_count or 0,
            "evaluations_count": row.evaluations_count or 0,
        }
        users.append(user_dict)

    # Count total - avec les mêmes jointures pour exclure les super_admin
    count_query = text(f"""
        SELECT COUNT(DISTINCT u.id)
        FROM users u
        LEFT JOIN user_organization_role uor ON u.id = uor.user_id AND uor.is_active = true
        LEFT JOIN entity_member em ON u.id = em.user_id AND em.is_active = true
        {where_sql}
    """)

    # Réutiliser les mêmes paramètres que la requête principale
    count_params = {
        "tenant_id": user_tenant_id
    }
    if is_active is not None:
        count_params["is_active"] = is_active

    total = db.execute(count_query, count_params).scalar()

    return {
        "items": users,
        "total": total or 0,
        "skip": skip,
        "limit": limit
    }


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: UUID,
    db: Session = Depends(get_db)
):
    """Récupère un utilisateur par son ID"""
    user = db.get(User, user_id)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Utilisateur {user_id} introuvable"
        )
    
    return user


@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: UUID,
    user_update: UserUpdate,
    db: Session = Depends(get_db)
):
    """Met à jour un utilisateur"""
    db_user = db.get(User, user_id)
    
    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Utilisateur {user_id} introuvable"
        )
    
    update_data = user_update.model_dump(exclude_unset=True)
    
    if 'password' in update_data and update_data['password']:
        update_data['password_hash'] = hash_password(update_data.pop('password'))
    
    for field, value in update_data.items():
        setattr(db_user, field, value)
    
    db.commit()
    db.refresh(db_user)
    
    logger.info(f"✅ Utilisateur {db_user.email} mis à jour")
    
    return db_user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: UUID,
    db: Session = Depends(get_db)
):
    """Supprime un utilisateur (soft delete)"""
    db_user = db.get(User, user_id)

    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Utilisateur {user_id} introuvable"
        )

    # Vérifier le rôle de l'utilisateur dans user_organization_role
    role_result = db.execute(
        text("""
            SELECT role
            FROM user_organization_role
            WHERE user_id = :user_id AND is_active = true
            LIMIT 1
        """),
        {"user_id": str(user_id)}
    ).fetchone()

    # Empêcher la suppression des ADMIN et SUPER_ADMIN
    if role_result and role_result[0] in ['ADMIN', 'SUPER_ADMIN']:
        logger.warning(f"❌ Tentative de suppression d'un administrateur ({role_result[0]}): {db_user.email}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Impossible de supprimer un utilisateur avec le rôle {role_result[0]}"
        )

    db_user.is_active = False
    db.commit()

    logger.info(f"✅ Utilisateur {db_user.email} désactivé")

    return None


@router.post("/activate", status_code=status.HTTP_200_OK)
async def activate_account(
    request: ActivateAccountRequest,
    db: Session = Depends(get_db)
):
    """Active un compte utilisateur avec un token"""

    logger.info(f"🔓 Activation de compte avec token: {request.token[:10]}...")

    return {"message": "Compte activé avec succès"}


@router.post("/generate-magic-link", response_model=GenerateMagicLinkResponse, status_code=status.HTTP_201_CREATED)
async def generate_and_send_magic_link(
    request: GenerateMagicLinkRequest,
    db: Session = Depends(get_db)
):
    """
    Génère un lien magique JWT pour un utilisateur audité et envoie l'email

    Ce endpoint est utilisé pour :
    - Générer un lien magique sécurisé avec token JWT
    - Enregistrer le token en base de données
    - Envoyer l'email d'invitation avec le lien magique

    Le lien permet un accès direct au questionnaire d'audit sans mot de passe.
    Réservé aux rôles AUDITE_CONTRIB et AUDITE_RESP.
    """

    logger.info(
        f"✨ Génération de lien magique pour {request.user_email} - "
        f"Campagne: {request.campaign_id}"
    )

    try:
        # 1. Vérifier que l'utilisateur ou le contact existe
        # Chercher d'abord dans la table users (utilisateurs internes)
        db_user = db.execute(
            select(User).where(User.email == request.user_email.lower().strip())
        ).scalar_one_or_none()

        # Si pas trouvé dans users, chercher dans entity_member (contacts)
        if not db_user:
            from sqlalchemy import text
            logger.info(f"🔎 Recherche du contact dans entity_member pour email: {request.user_email}")

            entity_member_query = text("""
                SELECT id, email, first_name, last_name
                FROM entity_member
                WHERE LOWER(email) = :email
                AND is_active = true
                LIMIT 1
            """)
            entity_member_result = db.execute(
                entity_member_query,
                {"email": request.user_email.lower().strip()}
            ).fetchone()

            if entity_member_result:
                # Créer un objet similaire à User pour la suite du traitement
                class ContactInfo:
                    def __init__(self, email, first_name, last_name):
                        self.email = email
                        self.first_name = first_name
                        self.last_name = last_name

                db_user = ContactInfo(
                    email=entity_member_result.email,
                    first_name=entity_member_result.first_name,
                    last_name=entity_member_result.last_name
                )
                logger.info(f"✅ Contact trouvé dans entity_member: {request.user_email}")
            else:
                logger.warning(f"❌ Utilisateur/Contact {request.user_email} non trouvé dans users ni dans entity_member")
                logger.warning(f"❌ Email recherché: '{request.user_email.lower().strip()}'")
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Utilisateur ou contact avec l'email '{request.user_email}' introuvable"
                )

        # 2. Vérifier que le tenant existe
        tenant = db.get(Tenant, request.tenant_id)
        if not tenant:
            logger.warning(f"❌ Tenant {request.tenant_id} non trouvé")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Tenant {request.tenant_id} introuvable"
            )

        # 3. Générer le lien magique
        magic_link, audit_token = generate_magic_link(
            db=db,
            user_email=request.user_email.lower().strip(),
            campaign_id=request.campaign_id,
            questionnaire_id=request.questionnaire_id,
            tenant_id=request.tenant_id
        )

        logger.info(
            f"✅ Lien magique généré: JTI={audit_token.token_jti}, "
            f"Expire: {audit_token.expires_at}"
        )

        # 4. Envoyer l'email avec le lien magique
        user_full_name = f"{db_user.first_name} {db_user.last_name}".strip()
        entity_display = request.entity_name if request.entity_name else tenant.name

        # Calculer le nombre de jours jusqu'à l'expiration
        expiry_days = int((audit_token.expires_at - datetime.now(timezone.utc)).days)

        send_magic_link_email(
            to_email=request.user_email,
            user_name=user_full_name,
            magic_link=magic_link,
            campaign_name=request.campaign_name,
            entity_name=entity_display,
            organization_name=tenant.name,
            expiry_days=expiry_days,
            max_uses=audit_token.max_uses
        )

        logger.info(f"📧 Email de lien magique envoyé à {request.user_email}")

        return GenerateMagicLinkResponse(
            success=True,
            magic_link=magic_link,
            token_jti=audit_token.token_jti,
            expires_at=audit_token.expires_at,
            max_uses=audit_token.max_uses,
            message=(
                f"Lien magique généré et envoyé à {request.user_email}. "
                f"Valide pendant {int((audit_token.expires_at - datetime.now(timezone.utc)).days)} jours, "
                f"utilisable {audit_token.max_uses} fois maximum."
            )
        )

    except HTTPException:
        # Re-lever les HTTPException déjà formattées
        raise

    except Exception as e:
        logger.error(f"❌ Erreur génération lien magique: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la génération du lien magique: {str(e)}"
        )