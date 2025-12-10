"""
Script pour créer les templates système par défaut.

Ce script insère les templates système dans la base :
- SYSTEM_EXECUTIVE : Rapport exécutif (8-12 pages)
- SYSTEM_TECHNICAL : Rapport technique (30-50 pages)
- SYSTEM_SUPPLIERS : Rapport évaluation fournisseurs (15-25 pages)
- SYSTEM_INDIVIDUAL : Rapport individuel par entité (10-20 pages)
- SYSTEM_SCAN_INDIVIDUAL : Rapport scan individuel (6-10 pages)
- SYSTEM_SCAN_ECOSYSTEM : Rapport écosystème scanner (8-15 pages)

Usage:
    python scripts/seed_system_templates.py
"""

import sys
import os
from pathlib import Path
from datetime import datetime, timezone
import uuid
import json

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from src.database import SessionLocal


# ============================================================================
# TEMPLATE 1 : EXÉCUTIF
# ============================================================================

TEMPLATE_EXECUTIVE = {
    "id": uuid.uuid4(),
    "tenant_id": None,  # Template système
    "name": "Rapport Exécutif",
    "description": "Vue synthétique pour la direction (8-12 pages)",
    "code": "SYSTEM_EXECUTIVE",
    "template_type": "executive",
    "report_scope": "consolidated",  # Vue écosystème multi-organismes
    "is_system": True,
    "is_default": True,
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
        {
            "widget_type": "cover",
            "widget_key": "cover_page",
            "position": 0,
            "config": {
                "title": "%campaign.name%",
                "subtitle": "Rapport d'Audit de Cybersécurité",
                "date": "%report.date%",
                "logo_position": "TENANT",
                "confidentiality": "CONFIDENTIEL - Ne pas diffuser"
            }
        },
        {
            "widget_type": "page_break",
            "widget_key": "break_1",
            "position": 1,
            "config": {}
        },
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
            "widget_key": "break_2",
            "position": 3,
            "config": {}
        },
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
            "widget_type": "metrics",
            "widget_key": "key_metrics",
            "position": 5,
            "config": {
                "metrics": [
                    {"label": "Score Global", "value": "%scores.global%", "type": "score"},
                    {"label": "Domaines Évalués", "value": "%stats.total_domains%", "type": "count"},
                    {"label": "Taux de Conformité", "value": "%stats.compliance_rate%", "type": "percentage"}
                ]
            }
        },
        {
            "widget_type": "gauge",
            "widget_key": "global_score_gauge",
            "position": 6,
            "config": {
                "title": "Score Global de Maturité",
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
        {
            "widget_type": "page_break",
            "widget_key": "break_3",
            "position": 7,
            "config": {}
        },
        {
            "widget_type": "title",
            "widget_key": "methodology_title",
            "position": 8,
            "config": {
                "text": "Méthodologie",
                "level": 1
            }
        },
        {
            "widget_type": "paragraph",
            "widget_key": "methodology_text",
            "position": 9,
            "config": {
                "text": "L'audit a été réalisé selon la méthodologie %framework.name% sur la période du %campaign.start_date% au %campaign.end_date%."
            }
        },
        {
            "widget_type": "page_break",
            "widget_key": "break_4",
            "position": 10,
            "config": {}
        },
        {
            "widget_type": "title",
            "widget_key": "results_title",
            "position": 11,
            "config": {
                "text": "Résultats Globaux",
                "level": 1
            }
        },
        {
            "widget_type": "radar_domains",
            "widget_key": "radar_by_domain",
            "position": 12,
            "config": {
                "title": "Score par Domaine",
                "series": ["evaluated", "sector"],
                "show_legend": True
            }
        },
        {
            "widget_type": "page_break",
            "widget_key": "break_5",
            "position": 13,
            "config": {}
        },
        {
            "widget_type": "title",
            "widget_key": "nc_title",
            "position": 14,
            "config": {
                "text": "Non-Conformités Critiques",
                "level": 1
            }
        },
        {
            "widget_type": "nc_table",
            "widget_key": "nc_major_table",
            "position": 15,
            "config": {
                "severity": "major",
                "limit": 10,
                "columns": ["domain", "question", "risk_level", "comment"]
            }
        },
        {
            "widget_type": "page_break",
            "widget_key": "break_6",
            "position": 16,
            "config": {}
        },
        {
            "widget_type": "title",
            "widget_key": "actions_title",
            "position": 17,
            "config": {
                "text": "Plan d'Action Synthétique",
                "level": 1
            }
        },
        {
            "widget_type": "actions_table",
            "widget_key": "priority_actions",
            "position": 18,
            "config": {
                "limit": 15,
                "priority_filter": ["P1", "P2"],
                "columns": ["title", "severity", "priority", "due_days", "suggested_role"]
            }
        }
    ]
}


