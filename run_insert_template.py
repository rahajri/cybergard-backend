#!/usr/bin/env python
"""Script pour insérer le template individuel."""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine, text
import json

# Connexion
engine = create_engine(os.getenv('DATABASE_URL'))

# Structure du template
structure = [
    {"widget_type": "cover", "widget_key": "cover_page", "position": 0, "config": {"title": "%entity.name%", "subtitle": "Rapport d'Audit de Cybersécurité", "date": "%report.date%", "logo_source": "entity", "confidentiality": "CONFIDENTIEL - Document réservé à l'entité auditée"}},
    {"widget_type": "page_break", "widget_key": "break_1", "position": 1, "config": {}},
    {"widget_type": "toc", "widget_key": "table_of_contents", "position": 2, "config": {"title": "Sommaire", "depth": 2}},
    {"widget_type": "page_break", "widget_key": "break_2", "position": 3, "config": {}},
    {"widget_type": "ai_summary", "widget_key": "ai_executive_summary", "position": 4, "config": {"title": "Résumé Exécutif", "tone": "executive", "report_scope": "individual", "use_ai": True, "editable": True, "max_words": 400}},
    {"widget_type": "page_break", "widget_key": "break_3", "position": 5, "config": {}},
    {"widget_type": "title", "widget_key": "kpi_title", "position": 6, "config": {"text": "Indicateurs Clés de Performance", "level": 1}},
    {"widget_type": "kpi", "widget_key": "main_kpis", "position": 7, "config": {"title": "", "layout": "grid", "show_global_score": True, "show_domains_count": True, "show_questions_count": True, "show_nc_count": True, "show_entities_count": False}},
    {"widget_type": "gauge", "widget_key": "maturity_gauge", "position": 8, "config": {"title": "Score de Maturité Global", "value": "%scores.global%", "min": 0, "max": 100, "thresholds": [{"value": 40, "color": "#EF4444", "label": "Faible"}, {"value": 70, "color": "#F59E0B", "label": "Moyen"}, {"value": 100, "color": "#22C55E", "label": "Bon"}]}},
    {"widget_type": "page_break", "widget_key": "break_4", "position": 9, "config": {}},
    {"widget_type": "title", "widget_key": "benchmark_title", "position": 10, "config": {"text": "Positionnement", "level": 1}},
    {"widget_type": "benchmark", "widget_key": "benchmark_widget", "position": 11, "config": {"title": "Comparaison avec les pairs", "show_position": True, "show_average": True, "show_delta": True}},
    {"widget_type": "page_break", "widget_key": "break_5", "position": 12, "config": {}},
    {"widget_type": "title", "widget_key": "domains_title", "position": 13, "config": {"text": "Analyse par Domaine", "level": 1}},
    {"widget_type": "radar_domains", "widget_key": "radar_chart", "position": 14, "config": {"title": "Vue Radar des Domaines", "series": ["evaluated"], "show_legend": True}},
    {"widget_type": "domain_scores", "widget_key": "domain_scores_table", "position": 15, "config": {"title": "Scores Détaillés par Domaine", "show_progress_bar": True, "sort_by": "score", "order": "asc"}},
    {"widget_type": "page_break", "widget_key": "break_6", "position": 16, "config": {}},
    {"widget_type": "title", "widget_key": "nc_title", "position": 17, "config": {"text": "Non-Conformités Identifiées", "level": 1}},
    {"widget_type": "nc_table", "widget_key": "nc_table_major", "position": 18, "config": {"title": "Non-Conformités Majeures", "severity": "major", "limit": 15, "columns": ["domain", "question", "risk_level", "comment"]}},
    {"widget_type": "nc_table", "widget_key": "nc_table_minor", "position": 19, "config": {"title": "Non-Conformités Mineures", "severity": "minor", "limit": 10, "columns": ["domain", "question", "risk_level", "comment"]}},
    {"widget_type": "page_break", "widget_key": "break_7", "position": 20, "config": {}},
    {"widget_type": "title", "widget_key": "actions_title", "position": 21, "config": {"text": "Plan d'Action Recommandé", "level": 1}},
    {"widget_type": "action_plan", "widget_key": "action_plan_widget", "position": 22, "config": {"title": "Actions Prioritaires", "limit": 15, "show_priority": True, "show_deadline": True, "show_responsible": False}},
    {"widget_type": "page_break", "widget_key": "break_8", "position": 23, "config": {}},
    {"widget_type": "title", "widget_key": "conclusion_title", "position": 24, "config": {"text": "Conclusion", "level": 1}},
    {"widget_type": "ai_summary", "widget_key": "ai_conclusion", "position": 25, "config": {"title": "Synthèse et Recommandations", "tone": "technical", "report_scope": "individual", "use_ai": True, "editable": True, "max_words": 300}}
]

