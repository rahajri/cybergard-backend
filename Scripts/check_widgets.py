"""Check widgets count in template."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json

# Load from database sync
import psycopg2
from dotenv import load_dotenv
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")
# Parse postgresql+asyncpg:// to postgresql://
conn_url = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

try:
    conn = psycopg2.connect(conn_url)
    cur = conn.cursor()

    # Get entity templates
    cur.execute("""
        SELECT id, name, is_system, tenant_id, structure
        FROM report_template
        WHERE report_scope = 'entity'
        ORDER BY is_system ASC, created_at DESC
    """)

    templates = cur.fetchall()

    print("=" * 60)
    print("TEMPLATES ENTITY SCOPE")
    print("=" * 60)

    for t in templates:
        tid, name, is_system, tenant_id, structure = t
        print("")
        print("TEMPLATE: %s" % name)
        print("   ID: %s" % tid)
        print("   system: %s, tenant: %s" % (is_system, tenant_id))

        if structure:
            widgets = structure if isinstance(structure, list) else []
            ai_count = sum(1 for w in widgets if w.get('widget_type') in ('ai_summary', 'summary'))
            print("   Total widgets: %d" % len(widgets))
            print("   AI widgets: %d" % ai_count)

            # List AI widgets
            for i, w in enumerate(widgets):
                wtype = w.get('widget_type', '?')
                if wtype in ('ai_summary', 'summary'):
                    title = w.get('config', {}).get('title', '-')
                    wid = w.get('id', 'no-id')
                    print("   [%d] %s: \"%s\" (id=%s...)" % (i, wtype, title, wid[:20] if wid else 'no-id'))

    cur.close()
    conn.close()
    print("")
    print("Done")

except Exception as e:
    print("Error: %s" % e)
    import traceback
    traceback.print_exc()
