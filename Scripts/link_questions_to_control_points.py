"""
Lie les questions aux points de contrôle via requirement_control_point.json
"""

import json
import logging
import sys
from pathlib import Path

# Ajouter le dossier parent au PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Configuration BDD
DATABASE_URL = "postgresql://postgres:votre_mot_de_passe@localhost:5432/audit_platform"

def get_db_session():
    """Crée une session de base de données."""
    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal()

def load_requirement_cp_mappings():
    """Charge les mappings depuis le JSON."""
    # Chercher le fichier JSON à plusieurs endroits
    possible_paths = [
        Path(__file__).parent.parent / "db" / "requirement_control_point_202510112336.json",
        Path(__file__).parent.parent.parent / "requirement_control_point_202510112336.json",
        Path(__file__).parent / "requirement_control_point_202510112336.json",
    ]
    
    json_file = None
    for path in possible_paths:
        if path.exists():
            json_file = path
            break
    
    if not json_file:
        raise FileNotFoundError(
            f"Fichier JSON introuvable. Cherché dans:\n" + 
            "\n".join(f"  - {p}" for p in possible_paths)
        )
    
    logger.info(f"📄 Chargement: {json_file}")
    
    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Créer un dictionnaire requirement_id → control_point_id
    mappings = {}
    for item in data['requirement_control_point']:
        req_id = item['requirement_id']
        cp_id = item['control_point_id']
        
        # Garder le premier mapping en cas de doublons
        if req_id not in mappings:
            mappings[req_id] = cp_id
    
    logger.info(f"✅ Chargé {len(mappings)} mappings requirement → control_point")
    return mappings

def link_questions_to_control_points(questionnaire_id: str):
    """Lie les questions aux PC via leurs requirement_id."""
    db = get_db_session()
    
    try:
        # 1️⃣ Charger les mappings
        req_cp_map = load_requirement_cp_mappings()
        
        # 2️⃣ Récupérer toutes les questions avec requirement_id
        logger.info(f"🔍 Recherche des questions du questionnaire {questionnaire_id[:8]}...")
        
        query = text("""
            SELECT 
                q.id as question_id,
                q.requirement_id,
                q.question_code
            FROM question q
            WHERE q.questionnaire_id = :qid
              AND q.requirement_id IS NOT NULL
            ORDER BY q.sort_order
        """)
        
        questions = db.execute(query, {"qid": questionnaire_id}).fetchall()
        logger.info(f"📊 Trouvé {len(questions)} questions avec requirement_id")
        
        if not questions:
            logger.warning("⚠️ Aucune question à traiter")
            return
        
        # 3️⃣ Mettre à jour question.control_point_id
        logger.info("⚡ Mise à jour de question.control_point_id...")
        
        updated = 0
        not_found = 0
        
        for q in questions:
            cp_id = req_cp_map.get(str(q.requirement_id))
            
            if cp_id:
                update_query = text("""
                    UPDATE question
                    SET control_point_id = :cp_id
                    WHERE id = :q_id
                """)
                db.execute(update_query, {"cp_id": cp_id, "q_id": str(q.question_id)})
                updated += 1
            else:
                not_found += 1
                logger.debug(f"⚠️ Pas de PC pour requirement {q.requirement_id} (question {q.question_code})")
        
        db.commit()
        logger.info(f"✅ Mis à jour: {updated} questions")
        if not_found > 0:
            logger.warning(f"⚠️ Sans PC: {not_found} questions")
        
        # 4️⃣ Peupler la table question_control_point
        logger.info("🔗 Peuplement de question_control_point...")
        
        link_query = text("""
            INSERT INTO question_control_point (question_id, control_point_id)
            SELECT q.id, q.control_point_id
            FROM question q
            WHERE q.questionnaire_id = :qid
              AND q.control_point_id IS NOT NULL
            ON CONFLICT DO NOTHING
        """)
        
        db.execute(link_query, {"qid": questionnaire_id})
        db.commit()
        
        # 5️⃣ Statistiques finales
        logger.info("\n📊 Statistiques finales:")
        
        stats_query = text("""
            SELECT 
                COUNT(*) as total,
                COUNT(requirement_id) as avec_requirement,
                COUNT(control_point_id) as avec_control_point,
                COUNT(*) - COUNT(control_point_id) as sans_control_point
            FROM question
            WHERE questionnaire_id = :qid
        """)
        
        stats = db.execute(stats_query, {"qid": questionnaire_id}).fetchone()
        
        logger.info(f"  Total questions: {stats.total}")
        logger.info(f"  ✅ Avec requirement_id: {stats.avec_requirement}")
        logger.info(f"  ✅ Avec control_point_id: {stats.avec_control_point}")
        logger.info(f"  ⚠️ Sans control_point_id: {stats.sans_control_point}")
        if stats.total > 0:
            logger.info(f"  📈 Taux de couverture PC: {100 * stats.avec_control_point / stats.total:.1f}%")
        
        # 6️⃣ Vérifier la table de liaison
        count_query = text("""
            SELECT COUNT(*) as count
            FROM question_control_point qcp
            JOIN question q ON q.id = qcp.question_id
            WHERE q.questionnaire_id = :qid
        """)
        
        count = db.execute(count_query, {"qid": questionnaire_id}).scalar()
        logger.info(f"  🔗 Liaisons question_control_point: {count}")
        
        # 7️⃣ Échantillon
        logger.info("\n📋 Échantillon (10 premières questions):")
        
        sample_query = text("""
            SELECT 
                q.question_code,
                r.official_code as req_code,
                cp.code as cp_code,
                LEFT(cp.name, 40) as cp_name
            FROM question q
            LEFT JOIN requirement r ON r.id = q.requirement_id
            LEFT JOIN control_point cp ON cp.id = q.control_point_id
            WHERE q.questionnaire_id = :qid
            ORDER BY r.official_code, q.question_code
            LIMIT 10
        """)
        
        samples = db.execute(sample_query, {"qid": questionnaire_id}).fetchall()
        
        for s in samples:
            logger.info(f"  {s.question_code} → {s.req_code} → {s.cp_code or '[AUCUN PC]'}")
        
        logger.info("\n✅ Liaison terminée avec succès!")
        
    except Exception as e:
        logger.error(f"❌ Erreur: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    # ⚠️ MODIFIEZ CE MOT DE PASSE
    import getpass
    
    print("🔐 Configuration de la connexion PostgreSQL")
    password = getpass.getpass("Mot de passe postgres: ")
    
    DATABASE_URL = f"postgresql://postgres:{password}@localhost:5432/audit_platform"
    
    questionnaire_id = "d5c363e9-63c4-4bee-8b85-702bf29fd44d"
    link_questions_to_control_points(questionnaire_id)