"""
Script de nettoyage des embeddings orphelins
"""
import asyncio
from sqlalchemy import text
from src.database import get_engine

async def cleanup_orphan_embeddings():
    """Supprime les embeddings sans requirement associé"""
    engine = get_engine()
    
    async with engine.begin() as conn:
        # 1. Compter les orphelins
        count_result = await conn.execute(text("""
            SELECT COUNT(*) 
            FROM requirement_embeddings re
            LEFT JOIN requirement r ON re.requirement_id = r.id
            WHERE r.id IS NULL
        """))
        orphan_count = count_result.scalar()
        
        print(f"🔍 Embeddings orphelins trouvés: {orphan_count}")
        
        if orphan_count == 0:
            print("✅ Aucun embedding orphelin, base de données propre")
            return
        
        # 2. Supprimer les orphelins
        result = await conn.execute(text("""
            DELETE FROM requirement_embeddings
            WHERE requirement_id IN (
                SELECT re.requirement_id
                FROM requirement_embeddings re
                LEFT JOIN requirement r ON re.requirement_id = r.id
                WHERE r.id IS NULL
            )
        """))
        
        deleted = result.rowcount
        print(f"🗑️  {deleted} embeddings orphelins supprimés")
        
        # 3. Vérifier les frameworks
        frameworks_result = await conn.execute(text("""
            SELECT f.code, f.name, COUNT(r.id) as req_count
            FROM framework f
            LEFT JOIN requirement r ON f.id = r.framework_id
            GROUP BY f.id, f.code, f.name
            ORDER BY f.code
        """))
        
        print("\n📊 État des frameworks:")
        for row in frameworks_result:
            print(f"   {row.code}: {row.req_count} exigences")
        
        print("\n✅ Nettoyage terminé")

if __name__ == "__main__":
    asyncio.run(cleanup_orphan_embeddings())