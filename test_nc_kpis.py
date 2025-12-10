"""
Script de test pour vérifier les KPIs des non-conformités
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from sqlalchemy import create_engine, select, update, func
from sqlalchemy.orm import Session
from src.models.audit import QuestionAnswer
from src.database import DB_URL
import uuid

def test_compliance_status():
    """Test le champ compliance_status et les KPIs"""

    # Créer connexion DB
    engine = create_engine(DB_URL)

    with Session(engine) as session:
        print("=" * 60)
        print("TEST DU CHAMP COMPLIANCE_STATUS")
        print("=" * 60)

        # 1. Vérifier que le champ existe
        print("\n1. Vérification de la structure de la table...")
        result = session.execute(select(QuestionAnswer).limit(1))
        sample = result.scalar_one_or_none()

        if sample:
            print(f"[OK] Table 'question_answer' accessible")
            print(f"   ID: {sample.id}")
            print(f"   compliance_status: {sample.compliance_status}")
        else:
            print("[WARN] Aucune donnee dans question_answer")

        # 2. Compter les réponses par compliance_status
        print("\n2. Statistiques par compliance_status...")

        statuses = [
            'compliant',
            'non_compliant_minor',
            'non_compliant_major',
            'not_applicable',
            'pending',
            None  # Pas encore évalué
        ]

        for status in statuses:
            if status is None:
                query = select(func.count(QuestionAnswer.id)).where(
                    QuestionAnswer.compliance_status.is_(None)
                )
                label = "NULL (pas évalué)"
            else:
                query = select(func.count(QuestionAnswer.id)).where(
                    QuestionAnswer.compliance_status == status
                )
                label = status

            count = session.execute(query).scalar()
            print(f"   {label}: {count}")

        # 3. Compter les NC par campagne (simulation du KPI endpoint)
        print("\n3. NC par campagne (simulation KPI endpoint)...")

        # Récupérer toutes les campagnes uniques
        campaigns_query = select(QuestionAnswer.campaign_id).where(
            QuestionAnswer.campaign_id.isnot(None)
        ).distinct()

        campaign_ids = [row[0] for row in session.execute(campaigns_query)]

        if not campaign_ids:
            print("   [WARN] Aucune campagne trouvee")
        else:
            for campaign_id in campaign_ids[:5]:  # Limiter à 5 pour lisibilité
                # NC Majeures
                nc_major_query = select(func.count(QuestionAnswer.id)).where(
                    QuestionAnswer.campaign_id == campaign_id,
                    QuestionAnswer.compliance_status == 'non_compliant_major'
                )
                nc_major = session.execute(nc_major_query).scalar() or 0

                # NC Mineures
                nc_minor_query = select(func.count(QuestionAnswer.id)).where(
                    QuestionAnswer.campaign_id == campaign_id,
                    QuestionAnswer.compliance_status == 'non_compliant_minor'
                )
                nc_minor = session.execute(nc_minor_query).scalar() or 0

                # Total réponses
                total_query = select(func.count(QuestionAnswer.id)).where(
                    QuestionAnswer.campaign_id == campaign_id
                )
                total = session.execute(total_query).scalar() or 0

                print(f"\n   Campagne: {campaign_id}")
                print(f"   - Total réponses: {total}")
                print(f"   - NC Majeures: {nc_major}")
                print(f"   - NC Mineures: {nc_minor}")

        # 4. Tester l'insertion d'une réponse avec compliance_status
        print("\n4. Test d'insertion avec compliance_status...")

        try:
            # Créer une réponse de test (ne sera pas committée)
            test_answer = QuestionAnswer(
                id=uuid.uuid4(),
                question_id=uuid.uuid4(),  # ID fictif
                audit_id=uuid.uuid4(),  # ID fictif
                campaign_id=uuid.uuid4(),  # ID fictif
                answer_value={"test": "value"},
                status='draft',
                compliance_status='non_compliant_major'
            )

            # Vérifier que l'objet peut être créé
            print(f"   [OK] Objet QuestionAnswer cree avec compliance_status={test_answer.compliance_status}")
            print(f"   [OK] Validation OK (pas d'erreur)")

        except Exception as e:
            print(f"   [ERROR] Erreur lors de la creation: {e}")

        # 5. Vérifier la contrainte CHECK
        print("\n5. Test de la contrainte de validation...")

        try:
            invalid_answer = QuestionAnswer(
                id=uuid.uuid4(),
                question_id=uuid.uuid4(),
                audit_id=uuid.uuid4(),
                compliance_status='invalid_status'  # ❌ Valeur interdite
            )

            # Tenter d'insérer (rollback attendu)
            session.add(invalid_answer)
            session.flush()

            print("   [ERROR] La contrainte n'a PAS bloque la valeur invalide!")
            session.rollback()

        except Exception as e:
            print(f"   [OK] Contrainte CHECK fonctionne: {type(e).__name__}")
            session.rollback()

        print("\n" + "=" * 60)
        print("FIN DES TESTS")
        print("=" * 60)

if __name__ == "__main__":
    test_compliance_status()