# ============================================================================
# TEMPLATE 2 : TECHNIQUE
# ============================================================================

TEMPLATE_TECHNICAL = {
    "id": uuid.uuid4(),
    "tenant_id": None,
    "name": "Rapport Technique",
    "description": "Rapport technique détaillé (30-50 pages)",
    "code": "SYSTEM_TECHNICAL",
    "template_type": "technical",
    "report_scope": "both",  # Compatible consolidé et individuel
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
        "primary": "#3B82F6",
        "secondary": "#8B5CF6",
        "accent": "#10B981",
        "danger": "#EF4444",
        "warning": "#F59E0B",
        "success": "#22C55E",
        "text": "#1F2937",
        "background": "#FFFFFF",
        "header_bg": "#1E40AF"
    },
    "fonts": {
        "title": {"family": "Noto Sans JP", "size": 16, "weight": "bold"},
        "heading1": {"family": "Noto Sans JP", "size": 14, "weight": "bold"},
        "heading2": {"family": "Noto Sans JP", "size": 12, "weight": "bold"},
        "heading3": {"family": "Noto Sans JP", "size": 11, "weight": "bold"},
        "body": {"family": "Noto Sans JP", "size": 9, "weight": "normal"}
    },
    "custom_css": None,
    "default_logo": "TENANT",
    "structure": [
        {
            "widget_type": "cover",
            "widget_key": "cover_page",
            "position": 0,
            "config": {
                "title": "%campaign.name%",
                "subtitle": "Rapport Technique d'Audit",
                "date": "%report.date%",
                "logo_position": "TENANT"
            }
        },
        {
            "widget_type": "page_break",
            "widget_key": "break_1",
            "position": 1,
            "config": {}
        },
        {
            "widget_type": "toc",
            "widget_key": "toc",
            "position": 2,
            "config": {
                "title": "Table des Matières",
                "depth": 3
            }
        },
        {
            "widget_type": "page_break",
            "widget_key": "break_2",
            "position": 3,
            "config": {}
        },
        {
            "widget_type": "title",
            "widget_key": "context_title",
            "position": 4,
            "config": {
                "text": "Contexte et Périmètre",
                "level": 1
            }
        },
        {
            "widget_type": "paragraph",
            "widget_key": "context_text",
            "position": 5,
            "config": {
                "text": "Audit réalisé pour %client.name% selon le référentiel %framework.name%."
            }
        },
        {
            "widget_type": "page_break",
            "widget_key": "break_3",
            "position": 6,
            "config": {}
        },
        {
            "widget_type": "loop_domains",
            "widget_key": "domains_loop",
            "position": 7,
            "config": {
                "children": [
                    {
                        "widget_type": "title",
                        "config": {"text": "%domain.name%", "level": 1}
                    },
                    {
                        "widget_type": "description",
                        "config": {"text": "%domain.description%"}
                    },
                    {
                        "widget_type": "metrics",
                        "config": {
                            "metrics": [
                                {"label": "Score", "value": "%domain.score%", "type": "score"},
                                {"label": "Questions", "value": "%domain.total_questions%", "type": "count"}
                            ]
                        }
                    },
                    {
                        "widget_type": "questions_table",
                        "config": {
                            "domain_id": "%domain.id%",
                            "columns": ["question", "response", "compliance", "comment"]
                        }
                    },
                    {
                        "widget_type": "page_break",
                        "config": {}
                    }
                ]
            }
        },
        {
            "widget_type": "title",
            "widget_key": "nc_synthesis_title",
            "position": 8,
            "config": {
                "text": "Synthèse des Non-Conformités",
                "level": 1
            }
        },
        {
            "widget_type": "nc_table",
            "widget_key": "all_nc_table",
            "position": 9,
            "config": {
                "severity": "all",
                "columns": ["domain", "question", "risk_level", "comment", "evidence"]
            }
        },
        {
            "widget_type": "page_break",
            "widget_key": "break_final",
            "position": 10,
            "config": {}
        },
        {
            "widget_type": "title",
            "widget_key": "action_plan_title",
            "position": 11,
            "config": {
                "text": "Plan d'Action Complet",
                "level": 1
            }
        },
        {
            "widget_type": "actions_table",
            "widget_key": "full_actions_table",
            "position": 12,
            "config": {
                "columns": ["title", "description", "severity", "priority", "due_days", "suggested_role", "deliverables"]
            }
        }
    ]
}


# ============================================================================
# TEMPLATE 3 : FOURNISSEURS
# ============================================================================

