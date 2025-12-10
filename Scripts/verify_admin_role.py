"""
Script pour vérifier et assigner le rôle ADMIN si nécessaire
"""
import os
os.environ['DATABASE_URL'] = 'postgresql://postgres:Hrafna10@localhost:5432/cybergard'

from sqlalchemy import create_engine, text

def main():
    engine = create_engine(os.environ['DATABASE_URL'])

    with engine.connect() as conn:
        # 1. Trouver l'utilisateur
        print("=" * 60)
        print("VERIFICATION UTILISATEUR ADMIN")
        print("=" * 60)

        user = conn.execute(text("""
            SELECT id, email, first_name, last_name, tenant_id
            FROM users
            WHERE email = 'rachid.ahajri@vision-agile.fr'
        """)).fetchone()

        if not user:
            print("Utilisateur non trouvé!")
            return

        print(f"Utilisateur: {user.email}")
        print(f"ID: {user.id}")

        # 2. Vérifier les rôles assignés
        roles = conn.execute(text("""
            SELECT r.id, r.code, r.name
            FROM role r
            JOIN user_role ur ON r.id = ur.role_id
            WHERE ur.user_id = :user_id
        """), {"user_id": str(user.id)}).fetchall()

        if roles:
            print(f"\nRoles assignes:")
            for r in roles:
                print(f"  - {r.code}: {r.name}")
        else:
            print("\n!!! AUCUN ROLE ASSIGNE !!!")

            # Trouver le rôle ADMIN
            admin_role = conn.execute(text("""
                SELECT id, code FROM role WHERE code = 'ADMIN'
            """)).fetchone()

            if admin_role:
                print(f"\nAssignation du role ADMIN ({admin_role.id})...")

                # Vérifier s'il n'existe pas déjà
                existing = conn.execute(text("""
                    SELECT 1 FROM user_role
                    WHERE user_id = :user_id AND role_id = :role_id
                """), {"user_id": str(user.id), "role_id": str(admin_role.id)}).fetchone()

                if not existing:
                    conn.execute(text("""
                        INSERT INTO user_role (user_id, role_id, assigned_at)
                        VALUES (:user_id, :role_id, NOW())
                    """), {"user_id": str(user.id), "role_id": str(admin_role.id)})
                    conn.commit()
                    print("Role ADMIN assigne avec succes!")
                else:
                    print("Role deja assigne (mais non trouve precedemment?)")
            else:
                print("Role ADMIN non trouve dans la base!")

        # 3. Compter les permissions
        perm_count = conn.execute(text("""
            SELECT COUNT(DISTINCT p.code)
            FROM permission p
            JOIN role_permission rp ON p.id = rp.permission_id
            JOIN user_role ur ON rp.role_id = ur.role_id
            WHERE ur.user_id = :user_id
        """), {"user_id": str(user.id)}).fetchone()

        print(f"\nNombre de permissions: {perm_count[0] if perm_count else 0}")

if __name__ == "__main__":
    main()
