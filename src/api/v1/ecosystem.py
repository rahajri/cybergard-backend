# backend/src/api/v1/ecosystem.py
# API Ecosystem - Gestion des organismes et membres
# Fix: member_count ajouté pour entités externes (entity_member) et internes (users)

from typing import List, Optional, Literal, Dict, Any
import uuid
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status, Header
from sqlalchemy import select, func, or_, and_, text as sql_text, text
from sqlalchemy.orm import Session, joinedload, selectinload

from src.database import get_db
from src.dependencies_keycloak import get_current_user_keycloak, require_permission
from src.models.audit import User
from src.models.ecosystem import RelationshipType, EcosystemEntity, EntityMember, EntityStatus
from src.schemas.pole import PoleResponse, PoleListResponse, PoleUpdate, PoleCreate
from src.models.pole import Pole
from src.models.category import Category

from src.schemas.ecosystem import (
    # RelationshipType schemas
    RelationshipTypeCreate, RelationshipTypeUpdate, RelationshipTypeResponse,
    # EcosystemEntity schemas
    EcosystemEntityCreate, EcosystemEntityUpdate, EcosystemEntityResponse,
    EcosystemEntityListResponse,
    # EntityMember schemas
    EntityMemberCreate, EntityMemberUpdate, EntityMemberResponse,
    # INSEE
    INSEEDataRequest, INSEEDataResponse,
    # Bulk operations
    BulkActivateRequest, BulkArchiveRequest, BulkOperationResponse
)
from src.models.pole import Pole
from src.schemas.pole import (
    PoleCreate,
    PoleUpdate,
    PoleResponse,
    PoleListResponse,
    PoleCreateWithTenant
)
from src.schemas.ecosystem import (
    EcosystemEntityCreate,
    CategoryCreateData
)

from src.services.insee_service import get_insee_service

# ✅ REDIS CACHE
from src.utils.redis_manager import cache_result, redis_manager

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ecosystem", tags=["Écosystème"])

# Champs autorisés pour les entités ecosystem
VALID_ENTITY_FIELDS = {
    'client_organization_id', 'name', 'legal_name', 'trade_name', 'short_name',
    'siret', 'siren', 'ape_code', 'vat_number', 'registration_number',
    'registration_country', 'stakeholder_type', 'entity_category',
    'parent_entity_id', 'hierarchy_level', 'hierarchy_path',
    'address_line1', 'address_line2', 'address_line3', 'postal_code',
    'city', 'region', 'country_code', 
    
    'annual_revenue',  'insee_data', 'insee_last_sync',
    'description', 'notes', 'is_active', 'is_certified', 'certification_info',
    'created_by', 'updated_by', 'relation_type_id', 'status',
    'short_code', 'is_activated', 'activated_at', 'activated_by',
    'mfa_config', 'is_domain', 'is_base_template', 'tenant_id',
    'ecosystem_domain_id', 'pole_id', 'category_id'  # ✅ Nouveaux champs
}

# Champs autorisés issus de la réponse INSEE uniquement
VALID_INSEE_FIELDS = {
    "siret",
    "siren",
    "legal_name",
    "trade_name",
    "ape_code",
    "address_line1",
    "postal_code",
    "city",
    "enterprise_category",
    "trancheEffectifsEtablissement",
    "trancheEffectifsUniteLegale",
    "creation_date",
    "raw_insee_data",
}

# ============================================================================
# ENDPOINTS : DOMAINS (Domaines ecosystem)
# ============================================================================

@router.get("/domains")
@cache_result(ttl=1800, key_prefix="ecosystem_domains")  # ✅ Cache 30min
async def list_domains(
    client_organization_id: Optional[str] = Query(None, description="ID de l'organisation cliente"),
    tenant_id: Optional[UUID] = Query(None, description="ID du tenant"),
    stakeholder_type: Optional[Literal["internal", "external"]] = Query(None),
    is_active: Optional[bool] = Query(True),
    db: Session = Depends(get_db)
):
    """
    Liste tous les domaines de l'écosystème (entités avec is_domain=True)

    Les domaines sont des catégories de haut niveau comme "Interne" et "Externe"
    """
    query = select(EcosystemEntity).where(EcosystemEntity.is_domain == True)
    
    # Filtres
    if client_organization_id:
        query = query.where(EcosystemEntity.client_organization_id == client_organization_id)
    
    if tenant_id:
        query = query.where(EcosystemEntity.tenant_id == tenant_id)
    
    if stakeholder_type:
        query = query.where(EcosystemEntity.stakeholder_type == stakeholder_type)
    
    if is_active is not None:
        query = query.where(EcosystemEntity.is_active == is_active)
    
    # Tri par niveau hiérarchique et nom
    query = query.order_by(EcosystemEntity.hierarchy_level, EcosystemEntity.name)
    
    result = db.execute(query)
    domains = result.scalars().all()
    
    return domains


@router.get("/domains/{domain_id}")
async def get_domain(
    domain_id: UUID,
    db: Session = Depends(get_db)
):
    """Récupère un domaine par son ID"""
    domain = db.get(EcosystemEntity, domain_id)
    
    if not domain or not domain.is_domain:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Domaine non trouvé"
        )
    
    return domain


@router.post("/domains", status_code=status.HTTP_201_CREATED)
async def create_domain(
    domain_data: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """
    Crée un nouveau domaine ecosystem
    
    Un domaine est une entité de haut niveau (is_domain=True, hierarchy_level=1)
    """
    # Forcer les valeurs pour un domaine
    domain_data["is_domain"] = True
    domain_data["is_base_template"] = True
    domain_data["hierarchy_level"] = 1
    domain_data["parent_entity_id"] = None
    
    # Vérifier qu'un domaine avec ce nom n'existe pas déjà
    existing = db.execute(
        select(EcosystemEntity).where(
            and_(
                EcosystemEntity.name == domain_data.get("name"),
                EcosystemEntity.client_organization_id == domain_data.get("client_organization_id"),
                EcosystemEntity.is_domain == True
            )
        )
    ).scalar_one_or_none()
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Un domaine avec le nom '{domain_data.get('name')}' existe déjà"
        )
    
    # Nettoyer et créer
    clean_data = sanitize_entity_data(domain_data)
    db_domain = EcosystemEntity(**clean_data)
    
    # Définir le hierarchy_path
    db.add(db_domain)
    db.flush()
    db_domain.hierarchy_path = f"/{db_domain.id}"
    
    db.commit()
    db.refresh(db_domain)
    
    logger.info(f"✓ Domaine créé: {db_domain.name} ({db_domain.id})")
    return db_domain


# ============================================================================
# ENDPOINTS : RelationshipType (Types de relations)
# ============================================================================

@router.get("/relationship-types", response_model=List[RelationshipTypeResponse])
@cache_result(ttl=3600, key_prefix="relationship_types")  # ✅ Cache 1h (données de référence)
async def list_relationship_types(
    is_active: Optional[bool] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db)
):
    """Liste tous les types de relations disponibles"""
    query = select(RelationshipType)
    
    if is_active is not None:
        query = query.where(RelationshipType.is_active == is_active)
    
    query = query.order_by(RelationshipType.name).offset(skip).limit(limit)
    
    result = db.execute(query)
    return result.scalars().all()


@router.post("/relationship-types", response_model=RelationshipTypeResponse, status_code=status.HTTP_201_CREATED)
async def create_relationship_type(
    relationship_type: RelationshipTypeCreate,
    db: Session = Depends(get_db)
):
    """Crée un nouveau type de relation"""
    # Vérifier l'unicité du nom
    existing = db.execute(
        select(RelationshipType).where(RelationshipType.name == relationship_type.name)
    ).scalar_one_or_none()
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Un type de relation avec le nom '{relationship_type.name}' existe déjà"
        )
    
    db_relationship_type = RelationshipType(**relationship_type.model_dump())
    db.add(db_relationship_type)
    db.commit()
    db.refresh(db_relationship_type)
    
    logger.info(f"✓ Type de relation créé: {db_relationship_type.name}")
    return db_relationship_type


@router.get("/relationship-types/{relationship_type_id}", response_model=RelationshipTypeResponse)
async def get_relationship_type(
    relationship_type_id: UUID,
    db: Session = Depends(get_db)
):
    """Récupère un type de relation par son ID"""
    db_relationship_type = db.get(RelationshipType, relationship_type_id)
    
    if not db_relationship_type:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Type de relation non trouvé"
        )
    
    return db_relationship_type


@router.put("/relationship-types/{relationship_type_id}", response_model=RelationshipTypeResponse)
async def update_relationship_type(
    relationship_type_id: UUID,
    relationship_type: RelationshipTypeUpdate,
    db: Session = Depends(get_db)
):
    """Met à jour un type de relation"""
    db_relationship_type = db.get(RelationshipType, relationship_type_id)
    
    if not db_relationship_type:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Type de relation non trouvé"
        )
    
    # Mettre à jour les champs
    for key, value in relationship_type.model_dump(exclude_unset=True).items():
        setattr(db_relationship_type, key, value)
    
    db.commit()
    db.refresh(db_relationship_type)
    
    logger.info(f"✓ Type de relation mis à jour: {db_relationship_type.name}")
    return db_relationship_type


@router.delete("/relationship-types/{relationship_type_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_relationship_type(
    relationship_type_id: UUID,
    db: Session = Depends(get_db)
):
    """Supprime un type de relation"""
    db_relationship_type = db.get(RelationshipType, relationship_type_id)
    
    if not db_relationship_type:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Type de relation non trouvé"
        )
    
    db.delete(db_relationship_type)
    db.commit()
    
    logger.info(f"✓ Type de relation supprimé: {db_relationship_type.name}")


# ============================================================================
# ENDPOINTS : EcosystemEntity (Organismes)
# ============================================================================

def sanitize_entity_data(data: dict) -> dict:
    """
    Nettoie les données d'entité pour correspondre au modèle SQLAlchemy
    Filtre uniquement les champs autorisés
    """
    filtered_data = {k: v for k, v in data.items() if k in VALID_ENTITY_FIELDS}
    
    # Conversion de annual_revenue: string -> Decimal ou None
    if 'annual_revenue' in filtered_data and filtered_data['annual_revenue'] is not None:
        try:
            from decimal import Decimal
            value = filtered_data['annual_revenue']
            if isinstance(value, str):
                filtered_data['annual_revenue'] = Decimal(value.strip())
        except (ValueError, AttributeError):
            filtered_data['annual_revenue'] = None
    
    # S'assurer que hierarchy_level est un int
    if 'hierarchy_level' in filtered_data and filtered_data['hierarchy_level'] is not None:
        try:
            filtered_data['hierarchy_level'] = int(filtered_data['hierarchy_level'])
        except (ValueError, TypeError):
            filtered_data['hierarchy_level'] = 0
    
    return filtered_data