TEMPLATE_SUPPLIERS = {
    "id": uuid.uuid4(),
    "tenant_id": None,
    "name": "Rapport Évaluation Fournisseurs",
    "description": "Évaluation des tiers pour due diligence (15-25 pages)",
    "code": "SYSTEM_SUPPLIERS",
    "template_type": "system",
    "report_scope": "entity",  # Rapport par entité/fournisseur
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
        "primary": "#10B981",
        "secondary": "#3B82F6",
        "accent": "#8B5CF6",
        "danger": "#EF4444",
        "warning": "#F59E0B",
        "success": "#22C55E",
        "text": "#1F2937",
        "background": "#FFFFFF",
        "header_bg": "#047857"
    },
    "fonts": {
        "title": {"family": "Noto Sans JP", "size": 18, "weight": "bold"},
        "heading1": {"family": "Noto Sans JP", "size": 16, "weight": "bold"},
        "heading2": {"family": "Noto Sans JP", "size": 14, "weight": "bold"},
        "heading3": {"family": "Noto Sans JP", "size": 12, "weight": "bold"},
        "body": {"family": "Noto Sans JP", "size": 10, "weight": "normal"}
    },
    "custom_css": None,
    "default_logo": "EVALUATED",
    "structure": [
        {
            "widget_type": "cover",
            "widget_key": "cover_page",
            "position": 0,
            "config": {
                "title": "Évaluation Cybersécurité Fournisseur",
                "subtitle": "%evaluated.name%",
                "date": "%report.date%",
                "logo_position": "EVALUATED"
            }
        },
        {
            "widget_type": "page_break",
            "widget_key": "break_1",
            "position": 1,
            "config": {}
        },
        {
            "widget_type": "toc",
            "widget_key": "toc",
            "position": 2,
            "config": {
                "title": "Sommaire",
                "depth": 2
            }
        },
        {
            "widget_type": "page_break",
            "widget_key": "break_2",
            "position": 3,
            "config": {}
        },
        {
            "widget_type": "title",
            "widget_key": "identity_title",
            "position": 4,
            "config": {
                "text": "Fiche d'Identité",
                "level": 1
            }
        },
        {
            "widget_type": "properties_table",
            "widget_key": "supplier_info",
            "position": 5,
            "config": {
                "properties": [
                    {"label": "Raison Sociale", "value": "%evaluated.name%"},
                    {"label": "SIRET", "value": "%evaluated.siret%"},
                    {"label": "Secteur d'Activité", "value": "%evaluated.naf_label%"},
                    {"label": "Date d'Évaluation", "value": "%report.date%"}
                ]
            }
        },
        {
            "widget_type": "page_break",
            "widget_key": "break_3",
            "position": 6,
            "config": {}
        },
        {
            "widget_type": "title",
            "widget_key": "maturity_title",
            "position": 7,
            "config": {
                "text": "Score de Maturité Cyber",
                "level": 1
            }
        },
        {
            "widget_type": "gauge",
            "widget_key": "maturity_gauge",
            "position": 8,
            "config": {
                "title": "Niveau de Maturité Global",
                "value": "%scores.global%",
                "min": 0,
                "max": 100
            }
        },
        {
            "widget_type": "comparison_chart",
            "widget_key": "sector_comparison",
            "position": 9,
            "config": {
                "title": "Comparaison Sectorielle",
                "series": ["evaluated", "sector"]
            }
        },
        {
            "widget_type": "page_break",
            "widget_key": "break_4",
            "position": 10,
            "config": {}
        },
        {
            "widget_type": "loop_entities",
            "widget_key": "entities_loop",
            "position": 11,
            "config": {
                "children": [
                    {
                        "widget_type": "title",
                        "config": {"text": "%entity.name%", "level": 1}
                    },
                    {
                        "widget_type": "radar_domains",
                        "config": {
                            "title": "Évaluation par Critère",
                            "entity_id": "%entity.id%"
                        }
                    },
                    {
                        "widget_type": "page_break",
                        "config": {}
                    }
                ]
            }
        },
        {
            "widget_type": "title",
            "widget_key": "risks_title",
            "position": 12,
            "config": {
                "text": "Analyse des Risques",
                "level": 1
            }
        },
        {
            "widget_type": "nc_table",
            "widget_key": "risks_table",
            "position": 13,
            "config": {
                "severity": "major",
                "columns": ["domain", "question", "risk_level", "comment"]
            }
        },
        {
            "widget_type": "page_break",
            "widget_key": "break_5",
            "position": 14,
            "config": {}
        },
        {
            "widget_type": "title",
            "widget_key": "recommendations_title",
            "position": 15,
            "config": {
                "text": "Recommandations",
                "level": 1
            }
        },
        {
            "widget_type": "actions_table",
            "widget_key": "recommendations_table",
            "position": 16,
            "config": {
                "priority_filter": ["P1"],
                "columns": ["title", "severity", "due_days"]
            }
        }
    ]
}


# ============================================================================
# TEMPLATE 4 : INDIVIDUEL PAR ENTITÉ
# ============================================================================

