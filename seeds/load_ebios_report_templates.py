#!/usr/bin/env python3
"""
Script de chargement des templates de rapport EBIOS RM

Ce script charge les templates de rapport EBIOS RM ANSSI dans la table report_template.
Mode upsert: met à jour les entrées existantes et ajoute les nouvelles.

Usage:
    python load_ebios_report_templates.py                  # Chargement normal (upsert)
    python load_ebios_report_templates.py --drop-existing  # Supprime les templates EBIOS existants d'abord
    python load_ebios_report_templates.py --check          # Vérifie seulement le nombre de templates

Prérequis:
    - La table report_template doit exister
    - La variable DATABASE_URL doit être définie
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

# Ajouter le répertoire parent pour importer les modules du backend
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Configuration
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/audit_platform"
)

# Répertoire des fichiers JSON
SEEDS_DIR = Path(__file__).parent / "ebios"


def load_json_file(filename: str) -> dict:
    """Charge un fichier JSON depuis le répertoire seeds/ebios/."""
    filepath = SEEDS_DIR / filename
    if not filepath.exists():
        print(f"[ERROR] Fichier non trouvé: {filepath}")
        return {}

    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def load_ebios_templates(session, data: dict, drop_existing: bool = False) -> int:
    """
    Charge les templates EBIOS RM dans report_template.

    Args:
        session: Session SQLAlchemy
        data: Données JSON contenant les templates
        drop_existing: Si True, supprime les templates EBIOS existants avant le chargement

    Returns:
        Nombre de templates chargés
    """
    if drop_existing:
        # Supprimer uniquement les templates système EBIOS (pas les copies tenant)
        session.execute(text("""
            DELETE FROM report_template
            WHERE code LIKE 'SYSTEM_EBIOS_%'
              AND is_system = true
              AND tenant_id IS NULL
        """))
        print("  [INFO] Templates système EBIOS supprimés")

    templates = data.get("templates", [])
    count = 0

    for template in templates:
        try:
            # Générer un ID déterministe basé sur le code pour permettre l'upsert
            template_id = uuid4()
            now = datetime.now(timezone.utc)

            # Convertir les objets JSON en chaînes pour PostgreSQL
            margins_json = json.dumps(template.get("margins", {}))
            color_scheme_json = json.dumps(template.get("color_scheme", {}))
            fonts_json = json.dumps(template.get("fonts", {}))
            structure_json = json.dumps(template.get("structure", []))

            # Vérifier si le template existe déjà
            check_query = text("""
                SELECT id FROM report_template
                WHERE code = :code
                  AND is_system = true
                  AND tenant_id IS NULL
            """)
            existing = session.execute(check_query, {"code": template["code"]}).fetchone()

            if existing:
                # Mise à jour
                update_query = text("""
                    UPDATE report_template SET
                        name = :name,
                        description = :description,
                        template_type = :template_type,
                        template_category = :template_category,
                        report_scope = :report_scope,
                        is_default = :is_default,
                        page_size = :page_size,
                        orientation = :orientation,
                        margins = CAST(:margins AS jsonb),
                        color_scheme = CAST(:color_scheme AS jsonb),
                        fonts = CAST(:fonts AS jsonb),
                        default_logo = :default_logo,
                        structure = CAST(:structure AS jsonb),
                        updated_at = :updated_at
                    WHERE code = :code
                      AND is_system = true
                      AND tenant_id IS NULL
                """)
                session.execute(update_query, {
                    "name": template["name"],
                    "description": template.get("description", ""),
                    "template_type": template.get("template_type", "ebios"),
                    "template_category": template.get("template_category", "ebios"),
                    "report_scope": template.get("report_scope", "consolidated"),
                    "is_default": template.get("is_default", False),
                    "page_size": template.get("page_size", "A4"),
                    "orientation": template.get("orientation", "portrait"),
                    "margins": margins_json,
                    "color_scheme": color_scheme_json,
                    "fonts": fonts_json,
                    "default_logo": template.get("default_logo", "TENANT"),
                    "structure": structure_json,
                    "updated_at": now,
                    "code": template["code"]
                })
                print(f"  [UPDATE] {template['code']} - {template['name']}")
            else:
                # Insertion
                insert_query = text("""
                    INSERT INTO report_template (
                        id, code, name, description, template_type, template_category,
                        report_scope, is_system, is_default, page_size, orientation,
                        margins, color_scheme, fonts, default_logo, structure,
                        tenant_id, created_at, updated_at
                    ) VALUES (
                        :id, :code, :name, :description, :template_type, :template_category,
                        :report_scope, :is_system, :is_default, :page_size, :orientation,
                        CAST(:margins AS jsonb), CAST(:color_scheme AS jsonb),
                        CAST(:fonts AS jsonb), :default_logo, CAST(:structure AS jsonb),
                        :tenant_id, :created_at, :updated_at
                    )
                """)
                session.execute(insert_query, {
                    "id": template_id,
                    "code": template["code"],
                    "name": template["name"],
                    "description": template.get("description", ""),
                    "template_type": template.get("template_type", "ebios"),
                    "template_category": template.get("template_category", "ebios"),
                    "report_scope": template.get("report_scope", "consolidated"),
                    "is_system": template.get("is_system", True),
                    "is_default": template.get("is_default", False),
                    "page_size": template.get("page_size", "A4"),
                    "orientation": template.get("orientation", "portrait"),
                    "margins": margins_json,
                    "color_scheme": color_scheme_json,
                    "fonts": fonts_json,
                    "default_logo": template.get("default_logo", "TENANT"),
                    "structure": structure_json,
                    "tenant_id": None,  # Template système
                    "created_at": now,
                    "updated_at": now
                })
                print(f"  [INSERT] {template['code']} - {template['name']}")

            count += 1

        except Exception as e:
            print(f"  [ERROR] Template {template.get('code', 'UNKNOWN')}: {e}")

    return count


def check_templates(session) -> dict:
    """Vérifie le nombre de templates EBIOS dans la base."""
    try:
        # Templates système EBIOS
        result_system = session.execute(text("""
            SELECT code, name, report_scope
            FROM report_template
            WHERE code LIKE 'SYSTEM_EBIOS_%'
              AND is_system = true
              AND tenant_id IS NULL
            ORDER BY code
        """))
        system_templates = result_system.fetchall()

        # Templates tenant EBIOS (copies)
        result_tenant = session.execute(text("""
            SELECT COUNT(*)
            FROM report_template
            WHERE code LIKE '%EBIOS_%'
              AND is_system = false
              AND tenant_id IS NOT NULL
        """))
        tenant_count = result_tenant.scalar()

        return {
            "system_templates": system_templates,
            "tenant_copies_count": tenant_count
        }
    except Exception as e:
        return {"error": str(e)}


def main():
    parser = argparse.ArgumentParser(
        description="Charge les templates de rapport EBIOS RM dans la base de données"
    )
    parser.add_argument(
        "--drop-existing",
        action="store_true",
        help="Supprime les templates EBIOS système existants avant le chargement"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Vérifie seulement le nombre de templates sans charger"
    )
    parser.add_argument(
        "--database-url",
        type=str,
        default=DATABASE_URL,
        help="URL de connexion à la base de données"
    )

    args = parser.parse_args()

    print("=" * 60)
    print("Chargement des Templates EBIOS RM ANSSI")
    print("=" * 60)
    print(f"Database: {args.database_url[:50]}...")
    print(f"Seeds directory: {SEEDS_DIR}")
    print()

    # Connexion à la base
    try:
        engine = create_engine(args.database_url)
        Session = sessionmaker(bind=engine)
        session = Session()
        print("[OK] Connexion à la base de données établie")
    except Exception as e:
        print(f"[ERROR] Impossible de se connecter à la base: {e}")
        sys.exit(1)

    # Mode vérification uniquement
    if args.check:
        print("\n[INFO] Mode vérification - État des templates EBIOS:\n")
        result = check_templates(session)

        if "error" in result:
            print(f"  [ERROR] {result['error']}")
        else:
            print("  Templates système EBIOS:")
            if result["system_templates"]:
                for t in result["system_templates"]:
                    print(f"    - {t[0]}: {t[1]} (scope: {t[2]})")
            else:
                print("    (aucun)")
            print(f"\n  Copies tenant: {result['tenant_copies_count']}")

        session.close()
        return

    # Chargement du fichier JSON
    print("\n[STEP 1] Chargement du fichier JSON...")
    data = load_json_file("ebios_report_templates.json")

    if not data:
        print("[ERROR] Fichier ebios_report_templates.json non trouvé ou vide")
        session.close()
        sys.exit(1)

    templates_count = len(data.get("templates", []))
    print(f"  [OK] {templates_count} templates trouvés dans le fichier")

    # Insertion en base
    try:
        print("\n[STEP 2] Insertion des templates en base...")
        count = load_ebios_templates(session, data, args.drop_existing)

        # Commit
        session.commit()
        print("\n[OK] Templates commitées en base")

    except Exception as e:
        session.rollback()
        print(f"\n[ERROR] Erreur lors du chargement: {e}")
        sys.exit(1)

    finally:
        session.close()

    # Résumé
    print("\n" + "=" * 60)
    print("RÉSUMÉ DU CHARGEMENT")
    print("=" * 60)
    print(f"  Templates chargés: {count}")
    print("\n[DONE] Chargement terminé avec succès!")
    print("\nPour dupliquer ces templates vers les tenants existants, exécutez:")
    print("  python duplicate_ebios_templates_for_tenants.py")


if __name__ == "__main__":
    main()
