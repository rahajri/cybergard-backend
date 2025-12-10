"""
Router FastAPI pour le module de génération de rapports.

Endpoints disponibles :
- Gestion des templates de rapports
- Génération de rapports
- Consultation des rapports générés
- Téléchargement des PDF
- Types de widgets disponibles
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import select, and_, desc, func
from typing import List, Optional
from uuid import UUID
from datetime import datetime
import logging

from ...database import get_db
from ...models.audit import User
from ...models.campaign import Campaign
from ...models.report import (
    ReportTemplate,
    ReportWidget,
    GeneratedReport,
    ReportGenerationJob
)
from ...schemas.report import (
    # Templates
    ReportTemplateCreate,
    ReportTemplateUpdate,
    ReportTemplateResponse,
    ReportTemplateListResponse,
    TemplateScope,
    # Rapports
    GenerateReportRequest,
    GenerateScanReportRequest,
    GenerateReportResponse,
    GeneratedReportResponse,
    GeneratedReportListResponse,
    ReportScope,
    # Jobs
    ReportGenerationJobResponse,
    # Widgets
    WidgetTypesResponse,
    WidgetDefaultConfigResponse,
    WidgetCategoryInfo,
    WidgetTypeInfo,
    # Charts
    ChartDataRequest,
    ChartDataResponse,
    # Enums
    TemplateType,
    ReportStatus,
    JobStatus
)
from ...dependencies_keycloak import get_current_user_keycloak, require_permission

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/reports",
    tags=["Reports"]
)


# ============================================================================
# TEMPLATES DE RAPPORTS
# ============================================================================

@router.get("/templates", response_model=ReportTemplateListResponse)
async def list_templates(
    template_type: Optional[TemplateType] = Query(None, description="Filtrer par type"),
    template_category: Optional[str] = Query(None, description="Filtrer par catégorie (audit, ebios, scan)"),
    report_scope: Optional[TemplateScope] = Query(None, description="Filtrer par scope (consolidated, entity, both)"),
    is_system: Optional[bool] = Query(None, description="Filtrer par templates système"),
    tenant_id: Optional[UUID] = Query(None, description="Filtrer par tenant (admin uniquement)"),
    page: int = Query(1, ge=1, description="Numéro de page"),
    limit: int = Query(20, ge=1, le=100, description="Nombre d'éléments par page"),
    current_user: User = Depends(require_permission("REPORT_READ")),
    db: Session = Depends(get_db)
):
    """
    Liste les templates de rapports disponibles.

    Paramètres de filtrage:
    - template_type: Type de template (system, executive, technical, etc.)
    - template_category: Catégorie du template (audit, ebios, scan)
        - audit: Templates pour campagnes d'audit (ISO 27001, NIS2, etc.)
        - ebios: Templates pour analyses EBIOS RM
        - scan: Templates pour rapports du scanner externe
    - report_scope: Scope du rapport (consolidated, entity, both)
        - consolidated: Pour rapports multi-organismes (vue écosystème)
        - entity: Pour rapports mono-organisme (vue individuelle)
        - both: Compatible avec les deux types
    - tenant_id: Filtrer par client (admin uniquement)

    Retourne :
    - Pour Super Admin : Tous les templates (système + custom de tous les clients)
    - Pour autres users : Templates système + templates de leur tenant
    """
    try:
        # Vérifier si l'utilisateur est Super Admin ou Platform Admin
        user_roles = []
        if current_user.roles:
            user_roles = [r.code if hasattr(r, 'code') else str(r) for r in current_user.roles]

        is_admin = any(role in ['SUPER_ADMIN', 'PLATFORM_ADMIN'] for role in user_roles)

        # Construction de la requête
        if is_admin:
            # Admin voit tous les templates
            query = select(ReportTemplate)
            count_base_query = select(func.count()).select_from(ReportTemplate)

            # Filtre optionnel par tenant pour l'admin
            if tenant_id:
                query = query.where(ReportTemplate.tenant_id == tenant_id)
                count_base_query = count_base_query.where(ReportTemplate.tenant_id == tenant_id)
        else:
            # User normal : templates système OU templates de son tenant
            query = select(ReportTemplate).where(
                (ReportTemplate.is_system == True) |
                (ReportTemplate.tenant_id == current_user.tenant_id)
            )
            count_base_query = select(func.count()).select_from(ReportTemplate).where(
                (ReportTemplate.is_system == True) |
                (ReportTemplate.tenant_id == current_user.tenant_id)
            )

        # Filtres optionnels
        if template_type:
            query = query.where(ReportTemplate.template_type == template_type.value)
            count_base_query = count_base_query.where(ReportTemplate.template_type == template_type.value)

        if is_system is not None:
            query = query.where(ReportTemplate.is_system == is_system)
            count_base_query = count_base_query.where(ReportTemplate.is_system == is_system)

        # Filtre par template_category (audit, ebios, scan)
        if template_category:
            query = query.where(ReportTemplate.template_category == template_category)
            count_base_query = count_base_query.where(ReportTemplate.template_category == template_category)

        # Filtre par report_scope
        if report_scope:
            # Si on demande 'consolidated' ou 'entity', inclure aussi 'both'
            if report_scope == TemplateScope.CONSOLIDATED:
                query = query.where(
                    (ReportTemplate.report_scope == 'consolidated') |
                    (ReportTemplate.report_scope == 'both')
                )
                count_base_query = count_base_query.where(
                    (ReportTemplate.report_scope == 'consolidated') |
                    (ReportTemplate.report_scope == 'both')
                )
            elif report_scope == TemplateScope.ENTITY:
                query = query.where(
                    (ReportTemplate.report_scope == 'entity') |
                    (ReportTemplate.report_scope == 'both')
                )
                count_base_query = count_base_query.where(
                    (ReportTemplate.report_scope == 'entity') |
                    (ReportTemplate.report_scope == 'both')
                )
            elif report_scope == TemplateScope.SCAN_INDIVIDUAL:
                query = query.where(
                    (ReportTemplate.report_scope == 'scan_individual') |
                    (ReportTemplate.report_scope == 'scan_both')
                )
                count_base_query = count_base_query.where(
                    (ReportTemplate.report_scope == 'scan_individual') |
                    (ReportTemplate.report_scope == 'scan_both')
                )
            elif report_scope == TemplateScope.SCAN_ECOSYSTEM:
                query = query.where(
                    (ReportTemplate.report_scope == 'scan_ecosystem') |
                    (ReportTemplate.report_scope == 'scan_both')
                )
                count_base_query = count_base_query.where(
                    (ReportTemplate.report_scope == 'scan_ecosystem') |
                    (ReportTemplate.report_scope == 'scan_both')
                )
            elif report_scope == TemplateScope.SCAN_BOTH:
                query = query.where(
                    (ReportTemplate.report_scope == 'scan_individual') |
                    (ReportTemplate.report_scope == 'scan_ecosystem') |
                    (ReportTemplate.report_scope == 'scan_both')
                )
                count_base_query = count_base_query.where(
                    (ReportTemplate.report_scope == 'scan_individual') |
                    (ReportTemplate.report_scope == 'scan_ecosystem') |
                    (ReportTemplate.report_scope == 'scan_both')
                )
            else:  # 'both'
                query = query.where(ReportTemplate.report_scope == report_scope.value)
                count_base_query = count_base_query.where(ReportTemplate.report_scope == report_scope.value)

        # Tri par défaut : templates système en premier, puis par nom
        query = query.order_by(
            desc(ReportTemplate.is_system),
            ReportTemplate.name
        )

        # Count total
        count_query = count_base_query

        total = db.execute(count_query).scalar() or 0

        # Pagination
        query = query.offset((page - 1) * limit).limit(limit)

        # Exécution
        result = db.execute(query)
        templates = result.scalars().all()

        return ReportTemplateListResponse(
            items=[ReportTemplateResponse.model_validate(t) for t in templates],
            total=total,
            page=page,
            limit=limit
        )

    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération des templates: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération des templates: {str(e)}"
        )


@router.get("/templates/{template_id}", response_model=ReportTemplateResponse)
async def get_template(
    template_id: UUID,
    current_user: User = Depends(require_permission("REPORT_READ")),
    db: Session = Depends(get_db)
):
    """Récupère les détails d'un template."""
    try:
        # Vérifier si l'utilisateur est admin (accès à tous les templates)
        # Extraire les codes des rôles (les rôles peuvent être des objets Role avec .code)
        user_roles = []
        if current_user.roles:
            user_roles = [r.code if hasattr(r, 'code') else str(r) for r in current_user.roles]

        is_admin = any(role in ['SUPER_ADMIN', 'PLATFORM_ADMIN'] for role in user_roles)
        logger.debug(f"🔍 get_template: user_roles={user_roles}, is_admin={is_admin}")

        if is_admin:
            # Admin : accès à tous les templates
            query = select(ReportTemplate).where(ReportTemplate.id == template_id)
        else:
            # Utilisateur normal : accès aux templates système ou de son tenant
            query = select(ReportTemplate).where(
                and_(
                    ReportTemplate.id == template_id,
                    (ReportTemplate.is_system == True) |
                    (ReportTemplate.tenant_id == current_user.tenant_id)
                )
            )

        template = db.execute(query).scalar_one_or_none()

        if not template:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Template non trouvé"
            )

        return ReportTemplateResponse.model_validate(template)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération du template: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération du template: {str(e)}"
        )


