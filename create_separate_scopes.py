import sys
sys.path.insert(0, r'c:\Users\rachi\Documents\Mes Sites\AI CYBER\backend')

from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import os
import uuid

load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL')
engine = create_engine(DATABASE_URL)

FRANCE_IA_ID = '1754cab1-c444-4a32-88d7-12faeb035115'
C2M_SYSTEM_ID = 'cbdebd92-e22a-4911-8da7-7cf665336b9b'
CAMPAIGN_ID = '65f50723-dcf5-4c48-83c2-ace342c9ae72'
OLD_SCOPE_ID = '5eb0b815-2dd1-46ab-bc6f-5bc4d3a0add2'

with engine.connect() as conn:
    # First, get the tenant_id and created_by from the campaign
    campaign_query = text("""
        SELECT tenant_id, created_by FROM campaign WHERE id = :campaign_id
    """)
    campaign = conn.execute(campaign_query, {"campaign_id": CAMPAIGN_ID}).fetchone()

    if not campaign:
        print(f"[ERROR] Campaign {CAMPAIGN_ID} not found")
        exit(1)

    tenant_id = campaign.tenant_id
    created_by = campaign.created_by

    print(f"[OK] Found campaign - Tenant: {tenant_id}, Created by: {created_by}")

    # Create scope for FRANCE IA
    france_ia_scope_id = str(uuid.uuid4())
    insert_france_ia = text("""
        INSERT INTO campaign_scope (id, tenant_id, name, description, entity_ids, auditor_ids, is_active, created_by)
        VALUES (
            :scope_id,
            :tenant_id,
            :name,
            :description,
            ARRAY[:entity_id]::uuid[],
            ARRAY[]::uuid[],
            true,
            :created_by
        )
    """)

    conn.execute(insert_france_ia, {
        "scope_id": france_ia_scope_id,
        "tenant_id": str(tenant_id),
        "name": "Scope - FRANCE IA - ISO 27001",
        "description": "Scope for FRANCE IA entity",
        "entity_id": FRANCE_IA_ID,
        "created_by": str(created_by) if created_by else None
    })

    print(f"[OK] Created scope for FRANCE IA: {france_ia_scope_id}")

    # Create scope for C2M SYSTEM
    c2m_scope_id = str(uuid.uuid4())
    insert_c2m = text("""
        INSERT INTO campaign_scope (id, tenant_id, name, description, entity_ids, auditor_ids, is_active, created_by)
        VALUES (
            :scope_id,
            :tenant_id,
            :name,
            :description,
            ARRAY[:entity_id]::uuid[],
            ARRAY[]::uuid[],
            true,
            :created_by
        )
    """)

    conn.execute(insert_c2m, {
        "scope_id": c2m_scope_id,
        "tenant_id": str(tenant_id),
        "name": "Scope - C2M SYSTEM - ISO 27001",
        "description": "Scope for C2M SYSTEM entity",
        "entity_id": C2M_SYSTEM_ID,
        "created_by": str(created_by) if created_by else None
    })

    print(f"[OK] Created scope for C2M SYSTEM: {c2m_scope_id}")

    conn.commit()

    # Verify the new scopes
    verify_query = text("""
        SELECT id, name, entity_ids
        FROM campaign_scope
        WHERE id IN (:scope1, :scope2)
    """)

    result = conn.execute(verify_query, {
        "scope1": france_ia_scope_id,
        "scope2": c2m_scope_id
    })

    print("\n=== NEW SCOPES CREATED ===")
    for row in result.fetchall():
        print(f"Scope ID: {row.id}")
        print(f"  Name: {row.name}")
        print(f"  Entity IDs: {row.entity_ids}")
        print()

    print(f"\n[NOTE] The campaign still points to the old scope: {OLD_SCOPE_ID}")
    print(f"   You may need to update the campaign.scope_id if needed.")
