#!/usr/bin/env python3
"""
Script rapide pour réinitialiser un token Magic Link saturé.
Utile pour les tests de développement.

Usage:
    python reset_token.py                      # Réinitialise TOUS les tokens
    python reset_token.py <token_jti>          # Réinitialise un token spécifique
    python reset_token.py --campaign <id>      # Réinitialise une campagne
"""
import sys
import os
from pathlib import Path

# Ajouter le répertoire parent au PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import argparse

# Charger les variables d'environnement
load_dotenv()

# Configuration de la base de données
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/audit_platform")

def reset_all_tokens():
    """Réinitialise tous les tokens"""
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        result = session.execute(text("""
            UPDATE audit_tokens
            SET used_count = 0,
                first_used_at = NULL,
                last_used_at = NULL,
                last_used_ip = NULL,
                last_user_agent = NULL,
                updated_at = CURRENT_TIMESTAMP
            RETURNING token_jti
        """))

        count = len(result.fetchall())
        session.commit()

        print(f"✅ {count} token(s) réinitialisé(s) avec succès")
        return count

    except Exception as e:
        session.rollback()
        print(f"❌ Erreur: {e}")
        return 0
    finally:
        session.close()

def reset_token_by_jti(token_jti: str):
    """Réinitialise un token spécifique"""
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        result = session.execute(text("""
            UPDATE audit_tokens
            SET used_count = 0,
                first_used_at = NULL,
                last_used_at = NULL,
                last_used_ip = NULL,
                last_user_agent = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE token_jti = :token_jti
            RETURNING token_jti, user_email
        """), {"token_jti": token_jti})

        row = result.fetchone()
        session.commit()

        if row:
            print(f"✅ Token réinitialisé: {row.token_jti} ({row.user_email})")
            return True
        else:
            print(f"❌ Token {token_jti} introuvable")
            return False

    except Exception as e:
        session.rollback()
        print(f"❌ Erreur: {e}")
        return False
    finally:
        session.close()

def reset_campaign_tokens(campaign_id: str):
    """Réinitialise tous les tokens d'une campagne"""
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        result = session.execute(text("""
            UPDATE audit_tokens
            SET used_count = 0,
                first_used_at = NULL,
                last_used_at = NULL,
                last_used_ip = NULL,
                last_user_agent = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE campaign_id = :campaign_id
            RETURNING token_jti
        """), {"campaign_id": campaign_id})

        count = len(result.fetchall())
        session.commit()

        print(f"✅ {count} token(s) de la campagne {campaign_id} réinitialisé(s)")
        return count

    except Exception as e:
        session.rollback()
        print(f"❌ Erreur: {e}")
        return 0
    finally:
        session.close()

def increase_token_limit(token_jti: str, new_limit: int):
    """Augmente la limite d'un token spécifique"""
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        result = session.execute(text("""
            UPDATE audit_tokens
            SET max_uses = :max_uses,
                updated_at = CURRENT_TIMESTAMP
            WHERE token_jti = :token_jti
            RETURNING token_jti, user_email, max_uses
        """), {"token_jti": token_jti, "max_uses": new_limit})

        row = result.fetchone()
        session.commit()

        if row:
            print(f"✅ Limite augmentée: {row.token_jti} ({row.user_email}) → {row.max_uses} utilisations")
            return True
        else:
            print(f"❌ Token {token_jti} introuvable")
            return False

    except Exception as e:
        session.rollback()
        print(f"❌ Erreur: {e}")
        return False
    finally:
        session.close()

def list_tokens():
    """Liste tous les tokens avec leurs statistiques"""
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        result = session.execute(text("""
            SELECT
                token_jti,
                user_email,
                campaign_id,
                used_count,
                max_uses,
                revoked,
                expires_at,
                created_at
            FROM audit_tokens
            ORDER BY created_at DESC
            LIMIT 20
        """))

        print("\n📋 Derniers tokens:")
        print("-" * 120)
        print(f"{'JTI':<38} {'Email':<30} {'Utilisations':<15} {'Révoqué':<10} {'Expiration':<20}")
        print("-" * 120)

        for row in result:
            status = f"{row.used_count}/{row.max_uses}"
            revoked = "OUI" if row.revoked else "NON"
            expires = row.expires_at.strftime("%Y-%m-%d %H:%M") if row.expires_at else "N/A"

            print(f"{str(row.token_jti):<38} {row.user_email:<30} {status:<15} {revoked:<10} {expires:<20}")

        # Statistiques globales
        stats = session.execute(text("""
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE used_count >= max_uses) as fully_used,
                COUNT(*) FILTER (WHERE revoked = true) as revoked,
                COUNT(*) FILTER (WHERE expires_at <= CURRENT_TIMESTAMP) as expired
            FROM audit_tokens
        """)).fetchone()

        print("-" * 120)
        print(f"📊 Total: {stats.total} | Saturés: {stats.fully_used} | Révoqués: {stats.revoked} | Expirés: {stats.expired}")
        print()

    except Exception as e:
        print(f"❌ Erreur: {e}")
    finally:
        session.close()

def main():
    parser = argparse.ArgumentParser(
        description="Gestion des tokens Magic Link",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples:
  python reset_token.py --list                                          # Liste les tokens
  python reset_token.py --all                                           # Réinitialise tous
  python reset_token.py --jti 7e277fd1-685e-4fce-94c9-d109ce8c3b14     # Réinitialise un token
  python reset_token.py --campaign <campaign_id>                        # Réinitialise une campagne
  python reset_token.py --increase-limit <jti> 50                       # Augmente la limite
        """
    )

    parser.add_argument("--list", action="store_true", help="Liste les tokens")
    parser.add_argument("--all", action="store_true", help="Réinitialise TOUS les tokens")
    parser.add_argument("--jti", type=str, help="Réinitialise un token spécifique (UUID)")
    parser.add_argument("--campaign", type=str, help="Réinitialise les tokens d'une campagne (UUID)")
    parser.add_argument("--increase-limit", nargs=2, metavar=("JTI", "LIMIT"), help="Augmente la limite d'un token")

    args = parser.parse_args()

    # Si aucun argument, afficher l'aide et lister les tokens
    if len(sys.argv) == 1:
        parser.print_help()
        print()
        list_tokens()
        return

    if args.list:
        list_tokens()
    elif args.all:
        confirm = input("⚠️  Voulez-vous vraiment réinitialiser TOUS les tokens ? (oui/non): ")
        if confirm.lower() == "oui":
            reset_all_tokens()
        else:
            print("❌ Annulé")
    elif args.jti:
        reset_token_by_jti(args.jti)
    elif args.campaign:
        reset_campaign_tokens(args.campaign)
    elif args.increase_limit:
        jti, limit = args.increase_limit
        increase_token_limit(jti, int(limit))
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