@router.post("/templates", response_model=ReportTemplateResponse, status_code=http_status.HTTP_201_CREATED)
async def create_template(
    template_data: ReportTemplateCreate,
    current_user: User = Depends(require_permission("REPORT_READ")),
    db: Session = Depends(get_db)
):
    """
    Crée un nouveau template de rapport.

    Permissions : ADMIN uniquement
    """
    try:
        # Vérifier les permissions (TODO: ajouter check de rôle ADMIN)

        # Créer le template
        new_template = ReportTemplate(
            tenant_id=current_user.tenant_id,
            name=template_data.name,
            description=template_data.description,
            template_type=template_data.template_type.value,
            page_size=template_data.page_size.value,
            orientation=template_data.orientation.value,
            margins=template_data.margins,
            color_scheme=template_data.color_scheme,
            fonts=template_data.fonts,
            custom_css=template_data.custom_css,
            default_logo=template_data.default_logo,
            structure=template_data.structure,
            is_system=False,  # Les templates créés via API ne sont jamais système
            created_by=current_user.id
        )

        db.add(new_template)
        db.commit()
        db.refresh(new_template)

        logger.info(f"✅ Template créé: {new_template.id} - {new_template.name}")

        return ReportTemplateResponse.model_validate(new_template)

    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur lors de la création du template: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la création du template: {str(e)}"
        )


@router.put("/templates/{template_id}", response_model=ReportTemplateResponse)
async def update_template(
    template_id: UUID,
    template_data: ReportTemplateUpdate,
    current_user: User = Depends(require_permission("REPORT_READ")),
    db: Session = Depends(get_db)
):
    """
    Met à jour un template de rapport existant.

    Permissions :
    - Impossible de modifier les templates système
    - SUPER_ADMIN/PLATFORM_ADMIN : accès à tous les templates
    - Autres : uniquement les templates de leur tenant
    """
    try:
        # Vérifier si l'utilisateur est admin
        # Extraire les codes des rôles (les rôles peuvent être des objets Role avec .code)
        user_roles = []
        if current_user.roles:
            user_roles = [r.code if hasattr(r, 'code') else str(r) for r in current_user.roles]

        is_admin = any(role in ['SUPER_ADMIN', 'PLATFORM_ADMIN'] for role in user_roles)
        logger.debug(f"🔍 update_template: user_roles={user_roles}, is_admin={is_admin}")

        # Récupérer le template
        if is_admin:
            # Admin : accès à tous les templates non-système
            query = select(ReportTemplate).where(ReportTemplate.id == template_id)
        else:
            # Utilisateur normal : uniquement son tenant
            query = select(ReportTemplate).where(
                and_(
                    ReportTemplate.id == template_id,
                    ReportTemplate.tenant_id == current_user.tenant_id
                )
            )

        template = db.execute(query).scalar_one_or_none()

        if not template:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Template non trouvé ou accès refusé"
            )

        # Vérifier que ce n'est pas un template système
        if template.is_system:
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="Impossible de modifier un template système"
            )

        # Mettre à jour les champs fournis
        update_data = template_data.model_dump(exclude_unset=True)

        for field, value in update_data.items():
            # Gérer les enums
            if field in ['template_type', 'page_size', 'orientation'] and value is not None:
                value = value.value if hasattr(value, 'value') else value
            setattr(template, field, value)

        db.commit()
        db.refresh(template)

        logger.info(f"✅ Template mis à jour: {template.id} - {template.name}")

        return ReportTemplateResponse.model_validate(template)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur lors de la mise à jour du template: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la mise à jour du template: {str(e)}"
        )


@router.delete("/templates/{template_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: UUID,
    current_user: User = Depends(require_permission("REPORT_READ")),
    db: Session = Depends(get_db)
):
    """
    Supprime un template de rapport.

    Permissions :
    - Impossible de supprimer les templates système
    - Uniquement les templates du tenant de l'utilisateur
    """
    try:
        # Récupérer le template
        query = select(ReportTemplate).where(
            and_(
                ReportTemplate.id == template_id,
                ReportTemplate.tenant_id == current_user.tenant_id
            )
        )

        template = db.execute(query).scalar_one_or_none()

        if not template:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Template non trouvé ou accès refusé"
            )

        # Vérifier que ce n'est pas un template système
        if template.is_system:
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="Impossible de supprimer un template système"
            )

        # Supprimer le template
        db.delete(template)
        db.commit()

        logger.info(f"✅ Template supprimé: {template_id}")

        return None

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur lors de la suppression du template: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la suppression du template: {str(e)}"
        )


@router.post("/templates/{template_id}/duplicate", response_model=ReportTemplateResponse, status_code=http_status.HTTP_201_CREATED)
async def duplicate_template(
    template_id: UUID,
    new_name: str = Query(..., description="Nom du template dupliqué"),
    current_user: User = Depends(require_permission("REPORT_READ")),
    db: Session = Depends(get_db)
):
    """
    Duplique un template existant.

    Permet de créer une copie modifiable d'un template (système ou custom).
    """
    try:
        # Récupérer le template source
        query = select(ReportTemplate).where(
            and_(
                ReportTemplate.id == template_id,
                # Accès : template système OU du tenant
                (ReportTemplate.is_system == True) |
                (ReportTemplate.tenant_id == current_user.tenant_id)
            )
        )

        source_template = db.execute(query).scalar_one_or_none()

        if not source_template:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Template source non trouvé"
            )

        # Créer le duplicata
        new_template = ReportTemplate(
            tenant_id=current_user.tenant_id,
            name=new_name,
            description=source_template.description,
            template_type=source_template.template_type,
            report_scope=source_template.report_scope,  # Copie le scope (consolidated/entity/both)
            page_size=source_template.page_size,
            orientation=source_template.orientation,
            margins=source_template.margins,
            color_scheme=source_template.color_scheme,
            fonts=source_template.fonts,
            custom_css=source_template.custom_css,
            default_logo=source_template.default_logo,
            structure=source_template.structure,  # Copie la structure JSON
            is_system=False,  # Les duplicatas ne sont jamais système
            is_default=False,  # Les duplicatas ne sont jamais par défaut
            created_by=current_user.id
        )

        db.add(new_template)
        db.commit()
        db.refresh(new_template)

        logger.info(f"✅ Template dupliqué: {source_template.id} → {new_template.id} - {new_name}")

        return ReportTemplateResponse.model_validate(new_template)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur lors de la duplication du template: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la duplication du template: {str(e)}"
        )


@router.post("/templates/{template_id}/logo", response_model=ReportTemplateResponse)
async def upload_template_logo(
    template_id: UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(require_permission("REPORT_READ")),
    db: Session = Depends(get_db)
):
    """
    Upload un logo personnalisé pour un template de rapport.

    Formats acceptés: PNG, JPG, JPEG, SVG
    Taille max: 2 MB

    Le logo est stocké en base64 dans le champ custom_logo du template.
    """
    import base64
    import os

    try:
        # Vérifier le format du fichier
        ALLOWED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.svg'}
        ALLOWED_MIME_TYPES = {'image/png', 'image/jpeg', 'image/svg+xml'}
        MAX_SIZE = 2 * 1024 * 1024  # 2 MB

        file_ext = os.path.splitext(file.filename or '')[1].lower()
        if file_ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=f"Format non supporté. Formats acceptés: {', '.join(ALLOWED_EXTENSIONS)}"
            )

        if file.content_type and file.content_type not in ALLOWED_MIME_TYPES:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=f"Type MIME non supporté: {file.content_type}"
            )

        # Lire et vérifier la taille
        file_content = await file.read()
        if len(file_content) > MAX_SIZE:
            raise HTTPException(
                status_code=http_status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Fichier trop volumineux. Taille max: 2 MB"
            )

        # Récupérer le template
        query = select(ReportTemplate).where(
            and_(
                ReportTemplate.id == template_id,
                ReportTemplate.tenant_id == current_user.tenant_id
            )
        )

        template = db.execute(query).scalar_one_or_none()

        if not template:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Template non trouvé ou accès refusé"
            )

        # Vérifier que ce n'est pas un template système
        if template.is_system:
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="Impossible de modifier un template système"
            )

        # Encoder en base64
        logo_base64 = base64.b64encode(file_content).decode('utf-8')
        mime_type = file.content_type or 'image/png'

        # Stocker avec le préfixe data URI
        template.custom_logo = f"data:{mime_type};base64,{logo_base64}"
        template.default_logo = "CUSTOM"  # Indiquer qu'on utilise un logo custom

        db.commit()
        db.refresh(template)

        logger.info(f"✅ Logo uploadé pour template: {template.id}")

        return ReportTemplateResponse.model_validate(template)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur lors de l'upload du logo: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de l'upload du logo: {str(e)}"
        )


@router.delete("/templates/{template_id}/logo", response_model=ReportTemplateResponse)
async def delete_template_logo(
    template_id: UUID,
    current_user: User = Depends(require_permission("REPORT_READ")),
    db: Session = Depends(get_db)
):
    """
    Supprime le logo personnalisé d'un template et remet le logo par défaut.
    """
    try:
        # Récupérer le template
        query = select(ReportTemplate).where(
            and_(
                ReportTemplate.id == template_id,
                ReportTemplate.tenant_id == current_user.tenant_id
            )
        )

        template = db.execute(query).scalar_one_or_none()

        if not template:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Template non trouvé ou accès refusé"
            )

        # Vérifier que ce n'est pas un template système
        if template.is_system:
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="Impossible de modifier un template système"
            )

        # Supprimer le logo custom
        template.custom_logo = None
        template.default_logo = "TENANT"  # Revenir au logo du tenant

        db.commit()
        db.refresh(template)

        logger.info(f"✅ Logo supprimé pour template: {template.id}")

        return ReportTemplateResponse.model_validate(template)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur lors de la suppression du logo: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la suppression du logo: {str(e)}"
        )


# ============================================================================
# GÉNÉRATION DE RAPPORTS
# ============================================================================

