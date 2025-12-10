import sys
sys.path.insert(0, r'c:\Users\rachi\Documents\Mes Sites\AI CYBER\backend')

from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import os
import json

load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL')
engine = create_engine(DATABASE_URL)

with engine.connect() as conn:
    # Trouver un audit existant
    audit_query = text("""
        SELECT id, name FROM audit LIMIT 1
    """)
    audit = conn.execute(audit_query).fetchone()

    if not audit:
        print("Aucun audit trouvé")
        exit(1)

    print(f"=== TEST avec audit: {audit.name} ===")
    print(f"Audit ID: {audit.id}\n")

    # Extraire l'entity_id et le campaign_title depuis le nom de l'audit
    audit_name_parts = audit.name.split(" - ")
    if len(audit_name_parts) >= 3:
        entity_name = audit_name_parts[-1].strip()
        campaign_title = audit_name_parts[1].strip()

        print(f"Entity name: {entity_name}")
        print(f"Campaign title: {campaign_title}\n")

        # Trouver l'entity_id
        entity_query = text("""
            SELECT id FROM ecosystem_entity
            WHERE name = :entity_name
        """)
        entity = conn.execute(entity_query, {"entity_name": entity_name}).fetchone()

        if not entity:
            print(f"Entity '{entity_name}' not found")
            exit(1)

        entity_id = entity.id
        print(f"Entity ID: {entity_id}\n")

        # SIMULER L'APPEL API : GET /api/v1/collaboration/audits/{audit_id}/collaborators
        print("=== SIMULATION DE L'APPEL API ===\n")

        # Requête 1 : Membres de l'entité (AUDITE_RESP + AUDITE_CONTRIB)
        entity_members_query = text("""
            SELECT
                em.id as collaborator_id,
                em.first_name,
                em.last_name,
                em.email,
                em.roles
            FROM entity_member em
            WHERE em.entity_id = :entity_id
              AND em.is_active = true
              AND (em.roles::jsonb ? 'audite_contrib' OR em.roles::jsonb ? 'audite_resp')
            ORDER BY em.last_name, em.first_name
        """)

        entity_members = conn.execute(entity_members_query, {"entity_id": str(entity_id)}).fetchall()

        print(f"=== MEMBRES DE L'ENTITÉ ({len(entity_members)}) ===")
        for m in entity_members:
            roles = json.loads(m.roles) if isinstance(m.roles, str) else m.roles
            print(f"- {m.first_name} {m.last_name} ({m.email})")
            print(f"  ID: {m.collaborator_id}")
            print(f"  Roles: {roles}")
        print()

        # Requête 2 : Auditeurs de la campagne
        auditor_query = text("""
            SELECT DISTINCT
                em.id as collaborator_id,
                em.first_name,
                em.last_name,
                em.email,
                em.roles
            FROM campaign c
            JOIN campaign_scope cs ON c.scope_id = cs.id
            JOIN entity_member em ON em.id = ANY(cs.auditor_ids)
            WHERE c.title = :campaign_title
              AND em.is_active = true
        """)

        auditors = conn.execute(auditor_query, {"campaign_title": campaign_title}).fetchall()

        print(f"=== AUDITEURS DE LA CAMPAGNE ({len(auditors)}) ===")
        for a in auditors:
            roles = json.loads(a.roles) if isinstance(a.roles, str) else a.roles
            print(f"- {a.first_name} {a.last_name} ({a.email})")
            print(f"  ID: {a.collaborator_id}")
            print(f"  Roles: {roles}")
        print()

        # Combiner et dédupliquer (comme dans l'endpoint)
        all_collaborators = {}

        for m in entity_members:
            all_collaborators[str(m.collaborator_id)] = {
                "id": str(m.collaborator_id),
                "first_name": m.first_name,
                "last_name": m.last_name,
                "email": m.email,
                "roles": json.loads(m.roles) if isinstance(m.roles, str) else m.roles
            }

        for a in auditors:
            if str(a.collaborator_id) not in all_collaborators:
                all_collaborators[str(a.collaborator_id)] = {
                    "id": str(a.collaborator_id),
                    "first_name": a.first_name,
                    "last_name": a.last_name,
                    "email": a.email,
                    "roles": json.loads(a.roles) if isinstance(a.roles, str) else a.roles
                }

        print(f"=== RÉSULTAT FINAL DE L'API (après déduplication) ===")
        print(f"Total: {len(all_collaborators)} personnes\n")

        for collab in all_collaborators.values():
            print(f"- {collab['first_name']} {collab['last_name']} ({collab['email']})")
            print(f"  ID: {collab['id']}")
            print(f"  Roles: {collab['roles']}")
        print()

        print(f"\n=== JSON RETOURNÉ PAR L'API ===")
        print(json.dumps(list(all_collaborators.values()), indent=2, ensure_ascii=False))
