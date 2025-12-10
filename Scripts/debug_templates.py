"""Script pour debug des templates de rapport."""

import asyncio
import sys
import os

# Ajouter le répertoire parent au path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print("=== DÉBUT DU SCRIPT ===", flush=True)

from sqlalchemy import text
from src.db.session import async_session

print("Imports OK", flush=True)


async def main():
    """Vérifie la structure des templates."""
    print("Connexion DB...", flush=True)

    async with async_session() as db:
        print("DB connectée", flush=True)

        # Lister les templates individuels
        result = await db.execute(text("""
            SELECT id, name, report_scope, is_system, tenant_id,
                   jsonb_array_length(structure) as widget_count
            FROM report_template
            WHERE report_scope = 'entity' AND deleted_at IS NULL
            ORDER BY created_at DESC
            LIMIT 5
        """))
        templates = result.fetchall()

        print(f"\nTROUVÉ {len(templates)} TEMPLATES ENTITY", flush=True)
        for t in templates:
            print(f"  - {t.name}: system={t.is_system}, widgets={t.widget_count}", flush=True)

        # Structure détaillée du template tenant
        result2 = await db.execute(text("""
            SELECT id, name, structure
            FROM report_template
            WHERE report_scope = 'entity' AND is_system = false AND deleted_at IS NULL
            LIMIT 1
        """))
        template = result2.fetchone()

        if template:
            print(f"\nSTRUCTURE: {template.name}", flush=True)
            structure = template.structure

            for i, w in enumerate(structure):
                wtype = w.get('widget_type', '?')
                title = w.get('config', {}).get('title', '-')
                if wtype in ('ai_summary', 'summary'):
                    print(f"  🤖 [{i}] {wtype}: {title}", flush=True)
        else:
            print("Aucun template tenant trouvé", flush=True)

    print("\n=== FIN DU SCRIPT ===", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
