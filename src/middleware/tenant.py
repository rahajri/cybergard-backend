from fastapi import Request
from sqlalchemy import text

async def inject_tenant_context(request: Request, call_next):
    """
    Injecte automatiquement le tenant_id dans le contexte PostgreSQL
    depuis le JWT ou header de la requête
    """
    # 1. Extraire tenant_id du JWT/header
    tenant_id = extract_tenant_from_token(request)
    
    # 2. Injecter dans PostgreSQL
    if tenant_id:
        async with engine.begin() as conn:
            await conn.execute(
                text("SET LOCAL app.current_tenant_id = :tid"),
                {"tid": str(tenant_id)}
            )
    
    response = await call_next(request)
    return response

# Ajouter dans main.py
app.middleware("http")(inject_tenant_context)