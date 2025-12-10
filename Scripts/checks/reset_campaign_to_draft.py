#!/usr/bin/env python3
"""
Script pour remettre une campagne en statut 'draft' pour les tests

Usage:
    python reset_campaign_to_draft.py
    python reset_campaign_to_draft.py --campaign-id <uuid>
    python reset_campaign_to_draft.py --latest
"""
import sys
import os
from pathlib import Path

# Ajouter le répertoire parent au PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import argparse
from datetime import datetime

# Charger les variables d'environnement
load_dotenv()

def reset_campaign_to_draft(campaign_id=None, use_latest=False):
    """
    Remet une campagne en statut 'draft'

    Args:
        campaign_id: UUID de la campagne (optionnel)
        use_latest: Si True, utilise la dernière campagne créée
    """
    DATABASE_URL = os.getenv('DATABASE_URL')
    if not DATABASE_URL:
        print("❌ DATABASE_URL non trouvé dans .env")
        return False

    engine = create_engine(DATABASE_URL)

    try:
        with engine.connect() as conn:
            # Si aucun ID fourni et pas de --latest, afficher la liste
            if not campaign_id and not use_latest:
                result = conn.execute(text("""
                    SELECT id, title, status, created_at
                    FROM campaign
                    ORDER BY created_at DESC
                    LIMIT 10
                """)).fetchall()

                if not result:
                    print("❌ Aucune campagne trouvée dans la base de données")
                    return False

                print("\n📋 Campagnes disponibles:")
                print("-" * 80)
                for i, row in enumerate(result, 1):
                    print(f"{i}. {row[1]}")
                    print(f"   ID: {row[0]}")
                    print(f"   Statut: {row[2]}")
                    print(f"   Créée: {row[3]}")
                    print("-" * 80)

                # Demander à l'utilisateur
                choice = input("\nEntrez le numéro de la campagne à remettre en draft (ou 'q' pour quitter): ")
                if choice.lower() == 'q':
                    return False

                try:
                    idx = int(choice) - 1
                    if 0 <= idx < len(result):
                        campaign_id = str(result[idx][0])
                    else:
                        print("❌ Numéro invalide")
                        return False
                except ValueError:
                    print("❌ Entrée invalide")
                    return False

            # Si --latest, prendre la dernière campagne
            elif use_latest:
                result = conn.execute(text("""
                    SELECT id, title, status
                    FROM campaign
                    ORDER BY created_at DESC
                    LIMIT 1
                """)).fetchone()

                if not result:
                    print("❌ Aucune campagne trouvée")
                    return False

                campaign_id = str(result[0])
                print(f"\n🎯 Campagne sélectionnée: {result[1]} (Statut actuel: {result[2]})")

            # Vérifier que la campagne existe
            campaign = conn.execute(text("""
                SELECT id, title, status, launch_date
                FROM campaign
                WHERE id = :campaign_id
            """), {"campaign_id": campaign_id}).fetchone()

            if not campaign:
                print(f"❌ Campagne {campaign_id} non trouvée")
                return False

            print(f"\n🔍 Campagne: {campaign[1]}")
            print(f"   Statut actuel: {campaign[2]}")
            print(f"   Date de lancement: {campaign[3]}")

            if campaign[2] == 'draft':
                print("✅ La campagne est déjà en statut 'draft'")
                return True

            # Remettre en draft
            conn.execute(text("""
                UPDATE campaign
                SET status = 'draft',
                    launch_date = NULL
                WHERE id = :campaign_id
            """), {"campaign_id": campaign_id})

            conn.commit()

            print(f"\n✅ Campagne {campaign[1]} remise en statut 'draft'")
            print("   - Statut: draft")
            print("   - Date de lancement: réinitialisée")
            print("\nVous pouvez maintenant relancer la campagne depuis l'interface.")

            return True

    except Exception as e:
        print(f"❌ Erreur: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Remet une campagne en statut 'draft' pour les tests"
    )
    parser.add_argument(
        '--campaign-id',
        type=str,
        help='UUID de la campagne à remettre en draft'
    )
    parser.add_argument(
        '--latest',
        action='store_true',
        help='Utiliser la dernière campagne créée'
    )

    args = parser.parse_args()

    success = reset_campaign_to_draft(
        campaign_id=args.campaign_id,
        use_latest=args.latest
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
