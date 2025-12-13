"""
API Admin pour la gestion des Clients (entités payantes)
"""
from typing import List, Optional
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func, and_, or_, text
from sqlalchemy.orm import Session

from src.database import get_db
from src.models.client import Client
from src.models.tenant import Tenant
from src.schemas.client import (
    ClientCreate,
    ClientUpdate,
    ClientResponse,
    ClientListResponse,
    ClientStats,
    TenantCreateData
)

# IDs des templates système à copier pour chaque nouveau tenant
SYSTEM_TEMPLATE_IDS = {
    'individual': '84a3ffe7-8cb3-4b37-87e5-0dd8c0577156',      # Rapport Individuel
    'consolidated': 'eaf46622-ceea-4175-9703-9c7444a9190f',    # Rapport Consolidé Écosystème
    'scan_individual': '666c7e73-7efc-4161-876c-ff477998e135', # Rapport Scan Individuel
    'scan_ecosystem': '357a10fc-687a-41a6-a33e-28df1ebd9d24',  # Rapport Écosystème Scanner
}

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/clients", tags=["Admin - Clients"])


def create_default_templates_for_tenant(db: Session, tenant_id: UUID, tenant_name: str) -> int:
    """
    Crée les 4 templates de rapport par défaut pour un nouveau tenant.
    Copie la structure des templates système.

    Returns:
        Nombre de templates créés
    """
    templates_config = [
        {
            'source_id': SYSTEM_TEMPLATE_IDS['individual'],
            'name': f'Rapport Individuel : {tenant_name}',
            'description': "Rapport d'audit détaillé pour une entité spécifique (10-20 pages)",
            'code': f'individual_{tenant_name.lower().replace(" ", "_")}',
            'report_scope': 'entity'
        },
        {
            'source_id': SYSTEM_TEMPLATE_IDS['consolidated'],
            'name': f'Rapport Consolidé Écosystème : {tenant_name}',
            'description': "Rapport consolidé multi-entités avec vue écosystème (10-15 pages)",
            'code': f'consolidated_{tenant_name.lower().replace(" ", "_")}',
            'report_scope': 'consolidated'
        },
        {
            'source_id': SYSTEM_TEMPLATE_IDS['scan_individual'],
            'name': f'Scan Individuel : {tenant_name}',
            'description': "Rapport de scan de vulnérabilités pour une cible spécifique",
            'code': f'scan_individual_{tenant_name.lower().replace(" ", "_")}',
            'report_scope': 'scan_individual'
        },
        {
            'source_id': SYSTEM_TEMPLATE_IDS['scan_ecosystem'],
            'name': f'Scan Écosystème : {tenant_name}',
            'description': "Rapport consolidé multi-cibles pour l'écosystème",
            'code': f'scan_ecosystem_{tenant_name.lower().replace(" ", "_")}',
            'report_scope': 'scan_ecosystem'
        },
    ]

    created_count = 0

    for config in templates_config:
        try:
            # Copier le template système vers le nouveau tenant
            query = text("""
                INSERT INTO report_template (
                    id, tenant_id, name, description, code, template_type,
                    is_system, is_default, page_size, orientation, margins,
                    color_scheme, fonts, structure, report_scope, created_at, updated_at
                )
                SELECT
                    gen_random_uuid(),
                    :tenant_id,
                    :name,
                    :description,
                    :code,
                    'custom',
                    false,
                    true,
                    page_size,
                    orientation,
                    margins,
                    color_scheme,
                    fonts,
                    structure,
                    :report_scope,
                    NOW(),
                    NOW()
                FROM report_template
                WHERE id = :source_id
            """)

            db.execute(query, {
                'tenant_id': str(tenant_id),
                'name': config['name'],
                'description': config['description'],
                'code': config['code'],
                'report_scope': config['report_scope'],
                'source_id': config['source_id']
            })

            created_count += 1
            logger.info(f"  ✓ Template créé: {config['name']}")

        except Exception as e:
            logger.error(f"  ✗ Erreur création template {config['name']}: {e}")

    return created_count


# ============================================================================
# ENDPOINTS : CRUD Clients
# ============================================================================

