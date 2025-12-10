"""
backend/src/api/v1/hierarchy.py
Routes pour la gestion de la hiérarchie (domaines, pôles, catégories)
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text
import uuid
import logging

from src.database import get_db
from src.models.category import Category
from src.schemas.category import CategoryCreate, CategoryResponse
from src.models.audit import User
from src.dependencies_keycloak import get_current_user_keycloak, require_permission
from src.models.organization import Organization
from sqlalchemy import select

# ✅ REDIS CACHE
from src.utils.redis_manager import cache_result

logger = logging.getLogger(__name__)

# Router sans prefix - le prefix est déjà dans main.py (/api/v1/hierarchy)
router = APIRouter(tags=["Hiérarchie"])


# ============================================================================
# ENDPOINTS EXISTANTS (GET)
# ============================================================================

@router.get("/domains", response_model=List[dict])
@cache_result(ttl=3600, key_prefix="hierarchy_domains")  # ✅ Cache 1h
async def get_domains(db: Session = Depends(get_db)):
    """
    Récupère tous les domaines (Interne et Externe)
    """
    query = """
        SELECT id, name, stakeholder_type, description, is_active
        FROM ecosystem_domains
        WHERE is_active = true
        ORDER BY name
    """
    
    result = db.execute(sql_text(query)).fetchall()
    
    return [
        {
            "id": str(row[0]),
            "name": row[1],
            "stakeholder_type": row[2],
            "description": row[3],
            "is_active": row[4]
        }
        for row in result
    ]


@router.get("/categories", response_model=List[dict])
async def get_categories(
    stakeholder_type: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """
    Récupère les catégories (pour organismes externes)
    """
    query = """
        SELECT 
            c.id, 
            c.name, 
            c.entity_category, 
            c.description, 
            c.short_code,
            d.name as domain_name
        FROM categories c
        LEFT JOIN ecosystem_domains d ON c.ecosystem_domain_id = d.id
        WHERE c.is_active = true
    """
    
    params = {}
    if stakeholder_type:
        domain_name = "Externe" if stakeholder_type == "external" else "Interne"
        query += " AND d.name = :domain_name"
        params["domain_name"] = domain_name
    
    query += " ORDER BY c.name"
    
    result = db.execute(sql_text(query), params).fetchall()
    
    return [
        {
            "id": str(row[0]),
            "name": row[1],
            "entity_category": row[2],
            "description": row[3],
            "short_code": row[4],
            "domain_name": row[5]
        }
        for row in result
    ]


@router.get("/poles", response_model=List[dict])
async def get_poles(
    db: Session = Depends(get_db)
):
    """
    Récupère les pôles (pour organismes internes)
    """
    query = """
        SELECT 
            p.id, 
            p.name, 
            p.description, 
            p.short_code,
            d.name as domain_name
        FROM poles p
        LEFT JOIN ecosystem_domains d ON p.ecosystem_domain_id = d.id
        WHERE p.is_active = true
        ORDER BY p.name
    """
    
    result = db.execute(sql_text(query)).fetchall()
    
    return [
        {
            "id": str(row[0]),
            "name": row[1],
            "description": row[2],
            "short_code": row[3],
            "domain_name": row[4]
        }
        for row in result
    ]


@router.get("/tree", response_model=dict)
@cache_result(ttl=3600, key_prefix="hierarchy_tree")  # ✅ Cache 1h
async def get_hierarchy_tree(db: Session = Depends(get_db)):
    """
    Récupère l'arbre hiérarchique complet
    """
    # Récupérer les domaines
    domains_query = "SELECT id, name, stakeholder_type FROM ecosystem_domains WHERE is_active = true"
    domains = db.execute(sql_text(domains_query)).fetchall()
    
    tree = []
    
    for domain in domains:
        domain_id = str(domain[0])
        domain_data = {
            "id": domain_id,
            "name": domain[1],
            "stakeholder_type": domain[2],
            "children": []
        }
        
        if domain[2] == "external":
            # Charger les catégories
            cat_query = """
                SELECT id, name, entity_category 
                FROM categories 
                WHERE ecosystem_domain_id = :domain_id AND is_active = true
            """
            categories = db.execute(sql_text(cat_query), {"domain_id": domain_id}).fetchall()
            
            for cat in categories:
                domain_data["children"].append({
                    "id": str(cat[0]),
                    "name": cat[1],
                    "entity_category": cat[2],
                    "type": "category"
                })
        else:
            # Charger les pôles
            pole_query = """
                SELECT id, name, short_code 
                FROM poles 
                WHERE ecosystem_domain_id = :domain_id AND is_active = true
            """
            poles = db.execute(sql_text(pole_query), {"domain_id": domain_id}).fetchall()
            
            for pole in poles:
                domain_data["children"].append({
                    "id": str(pole[0]),
                    "name": pole[1],
                    "short_code": pole[2],
                    "type": "pole"
                })
        
        tree.append(domain_data)
    
    return {"tree": tree}


# ============================================================================
# NOUVEAU : POST - Créer une catégorie
# ============================================================================

@router.post("/categories", response_model=CategoryResponse, status_code=status.HTTP_201_CREATED)
async def create_category(
    category_data: CategoryCreate,
    db: Session = Depends(get_db)
):
    """
    Créer une nouvelle catégorie ou sous-catégorie
    
    Structure hiérarchique:
    - hierarchy_level: 2 → Catégorie de base (Clients, Fournisseurs, Partenaires)
    - hierarchy_level: 3 → Sous-catégorie niveau 1 (Fournisseurs IT)
    - hierarchy_level: 4 → Sous-catégorie niveau 2 (Fournisseurs IT Cloud)
    """
    try:
        logger.info(f"📝 Création catégorie: {category_data.name}")
        
        # ========================================================================
        # 1. Récupérer le domaine (Interne ou Externe)
        # ========================================================================
        domain_name = "Externe" if category_data.stakeholder_type == "external" else "Interne"
        domain_query = """
            SELECT id FROM ecosystem_domains 
            WHERE name = :domain_name AND is_active = true
        """
        domain_result = db.execute(sql_text(domain_query), {"domain_name": domain_name}).fetchone()
        
        if not domain_result:
            raise HTTPException(
                status_code=404,
                detail=f"Domaine '{domain_name}' introuvable"
            )
        
        ecosystem_domain_id = str(domain_result[0])
        
        # ========================================================================
        # 2. Récupérer le pôle (obligatoire pour Interne, optionnel pour Externe)
        # ========================================================================
        pole_id = None
        
        if category_data.stakeholder_type == "internal":
            # ✅ Pour INTERNE : Pôle obligatoire
            pole_query = """
                SELECT id FROM poles 
                WHERE ecosystem_domain_id = :domain_id 
                AND is_active = true 
                LIMIT 1
            """
            pole_result = db.execute(
                sql_text(pole_query), 
                {"domain_id": ecosystem_domain_id}
            ).fetchone()
            
            if not pole_result:
                raise HTTPException(
                    status_code=404,
                    detail=f"Aucun pôle trouvé pour le domaine 'Interne'"
                )
            
            pole_id = str(pole_result[0])
            logger.info(f"✅ Pôle Interne: {pole_id}")
        
        else:
            # ✅ Pour EXTERNE : Utiliser un pôle par défaut
            # (Requis par le modèle Category mais pas conceptuellement important)
            default_pole_query = """
                SELECT id FROM poles 
                WHERE is_active = true 
                LIMIT 1
            """
            pole_result = db.execute(sql_text(default_pole_query)).fetchone()
            
            if not pole_result:
                # Créer un pôle générique si aucun n'existe
                logger.warning("⚠️ Création d'un pôle générique pour Externe")
                
                generic_pole_id = uuid.uuid4()
                insert_pole = """
                    INSERT INTO poles (
                        id, name, description, short_code, ecosystem_domain_id,
                        hierarchy_level, is_active, is_base_template, status, keywords
                    ) VALUES (
                        :pole_id, 'Pôle Générique (Externe)', 
                        'Pôle technique pour les catégories externes',
                        'GEN', :domain_id, 1, true, true, 'active', '[]'
                    )
                """
                db.execute(
                    sql_text(insert_pole),
                    {"pole_id": str(generic_pole_id), "domain_id": ecosystem_domain_id}
                )
                db.commit()
                pole_id = str(generic_pole_id)
            else:
                pole_id = str(pole_result[0])
            
            logger.info(f"✅ Pôle par défaut (Externe): {pole_id}")
        
        # ========================================================================
        # 3. Déterminer le hierarchy_level
        # ========================================================================
        hierarchy_level = 2  # Par défaut, catégorie de base
        
        if category_data.parent_category_id:
            # Vérifier que la catégorie parente existe
            parent_query = """
                SELECT id, hierarchy_level, name 
                FROM categories 
                WHERE id = :parent_id AND is_active = true
            """
            parent_result = db.execute(
                sql_text(parent_query),
                {"parent_id": category_data.parent_category_id}
            ).fetchone()
            
            if not parent_result:
                raise HTTPException(
                    status_code=404,
                    detail=f"Catégorie parente {category_data.parent_category_id} introuvable"
                )
            
            parent_hierarchy_level = parent_result[1]
            parent_name = parent_result[2]
            hierarchy_level = parent_hierarchy_level + 1
            
            logger.info(f"✅ Parent: {parent_name} (niveau {parent_hierarchy_level})")
            logger.info(f"✅ Nouvelle catégorie: niveau {hierarchy_level}")
        
        # ========================================================================
        # 4. Créer la nouvelle catégorie
        # ========================================================================
        new_category = Category(
            id=uuid.uuid4(),
            name=category_data.name,
            entity_category=category_data.entity_category,
            description=category_data.description,
            parent_category_id=uuid.UUID(category_data.parent_category_id) if category_data.parent_category_id else None,
            ecosystem_domain_id=uuid.UUID(ecosystem_domain_id),
            pole_id=uuid.UUID(pole_id),
            client_organization_id=category_data.client_organization_id,
            tenant_id=uuid.UUID(category_data.tenant_id) if category_data.tenant_id else None,
            hierarchy_level=hierarchy_level,
            is_base_template=False,
            is_active=True,
            status='active',
            keywords='[]'
        )
        
        db.add(new_category)
        db.commit()
        db.refresh(new_category)
        
        logger.info(f"✅ Catégorie créée: {new_category.name} (ID: {new_category.id})")
        
        # ========================================================================
        # 5. Retourner la réponse
        # ========================================================================
        return CategoryResponse(
            id=str(new_category.id),
            name=new_category.name,
            entity_category=new_category.entity_category,
            description=new_category.description,
            parent_category_id=str(new_category.parent_category_id) if new_category.parent_category_id else None,
            hierarchy_level=new_category.hierarchy_level,
            ecosystem_domain_id=str(new_category.ecosystem_domain_id),
            pole_id=str(new_category.pole_id),
            is_base_template=new_category.is_base_template,
            is_active=new_category.is_active,
            created_at=new_category.created_at
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur création catégorie: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la création de la catégorie: {str(e)}"
        )


# ============================================================================
# NOUVEAU : GET - Sous-catégories d'une catégorie
# ============================================================================

@router.get("/categories/{category_id}/children", response_model=List[dict])
async def get_category_children(
    category_id: str,
    client_organization_id: Optional[str] = Query(None, description="ID de l'organisation cliente (pour filtrer par tenant)"),
    current_user: User = Depends(require_permission("ECOSYSTEM_READ")),
    db: Session = Depends(get_db)
):
    """
    Récupère toutes les sous-catégories d'une catégorie donnée
    ✅ SÉCURITÉ: Filtre par tenant pour isolation multi-tenant
    """
    # ✅ Résoudre le tenant_id effectif (même logique que /categories)
    effective_tenant_id = None

    if client_organization_id:
        org = db.execute(
            select(Organization).where(Organization.id == client_organization_id)
        ).scalar_one_or_none()

        if org:
            effective_tenant_id = org.tenant_id
            logger.info(f"🔒 /children - Résolution tenant via organization {client_organization_id}: {effective_tenant_id}")
        else:
            logger.warning(f"Organization {client_organization_id} introuvable")
            effective_tenant_id = current_user.tenant_id
    else:
        effective_tenant_id = current_user.tenant_id

    query = """
        SELECT
            id,
            name,
            entity_category,
            description,
            hierarchy_level
        FROM categories
        WHERE parent_category_id = :parent_id
        AND is_active = true
        AND (tenant_id IS NULL OR tenant_id = :tenant_id)
        ORDER BY name
    """

    params = {
        "parent_id": category_id,
        "tenant_id": str(effective_tenant_id) if effective_tenant_id else None
    }

    result = db.execute(sql_text(query), params).fetchall()

    logger.info(f"🔍 /children - {len(result)} sous-catégories retournées pour parent={category_id}, tenant={effective_tenant_id}")

    return [
        {
            "id": str(row[0]),
            "name": row[1],
            "entity_category": row[2],
            "description": row[3],
            "hierarchy_level": row[4]
        }
        for row in result
    ]