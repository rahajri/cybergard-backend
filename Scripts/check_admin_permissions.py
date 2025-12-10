"""
Script pour vérifier et afficher les permissions de l'admin
"""
import os
import sys

# Force flush
sys.stdout.reconfigure(line_buffering=True)

os.environ['DATABASE_URL'] = 'postgresql://postgres:Hrafna10@localhost:5432/cybergard'

from sqlalchemy import create_engine, text

def main():
    engine = create_engine(os.environ['DATABASE_URL'])

    with engine.connect() as conn:
        print("=" * 70)
        print("1. UTILISATEUR ADMIN")
        print("=" * 70)

        user = conn.execute(text("""
            SELECT id, email, first_name, last_name, tenant_id
            FROM users
            WHERE email = 'rachid.ahajri@vision-agile.fr'
        """)).fetchone()

        if not user:
            print("ERREUR: Utilisateur non trouve!")
            return

        print(f"Email: {user.email}")
        print(f"ID: {user.id}")
        print(f"Tenant: {user.tenant_id}")

        print("\n" + "=" * 70)
        print("2. ROLES ASSIGNES")
        print("=" * 70)

        roles = conn.execute(text("""
            SELECT r.id, r.code, r.name
            FROM role r
            JOIN user_role ur ON r.id = ur.role_id
            WHERE ur.user_id = :user_id
        """), {"user_id": str(user.id)}).fetchall()

        if not roles:
            print("!!! AUCUN ROLE ASSIGNE !!!")

            # Assigner ADMIN automatiquement
            admin_role = conn.execute(text("""
                SELECT id FROM role WHERE code = 'ADMIN'
            """)).fetchone()

            if admin_role:
                print(f"\nAssignation du role ADMIN...")
                conn.execute(text("""
                    INSERT INTO user_role (user_id, role_id, assigned_at)
                    VALUES (:user_id, :role_id, NOW())
                """), {"user_id": str(user.id), "role_id": str(admin_role.id)})
                conn.commit()
                print("Role ADMIN assigne!")

                # Recharger les roles
                roles = conn.execute(text("""
                    SELECT r.id, r.code, r.name
                    FROM role r
                    JOIN user_role ur ON r.id = ur.role_id
                    WHERE ur.user_id = :user_id
                """), {"user_id": str(user.id)}).fetchall()

        for r in roles:
            print(f"  - {r.code}: {r.name}")

        print("\n" + "=" * 70)
        print("3. PERMISSIONS DISPONIBLES POUR CET UTILISATEUR")
        print("=" * 70)

        perms = conn.execute(text("""
            SELECT DISTINCT p.code, p.name, p.module
            FROM permission p
            JOIN role_permission rp ON p.id = rp.permission_id
            JOIN user_role ur ON rp.role_id = ur.role_id
            WHERE ur.user_id = :user_id
            ORDER BY p.module, p.code
        """), {"user_id": str(user.id)}).fetchall()

        if not perms:
            print("!!! AUCUNE PERMISSION !!!")
        else:
            current_module = None
            for p in perms:
                if p.module != current_module:
                    current_module = p.module
                    print(f"\n  [{current_module or 'GENERAL'}]")
                print(f"    - {p.code}")

        print("\n" + "=" * 70)
        print("4. TOUTES LES PERMISSIONS DANS LA BASE")
        print("=" * 70)

        all_perms = conn.execute(text("""
            SELECT code, name, module FROM permission ORDER BY module, code
        """)).fetchall()

        current_module = None
        for p in all_perms:
            if p.module != current_module:
                current_module = p.module
                print(f"\n  [{current_module or 'GENERAL'}]")
            print(f"    - {p.code}: {p.name}")

        print(f"\nTotal: {len(all_perms)} permissions")

        # Verifier si REPORT_READ existe
        print("\n" + "=" * 70)
        print("5. VERIFICATION PERMISSION REPORT_READ")
        print("=" * 70)

        report_perm = conn.execute(text("""
            SELECT id, code, name FROM permission WHERE code = 'REPORT_READ'
        """)).fetchone()

        if report_perm:
            print(f"Permission REPORT_READ existe: {report_perm.id}")

            # Verifier si assignee au role ADMIN
            admin_has_report = conn.execute(text("""
                SELECT 1 FROM role_permission rp
                JOIN role r ON rp.role_id = r.id
                WHERE r.code = 'ADMIN' AND rp.permission_id = :perm_id
            """), {"perm_id": str(report_perm.id)}).fetchone()

            if admin_has_report:
                print("  -> Assignee au role ADMIN: OUI")
            else:
                print("  -> Assignee au role ADMIN: NON")
        else:
            print("Permission REPORT_READ n'existe PAS!")

if __name__ == "__main__":
    main()