@router.get("/", response_model=ClientListResponse)
async def list_clients(
    is_active: Optional[bool] = Query(None),
    subscription_type: Optional[str] = Query(None),
    size_category: Optional[str] = Query(None),
    search: Optional[str] = Query(None, description="Recherche par nom ou domaine"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db)
):
    """Liste tous les clients avec filtres"""
    
    query = select(Client)
    
    # Filtres
    if is_active is not None:
        query = query.where(Client.is_active == is_active)
    
    if subscription_type:
        query = query.where(Client.subscription_type == subscription_type)
    
    if size_category:
        query = query.where(Client.size_category == size_category)
    
    if search:
        search_term = f"%{search.lower()}%"
        query = query.where(
            or_(
                func.lower(Client.name).like(search_term),
                func.lower(Client.domain).like(search_term)
            )
        )
    
    # Tri par date de création (plus récents en premier)
    query = query.order_by(Client.created_at.desc())
    
    # Count total
    count_query = select(func.count()).select_from(Client)
    if is_active is not None:
        count_query = count_query.where(Client.is_active == is_active)
    total = db.execute(count_query).scalar() or 0
    
    # Pagination
    query = query.offset(skip).limit(limit)
    
    # Exécution
    result = db.execute(query)
    clients = result.scalars().all()
    
    return {
        "items": clients,
        "total": total,
        "skip": skip,
        "limit": limit
    }


@router.post("/", response_model=ClientResponse, status_code=status.HTTP_201_CREATED)
async def create_client(
    client: ClientCreate,
    create_tenant: bool = Query(True, description="Créer automatiquement un tenant associé"),
    db: Session = Depends(get_db)
):
    """
    Crée un nouveau client
    
    - **create_tenant**: Si true, crée automatiquement un tenant associé
    """
    client_data = client.model_dump()
    
    # Vérifier que le nom n'existe pas déjà
    existing_client = db.execute(
        select(Client).where(Client.name == client.name)
    ).scalar_one_or_none()
    
    if existing_client:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Un client avec le nom '{client.name}' existe déjà"
        )
    
    # Vérifier que le domaine n'existe pas déjà (si fourni)
    if client.domain:
        existing_domain = db.execute(
            select(Client).where(Client.domain == client.domain)
        ).scalar_one_or_none()
        
        if existing_domain:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Le domaine '{client.domain}' est déjà utilisé"
            )
    
    # Créer le tenant si demandé
    tenant_id = None
    if create_tenant:
        # Configurer les limites par type d'abonnement
        limits = {
            'starter': {'max_users': 5, 'max_organizations': 1},
            'professional': {'max_users': 50, 'max_organizations': 10},
            'enterprise': {'max_users': 500, 'max_organizations': 100}
        }
        
        tenant_limits = limits.get(client.subscription_type, limits['starter'])
        
        db_tenant = Tenant(
            name=client.name,
            is_active=True,
            subscription_type=client.subscription_type,
            max_users=tenant_limits['max_users'],
            max_organizations=tenant_limits['max_organizations']
        )
        
        db.add(db_tenant)
        db.flush()  # Pour obtenir l'ID
        tenant_id = db_tenant.id
        client_data['tenant_id'] = tenant_id

        logger.info(f"✓ Tenant créé: {db_tenant.name} ({tenant_id})")

        # Créer les 4 templates de rapport par défaut pour ce tenant
        templates_created = create_default_templates_for_tenant(db, tenant_id, client.name)
        logger.info(f"✓ {templates_created} templates créés pour le tenant {client.name}")

    # Créer le client
    db_client = Client(**client_data)

    db.add(db_client)
    db.commit()
    db.refresh(db_client)

    logger.info(f"✓ Client créé: {db_client.name} ({db_client.id})")
    return db_client


@router.get("/{client_id}", response_model=ClientResponse)
async def get_client(
    client_id: UUID,
    db: Session = Depends(get_db)
):
    """Récupère un client par son ID"""
    client = db.get(Client, client_id)
    
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client non trouvé"
        )
    
    return client


@router.patch("/{client_id}", response_model=ClientResponse)
async def update_client(
    client_id: UUID,
    client_update: ClientUpdate,
    db: Session = Depends(get_db)
):
    """Met à jour un client"""
    db_client = db.get(Client, client_id)
    
    if not db_client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client non trouvé"
        )
    
    # Vérifier l'unicité du nom si modifié
    if client_update.name and client_update.name != db_client.name:
        existing = db.execute(
            select(Client).where(
                and_(
                    Client.name == client_update.name,
                    Client.id != client_id
                )
            )
        ).scalar_one_or_none()
        
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Un client avec le nom '{client_update.name}' existe déjà"
            )
    
    # Vérifier l'unicité du domaine si modifié
    if client_update.domain and client_update.domain != db_client.domain:
        existing = db.execute(
            select(Client).where(
                and_(
                    Client.domain == client_update.domain,
                    Client.id != client_id
                )
            )
        ).scalar_one_or_none()
        
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Le domaine '{client_update.domain}' est déjà utilisé"
            )
    
    # Mettre à jour les champs
    update_data = client_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_client, field, value)
    
    db.commit()
    db.refresh(db_client)
    
    logger.info(f"✓ Client mis à jour: {db_client.name} ({db_client.id})")
    return db_client


