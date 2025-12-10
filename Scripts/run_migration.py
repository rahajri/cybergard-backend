"""Script simple pour ajouter la colonne custom_logo."""
import sys
from pathlib import Path

# Créer un fichier log pour confirmer l'exécution
log_file = Path(__file__).parent / "migration_result.txt"

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from sqlalchemy import text
    from src.database import SessionLocal

    db = SessionLocal()
    try:
        # PostgreSQL supporte IF NOT EXISTS pour ADD COLUMN
        db.execute(text("ALTER TABLE report_template ADD COLUMN IF NOT EXISTS custom_logo TEXT"))
        db.commit()
        msg = "OK: Colonne custom_logo ajoutee avec succes!"
        print(msg)
        log_file.write_text(msg)
    except Exception as e:
        db.rollback()
        msg = f"ERREUR DB: {e}"
        print(msg)
        log_file.write_text(msg)
    finally:
        db.close()
except Exception as e:
    msg = f"ERREUR IMPORT: {e}"
    print(msg)
    log_file.write_text(msg)
