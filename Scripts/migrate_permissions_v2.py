"""
Migration : Enrichir la table Permission avec module, action, permission_type
+ Creer la table permission_dependency pour les dependances entre permissions

PostgreSQL - Cybergard AI
"""

import os
import sys
from pathlib import Path

# Ajouter le chemin du backend au PYTHONPATH
backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# Charger les variables d'environnement
load_dotenv(backend_path / ".env")

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    print("[ERROR] DATABASE_URL non definie dans .env")
    sys.exit(1)

engine = create_engine(DATABASE_URL)


def run_migration():
    """Execute la migration pour enrichir les permissions"""

    with engine.connect() as conn:
        # ============================================================
        # ETAPE 1 : Ajouter les nouvelles colonnes a la table permission
        # ============================================================
        print("[STEP 1] Ajout des colonnes module, action, permission_type...")

        # Verifier si les colonnes existent deja
        check_columns = text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'permission'
            AND column_name IN ('module', 'action', 'permission_type')
        """)
        existing_cols = [row[0] for row in conn.execute(check_columns)]

        if 'module' not in existing_cols:
            conn.execute(text("""
                ALTER TABLE permission
                ADD COLUMN module VARCHAR(50)
            """))
            print("  [OK] Colonne 'module' ajoutee")
        else:
            print("  [SKIP] Colonne 'module' existe deja")

        if 'action' not in existing_cols:
            conn.execute(text("""
                ALTER TABLE permission
                ADD COLUMN action VARCHAR(50)
            """))
            print("  [OK] Colonne 'action' ajoutee")
        else:
            print("  [SKIP] Colonne 'action' existe deja")

        if 'permission_type' not in existing_cols:
            conn.execute(text("""
                ALTER TABLE permission
                ADD COLUMN permission_type VARCHAR(20) DEFAULT 'general'
            """))
            print("  [OK] Colonne 'permission_type' ajoutee")
        else:
            print("  [SKIP] Colonne 'permission_type' existe deja")

        conn.commit()

        # ============================================================
        # ETAPE 2 : Creer les index pour performance
        # ============================================================
        print("\n[STEP 2] Creation des index...")

        # Index sur module + action
        try:
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS ix_permission_module_action
                ON permission(module, action)
            """))
            print("  [OK] Index ix_permission_module_action cree")
        except Exception as e:
            print(f"  [SKIP] Index ix_permission_module_action: {e}")

        # Index sur permission_type
        try:
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS ix_permission_type
                ON permission(permission_type)
            """))
            print("  [OK] Index ix_permission_type cree")
        except Exception as e:
            print(f"  [SKIP] Index ix_permission_type: {e}")

        conn.commit()

        # ============================================================
        # ETAPE 3 : Creer la table permission_dependency
        # ============================================================
        print("\n[STEP 3] Creation de la table permission_dependency...")

        # Verifier si la table existe
        check_table = text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'permission_dependency'
            )
        """)
        table_exists = conn.execute(check_table).scalar()

        if not table_exists:
            conn.execute(text("""
                CREATE TABLE permission_dependency (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    permission_id UUID NOT NULL REFERENCES permission(id) ON DELETE CASCADE,
                    depends_on_id UUID NOT NULL REFERENCES permission(id) ON DELETE CASCADE,
                    created_at TIMESTAMP DEFAULT NOW(),
                    CONSTRAINT uq_permission_dependency UNIQUE (permission_id, depends_on_id),
                    CONSTRAINT chk_no_self_dependency CHECK (permission_id != depends_on_id)
                )
            """))
            print("  [OK] Table permission_dependency creee")

            # Index pour les requetes
            conn.execute(text("""
                CREATE INDEX ix_permission_dependency_permission_id
                ON permission_dependency(permission_id)
            """))
            conn.execute(text("""
                CREATE INDEX ix_permission_dependency_depends_on_id
                ON permission_dependency(depends_on_id)
            """))
            print("  [OK] Index crees sur permission_dependency")
        else:
            print("  [SKIP] Table permission_dependency existe deja")

        conn.commit()

        # ============================================================
        # ETAPE 4 : Inserer les permissions par defaut
        # ============================================================
        print("\n[STEP 4] Insertion des permissions par defaut...")

        # Definition des permissions CRUD (general)
        general_permissions = [
            # Campagnes
            ("CAMPAIGN_READ", "campaign", "read", "general", "Lecture des campagnes", "Permet de consulter les campagnes d'audit"),
            ("CAMPAIGN_CREATE", "campaign", "create", "general", "Creation de campagnes", "Permet de creer de nouvelles campagnes"),
            ("CAMPAIGN_UPDATE", "campaign", "update", "general", "Modification des campagnes", "Permet de modifier les campagnes existantes"),
            ("CAMPAIGN_DELETE", "campaign", "delete", "general", "Suppression des campagnes", "Permet de supprimer des campagnes"),

            # Questionnaires
            ("QUESTIONNAIRE_READ", "questionnaire", "read", "general", "Lecture des questionnaires", "Permet de consulter les questionnaires"),
            ("QUESTIONNAIRE_CREATE", "questionnaire", "create", "general", "Creation de questionnaires", "Permet de creer de nouveaux questionnaires"),
            ("QUESTIONNAIRE_UPDATE", "questionnaire", "update", "general", "Modification des questionnaires", "Permet de modifier les questionnaires"),
            ("QUESTIONNAIRE_DELETE", "questionnaire", "delete", "general", "Suppression des questionnaires", "Permet de supprimer des questionnaires"),

            # Utilisateurs
            ("USERS_READ", "users", "read", "general", "Lecture des utilisateurs", "Permet de consulter la liste des utilisateurs"),
            ("USERS_CREATE", "users", "create", "general", "Creation d'utilisateurs", "Permet de creer de nouveaux utilisateurs"),
            ("USERS_UPDATE", "users", "update", "general", "Modification des utilisateurs", "Permet de modifier les utilisateurs"),
            ("USERS_DELETE", "users", "delete", "general", "Suppression des utilisateurs", "Permet de supprimer des utilisateurs"),

            # GED (Gestion Electronique de Documents)
            ("GED_READ", "ged", "read", "general", "Lecture des documents", "Permet de consulter les documents"),
            ("GED_CREATE", "ged", "create", "general", "Creation de documents", "Permet d'uploader des documents"),
            ("GED_UPDATE", "ged", "update", "general", "Modification des documents", "Permet de modifier les metadonnees des documents"),
            ("GED_DELETE", "ged", "delete", "general", "Suppression des documents", "Permet de supprimer des documents"),

            # Referentiels
            ("REFERENTIAL_READ", "referential", "read", "general", "Lecture des referentiels", "Permet de consulter les referentiels"),
            ("REFERENTIAL_CREATE", "referential", "create", "general", "Creation de referentiels", "Permet de creer de nouveaux referentiels"),
            ("REFERENTIAL_UPDATE", "referential", "update", "general", "Modification des referentiels", "Permet de modifier les referentiels"),
            ("REFERENTIAL_DELETE", "referential", "delete", "general", "Suppression des referentiels", "Permet de supprimer des referentiels"),

            # Dashboards
            ("DASHBOARD_READ", "dashboard", "read", "general", "Lecture des tableaux de bord", "Permet de consulter les dashboards"),
            ("DASHBOARD_CREATE", "dashboard", "create", "general", "Creation de tableaux de bord", "Permet de creer de nouveaux dashboards"),
            ("DASHBOARD_UPDATE", "dashboard", "update", "general", "Modification des tableaux de bord", "Permet de modifier les dashboards"),
            ("DASHBOARD_DELETE", "dashboard", "delete", "general", "Suppression des tableaux de bord", "Permet de supprimer des dashboards"),

            # Ecosystemes
            ("ECOSYSTEM_READ", "ecosystem", "read", "general", "Lecture des ecosystemes", "Permet de consulter les entites de l'ecosysteme"),
            ("ECOSYSTEM_CREATE", "ecosystem", "create", "general", "Creation d'ecosystemes", "Permet de creer de nouvelles entites"),
            ("ECOSYSTEM_UPDATE", "ecosystem", "update", "general", "Modification des ecosystemes", "Permet de modifier les entites"),
            ("ECOSYSTEM_DELETE", "ecosystem", "delete", "general", "Suppression des ecosystemes", "Permet de supprimer des entites"),

            # Actions (correctives/preventives)
            ("ACTION_READ", "action", "read", "general", "Lecture des actions", "Permet de consulter les actions correctives/preventives"),
            ("ACTION_CREATE", "action", "create", "general", "Creation d'actions", "Permet de creer de nouvelles actions"),
            ("ACTION_UPDATE", "action", "update", "general", "Modification des actions", "Permet de modifier les actions"),
            ("ACTION_DELETE", "action", "delete", "general", "Suppression des actions", "Permet de supprimer des actions"),

            # Rapports
            ("REPORT_READ", "report", "read", "general", "Lecture des rapports", "Permet de consulter les rapports d'audit"),
            ("REPORT_CREATE", "report", "create", "general", "Creation de rapports", "Permet de generer de nouveaux rapports"),
            ("REPORT_UPDATE", "report", "update", "general", "Modification des rapports", "Permet de modifier les rapports"),
            ("REPORT_DELETE", "report", "delete", "general", "Suppression des rapports", "Permet de supprimer des rapports"),
        ]

        # Definition des permissions Workflow
        workflow_permissions = [
            # Campagnes - Workflow
            ("CAMPAIGN_VALIDATE", "campaign", "validate", "workflow", "Validation des campagnes", "Permet de valider/approuver une campagne"),
            ("CAMPAIGN_REQUEST_CHANGES", "campaign", "request_changes", "workflow", "Demande de modifications", "Permet de demander des modifications sur une campagne"),
            ("CAMPAIGN_CLOSE", "campaign", "close", "workflow", "Cloture des campagnes", "Permet de cloturer une campagne"),

            # Rapports - Workflow
            ("REPORTS_VALIDATE", "reports", "validate", "workflow", "Validation des rapports", "Permet de valider/approuver un rapport"),
            ("REPORTS_CLOSE", "reports", "close", "workflow", "Cloture des rapports", "Permet de cloturer un rapport"),
        ]

        all_permissions = general_permissions + workflow_permissions

        inserted_count = 0
        updated_count = 0

        for code, module, action, perm_type, name, description in all_permissions:
            # Verifier si la permission existe
            check = conn.execute(text("""
                SELECT id FROM permission WHERE code = :code
            """), {"code": code}).fetchone()

            if check:
                # Mettre a jour les colonnes module, action, permission_type
                conn.execute(text("""
                    UPDATE permission
                    SET module = :module,
                        action = :action,
                        permission_type = :perm_type,
                        name = :name,
                        description = :description
                    WHERE code = :code
                """), {
                    "code": code,
                    "module": module,
                    "action": action,
                    "perm_type": perm_type,
                    "name": name,
                    "description": description
                })
                updated_count += 1
            else:
                # Inserer la nouvelle permission
                conn.execute(text("""
                    INSERT INTO permission (id, code, module, action, permission_type, name, description)
                    VALUES (gen_random_uuid(), :code, :module, :action, :perm_type, :name, :description)
                """), {
                    "code": code,
                    "module": module,
                    "action": action,
                    "perm_type": perm_type,
                    "name": name,
                    "description": description
                })
                inserted_count += 1

        conn.commit()
        print(f"  [OK] {inserted_count} permissions inserees, {updated_count} mises a jour")

        # ============================================================
        # ETAPE 5 : Inserer les dependances entre permissions
        # ============================================================
        print("\n[STEP 5] Insertion des dependances entre permissions...")

        # Regles de dependances :
        # - UPDATE necessite READ
        # - DELETE necessite READ
        # - CREATE necessite READ (optionnel mais logique)

        dependencies = [
            # Campagnes
            ("CAMPAIGN_UPDATE", "CAMPAIGN_READ"),
            ("CAMPAIGN_DELETE", "CAMPAIGN_READ"),
            ("CAMPAIGN_CREATE", "CAMPAIGN_READ"),

            # Questionnaires
            ("QUESTIONNAIRE_UPDATE", "QUESTIONNAIRE_READ"),
            ("QUESTIONNAIRE_DELETE", "QUESTIONNAIRE_READ"),
            ("QUESTIONNAIRE_CREATE", "QUESTIONNAIRE_READ"),

            # Utilisateurs
            ("USERS_UPDATE", "USERS_READ"),
            ("USERS_DELETE", "USERS_READ"),
            ("USERS_CREATE", "USERS_READ"),

            # GED
            ("GED_UPDATE", "GED_READ"),
            ("GED_DELETE", "GED_READ"),
            ("GED_CREATE", "GED_READ"),

            # Referentiels
            ("REFERENTIAL_UPDATE", "REFERENTIAL_READ"),
            ("REFERENTIAL_DELETE", "REFERENTIAL_READ"),
            ("REFERENTIAL_CREATE", "REFERENTIAL_READ"),

            # Dashboards
            ("DASHBOARD_UPDATE", "DASHBOARD_READ"),
            ("DASHBOARD_DELETE", "DASHBOARD_READ"),
            ("DASHBOARD_CREATE", "DASHBOARD_READ"),

            # Ecosystemes
            ("ECOSYSTEM_UPDATE", "ECOSYSTEM_READ"),
            ("ECOSYSTEM_DELETE", "ECOSYSTEM_READ"),
            ("ECOSYSTEM_CREATE", "ECOSYSTEM_READ"),

            # Actions
            ("ACTION_UPDATE", "ACTION_READ"),
            ("ACTION_DELETE", "ACTION_READ"),
            ("ACTION_CREATE", "ACTION_READ"),

            # Rapports
            ("REPORT_UPDATE", "REPORT_READ"),
            ("REPORT_DELETE", "REPORT_READ"),
            ("REPORT_CREATE", "REPORT_READ"),

            # Workflow - Campagnes (necessitent READ)
            ("CAMPAIGN_VALIDATE", "CAMPAIGN_READ"),
            ("CAMPAIGN_REQUEST_CHANGES", "CAMPAIGN_READ"),
            ("CAMPAIGN_CLOSE", "CAMPAIGN_READ"),

            # Workflow - Rapports (necessitent READ campagne)
            ("REPORTS_VALIDATE", "CAMPAIGN_READ"),
            ("REPORTS_CLOSE", "CAMPAIGN_READ"),
        ]

        dep_inserted = 0
        dep_skipped = 0

        for perm_code, depends_on_code in dependencies:
            # Recuperer les IDs
            perm_id = conn.execute(text("""
                SELECT id FROM permission WHERE code = :code
            """), {"code": perm_code}).fetchone()

            depends_id = conn.execute(text("""
                SELECT id FROM permission WHERE code = :code
            """), {"code": depends_on_code}).fetchone()

            if perm_id and depends_id:
                # Verifier si la dependance existe deja
                exists = conn.execute(text("""
                    SELECT 1 FROM permission_dependency
                    WHERE permission_id = :perm_id AND depends_on_id = :depends_id
                """), {"perm_id": perm_id[0], "depends_id": depends_id[0]}).fetchone()

                if not exists:
                    conn.execute(text("""
                        INSERT INTO permission_dependency (permission_id, depends_on_id)
                        VALUES (:perm_id, :depends_id)
                    """), {"perm_id": perm_id[0], "depends_id": depends_id[0]})
                    dep_inserted += 1
                else:
                    dep_skipped += 1
            else:
                print(f"  [WARN] Permission non trouvee: {perm_code} ou {depends_on_code}")

        conn.commit()
        print(f"  [OK] {dep_inserted} dependances inserees, {dep_skipped} deja existantes")

        # ============================================================
        # ETAPE 6 : Contrainte UNIQUE sur module + action
        # ============================================================
        print("\n[STEP 6] Ajout contrainte unique module + action...")

        try:
            conn.execute(text("""
                ALTER TABLE permission
                ADD CONSTRAINT uq_permission_module_action UNIQUE (module, action)
            """))
            print("  [OK] Contrainte uq_permission_module_action ajoutee")
        except Exception as e:
            if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                print("  [SKIP] Contrainte uq_permission_module_action existe deja")
            else:
                print(f"  [WARN] Erreur contrainte: {e}")

        conn.commit()

        # ============================================================
        # RESUME
        # ============================================================
        print("\n" + "="*60)
        print("[SUCCESS] MIGRATION TERMINEE AVEC SUCCES")
        print("="*60)

        # Afficher le resume
        total_perms = conn.execute(text("SELECT COUNT(*) FROM permission")).scalar()
        total_deps = conn.execute(text("SELECT COUNT(*) FROM permission_dependency")).scalar()
        general_count = conn.execute(text("SELECT COUNT(*) FROM permission WHERE permission_type = 'general'")).scalar()
        workflow_count = conn.execute(text("SELECT COUNT(*) FROM permission WHERE permission_type = 'workflow'")).scalar()

        print(f"\nResume :")
        print(f"   - Total permissions : {total_perms}")
        print(f"   - Permissions CRUD (general) : {general_count}")
        print(f"   - Permissions Workflow : {workflow_count}")
        print(f"   - Dependances configurees : {total_deps}")


if __name__ == "__main__":
    print("[START] Demarrage de la migration des permissions v2...")
    print("="*60)
    run_migration()
