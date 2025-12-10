import sys
sys.path.insert(0, r'c:\Users\rachi\Documents\Mes Sites\AI CYBER\backend')

from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import os

load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL')
engine = create_engine(DATABASE_URL)

CAMPAIGN_ID = '65f50723-dcf5-4c48-83c2-ace342c9ae72'

with engine.connect() as conn:
    print("=== VERIFICATION DES DONNEES GED ===\n")

    # Vérifier les documents liés à la campagne
    check_documents = text("""
        SELECT id, file_name, file_type, created_at
        FROM document
        WHERE campaign_id = :campaign_id
    """)

    try:
        result = conn.execute(check_documents, {"campaign_id": CAMPAIGN_ID})
        documents = result.fetchall()

        if documents:
            print(f"[FOUND] {len(documents)} document(s) trouvé(s) pour cette campagne:")
            for doc in documents:
                print(f"  - {doc.file_name} ({doc.file_type}) - créé le {doc.created_at}")
        else:
            print("[OK] Aucun document GED trouvé pour cette campagne")

    except Exception as e:
        print(f"[INFO] Pas de colonne campaign_id dans la table document: {e}")
        print("[INFO] Vérification d'autres liens possibles...")

        # Vérifier s'il y a une table de liaison
        check_tables = text("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name LIKE '%document%'
        """)
        result = conn.execute(check_tables)
        tables = result.fetchall()
        print(f"\n[INFO] Tables contenant 'document': {[t.table_name for t in tables]}")
