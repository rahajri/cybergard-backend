import sys
sys.path.insert(0, r'c:\Users\rachi\Documents\Mes Sites\AI CYBER\backend')

from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import os

load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL')
engine = create_engine(DATABASE_URL)

with engine.connect() as conn:
    # Trouver un audit_id pour tester
    audit_query = text("""
        SELECT id, name FROM audit LIMIT 1
    """)
    audit = conn.execute(audit_query).fetchone()

    if not audit:
        print("Aucun audit trouvé")
        exit(1)

    print(f"=== TEST avec audit: {audit.name} ===")
    print(f"Audit ID: {audit.id}\n")

    # Extraire l'entity_id depuis le nom de l'audit
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

        # Lister tous les membres de l'entité
        members_query = text("""
            SELECT id, first_name, last_name, email, roles
            FROM entity_member
            WHERE entity_id = :entity_id
              AND is_active = true
            ORDER BY last_name, first_name
        """)

        members = conn.execute(members_query, {"entity_id": str(entity_id)}).fetchall()

        print(f"=== TOUS LES MEMBRES DE L'ENTITE ({len(members)}) ===")
        import json
        for m in members:
            roles = json.loads(m.roles) if isinstance(m.roles, str) else m.roles
            print(f"- {m.first_name} {m.last_name} ({m.email})")
            print(f"  Roles: {roles}")
        print()

        # Lister AUDITE_RESP + AUDITE_CONTRIB
        filtered_query = text("""
            SELECT id, first_name, last_name, email, roles
            FROM entity_member
            WHERE entity_id = :entity_id
              AND is_active = true
              AND (roles::jsonb ? 'audite_contrib' OR roles::jsonb ? 'audite_resp')
            ORDER BY last_name, first_name
        """)

        filtered = conn.execute(filtered_query, {"entity_id": str(entity_id)}).fetchall()

        print(f"=== AUDITE_RESP + AUDITE_CONTRIB ({len(filtered)}) ===")
        for m in filtered:
            roles = json.loads(m.roles) if isinstance(m.roles, str) else m.roles
            print(f"- {m.first_name} {m.last_name} ({m.email})")
            print(f"  Roles: {roles}")
        print()

        # Lister les auditeurs de la campagne
        auditor_query = text("""
            SELECT DISTINCT em.id, em.first_name, em.last_name, em.email, em.roles
            FROM campaign c
            JOIN campaign_scope cs ON c.scope_id = cs.id
            JOIN entity_member em ON em.id = ANY(cs.auditor_ids)
            WHERE c.title = :campaign_title
              AND em.is_active = true
        """)

        auditors = conn.execute(auditor_query, {"campaign_title": campaign_title}).fetchall()

        print(f"=== AUDITEURS DE LA CAMPAGNE '{campaign_title}' ({len(auditors)}) ===")
        for a in auditors:
            roles = json.loads(a.roles) if isinstance(a.roles, str) else a.roles
            print(f"- {a.first_name} {a.last_name} ({a.email})")
            print(f"  Roles: {roles}")
        print()

        print(f"=== TOTAL PERSONNES TAGABLES: {len(filtered) + len(auditors)} ===")
