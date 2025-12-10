"""Script pour vérifier les templates dans la base."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    result = db.execute(text("""
        SELECT code, name, is_system, is_default
        FROM report_template
        ORDER BY is_default DESC, code
    """))

    print("\n" + "=" * 80)
    print("TEMPLATES IN DATABASE")
    print("=" * 80 + "\n")

    for row in result:
        print(f"  {row[0]:25} | {row[1]:35} | System: {row[2]} | Default: {row[3]}")

    print()
finally:
    db.close()