@router.post("/campaigns/{campaign_id}/generate", response_model=GenerateReportResponse, status_code=http_status.HTTP_202_ACCEPTED)
async def generate_report(
    campaign_id: UUID,
    request: GenerateReportRequest,
    current_user: User = Depends(require_permission("REPORT_READ")),
    db: Session = Depends(get_db)
):
    """
    Démarre la génération asynchrone d'un rapport pour une campagne.

    Types de rapports supportés:
    - CONSOLIDATED (report_scope='consolidated'):
        * Vue écosystème multi-organismes
        * entity_id DOIT être None
        * Stats comparatives, NC critiques globales, plan d'action consolidé

    - INDIVIDUEL (report_scope='entity'):
        * Vue mono-organisme
        * entity_id DOIT être fourni
        * Score personnalisé, analyse par domaine, benchmarking vs pairs

    Retourne immédiatement un job_id pour suivre la progression.
    """
    try:
        # ==============================================================
        # 1. VALIDATION DE COHÉRENCE scope/entity_id
        # ==============================================================
        try:
            request.validate_scope_entity_consistency()
        except ValueError as e:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=str(e)
            )

        # ==============================================================
        # 2. VÉRIFICATION CAMPAGNE
        # ==============================================================
        from ...models.campaign import Campaign
        campaign_query = select(Campaign).where(
            and_(
                Campaign.id == campaign_id,
                Campaign.tenant_id == current_user.tenant_id
            )
        )
        campaign = db.execute(campaign_query).scalar_one_or_none()

        if not campaign:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Campagne non trouvée"
            )

        # ==============================================================
        # 3. VÉRIFICATION ENTITÉ (si scope='entity')
        # ==============================================================
        entity_name = None
        if request.report_scope == ReportScope.ENTITY:
            from ...models.ecosystem import EcosystemEntity
            entity_query = select(EcosystemEntity).where(
                EcosystemEntity.id == request.entity_id
            )
            entity = db.execute(entity_query).scalar_one_or_none()

            if not entity:
                raise HTTPException(
                    status_code=http_status.HTTP_404_NOT_FOUND,
                    detail=f"Entité non trouvée: {request.entity_id}"
                )

            # Vérifier que l'entité fait partie de la campagne
            # On récupère le scope via la campagne (Campaign.scope_id -> CampaignScope)
            from ...models.campaign import Campaign, CampaignScope
            campaign_with_scope = db.execute(
                select(Campaign).where(Campaign.id == campaign_id)
            ).scalar_one_or_none()

            campaign_scope = None
            if campaign_with_scope and campaign_with_scope.scope_id:
                campaign_scope = db.execute(
                    select(CampaignScope).where(CampaignScope.id == campaign_with_scope.scope_id)
                ).scalar_one_or_none()

            if campaign_scope and campaign_scope.entity_ids:
                if str(request.entity_id) not in [str(eid) for eid in campaign_scope.entity_ids]:
                    raise HTTPException(
                        status_code=http_status.HTTP_400_BAD_REQUEST,
                        detail=f"L'entité {request.entity_id} ne fait pas partie du périmètre de cette campagne"
                    )

            entity_name = entity.name

        # ==============================================================
        # 4. VÉRIFICATION TEMPLATE ET COMPATIBILITÉ SCOPE
        # ==============================================================
        template = db.execute(
            select(ReportTemplate).where(ReportTemplate.id == request.template_id)
        ).scalar_one_or_none()

        if not template:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Template non trouvé"
            )

        # Vérifier la compatibilité du template avec le scope demandé
        template_scope = template.report_scope
        if template_scope != 'both':
            if request.report_scope == ReportScope.CONSOLIDATED and template_scope != 'consolidated':
                raise HTTPException(
                    status_code=http_status.HTTP_400_BAD_REQUEST,
                    detail=f"Le template '{template.name}' n'est pas compatible avec les rapports consolidés (scope actuel: {template_scope})"
                )
            if request.report_scope == ReportScope.ENTITY and template_scope != 'entity':
                raise HTTPException(
                    status_code=http_status.HTTP_400_BAD_REQUEST,
                    detail=f"Le template '{template.name}' n'est pas compatible avec les rapports individuels (scope actuel: {template_scope})"
                )

        # ==============================================================
        # 5. CRÉATION DU RAPPORT
        # ==============================================================
        new_report = GeneratedReport(
            tenant_id=current_user.tenant_id,
            campaign_id=campaign_id,
            template_id=request.template_id,
            report_scope=request.report_scope.value,
            entity_id=request.entity_id,
            title=request.title,
            description=request.description,
            status=ReportStatus.PENDING.value,
            generation_mode=request.options.get('force_mode', 'draft') if request.options else 'draft',
            generated_by=current_user.id,
            report_metadata={
                "entity_name": entity_name,
                "options": request.options
            }
        )

        db.add(new_report)
        db.flush()

        # ==============================================================
        # 6. CRÉATION DU JOB DE GÉNÉRATION
        # ==============================================================
        job = ReportGenerationJob(
            tenant_id=current_user.tenant_id,
            report_id=new_report.id,
            status=JobStatus.QUEUED.value,
            total_steps=10 if request.report_scope == ReportScope.CONSOLIDATED else 8
        )

        db.add(job)
        db.commit()

        scope_label = "consolidé" if request.report_scope == ReportScope.CONSOLIDATED else f"individuel ({entity_name})"
        logger.info(f"📄 Génération de rapport {scope_label} démarrée - Job: {job.id}, Report: {new_report.id}")

        # Exécuter le job de génération de manière synchrone
        # TODO: Remplacer par Celery pour exécution asynchrone en production
        try:
            from ...services.report_job_processor import ReportJobProcessor

            processor = ReportJobProcessor(db)
            success = processor.process_job(job.id)

            if success:
                logger.info(f"✅ Rapport généré avec succès - Job: {job.id}")
                # Recharger le job pour avoir le statut à jour
                db.refresh(job)
            else:
                logger.warning(f"⚠️ Échec génération rapport - Job: {job.id}")

        except Exception as e:
            logger.error(f"❌ Erreur lors de la génération du rapport: {str(e)}", exc_info=True)
            # Le job est déjà marqué comme failed par le processor

        return GenerateReportResponse(
            job_id=job.id,
            report_id=new_report.id,
            status=JobStatus(job.status) if job.status else JobStatus.QUEUED,
            estimated_time_seconds=0 if job.status == JobStatus.COMPLETED.value else 45
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur lors du démarrage de la génération: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors du démarrage de la génération: {str(e)}"
        )


# ============================================================================
# GÉNÉRATION BULK (TOUTES LES ENTITÉS)
# ============================================================================

from pydantic import BaseModel, ConfigDict

class BulkGenerateRequest(BaseModel):
    """Requête pour génération bulk de rapports individuels."""
    template_id: UUID
    options: Optional[dict] = None

class BulkJobInfo(BaseModel):
    """Info sur un job créé."""
    model_config = ConfigDict(from_attributes=True)

    job_id: str
    report_id: str
    entity_id: str
    entity_name: str

class BulkGenerateResponse(BaseModel):
    """Réponse de génération bulk."""
    model_config = ConfigDict(from_attributes=True)

    reports_count: int
    jobs: List[BulkJobInfo]
    message: str


@router.post("/campaigns/{campaign_id}/generate-bulk", response_model=BulkGenerateResponse, status_code=http_status.HTTP_202_ACCEPTED)
async def generate_bulk_reports(
    campaign_id: UUID,
    request: BulkGenerateRequest,
    current_user: User = Depends(require_permission("REPORT_READ")),
    db: Session = Depends(get_db)
):
    """
    Génère des rapports individuels pour TOUTES les entités d'une campagne.

    DEPRECATED: Utiliser /generate-bulk/stream pour la génération avec SSE.

    Cette fonction crée les jobs mais ne les exécute pas.
    Retourne immédiatement les job_ids pour suivi via SSE.
    """
    try:
        # ==============================================================
        # 1. VÉRIFICATION CAMPAGNE
        # ==============================================================
        from ...models.campaign import Campaign, CampaignScope
        campaign = db.execute(
            select(Campaign).where(
                and_(
                    Campaign.id == campaign_id,
                    Campaign.tenant_id == current_user.tenant_id
                )
            )
        ).scalar_one_or_none()

        if not campaign:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Campagne non trouvée"
            )

        # ==============================================================
        # 2. RÉCUPÉRER LES ENTITÉS DU SCOPE
        # ==============================================================
        campaign_scope = None
        if campaign.scope_id:
            campaign_scope = db.execute(
                select(CampaignScope).where(CampaignScope.id == campaign.scope_id)
            ).scalar_one_or_none()

        if not campaign_scope or not campaign_scope.entity_ids:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="Aucune entité dans le périmètre de cette campagne"
            )

        entity_ids = campaign_scope.entity_ids
        logger.info(f"📋 Génération bulk pour {len(entity_ids)} entités")

        # ==============================================================
        # 3. VÉRIFICATION TEMPLATE
        # ==============================================================
        template = db.execute(
            select(ReportTemplate).where(ReportTemplate.id == request.template_id)
        ).scalar_one_or_none()

        if not template:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Template non trouvé"
            )

        # Vérifier que le template supporte les rapports individuels
        if template.report_scope not in ('entity', 'both'):
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=f"Le template '{template.name}' n'est pas compatible avec les rapports individuels (scope: {template.report_scope})"
            )

        # ==============================================================
        # 4. RÉCUPÉRER LES ENTITÉS
        # ==============================================================
        from ...models.ecosystem import EcosystemEntity
        entities = db.execute(
            select(EcosystemEntity).where(EcosystemEntity.id.in_(entity_ids))
        ).scalars().all()

        if not entities:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="Aucune entité trouvée dans la base"
            )

        # ==============================================================
        # 5. CRÉER UN RAPPORT PAR ENTITÉ
        # ==============================================================
        jobs_created = []

        for entity in entities:
            # Créer le rapport
            new_report = GeneratedReport(
                tenant_id=current_user.tenant_id,
                campaign_id=campaign_id,
                template_id=request.template_id,
                report_scope='entity',
                entity_id=entity.id,
                title=f"Rapport {entity.name} - {campaign.title}",
                status=ReportStatus.PENDING.value,
                generation_mode=request.options.get('force_mode', 'draft') if request.options else 'draft',
                generated_by=current_user.id,
                report_metadata={
                    "entity_name": entity.name,
                    "options": request.options,
                    "bulk_generation": True
                }
            )
            db.add(new_report)
            db.flush()

            # Créer le job
            job = ReportGenerationJob(
                tenant_id=current_user.tenant_id,
                report_id=new_report.id,
                status=JobStatus.QUEUED.value,
                total_steps=8
            )
            db.add(job)
            db.flush()

            jobs_created.append({
                "job_id": str(job.id),
                "report_id": str(new_report.id),
                "entity_id": str(entity.id),
                "entity_name": entity.name
            })

            logger.info(f"📄 Rapport créé pour {entity.name} - Job: {job.id}")

        db.commit()

        # ==============================================================
        # 6. LANCER LA GÉNÉRATION DE MANIÈRE SYNCHRONE
        # ==============================================================
        # Traiter chaque job séquentiellement dans la même requête
        # Le frontend attend la fin de tous les rapports
        from ...services.report_job_processor import ReportJobProcessor

        processor = ReportJobProcessor(db)
        success_count = 0
        failed_count = 0

        for job_info in jobs_created:
            try:
                logger.info(f"🔄 Traitement rapport pour {job_info['entity_name']}...")
                success = processor.process_job(UUID(job_info["job_id"]))
                if success:
                    logger.info(f"✅ Rapport généré pour {job_info['entity_name']}")
                    success_count += 1
                else:
                    logger.warning(f"⚠️ Échec pour {job_info['entity_name']}")
                    failed_count += 1
            except Exception as e:
                logger.error(f"❌ Erreur génération {job_info['entity_name']}: {str(e)}")
                failed_count += 1

        logger.info(f"📊 Génération bulk terminée: {success_count} succès, {failed_count} échecs")

        # Convertir les dicts en objets BulkJobInfo pour la sérialisation
        jobs_info = [BulkJobInfo(**job) for job in jobs_created]

        # Message de résultat
        if failed_count == 0:
            message = f"✅ {success_count} rapport(s) généré(s) avec succès"
        elif success_count == 0:
            message = f"❌ Échec de génération pour {failed_count} rapport(s)"
        else:
            message = f"⚠️ {success_count} rapport(s) généré(s), {failed_count} en échec"

        return BulkGenerateResponse(
            reports_count=success_count,
            jobs=jobs_info,
            message=message
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur génération bulk: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la génération bulk: {str(e)}"
        )


