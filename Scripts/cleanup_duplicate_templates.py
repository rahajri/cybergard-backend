"""
Script pour nettoyer les templates dupliqués.

Garde uniquement UN template par tenant/scope, supprime les doublons.

Usage (depuis le dossier backend):
    python scripts/cleanup_duplicate_templates.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from src.database import SessionLocal


def cleanup_duplicates():
    """Supprime les templates dupliqués, garde le plus récent."""

    print("=" * 70)
    print("NETTOYAGE DES TEMPLATES DUPLIQUÉS")
    print("=" * 70)

    db = SessionLocal()
    try:
        # Trouver les doublons par tenant + report_scope
        duplicates_query = text("""
            SELECT tenant_id, report_scope, COUNT(*) as cnt
            FROM report_template
            WHERE is_system = false
              AND tenant_id IS NOT NULL
            GROUP BY tenant_id, report_scope
            HAVING COUNT(*) > 1
        """)

        duplicates = db.execute(duplicates_query).fetchall()

        if not duplicates:
            print("\n✓ Aucun doublon trouvé!")
            return

        print(f"\n⚠ {len(duplicates)} groupe(s) avec doublons trouvé(s)")

        total_deleted = 0

        for dup in duplicates:
            tenant_id = dup[0]
            report_scope = dup[1]
            count = dup[2]

            print(f"\n--- Tenant {str(tenant_id)[:8]}... | Scope: {report_scope} | {count} copies ---")

            # Récupérer tous les templates de ce groupe, triés par date (plus récent en premier)
            templates_query = text("""
                SELECT id, name, code, created_at
                FROM report_template
                WHERE tenant_id = :tenant_id
                  AND report_scope = :scope
                  AND is_system = false
                ORDER BY created_at DESC
            """)

            templates = db.execute(templates_query, {
                "tenant_id": tenant_id,
                "scope": report_scope
            }).fetchall()

            # Garder le premier (plus récent), supprimer les autres
            keep_template = templates[0]
            delete_templates = templates[1:]

            print(f"  ✓ GARDER: {keep_template[1]} ({keep_template[2]})")

            for to_delete in delete_templates:
                print(f"  ✗ SUPPRIMER: {to_delete[1]} ({to_delete[2]})")

                delete_query = text("""
                    DELETE FROM report_template
                    WHERE id = :id
                """)
                db.execute(delete_query, {"id": to_delete[0]})
                total_deleted += 1

        db.commit()

        print("\n" + "=" * 70)
        print(f"✓ NETTOYAGE TERMINÉ: {total_deleted} template(s) supprimé(s)")
        print("=" * 70)

        # Afficher l'état final
        print("\n--- État final ---")
        final_query = text("""
            SELECT rt.name, rt.code, rt.report_scope, t.name as tenant_name
            FROM report_template rt
            LEFT JOIN tenant t ON rt.tenant_id = t.id
            WHERE rt.is_system = false
            ORDER BY t.name, rt.report_scope
        """)

        final = db.execute(final_query).fetchall()
        for r in final:
            print(f"  {r[3]}: {r[0]} ({r[2]})")

    except Exception as e:
        db.rollback()
        print(f"\n[ERROR] Erreur: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    cleanup_duplicates()
