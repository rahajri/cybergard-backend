#!/usr/bin/env python
"""Script temporaire pour lister les templates de rapport."""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine, text
import json

engine = create_engine(os.getenv('DATABASE_URL'))

with engine.connect() as conn:
    # Lister les templates
    result = conn.execute(text("""
        SELECT id, name, report_scope, is_system, template_type, structure
        FROM report_template
        ORDER BY is_system DESC, name
    """)).fetchall()

    print("=" * 80)
    print("TEMPLATES DE RAPPORT EXISTANTS")
    print("=" * 80)

    for r in result:
        print(f"\n📄 {r.name}")
        print(f"   ID: {r.id}")
        print(f"   Scope: {r.report_scope}")
        print(f"   System: {r.is_system}")
        print(f"   Type: {r.template_type}")

        # Afficher la structure si présente
        if r.structure:
            try:
                structure = r.structure if isinstance(r.structure, list) else json.loads(r.structure)
                widgets = [w.get('widget_type', 'unknown') for w in structure]
                print(f"   Widgets ({len(widgets)}): {', '.join(widgets)}")
            except:
                print(f"   Structure: (erreur de parsing)")

    print("\n" + "=" * 80)
