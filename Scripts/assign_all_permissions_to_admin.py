"""
Script pour assigner TOUTES les permissions au role ADMIN
"""
import os
import sys

sys.stdout.reconfigure(line_buffering=True)
os.environ['DATABASE_URL'] = 'postgresql://postgres:postgres@localhost:5432/audit_platform'

from sqlalchemy import create_engine, text

def main():
    engine = create_engine(os.environ['DATABASE_URL'])

    with engine.connect() as conn:
        print("=" * 70, flush=True)
        print("ASSIGNATION DE TOUTES LES PERMISSIONS AU ROLE ADMIN", flush=True)
        print("=" * 70, flush=True)

        # 1. Trouver le role ADMIN
        admin_role = conn.execute(text("""
            SELECT id, code, name FROM role WHERE code = 'ADMIN'
        """)).fetchone()

        if not admin_role:
            print("ERREUR: Role ADMIN non trouve!", flush=True)
            return

        print(f"Role ADMIN trouve: {admin_role.id}", flush=True)

        # 2. Recuperer toutes les permissions
        all_perms = conn.execute(text("""
            SELECT id, code, name FROM permission ORDER BY code
        """)).fetchall()

        print(f"Total permissions dans la base: {len(all_perms)}", flush=True)

        # 3. Verifier les permissions deja assignees
        existing = conn.execute(text("""
            SELECT permission_id FROM role_permission WHERE role_id = :role_id
        """), {"role_id": str(admin_role.id)}).fetchall()

        existing_ids = {str(e.permission_id) for e in existing}
        print(f"Permissions deja assignees: {len(existing_ids)}", flush=True)

        # 4. Assigner les permissions manquantes
        added = 0
        for perm in all_perms:
            if str(perm.id) not in existing_ids:
                conn.execute(text("""
                    INSERT INTO role_permission (role_id, permission_id)
                    VALUES (:role_id, :perm_id)
                """), {"role_id": str(admin_role.id), "perm_id": str(perm.id)})
                print(f"  + {perm.code}", flush=True)
                added += 1

        conn.commit()

        print(f"\nPermissions ajoutees: {added}", flush=True)
        print(f"Total permissions ADMIN: {len(existing_ids) + added}", flush=True)

        # 5. Faire la meme chose pour SUPER_ADMIN
        super_admin = conn.execute(text("""
            SELECT id FROM role WHERE code = 'SUPER_ADMIN'
        """)).fetchone()

        if super_admin:
            print("\n" + "=" * 70, flush=True)
            print("ASSIGNATION AU ROLE SUPER_ADMIN", flush=True)
            print("=" * 70, flush=True)

            existing_super = conn.execute(text("""
                SELECT permission_id FROM role_permission WHERE role_id = :role_id
            """), {"role_id": str(super_admin.id)}).fetchall()

            existing_super_ids = {str(e.permission_id) for e in existing_super}
            added_super = 0

            for perm in all_perms:
                if str(perm.id) not in existing_super_ids:
                    conn.execute(text("""
                        INSERT INTO role_permission (role_id, permission_id)
                        VALUES (:role_id, :perm_id)
                    """), {"role_id": str(super_admin.id), "perm_id": str(perm.id)})
                    print(f"  + {perm.code}", flush=True)
                    added_super += 1

            conn.commit()
            print(f"Permissions ajoutees SUPER_ADMIN: {added_super}", flush=True)

        # 6. Verifier l'utilisateur admin
        print("\n" + "=" * 70, flush=True)
        print("VERIFICATION UTILISATEUR RACHID", flush=True)
        print("=" * 70, flush=True)

        user = conn.execute(text("""
            SELECT id, email FROM users
            WHERE email = 'rachid.ahajri@vision-agile.fr'
        """)).fetchone()

        if user:
            # Verifier si le role ADMIN est assigne
            user_admin = conn.execute(text("""
                SELECT 1 FROM user_role
                WHERE user_id = :user_id AND role_id = :role_id
            """), {"user_id": str(user.id), "role_id": str(admin_role.id)}).fetchone()

            if user_admin:
                print(f"Utilisateur {user.email} a le role ADMIN: OUI", flush=True)
            else:
                print(f"Utilisateur {user.email} a le role ADMIN: NON", flush=True)
                print("Assignation du role ADMIN...", flush=True)
                conn.execute(text("""
                    INSERT INTO user_role (user_id, role_id, assigned_at)
                    VALUES (:user_id, :role_id, NOW())
                """), {"user_id": str(user.id), "role_id": str(admin_role.id)})
                conn.commit()
                print("Role ADMIN assigne!", flush=True)

            # Compter les permissions finales
            final_perms = conn.execute(text("""
                SELECT COUNT(DISTINCT p.code)
                FROM permission p
                JOIN role_permission rp ON p.id = rp.permission_id
                JOIN user_role ur ON rp.role_id = ur.role_id
                WHERE ur.user_id = :user_id
            """), {"user_id": str(user.id)}).fetchone()

            print(f"\nPermissions totales pour {user.email}: {final_perms[0]}", flush=True)

        print("\n" + "=" * 70, flush=True)
        print("TERMINE!", flush=True)
        print("=" * 70, flush=True)

if __name__ == "__main__":
    main()
