"""
Script pour nettoyer les templates dupliqués par nom de tenant.

Usage (depuis le dossier backend):
    python scripts/cleanup_by_tenant_name.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from src.database import SessionLocal


def cleanup_by_tenant_name():
    """Analyse et nettoie les doublons par nom de tenant."""

    print("=" * 80)
    print("ANALYSE DES TEMPLATES PAR NOM DE TENANT")
    print("=" * 80)

    db = SessionLocal()
    try:
        # Voir tous les templates custom avec leur tenant
        query = text("""
            SELECT
                rt.id,
                rt.name,
                rt.code,
                rt.report_scope,
                rt.tenant_id,
                t.name as tenant_name,
                rt.created_at
            FROM report_template rt
            LEFT JOIN tenant t ON rt.tenant_id = t.id
            WHERE rt.is_system = false
            ORDER BY t.name, rt.report_scope, rt.created_at DESC
        """)

        templates = db.execute(query).fetchall()

        print(f"\n{len(templates)} templates custom trouvés:\n")
        print(f"{'TENANT':<20} | {'SCOPE':<12} | {'CODE':<30} | {'TENANT_ID':<10}")
        print("-" * 80)

        for t in templates:
            tenant_name = t[5] or "?"
            print(f"{tenant_name:<20} | {t[3]:<12} | {t[2]:<30} | {str(t[4])[:8]}...")

        # Compter par tenant_name + scope
        print("\n\n--- ANALYSE DES DOUBLONS ---\n")

        count_query = text("""
            SELECT
                t.name as tenant_name,
                rt.report_scope,
                COUNT(*) as cnt,
                array_agg(rt.id) as ids
            FROM report_template rt
            JOIN tenant t ON rt.tenant_id = t.id
            WHERE rt.is_system = false
            GROUP BY t.name, rt.report_scope
            HAVING COUNT(*) > 1
            ORDER BY t.name, rt.report_scope
        """)

        duplicates = db.execute(count_query).fetchall()

        if not duplicates:
            print("✓ Aucun doublon détecté par nom de tenant!")
        else:
            print(f"⚠ {len(duplicates)} groupe(s) avec doublons:\n")

            total_to_delete = 0
            ids_to_delete = []

            for dup in duplicates:
                tenant_name = dup[0]
                scope = dup[1]
                count = dup[2]
                ids = dup[3]

                print(f"  {tenant_name} / {scope}: {count} copies")

                # Garder le premier ID (le plus récent grâce à ORDER BY), supprimer les autres
                # On va requêter pour avoir le plus récent
                recent_query = text("""
                    SELECT rt.id, rt.code, rt.created_at
                    FROM report_template rt
                    JOIN tenant t ON rt.tenant_id = t.id
                    WHERE t.name = :tenant_name
                      AND rt.report_scope = :scope
                      AND rt.is_system = false
                    ORDER BY rt.created_at DESC
                """)

                recent = db.execute(recent_query, {
                    "tenant_name": tenant_name,
                    "scope": scope
                }).fetchall()

                keep = recent[0]
                delete = recent[1:]

                print(f"    → GARDER: {keep[1]} (créé {keep[2]})")
                for d in delete:
                    print(f"    → SUPPRIMER: {d[1]} (créé {d[2]})")
                    ids_to_delete.append(d[0])
                    total_to_delete += 1

            # Confirmation
            print(f"\n\n{'='*80}")
            print(f"RÉSUMÉ: {total_to_delete} template(s) à supprimer")
            print(f"{'='*80}")

            confirm = input("\nVoulez-vous supprimer ces doublons ? (oui/non): ")

            if confirm.lower() == 'oui':
                for tid in ids_to_delete:
                    db.execute(text("DELETE FROM report_template WHERE id = :id"), {"id": tid})
                db.commit()
                print(f"\n✓ {total_to_delete} template(s) supprimé(s)!")
            else:
                print("\n✗ Annulé.")

    except Exception as e:
        db.rollback()
        print(f"\n[ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    cleanup_by_tenant_name()
