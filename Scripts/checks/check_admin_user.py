"""
Script pour vérifier l'utilisateur admin@cyberguard.pro et son organisation
"""

import sys
import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# Charger les variables d'environnement
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/cyberguard")

engine = create_engine(DATABASE_URL)

def check_admin():
    """Vérifier l'utilisateur admin et son organisation"""

    with engine.connect() as conn:
        # 1. Vérifier l'utilisateur
        print("=" * 80)
        print("1. VERIFICATION UTILISATEUR admin@cyberguard.pro")
        print("=" * 80)

        user_result = conn.execute(text("""
            SELECT
                u.id,
                u.email,
                u.first_name,
                u.last_name,
                u.default_org_id,
                u.tenant_id,
                u.is_active
            FROM users u
            WHERE u.email = :email
        """), {"email": "admin@cyberguard.pro"})

        user = user_result.first()

        if not user:
            print("UTILISATEUR NON TROUVE")
            return

        print(f"ID: {user[0]}")
        print(f"Email: {user[1]}")
        print(f"Nom: {user[2]} {user[3]}")
        print(f"default_org_id: {user[4]}")
        print(f"tenant_id: {user[5]}")
        print(f"is_active: {user[6]}")

        user_id = user[0]
        default_org_id = user[4]

        # 2. Vérifier l'organisation
        if default_org_id:
            print("\n" + "=" * 80)
            print("2. VERIFICATION ORGANISATION")
            print("=" * 80)

            org_result = conn.execute(text("""
                SELECT
                    o.id,
                    o.name,
                    o.is_platform_owner,
                    o.is_active
                FROM organizations o
                WHERE o.id = :org_id
            """), {"org_id": str(default_org_id)})

            org = org_result.first()

            if org:
                print(f"ID: {org[0]}")
                print(f"Nom: {org[1]}")
                print(f"is_platform_owner: {org[2]}")
                print(f"is_active: {org[3]}")

                if org[2]:
                    print("\n>>> RESULTAT: Cette organisation EST marquee comme plateforme (is_platform_owner=true)")
                    print(">>> L'utilisateur DEVRAIT etre redirige vers /admin")
                else:
                    print("\n>>> PROBLEME IDENTIFIE: is_platform_owner = FALSE")
                    print(">>> L'utilisateur sera redirige vers /client au lieu de /admin")
                    print("\n>>> SOLUTION: Executer la commande suivante pour corriger:")
                    print(f">>>   UPDATE organizations SET is_platform_owner = true WHERE id = '{org[0]}';")
            else:
                print("ORGANISATION NON TROUVEE")
        else:
            print("\nPROBLEME: Utilisateur sans default_org_id")

        # 3. Vérifier le rôle dans user_organization_role
        print("\n" + "=" * 80)
        print("3. VERIFICATION ROLE user_organization_role")
        print("=" * 80)

        role_result = conn.execute(text("""
            SELECT
                uor.id,
                uor.role,
                uor.is_active,
                uor.organization_id
            FROM user_organization_role uor
            WHERE uor.user_id = :user_id
        """), {"user_id": str(user_id)})

        roles = role_result.all()

        if roles:
            for role in roles:
                print(f"\nRole ID: {role[0]}")
                print(f"  role: {role[1]}")
                print(f"  is_active: {role[2]}")
                print(f"  organization_id: {role[3]}")
        else:
            print("AUCUN ROLE TROUVE dans user_organization_role")

        # 4. Vérifier toutes les organisations avec is_platform_owner
        print("\n" + "=" * 80)
        print("4. TOUTES LES ORGANISATIONS PLATEFORME (is_platform_owner=true)")
        print("=" * 80)

        platform_orgs = conn.execute(text("""
            SELECT
                o.id,
                o.name,
                o.is_platform_owner,
                COUNT(u.id) as user_count
            FROM organizations o
            LEFT JOIN users u ON u.default_org_id = o.id
            WHERE o.is_platform_owner = true
            GROUP BY o.id, o.name, o.is_platform_owner
        """))

        orgs = platform_orgs.all()

        if orgs:
            for org in orgs:
                print(f"\nOrganisation: {org[1]}")
                print(f"  ID: {org[0]}")
                print(f"  is_platform_owner: {org[2]}")
                print(f"  Nombre utilisateurs: {org[3]}")
        else:
            print("AUCUNE organisation avec is_platform_owner=true trouvee")
            print("\nPROBLEME: La migration n'a pas ete executee ou 'Administration Plateforme' n'existe pas")
            print("\nSOLUTIONS:")
            print("1. Verifier si l'organisation 'Administration Plateforme' existe:")
            print("   SELECT * FROM organizations WHERE name LIKE '%Administration%';")
            print("\n2. Si elle existe, mettre a jour is_platform_owner:")
            print("   UPDATE organizations SET is_platform_owner = true WHERE name = 'Administration Plateforme';")
            print("\n3. Si elle n'existe pas, la creer:")
            print("   INSERT INTO organizations (id, name, is_platform_owner, is_active) ")
            print("   VALUES (gen_random_uuid(), 'Administration Plateforme', true, true);")

        print("\n" + "=" * 80)

if __name__ == "__main__":
    try:
        check_admin()
    except Exception as e:
        print(f"\nERREUR: {e}")
        import traceback
        traceback.print_exc()
