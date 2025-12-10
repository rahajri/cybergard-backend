"""
Script pour insérer le template CONSOLIDÉ système.

Ce template correspond à la structure testée et fonctionnelle
du rapport consolidé multi-entités.

Usage (depuis le dossier backend):
    python insert_consolidated_template.py
"""

import sys
import os
from pathlib import Path
from datetime import datetime, timezone
import uuid
import json

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import text
from src.database import SessionLocal


# ============================================================================
# TEMPLATE CONSOLIDÉ (basé sur le rapport qui fonctionne)
# ============================================================================

TEMPLATE_CONSOLIDATED = {
    "id": str(uuid.uuid4()),
    "tenant_id": None,  # Template système
    "name": "Rapport Consolidé Écosystème",
    "description": "Rapport consolidé multi-entités avec vue écosystème (10-15 pages)",
    "code": "SYSTEM_CONSOLIDATED",
    "template_type": "executive",
    "report_scope": "consolidated",  # Vue écosystème multi-organismes
    "is_system": True,
    "is_default": False,
    "page_size": "A4",
    "orientation": "portrait",
    "margins": {
        "top": 20,
        "right": 15,
        "bottom": 20,
        "left": 15
    },
    "color_scheme": {
        "primary": "#8B5CF6",
        "secondary": "#3B82F6",
        "accent": "#10B981",
        "danger": "#EF4444",
        "warning": "#F59E0B",
        "success": "#22C55E",
        "text": "#1F2937",
        "background": "#FFFFFF",
        "header_bg": "#3A6374"
    },
    "fonts": {
        "title": {"family": "Noto Sans JP", "size": 18, "weight": "bold"},
        "heading1": {"family": "Noto Sans JP", "size": 16, "weight": "bold"},
        "heading2": {"family": "Noto Sans JP", "size": 14, "weight": "bold"},
        "heading3": {"family": "Noto Sans JP", "size": 12, "weight": "bold"},
        "body": {"family": "Noto Sans JP", "size": 10, "weight": "normal"}
    },
    "custom_css": None,
    "default_logo": "TENANT",
    "structure": [
        # ==================== PAGE DE GARDE ====================
        {
            "widget_type": "cover",
            "widget_key": "cover_page",
            "position": 0,
            "config": {
                "title": "%framework.name%",
                "subtitle": "Rapport d'Audit de Cybersécurité",
                "date": "%report.date%",
                "logo_source": "tenant",
                "confidentiality": "CONFIDENTIEL - Ne pas diffuser"
            }
        },
        # ==================== HEADER (pour toutes les pages) ====================
        {
            "widget_type": "header",
            "widget_key": "page_header",
            "position": 1,
            "config": {
                "title": "%framework.name%",
                "show_logo": True,
                "show_date": True,
                "logo_source": "tenant"
            }
        },
        # ==================== SOMMAIRE ====================
        {
            "widget_type": "toc",
            "widget_key": "table_of_contents",
            "position": 2,
            "config": {
                "title": "Sommaire",
                "depth": 2
            }
        },
        {
            "widget_type": "page_break",
            "widget_key": "break_1",
            "position": 3,
            "config": {}
        },
        # ==================== RÉSUMÉ EXÉCUTIF IA ====================
        {
            "widget_type": "title",
            "widget_key": "summary_title",
            "position": 4,
            "config": {
                "text": "Résumé Exécutif",
                "level": 1
            }
        },
        {
            "widget_type": "ai_summary",
            "widget_key": "ai_executive_summary",
            "position": 5,
            "config": {
                "title": "",
                "tone": "executive",
                "report_scope": "consolidated",
                "use_ai": True,
                "editable": True,
                "max_words": 400
            }
        },
        # ==================== KPIs ====================
        {
            "widget_type": "kpi",
            "widget_key": "main_kpis",
            "position": 6,
            "config": {
                "title": "Indicateurs Clés",
                "layout": "grid",
                "show_global_score": True,
                "show_domains_count": True,
                "show_questions_count": False,
                "show_nc_count": True,
                "show_entities_count": True
            }
        },
        {
            "widget_type": "page_break",
            "widget_key": "break_2",
            "position": 7,
            "config": {}
        },
        # ==================== JAUGE DE MATURITÉ ====================
        {
            "widget_type": "title",
            "widget_key": "maturity_title",
            "position": 8,
            "config": {
                "text": "Score Global de Maturité",
                "level": 1
            }
        },
        {
            "widget_type": "gauge",
            "widget_key": "global_gauge",
            "position": 9,
            "config": {
                "title": "",
                "value": "%scores.global%",
                "min": 0,
                "max": 100,
                "thresholds": [
                    {"value": 40, "color": "#EF4444", "label": "Faible"},
                    {"value": 70, "color": "#F59E0B", "label": "Moyen"},
                    {"value": 100, "color": "#22C55E", "label": "Bon"}
                ]
            }
        },
        # ==================== MÉTHODOLOGIE ====================
        {
            "widget_type": "title",
            "widget_key": "methodology_title",
            "position": 10,
            "config": {
                "text": "Méthodologie",
                "level": 1
            }
        },
        {
            "widget_type": "paragraph",
            "widget_key": "methodology_text",
            "position": 11,
            "config": {
                "text": "L'audit a été réalisé selon la méthodologie %framework.name% sur la période du %campaign.start_date% au %campaign.due_date%."
            }
        },
        {
            "widget_type": "page_break",
            "widget_key": "break_3",
            "position": 12,
            "config": {}
        },
        # ==================== RÉSULTATS GLOBAUX ====================
        {
            "widget_type": "title",
            "widget_key": "results_title",
            "position": 13,
            "config": {
                "text": "Résultats Globaux",
                "level": 1
            }
        },
        {
            "widget_type": "radar_domains",
            "widget_key": "radar_chart",
            "position": 14,
            "config": {
                "title": "",
                "show_legend": True
            }
        },
        {
            "widget_type": "domain_scores",
            "widget_key": "domain_scores_table",
            "position": 15,
            "config": {
                "title": "Scores par Domaine",
                "show_progress_bar": True,
                "sort_by": "score",
                "order": "asc"
            }
        },
        {
            "widget_type": "page_break",
            "widget_key": "break_4",
            "position": 16,
            "config": {}
        },
        # ==================== NON-CONFORMITÉS ====================
        {
            "widget_type": "title",
            "widget_key": "nc_title",
            "position": 17,
            "config": {
                "text": "Non-Conformités Critiques",
                "level": 1
            }
        },
        {
            "widget_type": "nc_table",
            "widget_key": "nc_major_table",
            "position": 18,
            "config": {
                "title": "",
                "severity": "major",
                "limit": 15,
                "columns": ["domain", "question", "risk_level", "comment"]
            }
        },
        {
            "widget_type": "page_break",
            "widget_key": "break_5",
            "position": 19,
            "config": {}
        },
        # ==================== PLAN D'ACTION ====================
        {
            "widget_type": "title",
            "widget_key": "actions_title",
            "position": 20,
            "config": {
                "text": "Plan d'Action Synthétique",
                "level": 1
            }
        },
        {
            "widget_type": "action_plan",
            "widget_key": "action_plan_widget",
            "position": 21,
            "config": {
                "title": "",
                "limit": 15,
                "show_priority": True,
                "show_deadline": True,
                "show_responsible": True
            }
        },
        {
            "widget_type": "page_break",
            "widget_key": "break_6",
            "position": 22,
            "config": {}
        },
        # ==================== CONCLUSION IA ====================
        {
            "widget_type": "title",
            "widget_key": "conclusion_title",
            "position": 23,
            "config": {
                "text": "Conclusion et Recommandations",
                "level": 1
            }
        },
        {
            "widget_type": "ai_summary",
            "widget_key": "ai_conclusion",
            "position": 24,
            "config": {
                "title": "",
                "tone": "technical",
                "report_scope": "consolidated",
                "use_ai": True,
                "editable": True,
                "max_words": 350
            }
        }
    ]
}


