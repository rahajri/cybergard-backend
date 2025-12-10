"""
Script pour nettoyer les templates dupliqués par tenant.

Garde uniquement le plus récent de chaque type (consolidated/entity) par tenant.

Usage (depuis le dossier backend):
    python cleanup_duplicate_templates.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import text
from src.database import SessionLocal


def cleanup_duplicates():
    """Supprime les templates dupliqués, garde le plus récent."""

    print("=" * 70)
    print("NETTOYAGE DES TEMPLATES DUPLIQUES")
    print("=" * 70)
    print()

    db = SessionLocal()
    try:
        # 1. Identifier les doublons par tenant + report_scope
        duplicates_query = text("""
            SELECT tenant_id, report_scope, COUNT(*) as count
            FROM report_template
            WHERE is_system = false
              AND code LIKE 'TENANT_%'
            GROUP BY tenant_id, report_scope
            HAVING COUNT(*) > 1
        """)

        duplicates = db.execute(duplicates_query).fetchall()

        if not duplicates:
            print("[OK] Aucun doublon trouve.")
            return

        print(f"[WARN] {len(duplicates)} groupes avec doublons trouves")
        print()

        total_deleted = 0

        for dup in duplicates:
            tenant_id = dup[0]
            report_scope = dup[1]
            count = dup[2]

            # Récupérer le nom du tenant
            tenant_query = text("SELECT name FROM tenant WHERE id = :id")
            tenant_result = db.execute(tenant_query, {"id": tenant_id}).fetchone()
            tenant_name = tenant_result[0] if tenant_result else "Unknown"

            print(f"--- Tenant: {tenant_name} | Scope: {report_scope} | {count} templates ---")

            # Garder le plus récent (created_at DESC), supprimer les autres
            delete_query = text("""
                DELETE FROM report_template
                WHERE id IN (
                    SELECT id FROM report_template
                    WHERE tenant_id = :tenant_id
                      AND report_scope = :report_scope
                      AND is_system = false
                      AND code LIKE 'TENANT_%'
                    ORDER BY created_at DESC
                    OFFSET 1
                )
            """)

            result = db.execute(delete_query, {
                "tenant_id": tenant_id,
                "report_scope": report_scope
            })

            deleted = result.rowcount
            total_deleted += deleted
            print(f"     [OK] {deleted} doublons supprimes (1 conserve)")

        db.commit()

        print()
        print("=" * 70)
        print(f"[SUCCESS] {total_deleted} templates supprimes au total")
        print("=" * 70)
        print()

        # Afficher l'état final
        final_query = text("""
            SELECT t.name, rt.name as template_name, rt.report_scope
            FROM report_template rt
            JOIN tenant t ON rt.tenant_id = t.id
            WHERE rt.is_system = false
              AND rt.code LIKE 'TENANT_%'
            ORDER BY t.name, rt.report_scope
        """)

        final = db.execute(final_query).fetchall()

        if final:
            print("Templates restants par tenant:")
            print("-" * 70)
            current_tenant = None
            for row in final:
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
    finally:
        db.close()


if __name__ == "__main__":
    cleanup_duplicates()