TEMPLATE_INDIVIDUAL = {
    "id": uuid.uuid4(),
    "tenant_id": None,
    "name": "Rapport Individuel",
    "description": "Rapport d'audit détaillé pour une entité spécifique (10-20 pages)",
    "code": "SYSTEM_INDIVIDUAL",
    "template_type": "executive",
    "report_scope": "entity",  # Uniquement pour rapports individuels
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
        "primary": "#6366F1",
        "secondary": "#8B5CF6",
        "accent": "#10B981",
        "danger": "#EF4444",
        "warning": "#F59E0B",
        "success": "#22C55E",
        "text": "#1F2937",
        "background": "#FFFFFF",
        "header_bg": "#4338CA"
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
        # Page de garde
        {
            "widget_type": "cover",
            "widget_key": "cover_page",
            "position": 0,
            "config": {
                "title": "%entity.name%",
                "subtitle": "Rapport d'Audit de Cybersécurité",
                "date": "%report.date%",
                "logo_source": "entity",
                "confidentiality": "CONFIDENTIEL - Document réservé à l'entité auditée"
            }
        },
        {
            "widget_type": "page_break",
            "widget_key": "break_1",
            "position": 1,
            "config": {}
        },
        # Sommaire
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
            "widget_key": "break_2",
            "position": 3,
            "config": {}
        },
        # Résumé exécutif généré par IA
        {
            "widget_type": "ai_summary",
            "widget_key": "ai_executive_summary",
            "position": 4,
            "config": {
                "title": "Résumé Exécutif",
                "tone": "executive",
                "report_scope": "individual",
                "use_ai": True,
                "editable": True,
                "max_words": 400
            }
        },
        {
            "widget_type": "page_break",
            "widget_key": "break_3",
            "position": 5,
            "config": {}
        },
        # Indicateurs clés KPI
        {
            "widget_type": "title",
            "widget_key": "kpi_title",
            "position": 6,
            "config": {
                "text": "Indicateurs Clés de Performance",
                "level": 1
            }
        },
        {
            "widget_type": "kpi",
            "widget_key": "main_kpis",
            "position": 7,
            "config": {
                "title": "",
                "layout": "grid",
                "show_global_score": True,
                "show_domains_count": True,
                "show_questions_count": True,
                "show_nc_count": True,
                "show_entities_count": False
            }
        },
        # Jauge de maturité
        {
            "widget_type": "gauge",
            "widget_key": "maturity_gauge",
            "position": 8,
            "config": {
                "title": "Score de Maturité Global",
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
        {
            "widget_type": "page_break",
            "widget_key": "break_4",
            "position": 9,
            "config": {}
        },
        # Positionnement / Benchmarking
        {
            "widget_type": "title",
            "widget_key": "benchmark_title",
            "position": 10,
            "config": {
                "text": "Positionnement",
                "level": 1
            }
        },
        {
            "widget_type": "benchmark",
            "widget_key": "benchmark_widget",
            "position": 11,
            "config": {
                "title": "Comparaison avec les pairs",
                "show_position": True,
                "show_average": True,
                "show_delta": True
            }
        },
        {
            "widget_type": "page_break",
            "widget_key": "break_5",
            "position": 12,
            "config": {}
        },
        # Scores par domaine
        {
            "widget_type": "title",
            "widget_key": "domains_title",
            "position": 13,
            "config": {
                "text": "Analyse par Domaine",
                "level": 1
            }
        },
        {
            "widget_type": "radar_domains",
            "widget_key": "radar_chart",
            "position": 14,
            "config": {
                "title": "Vue Radar des Domaines",
                "series": ["evaluated"],
                "show_legend": True
            }
        },
        {
            "widget_type": "domain_scores",
            "widget_key": "domain_scores_table",
            "position": 15,
            "config": {
                "title": "Scores Détaillés par Domaine",
                "show_progress_bar": True,
                "sort_by": "score",
                "order": "asc"
            }
        },
        {
            "widget_type": "page_break",
            "widget_key": "break_6",
            "position": 16,
            "config": {}
        },
        # Non-conformités
        {
            "widget_type": "title",
            "widget_key": "nc_title",
            "position": 17,
            "config": {
                "text": "Non-Conformités Identifiées",
                "level": 1
            }
        },
        {
            "widget_type": "nc_table",
            "widget_key": "nc_table_major",
            "position": 18,
            "config": {
                "title": "Non-Conformités Majeures",
                "severity": "major",
                "limit": 15,
                "columns": ["domain", "question", "risk_level", "comment"]
            }
        },
        {
            "widget_type": "nc_table",
            "widget_key": "nc_table_minor",
            "position": 19,
            "config": {
                "title": "Non-Conformités Mineures",
                "severity": "minor",
                "limit": 10,
                "columns": ["domain", "question", "risk_level", "comment"]
            }
        },
        {
            "widget_type": "page_break",
            "widget_key": "break_7",
            "position": 20,
            "config": {}
        },
        # Plan d'action
        {
            "widget_type": "title",
            "widget_key": "actions_title",
            "position": 21,
            "config": {
                "text": "Plan d'Action Recommandé",
                "level": 1
            }
        },
        {
            "widget_type": "action_plan",
            "widget_key": "action_plan_widget",
            "position": 22,
            "config": {
                "title": "Actions Prioritaires",
                "limit": 15,
                "show_priority": True,
                "show_deadline": True,
                "show_responsible": False
            }
        },
        {
            "widget_type": "page_break",
            "widget_key": "break_8",
            "position": 23,
            "config": {}
        },
        # Conclusion
        {
            "widget_type": "title",
            "widget_key": "conclusion_title",
            "position": 24,
            "config": {
                "text": "Conclusion",
                "level": 1
            }
        },
        {
            "widget_type": "ai_summary",
            "widget_key": "ai_conclusion",
            "position": 25,
            "config": {
                "title": "Synthèse et Recommandations",
                "tone": "technical",
                "report_scope": "individual",
                "use_ai": True,
                "editable": True,
                "max_words": 300
            }
        }
    ]
}


