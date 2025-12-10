from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Dict, Any, Optional
import logging

from ...models.audit import Framework, Domain, Requirement
from ...database import get_db

# ✅ REDIS CACHE
from src.utils.redis_manager import cache_result

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get(
    "/",
    response_model=List[Dict[str, Any]],
    summary="Récupérer les exigences"
)
@cache_result(ttl=1800, key_prefix="requirements_list")  # ✅ Cache 30 minutes
def get_requirements(
    framework_id: str,
    domain: Optional[str] = None,
    limit: int = 1000,
    db: Session = Depends(get_db)
):
    """
    Récupère les exigences d'un référentiel, optionnellement filtrées par domaine.
    
    Args:
        framework_id: UUID du référentiel
        domain: UUID du domaine (optionnel)
        limit: Nombre max de résultats
    
    Returns:
        Liste des exigences avec leurs métadonnées
    """
    try:
        # Vérifier que le framework existe
        framework = db.query(Framework).filter_by(id=framework_id).first()
        if not framework:
            raise HTTPException(status_code=404, detail="Référentiel introuvable")
        
        # Construire la requête de base
        query = db.query(Requirement).filter(
            Requirement.framework_id == framework_id
        )
        
        # Filtrer par domaine si spécifié
        if domain:
            query = query.filter(Requirement.domain_id == domain)
        
        # Trier par code officiel
        query = query.order_by(Requirement.official_code)
        
        # Limiter les résultats
        query = query.limit(limit)
        
        # Exécuter et formatter
        requirements = query.all()
        
        result = []
        for req in requirements:
            # Récupérer le domaine associé
            domain_obj = db.query(Domain).filter_by(id=req.domain_id).first()
            domain_title = None
            if domain_obj:
                domain_title_obj = db.execute(
                    text("""
                        SELECT title 
                        FROM domain_title 
                        WHERE domain_id = :domain_id 
                        AND is_primary = true 
                        AND language = 'fr'
                        LIMIT 1
                    """),
                    {"domain_id": str(domain_obj.id)}
                ).fetchone()
                domain_title = domain_title_obj.title if domain_title_obj else domain_obj.code
            
            result.append({
                "id": str(req.id),
                "official_code": req.official_code,
                "title": req.title,
                "requirement_text": req.requirement_text,
                "domain": domain_title,
                "subdomain": "",  # Plus utilisé avec la nouvelle structure
                "risk_level": req.risk_level,
                "created_at": req.created_at.isoformat() if req.created_at else None
            })
        
        logger.info(f"✅ {len(result)} exigence(s) récupérée(s) pour {framework.code}")
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur récupération exigences : {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))