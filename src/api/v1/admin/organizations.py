# backend/src/api/v1/organizations.py
"""
API FastAPI pour le module Organizations (Clients)
Endpoints CRUD pour les organizations clientes
"""

from typing import Optional, Literal, Dict, Any, List
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func, and_, or_, text, text
from sqlalchemy.orm import Session

from src.database import get_db
from src.models.organization import Organization
from src.models.tenant import Tenant
from src.schemas.organization import (
    OrganizationCreate,
    OrganizationUpdate,
    OrganizationResponse,
    OrganizationListResponse,
    OrganizationStats,
    TenantCreateData,
)
from src.services.template_service import duplicate_default_templates_for_tenant

import logging

logger = logging.getLogger(__name__)

# NB: ce routeur était déjà monté sous /admin/organizations dans ce fichier.
router = APIRouter(prefix="/admin/organizations", tags=["Organizations"])

# ============================================================================
# Helpers
# ============================================================================

def _legacy_to_current_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Remappe d'éventuelles clés héritées de l'ancien schéma vers le schéma courant.
      - sector -> activity
      - enterprise_category -> category
      - employee_count -> workforce
    Sauvegarde les champs INSEE dans insee_data (JSONB).
    """
    d = dict(data)

    # Toujours convertir sector → activity (et supprimer sector)
    if "sector" in d:
        if "activity" not in d or not d["activity"]:
            d["activity"] = d["sector"]
        d.pop("sector", None)  # Supprimer sector dans tous les cas

    if "enterprise_category" in d and "category" not in d:
        d["category"] = d.pop("enterprise_category")

    if "employee_count" in d and "workforce" not in d:
        # accepte int/str, laisse None sinon
        try:
            d["workforce"] = int(d.pop("employee_count"))
        except Exception:
            d.pop("employee_count", None)

    # ✅ NOUVEAU : Extraire et sauvegarder TOUTES les données INSEE
    # Liste des champs qui sont des colonnes normales de la table organization
    # (ces champs ne doivent PAS être dans insee_data)
    organization_columns = {
        "name", "domain", "subscription_type", "email", "phone", 
        "country_code", "activity", "category", "workforce", 
        "is_active", "max_suppliers", "max_auditors", "tenant_id",
        "naf", "naf_title", "id", "created_at", "updated_at"
    }
    
    # Extraire TOUS les champs qui ne sont PAS des colonnes de la table
    insee_data = {}
    for key in list(d.keys()):
        if key not in organization_columns:
            value = d.pop(key)
            if value is not None:  # Ne garder que les valeurs non nulles
                insee_data[key] = value
    
    # Sauvegarder dans le champ JSONB insee_data si des données existent
    if insee_data:
        d["insee_data"] = insee_data
        logger.info(f"✅ Données INSEE à sauvegarder: {list(insee_data.keys())}")
    else:
        logger.warning("⚠️ Aucune donnée INSEE à sauvegarder")

    return d


# ============================================================================
# ENDPOINTS : Organizations (CRUD)
# ============================================================================

@router.get("/", response_model=OrganizationListResponse)
async def list_organizations(
    is_active: Optional[bool] = Query(None),
    subscription_type: Optional[Literal["starter", "professional", "enterprise"]] = Query(None),
    # recherche plein texte
    search: Optional[str] = Query(None, description="Recherche par nom ou domaine"),
    # filtres métier
    activity: Optional[str] = Query(None, description="Secteur d'activité (libellé NAF)"),
    category: Optional[Literal["MIC", "PME", "ETI", "GE"]] = Query(None, description="Catégorie INSEE"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """Liste toutes les organizations avec filtres et recherche."""

    query = select(Organization)

    # Filtres
    if is_active is not None:
        query = query.where(Organization.is_active == is_active)

    if subscription_type:
        query = query.where(Organization.subscription_type == subscription_type)

    if activity:
        query = query.where(Organization.activity.ilike(f"%{activity}%"))

    if category:
        query = query.where(Organization.category == category)

    if search:
        sp = f"%{search.lower()}%"
        query = query.where(
            or_(
                func.lower(Organization.name).like(sp),
                func.lower(Organization.domain).like(sp),
                func.lower(Organization.naf_title).like(sp),
            )
        )

    # Tri + pagination
    query = query.order_by(Organization.created_at.desc()).offset(skip).limit(limit)

    organizations = db.execute(query).scalars().all()

    # Total
    count_q = select(func.count()).select_from(Organization)
    if is_active is not None:
        count_q = count_q.where(Organization.is_active == is_active)
    if subscription_type:
        count_q = count_q.where(Organization.subscription_type == subscription_type)
    if activity:
        count_q = count_q.where(Organization.activity.ilike(f"%{activity}%"))
    if category:
        count_q = count_q.where(Organization.category == category)
    if search:
        sp = f"%{search.lower()}%"
        count_q = count_q.where(
            or_(
                func.lower(Organization.name).like(sp),
                func.lower(Organization.domain).like(sp),
                func.lower(Organization.naf_title).like(sp),
            )
        )
    total = db.execute(count_q).scalar() or 0

    return {"items": organizations, "total": total, "skip": skip, "limit": limit}


@router.post("/", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
async def create_organization(
    organization: OrganizationCreate,
    create_tenant: bool = Query(True, description="Créer automatiquement un tenant associé"),
    db: Session = Depends(get_db),
):
    """
    Crée une nouvelle organization cliente.
    Remappage legacy -> schéma courant assuré.
    """
    
    # 🔍 DEBUG : Voir les données brutes reçues
    logger.info("=" * 80)
    logger.info("🔍 DONNÉES REÇUES PAR LE BACKEND:")
    logger.info(f"📦 organization.model_dump() = {organization.model_dump()}")
    logger.info("=" * 80)

    # Remap legacy -> schéma courant
    org_data = _legacy_to_current_payload(organization.model_dump())
    
    # 🔍 DEBUG : Voir les données après mapping
    logger.info("=" * 80)
    logger.info("🔍 DONNÉES APRÈS MAPPING:")
    logger.info(f"📦 org_data = {org_data}")
    logger.info(f"📋 insee_data dans org_data = {org_data.get('insee_data', 'NON PRÉSENT')}")
    logger.info("=" * 80)

    # Unicité nom
    existing_org = db.execute(
        select(Organization).where(Organization.name == organization.name)
    ).scalar_one_or_none()
    if existing_org:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Une organisation avec le nom '{organization.name}' existe déjà",
        )

    # Tenant auto si demandé
    tenant_id = org_data.get("tenant_id")
    if create_tenant and not tenant_id:
        limits = {
            "starter": {"max_users": 5, "max_organizations": 1},
            "professional": {"max_users": 50, "max_organizations": 5},
            "enterprise": {"max_users": 500, "max_organizations": 50},
        }
        lcfg = limits.get(organization.subscription_type, limits["starter"])
        db_tenant = Tenant(
            id=uuid4(),
            name=organization.name,
            is_active=organization.is_active,
            subscription_type=organization.subscription_type,
            max_users=lcfg["max_users"],
            max_organizations=lcfg["max_organizations"],
        )
        db.add(db_tenant)
        db.flush()
        tenant_id = db_tenant.id
        logger.info(f"✓ Tenant créé: {db_tenant.name} ({tenant_id})")

        # Dupliquer les templates par défaut pour ce nouveau tenant
        try:
            created_templates = duplicate_default_templates_for_tenant(
                db=db,
                tenant_id=tenant_id,
                tenant_name=organization.name
            )
            if created_templates:
                logger.info(f"✓ {len(created_templates)} templates dupliqués pour le tenant")
        except Exception as e:
            logger.warning(f"⚠ Échec duplication templates (non bloquant): {str(e)}")

    org_data["tenant_id"] = tenant_id

    # Création
    db_organization = Organization(**org_data)
    db.add(db_organization)
    db.commit()
    db.refresh(db_organization)

    logger.info(f"✓ Organization créée: {db_organization.name} ({db_organization.id})")
    return db_organization


@router.get("/{organization_id}/admin-info")
async def get_organization_admin_info(
    organization_id: UUID, db: Session = Depends(get_db)
):
    """
    Récupère les informations de l'administrateur du tenant associé à l'organisation.

    Retourne:
      - first_name, last_name, email, phone de l'admin du tenant
      - L'admin est défini comme l'utilisateur avec is_tenant_owner = true
    """
    # 1. Récupérer l'organisation et son tenant_id
    organization = db.get(Organization, organization_id)
    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization non trouvée"
        )

    if not organization.tenant_id:
        return {
            "has_admin": False,
            "message": "Aucun tenant associé à cette organisation"
        }

    # 2. Chercher l'utilisateur proprietaire du tenant (is_tenant_owner = true)
    owner_query = text("""
        SELECT
            u.id,
            u.email,
            u.first_name,
            u.last_name,
            u.phone,
            u.created_at,
            u.last_login_at
        FROM users u
        WHERE u.tenant_id = :tenant_id
          AND u.is_tenant_owner = true
          AND u.is_active = true
        LIMIT 1
    """)

    result = db.execute(owner_query, {"tenant_id": str(organization.tenant_id)}).first()

    if not result:
        # Fallback 1: Chercher utilisateur avec role TENANT_ADMIN
        admin_query = text("""
            SELECT
                u.id,
                u.email,
                u.first_name,
                u.last_name,
                u.phone,
                u.created_at,
                u.last_login_at
            FROM users u
            JOIN user_role ur ON u.id = ur.user_id
            JOIN role r ON ur.role_id = r.id
            WHERE u.tenant_id = :tenant_id
              AND r.code = 'TENANT_ADMIN'
              AND u.is_active = true
            ORDER BY u.created_at ASC
            LIMIT 1
        """)
        result = db.execute(admin_query, {"tenant_id": str(organization.tenant_id)}).first()

    if not result:
        # Fallback 2: prendre le premier utilisateur actif du tenant
        fallback_query = text("""
            SELECT
                u.id,
                u.email,
                u.first_name,
                u.last_name,
                u.phone,
                u.created_at,
                u.last_login_at
            FROM users u
            WHERE u.tenant_id = :tenant_id
              AND u.is_active = true
            ORDER BY u.created_at ASC
            LIMIT 1
        """)
        result = db.execute(fallback_query, {"tenant_id": str(organization.tenant_id)}).first()

    if not result:
        return {
            "has_admin": False,
            "message": "Aucun utilisateur actif trouve pour ce tenant"
        }

    return {
        "has_admin": True,
        "admin": {
            "id": str(result.id),
            "email": result.email,
            "first_name": result.first_name,
            "last_name": result.last_name,
            "phone": result.phone,
            "created_at": result.created_at.isoformat() if result.created_at else None,
            "last_login_at": result.last_login_at.isoformat() if result.last_login_at else None
        }
    }


@router.get("/{organization_id}", response_model=OrganizationResponse)
async def get_organization(
    organization_id: UUID, db: Session = Depends(get_db)
):
    """Récupère une organization par son ID."""
    organization = db.get(Organization, organization_id)
    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Organization non trouvée"
        )
    return organization


@router.patch("/{organization_id}", response_model=OrganizationResponse)
async def update_organization(
    organization_id: UUID,
    organization_update: OrganizationUpdate,
    db: Session = Depends(get_db),
):
    """Met à jour une organization."""
    db_org = db.get(Organization, organization_id)
    if not db_org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Organization non trouvée"
        )

    # Unicité du nom si modifié
    if organization_update.name and organization_update.name != db_org.name:
        conflict = db.execute(
            select(Organization).where(
                and_(
                    Organization.name == organization_update.name,
                    Organization.id != organization_id,
                )
            )
        ).scalar_one_or_none()
        if conflict:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Une organisation avec le nom '{organization_update.name}' existe déjà",
            )

    # Remap legacy -> schéma courant puis update
    update_data = _legacy_to_current_payload(
        organization_update.model_dump(exclude_unset=True)
    )
    for k, v in update_data.items():
        setattr(db_org, k, v)

    db.commit()
    db.refresh(db_org)
    logger.info(f"✓ Organization mise à jour: {db_org.name} ({db_org.id})")
    return db_org


@router.delete("/{organization_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_organization(
    organization_id: UUID,
    force: bool = Query(False, description="Forcer la suppression même avec des données liées"),
    db: Session = Depends(get_db),
):
    """
    Supprime complètement une organisation et toutes ses dépendances
    
    Ordre de suppression (IMPORTANT) :
    1. Rôles des utilisateurs (user_role) - aucune contrainte
    2. Utilisateurs (users) - référence organization
    3. Organisation (organization) - référence tenant
    4. Tenant (tenant) - si non partagé
    """
    
    # 🔥🔥🔥 DEBUG MASSIF - À SUPPRIMER APRÈS LE DIAGNOSTIC
    print("\n" + "=" * 100)
    print("🔥🔥🔥 VERSION SQL BRUT - FONCTION DELETE_ORGANIZATION APPELÉE 🔥🔥🔥")
    print("=" * 100)
    logger.info("\n" + "=" * 100)
    logger.info("🔥🔥🔥 VERSION SQL BRUT - DÉBUT DE L'EXÉCUTION 🔥🔥🔥")
    logger.info("=" * 100)
    
    logger.info(f"🔴 Tentative de suppression de l'organisation: {organization_id}")
    
    # 1. Vérifier que l'organisation existe avec du SQL brut
    org_result = db.execute(
        text("SELECT name, tenant_id FROM organization WHERE id = :org_id"),
        {"org_id": str(organization_id)}
    ).first()
    
    if not org_result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organisation non trouvée"
        )
    
    org_name = org_result[0]
    tenant_id = org_result[1]
    
    # 2. Vérifier les dépendances critiques si force=False
    if not force:
        try:
            audit_count = db.execute(
                text("SELECT COUNT(*) FROM audit WHERE organization_id = :org_id"),
                {"org_id": str(organization_id)}
            ).scalar()
            
            if audit_count and audit_count > 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Impossible de supprimer : {audit_count} audit(s) lié(s). Utilisez force=true."
                )
        except HTTPException:
            # Re-lever l'exception HTTP
            raise
        except Exception as e:
            # Si erreur SQL (table inexistante, etc.), rollback et continuer
            db.rollback()
            if "relation" not in str(e).lower():  # Si ce n'est pas une erreur de table inexistante
                logger.warning(f"⚠️ Erreur vérification audits: {e}")
    
    try:
        # 3. Récupérer les IDs des utilisateurs
        user_ids_result = db.execute(
            text("SELECT id FROM users WHERE default_org_id = :org_id"),
            {"org_id": str(organization_id)}
        ).fetchall()
        
        user_ids = [str(row[0]) for row in user_ids_result]
        user_count = len(user_ids)
        
        logger.info(f"📋 Trouvé {user_count} utilisateur(s) à supprimer")
        
        # 4. Supprimer les rôles des utilisateurs (ÉTAPE 1 - aucune contrainte)
        if user_ids:
            user_ids_str = "'" + "','".join(user_ids) + "'"
            roles_deleted = db.execute(
                text(f"DELETE FROM user_organization_role WHERE user_id IN ({user_ids_str})")
            )
            logger.info(f"✅ Rôles supprimés pour {user_count} utilisateur(s)")
        
        # 5. Supprimer les utilisateurs (ÉTAPE 2 - avant l'organisation)
        if user_count > 0:
            users_deleted = db.execute(
                text("DELETE FROM users WHERE default_org_id = :org_id"),
                {"org_id": str(organization_id)}
            )
            logger.info(f"✅ {user_count} utilisateur(s) supprimé(s)")
        
        # 6. Supprimer l'organisation (ÉTAPE 3 - après les utilisateurs)
        org_deleted = db.execute(
            text("DELETE FROM organization WHERE id = :org_id"),
            {"org_id": str(organization_id)}
        )
        logger.info(f"✅ Organisation supprimée: {org_name}")
        
        # 7. Supprimer le tenant SI aucune autre organisation ne l'utilise (ÉTAPE 4)
        if tenant_id:
            other_orgs_count = db.execute(
                text("""
                    SELECT COUNT(*) FROM organization 
                    WHERE tenant_id = :tenant_id AND id != :org_id
                """),
                {"tenant_id": str(tenant_id), "org_id": str(organization_id)}
            ).scalar()
            
            if other_orgs_count == 0:
                db.execute(
                    text("DELETE FROM tenant WHERE id = :tenant_id"),
                    {"tenant_id": str(tenant_id)}
                )
                logger.info(f"✅ Tenant supprimé: {tenant_id} (aucune autre organisation)")
            else:
                logger.info(f"ℹ️ Tenant conservé: {tenant_id} ({other_orgs_count} autre(s) organisation(s))")
        
        # 8. Commit de toutes les suppressions
        db.commit()
        
        logger.info(f"🎉 Suppression complète réussie: {org_name} ({organization_id})")
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur lors de la suppression: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la suppression: {str(e)}"
        )


@router.patch("/{organization_id}/toggle-active", response_model=OrganizationResponse)
async def toggle_organization_active(
    organization_id: UUID, 
    db: Session = Depends(get_db)
):
    """
    Active ou désactive une organisation et tous ses utilisateurs
    
    Quand désactivée: tous les utilisateurs ne peuvent plus se connecter
    Quand réactivée: tous les utilisateurs peuvent à nouveau se connecter
    """
    
    logger.info(f"🔄 Toggle active pour: {organization_id}")
    
    db_org = db.get(Organization, organization_id)
    if not db_org:
        raise HTTPException(status_code=404, detail="Organisation non trouvée")
    
    new_status = not db_org.is_active
    db_org.is_active = new_status
    
    try:
        result = db.execute(
            text("UPDATE users SET is_active = :status WHERE default_org_id = :org_id RETURNING id"),
            {"status": new_status, "org_id": str(organization_id)}
        )
        
        updated_count = len(result.fetchall())
        db.commit()
        db.refresh(db_org)
        
        status_text = "activée" if new_status else "désactivée"
        logger.info(f"✅ Organisation {status_text}: {db_org.name}")
        logger.info(f"✅ {updated_count} utilisateur(s) {status_text}(s)")
        
        return db_org
        
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# ENDPOINTS : Statistiques
# ============================================================================

@router.get("/stats/overview", response_model=OrganizationStats)
def get_organizations_overview(db: Session = Depends(get_db)) -> "OrganizationStats":
    """
    Vue synthétique des organisations :
      - total_clients / active_clients / inactive_clients
      - total_users (somme workforce)
      - subscription_breakdown
    """

    total_clients = db.scalar(select(func.count(Organization.id))) or 0
    active_clients = (
        db.scalar(
            select(func.count(Organization.id)).where(Organization.is_active.is_(True))
        )
        or 0
    )
    inactive_clients = total_clients - active_clients

    # Répartition par type d'abonnement
    sub_rows = db.execute(
        select(Organization.subscription_type, func.count(Organization.id)).group_by(
            Organization.subscription_type
        )
    ).all()
    counted = {(k or "starter"): v for (k, v) in sub_rows}
    subscription_breakdown = {
        "starter": counted.get("starter", 0),
        "professional": counted.get("professional", 0),
        "enterprise": counted.get("enterprise", 0),
    }

    # Total utilisateurs = somme workforce
    total_users = (
        db.scalar(select(func.coalesce(func.sum(Organization.workforce), 0))) or 0
    )

    return {
        "total_clients": int(total_clients),
        "active_clients": int(active_clients),
        "inactive_clients": int(inactive_clients),
        "total_users": int(total_users),
        "subscription_breakdown": subscription_breakdown,
    }


@router.get("/stats/by-subscription")
async def get_stats_by_subscription(db: Session = Depends(get_db)):
    """Statistiques par type d'abonnement."""
    rows = db.execute(
        select(
            Organization.subscription_type,
            func.count(Organization.id).label("total"),
            func.count(Organization.id)
            .filter(Organization.is_active.is_(True))
            .label("active"),
            func.coalesce(func.avg(Organization.workforce), 0).label("avg_employees"),
            func.coalesce(func.sum(Organization.workforce), 0).label("total_employees"),
        ).group_by(Organization.subscription_type)
    ).all()

    return [
        {
            "subscription_type": r.subscription_type,
            "total": r.total,
            "active": r.active,
            "inactive": r.total - r.active,
            "avg_employees": round(float(r.avg_employees), 1),
            "total_employees": int(r.total_employees),
        }
        for r in rows
    ]