@router.get("/entities", response_model=EcosystemEntityListResponse)
# @cache_result(ttl=900, key_prefix="ecosystem_entities")  # ⏸️ Cache désactivé temporairement pour debug member_count
async def list_entities(
    stakeholder_type: Optional[Literal["internal", "external"]] = Query(None),
    is_active: Optional[bool] = Query(None),
    is_domain: Optional[bool] = Query(None),
    is_base_template: Optional[bool] = Query(None),  # ✅ AJOUTÉ pour filtrer les templates
    parent_entity_id: Optional[UUID] = Query(None),
    client_organization_id: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    current_user: User = Depends(require_permission("ECOSYSTEM_READ")),
    db: Session = Depends(get_db)
):
    """Liste tous les organismes de l'écosystème avec filtres"""
    # 🔒 Validation tenant
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès interdit : utilisateur sans tenant"
        )

    logger.info(f"📋 Liste des entités pour tenant: {current_user.tenant_id}")

    # 🔒 Filtrer par tenant : universal (tenant_id IS NULL) OU tenant spécifique
    query = select(EcosystemEntity).where(
        or_(
            EcosystemEntity.tenant_id == None,  # Entités universelles
            EcosystemEntity.tenant_id == current_user.tenant_id  # Entités du tenant
        )
    )

    # Filtres
    if stakeholder_type:
        query = query.where(EcosystemEntity.stakeholder_type == stakeholder_type)
    
    if is_domain is not None:
        query = query.where(EcosystemEntity.is_domain == is_domain)
    
    if is_base_template is not None:  # ✅ AJOUTÉ
        query = query.where(EcosystemEntity.is_base_template == is_base_template)
    
    if is_active is not None:
        query = query.where(EcosystemEntity.is_active == is_active)
    
    if parent_entity_id:
        query = query.where(EcosystemEntity.parent_entity_id == parent_entity_id)
    
    if client_organization_id:
        query = query.where(EcosystemEntity.client_organization_id == client_organization_id)
    
    # Pagination
    query = query.offset(skip).limit(limit)
    
    # Exécution
    result = db.execute(query)
    entities = result.scalars().all()
    
    # ✅ PATCH : Charger manuellement les champs manquants depuis la BDD
    enriched_entities = []

    for entity in entities:
        # Charger les champs manquants + comptage membres avec une requête SQL brute
        # Le comptage dépend du type de stakeholder :
        # - external : compter depuis entity_member
        # - internal : compter depuis users (via default_org_id)
        extra_fields_query = sql_text("""
            SELECT
                ee.pole_id,
                ee.category_id,
                ee.ecosystem_domain_id,
                CASE
                    WHEN ee.stakeholder_type = 'external' THEN
                        (SELECT COUNT(*) FROM entity_member em WHERE em.entity_id = ee.id AND em.is_active = true)
                    WHEN ee.stakeholder_type = 'internal' THEN
                        (SELECT COUNT(*) FROM users u WHERE u.default_org_id = ee.id AND u.is_active = true)
                    ELSE 0
                END as member_count
            FROM ecosystem_entity ee
            WHERE ee.id = :entity_id
        """)
        extra_fields = db.execute(extra_fields_query, {"entity_id": str(entity.id)}).fetchone()

        # Créer un dict avec tous les champs
        entity_dict = {
            "id": entity.id,
            "name": entity.name,
            "client_organization_id": entity.client_organization_id,
            "stakeholder_type": entity.stakeholder_type,
            "entity_category": entity.entity_category,
            "short_code": entity.short_code,
            "description": entity.description,
            "status": entity.status,
            "is_active": entity.is_active,
            "created_at": entity.created_at,
            "updated_at": entity.updated_at,
            # ✅ Ajouter les champs manquants
            "pole_id": extra_fields[0] if extra_fields else None,
            "category_id": extra_fields[1] if extra_fields else None,
            "ecosystem_domain_id": extra_fields[2] if extra_fields else None,
            # ✅ Ajouter le comptage des membres
            "member_count": int(extra_fields[3]) if extra_fields and extra_fields[3] is not None else 0,
        }
        enriched_entities.append(entity_dict)
    
    # Count total
    count_query = select(func.count()).select_from(EcosystemEntity).where(
        or_(
            EcosystemEntity.tenant_id == None,  # Entités universelles
            EcosystemEntity.tenant_id == current_user.tenant_id  # Entités du tenant
        )
    )
    if stakeholder_type:
        count_query = count_query.where(EcosystemEntity.stakeholder_type == stakeholder_type)
    if is_domain is not None:  # ✅ AJOUTÉ
        count_query = count_query.where(EcosystemEntity.is_domain == is_domain)
    if is_base_template is not None:  # ✅ AJOUTÉ
        count_query = count_query.where(EcosystemEntity.is_base_template == is_base_template)
    if client_organization_id:
        count_query = count_query.where(EcosystemEntity.client_organization_id == client_organization_id)
    
    total = db.execute(count_query).scalar()
    
    return {
        "items": enriched_entities,
        "total": total or 0,
        "skip": skip,
        "limit": limit
    }

@router.post("/entities", response_model=EcosystemEntityResponse, status_code=status.HTTP_201_CREATED)
async def create_entity(
    entity: EcosystemEntityCreate,
    enrich_with_insee: bool = Query(False, description="Enrichir automatiquement avec l'API INSEE"),
    current_user: User = Depends(require_permission("ECOSYSTEM_CREATE")),
    db: Session = Depends(get_db)
):
    """
    Crée un nouvel organisme dans l'écosystème (isolé par tenant)

    - **enrich_with_insee**: Si true et SIRET fourni, récupère automatiquement les données INSEE
    - Gère automatiquement la hiérarchie via les tables ecosystem_domains, poles et categories
    - L'organisme est créé pour le tenant de l'utilisateur connecté
    """
    # ✅ Isolation par tenant : vérifier que l'utilisateur a un tenant_id
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès interdit : utilisateur sans tenant"
        )

    entity_data = entity.model_dump()

    # ============================================================================
    # ✅ Résolution automatique du tenant_id depuis l'utilisateur connecté
    # ============================================================================
    client_org_id = entity_data.get("client_organization_id")
    # Forcer le tenant_id à celui de l'utilisateur (sécurité)
    tenant_id = current_user.tenant_id
    entity_data["tenant_id"] = tenant_id
    
    # ✅ VALIDATION UUID : Vérifier que client_org_id est un UUID valide
    if client_org_id:
        if isinstance(client_org_id, str):
            try:
                # Tenter de convertir en UUID
                client_org_id = uuid.UUID(client_org_id)
                entity_data["client_organization_id"] = client_org_id
            except (ValueError, AttributeError) as e:
                logger.error(f"❌ client_organization_id invalide (pas un UUID): '{client_org_id}'")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"client_organization_id doit être un UUID valide. Valeur reçue: '{client_org_id}'"
                )
        elif not isinstance(client_org_id, UUID):
            logger.error(f"❌ client_organization_id a un type invalide: {type(client_org_id)}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"client_organization_id doit être un UUID, reçu: {type(client_org_id)}"
            )

    # ✅ Vérifier que l'organisation appartient bien au tenant de l'utilisateur
    if client_org_id:
        from src.models.organization import Organization
        org = db.execute(
            select(Organization).where(
                Organization.id == client_org_id,
                Organization.tenant_id == current_user.tenant_id
            )
        ).scalar_one_or_none()

        if not org:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"L'organisation {client_org_id} n'appartient pas à votre tenant ou n'existe pas"
            )

    logger.info(f"✅ Création entité pour tenant {tenant_id}")

    # ============================================================================
    # 📋 Enrichissement INSEE si demandé
    # ============================================================================
    if enrich_with_insee and entity_data.get("siret"):
        insee_service = get_insee_service()
        try:
            entity_data = await insee_service.enrich_entity_with_insee(entity_data)
            logger.info(f"✓ Entité enrichie avec données INSEE")
        except Exception as e:
            logger.warning(f"Impossible d'enrichir avec INSEE: {e}")
    
    # ============================================================================
    # 🔧 RÉSOLUTION AUTOMATIQUE DE LA HIÉRARCHIE via SQL direct
    # ============================================================================
    
    stakeholder_type = entity_data.get("stakeholder_type")
    entity_category = entity_data.get("entity_category")
    
    # Convertir les enums en string si nécessaire
    if stakeholder_type and hasattr(stakeholder_type, 'value'):
        stakeholder_type = stakeholder_type.value
    if entity_category and hasattr(entity_category, 'value'):
        entity_category = entity_category.value
    
    if stakeholder_type:
        logger.info(f"🔧 Résolution de hiérarchie pour: stakeholder_type={stakeholder_type}, entity_category={entity_category}")
        
        # 1️⃣ Chercher le DOMAINE dans ecosystem_domains
        domain_name = "Externe" if stakeholder_type == "external" else "Interne"
        
        domain_result = db.execute(
            sql_text("SELECT id FROM ecosystem_domains WHERE name = :name LIMIT 1"),
            {"name": domain_name}
        ).fetchone()
        
        if not domain_result:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Domaine '{domain_name}' introuvable. Veuillez exécuter le script d'initialisation."
            )
        
        domain_id = str(domain_result[0])
        entity_data["ecosystem_domain_id"] = domain_id
        logger.info(f"✓ Domaine trouvé: {domain_name} (id={domain_id})")
        
        # 2️⃣ Pour les organismes EXTERNES : chercher la catégorie
        if stakeholder_type == "external" and entity_category:
            # ✨ CORRECTION : Ne chercher automatiquement QUE si category_id n'est PAS fournie
            if not entity_data.get("category_id"):
                logger.info(f"🔍 Recherche automatique de category_id pour entity_category={entity_category}")
                category_result = db.execute(
                    sql_text("""
                        SELECT id FROM categories 
                        WHERE entity_category = :category 
                        AND ecosystem_domain_id = :domain_id
                        AND parent_category_id IS NULL
                        LIMIT 1
                    """),
                    {"category": entity_category, "domain_id": domain_id}
                ).fetchone()
                
                if not category_result:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Catégorie '{entity_category}' introuvable pour le domaine Externe."
                    )
                
                category_id = str(category_result[0])
                entity_data["category_id"] = category_id
                logger.info(f"✅ Catégorie trouvée automatiquement: {entity_category} (id={category_id})")
            else:
                # ✅ category_id déjà fournie par le frontend, on la garde !
                category_id = entity_data["category_id"]
                logger.info(f"✅ Utilisation de la category_id fournie: {category_id}")
        
        # 3️⃣ Pour les organismes INTERNES : vérifier le pôle
        elif stakeholder_type == "internal":
            pole_id = entity_data.get("pole_id")
            
            if not pole_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Pour un organisme interne, le 'pole_id' est obligatoire."
                )
            
            pole_result = db.execute(
                sql_text("SELECT id FROM poles WHERE id = :pole_id LIMIT 1"),
                {"pole_id": pole_id}
            ).fetchone()
            
            if not pole_result:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Pôle avec l'ID '{pole_id}' introuvable."
                )
            
            entity_data["category_id"] = None
            entity_data["hierarchy_level"] = 3
            logger.info(f"✓ Pôle trouvé (id={pole_id})")
        
        logger.info(f"✓ Hiérarchie résolue: {domain_name}")
    
    # ============================================================================
    # 🔍 Vérifications
    # ============================================================================
    
    # Vérifier que le type de relation existe (si spécifié)
    if entity_data.get("relation_type_id"):
        relation_type = db.get(RelationshipType, entity_data["relation_type_id"])
        if not relation_type:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Type de relation non trouvé"
            )
    
    # ============================================================================
    # 💾 Création de l'entité
    # ============================================================================

    # Nettoyer et filtrer les données
    entity_data_clean = sanitize_entity_data(entity_data)

    # Sauvegarder les IDs de hiérarchie pour mise à jour ultérieure
    ecosystem_domain_id_value = entity_data.get("ecosystem_domain_id")
    pole_id_value = entity_data.get("pole_id")
    category_id_value = entity_data.get("category_id")
    hierarchy_level_value = entity_data.get("hierarchy_level", 0)

    # ✅ AUDIT : Ajouter les champs d'audit
    entity_data_clean["created_by"] = current_user.email or str(current_user.id)
    entity_data_clean["updated_by"] = current_user.email or str(current_user.id)

    # Si notes n'est pas fourni, initialiser à None
    if "notes" not in entity_data_clean:
        entity_data_clean["notes"] = None

    # IMPORTANT: Retirer les colonnes qui causent des problèmes avec la contrainte
    entity_data_clean.pop("ecosystem_domain_id", None)
    entity_data_clean.pop("pole_id", None)
    entity_data_clean.pop("category_id", None)

    # Créer l'entité SANS les colonnes de hiérarchie
    db_entity = EcosystemEntity(**entity_data_clean)
    db.add(db_entity)
    db.flush()  # Obtenir l'ID

    # Mettre à jour les colonnes de hiérarchie via SQL brut
    if ecosystem_domain_id_value or pole_id_value or category_id_value:
        update_parts = []
        update_params = {"entity_id": str(db_entity.id)}
        
        if ecosystem_domain_id_value:
            update_parts.append("ecosystem_domain_id = :ecosystem_domain_id")
            update_params["ecosystem_domain_id"] = ecosystem_domain_id_value
        
        if pole_id_value:
            update_parts.append("pole_id = :pole_id")
            update_params["pole_id"] = pole_id_value
        
        if category_id_value:
            update_parts.append("category_id = :category_id")
            update_params["category_id"] = category_id_value
        
        if hierarchy_level_value:
            update_parts.append("hierarchy_level = :hierarchy_level")
            update_params["hierarchy_level"] = hierarchy_level_value
        
        # Calculer hierarchy_path
        if ecosystem_domain_id_value:
            if category_id_value:
                hierarchy_path = f"/{ecosystem_domain_id_value}/{category_id_value}/{db_entity.id}"
            elif pole_id_value:
                hierarchy_path = f"/{ecosystem_domain_id_value}/{pole_id_value}/{db_entity.id}"
            else:
                hierarchy_path = f"/{ecosystem_domain_id_value}/{db_entity.id}"
            
            update_parts.append("hierarchy_path = :hierarchy_path")
            update_params["hierarchy_path"] = hierarchy_path
        
        if update_parts:
            update_sql = f"""
                UPDATE ecosystem_entity 
                SET {', '.join(update_parts)}, updated_at = now()
                WHERE id = :entity_id
            """
            db.execute(sql_text(update_sql), update_params)
            logger.info(f"✓ Hiérarchie mise à jour via SQL pour l'entité {db_entity.id}")

    db.commit()
    db.refresh(db_entity)

    logger.info(f"✓ Entité créée: {db_entity.name} (id={db_entity.id}, level={getattr(db_entity, 'hierarchy_level', 0)})")
    return db_entity

