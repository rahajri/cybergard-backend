"""
Script pour insérer les templates système EBIOS RM.

Ce script crée les templates maîtres pour les rapports EBIOS Risk Manager :
- SYSTEM_EBIOS_CONSOLIDATED : Rapport consolidé (vue d'ensemble)
- SYSTEM_EBIOS_INDIVIDUAL : Rapport individuel (par scénario)

Ils seront ensuite dupliqués pour chaque tenant par le script de duplication.

Usage (depuis le dossier backend):
    python insert_ebios_template.py
"""

import sys
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4
import json

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import text
from src.database import SessionLocal


# ============================================================================
# STRUCTURE DU TEMPLATE EBIOS RM CONSOLIDÉ
# ============================================================================
EBIOS_CONSOLIDATED_STRUCTURE = [
    # Page de couverture
    {
        "widget_type": "cover",
        "config": {
            "title": "Rapport d'Analyse de Risques",
            "subtitle": "EBIOS Risk Manager",
            "show_logo": True,
            "show_date": True,
            "show_version": True,
            "background_color": "#dc2626"
        }
    },
    # Table des matières
    {
        "widget_type": "toc",
        "config": {
            "title": "Table des Matières",
            "max_depth": 3,
            "show_page_numbers": True
        }
    },
    # Résumé exécutif
    {
        "widget_type": "section",
        "config": {
            "title": "Résumé Exécutif",
            "level": 1
        }
    },
    {
        "widget_type": "ai_summary",
        "config": {
            "section": "executive_summary",
            "tone": "executive",
            "placeholder": "Ce résumé sera généré automatiquement par l'IA en fonction des données de l'analyse."
        }
    },
    # AT1 - Cadrage et socle de sécurité
    {
        "widget_type": "page_break",
        "config": {}
    },
    {
        "widget_type": "section",
        "config": {
            "title": "AT1 - Cadrage et Socle de Sécurité",
            "level": 1,
            "description": "Identification des valeurs métier, biens supports et événements redoutés."
        }
    },
    {
        "widget_type": "ai_summary",
        "config": {
            "section": "at1_summary",
            "tone": "executive"
        }
    },
    {
        "widget_type": "section",
        "config": {
            "title": "Valeurs Métier",
            "level": 2
        }
    },
    {
        "widget_type": "ebios_table",
        "config": {
            "data_source": "at1.business_values",
            "columns": [
                {"key": "code", "label": "Code", "width": "10%"},
                {"key": "label", "label": "Libellé", "width": "25%"},
                {"key": "description", "label": "Description", "width": "45%"},
                {"key": "criticality", "label": "Criticité", "width": "20%", "style": "badge"}
            ]
        }
    },
    {
        "widget_type": "section",
        "config": {
            "title": "Biens Supports",
            "level": 2
        }
    },
    {
        "widget_type": "ebios_table",
        "config": {
            "data_source": "at1.assets",
            "columns": [
                {"key": "code", "label": "Code", "width": "10%"},
                {"key": "label", "label": "Libellé", "width": "25%"},
                {"key": "asset_type", "label": "Type", "width": "20%"},
                {"key": "description", "label": "Description", "width": "45%"}
            ]
        }
    },
    {
        "widget_type": "section",
        "config": {
            "title": "Événements Redoutés",
            "level": 2
        }
    },
    {
        "widget_type": "ebios_table",
        "config": {
            "data_source": "at1.feared_events",
            "columns": [
                {"key": "code", "label": "Code", "width": "10%"},
                {"key": "label", "label": "Libellé", "width": "35%"},
                {"key": "impacts", "label": "Impacts", "width": "35%"},
                {"key": "severity", "label": "Gravité", "width": "20%", "style": "risk_level"}
            ]
        }
    },
    # AT2 - Sources de risques
    {
        "widget_type": "page_break",
        "config": {}
    },
    {
        "widget_type": "section",
        "config": {
            "title": "AT2 - Sources de Risques",
            "level": 1,
            "description": "Identification et évaluation des sources de risques et de leurs objectifs visés."
        }
    },
    {
        "widget_type": "ai_summary",
        "config": {
            "section": "at2_summary",
            "tone": "executive"
        }
    },
    {
        "widget_type": "ebios_table",
        "config": {
            "data_source": "at2.risk_sources",
            "columns": [
                {"key": "code", "label": "Code", "width": "8%"},
                {"key": "label", "label": "Source", "width": "20%"},
                {"key": "source_type", "label": "Type", "width": "12%"},
                {"key": "motivation", "label": "Motivation", "width": "25%"},
                {"key": "resources", "label": "Ressources", "width": "20%"},
                {"key": "pertinence", "label": "Pertinence", "width": "15%", "style": "risk_level"}
            ]
        }
    },
    # AT3 - Scénarios stratégiques
    {
        "widget_type": "page_break",
        "config": {}
    },
    {
        "widget_type": "section",
        "config": {
            "title": "AT3 - Scénarios Stratégiques",
            "level": 1,
            "description": "Élaboration des scénarios stratégiques de haut niveau reliant sources de risques et événements redoutés."
        }
    },
    {
        "widget_type": "ebios_table",
        "config": {
            "data_source": "at3.strategic_scenarios",
            "columns": [
                {"key": "code", "label": "Code", "width": "8%"},
                {"key": "title", "label": "Titre", "width": "30%"},
                {"key": "risk_source.code", "label": "Source", "width": "12%"},
                {"key": "feared_event.code", "label": "ER", "width": "12%"},
                {"key": "severity", "label": "G", "width": "8%"},
                {"key": "likelihood", "label": "V", "width": "8%"},
                {"key": "risk_level", "label": "Niveau", "width": "12%", "style": "risk_level"}
            ]
        }
    },
    # AT4 - Scénarios opérationnels
    {
        "widget_type": "page_break",
        "config": {}
    },
    {
        "widget_type": "section",
        "config": {
            "title": "AT4 - Scénarios Opérationnels",
            "level": 1,
            "description": "Déclinaison des scénarios stratégiques en chemins d'attaque techniques."
        }
    },
    {
        "widget_type": "ebios_table",
        "config": {
            "data_source": "at4.operational_scenarios",
            "columns": [
                {"key": "code", "label": "Code", "width": "8%"},
                {"key": "title", "label": "Titre", "width": "35%"},
                {"key": "strategic_scenario.code", "label": "SS", "width": "10%"},
                {"key": "severity", "label": "G", "width": "8%"},
                {"key": "likelihood", "label": "V", "width": "8%"},
                {"key": "risk_level", "label": "Niveau", "width": "12%", "style": "risk_level"}
            ]
        }
    },
    # AT5 - Matrice des risques
    {
        "widget_type": "page_break",
        "config": {}
    },
    {
        "widget_type": "section",
        "config": {
            "title": "AT5 - Matrice des Risques",
            "level": 1,
            "description": "Synthèse des niveaux de risques et aide à la décision pour le traitement."
        }
    },
    {
        "widget_type": "ai_summary",
        "config": {
            "section": "risk_analysis",
            "tone": "executive"
        }
    },
    {
        "widget_type": "ebios_risk_matrix",
        "config": {
            "title": "Répartition des Risques",
            "show_legend": True,
            "show_counts": True,
            "levels": [
                {"min": 16, "max": 25, "label": "Critique", "color": "#dc2626"},
                {"min": 9, "max": 15, "label": "Important", "color": "#f97316"},
                {"min": 4, "max": 8, "label": "Modéré", "color": "#eab308"},
                {"min": 1, "max": 3, "label": "Faible", "color": "#22c55e"}
            ]
        }
    },
    # AT6 - Plan de traitement des risques
    {
        "widget_type": "page_break",
        "config": {}
    },
    {
        "widget_type": "section",
        "config": {
            "title": "AT6 - Plan de Traitement des Risques",
            "level": 1,
            "description": "Mesures de sécurité préconisées pour réduire les risques identifiés."
        }
    },
    {
        "widget_type": "section",
        "config": {
            "title": "Vue Synthétique",
            "level": 2
        }
    },
    {
        "widget_type": "ebios_table",
        "config": {
            "data_source": "at6.actions",
            "columns": [
                {"key": "code_action", "label": "Code", "width": "10%"},
                {"key": "titre", "label": "Titre", "width": "35%"},
                {"key": "categorie", "label": "Catégorie", "width": "20%"},
                {"key": "priorite", "label": "Priorité", "width": "10%", "style": "priority"},
                {"key": "statut", "label": "Statut", "width": "15%", "style": "status"},
                {"key": "echeance", "label": "Échéance", "width": "10%"}
            ]
        }
    },
    {
        "widget_type": "section",
        "config": {
            "title": "Fiches Actions Détaillées",
            "level": 2
        }
    },
    {
        "widget_type": "ebios_action_cards",
        "config": {
            "data_source": "at6.actions",
            "fields": [
                {"key": "code_action", "label": "Code"},
                {"key": "titre", "label": "Titre"},
                {"key": "description", "label": "Description"},
                {"key": "categorie", "label": "Catégorie"},
                {"key": "priorite", "label": "Priorité"},
                {"key": "responsable_suggere", "label": "Responsable suggéré"},
                {"key": "effort", "label": "Effort estimé"},
                {"key": "cout_estime", "label": "Coût estimé"},
                {"key": "echeance", "label": "Échéance"},
                {"key": "statut", "label": "Statut"}
            ],
            "show_risk_reduction": True
        }
    },
    # Footer
    {
        "widget_type": "footer",
        "config": {
            "show_page_numbers": True,
            "show_date": True,
            "text": "Rapport généré par Cybergard AI - Méthodologie EBIOS RM (ANSSI)"
        }
    }
]


