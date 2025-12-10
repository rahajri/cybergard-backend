"""Diagnostic intelligent des campagnes et questionnaires"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import create_engine, text
from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/audit_platform")
engine = create_engine(DATABASE_URL)

print("="*80)
print("DIAGNOSTIC INTELLIGENT - CAMPAGNES + QUESTIONNAIRES")
print("="*80)

with engine.connect() as conn:
    # 1. Lister toutes les campagnes récentes
    print("\n[1/5] Recherche des campagnes récentes...")
    result = conn.execute(text("""
        SELECT
            c.id as campaign_id,
            c.title,
            c.questionnaire_id,
            c.status,
            c.launch_date,
            c.created_at,
            q.name as questionnaire_name,
            q.is_active as questionnaire_active,
            (SELECT COUNT(*) FROM audit_tokens WHERE campaign_id = c.id) as token_count
        FROM campaign c
        LEFT JOIN questionnaire q ON c.questionnaire_id = q.id
        ORDER BY c.created_at DESC
        LIMIT 10
    """))

    campaigns = result.fetchall()

    if not campaigns:
        print("[INFO] Aucune campagne trouvée")
        exit(0)

    print(f"[OK] {len(campaigns)} campagne(s) trouvée(s)\n")

    for i, camp in enumerate(campaigns, 1):
        print(f"{i}. {camp.title}")
        print(f"   ID: {camp.campaign_id}")
        print(f"   Questionnaire: {camp.questionnaire_name or '[NON TROUVÉ]'}")
        print(f"   Questionnaire ID: {camp.questionnaire_id}")
        print(f"   Questionnaire actif: {camp.questionnaire_active if camp.questionnaire_active is not None else 'N/A'}")
        print(f"   Status: {camp.status}")
        print(f"   Magic Links: {camp.token_count}")
        print(f"   Créée: {camp.created_at}")

        if not camp.questionnaire_name:
            print(f"   ⚠️  PROBLÈME: Le questionnaire référencé n'existe pas!")

        print()

    # 2. Chercher les Magic Links récents
    print("\n[2/5] Recherche des Magic Links récents...")
    result = conn.execute(text("""
        SELECT
            at.token_jti,
            at.user_email,
            at.campaign_id,
            at.questionnaire_id as token_questionnaire_id,
            at.created_at,
            at.used_count,
            at.max_uses,
            c.title as campaign_title,
            c.questionnaire_id as campaign_questionnaire_id,
            q.name as questionnaire_name
        FROM audit_tokens at
        LEFT JOIN campaign c ON at.campaign_id = c.id
        LEFT JOIN questionnaire q ON at.questionnaire_id = q.id
        ORDER BY at.created_at DESC
        LIMIT 10
    """))

    tokens = result.fetchall()

    if not tokens:
        print("[INFO] Aucun Magic Link trouvé")
    else:
        print(f"[OK] {len(tokens)} Magic Link(s) trouvé(s)\n")

        problems = []

        for i, tok in enumerate(tokens, 1):
            print(f"{i}. {tok.user_email}")
            print(f"   Token JTI: {tok.token_jti}")
            print(f"   Campagne: {tok.campaign_title or '[CAMPAGNE SUPPRIMÉE]'}")
            print(f"   Questionnaire (token): {tok.token_questionnaire_id}")
            print(f"   Questionnaire (campagne): {tok.campaign_questionnaire_id}")
            print(f"   Questionnaire nom: {tok.questionnaire_name or '[NON TROUVÉ]'}")
            print(f"   Utilisations: {tok.used_count}/{tok.max_uses}")

            # Vérifier les incohérences
            issues = []

            if not tok.questionnaire_name:
                issues.append("Questionnaire référencé n'existe pas")

            if tok.token_questionnaire_id != tok.campaign_questionnaire_id:
                issues.append("Incohérence token/campagne")

            if not tok.campaign_title:
                issues.append("Campagne supprimée")

            if issues:
                print(f"   ⚠️  PROBLÈMES: {', '.join(issues)}")
                problems.append({
                    'token_jti': tok.token_jti,
                    'campaign_id': tok.campaign_id,
                    'token_q_id': tok.token_questionnaire_id,
                    'campaign_q_id': tok.campaign_questionnaire_id,
                    'issues': issues
                })

            print()

    # 3. Lister tous les questionnaires actifs
    print("\n[3/5] Liste des questionnaires actifs disponibles...")
    result = conn.execute(text("""
        SELECT
            id,
            name,
            is_active,
            created_at,
            (SELECT COUNT(*) FROM campaign WHERE questionnaire_id = questionnaire.id) as campaign_count
        FROM questionnaire
        WHERE is_active = true
        ORDER BY created_at DESC
        LIMIT 20
    """))

    questionnaires = result.fetchall()

    if not questionnaires:
        print("[ATTENTION] Aucun questionnaire actif trouvé!")
    else:
        print(f"[OK] {len(questionnaires)} questionnaire(s) actif(s)\n")

        for i, q in enumerate(questionnaires, 1):
            print(f"{i}. {q.name}")
            print(f"   ID: {q.id}")
            print(f"   Campagnes liées: {q.campaign_count}")
            print(f"   Créé: {q.created_at}")
            print()

    # 4. Identifier le problème spécifique
    print("\n[4/5] Analyse des problèmes détectés...")

    if not problems:
        print("[OK] Aucun problème détecté!")
    else:
        print(f"[ATTENTION] {len(problems)} problème(s) détecté(s)")

        for prob in problems:
            print(f"\n• Token: {prob['token_jti']}")
            print(f"  Problèmes: {', '.join(prob['issues'])}")

            if "Questionnaire référencé n'existe pas" in prob['issues']:
                print(f"  → Le questionnaire {prob['token_q_id']} n'existe pas en BDD")

            if "Incohérence token/campagne" in prob['issues']:
                print(f"  → Token pointe vers: {prob['token_q_id']}")
                print(f"  → Campagne pointe vers: {prob['campaign_q_id']}")

    # 5. Proposer des solutions
    print("\n[5/5] Solutions recommandées...")

    if problems:
        print("\n" + "="*80)
        print("ACTIONS À EFFECTUER")
        print("="*80)

        # Trouver les questionnaires orphelins
        orphan_questionnaire_ids = set()
        for prob in problems:
            if "Questionnaire référencé n'existe pas" in prob['issues']:
                orphan_questionnaire_ids.add(prob['token_q_id'])

        if orphan_questionnaire_ids:
            print("\n1. QUESTIONNAIRES INEXISTANTS")
            for q_id in orphan_questionnaire_ids:
                print(f"\n   Questionnaire manquant: {q_id}")

                # Chercher les campagnes et tokens affectés
                result = conn.execute(text("""
                    SELECT DISTINCT campaign_id
                    FROM audit_tokens
                    WHERE questionnaire_id = :q_id
                """), {"q_id": str(q_id)})

                affected_campaigns = [str(row.campaign_id) for row in result.fetchall()]

                if affected_campaigns:
                    print(f"   Campagnes affectées: {len(affected_campaigns)}")

                    if questionnaires:
                        print(f"\n   SOLUTION: Choisir un questionnaire de remplacement parmi:")
                        for i, q in enumerate(questionnaires[:5], 1):
                            print(f"     {i}. {q.name} ({q.id})")

                        print(f"\n   Commandes SQL pour corriger:")
                        print(f"   -- Choisir un questionnaire de remplacement, par exemple:")
                        replacement_id = questionnaires[0].id
                        print(f"   -- '{questionnaires[0].name}' ({replacement_id})")
                        print()

                        for camp_id in affected_campaigns:
                            print(f"   -- Campagne {camp_id}")
                            print(f"   UPDATE campaign SET questionnaire_id = '{replacement_id}'")
                            print(f"   WHERE id = '{camp_id}';")
                            print()
                            print(f"   UPDATE audit_tokens SET questionnaire_id = '{replacement_id}'")
                            print(f"   WHERE campaign_id = '{camp_id}';")
                            print()

print("\n" + "="*80)
print("FIN DU DIAGNOSTIC")
print("="*80)