@router.get("/entities/{entity_id}", response_model=EcosystemEntityResponse)
async def get_entity(
    entity_id: UUID,
    current_user: User = Depends(require_permission("ECOSYSTEM_READ")),
    db: Session = Depends(get_db)
):
    """Récupère un organisme par son ID"""
    # 🔒 Validation tenant
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès interdit : utilisateur sans tenant"
        )

    # 🔒 Récupérer l'entité avec vérification tenant
    db_entity = db.execute(
        select(EcosystemEntity).where(
            EcosystemEntity.id == entity_id,
            or_(
                EcosystemEntity.tenant_id == None,  # Entité universelle
                EcosystemEntity.tenant_id == current_user.tenant_id  # Entité du tenant
            )
        )
    ).scalar_one_or_none()

    if not db_entity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organisme non trouvé"
        )

    return db_entity


@router.put("/entities/{entity_id}", response_model=EcosystemEntityResponse)
async def update_entity(
    entity_id: UUID,
    entity: EcosystemEntityUpdate,
    current_user: User = Depends(require_permission("ECOSYSTEM_UPDATE")),
    db: Session = Depends(get_db)
):
    """Met à jour un organisme"""
    # 🔒 Validation tenant
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès interdit : utilisateur sans tenant"
        )

    # 🔒 Récupérer l'entité avec vérification tenant (uniquement les entités du tenant, pas les universelles)
    db_entity = db.execute(
        select(EcosystemEntity).where(
            EcosystemEntity.id == entity_id,
            EcosystemEntity.tenant_id == current_user.tenant_id  # Seules les entités du tenant peuvent être modifiées
        )
    ).scalar_one_or_none()

    if not db_entity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organisme non trouvé ou vous n'avez pas les droits pour le modifier"
        )

    # Mettre à jour les champs
    update_data = sanitize_entity_data(entity.model_dump(exclude_unset=True))

    # ✅ AUDIT : Ajouter updated_by
    update_data["updated_by"] = current_user.email or str(current_user.id)

    for key, value in update_data.items():
        setattr(db_entity, key, value)

    db.commit()
    db.refresh(db_entity)

    logger.info(f"✓ Entité mise à jour: {db_entity.name}")
    return db_entity


@router.delete("/entities/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entity(
    entity_id: UUID,
    current_user: User = Depends(require_permission("ECOSYSTEM_DELETE")),
    db: Session = Depends(get_db)
):
    """Supprime un organisme"""
    # 🔒 Validation tenant
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès interdit : utilisateur sans tenant"
        )

    # 🔒 Récupérer l'entité avec vérification tenant (uniquement les entités du tenant)
    db_entity = db.execute(
        select(EcosystemEntity).where(
            EcosystemEntity.id == entity_id,
            EcosystemEntity.tenant_id == current_user.tenant_id  # Seules les entités du tenant peuvent être supprimées
        )
    ).scalar_one_or_none()

    if not db_entity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organisme non trouvé ou vous n'avez pas les droits pour le supprimer"
        )

    db.delete(db_entity)
    db.commit()

    logger.info(f"✓ Entité supprimée: {db_entity.name}")


@router.get("/entities/{entity_id}/hierarchy")
async def get_entity_hierarchy(
    entity_id: UUID,
    direction: Literal["ancestors", "descendants", "both"] = Query("both"),
    current_user: User = Depends(require_permission("ECOSYSTEM_READ")),
    db: Session = Depends(get_db)
):
    """
    Récupère la hiérarchie d'un organisme
    - ancestors: Uniquement les ancêtres (chemin vers la racine)
    - descendants: Uniquement les enfants (sous-arbre complet)
    - both: Ancêtres + descendants
    """
    # 🔒 Validation tenant
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès interdit : utilisateur sans tenant"
        )

    # 🔒 Vérifier que l'entité appartient au tenant ou est universelle
    db_entity = db.execute(
        select(EcosystemEntity).where(
            EcosystemEntity.id == entity_id,
            or_(
                EcosystemEntity.tenant_id == None,  # Entité universelle
                EcosystemEntity.tenant_id == current_user.tenant_id  # Entité du tenant
            )
        )
    ).scalar_one_or_none()

    if not db_entity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organisme non trouvé"
        )

    result = []

    # Récupérer les ancêtres
    if direction in ["ancestors", "both"]:
        ancestors_query = select(EcosystemEntity).where(
            EcosystemEntity.hierarchy_path.like(f"%{entity_id}%"),
            or_(
                EcosystemEntity.tenant_id == None,  # Ancêtres universels
                EcosystemEntity.tenant_id == current_user.tenant_id  # Ancêtres du tenant
            )
        ).order_by(EcosystemEntity.hierarchy_level)

        ancestors = db.execute(ancestors_query).scalars().all()
        result.extend(ancestors)

    # Récupérer les descendants
    if direction in ["descendants", "both"]:
        descendants_query = select(EcosystemEntity).where(
            EcosystemEntity.hierarchy_path.like(f"{db_entity.hierarchy_path}%"),
            or_(
                EcosystemEntity.tenant_id == None,  # Descendants universels
                EcosystemEntity.tenant_id == current_user.tenant_id  # Descendants du tenant
            )
        ).order_by(EcosystemEntity.hierarchy_level, EcosystemEntity.name)

        descendants = db.execute(descendants_query).scalars().all()
        result.extend(descendants)

    # Supprimer les doublons
    result = list({e.id: e for e in result}.values())

    return result


# ============================================================================
# ENDPOINTS : INSEE
# ============================================================================

@router.post("/entities/enrich-insee", response_model=INSEEDataResponse)
async def enrich_with_insee(
    request: INSEEDataRequest
):
    """
    Récupère les données INSEE pour un SIRET donné.
    Ne renvoie QUE des champs issus de l'INSEE (+ raw_data pour debug).
    """
    insee_service = get_insee_service()

    logger.info("[INSEE] /entities/enrich-insee start siret=%s", request.siret)

    try:
        insee_data = await insee_service.get_establishment_by_siret(request.siret)
        if not insee_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Aucune donnée INSEE trouvée pour ce SIRET"
            )

        parsed = insee_service.parse_establishment_data(insee_data)

        # Vérifications minimales
        if not parsed.get("siret") or not parsed.get("siren"):
            logger.error("[INSEE] Réponse incomplète: siret/siren manquant (siret demandé=%s)", request.siret)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Réponse INSEE incomplète : SIRET ou SIREN manquant"
            )

        logger.info("[INSEE] parsed ok siret=%s siren=%s cat=%s",
                    parsed.get("siret"), parsed.get("siren"), parsed.get("enterprise_category"))

        # On renvoie STRICTEMENT les champs INSEE + raw_data
        return INSEEDataResponse(
            siret=parsed.get("siret"),
            siren=parsed.get("siren"),
            legal_name=parsed.get("legal_name"),
            trade_name=parsed.get("trade_name"),
            ape_code=parsed.get("ape_code"),
            address_line1=parsed.get("address_line1"),
            postal_code=parsed.get("postal_code"),
            city=parsed.get("city"),
            creation_date=parsed.get("creation_date"),
            enterprise_category=parsed.get("enterprise_category"),
            raw_data=parsed.get("raw_insee_data") or {}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[INSEE] enrich-insee error siret=%s: %s", request.siret, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erreur lors de la récupération des données INSEE"
        )


# ============================================================================
# ENDPOINTS : EntityMember (Membres d'entités)
# ============================================================================

@router.get("/entities/{entity_id}/members", response_model=List[EntityMemberResponse])
async def list_entity_members(
    entity_id: UUID,
    current_user: User = Depends(require_permission("ECOSYSTEM_READ")),
    db: Session = Depends(get_db)
):
    """Liste tous les membres d'un organisme"""
    # 🔒 Validation tenant
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès interdit : utilisateur sans tenant"
        )

    # 🔒 Vérifier que l'entité appartient au tenant ou est universelle
    db_entity = db.execute(
        select(EcosystemEntity).where(
            EcosystemEntity.id == entity_id,
            or_(
                EcosystemEntity.tenant_id == None,  # Entité universelle
                EcosystemEntity.tenant_id == current_user.tenant_id  # Entité du tenant
            )
        )
    ).scalar_one_or_none()

    if not db_entity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organisme non trouvé"
        )

    query = select(EntityMember).where(EntityMember.entity_id == entity_id)
    result = db.execute(query)
    return result.scalars().all()


@router.post("/entities/{entity_id}/members", response_model=EntityMemberResponse, status_code=status.HTTP_201_CREATED)
async def add_entity_member(
    entity_id: UUID,
    member: EntityMemberCreate,
    current_user: User = Depends(require_permission("ECOSYSTEM_CREATE")),
    db: Session = Depends(get_db)
):
    """Ajoute un membre à un organisme"""
    # 🔒 Validation tenant
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès interdit : utilisateur sans tenant"
        )

    # 🔒 Vérifier que l'entité appartient au tenant (on ne peut ajouter des membres qu'aux entités du tenant)
    db_entity = db.execute(
        select(EcosystemEntity).where(
            EcosystemEntity.id == entity_id,
            EcosystemEntity.tenant_id == current_user.tenant_id  # Seulement les entités du tenant
        )
    ).scalar_one_or_none()

    if not db_entity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organisme non trouvé ou vous n'avez pas les droits pour y ajouter des membres"
        )

    member_data = member.model_dump()
    member_data["entity_id"] = entity_id

    db_member = EntityMember(**member_data)
    db.add(db_member)
    db.commit()
    db.refresh(db_member)

    logger.info(f"✓ Membre ajouté à l'entité {entity_id}: {db_member.user_id}")
    return db_member


@router.put("/entities/{entity_id}/members/{member_id}", response_model=EntityMemberResponse)
async def update_entity_member(
    entity_id: UUID,
    member_id: UUID,
    member: EntityMemberUpdate,
    current_user: User = Depends(require_permission("ECOSYSTEM_UPDATE")),
    db: Session = Depends(get_db)
):
    """Met à jour un membre d'un organisme"""
    # 🔒 Validation tenant
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès interdit : utilisateur sans tenant"
        )

    # 🔒 Vérifier que l'entité appartient au tenant
    db_entity = db.execute(
        select(EcosystemEntity).where(
            EcosystemEntity.id == entity_id,
            EcosystemEntity.tenant_id == current_user.tenant_id
        )
    ).scalar_one_or_none()

    if not db_entity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organisme non trouvé ou vous n'avez pas les droits"
        )

    db_member = db.get(EntityMember, member_id)

    if not db_member or db_member.entity_id != entity_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Membre non trouvé"
        )

    # Mettre à jour les champs
    for key, value in member.model_dump(exclude_unset=True).items():
        setattr(db_member, key, value)

    db.commit()
    db.refresh(db_member)

    logger.info(f"✓ Membre mis à jour: {db_member.user_id}")
    return db_member


@router.delete("/entities/{entity_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_entity_member(
    entity_id: UUID,
    member_id: UUID,
    current_user: User = Depends(require_permission("ECOSYSTEM_DELETE")),
    db: Session = Depends(get_db)
):
    """Retire un membre d'un organisme"""
    # 🔒 Validation tenant
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès interdit : utilisateur sans tenant"
        )

    # 🔒 Vérifier que l'entité appartient au tenant
    db_entity = db.execute(
        select(EcosystemEntity).where(
            EcosystemEntity.id == entity_id,
            EcosystemEntity.tenant_id == current_user.tenant_id
        )
    ).scalar_one_or_none()

    if not db_entity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organisme non trouvé ou vous n'avez pas les droits"
        )

    db_member = db.get(EntityMember, member_id)

    if not db_member or db_member.entity_id != entity_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Membre non trouvé"
        )

    db.delete(db_member)
    db.commit()

    logger.info(f"✓ Membre retiré de l'entité {entity_id}: {db_member.user_id}")


# ============================================================================
# ENDPOINTS : Pôles
# ============================================================================
# Correction de l'endpoint GET /categories
# Fichier: backend/src/api/v1/ecosystem.py
# Ligne: 908-952