# ============================================================================
# STRUCTURE DU TEMPLATE EBIOS RM INDIVIDUEL (par scénario)
# ============================================================================
EBIOS_INDIVIDUAL_STRUCTURE = [
    # Page de couverture
    {
        "widget_type": "cover",
        "config": {
            "title": "Fiche Scénario de Risque",
            "subtitle": "EBIOS Risk Manager",
            "show_logo": True,
            "show_date": True,
            "show_scenario_info": True,
            "background_color": "#dc2626"
        }
    },
    # Informations du scénario
    {
        "widget_type": "section",
        "config": {
            "title": "Identification du Scénario",
            "level": 1
        }
    },
    {
        "widget_type": "scenario_header",
        "config": {
            "fields": [
                {"key": "code", "label": "Code"},
                {"key": "title", "label": "Titre"},
                {"key": "type", "label": "Type", "values": {"strategic": "Stratégique", "operational": "Opérationnel"}},
                {"key": "risk_level", "label": "Niveau de risque", "style": "risk_level"}
            ]
        }
    },
    # Description
    {
        "widget_type": "section",
        "config": {
            "title": "Description",
            "level": 2
        }
    },
    {
        "widget_type": "scenario_description",
        "config": {
            "field": "description",
            "show_context": True
        }
    },
    # Évaluation
    {
        "widget_type": "section",
        "config": {
            "title": "Évaluation du Risque",
            "level": 2
        }
    },
    {
        "widget_type": "risk_evaluation",
        "config": {
            "fields": [
                {"key": "severity", "label": "Gravité (G)", "max": 4},
                {"key": "likelihood", "label": "Vraisemblance (V)", "max": 4},
                {"key": "risk_level", "label": "Niveau de risque", "formula": "G × V"}
            ],
            "show_scale": True,
            "show_visual": True
        }
    },
    # Source de risque associée
    {
        "widget_type": "section",
        "config": {
            "title": "Source de Risque Associée",
            "level": 2,
            "condition": "scenario.risk_source"
        }
    },
    {
        "widget_type": "risk_source_card",
        "config": {
            "data_source": "scenario.risk_source",
            "fields": [
                {"key": "code", "label": "Code"},
                {"key": "label", "label": "Libellé"},
                {"key": "source_type", "label": "Type"},
                {"key": "motivation", "label": "Motivation"},
                {"key": "pertinence", "label": "Pertinence"}
            ]
        }
    },
    # Événement redouté associé
    {
        "widget_type": "section",
        "config": {
            "title": "Événement Redouté Associé",
            "level": 2,
            "condition": "scenario.feared_event"
        }
    },
    {
        "widget_type": "feared_event_card",
        "config": {
            "data_source": "scenario.feared_event",
            "fields": [
                {"key": "code", "label": "Code"},
                {"key": "label", "label": "Libellé"},
                {"key": "impacts", "label": "Impacts"},
                {"key": "severity", "label": "Gravité"}
            ]
        }
    },
    # Actions associées
    {
        "widget_type": "page_break",
        "config": {}
    },
    {
        "widget_type": "section",
        "config": {
            "title": "Actions de Traitement",
            "level": 1
        }
    },
    {
        "widget_type": "ai_summary",
        "config": {
            "section": "scenario_actions_summary",
            "tone": "executive"
        }
    },
    {
        "widget_type": "ebios_table",
        "config": {
            "data_source": "scenario.actions",
            "columns": [
                {"key": "code_action", "label": "Code", "width": "12%"},
                {"key": "titre", "label": "Action", "width": "40%"},
                {"key": "categorie", "label": "Catégorie", "width": "18%"},
                {"key": "priorite", "label": "Priorité", "width": "15%", "style": "priority"},
                {"key": "statut", "label": "Statut", "width": "15%", "style": "status"}
            ],
            "empty_message": "Aucune action de traitement définie pour ce scénario."
        }
    },
    # Footer
    {
        "widget_type": "footer",
        "config": {
            "show_page_numbers": True,
            "show_date": True,
            "text": "Fiche scénario EBIOS RM - Cybergard AI"
        }
    }
]


