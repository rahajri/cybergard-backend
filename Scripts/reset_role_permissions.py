"""
Script pour reinitialiser les permissions des roles.

Supprime toutes les permissions assignees aux roles SAUF pour ADMIN et SUPER_ADMIN.
Cela permet a l'administrateur de configurer manuellement les permissions de chaque role.

Usage:
    cd backend
    .venv/Scripts/python.exe scripts/reset_role_permissions.py
"""

import os
import sys

# Ajouter le repertoire parent au path pour les imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:Hrafna10@localhost:5432/cybergard")

# Roles a ne PAS modifier (garder leurs permissions)
PROTECTED_ROLES = ['ADMIN', 'SUPER_ADMIN']


def run_reset():
    """Execute la reinitialisation des permissions."""

    engine = create_engine(DATABASE_URL)

    with engine.connect() as conn:
        print("=" * 60)
        print("[RESET] Reinitialisation des permissions des roles")
        print("=" * 60)

        # 1. Lister les roles actuels avec leurs permissions
        print("\n[STEP 1] Etat actuel des roles et permissions...")

        current_state = text("""
            SELECT
                r.code as role_code,
                r.name as role_name,
                r.is_system,
                COUNT(rp.permission_id) as permissions_count
            FROM role r
            LEFT JOIN role_permission rp ON r.id = rp.role_id
            GROUP BY r.id, r.code, r.name, r.is_system
            ORDER BY r.is_system DESC, r.name
        """)

        roles = conn.execute(current_state).fetchall()

        print("\nRoles actuels:")
        print("-" * 60)
        for role in roles:
            status = "[PROTEGE]" if role.role_code in PROTECTED_ROLES else "[A VIDER]"
            system = "(systeme)" if role.is_system else "(custom)"
            print(f"  {status} {role.role_name} ({role.role_code}) {system}: {role.permissions_count} permissions")

        # 2. Supprimer les permissions des roles NON proteges
        print("\n[STEP 2] Suppression des permissions...")

        delete_query = text("""
            DELETE FROM role_permission
            WHERE role_id IN (
                SELECT id FROM role WHERE code NOT IN :protected_roles
            )
            RETURNING role_id
        """)

        result = conn.execute(delete_query, {"protected_roles": tuple(PROTECTED_ROLES)})
        deleted_count = result.rowcount

        print(f"[OK] {deleted_count} associations role-permission supprimees")

        # 3. Commit des changements
        conn.commit()

        # 4. Verification finale
        print("\n[STEP 3] Verification finale...")

        final_state = text("""
            SELECT
                r.code as role_code,
                r.name as role_name,
                r.is_system,
                COUNT(rp.permission_id) as permissions_count
            FROM role r
            LEFT JOIN role_permission rp ON r.id = rp.role_id
            GROUP BY r.id, r.code, r.name, r.is_system
            ORDER BY r.is_system DESC, r.name
        """)

        roles_after = conn.execute(final_state).fetchall()

        print("\nEtat apres reinitialisation:")
        print("-" * 60)
        for role in roles_after:
            status = "[PROTEGE]" if role.role_code in PROTECTED_ROLES else "[VIDE]"
            system = "(systeme)" if role.is_system else "(custom)"
            print(f"  {status} {role.role_name} ({role.role_code}) {system}: {role.permissions_count} permissions")

        print("\n" + "=" * 60)
        print("[SUCCESS] Reinitialisation terminee!")
        print("=" * 60)
        print("\nL'administrateur peut maintenant configurer les permissions")
        print("de chaque role via l'interface Administration > Roles.")
        print("=" * 60)


if __name__ == "__main__":
    run_reset()