# ============================================================================
# TEMPLATE 5 : SCAN INDIVIDUEL
# ============================================================================

TEMPLATE_SCAN_INDIVIDUAL = {
    "id": uuid.uuid4(),
    "tenant_id": None,  # Template système
    "name": "Rapport Scan Individuel",
    "description": "Rapport détaillé d'un scan de vulnérabilités externe (6-10 pages)",
    "code": "SYSTEM_SCAN_INDIVIDUAL",
    "template_type": "technical",
    "report_scope": "scan_individual",  # Scope scanner individuel
    "is_system": True,
    "is_default": True,  # Template par défaut pour scans individuels
    "page_size": "A4",
    "orientation": "portrait",
    "margins": {
        "top": 20,
        "right": 15,
        "bottom": 20,
        "left": 15
    },
    "color_scheme": {
        "primary": "#0891B2",  # Cyan (Scanner menu)
        "secondary": "#0E7490",  # Cyan foncé
        "accent": "#06B6D4",  # Cyan clair
        "danger": "#EF4444",
        "warning": "#F59E0B",
        "success": "#22C55E",
        "text": "#1F2937",
        "background": "#FFFFFF",
        "header_bg": "#0E7490"  # Cyan-700 (harmonisé menu Scanner)
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
        # Page de garde
        {
            "widget_type": "cover",
            "widget_key": "cover_page",
            "position": 0,
            "config": {
                "title": "Rapport de Scan de Vulnérabilités",
                "subtitle": "%scan.target%",
                "date": "%report.date%",
                "logo_position": "TENANT",
                "confidentiality": "CONFIDENTIEL - Surface d'attaque externe"
            }
        },
        {
            "widget_type": "page_break",
            "widget_key": "break_1",
            "position": 1,
            "config": {}
        },
        # Sommaire
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
            "widget_key": "break_2",
            "position": 3,
            "config": {}
        },
        # Résumé du scan
        {
            "widget_type": "title",
            "widget_key": "summary_title",
            "position": 4,
            "config": {
                "text": "Résumé du Scan",
                "level": 1
            }
        },
        {
            "widget_type": "scan_summary",
            "widget_key": "scan_summary_widget",
            "position": 5,
            "config": {
                "show_target": True,
                "show_entity": True,
                "show_date": True,
                "show_status": True,
                "show_duration": True
            }
        },
        # Score d'exposition
        {
            "widget_type": "scan_exposure_score",
            "widget_key": "exposure_score_widget",
            "position": 6,
            "config": {
                "title": "Score d'Exposition",
                "show_gauge": True,
                "show_cvss_avg": True,
                "show_cvss_max": True,
                "show_risk_level": True
            }
        },
        {
            "widget_type": "page_break",
            "widget_key": "break_3",
            "position": 7,
            "config": {}
        },
        # Positionnement dans l'écosystème
        {
            "widget_type": "title",
            "widget_key": "positioning_title",
            "position": 8,
            "config": {
                "text": "Positionnement dans l'Écosystème",
                "level": 1
            }
        },
        {
            "widget_type": "paragraph",
            "widget_key": "positioning_description",
            "position": 9,
            "config": {
                "text": "Ce graphique positionne l'entité scannée par rapport aux autres organismes de votre écosystème. L'axe X représente le nombre de CVEs, l'axe Y le score CVSS moyen. Plus un point est en haut à droite, plus le risque est élevé."
            }
        },
        {
            "widget_type": "scan_ecosystem_scatter",
            "widget_key": "positioning_chart",
            "position": 10,
            "config": {
                "title": "Position dans l'Écosystème",
                "highlight_current": True,
                "show_legend": True,
                "x_axis": "cve_count",
                "y_axis": "cvss_avg"
            }
        },
        {
            "widget_type": "page_break",
            "widget_key": "break_4",
            "position": 11,
            "config": {}
        },
        # Vulnérabilités détectées
        {
            "widget_type": "title",
            "widget_key": "vulns_title",
            "position": 12,
            "config": {
                "text": "Vulnérabilités Détectées",
                "level": 1
            }
        },
        {
            "widget_type": "scan_cvss_distribution",
            "widget_key": "cvss_distribution_chart",
            "position": 13,
            "config": {
                "title": "Distribution par Sévérité CVSS",
                "show_labels": True,
                "colors": {
                    "critical": "#991B1B",
                    "high": "#DC2626",
                    "medium": "#F97316",
                    "low": "#EAB308",
                    "info": "#60A5FA"
                }
            }
        },
        {
            "widget_type": "scan_vulnerabilities_table",
            "widget_key": "vulns_table",
            "position": 14,
            "config": {
                "title": "Liste des Vulnérabilités",
                "columns": ["cve_id", "severity", "cvss_score", "description", "affected_service"],
                "sort_by": "cvss_score",
                "order": "desc",
                "limit": 30
            }
        },
        {
            "widget_type": "page_break",
            "widget_key": "break_5",
            "position": 15,
            "config": {}
        },
        # Services exposés
        {
            "widget_type": "title",
            "widget_key": "services_title",
            "position": 16,
            "config": {
                "text": "Services Exposés",
                "level": 1
            }
        },
        {
            "widget_type": "scan_services_table",
            "widget_key": "services_table",
            "position": 17,
            "config": {
                "title": "Ports et Services Détectés",
                "columns": ["port", "protocol", "service", "version", "state"],
                "show_risk_indicator": True
            }
        },
        {
            "widget_type": "page_break",
            "widget_key": "break_6",
            "position": 18,
            "config": {}
        },
        # Analyse TLS/SSL
        {
            "widget_type": "title",
            "widget_key": "tls_title",
            "position": 19,
            "config": {
                "text": "Analyse TLS/SSL",
                "level": 1
            }
        },
        {
            "widget_type": "scan_tls_analysis",
            "widget_key": "tls_analysis_widget",
            "position": 20,
            "config": {
                "show_grade": True,
                "show_certificate_info": True,
                "show_protocols": True,
                "show_cipher_suites": True,
                "show_vulnerabilities": True
            }
        },
        {
            "widget_type": "page_break",
            "widget_key": "break_7",
            "position": 21,
            "config": {}
        },
        # Recommandations
        {
            "widget_type": "title",
            "widget_key": "recommendations_title",
            "position": 22,
            "config": {
                "text": "Recommandations",
                "level": 1
            }
        },
        {
            "widget_type": "scan_recommendations",
            "widget_key": "recommendations_widget",
            "position": 23,
            "config": {
                "show_priority": True,
                "group_by": "severity",
                "limit": 15
            }
        }
    ]
}


