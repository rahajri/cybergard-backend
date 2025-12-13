"""
Service pour la gestion des templates de rapports.

Inclut la duplication automatique des templates système
lors de la création d'un nouveau tenant.
"""

from uuid import UUID, uuid4
from datetime import datetime, timezone
from typing import List, Optional
import logging
import json

from sqlalchemy import select, text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# Codes des templates à dupliquer automatiquement pour chaque nouveau client
# Campagne templates
DEFAULT_TEMPLATES_TO_DUPLICATE = [
    "SYSTEM_CONSOLIDATED",
    "SYSTEM_INDIVIDUAL"
]

# Scanner templates - à dupliquer séparément
SCANNER_TEMPLATES_TO_DUPLICATE = [
    "SYSTEM_SCAN_INDIVIDUAL",
    "SYSTEM_SCAN_ECOSYSTEM"
]

# EBIOS RM templates - pour les rapports d'analyse de risques ANSSI
EBIOS_TEMPLATES_TO_DUPLICATE = [
    "SYSTEM_EBIOS_CONSOLIDATED",
    "SYSTEM_EBIOS_INDIVIDUAL"
]

# Tous les templates à dupliquer
ALL_TEMPLATES_TO_DUPLICATE = (
    DEFAULT_TEMPLATES_TO_DUPLICATE +
    SCANNER_TEMPLATES_TO_DUPLICATE +
    EBIOS_TEMPLATES_TO_DUPLICATE
)


def duplicate_default_templates_for_tenant(
    db: Session,
    tenant_id: UUID,
    tenant_name: str,
    include_scanner: bool = True,
    include_ebios: bool = True
) -> List[dict]:
    """
    Duplique les templates système par défaut pour un nouveau tenant.

    Cette fonction est appelée automatiquement lors de la création
    d'un nouveau client (tenant) pour lui fournir ses propres copies
    des templates Consolidé, Individuel, Scanner et EBIOS RM qu'il pourra personnaliser.

    Args:
        db: Session SQLAlchemy
        tenant_id: ID du nouveau tenant
        tenant_name: Nom du tenant (pour nommer les templates)
        include_scanner: Inclure les templates Scanner (défaut: True)
        include_ebios: Inclure les templates EBIOS RM ANSSI (défaut: True)

    Returns:
        Liste des templates créés avec leurs infos
    """

    created_templates = []

    # Déterminer quels templates dupliquer
    templates_to_duplicate = list(DEFAULT_TEMPLATES_TO_DUPLICATE)
    if include_scanner:
        templates_to_duplicate.extend(SCANNER_TEMPLATES_TO_DUPLICATE)
    if include_ebios:
        templates_to_duplicate.extend(EBIOS_TEMPLATES_TO_DUPLICATE)

    try:
        # Récupérer les templates système à dupliquer
        query = text("""
            SELECT
                id, name, description, code, template_type, report_scope,
                page_size, orientation, margins, color_scheme, fonts,
                custom_css, default_logo, structure
            FROM report_template
            WHERE code IN :codes
              AND is_system = true
              AND tenant_id IS NULL
        """)

        result = db.execute(query, {"codes": tuple(templates_to_duplicate)})
        system_templates = result.fetchall()

        if not system_templates:
            logger.warning(f"[TEMPLATE] Aucun template système trouvé pour duplication. Codes recherchés: {templates_to_duplicate}")
            return []

        logger.info(f"[TEMPLATE] Duplication de {len(system_templates)} templates pour tenant '{tenant_name}' ({tenant_id})")

        for template in system_templates:
            # Générer le nouveau nom avec le nom du tenant
            original_name = template[1]  # name
            original_code = template[3]  # code

            # Nouveau nom : "Rapport Consolidé Écosystème : AHAJRI"
            new_name = f"{original_name} : {tenant_name}"

            # Nouveau code : "TENANT_{tenant_id}_{original_code}"
            new_code = f"TENANT_{str(tenant_id)[:8]}_{original_code.replace('SYSTEM_', '')}"

            new_id = uuid4()
            now = datetime.now(timezone.utc)

            # Insérer la copie
            insert_query = text("""
                INSERT INTO report_template (
                    id, tenant_id, name, description, code, template_type,
                    report_scope, is_system, is_default, page_size, orientation,
                    margins, color_scheme, fonts, custom_css, default_logo,
                    structure, created_at, updated_at
                ) VALUES (
                    :id, :tenant_id, :name, :description, :code, :template_type,
                    :report_scope, :is_system, :is_default, :page_size, :orientation,
                    :margins, :color_scheme, :fonts, :custom_css, :default_logo,
                    :structure, :created_at, :updated_at
                )
            """)

            db.execute(insert_query, {
                "id": new_id,
                "tenant_id": tenant_id,
                "name": new_name,
                "description": template[2],  # description
                "code": new_code,
                "template_type": template[4],  # template_type
                "report_scope": template[5],  # report_scope
                "is_system": False,  # Ce n'est plus un template système
                "is_default": True,  # C'est le template par défaut du tenant
                "page_size": template[6],  # page_size
                "orientation": template[7],  # orientation
                "margins": template[8],  # margins (déjà JSONB)
                "color_scheme": template[9],  # color_scheme (déjà JSONB)
                "fonts": template[10],  # fonts (déjà JSONB)
                "custom_css": template[11],  # custom_css
                "default_logo": template[12],  # default_logo
                "structure": template[13],  # structure (déjà JSONB)
                "created_at": now,
                "updated_at": now
            })

            created_templates.append({
                "id": str(new_id),
                "name": new_name,
                "code": new_code,
                "report_scope": template[5],
                "source_template": original_code
            })

            logger.info(f"[TEMPLATE] ✓ Créé: {new_name} (scope: {template[5]})")

        # Ne pas commit ici - laisser l'appelant gérer la transaction
        logger.info(f"[TEMPLATE] {len(created_templates)} templates dupliqués pour '{tenant_name}'")

        return created_templates

    except Exception as e:
        logger.error(f"[TEMPLATE] Erreur lors de la duplication: {str(e)}")
        raise