with engine.connect() as conn:
    # Supprimer si existe
    conn.execute(text("DELETE FROM report_template WHERE code = 'SYSTEM_INDIVIDUAL'"))

    # Insérer le nouveau template
    insert_sql = text("""
        INSERT INTO report_template (
            id, tenant_id, name, description, code, template_type,
            report_scope, is_system, is_default, page_size, orientation,
            margins, color_scheme, fonts, custom_css, default_logo,
            structure, created_at, updated_at
        ) VALUES (
            gen_random_uuid(),
            NULL,
            'Rapport Individuel',
            'Rapport d''audit détaillé pour une entité spécifique (10-20 pages)',
            'SYSTEM_INDIVIDUAL',
            'executive',
            'entity',
            TRUE,
            FALSE,
            'A4',
            'portrait',
            CAST(:margins AS jsonb),
            CAST(:color_scheme AS jsonb),
            CAST(:fonts AS jsonb),
            NULL,
            'TENANT',
            CAST(:structure AS jsonb),
            NOW(),
            NOW()
        )
    """)

    conn.execute(insert_sql, {
        "margins": json.dumps({"top": 20, "right": 15, "bottom": 20, "left": 15}),
        "color_scheme": json.dumps({
            "primary": "#6366F1",
            "secondary": "#8B5CF6",
            "accent": "#10B981",
            "danger": "#EF4444",
            "warning": "#F59E0B",
            "success": "#22C55E",
            "text": "#1F2937",
            "background": "#FFFFFF",
            "header_bg": "#4338CA"
        }),
        "fonts": json.dumps({
            "title": {"family": "Noto Sans JP", "size": 18, "weight": "bold"},
            "heading1": {"family": "Noto Sans JP", "size": 16, "weight": "bold"},
            "heading2": {"family": "Noto Sans JP", "size": 14, "weight": "bold"},
            "heading3": {"family": "Noto Sans JP", "size": 12, "weight": "bold"},
            "body": {"family": "Noto Sans JP", "size": 10, "weight": "normal"}
        }),
        "structure": json.dumps(structure)
    })

    # Mettre à jour les templates existants
    conn.execute(text("UPDATE report_template SET report_scope = 'consolidated' WHERE code = 'SYSTEM_EXECUTIVE' AND (report_scope IS NULL OR report_scope = '')"))
    conn.execute(text("UPDATE report_template SET report_scope = 'both' WHERE code = 'SYSTEM_TECHNICAL' AND (report_scope IS NULL OR report_scope = '')"))
    conn.execute(text("UPDATE report_template SET report_scope = 'entity' WHERE code = 'SYSTEM_SUPPLIERS' AND (report_scope IS NULL OR report_scope = '')"))

    conn.commit()

    # Vérifier
    result = conn.execute(text("SELECT name, code, report_scope, is_system FROM report_template WHERE is_system = TRUE ORDER BY name")).fetchall()

    print("=" * 60)
    print("TEMPLATES SYSTÈME")
    print("=" * 60)
    for r in result:
        print(f"  - {r.name} ({r.code}) - scope: {r.report_scope}")
    print()
    print("SUCCESS!")