# ============================================================================
# TEMPLATE 6 : SCAN ÉCOSYSTÈME
# ============================================================================

TEMPLATE_SCAN_ECOSYSTEM = {
    "id": uuid.uuid4(),
    "tenant_id": None,  # Template système
    "name": "Rapport Écosystème Scanner",
    "description": "Vue consolidée de tous les scans de votre écosystème (8-15 pages)",
    "code": "SYSTEM_SCAN_ECOSYSTEM",
    "template_type": "executive",
    "report_scope": "scan_ecosystem",  # Scope écosystème scanner
    "is_system": True,
    "is_default": True,  # Template par défaut pour vue écosystème
    "page_size": "A4",
    "orientation": "portrait",
    "margins": {
        "top": 20,
        "right": 15,
        "bottom": 20,
        "left": 15
    },
    "color_scheme": {
        "primary": "#0891B2",  # Cyan (Scanner menu)
        "secondary": "#0E7490",  # Cyan foncé
        "accent": "#06B6D4",  # Cyan clair
        "danger": "#EF4444",
        "warning": "#F59E0B",
        "success": "#22C55E",
        "text": "#1F2937",
        "background": "#FFFFFF",
        "header_bg": "#0E7490"  # Cyan-700 (harmonisé menu Scanner)
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
        # Page de garde
        {
            "widget_type": "cover",
            "widget_key": "cover_page",
            "position": 0,
            "config": {
                "title": "Rapport Écosystème - Surface d'Attaque",
                "subtitle": "Vue consolidée des scans de vulnérabilités",
                "date": "%report.date%",
                "logo_position": "TENANT",
                "confidentiality": "CONFIDENTIEL - Vue écosystème"
            }
        },
        {
            "widget_type": "page_break",
            "widget_key": "break_1",
            "position": 1,
            "config": {}
        },
        # Sommaire
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
            "widget_key": "break_2",
            "position": 3,
            "config": {}
        },
        # Résumé exécutif
        {
            "widget_type": "title",
            "widget_key": "executive_summary_title",
            "position": 4,
            "config": {
                "text": "Résumé Exécutif",
                "level": 1
            }
        },
        {
            "widget_type": "metrics",
            "widget_key": "key_metrics",
            "position": 5,
            "config": {
                "metrics": [
                    {"label": "Entités Scannées", "value": "%ecosystem.entities_count%", "type": "count"},
                    {"label": "Total CVEs", "value": "%ecosystem.total_cves%", "type": "count"},
                    {"label": "CVEs Critiques", "value": "%ecosystem.critical_cves%", "type": "count"},
                    {"label": "Score CVSS Moyen", "value": "%ecosystem.avg_cvss%", "type": "score"}
                ]
            }
        },
        {
            "widget_type": "scan_risk_gauge",
            "widget_key": "global_risk_gauge",
            "position": 6,
            "config": {
                "title": "Niveau de Risque Global",
                "value": "%ecosystem.risk_score%",
                "min": 0,
                "max": 10,
                "thresholds": [
                    {"value": 3, "color": "#22C55E", "label": "Faible"},
                    {"value": 6, "color": "#F59E0B", "label": "Moyen"},
                    {"value": 8, "color": "#F97316", "label": "Élevé"},
                    {"value": 10, "color": "#DC2626", "label": "Critique"}
                ]
            }
        },
        {
            "widget_type": "page_break",
            "widget_key": "break_3",
            "position": 7,
            "config": {}
        },
        # Vue écosystème - Nuage de points
        {
            "widget_type": "title",
            "widget_key": "ecosystem_title",
            "position": 8,
            "config": {
                "text": "Positionnement des Organismes",
                "level": 1
            }
        },
        {
            "widget_type": "paragraph",
            "widget_key": "ecosystem_description",
            "position": 9,
            "config": {
                "text": "Ce graphique positionne chaque organisme de votre écosystème selon son exposition aux vulnérabilités. L'axe horizontal représente le nombre de CVEs détectées, l'axe vertical le score CVSS moyen. La taille des points indique le niveau d'exposition global."
            }
        },
        {
            "widget_type": "scan_ecosystem_scatter",
            "widget_key": "ecosystem_scatter_chart",
            "position": 10,
            "config": {
                "title": "Carte des Risques Écosystème",
                "highlight_current": False,
                "show_legend": True,
                "show_labels": True,
                "x_axis": "cve_count",
                "y_axis": "cvss_avg",
                "color_by": "risk_level"
            }
        },
        {
            "widget_type": "page_break",
            "widget_key": "break_4",
            "position": 11,
            "config": {}
        },
        # Comparaison des entités
        {
            "widget_type": "title",
            "widget_key": "comparison_title",
            "position": 12,
            "config": {
                "text": "Comparaison des Entités",
                "level": 1
            }
        },
        {
            "widget_type": "scan_comparison_table",
            "widget_key": "entities_comparison_table",
            "position": 13,
            "config": {
                "title": "Tableau Comparatif",
                "columns": ["entity_name", "target", "total_cves", "critical", "high", "medium", "cvss_avg", "last_scan"],
                "sort_by": "cvss_avg",
                "order": "desc",
                "show_risk_indicator": True
            }
        },
        {
            "widget_type": "page_break",
            "widget_key": "break_5",
            "position": 14,
            "config": {}
        },
        # Top vulnérabilités
        {
            "widget_type": "title",
            "widget_key": "top_vulns_title",
            "position": 15,
            "config": {
                "text": "Top Vulnérabilités Critiques",
                "level": 1
            }
        },
        {
            "widget_type": "scan_top_vulnerabilities",
            "widget_key": "top_vulns_widget",
            "position": 16,
            "config": {
                "title": "Vulnérabilités les Plus Critiques",
                "limit": 15,
                "min_severity": "high",
                "columns": ["cve_id", "cvss_score", "affected_entities", "description"],
                "group_by_cve": True
            }
        },
        {
            "widget_type": "page_break",
            "widget_key": "break_6",
            "position": 17,
            "config": {}
        },
        # Distribution des vulnérabilités
        {
            "widget_type": "title",
            "widget_key": "distribution_title",
            "position": 18,
            "config": {
                "text": "Distribution des Vulnérabilités",
                "level": 1
            }
        },
        {
            "widget_type": "scan_cvss_distribution",
            "widget_key": "cvss_distribution_ecosystem",
            "position": 19,
            "config": {
                "title": "Répartition par Sévérité CVSS",
                "show_labels": True,
                "show_percentages": True,
                "aggregation": "ecosystem",
                "colors": {
                    "critical": "#991B1B",
                    "high": "#DC2626",
                    "medium": "#F97316",
                    "low": "#EAB308",
                    "info": "#60A5FA"
                }
            }
        },
        {
            "widget_type": "page_break",
            "widget_key": "break_7",
            "position": 20,
            "config": {}
        },
        # Historique et tendances
        {
            "widget_type": "title",
            "widget_key": "history_title",
            "position": 21,
            "config": {
                "text": "Évolution Temporelle",
                "level": 1
            }
        },
        {
            "widget_type": "scan_history_chart",
            "widget_key": "history_chart",
            "position": 22,
            "config": {
                "title": "Évolution du Nombre de CVEs",
                "period": "6_months",
                "show_trend": True,
                "metrics": ["total_cves", "critical_cves"]
            }
        },
        {
            "widget_type": "page_break",
            "widget_key": "break_8",
            "position": 23,
            "config": {}
        },
        # Recommandations globales
        {
            "widget_type": "title",
            "widget_key": "recommendations_title",
            "position": 24,
            "config": {
                "text": "Recommandations Prioritaires",
                "level": 1
            }
        },
        {
            "widget_type": "scan_recommendations",
            "widget_key": "global_recommendations",
            "position": 25,
            "config": {
                "show_priority": True,
                "group_by": "entity",
                "limit": 20,
                "scope": "ecosystem"
            }
        }
    ]
}


