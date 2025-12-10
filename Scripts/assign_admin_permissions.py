"""
Script pour assigner TOUTES les permissions aux roles ADMIN et SUPER_ADMIN.

Ces roles doivent avoir un acces complet a toutes les fonctionnalites.

Usage:
    cd backend
    python scripts/assign_admin_permissions.py
"""

import os
import sys

# Ajouter le repertoire parent au path pour les imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:Hrafna10@localhost:5432/cybergard")

# Roles qui doivent avoir TOUTES les permissions
ADMIN_ROLES = ['ADMIN', 'SUPER_ADMIN']


def run_assign():
    """Assigne toutes les permissions aux roles admin."""

    engine = create_engine(DATABASE_URL)

    with engine.connect() as conn:
        print("=" * 60)
        print("[ADMIN] Attribution de toutes les permissions aux admins")
        print("=" * 60)

        # 1. Recuperer les IDs des roles admin
        print("\n[STEP 1] Recherche des roles admin...")

        roles_query = text("""
            SELECT id, code, name FROM role WHERE code = ANY(:codes)
        """)
        admin_roles = conn.execute(roles_query, {"codes": ADMIN_ROLES}).fetchall()

        if not admin_roles:
            print("[ERROR] Aucun role admin trouve!")
            return

        for role in admin_roles:
            print(f"  [OK] {role.name} ({role.code}) - ID: {role.id}")

        # 2. Recuperer toutes les permissions
        print("\n[STEP 2] Recuperation de toutes les permissions...")

        permissions_query = text("SELECT id, code, name FROM permission ORDER BY code")
        all_permissions = conn.execute(permissions_query).fetchall()

        print(f"  [OK] {len(all_permissions)} permissions trouvees")

        # 3. Supprimer les permissions existantes des roles admin
        print("\n[STEP 3] Nettoyage des permissions existantes...")

        for role in admin_roles:
            delete_query = text("DELETE FROM role_permission WHERE role_id = :role_id")
            conn.execute(delete_query, {"role_id": str(role.id)})
            print(f"  [OK] Permissions supprimees pour {role.code}")

        # 4. Assigner toutes les permissions aux roles admin
        print("\n[STEP 4] Attribution de toutes les permissions...")

        for role in admin_roles:
            count = 0
            for perm in all_permissions:
                insert_query = text("""
                    INSERT INTO role_permission (role_id, permission_id)
                    VALUES (:role_id, :permission_id)
                    ON CONFLICT DO NOTHING
                """)
                conn.execute(insert_query, {
                    "role_id": str(role.id),
                    "permission_id": str(perm.id)
                })
                count += 1

            print(f"  [OK] {count} permissions assignees a {role.code}")

        # 5. Commit des changements
        conn.commit()

        # 6. Verification finale
        print("\n[STEP 5] Verification finale...")

        verify_query = text("""
            SELECT
                r.code as role_code,
                r.name as role_name,
                COUNT(rp.permission_id) as permissions_count
            FROM role r
            LEFT JOIN role_permission rp ON r.id = rp.role_id
            WHERE r.code = ANY(:codes)
            GROUP BY r.id, r.code, r.name
        """)

        final_state = conn.execute(verify_query, {"codes": ADMIN_ROLES}).fetchall()

        print("\nEtat final des roles admin:")
        print("-" * 60)
        for role in final_state:
            print(f"  [OK] {role.role_name} ({role.role_code}): {role.permissions_count} permissions")

        print("\n" + "=" * 60)
        print("[SUCCESS] Permissions admin configurees!")
        print("=" * 60)


if __name__ == "__main__":
    run_assign()