@router.get("/categories", response_model=List[dict])
# @cache_result(ttl=1800, key_prefix="ecosystem_categories")  # ❌ DÉSACTIVÉ: problème isolation multi-tenant
async def get_categories(
    stakeholder_type: Optional[str] = Query(None, description="Filtrer par type: internal ou external"),
    client_organization_id: Optional[str] = Query(None, description="ID de l'organisation cliente (pour filtrer par tenant)"),
    tenant_id: Optional[str] = Query(None, description="🔒 SÉCURITÉ: ID du tenant cible (pour isolation cache)"),
    current_user: User = Depends(require_permission("ECOSYSTEM_READ")),
    db: Session = Depends(get_db)
):
    """
    Récupère la liste des catégories visibles pour l'utilisateur :
    - Catégories universelles (tenant_id = NULL)
    - Catégories spécifiques au tenant de l'utilisateur ou de l'organisation sélectionnée

    - **stakeholder_type**: Filtrer par 'internal' ou 'external'
    - **client_organization_id**: Pour les super-admins, permet de filtrer par organisation
    - **tenant_id**: 🔒 Pour isolation cache multi-tenant (alimenté automatiquement)
    """
    from sqlalchemy import select, and_
    from src.models.organization import Organization

    # ✅ PRIORITÉ 1: tenant_id explicite (envoyé par l'UI pour isolation cache)
    # ✅ PRIORITÉ 2: Résolution via client_organization_id
    # ✅ PRIORITÉ 3: Fallback sur current_user.tenant_id
    effective_tenant_id = None

    if tenant_id:
        # Tenant explicite fourni par l'UI (priorité max pour cache)
        effective_tenant_id = tenant_id
        logger.info(f"🔒 Utilisation tenant_id explicite: {tenant_id}")
    elif client_organization_id:
        # Résoudre le tenant_id depuis l'organization_id
        org = db.execute(
            select(Organization).where(Organization.id == client_organization_id)
        ).scalar_one_or_none()

        if org:
            effective_tenant_id = org.tenant_id
            logger.info(f"🔒 Résolution tenant via organization {client_organization_id}: {effective_tenant_id}")
        else:
            logger.warning(f"Organization {client_organization_id} introuvable")
            effective_tenant_id = current_user.tenant_id
    else:
        # Fallback: utiliser le tenant de l'utilisateur connecté
        effective_tenant_id = current_user.tenant_id

    # ✅ CRITIQUE: Forcer le cache Redis à utiliser le tenant_id résolu dans la clé
    # Sans ça, le cache utilise client_organization_id et mélange les tenants
    tenant_id = str(effective_tenant_id) if effective_tenant_id else None
    logger.info(f"🔑 Cache key will use tenant_id: {tenant_id}")

    # ✅ Isolation par tenant : catégories universelles OU spécifiques au tenant effectif
    query_text = """
        SELECT
            id,
            name,
            entity_category,
            description,
            short_code,
            parent_category_id,
            hierarchy_level,
            tenant_id,
            is_base_template
        FROM categories
        WHERE is_active = true
          AND (tenant_id IS NULL OR tenant_id = :tenant_id)
    """

    params = {"tenant_id": str(effective_tenant_id) if effective_tenant_id else None}

    # Filtrer par ecosystem_domain si stakeholder_type fourni
    if stakeholder_type:
        domain_name = "Externe" if stakeholder_type == "external" else "Interne"
        query_text += " AND ecosystem_domain_id = (SELECT id FROM ecosystem_domains WHERE name = :domain_name)"
        params["domain_name"] = domain_name
    
    # ✅ CORRECTION : Trier par niveau hiérarchique puis nom
    query_text += " ORDER BY hierarchy_level, name"
    
    result = db.execute(sql_text(query_text), params).fetchall()

    # 🔍 DEBUG: Logger CHAQUE ligne retournée par SQL pour voir ce qui vient de la DB
    logger.info(f"🔍 SQL a retourné {len(result)} lignes de la base de données")
    for idx, row in enumerate(result):
        logger.info(f"🔍 Ligne {idx+1}: name={row[1]}, entity_category={row[2]}, tenant_id={row[7]}")

    categories = []
    for row in result:
        categories.append({
            "id": str(row[0]),
            "name": row[1],
            "entity_category": row[2],
            "description": row[3],
            "short_code": row[4],
            "parent_category_id": str(row[5]) if row[5] else None,
            "hierarchy_level": row[6],
            "tenant_id": str(row[7]) if row[7] else None,      # ✅ AJOUTÉ pour frontend
            "is_base_template": row[8] if row[8] else False    # ✅ AJOUTÉ pour frontend
        })

    logger.info(f"✅ {len(categories)} catégories récupérées (type={stakeholder_type})")

    # 🔍 DEBUG: Logger les catégories de type "supplier" pour voir le problème
    supplier_cats = [c for c in categories if c['entity_category'] == 'supplier']
    logger.info(f"🔍 {len(supplier_cats)} catégories SUPPLIER dans la réponse:")
    for cat in supplier_cats:
        logger.info(f"🔍   - {cat['name']} (tenant_id={cat['tenant_id']})")

    return categories


@router.get("/poles", response_model=PoleListResponse)
@cache_result(ttl=1800, key_prefix="ecosystem_poles")  # ✅ Cache 30min
async def list_poles(
    client_organization_id: Optional[str] = Query(None, description="ID de l'organisation cliente"),
    is_active: Optional[bool] = Query(None),
    search: Optional[str] = Query(None, description="Recherche par nom ou short_code"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    current_user: User = Depends(require_permission("ECOSYSTEM_READ")),
    db: Session = Depends(get_db)
):
    """
    Liste les pôles visibles pour l'utilisateur :
    - Pôles universels (tenant_id = NULL)
    - Pôles spécifiques au tenant de l'utilisateur
    """
    # ✅ Isolation par tenant : pôles universels OU spécifiques au tenant
    base = select(Pole).where(
        or_(
            Pole.tenant_id == None,  # Pôles universels
            Pole.tenant_id == current_user.tenant_id  # Pôles spécifiques au tenant
        )
    )

    # Filtrer par client_organization_id si fourni
    if client_organization_id:
        base = base.where(
            or_(
                Pole.client_organization_id == client_organization_id,
                Pole.tenant_id == None  # Garder les pôles universels
            )
        )

    if is_active is not None:
        base = base.where(Pole.is_active == is_active)

    if search:
        s = f"%{search.lower()}%"
        base = base.where(or_(Pole.name.ilike(s), Pole.short_code.ilike(s)))

    # total sans pagination
    total = db.execute(base.with_only_columns(func.count()).order_by(None)).scalar() or 0

    # page
    rows = db.execute(
        base.order_by(Pole.name.asc()).offset(skip).limit(limit)
    ).scalars().all()

    return {
        "items": [PoleResponse.model_validate(p) for p in rows],
        "total": total,
        "skip": skip,
        "limit": limit
    }



@router.post("/poles", response_model=PoleResponse, status_code=status.HTTP_201_CREATED)
async def create_pole_with_tenant(
    pole: PoleCreateWithTenant,
    db: Session = Depends(get_db),
    x_tenant_id: Optional[str] = Header(None, description="ID du tenant (depuis le JWT ou header)")
):
    """
    Crée un nouveau pôle (universel ou personnalisé selon tenant_id)
    
    **Logique tenant:**
    - Si `tenant_id` est fourni dans le body OU dans le header → Pôle personnalisé
    - Si `tenant_id` est null ET `is_base_template=true` → Pôle universel (admin seulement)
    - Vérifie l'unicité du nom dans le scope du tenant
    
    **Exemples:**
    ```json
    // Pôle personnalisé pour un client
    {
      "ecosystem_domain_id": "uuid-domain-interne",
      "tenant_id": "uuid-tenant",
      "name": "Pôle Innovation EMEA",
      "description": "Pôle innovation pour la région EMEA",
      "is_base_template": false
    }
    
    // Pôle universel (admin système)
    {
      "ecosystem_domain_id": "uuid-domain-interne",
      "tenant_id": null,
      "name": "Direction",
      "description": "Direction générale",
      "is_base_template": true
    }
    ```
    """
    
    # Déterminer le tenant_id effectif
    effective_tenant_id = pole.tenant_id
    if not effective_tenant_id and x_tenant_id:
        try:
            effective_tenant_id = UUID(x_tenant_id)
        except:
            pass
    
    # Vérifier l'unicité du nom dans le scope du tenant
    query = select(Pole).where(Pole.name == pole.name)
    
    if effective_tenant_id:
        # Pour un tenant spécifique, vérifier l'unicité dans ce tenant
        query = query.where(Pole.tenant_id == effective_tenant_id)
    else:
        # Pour un pôle universel, vérifier l'unicité globale
        query = query.where(Pole.tenant_id.is_(None))
    
    existing = db.execute(query).scalar_one_or_none()
    
    if existing:
        scope = f"pour le tenant {effective_tenant_id}" if effective_tenant_id else "dans les templates universels"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Un pôle avec le nom '{pole.name}' existe déjà {scope}"
        )
    
    # Créer le pôle
    pole_data = pole.model_dump()
    pole_data['tenant_id'] = effective_tenant_id

    # Calculer hierarchy_level et hierarchy_path
    if pole.parent_pole_id:
        # Récupérer le pôle parent
        parent_pole = db.execute(select(Pole).where(Pole.id == pole.parent_pole_id)).scalar_one_or_none()
        if not parent_pole:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Pôle parent {pole.parent_pole_id} introuvable"
            )
        pole_data['hierarchy_level'] = parent_pole.hierarchy_level + 1
    else:
        # Pôle racine
        pole_data['hierarchy_level'] = 1

    # Créer le pôle sans hierarchy_path (sera calculé après insertion)
    db_pole = Pole(**pole_data)
    db.add(db_pole)
    db.flush()  # Flush pour obtenir l'ID généré

    # Calculer hierarchy_path maintenant que nous avons l'ID
    if pole.parent_pole_id:
        parent_pole = db.execute(select(Pole).where(Pole.id == pole.parent_pole_id)).scalar_one()
        db_pole.hierarchy_path = (parent_pole.hierarchy_path or f"/{parent_pole.id}") + f"/{db_pole.id}"
    else:
        db_pole.hierarchy_path = f"/{db_pole.id}"

    db.commit()
    db.refresh(db_pole)

    # Invalider le cache des pôles
    redis_manager.delete_pattern("ecosystem_poles:*")

    logger.info(f"✓ Pôle créé: {db_pole.name} (tenant_id={db_pole.tenant_id}, hierarchy_level={db_pole.hierarchy_level}, is_base_template={db_pole.is_base_template})")
    return db_pole


@router.get("/poles/{pole_id}", response_model=PoleResponse)
async def get_pole(
    pole_id: UUID,
    db: Session = Depends(get_db)
):
    """Récupère un pôle par son ID"""
    db_pole = db.get(Pole, pole_id)
    
    if not db_pole:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pôle non trouvé"
        )
    
    return db_pole


@router.put("/poles/{pole_id}", response_model=PoleResponse)
async def update_pole(
    pole_id: UUID,
    pole: PoleUpdate,
    db: Session = Depends(get_db)
):
    """Met à jour un pôle"""
    db_pole = db.get(Pole, pole_id)
    
    if not db_pole:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pôle non trouvé"
        )
    
    # Mettre à jour les champs
    for key, value in pole.model_dump(exclude_unset=True).items():
        setattr(db_pole, key, value)
    
    db.commit()
    db.refresh(db_pole)
    
    logger.info(f"✓ Pôle mis à jour: {db_pole.name}")
    return db_pole


@router.delete("/poles/{pole_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pole(
    pole_id: UUID,
    db: Session = Depends(get_db)
):
    """Supprime un pôle"""
    db_pole = db.get(Pole, pole_id)
    
    if not db_pole:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pôle non trouvé"
        )
    
    db.delete(db_pole)
    db.commit()
    
    logger.info(f"✓ Pôle supprimé: {db_pole.name}")


# ============================================================================
# ENDPOINT : ENTITIES WITH DETAILS (avec JOIN poles et categories)
# ============================================================================