def share_template_with_tenant(
    db: Session,
    template_id: UUID,
    target_tenant_id: UUID,
    target_tenant_name: str
) -> dict:
    """
    Partage un template système avec un tenant spécifique.

    Crée une copie du template pour le tenant cible,
    similaire au partage de questionnaires.

    Args:
        db: Session SQLAlchemy
        template_id: ID du template à partager
        target_tenant_id: ID du tenant destinataire
        target_tenant_name: Nom du tenant (pour nommer le template)

    Returns:
        Infos du template créé
    """

    # Récupérer le template source
    query = text("""
        SELECT
            id, name, description, code, template_type, report_scope,
            page_size, orientation, margins, color_scheme, fonts,
            custom_css, default_logo, structure, is_system
        FROM report_template
        WHERE id = :template_id
    """)

    result = db.execute(query, {"template_id": template_id})
    source_template = result.fetchone()

    if not source_template:
        raise ValueError(f"Template {template_id} non trouvé")

    # Vérifier que ce n'est pas déjà un template du tenant cible
    if source_template[14]:  # is_system
        # OK, on peut partager un template système
        pass
    else:
        raise ValueError("Seuls les templates système peuvent être partagés")

    original_name = source_template[1]
    original_code = source_template[3]

    # Nouveau nom avec le tenant
    new_name = f"{original_name} : {target_tenant_name}"
    new_code = f"SHARED_{str(target_tenant_id)[:8]}_{original_code.replace('SYSTEM_', '')}"

    new_id = uuid4()
    now = datetime.now(timezone.utc)

    insert_query = text("""
        INSERT INTO report_template (
            id, tenant_id, name, description, code, template_type,
            report_scope, is_system, is_default, page_size, orientation,
            margins, color_scheme, fonts, custom_css, default_logo,
            structure, created_at, updated_at
        ) VALUES (
            :id, :tenant_id, :name, :description, :code, :template_type,
            :report_scope, :is_system, :is_default, :page_size, :orientation,
            :margins, :color_scheme, :fonts, :custom_css, :default_logo,
            :structure, :created_at, :updated_at
        )
    """)

    db.execute(insert_query, {
        "id": new_id,
        "tenant_id": target_tenant_id,
        "name": new_name,
        "description": source_template[2],
        "code": new_code,
        "template_type": source_template[4],
        "report_scope": source_template[5],
        "is_system": False,
        "is_default": False,  # Pas par défaut pour un partage
        "page_size": source_template[6],
        "orientation": source_template[7],
        "margins": source_template[8],
        "color_scheme": source_template[9],
        "fonts": source_template[10],
        "custom_css": source_template[11],
        "default_logo": source_template[12],
        "structure": source_template[13],
        "created_at": now,
        "updated_at": now
    })

    logger.info(f"[TEMPLATE] Template partagé: {new_name} -> tenant {target_tenant_id}")

    return {
        "id": str(new_id),
        "name": new_name,
        "code": new_code,
        "report_scope": source_template[5],
        "source_template_id": str(template_id)
    }


def get_tenant_templates(
    db: Session,
    tenant_id: UUID,
    include_system: bool = True
) -> List[dict]:
    """
    Récupère tous les templates disponibles pour un tenant.

    Args:
        db: Session SQLAlchemy
        tenant_id: ID du tenant
        include_system: Inclure les templates système partageables

    Returns:
        Liste des templates avec leurs infos
    """

    if include_system:
        # Templates du tenant + templates système
        query = text("""
            SELECT
                id, name, description, code, template_type, report_scope,
                is_system, is_default, tenant_id
            FROM report_template
            WHERE (tenant_id = :tenant_id OR (is_system = true AND tenant_id IS NULL))
              AND deleted_at IS NULL
            ORDER BY
                CASE WHEN tenant_id = :tenant_id THEN 0 ELSE 1 END,
                is_default DESC,
                name
        """)
    else:
        # Uniquement les templates du tenant
        query = text("""
            SELECT
                id, name, description, code, template_type, report_scope,
                is_system, is_default, tenant_id
            FROM report_template
            WHERE tenant_id = :tenant_id
              AND deleted_at IS NULL
            ORDER BY is_default DESC, name
        """)

    result = db.execute(query, {"tenant_id": tenant_id})
    templates = result.fetchall()

    return [
        {
            "id": str(t[0]),
            "name": t[1],
            "description": t[2],
            "code": t[3],
            "template_type": t[4],
            "report_scope": t[5],
            "is_system": t[6],
            "is_default": t[7],
            "is_own": t[8] == tenant_id
        }
        for t in templates
    ]