# ============================================================================
# GÉNÉRATION BULK AVEC SSE (Server-Sent Events)
# ============================================================================

from fastapi.responses import StreamingResponse
import json
import asyncio

@router.get("/campaigns/{campaign_id}/generate-bulk/stream")
async def generate_bulk_reports_stream(
    campaign_id: UUID,
    template_id: UUID = Query(..., description="ID du template à utiliser"),
    token: Optional[str] = Query(None, description="Token d'authentification"),
    current_user: User = Depends(require_permission("REPORT_READ")),
    db: Session = Depends(get_db)
):
    """
    Génère des rapports individuels pour TOUTES les entités d'une campagne
    avec progression en temps réel via Server-Sent Events (SSE).

    Cette route maintient la connexion ouverte et envoie des événements
    de progression pour chaque rapport généré.

    Événements SSE:
    - started: Début de la génération
    - entity_started: Début génération pour une entité
    - entity_progress: Progression pour une entité (étapes)
    - entity_completed: Fin génération pour une entité
    - entity_failed: Échec pour une entité
    - completed: Tous les rapports générés
    - error: Erreur globale
    """

    async def event_generator():
        """Générateur d'événements SSE."""
        try:
            # ==============================================================
            # 1. VÉRIFICATION CAMPAGNE
            # ==============================================================
            from ...models.campaign import Campaign, CampaignScope
            campaign = db.execute(
                select(Campaign).where(
                    and_(
                        Campaign.id == campaign_id,
                        Campaign.tenant_id == current_user.tenant_id
                    )
                )
            ).scalar_one_or_none()

            if not campaign:
                yield f"data: {json.dumps({'status': 'error', 'message': 'Campagne non trouvée'})}\n\n"
                return

            # ==============================================================
            # 2. RÉCUPÉRER LES ENTITÉS DU SCOPE
            # ==============================================================
            campaign_scope = None
            if campaign.scope_id:
                campaign_scope = db.execute(
                    select(CampaignScope).where(CampaignScope.id == campaign.scope_id)
                ).scalar_one_or_none()

            if not campaign_scope or not campaign_scope.entity_ids:
                yield f"data: {json.dumps({'status': 'error', 'message': 'Aucune entité dans le périmètre'})}\n\n"
                return

            entity_ids = campaign_scope.entity_ids

            # ==============================================================
            # 3. VÉRIFICATION TEMPLATE
            # ==============================================================
            template = db.execute(
                select(ReportTemplate).where(ReportTemplate.id == template_id)
            ).scalar_one_or_none()

            if not template:
                yield f"data: {json.dumps({'status': 'error', 'message': 'Template non trouvé'})}\n\n"
                return

            if template.report_scope not in ('entity', 'both'):
                yield f"data: {json.dumps({'status': 'error', 'message': f'Template incompatible (scope: {template.report_scope})'})}\n\n"
                return

            # ==============================================================
            # 4. RÉCUPÉRER LES ENTITÉS
            # ==============================================================
            from ...models.ecosystem import EcosystemEntity
            entities = db.execute(
                select(EcosystemEntity).where(EcosystemEntity.id.in_(entity_ids))
            ).scalars().all()

            if not entities:
                yield f"data: {json.dumps({'status': 'error', 'message': 'Aucune entité trouvée'})}\n\n"
                return

            total_entities = len(entities)
            logger.info(f"📋 SSE: Génération bulk pour {total_entities} entités")

            # Envoyer l'événement de démarrage
            yield f"data: {json.dumps({'status': 'started', 'total_entities': total_entities, 'entities': [{'id': str(e.id), 'name': e.name} for e in entities]})}\n\n"

            # ==============================================================
            # 5. CRÉER ET TRAITER CHAQUE RAPPORT
            # ==============================================================
            from ...services.report_job_processor import ReportJobProcessor
            processor = ReportJobProcessor(db)

            success_count = 0
            failed_count = 0
            results = []

            for idx, entity in enumerate(entities):
                entity_index = idx + 1

                # Envoyer l'événement de début pour cette entité
                yield f"data: {json.dumps({'status': 'entity_started', 'entity_index': entity_index, 'entity_id': str(entity.id), 'entity_name': entity.name, 'total_entities': total_entities})}\n\n"

                try:
                    # Créer le rapport
                    new_report = GeneratedReport(
                        tenant_id=current_user.tenant_id,
                        campaign_id=campaign_id,
                        template_id=template_id,
                        report_scope='entity',
                        entity_id=entity.id,
                        title=f"Rapport {entity.name} - {campaign.title}",
                        status=ReportStatus.PENDING.value,
                        generation_mode='draft',
                        generated_by=current_user.id,
                        report_metadata={
                            "entity_name": entity.name,
                            "bulk_generation": True
                        }
                    )
                    db.add(new_report)
                    db.flush()

                    # Créer le job
                    job = ReportGenerationJob(
                        tenant_id=current_user.tenant_id,
                        report_id=new_report.id,
                        status=JobStatus.QUEUED.value,
                        total_steps=8
                    )
                    db.add(job)
                    db.flush()
                    db.commit()

                    # Envoyer progression: collecte des données
                    yield f"data: {json.dumps({'status': 'entity_progress', 'entity_index': entity_index, 'entity_name': entity.name, 'step': 'collecting_data', 'step_label': 'Collecte des données...'})}\n\n"

                    # Traiter le job
                    logger.info(f"🔄 SSE: Traitement rapport pour {entity.name}...")
                    success = processor.process_job(job.id)

                    if success:
                        logger.info(f"✅ SSE: Rapport généré pour {entity.name}")
                        success_count += 1

                        # Récupérer le rapport mis à jour
                        db.refresh(new_report)

                        yield f"data: {json.dumps({'status': 'entity_completed', 'entity_index': entity_index, 'entity_id': str(entity.id), 'entity_name': entity.name, 'report_id': str(new_report.id), 'success': True, 'total_entities': total_entities, 'success_count': success_count, 'failed_count': failed_count})}\n\n"

                        results.append({
                            'entity_id': str(entity.id),
                            'entity_name': entity.name,
                            'report_id': str(new_report.id),
                            'success': True
                        })
                    else:
                        logger.warning(f"⚠️ SSE: Échec pour {entity.name}")
                        failed_count += 1

                        yield f"data: {json.dumps({'status': 'entity_failed', 'entity_index': entity_index, 'entity_id': str(entity.id), 'entity_name': entity.name, 'error': 'Échec de génération', 'total_entities': total_entities, 'success_count': success_count, 'failed_count': failed_count})}\n\n"

                        results.append({
                            'entity_id': str(entity.id),
                            'entity_name': entity.name,
                            'success': False,
                            'error': 'Échec de génération'
                        })

                except Exception as e:
                    logger.error(f"❌ SSE: Erreur génération {entity.name}: {str(e)}")
                    failed_count += 1
                    db.rollback()

                    yield f"data: {json.dumps({'status': 'entity_failed', 'entity_index': entity_index, 'entity_id': str(entity.id), 'entity_name': entity.name, 'error': str(e), 'total_entities': total_entities, 'success_count': success_count, 'failed_count': failed_count})}\n\n"

                    results.append({
                        'entity_id': str(entity.id),
                        'entity_name': entity.name,
                        'success': False,
                        'error': str(e)
                    })

                # Petit délai pour permettre au client de traiter
                await asyncio.sleep(0.1)

            # ==============================================================
            # 6. ENVOYER L'ÉVÉNEMENT DE FIN
            # ==============================================================
            logger.info(f"📊 SSE: Génération bulk terminée: {success_count} succès, {failed_count} échecs")

            if failed_count == 0:
                message = f"✅ {success_count} rapport(s) généré(s) avec succès"
            elif success_count == 0:
                message = f"❌ Échec de génération pour {failed_count} rapport(s)"
            else:
                message = f"⚠️ {success_count} rapport(s) généré(s), {failed_count} en échec"

            yield f"data: {json.dumps({'status': 'completed', 'success_count': success_count, 'failed_count': failed_count, 'total_entities': total_entities, 'message': message, 'results': results})}\n\n"

        except Exception as e:
            logger.error(f"❌ SSE: Erreur globale: {str(e)}", exc_info=True)
            yield f"data: {json.dumps({'status': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Désactive le buffering nginx
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Credentials": "true",
        }
    )


