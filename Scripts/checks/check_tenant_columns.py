from src.database import engine
import sqlalchemy

cols = sqlalchemy.inspect(engine).get_columns('tenant')
print('Tenant columns:')
for c in cols:
    print(f"- {c['name']}: {c['type']}")