def insert_ebios_templates():
    """Insère les templates système EBIOS RM (Consolidé et Individuel)."""

    print("=" * 70)
    print("INSERTION DES TEMPLATES SYSTÈME EBIOS RM")
    print("=" * 70)
    print()

    # Configuration commune
    color_scheme = {
        "primary": "#dc2626",       # Rouge EBIOS
        "secondary": "#991b1b",     # Rouge foncé
        "accent": "#f87171",        # Rouge clair
        "danger": "#7f1d1d",        # Rouge très foncé
        "warning": "#f59e0b",       # Orange
        "success": "#22c55e",       # Vert
        "text": "#1f2937",          # Gris foncé
        "background": "#ffffff",    # Blanc
        "header_bg": "#dc2626"      # Rouge header
    }

    fonts = {
        "title": {"family": "Segoe UI", "size": 24, "weight": "bold"},
        "heading1": {"family": "Segoe UI", "size": 18, "weight": "bold"},
        "heading2": {"family": "Segoe UI", "size": 14, "weight": "bold"},
        "heading3": {"family": "Segoe UI", "size": 12, "weight": "bold"},
        "body": {"family": "Segoe UI", "size": 10, "weight": "normal"}
    }

    margins = {
        "top": 20,
        "right": 15,
        "bottom": 20,
        "left": 15
    }

    # Templates à créer
    templates = [
        {
            "code": "SYSTEM_EBIOS_CONSOLIDATED",
            "name": "Rapport EBIOS RM Consolidé",
            "description": "Rapport d'analyse de risques complet selon la méthodologie EBIOS Risk Manager de l'ANSSI. Inclut tous les ateliers AT1 à AT6 avec synthèses IA.",
            "report_scope": "consolidated",
            "structure": EBIOS_CONSOLIDATED_STRUCTURE
        },
        {
            "code": "SYSTEM_EBIOS_INDIVIDUAL",
            "name": "Rapport EBIOS RM Individuel",
            "description": "Fiche détaillée d'un scénario de risque EBIOS RM. Utilisé pour générer un rapport par scénario avec son évaluation et ses actions associées.",
            "report_scope": "entity",  # 'entity' = individuel dans le système existant
            "structure": EBIOS_INDIVIDUAL_STRUCTURE
        }
    ]

    db = SessionLocal()
    try:
        created_count = 0

        for template_def in templates:
            # Vérifier si le template existe déjà
            check_query = text("""
                SELECT id FROM report_template
                WHERE code = :code
            """)
            existing = db.execute(check_query, {"code": template_def["code"]}).fetchone()

            if existing:
                print(f"[SKIP] {template_def['code']} existe déjà (ID: {existing[0]})")
                continue

            # Créer le template
            template_id = uuid4()
            now = datetime.now(timezone.utc)

            insert_query = text("""
                INSERT INTO report_template (
                    id, tenant_id, name, description, code, template_type,
                    template_category, report_scope, is_system, is_default, page_size, orientation,
                    margins, color_scheme, fonts, custom_css, default_logo,
                    structure, created_at, updated_at
                ) VALUES (
                    :id, NULL, :name, :description, :code, :template_type,
                    :template_category, :report_scope, true, false, :page_size, :orientation,
                    CAST(:margins AS jsonb), CAST(:color_scheme AS jsonb),
                    CAST(:fonts AS jsonb), :custom_css, :default_logo,
                    CAST(:structure AS jsonb), :created_at, :updated_at
                )
            """)

            db.execute(insert_query, {
                "id": template_id,
                "name": template_def["name"],
                "description": template_def["description"],
                "code": template_def["code"],
                "template_type": "ebios",
                "template_category": "ebios",  # Catégorie EBIOS pour différencier des templates d'audit
                "report_scope": template_def["report_scope"],
                "page_size": "A4",
                "orientation": "portrait",
                "margins": json.dumps(margins),
                "color_scheme": json.dumps(color_scheme),
                "fonts": json.dumps(fonts),
                "custom_css": None,
                "default_logo": "TENANT",
                "structure": json.dumps(template_def["structure"]),
                "created_at": now,
                "updated_at": now
            })

            print(f"[OK] {template_def['code']}")
            print(f"     Nom: {template_def['name']}")
            print(f"     Scope: {template_def['report_scope']}")
            print(f"     Widgets: {len(template_def['structure'])}")
            print()
            created_count += 1

        db.commit()

        print("=" * 70)
        print(f"[SUCCESS] {created_count} template(s) créé(s)")
        print("=" * 70)
        print()
        print("Pour dupliquer ces templates pour tous les tenants existants :")
        print("  python duplicate_ebios_templates_for_tenants.py")
        print()

    except Exception as e:
        db.rollback()
        print(f"[ERROR] Erreur: {str(e)}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    insert_ebios_templates()