@router.get("/jobs/{job_id}", response_model=ReportGenerationJobResponse)
async def get_job_status(
    job_id: UUID,
    current_user: User = Depends(require_permission("REPORT_READ")),
    db: Session = Depends(get_db)
):
    """Récupère le statut d'un job de génération."""
    try:
        query = select(ReportGenerationJob).where(
            and_(
                ReportGenerationJob.id == job_id,
                ReportGenerationJob.tenant_id == current_user.tenant_id
            )
        )

        job = db.execute(query).scalar_one_or_none()

        if not job:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Job non trouvé"
            )

        return ReportGenerationJobResponse.model_validate(job)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération du job: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération du job: {str(e)}"
        )


@router.get("/campaigns/{campaign_id}/reports", response_model=GeneratedReportListResponse)
async def list_campaign_reports(
    campaign_id: UUID,
    report_scope: Optional[ReportScope] = Query(None, description="Filtrer par scope (consolidated ou entity)"),
    entity_id: Optional[UUID] = Query(None, description="Filtrer par entité (pour rapports individuels)"),
    status: Optional[ReportStatus] = Query(None, description="Filtrer par statut"),
    version: str = Query("latest", description="latest ou all"),
    current_user: User = Depends(require_permission("REPORT_READ")),
    db: Session = Depends(get_db)
):
    """
    Liste les rapports générés pour une campagne.

    Paramètres de filtrage:
    - report_scope: Filtrer par type de rapport
        - 'consolidated': Rapports multi-organismes
        - 'entity': Rapports mono-organisme
    - entity_id: Filtrer par entité (applicable uniquement si scope='entity')
    - status: Filtrer par statut du rapport
    - version: 'latest' (défaut) ou 'all' pour inclure les anciennes versions
    """
    try:
        query = select(GeneratedReport).where(
            and_(
                GeneratedReport.campaign_id == campaign_id,
                GeneratedReport.tenant_id == current_user.tenant_id
            )
        )

        # Filtre par scope
        if report_scope:
            query = query.where(GeneratedReport.report_scope == report_scope.value)

        # Filtre par entité
        if entity_id:
            query = query.where(GeneratedReport.entity_id == entity_id)

        if status:
            query = query.where(GeneratedReport.status == status.value)

        if version == "latest":
            query = query.where(GeneratedReport.is_latest == True)

        query = query.order_by(desc(GeneratedReport.created_at))

        result = db.execute(query)
        reports = result.scalars().all()

        # Enrichir avec le nom de l'entité pour les rapports individuels
        enriched_reports = []
        for r in reports:
            report_dict = GeneratedReportResponse.model_validate(r).model_dump()

            # Récupérer le nom de l'entité depuis metadata ou depuis la BDD
            if r.entity_id and r.report_metadata:
                report_dict['entity_name'] = r.report_metadata.get('entity_name')

            enriched_reports.append(GeneratedReportResponse(**report_dict))

        return GeneratedReportListResponse(
            items=enriched_reports,
            total=len(enriched_reports)
        )

    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération des rapports: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération des rapports: {str(e)}"
        )


# ============================================================================
# WIDGETS - TYPES ET CONFIGURATION
# ============================================================================

@router.get("/widgets/types", response_model=WidgetTypesResponse)
async def get_widget_types(
    current_user: User = Depends(require_permission("REPORT_READ"))
):
    """Liste tous les types de widgets disponibles, organisés par catégorie."""
    try:
        categories = [
            WidgetCategoryInfo(
                name="Structure",
                widgets=[
                    WidgetTypeInfo(type="cover", label="Page de garde", icon="file-text", category="Structure"),
                    WidgetTypeInfo(type="header", label="En-tête", icon="layout", category="Structure"),
                    WidgetTypeInfo(type="footer", label="Pied de page", icon="layout", category="Structure"),
                    WidgetTypeInfo(type="toc", label="Table des matières", icon="list", category="Structure"),
                    WidgetTypeInfo(type="page_break", label="Saut de page", icon="file-plus", category="Structure"),
                ]
            ),
            WidgetCategoryInfo(
                name="Texte",
                widgets=[
                    WidgetTypeInfo(type="title", label="Titre", icon="heading", category="Texte"),
                    WidgetTypeInfo(type="paragraph", label="Paragraphe", icon="align-left", category="Texte"),
                    WidgetTypeInfo(type="description", label="Description", icon="file-text", category="Texte"),
                ]
            ),
            WidgetCategoryInfo(
                name="Métriques",
                widgets=[
                    WidgetTypeInfo(type="metrics", label="Indicateurs", icon="bar-chart-2", category="Métriques"),
                    WidgetTypeInfo(type="score_card", label="Carte de score", icon="award", category="Métriques"),
                ]
            ),
            WidgetCategoryInfo(
                name="Graphiques",
                widgets=[
                    WidgetTypeInfo(type="radar_domains", label="Radar par domaine", icon="activity", category="Graphiques"),
                    WidgetTypeInfo(type="bar_chart", label="Graphique à barres", icon="bar-chart", category="Graphiques"),
                    WidgetTypeInfo(type="pie_chart", label="Camembert", icon="pie-chart", category="Graphiques"),
                    WidgetTypeInfo(type="gauge", label="Jauge", icon="gauge", category="Graphiques"),
                ]
            ),
            WidgetCategoryInfo(
                name="Tables",
                widgets=[
                    WidgetTypeInfo(type="actions_table", label="Table des actions", icon="list", category="Tables"),
                    WidgetTypeInfo(type="questions_table", label="Table des questions", icon="help-circle", category="Tables"),
                    WidgetTypeInfo(type="nc_table", label="Table des NC", icon="alert-triangle", category="Tables"),
                ]
            ),
        ]

        return WidgetTypesResponse(categories=categories)

    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération des types de widgets: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération des types de widgets: {str(e)}"
        )


# ============================================================================
# APERÇU HTML DES RAPPORTS
# ============================================================================

