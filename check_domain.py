from sqlalchemy import text
from src.database import SessionLocal

db = SessionLocal()
result = db.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'domain'"))
print("Colonnes de la table domain:")
for r in result.fetchall():
    print(f"  - {r[0]}")
db.close()