@router.get("/entities-with-details", response_model=EcosystemEntityListResponse)
async def list_entities_with_details(
    client_organization_id: Optional[str] = Query(None, description="ID de l'organisation cliente"),
    tenant_id: Optional[UUID] = Query(None, description="ID du tenant"),
    stakeholder_type: Optional[Literal["internal", "external"]] = Query(None),
    pole_id: Optional[UUID] = Query(None),
    category_id: Optional[UUID] = Query(None),
    status: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(True),
    search: Optional[str] = Query(None, description="Recherche par nom"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    current_user: User = Depends(require_permission("ECOSYSTEM_READ")),
    db: Session = Depends(get_db)
):
    """
    Liste toutes les entités de l'écosystème AVEC les détails des pôles et catégories

    Retourne les entités avec les champs suivants ajoutés via JOIN:
    - pole_name: Nom du pôle (pour les entités internes)
    - pole_code: Code du pôle
    - category_name: Nom de la catégorie (pour les entités externes)
    - category_code: Code de la catégorie
    """
    from sqlalchemy import text as sql_text

    # 🔒 Validation tenant
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès interdit : utilisateur sans tenant"
        )

    logger.info(f"📋 Liste des entités avec détails pour tenant: {current_user.tenant_id}")

    # Construire la requête SQL avec JOIN
    query_conditions = []
    params = {}

    # 🔒 Filtrage par tenant : universel OU tenant spécifique
    query_conditions.append("(e.tenant_id IS NULL OR e.tenant_id = :current_tenant_id)")
    params['current_tenant_id'] = str(current_user.tenant_id)

    # Filtres de base
    query_conditions.append("e.is_domain = false")
    query_conditions.append("e.is_base_template = false")

    if client_organization_id:
        query_conditions.append("e.client_organization_id = :org_id")
        params['org_id'] = client_organization_id

    if tenant_id:
        # Vérifier que le tenant demandé est celui de l'utilisateur
        if str(tenant_id) != str(current_user.tenant_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Vous ne pouvez pas accéder aux entités d'un autre tenant"
            )
        query_conditions.append("e.tenant_id = :tenant_id")
        params['tenant_id'] = str(tenant_id)
    
    if stakeholder_type:
        query_conditions.append("e.stakeholder_type = :stakeholder_type")
        params['stakeholder_type'] = stakeholder_type
    
    if pole_id:
        query_conditions.append("e.pole_id = :pole_id")
        params['pole_id'] = str(pole_id)
    
    if category_id:
        query_conditions.append("e.category_id = :category_id")
        params['category_id'] = str(category_id)
    
    if status:
        query_conditions.append("e.status = :status")
        params['status'] = status
    
    if is_active is not None:
        query_conditions.append("e.is_active = :is_active")
        params['is_active'] = is_active
    
    if search:
        query_conditions.append("(e.name ILIKE :search OR e.legal_name ILIKE :search)")
        params['search'] = f"%{search}%"
    
    # WHERE clause
    where_clause = " AND ".join(query_conditions) if query_conditions else "1=1"
    
    # Requête principale avec JOIN
    query_text = f"""
        SELECT 
            e.id,
            e.client_organization_id,
            e.name,
            e.legal_name,
            e.trade_name,
            e.short_name,
            e.siret,
            e.siren,
            e.ape_code,
            e.vat_number,
            e.registration_number,
            e.registration_country,
            e.stakeholder_type,
            e.entity_category,
            e.parent_entity_id,
            e.hierarchy_level,
            e.hierarchy_path,
            e.address_line1,
            e.address_line2,
            e.address_line3,
            e.postal_code,
            e.city,
            e.region,
            e.country_code,
            e.insee_data,
            e.insee_last_sync,
            e.description,
            e.notes,
            e.is_active,
            e.is_certified,
            e.certification_info,
            e.created_at,
            e.updated_at,
            e.created_by,
            e.updated_by,
            e.relation_type_id,
            e.status,
            e.short_code,
            e.is_activated,
            e.activated_at,
            e.activated_by,
            e.mfa_config,
            e.tenant_id,
            e.is_domain,
            e.is_base_template,
            e.ecosystem_domain_id,
            e.pole_id,
            e.category_id,
            p.name as pole_name,
            p.short_code as pole_code,
            c.name as category_name,
            c.short_code as category_code
        FROM ecosystem_entity e
        LEFT JOIN poles p ON e.pole_id = p.id
        LEFT JOIN categories c ON e.category_id = c.id
        WHERE {where_clause}
        ORDER BY e.name
        LIMIT :limit OFFSET :skip
    """
    
    params['limit'] = limit
    params['skip'] = skip
    
    # Exécuter la requête
    result = db.execute(sql_text(query_text), params).fetchall()
    
    # Convertir les résultats en dictionnaires avec accès explicite aux colonnes du JOIN
    entities = []
    for row in result:
        # Créer le dictionnaire de base à partir du mapping
        entity_dict = dict(row._mapping)
        
        # S'assurer que les colonnes du JOIN sont bien présentes
        # (contournement pour les cas où _mapping ne les inclut pas)
        try:
            if hasattr(row, 'pole_name'):
                entity_dict['pole_name'] = row.pole_name
            if hasattr(row, 'pole_code'):
                entity_dict['pole_code'] = row.pole_code
            if hasattr(row, 'category_name'):
                entity_dict['category_name'] = row.category_name
            if hasattr(row, 'category_code'):
                entity_dict['category_code'] = row.category_code
        except Exception as e:
            logger.warning(f"Erreur lors de l'extraction des noms de pôles/catégories: {e}")
        
        entities.append(entity_dict)
    
    # Compter le total
    count_query = f"""
        SELECT COUNT(*) 
        FROM ecosystem_entity e
        WHERE {where_clause}
    """
    
    total = db.execute(sql_text(count_query), {k: v for k, v in params.items() if k not in ['limit', 'skip']}).scalar()
    
    logger.info(f"✓ {len(entities)} entités avec détails récupérées (total: {total})")
    
    return {
        "items": entities,
        "total": total or 0,
        "skip": skip,
        "limit": limit
    }

# ============================================================================
# ENDPOINT : STATISTIQUES
# ============================================================================

@router.get("/stats")
async def get_ecosystem_stats(
    client_organization_id: Optional[str] = Query(None, description="ID de l'organisation cliente"),
    db: Session = Depends(get_db)
):
    """
    Récupère les statistiques de l'écosystème
    
    Retourne :
    - Nombre total d'entités
    - Nombre d'entités actives, en attente, inactives
    - Nombre total de membres
    - Répartition interne/externe
    """
    
    # Requête de base
    query = select(EcosystemEntity).where(
        EcosystemEntity.is_domain == False,
        EcosystemEntity.is_base_template == False
    )
    
    # Filtrer par organisation si spécifié
    if client_organization_id:
        query = query.where(EcosystemEntity.client_organization_id == client_organization_id)
    
    # Récupérer toutes les entités
    result = db.execute(query)
    entities = result.scalars().all()
    
    # Calculer les statistiques
    total = len(entities)
    active = len([e for e in entities if e.status == 'active'])
    pending = len([e for e in entities if e.status == 'pending'])
    inactive = len([e for e in entities if e.status == 'inactive'])
    
    # Compter les membres selon le type d'entité :
    # - Externes (entity_member) : personnes auditées
    # - Internes (users via default_org_id) : utilisateurs internes
    total_members = 0
    try:
        if client_organization_id:
            # Compter les membres externes (entity_member) pour les entités de cette organisation
            external_members_query = text("""
                SELECT COUNT(DISTINCT em.id) as total
                FROM entity_member em
                JOIN ecosystem_entity ee ON ee.id = em.entity_id
                WHERE ee.client_organization_id = :org_id
                  AND ee.stakeholder_type = 'external'
                  AND em.is_active = true
            """)
            external_result = db.execute(external_members_query, {"org_id": client_organization_id}).first()
            external_members = external_result.total if external_result else 0

            # Compter les utilisateurs internes (users) pour les entités internes de cette organisation
            internal_members_query = text("""
                SELECT COUNT(DISTINCT u.id) as total
                FROM users u
                JOIN ecosystem_entity ee ON ee.id = u.default_org_id
                WHERE ee.client_organization_id = :org_id
                  AND ee.stakeholder_type = 'internal'
                  AND u.is_active = true
            """)
            internal_result = db.execute(internal_members_query, {"org_id": client_organization_id}).first()
            internal_members = internal_result.total if internal_result else 0

            total_members = external_members + internal_members
        else:
            # Compter tous les membres (externes + internes)
            external_count_query = text("SELECT COUNT(*) as total FROM entity_member WHERE is_active = true")
            external_result = db.execute(external_count_query).first()
            external_members = external_result.total if external_result else 0

            internal_count_query = text("SELECT COUNT(*) as total FROM users WHERE is_active = true")
            internal_result = db.execute(internal_count_query).first()
            internal_members = internal_result.total if internal_result else 0

            total_members = external_members + internal_members
    except Exception as e:
        # Si la requête échoue, ignorer
        logger.warning(f"Erreur comptage membres: {e}")
        pass
    
    # Répartition interne/externe
    internal_count = len([e for e in entities if e.stakeholder_type == 'internal'])
    external_count = len([e for e in entities if e.stakeholder_type == 'external'])
    
    # Répartition par catégorie (optionnel)
    pole_count = 0
    service_count = 0
    client_count = 0
    supplier_count = 0
    subcontractor_count = 0
    
    for entity in entities:
        category = entity.entity_category or ''
        if category == 'pole':
            pole_count += 1
        elif category == 'service':
            service_count += 1
        elif category == 'client':
            client_count += 1
        elif category == 'supplier':
            supplier_count += 1
        elif category == 'subcontractor':
            subcontractor_count += 1
    
    return {
        "total": total,
        "active": active,
        "pending": pending,
        "inactive": inactive,
        "total_members": total_members,
        "internal_count": internal_count,
        "external_count": external_count,
        "pole_count": pole_count,
        "service_count": service_count,
        "client_count": client_count,
        "supplier_count": supplier_count,
        "subcontractor_count": subcontractor_count
    }

# @router.post("/categories", response_model=dict, status_code=status.HTTP_201_CREATED)
# async def create_category_with_tenant(
#     category: CategoryCreateWithTenant,
#     db: Session = Depends(get_db),
#     x_tenant_id: Optional[str] = Header(None, description="ID du tenant (depuis le JWT ou header)")
# ):
#     """
#     Crée une nouvelle catégorie (universelle ou personnalisée selon tenant_id)
    
#     **Logique tenant:**
#     - Si `tenant_id` est fourni dans le body OU dans le header → Catégorie personnalisée
#     - Si `tenant_id` est null ET `is_base_template=true` → Catégorie universelle (admin seulement)
#     - Vérifie l'unicité du nom dans le scope du tenant
    
#     **Exemples:**
#     ```json
#     // Catégorie personnalisée pour un client
#     {
#       "ecosystem_domain_id": "uuid-domain-externe",
#       "pole_id": "uuid-pole-externe",
#       "tenant_id": "uuid-tenant",
#       "name": "Fournisseurs Cloud EMEA",
#       "entity_category": "supplier",
#       "description": "Fournisseurs cloud pour la région EMEA",
#       "is_base_template": false
#     }
    
#     // Catégorie universelle (admin système)
#     {
#       "ecosystem_domain_id": "uuid-domain-externe",
#       "pole_id": "uuid-pole-externe",
#       "tenant_id": null,
#       "name": "Clients",
#       "entity_category": "client",
#       "is_base_template": true
#     }
#     ```
#     """
    
#     # Déterminer le tenant_id effectif
#     effective_tenant_id = category.tenant_id
#     if not effective_tenant_id and x_tenant_id:
#         try:
#             effective_tenant_id = UUID(x_tenant_id)
#         except:
#             pass
    
#     # Vérifier l'unicité du nom dans le scope du tenant
#     query = select(Category).where(Category.name == category.name)
    
#     if effective_tenant_id:
#         # Pour un tenant spécifique, vérifier l'unicité dans ce tenant
#         query = query.where(Category.tenant_id == effective_tenant_id)
#     else:
#         # Pour une catégorie universelle, vérifier l'unicité globale
#         query = query.where(Category.tenant_id.is_(None))
    
#     existing = db.execute(query).scalar_one_or_none()
    
#     if existing:
#         scope = f"pour le tenant {effective_tenant_id}" if effective_tenant_id else "dans les templates universels"
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail=f"Une catégorie avec le nom '{category.name}' existe déjà {scope}"
#         )
    
#     # Créer la catégorie
#     category_data = category.model_dump()
#     category_data['tenant_id'] = effective_tenant_id
    
#     # Gérer le champ keywords (conversion list -> JSON string si nécessaire)
#     if 'keywords' in category_data and isinstance(category_data['keywords'], list):
#         import json
#         category_data['keywords'] = json.dumps(category_data['keywords'])
    
#     db_category = Category(**category_data)
#     db.add(db_category)
#     db.commit()
#     db.refresh(db_category)
    
#     # Construire la réponse
#     response = {
#         "id": str(db_category.id),
#         "name": db_category.name,
#         "entity_category": db_category.entity_category,
#         "description": db_category.description,
#         "short_code": db_category.short_code,
#         "tenant_id": str(db_category.tenant_id) if db_category.tenant_id else None,
#         "is_base_template": db_category.is_base_template,
#         "ecosystem_domain_id": str(db_category.ecosystem_domain_id),
#         "pole_id": str(db_category.pole_id),
#         "status": db_category.status,
#         "is_active": db_category.is_active,
#         "created_at": db_category.created_at.isoformat() if db_category.created_at else None
#     }
    
#     logger.info(f"✓ Catégorie créée: {db_category.name} (tenant_id={db_category.tenant_id}, is_base_template={db_category.is_base_template})")
#     return response