@router.get("/reports/{report_id}/preview-html")
async def preview_report_html(
    report_id: UUID,
    current_user: User = Depends(require_permission("REPORT_READ")),
    db: Session = Depends(get_db)
):
    """
    Génère et retourne l'aperçu HTML d'un rapport.

    Cette route régénère le HTML à partir des données actuelles de la campagne
    et du template associé, permettant de visualiser le rendu avant conversion PDF.

    Returns:
        HTML content du rapport
    """
    try:
        from fastapi.responses import HTMLResponse
        from ...services.report_service import ReportService
        from ...services.widget_renderer import WidgetRenderer
        from datetime import datetime, timezone

        # 1. Récupérer le rapport
        query = select(GeneratedReport).where(
            and_(
                GeneratedReport.id == report_id,
                GeneratedReport.tenant_id == current_user.tenant_id
            )
        )

        report = db.execute(query).scalar_one_or_none()

        if not report:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Rapport non trouvé"
            )

        # 2. Récupérer le template
        template = db.execute(
            select(ReportTemplate).where(ReportTemplate.id == report.template_id)
        ).scalar_one_or_none()

        if not template:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Template non trouvé"
            )

        # 3. Collecter les données selon le scope
        report_service = ReportService(db)

        if report.report_scope == ReportScope.CONSOLIDATED.value:
            data = report_service.collect_consolidated_data(report.campaign_id)

            # Normaliser les données consolidées pour compatibilité avec les widgets
            # Les widgets attendent 'stats' et 'scores', pas 'global_stats'
            global_stats = data.get('global_stats', {})
            data['stats'] = {
                'total_questions': global_stats.get('total_evaluations', 0),
                'answered_questions': global_stats.get('total_evaluations', 0),
                'compliance_rate': global_stats.get('avg_compliance_rate', 0),
                'nc_major_count': global_stats.get('nc_critical', 0),
                'nc_minor_count': global_stats.get('nc_minor', 0),
                'nc_count': global_stats.get('total_nc', 0),
                'total_domains': len(data.get('domain_comparison', [])),
                'entities_count': global_stats.get('total_entities', 0),
                'entities_audited': global_stats.get('entities_audited', 0),
                'entities_at_risk': global_stats.get('entities_at_risk', 0),
            }
            data['scores'] = {
                'global': global_stats.get('avg_compliance_rate', 0)
            }

            # Normaliser domain_scores depuis domain_comparison pour le radar
            if data.get('domain_comparison'):
                domain_scores = []
                for dc in data['domain_comparison']:
                    # Calculer la moyenne des scores par entité pour ce domaine
                    scores_by_entity = dc.get('scores_by_entity', {})
                    if scores_by_entity:
                        avg_score = sum(scores_by_entity.values()) / len(scores_by_entity)
                    else:
                        avg_score = 0
                    domain_scores.append({
                        'id': dc.get('domain_id'),
                        'name': dc.get('domain_name'),
                        'code': dc.get('domain_code'),
                        'score': round(avg_score, 1)
                    })
                data['domain_scores'] = domain_scores

            # Normaliser les NC pour le tableau
            data['nc_major'] = data.get('nc_critical_all', [])
            data['nc_minor'] = []

            # Normaliser les actions
            data['actions'] = data.get('consolidated_actions', [])

            # Récupérer les logos
            campaign = db.execute(
                select(Campaign).where(Campaign.id == report.campaign_id)
            ).scalar_one_or_none()
            if campaign:
                data['logos'] = report_service._get_logos_data(campaign.tenant_id)
                data['framework'] = report_service._get_framework_data(campaign.questionnaire_id)
        elif report.report_scope == 'scan_individual':
            # Rapport de scan individuel
            if not report.scan_id:
                raise HTTPException(
                    status_code=http_status.HTTP_400_BAD_REQUEST,
                    detail="ID du scan manquant pour un rapport de scan individuel"
                )
            data = report_service.collect_scanner_data(report.scan_id)

            # Ajouter les logos du tenant
            data['logos'] = report_service._get_logos_data(current_user.tenant_id)

        elif report.report_scope == 'scan_ecosystem':
            # Rapport écosystème scanner
            data = report_service.collect_scan_ecosystem_data(
                tenant_id=current_user.tenant_id,
                filter_entity_id=report.entity_id  # Optionnel: filtrer par entité
            )

            # Ajouter les logos du tenant
            data['logos'] = report_service._get_logos_data(current_user.tenant_id)

        else:
            # Rapport entity (campagne)
            data = report_service.collect_entity_data(
                report.campaign_id,
                report.entity_id
            )

            # Normaliser nc_count pour les widgets
            stats = data.get('stats', {})
            stats['nc_count'] = stats.get('nc_major_count', 0) + stats.get('nc_minor_count', 0)
            data['stats'] = stats

            # Normaliser scores
            if 'scores' not in data:
                data['scores'] = {'global': stats.get('compliance_rate', 0)}

        # 3b. Appliquer le logo personnalisé du template si configuré
        # (même logique que report_job_processor.py)
        logger.info(f"🔍 Preview logo check: default_logo='{template.default_logo}', custom_logo={'présent' if template.custom_logo else 'absent'}")
        if template.default_logo == 'CUSTOM' and template.custom_logo:
            if 'logos' not in data:
                data['logos'] = {}
            data['logos']['tenant_logo_url'] = template.custom_logo
            data['logos']['entity_logo_url'] = template.custom_logo
            data['logos']['organization_logo_url'] = template.custom_logo
            data['logos']['custom_logo'] = template.custom_logo
            logger.info(f"✅ Logo personnalisé appliqué pour preview (toutes sources, {len(template.custom_logo)} chars)")
        elif template.default_logo == 'PLATFORM':
            if 'logos' not in data:
                data['logos'] = {}
            data['logos']['tenant_logo_url'] = '/logo-cyberguard.png'
            logger.info(f"✅ Logo plateforme appliqué pour preview")
        elif template.default_logo == 'NONE':
            if 'logos' not in data:
                data['logos'] = {}
            data['logos']['tenant_logo_url'] = None
            logger.info(f"✅ Aucun logo configuré pour preview")

        # 4. Ajouter les métadonnées du rapport
        data['report'] = {
            'id': str(report.id),
            'title': report.title,
            'description': report.description,
            'scope': report.report_scope,
            'generated_at': datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M'),
            'mode': report.generation_mode
        }

        # 5. Préparer le renderer
        color_scheme = template.color_scheme or {
            'primary': '#8B5CF6',
            'secondary': '#3B82F6',
            'accent': '#10B981',
            'danger': '#EF4444',
            'warning': '#F59E0B',
            'success': '#22C55E',
            'text': '#1F2937',
            'background': '#FFFFFF'
        }

        fonts = template.fonts or {
            'title': {'family': 'Helvetica, Arial, sans-serif', 'size': 24, 'weight': 'bold'},
            'heading1': {'family': 'Helvetica, Arial, sans-serif', 'size': 18, 'weight': 'bold'},
            'heading2': {'family': 'Helvetica, Arial, sans-serif', 'size': 14, 'weight': 'bold'},
            'heading3': {'family': 'Helvetica, Arial, sans-serif', 'size': 12, 'weight': 'bold'},
            'body': {'family': 'Helvetica, Arial, sans-serif', 'size': 10, 'weight': 'normal'}
        }

        renderer = WidgetRenderer(color_scheme, fonts)

        # 5b. Charger les ai_contents pour les widgets IA
        # Priorité: 1) report_data.ai_contents (déjà généré), 2) reconstruire depuis ai_widget_configs

        report_data = report.report_data or {}
        report_metadata = report.report_metadata or {}
        options = report_metadata.get('options', {})
        ai_widget_configs = options.get('ai_widget_configs', [])

        # D'abord vérifier si le rapport a déjà été généré avec des ai_contents stockés
        ai_contents = report_data.get('ai_contents', {})

        if ai_contents:
            logger.info(f"📋 Preview: ai_contents chargés depuis report_data: {list(ai_contents.keys())}")
        else:
            logger.info(f"📋 Preview: {len(ai_widget_configs)} ai_widget_configs trouvés dans report_metadata")

            # Reconstruire ai_contents à partir des configs stockées
            # Format ai_widget_configs: [{widgetId, useAI, manualContent, tone, ...}, ...]
            for config in ai_widget_configs:
                widget_id = config.get('widgetId', '')
                use_ai = config.get('useAI', True)
                manual_content = config.get('manualContent', '')
                tone = config.get('tone', 'executive')

                if widget_id:
                    if not use_ai and manual_content.strip():
                        # Contenu manuel
                        ai_contents[widget_id] = {
                            'text': manual_content,
                            'source': 'manual',
                            'tone': tone
                        }
                        logger.info(f"  → Widget {widget_id[:12]}...: contenu manuel ({len(manual_content)} chars)")
                    elif use_ai:
                        # Pour l'aperçu avant génération, on affiche un placeholder
                        # Le contenu IA réel est généré uniquement lors de la génération finale
                        ai_contents[widget_id] = {
                            'text': '[Contenu IA - sera généré lors de la génération du rapport]',
                            'source': 'preview_placeholder',
                            'tone': tone
                        }
                        logger.info(f"  → Widget {widget_id[:12]}...: mode IA (placeholder pour aperçu)")

        # Ajouter ai_contents aux données pour le rendu des widgets
        data['ai_contents'] = ai_contents
        logger.info(f"📊 Preview ai_contents final: {list(ai_contents.keys())}")

        # 6. Récupérer et rendre la structure
        structure = template.structure or []
        if isinstance(structure, str):
            import json
            structure = json.loads(structure)

        # Passer la structure du template dans data pour que render_toc puisse générer la TOC
        data['_template_structure'] = structure

        widgets_html = []
        for widget in sorted(structure, key=lambda w: w.get('position', 0)):
            widget_type = widget.get('widget_type', '')
            config = widget.get('config', {}).copy()  # Copier pour ne pas modifier l'original

            # IMPORTANT: Inclure l'ID du widget dans la config pour le rendu
            # Cela permet aux widgets IA de récupérer leur contenu depuis ai_contents
            if widget.get('id'):
                config['id'] = widget.get('id')

            try:
                html = renderer.render_widget(widget_type, config, data)
                widgets_html.append(html)
            except Exception as e:
                logger.warning(f"Erreur rendu widget {widget_type}: {e}")
                widgets_html.append(f"<!-- Erreur widget {widget_type}: {e} -->")

        # 7. Assembler le HTML final
        primary_color = color_scheme.get('primary', '#8B5CF6')

        html_content = f"""
        <!DOCTYPE html>
        <html lang="fr">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{report.title}</title>
            <style>
                * {{
                    box-sizing: border-box;
                }}
                body {{
                    font-family: {fonts['body']['family']};
                    font-size: {fonts['body']['size']}px;
                    line-height: 1.6;
                    color: {color_scheme.get('text', '#1F2937')};
                    background-color: #f5f5f5;
                    margin: 0;
                    padding: 20px;
                }}
                .report-container {{
                    max-width: 210mm;
                    margin: 0 auto;
                    background: white;
                    box-shadow: 0 4px 20px rgba(0,0,0,0.15);
                    padding: 30px;
                    border-radius: 8px;
                }}
                h1, h2, h3 {{
                    color: {primary_color};
                }}
                table {{
                    width: 100%;
                    border-collapse: collapse;
                    margin: 15px 0;
                }}
                th, td {{
                    padding: 10px;
                    border: 1px solid #e5e7eb;
                    text-align: left;
                }}
                th {{
                    background-color: {primary_color};
                    color: white;
                }}
                .page-break {{
                    border-top: 2px dashed #ccc;
                    margin: 30px 0;
                    padding-top: 10px;
                }}
                .page-break::before {{
                    content: "--- Saut de page ---";
                    display: block;
                    text-align: center;
                    color: #999;
                    font-size: 12px;
                    margin-bottom: 20px;
                }}
                @media print {{
                    body {{
                        background: white;
                        padding: 0;
                    }}
                    .report-container {{
                        box-shadow: none;
                        max-width: 100%;
                        padding: 20px;
                    }}
                    .page-break {{
                        page-break-before: always;
                        border: none;
                        margin: 0;
                        padding: 0;
                    }}
                    .page-break::before {{
                        display: none;
                    }}
                }}
            </style>
        </head>
        <body>
            <div class="report-container">
                {''.join(widgets_html)}
            </div>
        </body>
        </html>
        """

        logger.info(f"📄 Aperçu HTML généré pour rapport {report_id}")

        return HTMLResponse(content=html_content, status_code=200)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur génération aperçu HTML: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la génération de l'aperçu: {str(e)}"
        )


# ============================================================================
# TÉLÉCHARGEMENT DE RAPPORTS
# ============================================================================