@router.get("/stats/by-sector")
async def get_stats_by_sector(db: Session = Depends(get_db)):
    """Top secteurs d'activité (libellé NAF, champ `activity`)."""
    rows = db.execute(
        select(Organization.activity, func.count(Organization.id).label("count"))
        .where(Organization.activity.isnot(None))
        .group_by(Organization.activity)
        .order_by(func.count(Organization.id).desc())
        .limit(10)
    ).all()
    return [{"activity": r.activity, "count": r.count} for r in rows]


# ============================================================================
# ENDPOINTS : Recherche & Export
# ============================================================================

@router.get("/search")
async def search_organizations(
    q: str = Query(..., min_length=2, description="Terme de recherche"),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """Recherche rapide d'organizations par nom/domaine/libellé NAF."""
    sp = f"%{q.lower()}%"
    orgs = (
        db.execute(
            select(Organization).where(
                or_(
                    func.lower(Organization.name).like(sp),
                    func.lower(Organization.domain).like(sp),
                    func.lower(Organization.naf_title).like(sp),
                )
            ).limit(limit)
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": org.id,
            "name": org.name,
            "domain": org.domain,
            "subscription_type": org.subscription_type,
            "is_active": org.is_active,
        }
        for org in orgs
    ]


@router.get("/export")
async def export_organizations(
    format: str = Query("json", pattern="^(json|csv)$"),
    is_active: Optional[bool] = Query(None),
    subscription_type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Export JSON/CSV des organizations (schéma courant)."""
    query = select(Organization)
    if is_active is not None:
        query = query.where(Organization.is_active == is_active)
    if subscription_type:
        query = query.where(Organization.subscription_type == subscription_type)

    orgs = db.execute(query).scalars().all()

    if format == "json":
        from fastapi.responses import JSONResponse

        data = [
            OrganizationResponse.model_validate(o).model_dump(mode="json") for o in orgs
        ]
        return JSONResponse(content=data)

    # CSV
    import csv
    from io import StringIO
    from fastapi.responses import StreamingResponse

    output = StringIO()
    writer = csv.writer(output)

    headers = [
        "id",
        "name",
        "domain",
        "subscription_type",
        "email",
        "phone",
        "country_code",
        "category",
        "activity",
        "workforce",
        "siret",
        "naf",
        "naf_title",
        "is_active",
        "created_at",
        "updated_at",
    ]
    writer.writerow(headers)

    for o in orgs:
        writer.writerow(
            [
                str(o.id),
                o.name,
                o.domain or "",
                o.subscription_type or "",
                o.email or "",
                o.phone or "",
                o.country_code or "FR",
                o.category or "",
                o.activity or "",
                o.workforce or 0,
                o.siret or "",
                o.naf or "",
                o.naf_title or "",
                bool(o.is_active),
                o.created_at.isoformat() if o.created_at else "",
                o.updated_at.isoformat() if o.updated_at else "",
            ]
        )

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=organizations_export.csv"},
    )