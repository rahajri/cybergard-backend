"""
Script de validation des données avant génération de rapport.

Ce script vérifie que toutes les données nécessaires sont présentes
et valides avant de lancer une génération de rapport.

Usage:
    python scripts/validate_report_generation.py <campaign_id> [--template-code CODE]
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import json
from uuid import UUID
from sqlalchemy import select

from src.database import SessionLocal
from src.services.report_service import ReportService
from src.services.template_validator import (
    TemplateValidator,
    validate_template_before_generation
)
from src.models.report import ReportTemplate
from src.models.campaign import Campaign


def validate_campaign_exists(db, campaign_id: UUID) -> dict:
    """
    Vérifie que la campagne existe et retourne ses informations.

    Returns:
        dict avec infos de la campagne

    Raises:
        ValueError: Si campagne non trouvée
    """
    print(f"\n[1/5] Verification de la campagne {campaign_id}...")

    campaign = db.execute(
        select(Campaign).where(Campaign.id == campaign_id)
    ).scalar_one_or_none()

    if not campaign:
        raise ValueError(f"Campagne {campaign_id} non trouvee")

    print(f"  [OK] Campagne trouvee: '{campaign.title}'")
    print(f"       Status: {campaign.status}")
    print(f"       Questionnaire: {campaign.questionnaire_id}")

    return {
        'id': campaign.id,
        'title': campaign.title,
        'status': campaign.status,
        'questionnaire_id': campaign.questionnaire_id
    }


def validate_template_exists(db, template_code: str = None) -> dict:
    """
    Vérifie que le template existe et est valide.

    Args:
        template_code: Code du template (optionnel, sinon prend le défaut)

    Returns:
        dict avec config du template

    Raises:
        ValueError: Si template non trouvé ou invalide
    """
    print(f"\n[2/5] Verification du template...")

    if template_code:
        template = db.execute(
            select(ReportTemplate).where(ReportTemplate.code == template_code)
        ).scalar_one_or_none()

        if not template:
            raise ValueError(f"Template '{template_code}' non trouve")
    else:
        # Prendre le template par défaut
        template = db.execute(
            select(ReportTemplate).where(ReportTemplate.is_default == True)
        ).scalar_one_or_none()

        if not template:
            raise ValueError("Aucun template par defaut trouve")

    print(f"  [OK] Template: '{template.name}' (code: {template.code})")
    print(f"       Type: {template.template_type}")
    print(f"       Widgets: {len(template.structure)}")

    # Valider la structure du template
    validator = TemplateValidator()
    template_dict = {
        'id': str(template.id),
        'name': template.name,
        'code': template.code,
        'template_type': template.template_type,
        'structure': template.structure,
        'color_scheme': template.color_scheme,
        'fonts': template.fonts
    }

    is_valid, errors = validator.validate_template(template_dict, strict=False)

    if not is_valid:
        print(f"  [WARN] Template a des problemes de validation:")
        for err in errors:
            print(f"         - {err}")
    else:
        print(f"  [OK] Validation du template reussie")

    return template_dict


def validate_campaign_data(db, campaign_id: UUID) -> dict:
    """
    Collecte et valide les données de la campagne.

    Returns:
        dict avec toutes les données collectées

    Raises:
        ValueError: Si données insuffisantes
    """
    print(f"\n[3/5] Collecte des donnees de la campagne...")

    service = ReportService(db)

    # Déterminer le mode
    mode = service.determine_generation_mode(campaign_id)
    print(f"  [INFO] Mode de generation: {mode.value}")

    # Collecter les données
    data = service.collect_campaign_data(campaign_id)

    # Afficher les stats
    stats = data.get('stats', {})
    print(f"\n  [STATS] Statistiques de la campagne:")
    print(f"          Questions totales: {stats.get('total_questions', 0)}")
    print(f"          Questions repondues: {stats.get('answered_questions', 0)}")
    print(f"          Taux de conformite: {stats.get('compliance_rate', 0):.1f}%")
    print(f"          NC majeures: {stats.get('nc_major_count', 0)}")
    print(f"          NC mineures: {stats.get('nc_minor_count', 0)}")

    # Afficher les domaines
    domains = data.get('domains', [])
    print(f"\n  [DOMAINS] {len(domains)} domaines trouves:")
    for domain in domains[:5]:  # Afficher max 5
        print(f"            - {domain['name']}: {domain['score']:.1f}/100")
    if len(domains) > 5:
        print(f"            ... et {len(domains) - 5} autres")

    # Afficher les NC
    nc_major = data.get('nc_major', [])
    nc_minor = data.get('nc_minor', [])
    print(f"\n  [NC] Non-conformites:")
    print(f"       Majeures: {len(nc_major)}")
    print(f"       Mineures: {len(nc_minor)}")

    # Afficher les actions
    actions = data.get('actions', [])
    print(f"\n  [ACTIONS] {len(actions)} actions dans le plan d'action")

    # Validation des données
    validator = TemplateValidator()
    is_valid, errors = validator.validate_generation_data(campaign_id, data)

    if not is_valid:
        print(f"\n  [ERROR] Donnees invalides:")
        for err in errors:
            print(f"          - {err}")
        raise ValueError("Donnees de campagne invalides")

    print(f"\n  [OK] Donnees collectees et validees")

    return data


def validate_full_generation(
    db,
    campaign_id: UUID,
    template_code: str = None
):
    """
    Validation complète : template + données.

    Raises:
        Exception: Si une validation échoue
    """
    print(f"\n[4/5] Validation complete (template + donnees)...")

    # Récupérer template et données
    service = ReportService(db)

    if template_code:
        template = db.execute(
            select(ReportTemplate).where(ReportTemplate.code == template_code)
        ).scalar_one_or_none()
    else:
        template = db.execute(
            select(ReportTemplate).where(ReportTemplate.is_default == True)
        ).scalar_one_or_none()

    template_dict = {
        'id': str(template.id),
        'name': template.name,
        'code': template.code,
        'template_type': template.template_type,
        'structure': template.structure,
        'color_scheme': template.color_scheme,
        'fonts': template.fonts
    }

    data = service.collect_campaign_data(campaign_id)

    # Validation complète
    try:
        validate_template_before_generation(
            template=template_dict,
            data=data,
            campaign_id=campaign_id,
            strict=True
        )
        print(f"  [OK] Validation complete reussie")
    except Exception as e:
        print(f"  [ERROR] Validation complete echouee:")
        print(f"          {str(e)}")
        raise


def estimate_report_size(data: dict) -> dict:
    """
    Estime la taille approximative du rapport généré.

    Returns:
        dict avec estimations (pages, fichier size, etc.)
    """
    print(f"\n[5/5] Estimation de la taille du rapport...")

    # Estimation basée sur le nombre d'éléments
    stats = data.get('stats', {})
    domains = data.get('domains', [])
    nc_major = data.get('nc_major', [])
    nc_minor = data.get('nc_minor', [])
    actions = data.get('actions', [])

    # Pages estimées
    # - Cover: 1 page
    # - TOC: 1 page
    # - Intro + metrics: 1-2 pages
    # - Domains (1 domain = 0.5 page): len(domains) * 0.5
    # - NC table (20 NC par page): (nc_major + nc_minor) / 20
    # - Actions (15 actions par page): len(actions) / 15
    # - Conclusion: 1 page

    estimated_pages = (
        3 +  # Cover + TOC + Intro
        max(1, len(domains) * 0.5) +
        max(1, (len(nc_major) + len(nc_minor)) / 20) +
        max(1, len(actions) / 15) +
        1  # Conclusion
    )

    # Taille fichier (PDF: ~50-100KB par page)
    estimated_size_kb = int(estimated_pages * 75)

    print(f"  [ESTIMATE] Pages: ~{int(estimated_pages)} pages")
    print(f"             Taille fichier: ~{estimated_size_kb} KB")
    print(f"             Temps generation: ~{int(estimated_pages * 2)} secondes")

    return {
        'estimated_pages': int(estimated_pages),
        'estimated_size_kb': estimated_size_kb,
        'estimated_time_seconds': int(estimated_pages * 2)
    }


def main():
    """Point d'entrée du script."""
    parser = argparse.ArgumentParser(
        description="Valide les donnees avant generation de rapport"
    )
    parser.add_argument(
        'campaign_id',
        type=str,
        help="UUID de la campagne"
    )
    parser.add_argument(
        '--template-code',
        type=str,
        default=None,
        help="Code du template (optionnel, sinon utilise le defaut)"
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help="Sortie au format JSON"
    )

    args = parser.parse_args()

    # Parse UUID
    try:
        campaign_id = UUID(args.campaign_id)
    except ValueError:
        print(f"[ERROR] UUID invalide: {args.campaign_id}")
        sys.exit(1)

    # Connexion DB
    db = SessionLocal()

    try:
        print("=" * 80)
        print("VALIDATION DE GENERATION DE RAPPORT")
        print("=" * 80)

        # Étapes de validation
        campaign_info = validate_campaign_exists(db, campaign_id)
        template_info = validate_template_exists(db, args.template_code)
        data = validate_campaign_data(db, campaign_id)
        validate_full_generation(db, campaign_id, args.template_code)
        estimates = estimate_report_size(data)

        print("\n" + "=" * 80)
        print("[SUCCESS] TOUTES LES VALIDATIONS SONT REUSSIES")
        print("=" * 80)
        print("\nLe rapport peut etre genere en toute securite.")

        # Sortie JSON si demandé
        if args.json:
            result = {
                'success': True,
                'campaign': campaign_info,
                'template': {
                    'name': template_info['name'],
                    'code': template_info['code'],
                    'type': template_info['template_type']
                },
                'stats': data.get('stats', {}),
                'estimates': estimates
            }
            print("\nJSON Output:")
            print(json.dumps(result, indent=2, default=str))

        sys.exit(0)

    except Exception as e:
        print("\n" + "=" * 80)
        print("[FAILED] VALIDATION ECHOUEE")
        print("=" * 80)
        print(f"\nErreur: {str(e)}")

        if args.json:
            result = {
                'success': False,
                'error': str(e)
            }
            print("\nJSON Output:")
            print(json.dumps(result, indent=2))

        sys.exit(1)

    finally:
        db.close()


if __name__ == "__main__":
    main()