def seed_templates():
    """Insère les templates système dans la base."""

    print("=" * 80)
    print("INSERTION DES TEMPLATES SYSTÈME")
    print("=" * 80)
    print()

    db = SessionLocal()
    try:
        # Liste des codes système
        system_codes = [
            'SYSTEM_EXECUTIVE',
            'SYSTEM_TECHNICAL',
            'SYSTEM_SUPPLIERS',
            'SYSTEM_INDIVIDUAL',
            'SYSTEM_SCAN_INDIVIDUAL',
            'SYSTEM_SCAN_ECOSYSTEM'
        ]

        # Vérifier si les templates existent déjà
        check_query = text("""
            SELECT code FROM report_template
            WHERE code IN :codes
        """)

        existing = db.execute(check_query, {"codes": tuple(system_codes)})
        existing_codes = [row[0] for row in existing.fetchall()]

        if existing_codes:
            print(f"[WARN] Templates deja existants: {existing_codes}")
            print("   Suppression et recreation...")

            delete_query = text("""
                DELETE FROM report_template
                WHERE code IN :codes
            """)
            db.execute(delete_query, {"codes": tuple(system_codes)})
            db.commit()

        # Insertion des templates
        templates = [
            TEMPLATE_EXECUTIVE,
            TEMPLATE_TECHNICAL,
            TEMPLATE_SUPPLIERS,
            TEMPLATE_INDIVIDUAL,
            TEMPLATE_SCAN_INDIVIDUAL,
            TEMPLATE_SCAN_ECOSYSTEM
        ]

        for template in templates:
            print(f"[OK] Insertion template: {template['name']} ({template['code']}) - scope: {template['report_scope']}")

            # Convertir les dicts en JSON pour PostgreSQL
            template_copy = template.copy()
            template_copy['margins'] = json.dumps(template_copy['margins'])
            template_copy['color_scheme'] = json.dumps(template_copy['color_scheme'])
            template_copy['fonts'] = json.dumps(template_copy['fonts'])
            template_copy['structure'] = json.dumps(template_copy['structure'])

            insert_query = text("""
                INSERT INTO report_template (
                    id, tenant_id, name, description, code, template_type,
                    report_scope, is_system, is_default, page_size, orientation,
                    margins, color_scheme, fonts, custom_css, default_logo,
                    structure, created_at, updated_at
                ) VALUES (
                    :id, :tenant_id, :name, :description, :code, :template_type,
                    :report_scope, :is_system, :is_default, :page_size, :orientation,
                    CAST(:margins AS jsonb), CAST(:color_scheme AS jsonb), CAST(:fonts AS jsonb), :custom_css, :default_logo,
                    CAST(:structure AS jsonb), :created_at, :updated_at
                )
            """)

            db.execute(insert_query, {
                **template_copy,
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc)
            })

        db.commit()

        print()
        print("[SUCCESS] Templates systeme inseres avec succes!")
        print()
        print("Templates disponibles:")
        print("  - SYSTEM_EXECUTIVE       : Rapport Executif (consolidated - par défaut)")
        print("  - SYSTEM_TECHNICAL       : Rapport Technique (both)")
        print("  - SYSTEM_SUPPLIERS       : Rapport Fournisseurs (entity)")
        print("  - SYSTEM_INDIVIDUAL      : Rapport Individuel (entity)")
        print("  - SYSTEM_SCAN_INDIVIDUAL : Rapport Scan Individuel (scan_individual)")
        print("  - SYSTEM_SCAN_ECOSYSTEM  : Rapport Écosystème Scanner (scan_ecosystem)")
        print()

    except Exception as e:
        db.rollback()
        print(f"[ERROR] Erreur lors de l'insertion: {str(e)}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_templates()
