"""
Script pour dupliquer les templates EBIOS RM pour tous les tenants existants.

Ce script crée les copies personnalisables des templates
SYSTEM_EBIOS_CONSOLIDATED et SYSTEM_EBIOS_INDIVIDUAL pour chaque client existant.

Usage (depuis le dossier backend):
    python duplicate_ebios_templates_for_tenants.py
"""

import sys
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4
import json

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import text
from src.database import SessionLocal


def duplicate_ebios_templates_for_all_tenants():
    """Duplique les templates EBIOS RM pour tous les tenants existants."""

    print("=" * 70)
    print("DUPLICATION DES TEMPLATES EBIOS RM POUR TOUS LES TENANTS")
    print("=" * 70)
    print()

    db = SessionLocal()
    try:
        # 1. Récupérer les templates EBIOS système à dupliquer
        templates_query = text("""
            SELECT
                id, name, description, code, template_type, report_scope,
                page_size, orientation, margins, color_scheme, fonts,
                custom_css, default_logo, structure, template_category
            FROM report_template
            WHERE code IN ('SYSTEM_EBIOS_CONSOLIDATED', 'SYSTEM_EBIOS_INDIVIDUAL')
              AND is_system = true
              AND tenant_id IS NULL
        """)

        system_templates = db.execute(templates_query).fetchall()

        if not system_templates:
            print("[ERROR] Aucun template EBIOS systeme trouve!")
            print("        Executez d'abord: python insert_ebios_template.py")
            return

        print(f"[OK] {len(system_templates)} templates EBIOS systeme trouves:")
        for t in system_templates:
            print(f"     - {t[3]}: {t[1]} (scope: {t[5]})")
        print()

        # 2. Récupérer tous les tenants actifs
        tenants_query = text("""
            SELECT id, name
            FROM tenant
            WHERE is_active = true
            ORDER BY name
        """)

        tenants = db.execute(tenants_query).fetchall()

        if not tenants:
            print("[WARN] Aucun tenant actif trouve.")
            return

        print(f"[OK] {len(tenants)} tenants actifs trouves")
        print()

        # 3. Pour chaque tenant, vérifier et créer les templates manquants
        total_created = 0

        for tenant in tenants:
            tenant_id = tenant[0]
            tenant_name = tenant[1]

            print(f"--- Tenant: {tenant_name} ({str(tenant_id)[:8]}...) ---")

            # Vérifier les templates EBIOS existants pour ce tenant
            existing_query = text("""
                SELECT code FROM report_template
                WHERE tenant_id = :tenant_id
                  AND code LIKE 'TENANT_%_EBIOS_%'
            """)
            existing = db.execute(existing_query, {"tenant_id": tenant_id}).fetchall()
            existing_codes = [e[0] for e in existing]

            templates_created = 0

            for template in system_templates:
                parent_template_id = template[0]  # ID du template système (parent)
                original_code = template[3]  # code (ex: SYSTEM_EBIOS_CONSOLIDATED)
                base_code = original_code.replace('SYSTEM_', '')  # EBIOS_CONSOLIDATED
                template_category = template[14] if len(template) > 14 else 'ebios'  # Catégorie (ebios par défaut)

                # Code pour le tenant
                tenant_code = f"TENANT_{str(tenant_id)[:8]}_{base_code}"

                # Vérifier si déjà existant
                if tenant_code in existing_codes:
                    print(f"     [SKIP] {base_code} - deja existant")
                    continue

                # Créer le template pour ce tenant
                new_id = uuid4()
                new_name = f"{template[1]} - {tenant_name}"  # Ex: "Rapport EBIOS RM Consolidé - AHAJRI"
                now = datetime.now(timezone.utc)

                # Convertir les dicts en JSON strings pour PostgreSQL
                margins_json = json.dumps(template[8]) if isinstance(template[8], dict) else template[8]
                color_scheme_json = json.dumps(template[9]) if isinstance(template[9], dict) else template[9]
                fonts_json = json.dumps(template[10]) if isinstance(template[10], dict) else template[10]
                structure_json = json.dumps(template[13]) if isinstance(template[13], (dict, list)) else template[13]

                insert_query = text("""
                    INSERT INTO report_template (
                        id, tenant_id, parent_template_id, name, description, code, template_type,
                        template_category, report_scope, is_system, is_default, page_size, orientation,
                        margins, color_scheme, fonts, custom_css, default_logo,
                        structure, created_at, updated_at
                    ) VALUES (
                        :id, :tenant_id, :parent_template_id, :name, :description, :code, :template_type,
                        :template_category, :report_scope, :is_system, :is_default, :page_size, :orientation,
                        CAST(:margins AS jsonb), CAST(:color_scheme AS jsonb),
                        CAST(:fonts AS jsonb), :custom_css, :default_logo,
                        CAST(:structure AS jsonb), :created_at, :updated_at
                    )
                """)

                db.execute(insert_query, {
                    "id": new_id,
                    "tenant_id": tenant_id,
                    "parent_template_id": parent_template_id,  # Lien vers le template maître EBIOS
                    "name": new_name,
                    "description": template[2],
                    "code": tenant_code,
                    "template_type": template[4],
                    "template_category": template_category,  # Hériter de la catégorie (ebios)
                    "report_scope": template[5],
                    "is_system": False,
                    "is_default": True,
                    "page_size": template[6],
                    "orientation": template[7],
                    "margins": margins_json,
                    "color_scheme": color_scheme_json,
                    "fonts": fonts_json,
                    "custom_css": template[11],
                    "default_logo": template[12],
                    "structure": structure_json,
                    "created_at": now,
                    "updated_at": now
                })

                print(f"     [OK] {base_code} -> {new_name}")
                templates_created += 1
                total_created += 1

            if templates_created == 0:
                print(f"     (Aucun template a creer)")

            print()

        db.commit()

        print("=" * 70)
        print(f"[SUCCESS] {total_created} templates EBIOS crees au total")
        print("=" * 70)
        print()

        # 4. Afficher un résumé des templates EBIOS
        summary_query = text("""
            SELECT t.name as tenant_name, rt.name as template_name, rt.report_scope
            FROM report_template rt
            JOIN tenant t ON rt.tenant_id = t.id
            WHERE rt.is_system = false
              AND rt.code LIKE 'TENANT_%_EBIOS_%'
            ORDER BY t.name, rt.report_scope
        """)

        summary = db.execute(summary_query).fetchall()

        if summary:
            print("Templates EBIOS par tenant:")
            print("-" * 70)
            current_tenant = None
            for row in summary:
                if row[0] != current_tenant:
                    current_tenant = row[0]
                    print(f"\n  {current_tenant}:")
                print(f"    - {row[1]} ({row[2]})")
            print()

    except Exception as e:
        db.rollback()
        print(f"[ERROR] Erreur: {str(e)}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    duplicate_ebios_templates_for_all_tenants()
