"""Vérifier la campagne et son questionnaire"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/audit_platform")
engine = create_engine(DATABASE_URL)

campaign_id = "ff368151-55c0-4343-a27a-ba16d7bc1199"

print("="*80)
print("DIAGNOSTIC CAMPAGNE + QUESTIONNAIRE")
print("="*80)
print(f"Campaign ID: {campaign_id}\n")

with engine.connect() as conn:
    # 1. Vérifier la campagne
    print("[1/4] Vérification de la campagne...")
    result = conn.execute(text("""
        SELECT
            id,
            title,
            questionnaire_id,
            status,
            launch_date,
            created_at
        FROM campaign
        WHERE id = :campaign_id
    """), {"campaign_id": campaign_id})

    campaign = result.fetchone()

    if not campaign:
        print(f"[ERREUR] Campagne {campaign_id} introuvable!")
        exit(1)

    print(f"[OK] Campagne trouvée")
    print(f"   Titre: {campaign.title}")
    print(f"   Questionnaire ID: {campaign.questionnaire_id}")
    print(f"   Status: {campaign.status}")
    print(f"   Lancée le: {campaign.launch_date}")
    print()

    questionnaire_id_campaign = str(campaign.questionnaire_id)

    # 2. Vérifier le questionnaire de la campagne
    print("[2/4] Vérification du questionnaire de la campagne...")
    result = conn.execute(text("""
        SELECT
            id,
            name,
            is_active,
            created_at
        FROM questionnaire
        WHERE id = :questionnaire_id
    """), {"questionnaire_id": questionnaire_id_campaign})

    questionnaire = result.fetchone()

    if not questionnaire:
        print(f"[ERREUR] Questionnaire {questionnaire_id_campaign} introuvable!")
        print("   Le questionnaire référencé par la campagne n'existe pas en BDD")
    else:
        print(f"[OK] Questionnaire trouvé")
        print(f"   Nom: {questionnaire.name}")
        print(f"   Actif: {questionnaire.is_active}")
        print(f"   Créé le: {questionnaire.created_at}")
    print()

    # 3. Vérifier le Magic Link généré
    print("[3/4] Vérification du Magic Link...")
    result = conn.execute(text("""
        SELECT
            token_jti,
            user_email,
            campaign_id,
            questionnaire_id,
            created_at,
            expires_at,
            used_count,
            max_uses
        FROM audit_tokens
        WHERE campaign_id = :campaign_id
        ORDER BY created_at DESC
        LIMIT 1
    """), {"campaign_id": campaign_id})

    token = result.fetchone()

    if not token:
        print("[ATTENTION] Aucun Magic Link trouvé pour cette campagne")
    else:
        print(f"[OK] Magic Link trouvé")
        print(f"   Email: {token.user_email}")
        print(f"   Questionnaire ID (token): {token.questionnaire_id}")
        print(f"   Utilisations: {token.used_count}/{token.max_uses}")
        print(f"   Créé le: {token.created_at}")
        print(f"   Expire le: {token.expires_at}")

        if str(token.questionnaire_id) != questionnaire_id_campaign:
            print(f"\n   [ATTENTION] INCOHÉRENCE DÉTECTÉE!")
            print(f"   - Questionnaire dans la campagne: {questionnaire_id_campaign}")
            print(f"   - Questionnaire dans le token:    {token.questionnaire_id}")
    print()

    # 4. Vérifier le "bon" questionnaire mentionné
    print("[4/4] Vérification du questionnaire cc44ae5b...")
    correct_questionnaire_id = "cc44ae5b-12f9-40f2-a672-f087562a121c"

    result = conn.execute(text("""
        SELECT
            id,
            name,
            is_active,
            created_at
        FROM questionnaire
        WHERE id = :questionnaire_id
    """), {"questionnaire_id": correct_questionnaire_id})

    correct_q = result.fetchone()

    if not correct_q:
        print(f"[ERREUR] Questionnaire {correct_questionnaire_id} introuvable!")
    else:
        print(f"[OK] Questionnaire trouvé")
        print(f"   Nom: {correct_q.name}")
        print(f"   Actif: {correct_q.is_active}")
        print(f"   Créé le: {correct_q.created_at}")
    print()

print("="*80)
print("DIAGNOSTIC ET SOLUTIONS")
print("="*80)

if campaign and token:
    if str(campaign.questionnaire_id) != str(token.questionnaire_id):
        print("\n[PROBLÈME 1] Incohérence campagne/token")
        print(f"   La campagne référence: {campaign.questionnaire_id}")
        print(f"   Le Magic Link référence: {token.questionnaire_id}")
        print("\n   SOLUTION: Mettre à jour le Magic Link")
        print(f"   UPDATE audit_tokens")
        print(f"   SET questionnaire_id = '{questionnaire_id_campaign}'")
        print(f"   WHERE campaign_id = '{campaign_id}';")

if not questionnaire:
    print("\n[PROBLÈME 2] Questionnaire de la campagne inexistant")
    print(f"   La campagne référence un questionnaire qui n'existe pas: {questionnaire_id_campaign}")
    print("\n   SOLUTION: Mettre à jour la campagne avec le bon questionnaire")
    print(f"   UPDATE campaign")
    print(f"   SET questionnaire_id = '{correct_questionnaire_id}'")
    print(f"   WHERE id = '{campaign_id}';")
    print()
    print(f"   Puis mettre à jour les tokens:")
    print(f"   UPDATE audit_tokens")
    print(f"   SET questionnaire_id = '{correct_questionnaire_id}'")
    print(f"   WHERE campaign_id = '{campaign_id}';")

if correct_q:
    print("\n[SOLUTION RECOMMANDÉE]")
    print("   Le questionnaire cc44ae5b existe et est valide.")
    print("   Mettre à jour la campagne ET les tokens pour pointer vers ce questionnaire:")
    print()
    print("   # Étape 1: Mettre à jour la campagne")
    print(f"   UPDATE campaign SET questionnaire_id = '{correct_questionnaire_id}'")
    print(f"   WHERE id = '{campaign_id}';")
    print()
    print("   # Étape 2: Mettre à jour les Magic Links")
    print(f"   UPDATE audit_tokens SET questionnaire_id = '{correct_questionnaire_id}'")
    print(f"   WHERE campaign_id = '{campaign_id}';")

print("\n" + "="*80)
