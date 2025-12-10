"""
Script pour vérifier les permissions d'un utilisateur
"""
import os
import sys

# Configuration
os.environ['DATABASE_URL'] = 'postgresql://postgres:Hrafna10@localhost:5432/cybergard'

from sqlalchemy import create_engine, text

def main():
    engine = create_engine(os.environ['DATABASE_URL'])

    with engine.connect() as conn:
        # 1. Trouver l'utilisateur
        print("=" * 60)
        print("1. RECHERCHE DE L'UTILISATEUR")
        print("=" * 60)

        user = conn.execute(text("""
            SELECT id, email, first_name, last_name, tenant_id
            FROM users
            WHERE email = 'rachid.ahajri@vision-agile.fr'
        """)).fetchone()

        if not user:
            print("❌ Utilisateur non trouvé!")
            return

        print(f"✅ Utilisateur trouvé:")
        print(f"   ID: {user.id}")
        print(f"   Email: {user.email}")
        print(f"   Nom: {user.first_name} {user.last_name}")
        print(f"   Tenant: {user.tenant_id}")

        # 2. Vérifier les rôles assignés
        print()
        print("=" * 60)
        print("2. ROLES ASSIGNES (table user_role)")
        print("=" * 60)

        roles = conn.execute(text("""
            SELECT r.id, r.code, r.name, ur.assigned_at
            FROM role r
            JOIN user_role ur ON r.id = ur.role_id
            WHERE ur.user_id = :user_id
        """), {"user_id": str(user.id)}).fetchall()

        if not roles:
            print("❌ AUCUN ROLE ASSIGNE à cet utilisateur!")
            print("   C'est le problème : l'utilisateur n'a pas de rôle dans user_role")
        else:
            for r in roles:
                print(f"   ✅ {r.code}: {r.name} (assigné le {r.assigned_at})")

        # 3. Vérifier les permissions
        print()
        print("=" * 60)
        print("3. PERMISSIONS DISPONIBLES (via role_permission)")
        print("=" * 60)

        perms = conn.execute(text("""
            SELECT DISTINCT p.code, p.name, p.module
            FROM permission p
            JOIN role_permission rp ON p.id = rp.permission_id
            JOIN user_role ur ON rp.role_id = ur.role_id
            WHERE ur.user_id = :user_id
            ORDER BY p.module, p.code
        """), {"user_id": str(user.id)}).fetchall()

        if not perms:
            print("❌ AUCUNE PERMISSION!")
        else:
            current_module = None
            for p in perms:
                if p.module != current_module:
                    current_module = p.module
                    print(f"\n   [{current_module}]")
                print(f"      - {p.code}")

        # 4. Vérifier les rôles disponibles
        print()
        print("=" * 60)
        print("4. TOUS LES ROLES DISPONIBLES")
        print("=" * 60)

        all_roles = conn.execute(text("""
            SELECT r.id, r.code, r.name,
                   (SELECT COUNT(*) FROM role_permission rp WHERE rp.role_id = r.id) as perm_count
            FROM role r
            ORDER BY r.code
        """)).fetchall()

        for r in all_roles:
            print(f"   - {r.code}: {r.name} ({r.perm_count} permissions)")

        # 5. Solution
        print()
        print("=" * 60)
        print("5. SOLUTION PROPOSEE")
        print("=" * 60)

        if not roles:
            admin_role = conn.execute(text("""
                SELECT id FROM role WHERE code = 'ADMIN' LIMIT 1
            """)).fetchone()

            if admin_role:
                print(f"""
Pour assigner le rôle ADMIN à cet utilisateur, exécutez:

INSERT INTO user_role (user_id, role_id, assigned_at)
VALUES ('{user.id}', '{admin_role.id}', NOW());

Ou via le script assign_role_to_user.py
""")

if __name__ == "__main__":
    main()
