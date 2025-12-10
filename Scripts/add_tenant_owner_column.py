"""
Script de migration pour ajouter la colonne is_tenant_owner a la table users.

Cette colonne permet d'identifier le proprietaire/administrateur principal d'un tenant.
Le script marque aussi les utilisateurs existants comme tenant_owner s'ils sont
le premier utilisateur cree pour leur tenant.

Usage:
    cd backend
    .venv/Scripts/python.exe scripts/add_tenant_owner_column.py
"""

import os
import sys

# Ajouter le repertoire parent au path pour les imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:Hrafna10@localhost:5432/cybergard")


def run_migration():
    """Execute la migration pour ajouter is_tenant_owner."""

    engine = create_engine(DATABASE_URL)

    with engine.connect() as conn:
        print("=" * 60)
        print("[MIGRATION] Ajout de la colonne is_tenant_owner")
        print("=" * 60)

        # 1. Verifier si la colonne existe deja
        print("\n[STEP 1] Verification de l'existence de la colonne...")
        check_column = text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'users' AND column_name = 'is_tenant_owner'
        """)
        result = conn.execute(check_column).fetchone()

        if result:
            print("[OK] La colonne is_tenant_owner existe deja.")
        else:
            # 2. Ajouter la colonne
            print("[INFO] La colonne n'existe pas, creation en cours...")
            add_column = text("""
                ALTER TABLE users
                ADD COLUMN is_tenant_owner BOOLEAN DEFAULT FALSE
            """)
            conn.execute(add_column)
            print("[OK] Colonne is_tenant_owner ajoutee avec succes.")

            # 3. Creer un index pour optimiser les requetes
            print("\n[STEP 2] Creation de l'index...")
            create_index = text("""
                CREATE INDEX IF NOT EXISTS ix_users_is_tenant_owner
                ON users (is_tenant_owner)
                WHERE is_tenant_owner = TRUE
            """)
            conn.execute(create_index)
            print("[OK] Index cree avec succes.")

        # 4. Marquer les tenant owners existants
        # Strategie: le premier utilisateur cree pour chaque tenant devient owner
        print("\n[STEP 3] Identification des tenant owners existants...")

        # D'abord, compter les tenants avec des utilisateurs
        count_tenants = text("""
            SELECT COUNT(DISTINCT tenant_id)
            FROM users
            WHERE tenant_id IS NOT NULL
        """)
        tenant_count = conn.execute(count_tenants).scalar()
        print(f"[INFO] {tenant_count} tenant(s) avec des utilisateurs trouves.")

        if tenant_count > 0:
            # Marquer le premier utilisateur de chaque tenant comme owner
            update_owners = text("""
                WITH first_users AS (
                    SELECT DISTINCT ON (tenant_id) id, tenant_id, email
                    FROM users
                    WHERE tenant_id IS NOT NULL
                    ORDER BY tenant_id, created_at ASC
                )
                UPDATE users u
                SET is_tenant_owner = TRUE
                FROM first_users fu
                WHERE u.id = fu.id
                RETURNING u.id, u.email, u.tenant_id
            """)
            updated = conn.execute(update_owners).fetchall()

            print(f"\n[OK] {len(updated)} utilisateur(s) marque(s) comme tenant owner:")
            for row in updated:
                print(f"    - {row.email} (tenant: {row.tenant_id})")

        # 5. Commit des changements
        conn.commit()

        # 6. Verification finale
        print("\n[STEP 4] Verification finale...")
        verify = text("""
            SELECT
                u.email,
                u.first_name,
                u.last_name,
                u.phone,
                u.is_tenant_owner,
                o.name as org_name
            FROM users u
            LEFT JOIN organization o ON o.tenant_id = u.tenant_id
            WHERE u.is_tenant_owner = TRUE
            ORDER BY u.created_at
        """)
        owners = conn.execute(verify).fetchall()

        print(f"\n[RESULT] Liste des tenant owners ({len(owners)}):")
        print("-" * 60)
        for owner in owners:
            name = f"{owner.first_name or ''} {owner.last_name or ''}".strip() or "Non renseigne"
            phone = owner.phone or "Non renseigne"
            print(f"  Organisation: {owner.org_name or 'N/A'}")
            print(f"  Nom: {name}")
            print(f"  Email: {owner.email}")
            print(f"  Telephone: {phone}")
            print("-" * 60)

        print("\n[SUCCESS] Migration terminee avec succes!")
        print("=" * 60)


if __name__ == "__main__":
    run_migration()