@router.post("/categories", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_category_with_tenant(
    # ✅ Utiliser CategoryCreateData (existe déjà dans ecosystem.py)
    category_data: CategoryCreateData,
    db: Session = Depends(get_db),
    x_tenant_id: Optional[str] = Header(None, description="ID du tenant (depuis le JWT ou header)")
):
    """
    Crée une nouvelle catégorie personnalisée
    
    **Logique tenant:**
    - Si `tenant_id` est fourni dans le body OU dans le header → Catégorie personnalisée
    - Sinon → Template universel
    
    **Exemple:**
    ```json
    {
      "name": "Fournisseurs Cloud EMEA",
      "stakeholder_type": "external",
      "entity_category": "supplier",
      "description": "Fournisseurs cloud pour la région EMEA",
      "client_organization_id": "acme_corp",
      "tenant_id": "uuid-tenant"
    }
    ```
    """
    
    # Déterminer le tenant_id effectif
    effective_tenant_id = category_data.tenant_id
    if not effective_tenant_id and x_tenant_id:
        try:
            effective_tenant_id = UUID(x_tenant_id)
        except:
            pass
    
    # Vérifier l'unicité du nom dans le scope du tenant
    # Les catégories sont stockées dans la table 'categories', pas 'ecosystem_entity'
    query = select(Category).where(Category.name == category_data.name)
    
    if effective_tenant_id:
        # Pour un tenant spécifique, vérifier l'unicité dans ce tenant
        query = query.where(Category.tenant_id == effective_tenant_id)
    else:
        # Pour une catégorie universelle, vérifier l'unicité globale
        query = query.where(Category.tenant_id.is_(None))
    
    existing = db.execute(query).scalar_one_or_none()
    
    if existing:
        scope = f"pour le tenant {effective_tenant_id}" if effective_tenant_id else "dans les templates universels"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Une catégorie avec le nom '{category_data.name}' existe déjà {scope}"
        )
    
    # Préparer les données pour Category
    # Note: CategoryCreateData n'a pas tous les champs de Category
    # Il faut les mapper correctement
    
    # Récupérer l'ecosystem_domain_id selon le stakeholder_type
    domain_name = "Externe" if category_data.stakeholder_type == "external" else "Interne"
    domain = db.execute(
        select(EcosystemEntity)
        .where(EcosystemEntity.name == domain_name)
        .where(EcosystemEntity.is_domain == True)
    ).scalar_one_or_none()
    
    if not domain:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Domaine '{domain_name}' non trouvé"
        )
    
    # Récupérer un pole_id par défaut (le premier pôle universel)
    default_pole = db.execute(
        select(Pole)
        .where(Pole.tenant_id.is_(None))
        .where(Pole.is_active == True)
        .limit(1)
    ).scalar_one_or_none()
    
    if not default_pole:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Aucun pôle universel trouvé"
        )
    
    # Créer la catégorie
    db_category = Category(
        ecosystem_domain_id=domain.id,
        pole_id=default_pole.id,
        tenant_id=effective_tenant_id,
        client_organization_id=category_data.client_organization_id,
        name=category_data.name,
        entity_category=category_data.entity_category,
        description=category_data.description,
        parent_category_id=category_data.parent_entity_id,
        is_base_template=(effective_tenant_id is None),
        status="active",
        is_active=True
    )
    
    db.add(db_category)
    db.commit()
    db.refresh(db_category)
    
    logger.info(f"✓ Catégorie créée: {db_category.name} (tenant_id={db_category.tenant_id})")
    
    # Construire la réponse
    return {
        "id": str(db_category.id),
        "name": db_category.name,
        "entity_category": db_category.entity_category,
        "description": db_category.description,
        "tenant_id": str(db_category.tenant_id) if db_category.tenant_id else None,
        "is_base_template": db_category.is_base_template,
        "status": db_category.status,
        "created_at": db_category.created_at.isoformat() if db_category.created_at else None
    }

# ============================================================================
# ROUTE 3 : LISTER LES PÔLES AVEC FILTRAGE PAR TENANT
# ============================================================================

@router.get("/poles", response_model=PoleListResponse)
async def list_poles_with_tenant(
    tenant_id: Optional[UUID] = Query(None, description="Filtrer par tenant (null pour universels)"),
    include_universal: bool = Query(True, description="Inclure les templates universels"),
    is_active: Optional[bool] = Query(None),
    search: Optional[str] = Query(None, description="Recherche par nom ou short_code"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    x_tenant_id: Optional[str] = Header(None)
):
    """
    Liste les pôles avec filtrage par tenant
    
    **Logique de filtrage:**
    - Si `tenant_id` fourni → Retourne les pôles de ce tenant + universels (si include_universal=true)
    - Si `tenant_id` non fourni → Retourne uniquement les templates universels
    - Si header `x-tenant-id` présent → Utilise ce tenant par défaut
    
    **Exemples:**
    ```
    GET /poles?tenant_id=uuid-tenant&include_universal=true
    → Retourne pôles du tenant + pôles universels
    
    GET /poles?include_universal=false
    → Retourne uniquement les templates universels
    
    GET /poles (avec header x-tenant-id)
    → Retourne pôles du tenant + universels
    ```
    """
    
    # Déterminer le tenant effectif
    effective_tenant_id = tenant_id
    if not effective_tenant_id and x_tenant_id:
        try:
            effective_tenant_id = UUID(x_tenant_id)
        except:
            pass
    
    # Construire la requête de base
    base = select(Pole)
    
    # Filtrer par tenant
    if effective_tenant_id:
        if include_universal:
            # Pôles du tenant OU pôles universels
            base = base.where(
                or_(
                    Pole.tenant_id == effective_tenant_id,
                    Pole.tenant_id.is_(None)
                )
            )
        else:
            # Uniquement les pôles du tenant
            base = base.where(Pole.tenant_id == effective_tenant_id)
    else:
        # Uniquement les templates universels
        base = base.where(Pole.tenant_id.is_(None))
    
    # Autres filtres
    if is_active is not None:
        base = base.where(Pole.is_active == is_active)
    
    if search:
        s = f"%{search.lower()}%"
        base = base.where(or_(Pole.name.ilike(s), Pole.short_code.ilike(s)))
    
    # Total
    total = db.execute(base.with_only_columns(func.count()).order_by(None)).scalar() or 0
    
    # Pagination
    rows = db.execute(
        base.order_by(Pole.name.asc()).offset(skip).limit(limit)
    ).scalars().all()

    return {
        "items": [PoleResponse.model_validate(p) for p in rows],
        "total": total,
        "skip": skip,
        "limit": limit
    }


# ============================================================================
# ROUTE : RÉCUPÉRER LES MEMBRES D'UNE ENTITÉ
# ============================================================================

@router.get("/entities/{entity_id}/members")
async def get_entity_members(
    entity_id: UUID,
    campaign_id: Optional[UUID] = Query(None, description="ID de campagne pour déterminer le type (interne/externe)"),
    action_item_id: Optional[UUID] = Query(None, description="ID de l'action pour filtrer par domaines des questions sources"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("ECOSYSTEM_READ"))
):
    """
    Récupère les membres assignables à une action pour une entité donnée.

    **Logique:**
    - **Campagne externe**: Récupère les membres depuis `entity_member` (organismes externes)
    - **Campagne interne**: Récupère les utilisateurs depuis `users` table (employés internes)
    - **Filtrage par domaine**: Si `action_item_id` fourni, filtre selon audite_domain_scope

    Le type de campagne est déterminé via le `campaign_id` fourni.
    """

    members = []
    domain_ids = []

    # Si action_item_id fourni, récupérer les domaines des questions sources
    if action_item_id and campaign_id:
        logger.info(f"🔍 Filtrage par domaine activé - action_item_id: {action_item_id}")
        domains_query = text("""
            SELECT DISTINCT r.domain_id
            FROM action_plan_item api
            JOIN question q ON q.id = ANY(api.source_question_ids)
            JOIN requirement r ON q.requirement_id = r.id
            WHERE api.id = CAST(:action_item_id AS uuid)
        """)
        domains_result = db.execute(domains_query, {"action_item_id": str(action_item_id)})
        domain_ids = [str(row[0]) for row in domains_result]
        logger.info(f"📋 Domaines trouvés pour l'action: {domain_ids}")

    # Récupérer les membres de l'entité depuis entity_member
    if domain_ids:
        logger.info(f"✅ Application du filtrage par domaines: {domain_ids}")
        # Avec filtrage par domaine
        entity_members_query = text("""
            SELECT DISTINCT
                em.id,
                em.first_name,
                em.last_name,
                em.email,
                em.roles
            FROM entity_member em
            LEFT JOIN audite_domain_scope ads
                ON ads.entity_member_id = em.id
                AND ads.campaign_id = CAST(:campaign_id AS uuid)
            WHERE em.entity_id = CAST(:entity_id AS uuid)
              AND em.is_active = true
              AND em.can_be_assigned_audits = true
              AND (
                  em.roles::jsonb ? 'audite_contrib'  -- Contributeur transverse
                  OR (
                      em.roles::jsonb ? 'audite_resp'
                      AND CAST(ads.domain_ids AS uuid[]) && CAST(:domain_ids AS uuid[])  -- Au moins un domaine en commun
                  )
              )
            ORDER BY em.last_name, em.first_name
        """)
        entity_members_result = db.execute(entity_members_query, {
            "entity_id": str(entity_id),
            "campaign_id": str(campaign_id),
            "domain_ids": domain_ids
        })
    else:
        # Sans filtrage par domaine
        entity_members_query = text("""
            SELECT
                em.id,
                em.first_name,
                em.last_name,
                em.email,
                em.roles
            FROM entity_member em
            WHERE em.entity_id = CAST(:entity_id AS uuid)
              AND em.is_active = true
              AND em.can_be_assigned_audits = true
            ORDER BY em.last_name, em.first_name
        """)
        entity_members_result = db.execute(entity_members_query, {"entity_id": str(entity_id)})
        logger.info(f"❌ Aucun filtrage par domaine - retourne tous les membres")

    for row in entity_members_result:
        # Récupérer les rôles depuis JSONB
        roles_jsonb = row[4]
        roles_list = []
        if roles_jsonb:
            if isinstance(roles_jsonb, list):
                roles_list = roles_jsonb
            elif isinstance(roles_jsonb, dict):
                roles_list = list(roles_jsonb.keys())

        members.append({
            "id": str(row[0]),
            "first_name": row[1] or "",
            "last_name": row[2] or "",
            "email": row[3] or "",
            "roles": roles_list
        })

    return {
        "members": members,
        "total": len(members),
        "is_internal_campaign": False
    }


# ============================================================================
# ENDPOINTS : Membres d'une entité par rôle (pour création d'action)
# ============================================================================

@router.get("/entities/{entity_id}/members")
async def get_entity_members_by_role(
    entity_id: UUID,
    role: Optional[str] = Query(None, description="Filtrer par rôle (audite_resp, audite_contrib, etc.)"),
    current_user: User = Depends(require_permission("ECOSYSTEM_READ")),
    db: Session = Depends(get_db)
):
    """
    Récupère les membres d'une entité, avec filtrage optionnel par rôle.
    Utilisé pour le modal de création d'action dans le plan d'action.

    Args:
        entity_id: ID de l'entité
        role: Rôle à filtrer (ex: audite_resp)

    Returns:
        Liste des membres avec id, first_name, last_name, email
    """
    try:
        logger.info(f"📋 Récupération des membres pour entité {entity_id}, rôle={role}")

        # Vérifier que l'entité existe et appartient au tenant
        entity_check_query = text("""
            SELECT id FROM ecosystem_entity
            WHERE id = CAST(:entity_id AS uuid)
              AND tenant_id = CAST(:tenant_id AS uuid)
        """)
        entity_result = db.execute(entity_check_query, {
            "entity_id": str(entity_id),
            "tenant_id": str(current_user.tenant_id)
        }).first()

        if not entity_result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Entité non trouvée"
            )

        # Récupérer les membres avec filtrage par rôle si spécifié
        if role:
            # Filtrer les membres qui ont le rôle spécifié dans leur JSONB roles
            members_query = text("""
                SELECT
                    em.id,
                    em.first_name,
                    em.last_name,
                    em.email
                FROM entity_member em
                WHERE em.entity_id = CAST(:entity_id AS uuid)
                  AND em.is_active = true
                  AND em.roles::jsonb ? :role
                ORDER BY em.last_name, em.first_name
            """)
            members_result = db.execute(members_query, {
                "entity_id": str(entity_id),
                "role": role
            }).mappings().all()
        else:
            # Récupérer tous les membres actifs
            members_query = text("""
                SELECT
                    em.id,
                    em.first_name,
                    em.last_name,
                    em.email
                FROM entity_member em
                WHERE em.entity_id = CAST(:entity_id AS uuid)
                  AND em.is_active = true
                ORDER BY em.last_name, em.first_name
            """)
            members_result = db.execute(members_query, {
                "entity_id": str(entity_id)
            }).mappings().all()

        members = [{
            "id": str(m.id),
            "first_name": m.first_name or "",
            "last_name": m.last_name or "",
            "email": m.email or ""
        } for m in members_result]

        logger.info(f"✅ {len(members)} membres trouvés pour entité {entity_id}")

        return {"members": members}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur récupération membres: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération des membres: {str(e)}"
        )