@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_client(
    client_id: UUID,
    force: bool = Query(False, description="Forcer la suppression même si le client a des dépendances"),
    delete_tenant: bool = Query(True, description="Supprimer également le tenant associé"),
    db: Session = Depends(get_db)
):
    """
    Supprime un client
    
    - **force**: Si false, empêche la suppression si le client a des dépendances
    - **delete_tenant**: Si true, supprime également le tenant associé
    """
    db_client = db.get(Client, client_id)
    
    if not db_client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client non trouvé"
        )
    
    if not force:
        # TODO: Vérifier s'il y a des dépendances (organisations, audits, utilisateurs, etc.)
        # Pour l'instant, on autorise la suppression
        pass
    
    # Supprimer le tenant associé si demandé
    if delete_tenant and db_client.tenant_id:
        tenant = db.get(Tenant, db_client.tenant_id)
        if tenant:
            db.delete(tenant)
            logger.info(f"✓ Tenant supprimé: {tenant.id}")
    
    db.delete(db_client)
    db.commit()
    
    logger.info(f"✓ Client supprimé: {client_id}")


# ============================================================================
# ENDPOINTS : Statistiques
# ============================================================================

@router.get("/stats/overview", response_model=ClientStats)
async def get_clients_stats(db: Session = Depends(get_db)):
    """Récupère les statistiques globales des clients"""
    
    # Total clients
    total_clients = db.scalar(select(func.count(Client.id))) or 0
    
    # Actifs/Inactifs
    active_clients = db.scalar(
        select(func.count(Client.id))
        .where(Client.is_active == True)
    ) or 0
    
    inactive_clients = total_clients - active_clients
    
    # Répartition par type d'abonnement
    subscription_stats = db.execute(
        select(
            Client.subscription_type,
            func.count(Client.id).label('count')
        ).group_by(Client.subscription_type)
    ).all()
    
    subscription_breakdown = {row.subscription_type: row.count for row in subscription_stats}
    
    return ClientStats(
        total_clients=total_clients,
        active_clients=active_clients,
        inactive_clients=inactive_clients,
        subscription_breakdown=subscription_breakdown
    )


# ============================================================================
# ENDPOINTS : Actions spécialisées
# ============================================================================

@router.post("/{client_id}/activate", response_model=ClientResponse)
async def activate_client(
    client_id: UUID,
    db: Session = Depends(get_db)
):
    """Active un client"""
    db_client = db.get(Client, client_id)
    
    if not db_client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client non trouvé"
        )
    
    if db_client.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le client est déjà actif"
        )
    
    db_client.is_active = True
    
    # Activer également le tenant associé si nécessaire
    if db_client.tenant_id:
        tenant = db.get(Tenant, db_client.tenant_id)
        if tenant and not tenant.is_active:
            tenant.is_active = True
            logger.info(f"✓ Tenant activé: {tenant.id}")
    
    db.commit()
    db.refresh(db_client)
    
    logger.info(f"✓ Client activé: {db_client.name}")
    return db_client


@router.post("/{client_id}/deactivate", response_model=ClientResponse)
async def deactivate_client(
    client_id: UUID,
    db: Session = Depends(get_db)
):
    """Désactive un client"""
    db_client = db.get(Client, client_id)
    
    if not db_client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client non trouvé"
        )
    
    if not db_client.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le client est déjà inactif"
        )
    
    db_client.is_active = False
    
    # Désactiver également le tenant associé si nécessaire
    if db_client.tenant_id:
        tenant = db.get(Tenant, db_client.tenant_id)
        if tenant and tenant.is_active:
            tenant.is_active = False
            logger.info(f"✓ Tenant désactivé: {tenant.id}")
    
    db.commit()
    db.refresh(db_client)
    
    logger.info(f"✓ Client désactivé: {db_client.name}")
    return db_client