@router.get("/reports/{report_id}/download")
async def download_report(
    report_id: UUID,
    inline: bool = False,
    current_user: User = Depends(require_permission("REPORT_READ")),
    db: Session = Depends(get_db)
):
    """
    Télécharge ou affiche un rapport PDF généré.

    Args:
        inline: Si True, affiche le PDF dans le navigateur (pour aperçu).
                Si False (défaut), force le téléchargement.

    Supporte les fichiers stockés :
    - Localement (chemin absolu)
    - Dans MinIO (chemin relatif tenant/campaign/reports/...)

    Permissions :
    - User doit appartenir au tenant du rapport
    - Ou être affecté à la campagne du rapport
    """
    try:
        from fastapi.responses import FileResponse, StreamingResponse
        from pathlib import Path
        from io import BytesIO

        # Récupérer le rapport
        query = select(GeneratedReport).where(
            and_(
                GeneratedReport.id == report_id,
                GeneratedReport.tenant_id == current_user.tenant_id
            )
        )

        report = db.execute(query).scalar_one_or_none()

        if not report:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Rapport non trouvé"
            )

        # Vérifier que le fichier existe
        if not report.file_path:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Fichier PDF non disponible"
            )

        # Incrémenter le compteur de téléchargements
        from datetime import datetime, timezone
        report.downloaded_count = (report.downloaded_count or 0) + 1
        report.last_downloaded_at = datetime.now(timezone.utc)
        db.commit()

        # Déterminer le type MIME
        file_name = report.file_name or f"report_{report_id}.pdf"
        media_type = report.file_mime_type or "application/pdf"
        if file_name.endswith('.html'):
            media_type = "text/html"

        # Vérifier si c'est un chemin MinIO ou local
        file_path = Path(report.file_path)

        # Déterminer le Content-Disposition selon le mode
        content_disposition = "inline" if inline else "attachment"

        # PRIORITÉ 1: Vérifier d'abord si le fichier local backup existe
        # Les fichiers sont toujours sauvegardés localement en backup
        project_root = Path(__file__).resolve().parent.parent.parent.parent
        backup_filename = report.file_name or Path(report.file_path).name
        local_backup_path = project_root / "storage" / "reports" / backup_filename

        logger.info(f"🔍 Recherche fichier backup: {local_backup_path}")
        logger.info(f"🔍 project_root={project_root}, backup_filename={backup_filename}")

        if local_backup_path.exists():
            # Vérifier que le fichier n'est pas vide
            file_size = local_backup_path.stat().st_size
            logger.info(f"📁 Fichier backup trouvé: {local_backup_path} ({file_size} bytes)")

            if file_size == 0:
                logger.warning(f"⚠️ Fichier backup vide, passage au fallback MinIO")
            else:
                # Fichier local backup disponible - le préférer car toujours fiable
                logger.info(f"📥 {'Aperçu' if inline else 'Téléchargement'} rapport local (backup): {local_backup_path}")
                return FileResponse(
                    path=str(local_backup_path),
                    media_type=media_type,
                    filename=file_name if not inline else None,
                    headers={
                        "Content-Disposition": f'{content_disposition}; filename="{file_name}"'
                    }
                )

        else:
            logger.warning(f"⚠️ Fichier backup non trouvé: {local_backup_path}")

        # PRIORITÉ 2: Chemin absolu dans file_path
        if file_path.is_absolute() and file_path.exists():
            # Fichier local avec chemin absolu
            logger.info(f"📥 {'Aperçu' if inline else 'Téléchargement'} rapport local: {file_path}")
            return FileResponse(
                path=str(file_path),
                media_type=media_type,
                filename=file_name if not inline else None,
                headers={
                    "Content-Disposition": f'{content_disposition}; filename="{file_name}"'
                }
            )

        # PRIORITÉ 3: Fichier dans MinIO (fallback)
        try:
            from ...services.file_storage_service import FileStorageService

            storage = FileStorageService()
            response = storage.download_file_ged(
                object_path=report.file_path,
                tenant_id=current_user.tenant_id
            )

            # Lire le contenu
            file_content = response.read()
            response.close()
            response.release_conn()

            logger.info(f"📥 {'Aperçu' if inline else 'Téléchargement'} rapport MinIO: {report.file_path} ({len(file_content)} bytes)")

            return StreamingResponse(
                BytesIO(file_content),
                media_type=media_type,
                headers={
                    "Content-Disposition": f'{content_disposition}; filename="{file_name}"',
                    "Content-Length": str(len(file_content))
                }
            )

        except Exception as minio_error:
            logger.error(f"❌ Erreur téléchargement MinIO: {minio_error}")
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Fichier PDF introuvable (ni local ni MinIO: {minio_error})"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur lors du téléchargement: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors du téléchargement: {str(e)}"
        )


@router.get("/reports/{report_id}")
async def get_report(
    report_id: UUID,
    current_user: User = Depends(require_permission("REPORT_READ")),
    db: Session = Depends(get_db)
):
    """Récupère les détails d'un rapport généré."""
    try:
        from ...schemas.report import GeneratedReportResponse

        query = select(GeneratedReport).where(
            and_(
                GeneratedReport.id == report_id,
                GeneratedReport.tenant_id == current_user.tenant_id
            )
        )

        report = db.execute(query).scalar_one_or_none()

        if not report:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Rapport non trouvé"
            )

        return GeneratedReportResponse.model_validate(report)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération du rapport: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération du rapport: {str(e)}"
        )


@router.delete("/reports/{report_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_report(
    report_id: UUID,
    current_user: User = Depends(require_permission("REPORT_READ")),
    db: Session = Depends(get_db)
):
    """
    Supprime un rapport généré et ses fichiers associés.

    Cette opération supprime :
    - Le rapport de la base de données
    - Le job de génération associé
    - Le fichier PDF/HTML stocké (local ou MinIO)

    Permissions :
    - User doit appartenir au tenant du rapport
    """
    try:
        from pathlib import Path

        # Récupérer le rapport
        query = select(GeneratedReport).where(
            and_(
                GeneratedReport.id == report_id,
                GeneratedReport.tenant_id == current_user.tenant_id
            )
        )

        report = db.execute(query).scalar_one_or_none()

        if not report:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Rapport non trouvé"
            )

        # 1. Supprimer le fichier si existant
        if report.file_path:
            file_path = Path(report.file_path)

            # Vérifier si c'est un fichier local
            if file_path.is_absolute() and file_path.exists():
                try:
                    file_path.unlink()
                    logger.info(f"🗑️ Fichier local supprimé: {file_path}")
                except Exception as e:
                    logger.warning(f"⚠️ Impossible de supprimer le fichier local: {e}")
            else:
                # Fichier dans MinIO
                try:
                    from ...services.file_storage_service import FileStorageService

                    storage = FileStorageService()
                    storage.delete_file(
                        object_path=report.file_path,
                        tenant_id=current_user.tenant_id
                    )
                    logger.info(f"🗑️ Fichier MinIO supprimé: {report.file_path}")
                except Exception as e:
                    logger.warning(f"⚠️ Impossible de supprimer le fichier MinIO: {e}")

            # Supprimer aussi le backup local éventuel
            backup_path = Path("storage/reports") / Path(report.file_path).name
            if backup_path.exists():
                try:
                    backup_path.unlink()
                    logger.info(f"🗑️ Fichier backup supprimé: {backup_path}")
                except Exception as e:
                    logger.warning(f"⚠️ Impossible de supprimer le backup: {e}")

        # 2. Supprimer les jobs associés
        jobs_query = select(ReportGenerationJob).where(
            ReportGenerationJob.report_id == report_id
        )
        jobs = db.execute(jobs_query).scalars().all()

        for job in jobs:
            db.delete(job)
            logger.info(f"🗑️ Job supprimé: {job.id}")

        # 3. Supprimer le rapport
        db.delete(report)
        db.commit()

        logger.info(f"✅ Rapport supprimé: {report_id}")

        return None

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur lors de la suppression du rapport: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la suppression du rapport: {str(e)}"
        )


# ============================================================================
# RAPPORTS SCANNER
# ============================================================================

# IMPORTANT: L'endpoint /scans/ecosystem/generate DOIT être défini AVANT /scans/{scan_id}/generate
# car FastAPI matche les routes dans l'ordre de définition et {scan_id} pourrait capturer "ecosystem"