# ============================================================================
# ENDPOINTS : VUE DÉTAILLÉE ORGANISME (KPI, Campagnes, Actions, Conformité)
# ============================================================================

@router.get("/entities/{entity_id}/kpis")
async def get_entity_kpis(
    entity_id: UUID,
    current_user: User = Depends(require_permission("ECOSYSTEM_READ")),
    db: Session = Depends(get_db)
):
    """
    Récupère les KPIs agrégés d'un organisme :
    - Nombre de membres
    - Nombre de campagnes (en cours, terminées)
    - Nombre d'actions (par statut)
    - Niveau de conformité global
    - Prochaine échéance
    - Dernier rapport généré
    """
    tenant_id = str(current_user.tenant_id) if current_user.tenant_id else None

    if not tenant_id:
        raise HTTPException(status_code=400, detail="Tenant ID requis")

    try:
        # Vérifier que l'entité existe et appartient au tenant
        entity_check = db.execute(
            text("SELECT id, name FROM ecosystem_entity WHERE id = CAST(:entity_id AS uuid) AND tenant_id = CAST(:tenant_id AS uuid)"),
            {"entity_id": str(entity_id), "tenant_id": tenant_id}
        ).fetchone()

        if not entity_check:
            raise HTTPException(status_code=404, detail="Organisme non trouvé")

        # Requête KPIs agrégés
        # NOTE: campaign.scope_id → campaign_scope.id (relation correcte)
        # Tables utilisées: question_answer, published_action, generated_report
        kpi_query = text("""
            WITH entity_members AS (
                SELECT COUNT(*) as count
                FROM entity_member em
                WHERE em.entity_id = CAST(:entity_id AS uuid)
                  AND em.is_active = true
            ),
            entity_campaigns AS (
                SELECT
                    COUNT(*) as total,
                    COUNT(CASE WHEN c.status IN ('ongoing', 'late') THEN 1 END) as in_progress,
                    COUNT(CASE WHEN c.status IN ('completed', 'frozen') THEN 1 END) as completed
                FROM campaign c
                JOIN campaign_scope cs ON c.scope_id = cs.id
                WHERE CAST(:entity_id AS uuid) = ANY(cs.entity_ids)
                  AND c.tenant_id = CAST(:tenant_id AS uuid)
            ),
            entity_actions AS (
                SELECT
                    COUNT(*) as total,
                    COUNT(CASE WHEN pa.status = 'pending' THEN 1 END) as todo,
                    COUNT(CASE WHEN pa.status = 'in_progress' THEN 1 END) as in_progress,
                    COUNT(CASE WHEN pa.status = 'completed' THEN 1 END) as done,
                    COUNT(CASE WHEN pa.status NOT IN ('completed', 'cancelled') AND pa.due_date < NOW() THEN 1 END) as overdue,
                    MIN(CASE WHEN pa.status NOT IN ('completed', 'cancelled') AND pa.due_date >= NOW() THEN pa.due_date END) as next_due_date
                FROM published_action pa
                JOIN campaign c ON pa.campaign_id = c.id
                JOIN campaign_scope cs ON c.scope_id = cs.id
                WHERE CAST(:entity_id AS uuid) = ANY(cs.entity_ids)
                  AND c.tenant_id = CAST(:tenant_id AS uuid)
            ),
            entity_conformity AS (
                SELECT
                    COALESCE(AVG(
                        CASE
                            WHEN qa.compliance_status = 'compliant' THEN 100
                            WHEN qa.compliance_status = 'partial' THEN 50
                            WHEN qa.compliance_status = 'non_compliant' THEN 0
                            ELSE NULL
                        END
                    ), 0) as compliance_level
                FROM question_answer qa
                JOIN campaign c ON qa.campaign_id = c.id
                JOIN campaign_scope cs ON c.scope_id = cs.id
                WHERE CAST(:entity_id AS uuid) = ANY(cs.entity_ids)
                  AND c.tenant_id = CAST(:tenant_id AS uuid)
                  AND qa.compliance_status IS NOT NULL
            ),
            entity_reports AS (
                SELECT
                    gr.created_at as last_report_at,
                    gr.id as last_report_id
                FROM generated_report gr
                JOIN campaign c ON gr.campaign_id = c.id
                JOIN campaign_scope cs ON c.scope_id = cs.id
                WHERE CAST(:entity_id AS uuid) = ANY(cs.entity_ids)
                  AND c.tenant_id = CAST(:tenant_id AS uuid)
                ORDER BY gr.created_at DESC
                LIMIT 1
            )
            SELECT
                COALESCE((SELECT count FROM entity_members), 0) as members_count,
                COALESCE((SELECT total FROM entity_campaigns), 0) as campaigns_total,
                COALESCE((SELECT in_progress FROM entity_campaigns), 0) as campaigns_in_progress,
                COALESCE((SELECT completed FROM entity_campaigns), 0) as campaigns_completed,
                COALESCE((SELECT total FROM entity_actions), 0) as actions_total,
                COALESCE((SELECT todo FROM entity_actions), 0) as actions_todo,
                COALESCE((SELECT in_progress FROM entity_actions), 0) as actions_in_progress,
                COALESCE((SELECT done FROM entity_actions), 0) as actions_done,
                COALESCE((SELECT overdue FROM entity_actions), 0) as actions_overdue,
                (SELECT next_due_date FROM entity_actions) as next_due_date,
                COALESCE((SELECT compliance_level FROM entity_conformity), 0) as compliance_level,
                (SELECT last_report_at FROM entity_reports) as last_report_at,
                (SELECT last_report_id FROM entity_reports) as last_report_id
        """)

        result = db.execute(kpi_query, {
            "entity_id": str(entity_id),
            "tenant_id": tenant_id
        }).mappings().fetchone()

        kpis = {
            "members_count": result["members_count"] or 0,
            "campaigns": {
                "total": result["campaigns_total"] or 0,
                "in_progress": result["campaigns_in_progress"] or 0,
                "completed": result["campaigns_completed"] or 0
            },
            "actions": {
                "total": result["actions_total"] or 0,
                "todo": result["actions_todo"] or 0,
                "in_progress": result["actions_in_progress"] or 0,
                "done": result["actions_done"] or 0,
                "overdue": result["actions_overdue"] or 0
            },
            "compliance_level": round(float(result["compliance_level"] or 0), 1),
            "next_due_date": result["next_due_date"].isoformat() if result["next_due_date"] else None,
            "last_report": {
                "id": str(result["last_report_id"]) if result["last_report_id"] else None,
                "generated_at": result["last_report_at"].isoformat() if result["last_report_at"] else None
            }
        }

        logger.info(f"📊 KPIs entité {entity_id}: {kpis['compliance_level']}% conformité, {kpis['campaigns']['total']} campagnes")
        return kpis

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur KPIs entité: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erreur: {str(e)}")


