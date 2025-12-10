"""Regénérer un nouveau Magic Link avec le bon questionnaire_id"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/audit_platform")
engine = create_engine(DATABASE_URL)

# Questionnaire correct
CORRECT_QUESTIONNAIRE_ID = "cc44ae5b-12f9-40f2-a672-f087562a121c"

# Email de l'utilisateur concerné
USER_EMAIL = "audite@maroc.ma"

print("="*80)
print("REGENERATION MAGIC LINK")
print("="*80)

with engine.connect() as conn:
    # 1. Trouver le token actuel
    print(f"\n[1/4] Recherche du Magic Link pour {USER_EMAIL}...")

    result = conn.execute(text("""
        SELECT
            token_jti,
            campaign_id,
            questionnaire_id,
            tenant_id,
            created_at
        FROM audit_tokens
        WHERE user_email = :email
        ORDER BY created_at DESC
        LIMIT 1
    """), {"email": USER_EMAIL})

    current_token = result.fetchone()

    if not current_token:
        print(f"[ERREUR] Aucun Magic Link trouvé pour {USER_EMAIL}")
        exit(1)

    print(f"[OK] Magic Link trouvé")
    print(f"   Token JTI: {current_token.token_jti}")
    print(f"   Campaign ID: {current_token.campaign_id}")
    print(f"   Questionnaire ID (ancien): {current_token.questionnaire_id}")
    print(f"   Tenant ID: {current_token.tenant_id}")

    campaign_id = str(current_token.campaign_id)
    tenant_id = str(current_token.tenant_id)

    # 2. Supprimer l'ancien token
    print(f"\n[2/4] Suppression de l'ancien Magic Link...")

    conn.execute(text("""
        DELETE FROM audit_tokens
        WHERE token_jti = :jti
    """), {"jti": str(current_token.token_jti)})

    conn.commit()
    print("[OK] Ancien Magic Link supprimé")

    # 3. Générer un nouveau Magic Link
    print(f"\n[3/4] Génération d'un nouveau Magic Link...")
    print(f"   Email: {USER_EMAIL}")
    print(f"   Campaign: {campaign_id}")
    print(f"   Questionnaire: {CORRECT_QUESTIONNAIRE_ID}")
    print(f"   Tenant: {tenant_id}")

    # Importer le service magic_link
    sys.path.insert(0, str(Path(__file__).parent / "src"))

    from services.magic_link_service import generate_magic_link
    import uuid

    # Convertir les IDs en UUID
    campaign_uuid = uuid.UUID(campaign_id)
    questionnaire_uuid = uuid.UUID(CORRECT_QUESTIONNAIRE_ID)
    tenant_uuid = uuid.UUID(tenant_id)

    # Créer une session SQLAlchemy
    from sqlalchemy.orm import Session
    session = Session(bind=engine)

    try:
        # Générer le nouveau Magic Link
        magic_link, audit_token = generate_magic_link(
            db=session,
            user_email=USER_EMAIL,
            campaign_id=campaign_uuid,
            questionnaire_id=questionnaire_uuid,
            tenant_id=tenant_uuid
        )

        print(f"[OK] Nouveau Magic Link généré!")
        print(f"   Token JTI: {audit_token.token_jti}")

        # 4. Afficher le nouveau lien
        print(f"\n[4/4] Nouveau Magic Link:")
        print("-"*80)
        print(magic_link)
        print("-"*80)

        # Extraire le token pour le test
        token_part = magic_link.split("?token=")[1]

        # Créer le fichier de test
        import json
        test_data = {"magic_token": token_part}

        with open("test_exchange.json", "w") as f:
            json.dump(test_data, f, indent=2)

        print("\n[OK] Fichier test_exchange.json mis à jour")
        print("\nVous pouvez maintenant tester:")
        print("  curl -X POST http://localhost:8000/api/v1/magic-link/exchange \\")
        print("    -H 'Content-Type: application/json' \\")
        print("    -d @test_exchange.json")

        session.close()

    except Exception as e:
        session.rollback()
        session.close()
        print(f"[ERREUR] {e}")
        import traceback
        traceback.print_exc()
        exit(1)

print("\n" + "="*80)
print("TERMINE")
print("="*80)