@router.post("/scans/ecosystem/generate", response_model=GenerateReportResponse, status_code=http_status.HTTP_202_ACCEPTED)
async def generate_scan_ecosystem_report(
    request: GenerateScanReportRequest,
    entity_id: Optional[UUID] = Query(None, description="Filtrer par entité (optionnel)"),
    current_user: User = Depends(require_permission("REPORT_READ")),
    db: Session = Depends(get_db)
):
    """
    Génère un rapport écosystème pour tous les scans.

    Ce rapport inclut :
    - Synthèse globale de l'écosystème
    - Graphique de positionnement (toutes les entités)
    - Top vulnérabilités par sévérité
    - Comparaison des entités
    - Tendances de sécurité
    - Distribution des grades
    - Statistiques globales (CVSS moyen, CVE totaux, etc.)

    Args:
        request: Configuration du rapport (template, titre, options)
        entity_id: UUID de l'entité pour filtrer (optionnel)

    Returns:
        job_id et report_id pour suivre la génération
    """
    try:
        # DEBUG: Log de la requête reçue
        logger.info(f"🔍 generate_scan_ecosystem_report - Requête reçue:")
        logger.info(f"   template_id: {request.template_id}")
        logger.info(f"   title: {request.title}")
        logger.info(f"   report_scope: {request.report_scope}")
        logger.info(f"   options: {request.options}")

        # Forcer le scope
        request.report_scope = ReportScope.SCAN_ECOSYSTEM

        # ==============================================================
        # 1. VÉRIFICATION TEMPLATE
        # ==============================================================
        template = db.execute(
            select(ReportTemplate).where(ReportTemplate.id == request.template_id)
        ).scalar_one_or_none()

        if not template:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Template non trouvé"
            )

        # Vérifier compatibilité
        template_scope = template.report_scope
        if template_scope not in ['scan_ecosystem', 'scan_both']:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=f"Le template '{template.name}' n'est pas compatible avec les rapports écosystème scanner (scope: {template_scope})"
            )

        # ==============================================================
        # 2. CRÉATION DU RAPPORT
        # ==============================================================
        entity_name = None
        if entity_id:
            from ...models.ecosystem import EcosystemEntity
            entity = db.execute(
                select(EcosystemEntity).where(EcosystemEntity.id == entity_id)
            ).scalar_one_or_none()
            entity_name = entity.name if entity else None

        # Titre par défaut si non fourni
        default_title = f"Rapport Écosystème Scanner - {datetime.now().strftime('%d/%m/%Y')}"

        new_report = GeneratedReport(
            tenant_id=current_user.tenant_id,
            template_id=request.template_id,
            report_scope=ReportScope.SCAN_ECOSYSTEM.value,
            entity_id=entity_id,
            title=request.title or default_title,
            description=None,
            status=ReportStatus.PENDING.value,
            generation_mode=request.options.get('force_mode', 'final') if request.options else 'final',
            generated_by=current_user.id,
            report_metadata={
                "entity_id": str(entity_id) if entity_id else None,
                "entity_name": entity_name,
                "filter_entity": entity_id is not None,
                "options": request.options
            }
        )

        db.add(new_report)
        db.flush()

        # ==============================================================
        # 3. CRÉATION DU JOB
        # ==============================================================
        job = ReportGenerationJob(
            tenant_id=current_user.tenant_id,
            report_id=new_report.id,
            status=JobStatus.QUEUED.value,
            total_steps=8
        )

        db.add(job)
        db.commit()

        filter_msg = f" (filtré par {entity_name})" if entity_id else ""
        logger.info(f"🌐 Génération rapport écosystème scanner démarrée - Job: {job.id}{filter_msg}")

        # ==============================================================
        # 4. TRAITEMENT DU JOB
        # ==============================================================
        try:
            from ...services.report_job_processor import ReportJobProcessor

            processor = ReportJobProcessor(db)
            success = processor.process_job(job.id)

            if success:
                logger.info(f"✅ Rapport écosystème scanner généré - Job: {job.id}")
                db.refresh(job)
            else:
                logger.warning(f"⚠️ Échec génération rapport écosystème - Job: {job.id}")

        except Exception as e:
            logger.error(f"❌ Erreur génération rapport écosystème: {str(e)}", exc_info=True)

        return GenerateReportResponse(
            job_id=job.id,
            report_id=new_report.id,
            status=JobStatus(job.status) if job.status else JobStatus.QUEUED,
            estimated_time_seconds=0 if job.status == JobStatus.COMPLETED.value else 45
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur démarrage génération écosystème: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors du démarrage de la génération: {str(e)}"
        )


@router.post("/scans/{scan_id}/generate", response_model=GenerateReportResponse, status_code=http_status.HTTP_202_ACCEPTED)
async def generate_scan_report(
    scan_id: UUID,
    request: GenerateReportRequest,
    current_user: User = Depends(require_permission("REPORT_READ")),
    db: Session = Depends(get_db)
):
    """
    Génère un rapport pour un scan individuel.

    Ce rapport inclut :
    - Score d'exposition et niveau de risque
    - Analyse TLS/SSL
    - Vulnérabilités détectées
    - Services exposés
    - Historique des scans
    - Graphique de positionnement (l'entité positionnée par rapport aux autres)
    - Recommandations

    Args:
        scan_id: UUID du scan à rapporter
        request: Configuration du rapport (template, titre, options)

    Returns:
        job_id et report_id pour suivre la génération
    """
    try:
        from ...models.external_scan import ExternalScan, ExternalTarget

        # ==============================================================
        # 1. VALIDATION
        # ==============================================================
        # Forcer le scope à scan_individual
        if request.report_scope not in [ReportScope.SCAN_INDIVIDUAL, ReportScope.SCAN_ECOSYSTEM]:
            request.report_scope = ReportScope.SCAN_INDIVIDUAL

        # Vérifier scan_id est fourni
        if not scan_id:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="scan_id est requis"
            )

        # ==============================================================
        # 2. VÉRIFICATION DU SCAN
        # ==============================================================
        scan_query = select(ExternalScan).where(
            and_(
                ExternalScan.id == scan_id,
                ExternalScan.tenant_id == current_user.tenant_id
            )
        )
        scan = db.execute(scan_query).scalar_one_or_none()

        if not scan:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Scan non trouvé"
            )

        # Récupérer la cible du scan
        target = db.execute(
            select(ExternalTarget).where(ExternalTarget.id == scan.external_target_id)
        ).scalar_one_or_none()

        target_value = target.value if target else "Cible inconnue"
        entity_id = target.entity_id if target else None
        entity_name = None

        # Récupérer le nom de l'entité si disponible
        if entity_id:
            from ...models.ecosystem import EcosystemEntity
            entity = db.execute(
                select(EcosystemEntity).where(EcosystemEntity.id == entity_id)
            ).scalar_one_or_none()
            entity_name = entity.name if entity else None

        # ==============================================================
        # 3. VÉRIFICATION TEMPLATE
        # ==============================================================
        template = db.execute(
            select(ReportTemplate).where(ReportTemplate.id == request.template_id)
        ).scalar_one_or_none()

        if not template:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Template non trouvé"
            )

        # Vérifier compatibilité du template avec le scope scanner
        template_scope = template.report_scope
        if template_scope not in ['scan_individual', 'scan_both']:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=f"Le template '{template.name}' n'est pas compatible avec les rapports de scan individuel (scope: {template_scope})"
            )

        # ==============================================================
        # 4. CRÉATION DU RAPPORT
        # ==============================================================
        new_report = GeneratedReport(
            tenant_id=current_user.tenant_id,
            scan_id=scan_id,
            template_id=request.template_id,
            report_scope=ReportScope.SCAN_INDIVIDUAL.value,
            entity_id=entity_id,
            title=request.title or f"Rapport Scan - {target_value}",
            description=request.description,
            status=ReportStatus.PENDING.value,
            generation_mode=request.options.get('force_mode', 'final') if request.options else 'final',
            generated_by=current_user.id,
            report_metadata={
                "scan_id": str(scan_id),
                "target_value": target_value,
                "entity_id": str(entity_id) if entity_id else None,
                "entity_name": entity_name,
                "exposure_score": scan.summary.get('exposure_score') if scan.summary else None,
                "risk_level": scan.summary.get('risk_level') if scan.summary else None,
                "options": request.options
            }
        )

        db.add(new_report)
        db.flush()

        # ==============================================================
        # 5. CRÉATION DU JOB DE GÉNÉRATION
        # ==============================================================
        job = ReportGenerationJob(
            tenant_id=current_user.tenant_id,
            report_id=new_report.id,
            status=JobStatus.QUEUED.value,
            total_steps=7  # Étapes spécifiques scan
        )

        db.add(job)
        db.commit()

        logger.info(f"📡 Génération rapport scan démarrée - Job: {job.id}, Scan: {scan_id}, Target: {target_value}")

        # ==============================================================
        # 6. TRAITEMENT DU JOB
        # ==============================================================
        try:
            from ...services.report_job_processor import ReportJobProcessor

            processor = ReportJobProcessor(db)
            success = processor.process_job(job.id)

            if success:
                logger.info(f"✅ Rapport scan généré avec succès - Job: {job.id}")
                db.refresh(job)
            else:
                logger.warning(f"⚠️ Échec génération rapport scan - Job: {job.id}")

        except Exception as e:
            logger.error(f"❌ Erreur lors de la génération du rapport scan: {str(e)}", exc_info=True)

        return GenerateReportResponse(
            job_id=job.id,
            report_id=new_report.id,
            status=JobStatus(job.status) if job.status else JobStatus.QUEUED,
            estimated_time_seconds=0 if job.status == JobStatus.COMPLETED.value else 30
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur lors du démarrage de la génération scan: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors du démarrage de la génération: {str(e)}"
        )


# IMPORTANT: /scans/ecosystem/reports DOIT être défini AVANT /scans/{scan_id}/reports
# pour éviter que FastAPI interprète "ecosystem" comme un scan_id

@router.get("/scans/ecosystem/reports", response_model=GeneratedReportListResponse)
async def list_scan_ecosystem_reports(
    status: Optional[ReportStatus] = Query(None, description="Filtrer par statut"),
    current_user: User = Depends(require_permission("REPORT_READ")),
    db: Session = Depends(get_db)
):
    """
    Liste les rapports écosystème scanner générés.
    """
    try:
        query = select(GeneratedReport).where(
            and_(
                GeneratedReport.report_scope == ReportScope.SCAN_ECOSYSTEM.value,
                GeneratedReport.tenant_id == current_user.tenant_id
            )
        )

        if status:
            query = query.where(GeneratedReport.status == status.value)

        query = query.order_by(desc(GeneratedReport.created_at))

        reports = db.execute(query).scalars().all()

        return GeneratedReportListResponse(
            items=[GeneratedReportResponse.model_validate(r) for r in reports],
            total=len(reports)
        )

    except Exception as e:
        logger.error(f"❌ Erreur liste rapports écosystème: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération des rapports: {str(e)}"
        )


@router.get("/scans/{scan_id}/reports", response_model=GeneratedReportListResponse)
async def list_scan_reports(
    scan_id: UUID,
    status: Optional[ReportStatus] = Query(None, description="Filtrer par statut"),
    current_user: User = Depends(require_permission("REPORT_READ")),
    db: Session = Depends(get_db)
):
    """
    Liste les rapports générés pour un scan spécifique.
    """
    try:
        query = select(GeneratedReport).where(
            and_(
                GeneratedReport.scan_id == scan_id,
                GeneratedReport.tenant_id == current_user.tenant_id
            )
        )

        if status:
            query = query.where(GeneratedReport.status == status.value)

        query = query.order_by(desc(GeneratedReport.created_at))

        reports = db.execute(query).scalars().all()

        return GeneratedReportListResponse(
            items=[GeneratedReportResponse.model_validate(r) for r in reports],
            total=len(reports)
        )

    except Exception as e:
        logger.error(f"❌ Erreur liste rapports scan: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération des rapports: {str(e)}"
        )