@router.get("/entities/{entity_id}/campaigns")
async def get_entity_campaigns(
    entity_id: UUID,
    status_filter: Optional[str] = Query(None, description="Filtrer par statut"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_permission("ECOSYSTEM_READ")),
    db: Session = Depends(get_db)
):
    """
    Récupère les campagnes associées à un organisme.
    """
    tenant_id = str(current_user.tenant_id) if current_user.tenant_id else None

    if not tenant_id:
        raise HTTPException(status_code=400, detail="Tenant ID requis")

    try:
        # Requête campagnes
        # NOTE: campaign.scope_id → campaign_scope.id (relation correcte)
        # NOTE: campaign utilise launch_date/due_date pas start_date/end_date
        # NOTE: questionnaire.framework_id → framework.id (pas referential)
        # Tables: question_answer, published_action
        query = text("""
            SELECT
                c.id,
                c.title,
                c.status,
                c.launch_date,
                c.due_date,
                c.created_at,
                f.id as framework_id,
                f.name as referential_name,
                f.code as referential_code,
                (
                    SELECT COALESCE(AVG(
                        CASE
                            WHEN qa.compliance_status = 'compliant' THEN 100
                            WHEN qa.compliance_status = 'partial' THEN 50
                            WHEN qa.compliance_status = 'non_compliant' THEN 0
                            ELSE NULL
                        END
                    ), 0)
                    FROM question_answer qa
                    WHERE qa.campaign_id = c.id
                      AND qa.compliance_status IS NOT NULL
                ) as score,
                (
                    SELECT COUNT(*)
                    FROM published_action pa
                    WHERE pa.campaign_id = c.id
                      AND pa.status NOT IN ('completed', 'cancelled')
                ) as pending_actions
            FROM campaign c
            JOIN campaign_scope cs ON c.scope_id = cs.id
            LEFT JOIN questionnaire q ON c.questionnaire_id = q.id
            LEFT JOIN framework f ON q.framework_id = f.id
            WHERE CAST(:entity_id AS uuid) = ANY(cs.entity_ids)
              AND c.tenant_id = CAST(:tenant_id AS uuid)
              AND (:status_filter IS NULL OR c.status = :status_filter)
            ORDER BY c.created_at DESC
            LIMIT :limit OFFSET :offset
        """)

        campaigns_result = db.execute(query, {
            "entity_id": str(entity_id),
            "tenant_id": tenant_id,
            "status_filter": status_filter,
            "limit": limit,
            "offset": offset
        }).mappings().all()

        # Count total
        count_query = text("""
            SELECT COUNT(*)
            FROM campaign c
            JOIN campaign_scope cs ON c.scope_id = cs.id
            WHERE CAST(:entity_id AS uuid) = ANY(cs.entity_ids)
              AND c.tenant_id = CAST(:tenant_id AS uuid)
              AND (:status_filter IS NULL OR c.status = :status_filter)
        """)
        total = db.execute(count_query, {
            "entity_id": str(entity_id),
            "tenant_id": tenant_id,
            "status_filter": status_filter
        }).scalar()

        campaigns = [{
            "id": str(c["id"]),
            "title": c["title"],
            "status": c["status"],
            "start_date": c["launch_date"].isoformat() if c["launch_date"] else None,
            "end_date": c["due_date"].isoformat() if c["due_date"] else None,
            "created_at": c["created_at"].isoformat() if c["created_at"] else None,
            "referential": {
                "name": c["referential_name"],
                "code": c["referential_code"]
            } if c["referential_name"] else None,
            "score": round(float(c["score"] or 0), 1),
            "pending_actions": c["pending_actions"] or 0
        } for c in campaigns_result]

        # Enrichir avec les auditeurs et audités pour chaque campagne
        for campaign in campaigns:
            campaign_id_uuid = campaign["id"]

            # Récupérer les auditeurs (campaign_user)
            auditors_query = text("""
                SELECT
                    u.id,
                    u.first_name,
                    u.last_name,
                    u.email,
                    cu.role
                FROM campaign_user cu
                JOIN users u ON cu.user_id = u.id
                WHERE cu.campaign_id = CAST(:campaign_id AS uuid)
                  AND cu.is_active = true
                ORDER BY cu.role, u.last_name
            """)
            auditors_result = db.execute(auditors_query, {"campaign_id": campaign_id_uuid}).mappings().all()
            campaign["auditors"] = [{
                "id": str(a["id"]),
                "name": f"{a['first_name']} {a['last_name']}".strip(),
                "email": a["email"],
                "role": a["role"]
            } for a in auditors_result]

            # Récupérer les personnes auditées (entity_member liés aux entités de la campagne)
            auditees_query = text("""
                SELECT DISTINCT
                    em.id,
                    em.first_name,
                    em.last_name,
                    em.email,
                    em.roles,
                    ee.name as entity_name
                FROM entity_member em
                JOIN ecosystem_entity ee ON em.entity_id = ee.id
                JOIN campaign_scope cs ON em.entity_id = ANY(cs.entity_ids)
                JOIN campaign c ON c.scope_id = cs.id
                WHERE c.id = CAST(:campaign_id AS uuid)
                  AND em.is_active = true
                ORDER BY ee.name, em.last_name
            """)
            auditees_result = db.execute(auditees_query, {"campaign_id": campaign_id_uuid}).mappings().all()
            campaign["auditees"] = [{
                "id": str(a["id"]),
                "name": f"{a['first_name']} {a['last_name']}".strip(),
                "email": a["email"],
                "roles": a["roles"] if a["roles"] else [],
                "entity_name": a["entity_name"]
            } for a in auditees_result]

        return {
            "items": campaigns,
            "total": total,
            "limit": limit,
            "offset": offset
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur campagnes entité: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erreur: {str(e)}")


@router.get("/entities/{entity_id}/actions")
async def get_entity_actions(
    entity_id: UUID,
    status_filter: Optional[str] = Query(None, description="Filtrer par statut: todo, in_progress, done"),
    priority_filter: Optional[str] = Query(None, description="Filtrer par priorité: P1, P2, P3"),
    campaign_id: Optional[UUID] = Query(None, description="Filtrer par campagne"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_permission("ECOSYSTEM_READ")),
    db: Session = Depends(get_db)
):
    """
    Récupère toutes les actions correctives associées à un organisme.
    """
    tenant_id = str(current_user.tenant_id) if current_user.tenant_id else None

    if not tenant_id:
        raise HTTPException(status_code=400, detail="Tenant ID requis")

    try:
        # NOTE: campaign.scope_id → campaign_scope.id (relation correcte)
        # Table: published_action (pas action)
        query = text("""
            SELECT
                pa.id,
                pa.code_action,
                pa.title,
                pa.description,
                pa.objective,
                pa.deliverables,
                pa.status,
                pa.priority,
                pa.due_date,
                pa.created_at,
                pa.severity,
                pa.entity_name,
                pa.suggested_role,
                pa.recommended_due_days,
                pa.assigned_user_id,
                pa.source_question_ids,
                pa.control_point_ids,
                pa.ai_justifications,
                c.id as campaign_id,
                c.title as campaign_title,
                u.first_name || ' ' || u.last_name as responsible_name,
                CASE WHEN pa.status NOT IN ('completed', 'cancelled') AND pa.due_date < NOW() THEN true ELSE false END as is_overdue
            FROM published_action pa
            JOIN campaign c ON pa.campaign_id = c.id
            JOIN campaign_scope cs ON c.scope_id = cs.id
            LEFT JOIN users u ON pa.assigned_user_id = u.id
            WHERE CAST(:entity_id AS uuid) = ANY(cs.entity_ids)
              AND c.tenant_id = CAST(:tenant_id AS uuid)
              AND (:status_filter IS NULL OR pa.status = :status_filter)
              AND (:priority_filter IS NULL OR pa.priority = :priority_filter)
              AND (:campaign_id IS NULL OR pa.campaign_id = CAST(:campaign_id AS uuid))
            ORDER BY
                CASE pa.priority
                    WHEN 'P1' THEN 1
                    WHEN 'P2' THEN 2
                    WHEN 'P3' THEN 3
                    ELSE 4
                END,
                pa.due_date ASC NULLS LAST
            LIMIT :limit OFFSET :offset
        """)

        actions_result = db.execute(query, {
            "entity_id": str(entity_id),
            "tenant_id": tenant_id,
            "status_filter": status_filter,
            "priority_filter": priority_filter,
            "campaign_id": str(campaign_id) if campaign_id else None,
            "limit": limit,
            "offset": offset
        }).mappings().all()

        # Count total
        count_query = text("""
            SELECT COUNT(*)
            FROM published_action pa
            JOIN campaign c ON pa.campaign_id = c.id
            JOIN campaign_scope cs ON c.scope_id = cs.id
            WHERE CAST(:entity_id AS uuid) = ANY(cs.entity_ids)
              AND c.tenant_id = CAST(:tenant_id AS uuid)
              AND (:status_filter IS NULL OR pa.status = :status_filter)
              AND (:priority_filter IS NULL OR pa.priority = :priority_filter)
              AND (:campaign_id IS NULL OR pa.campaign_id = CAST(:campaign_id AS uuid))
        """)
        total = db.execute(count_query, {
            "entity_id": str(entity_id),
            "tenant_id": tenant_id,
            "status_filter": status_filter,
            "priority_filter": priority_filter,
            "campaign_id": str(campaign_id) if campaign_id else None
        }).scalar()

        actions = [{
            "id": str(a["id"]),
            "code_action": a["code_action"],
            "title": a["title"],
            "description": a["description"] or "",
            "objective": a["objective"],
            "deliverables": a["deliverables"],
            "status": a["status"],
            "priority": a["priority"],
            "severity": a["severity"] or "minor",
            "suggested_role": a["suggested_role"] or "",
            "recommended_due_days": a["recommended_due_days"] or 30,
            "assigned_user_id": str(a["assigned_user_id"]) if a["assigned_user_id"] else None,
            "due_date": a["due_date"].isoformat() if a["due_date"] else None,
            "created_at": a["created_at"].isoformat() if a["created_at"] else None,
            "source_question_ids": [str(sq_id) for sq_id in (a["source_question_ids"] or [])],
            "control_point_ids": [str(cp_id) for cp_id in (a["control_point_ids"] or [])],
            "ai_justifications": a["ai_justifications"],
            "campaign": {
                "id": str(a["campaign_id"]),
                "title": a["campaign_title"]
            },
            "domain_name": a["entity_name"],  # published_action utilise entity_name
            "responsible_name": a["responsible_name"],
            "assigned_user_name": a["responsible_name"],
            "is_overdue": a["is_overdue"]
        } for a in actions_result]

        return {
            "items": actions,
            "total": total,
            "limit": limit,
            "offset": offset
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur actions entité: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erreur: {str(e)}")


@router.get("/entities/{entity_id}/conformity")
async def get_entity_conformity(
    entity_id: UUID,
    campaign_id: Optional[UUID] = Query(None, description="Filtrer par campagne"),
    current_user: User = Depends(require_permission("ECOSYSTEM_READ")),
    db: Session = Depends(get_db)
):
    """
    Récupère la conformité détaillée par domaine pour un organisme.
    """
    tenant_id = str(current_user.tenant_id) if current_user.tenant_id else None

    if not tenant_id:
        raise HTTPException(status_code=400, detail="Tenant ID requis")

    try:
        # NOTE: campaign.scope_id → campaign_scope.id (relation correcte)
        # Table: question_answer (pas question_response)
        # Statuts de conformité réels: 'compliant', 'non_compliant_major', 'non_compliant_minor', 'partial'
        # Les questions n'ont pas toujours un chapter rempli, donc on calcule le score global directement

        # 1. Score global sans regroupement par domaine
        global_query = text("""
            SELECT
                COUNT(DISTINCT qa.id) as total_answers,
                COUNT(DISTINCT CASE WHEN qa.compliance_status = 'compliant' THEN qa.id END) as compliant_count,
                COUNT(DISTINCT CASE WHEN qa.compliance_status = 'partial' THEN qa.id END) as partial_count,
                COUNT(DISTINCT CASE WHEN qa.compliance_status IN ('non_compliant', 'non_compliant_major', 'non_compliant_minor') THEN qa.id END) as non_compliant_count
            FROM question_answer qa
            JOIN campaign c ON qa.campaign_id = c.id
            JOIN campaign_scope cs ON c.scope_id = cs.id
            WHERE CAST(:entity_id AS uuid) = ANY(cs.entity_ids)
              AND c.tenant_id = CAST(:tenant_id AS uuid)
              AND (:campaign_id IS NULL OR c.id = CAST(:campaign_id AS uuid))
              AND qa.compliance_status IS NOT NULL
              AND qa.compliance_status != ''
        """)

        global_result = db.execute(global_query, {
            "entity_id": str(entity_id),
            "tenant_id": tenant_id,
            "campaign_id": str(campaign_id) if campaign_id else None
        }).mappings().first()

        total_answers = global_result["total_answers"] if global_result else 0
        compliant = global_result["compliant_count"] if global_result else 0
        partial = global_result["partial_count"] if global_result else 0
        non_compliant = global_result["non_compliant_count"] if global_result else 0

        # Calcul du score: compliant=100%, partial=50%, non_compliant=0%
        if total_answers > 0:
            global_score = round((compliant * 100 + partial * 50) / total_answers, 1)
        else:
            global_score = 0

        # 2. Regroupement par campagne (comme proxy pour les "domaines")
        campaign_query = text("""
            SELECT
                c.id as campaign_id,
                c.title as campaign_name,
                COUNT(DISTINCT qa.id) as total_questions,
                COUNT(DISTINCT CASE WHEN qa.compliance_status = 'compliant' THEN qa.id END) as compliant_count,
                COUNT(DISTINCT CASE WHEN qa.compliance_status = 'partial' THEN qa.id END) as partial_count,
                COUNT(DISTINCT CASE WHEN qa.compliance_status IN ('non_compliant', 'non_compliant_major', 'non_compliant_minor') THEN qa.id END) as non_compliant_count
            FROM question_answer qa
            JOIN campaign c ON qa.campaign_id = c.id
            JOIN campaign_scope cs ON c.scope_id = cs.id
            WHERE CAST(:entity_id AS uuid) = ANY(cs.entity_ids)
              AND c.tenant_id = CAST(:tenant_id AS uuid)
              AND (:campaign_id IS NULL OR c.id = CAST(:campaign_id AS uuid))
              AND qa.compliance_status IS NOT NULL
              AND qa.compliance_status != ''
            GROUP BY c.id, c.title
            ORDER BY c.title
        """)

        campaign_result = db.execute(campaign_query, {
            "entity_id": str(entity_id),
            "tenant_id": tenant_id,
            "campaign_id": str(campaign_id) if campaign_id else None
        }).mappings().all()

        domains = []
        for r in campaign_result:
            total = r["total_questions"]
            if total > 0:
                score = round((r["compliant_count"] * 100 + r["partial_count"] * 50) / total, 1)
            else:
                score = 0
            domains.append({
                "id": str(r["campaign_id"]),
                "name": r["campaign_name"],
                "code": "",
                "total_questions": total,
                "compliant": r["compliant_count"],
                "partial": r["partial_count"],
                "non_compliant": r["non_compliant_count"],
                "score": score
            })

        return {
            "global_score": global_score,
            "total_questions": total_answers,
            "domains": domains
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur conformité entité: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erreur: {str(e)}")


@router.get("/entities/{entity_id}/history")
async def get_entity_history(
    entity_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_permission("ECOSYSTEM_READ")),
    db: Session = Depends(get_db)
):
    """
    Récupère l'historique des événements pour un organisme.
    """
    tenant_id = str(current_user.tenant_id) if current_user.tenant_id else None

    if not tenant_id:
        raise HTTPException(status_code=400, detail="Tenant ID requis")

    try:
        # Union des différents types d'événements
        # NOTE: campaign.scope_id → campaign_scope.id (relation correcte)
        # Tables: published_action, generated_report
        query = text("""
            WITH events AS (
                -- Campagnes créées
                SELECT
                    c.id as event_id,
                    'campaign_created' as event_type,
                    c.title as event_title,
                    c.created_at as event_date,
                    u.first_name || ' ' || u.last_name as actor
                FROM campaign c
                JOIN campaign_scope cs ON c.scope_id = cs.id
                LEFT JOIN users u ON c.created_by = u.id
                WHERE CAST(:entity_id AS uuid) = ANY(cs.entity_ids)
                  AND c.tenant_id = CAST(:tenant_id AS uuid)

                UNION ALL

                -- Actions publiées
                SELECT
                    pa.id as event_id,
                    'action_created' as event_type,
                    pa.title as event_title,
                    pa.published_at as event_date,
                    u.first_name || ' ' || u.last_name as actor
                FROM published_action pa
                JOIN campaign c ON pa.campaign_id = c.id
                JOIN campaign_scope cs ON c.scope_id = cs.id
                LEFT JOIN users u ON pa.published_by = u.id
                WHERE CAST(:entity_id AS uuid) = ANY(cs.entity_ids)
                  AND c.tenant_id = CAST(:tenant_id AS uuid)

                UNION ALL

                -- Rapports générés
                SELECT
                    gr.id as event_id,
                    'report_generated' as event_type,
                    c.title || ' - Rapport' as event_title,
                    gr.created_at as event_date,
                    'Système' as actor
                FROM generated_report gr
                JOIN campaign c ON gr.campaign_id = c.id
                JOIN campaign_scope cs ON c.scope_id = cs.id
                WHERE CAST(:entity_id AS uuid) = ANY(cs.entity_ids)
                  AND c.tenant_id = CAST(:tenant_id AS uuid)
            )
            SELECT * FROM events
            ORDER BY event_date DESC
            LIMIT :limit OFFSET :offset
        """)

        result = db.execute(query, {
            "entity_id": str(entity_id),
            "tenant_id": tenant_id,
            "limit": limit,
            "offset": offset
        }).mappings().all()

        events = [{
            "id": str(e["event_id"]),
            "type": e["event_type"],
            "title": e["event_title"],
            "date": e["event_date"].isoformat() if e["event_date"] else None,
            "actor": e["actor"]
        } for e in result]

        return {
            "items": events,
            "limit": limit,
            "offset": offset
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur historique entité: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erreur: {str(e)}")