def insert_template():
    """Insère le template consolidé dans la base."""

    print("=" * 70)
    print("INSERTION DU TEMPLATE CONSOLIDE")
    print("=" * 70)
    print()

    db = SessionLocal()
    try:
        # Vérifier si le template existe déjà
        check_query = text("""
            SELECT id, name FROM report_template
            WHERE code = :code
        """)

        existing = db.execute(check_query, {"code": "SYSTEM_CONSOLIDATED"}).fetchone()

        if existing:
            print(f"[INFO] Template existant trouve: {existing[1]} (ID: {existing[0]})")
            print("   Suppression et recreation...")

            delete_query = text("""
                DELETE FROM report_template
                WHERE code = :code
            """)
            db.execute(delete_query, {"code": "SYSTEM_CONSOLIDATED"})
            db.commit()

        # Préparer les données
        template = TEMPLATE_CONSOLIDATED.copy()

        print(f"[OK] Insertion template: {template['name']}")
        print(f"     Code: {template['code']}")
        print(f"     Scope: {template['report_scope']}")
        print(f"     Widgets: {len(template['structure'])}")

        insert_query = text("""
            INSERT INTO report_template (
                id, tenant_id, name, description, code, template_type,
                report_scope, is_system, is_default, page_size, orientation,
                margins, color_scheme, fonts, custom_css, default_logo,
                structure, created_at, updated_at
            ) VALUES (
                CAST(:id AS uuid), :tenant_id, :name, :description, :code, :template_type,
                :report_scope, :is_system, :is_default, :page_size, :orientation,
                CAST(:margins AS jsonb), CAST(:color_scheme AS jsonb), CAST(:fonts AS jsonb),
                :custom_css, :default_logo,
                CAST(:structure AS jsonb), :created_at, :updated_at
            )
        """)

        db.execute(insert_query, {
            "id": template["id"],
            "tenant_id": template["tenant_id"],
            "name": template["name"],
            "description": template["description"],
            "code": template["code"],
            "template_type": template["template_type"],
            "report_scope": template["report_scope"],
            "is_system": template["is_system"],
            "is_default": template["is_default"],
            "page_size": template["page_size"],
            "orientation": template["orientation"],
            "margins": json.dumps(template["margins"]),
            "color_scheme": json.dumps(template["color_scheme"]),
            "fonts": json.dumps(template["fonts"]),
            "custom_css": template["custom_css"],
            "default_logo": template["default_logo"],
            "structure": json.dumps(template["structure"]),
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        })

        db.commit()

        print()
        print("[SUCCESS] Template consolide insere avec succes!")
        print()

        # Afficher tous les templates système
        list_query = text("""
            SELECT code, name, report_scope, is_default
            FROM report_template
            WHERE is_system = true
            ORDER BY code
        """)

        templates = db.execute(list_query).fetchall()

        print("Templates systeme disponibles:")
        print("-" * 60)
        for t in templates:
            default_mark = " (par defaut)" if t[3] else ""
            print(f"  {t[0]:25} | {t[2]:15} | {t[1]}{default_mark}")
        print()

    except Exception as e:
        db.rollback()
        print(f"[ERROR] Erreur lors de l'insertion: {str(e)}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    insert_template()
