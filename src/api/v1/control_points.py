# backend/src/api/v1/control_points.py
"""
Routes API pour la gestion des Points de Contrôle
Version corrigée - Utilise openai_generator.py existant
"""
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi import Body
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi import Query

from sqlalchemy.orm import Session
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Generator
from uuid import UUID, uuid4  # ✅ AJOUTER uuid4 aussi
import logging
import uuid
import json
import time
import asyncio
from datetime import datetime

from ...config import settings
from ...models.audit import Requirement, Framework, ControlPoint, Domain, User
from src.services.embedding_service import ControlPointEmbeddingService
from ...database import get_db, SessionLocal
from src.dependencies_keycloak import get_current_user_keycloak, require_permission

# 👇 sécurise l'accès aux paramètres applicatifs
try:
    from src.config import settings
except Exception:
    class _DummySettings:
        ollama_model = None
        ai_model = None
    settings = _DummySettings()
    
# Import du générateur existant (openai_generator.py)

try:
    from src.services.deepseek_pc_generator import DeepSeekControlPointGenerator
except ImportError:
    DeepSeekControlPointGenerator = None

# Import du service embeddings
try:
    from ...services.embedding_service import ControlPointEmbeddingService
except ImportError:
    ControlPointEmbeddingService = None

# ✅ REDIS CACHE
from src.utils.redis_manager import cache_result

logger = logging.getLogger(__name__)

router = APIRouter()

# ============================================================================
# HEALTH & LISTING
# ============================================================================
# Assure-toi que ces constantes existent en haut du fichier :
AI_METHOD = "ai_generation"
HUMAN_METHOD = "human"

from typing import Generator
from sqlalchemy.orm import Session
from src.database import SessionLocal

def get_db() -> Generator[Session, None, None]:
    """Dependency pour obtenir une session DB"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_deepseek_generator():
    """
    Dependency pour obtenir une instance du générateur DeepSeek.
    Crée une nouvelle instance à chaque requête.
    """
    from src.services.deepseek_pc_generator import DeepSeekControlPointGenerator
    
    # Créer une instance sans DB (elle prend la DB via les endpoints)
    generator = DeepSeekControlPointGenerator()
    
    return generator

# Ajouter une fonction helper en début de fichier

# LIGNE 80 (après les constantes AI_METHOD, HUMAN_METHOD)

def _infer_mapping_method(source: Optional[str], explicit: Optional[str]) -> str:
    """
    Détermine la méthode de mapping.
    - Si explicit fourni → utilisé
    - Sinon, déduit de source ('ai_*' → ai_generation; sinon human)
    """
    if explicit:
        return explicit
    
    if source and source.startswith("ai_"):
        return AI_METHOD
    
    return HUMAN_METHOD

import numpy as np
from typing import List

def cosine_similarity(embedding1: List[float], embedding2: List[float]) -> float:
    """
    Calcule la similarité cosine entre deux embeddings
    
    Retourne un score entre 0 (différents) et 1 (identiques)
    """
    try:
        vec1 = np.array(embedding1)
        vec2 = np.array(embedding2)
        
        # Produit scalaire
        dot_product = np.dot(vec1, vec2)
        
        # Normes
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        
        # Similarité cosine
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        similarity = dot_product / (norm1 * norm2)
        
        return max(0.0, min(1.0, similarity))  # Clamp entre 0 et 1
        
    except Exception as e:
        print(f"❌ Erreur calcul similarité: {e}")
        return 0.0

def get_domain_hierarchy(domain_obj, db: Session) -> tuple[str, str]:
    """
    Récupère le domaine racine et le chemin complet des sous-domaines
    Returns: (domain_name, subdomain_path)
    """
    if not domain_obj:
        return "", ""
    
    # Remonter la hiérarchie
    path = []
    current = domain_obj
    
    while current:
        path.insert(0, current.code or current.name)
        if current.parent_id:
            # Charger le parent
            current = db.query(Domain).filter(Domain.id == current.parent_id).first()
        else:
            break
    
    if len(path) == 0:
        return "", ""
    elif len(path) == 1:
        return path[0], ""
    else:
        # Premier = domaine racine, le reste = sous-domaines
        return path[0], " > ".join(path[1:])


# Puis dans la fonction principale

# LIGNE 150-165 : Modifier l'appel au générateur

@router.post("/generate-from-framework/{framework_id}")
async def generate_control_points_from_framework(
    framework_id: str,
    current_user: User = Depends(require_permission("REFERENTIAL_READ")),
    db: Session = Depends(get_db),
):
    """Génère des PCs avec déduplication intelligente"""
    try:
        # Convertir framework_id en UUID
        try:
            framework_uuid = UUID(framework_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="ID de référentiel invalide")
        
        # Récupérer le framework
        framework = db.query(Framework).filter(Framework.id == framework_uuid).first()
        if not framework:
            raise HTTPException(status_code=404, detail="Référentiel introuvable")
        
        # Récupérer les exigences avec leurs domaines via jointure
        from sqlalchemy import case
        from src.models.audit import Domain

        requirements = db.query(Requirement)\
            .outerjoin(Domain, Requirement.domain_id == Domain.id)\
            .filter(Requirement.framework_id == framework_uuid)\
            .add_columns(
                case(
                    (Domain.code_officiel != None, Domain.code_officiel),
                    else_=Domain.code
                ).label('domain_name')
            )\
            .all()

        if not requirements:
            raise HTTPException(status_code=404, detail="Aucune exigence trouvée")

        # Préparer les données
        req_data = []
        for req, domain_name in requirements:
            domain_label = domain_name if domain_name else "Non classé"

            req_data.append({
                "id": str(req.id),
                "code": req.official_code or f"REQ-{req.id}",
                "official_code": req.official_code,
                "title": req.title or "",
                "text": req.requirement_text or "",
                "requirement_text": req.requirement_text or "",
                "domain": domain_label,
                "subdomain": "",
                "risk_level": req.risk_level or "MEDIUM",
            })
        
        # Créer une instance du générateur
        from src.services.deepseek_pc_generator import DeepSeekControlPointGenerator
        generator = DeepSeekControlPointGenerator(db=db)
        
        logger.info(f"🚀 Génération avec déduplication pour {len(req_data)} exigences")
        
        # Générer
        result = await generator.generate_from_framework(
            framework={"id": str(framework_uuid), "name": framework.name},
            requirements=req_data,
        )
        
        # ✅ CALCULER total_generated à partir de control_points
        # LIGNE 185-210 : Remplacer le calcul de couverture

        # ✅ CALCULER total_generated à partir de control_points
        total_generated = len(result.get("control_points", []))
        
        # ✅ CALCULER coverage_percentage CORRECTEMENT
        total_requirements = len(requirements)
        
        # Créer un set des IDs d'exigences couvertes
        mapped_requirements = set()
        for cp in result.get("control_points", []):
            # Les mapped_requirements peuvent être des UUIDs ou des strings
            for req_id in cp.get("mapped_requirements", []):
                # Normaliser en string
                req_id_str = str(req_id).strip()
                mapped_requirements.add(req_id_str)
        
        # Vérifier la correspondance avec les vrais IDs
        # requirements est une liste de tuples (req, domain_name)
        actual_req_ids = {str(req.id) for req, _ in requirements}
        matched_requirements = mapped_requirements.intersection(actual_req_ids)
        
        coverage_percentage = (len(matched_requirements) / total_requirements * 100) if total_requirements > 0 else 0
        
        logger.info(f"✅ Génération terminée:")
        logger.info(f"  - PCs générés: {total_generated}")
        logger.info(f"  - Exigences totales: {total_requirements}")
        logger.info(f"  - Exigences couvertes: {len(matched_requirements)}")
        logger.info(f"  - Couverture: {coverage_percentage:.1f}%")
        logger.debug(f"  - Mapped IDs: {list(mapped_requirements)[:5]}...")
        logger.debug(f"  - Actual IDs: {list(actual_req_ids)[:5]}...")
        
        # Enrichir les PCs avec les détails des exigences
        # LIGNE 215-250 : Corriger l'enrichissement avec debug

        # Enrichir les PCs avec les détails des exigences
        enriched_cps = []
        for cp in result.get("control_points", []):
            mapped_req_details = []
            
            # Récupérer les IDs mappés
            mapped_req_ids = cp.get("mapped_requirements", [])
            logger.debug(f"PC {cp.get('code')}: mapped_requirements = {mapped_req_ids}")
            
            # Pour chaque ID mappé, trouver l'exigence correspondante
            for req_id in mapped_req_ids:
                req_id_str = str(req_id).strip()
                
                # Chercher l'exigence dans la liste (requirements est une liste de tuples)
                req_tuple = next(
                    ((r, d) for r, d in requirements if str(r.id) == req_id_str),
                    None
                )

                if req_tuple:
                    req, domain_name = req_tuple
                    mapped_req_details.append({
                        "id": str(req.id),
                        "official_code": req.official_code,
                        "title": req.title,
                        "requirement_text": req.requirement_text,
                        "domain": domain_name,
                        "subdomain": "",
                        "risk_level": req.risk_level,
                        "compliance_obligation": req.compliance_obligation,
                    })
                else:
                    logger.warning(f"⚠️ Exigence {req_id_str} non trouvée pour PC {cp.get('code')}")
            
            logger.debug(f"PC {cp.get('code')}: {len(mapped_req_details)} exigences liées")
            
            enriched_cps.append({
                "id": cp.get("id", str(uuid4())),
                "code": cp.get("cp_ref") or cp.get("code"),
                "name": cp.get("title"),
                "description": cp.get("description"),
                "domain": cp.get("domain"),
                "criticality": cp.get("criticality_level", "MEDIUM"),
                "effort_estimation": cp.get("estimated_effort_hours", 8),
                "ai_confidence": cp.get("ai_confidence", 0.7),
                "rationale": cp.get("ai_explanation") or cp.get("rationale"),
                "mapped_requirements": [str(rid) for rid in mapped_req_ids],  # ✅ Normaliser
                "mapped_requirements_details": mapped_req_details,  # ✅ Détails enrichis
                "status": "pending",
                "reused": cp.get("reused", False),
                "existing_code": cp.get("existing_code"),
                "deduplication_rationale": cp.get("deduplication_rationale"),
            })
        
        # ✅ IDENTIFIER LES ORPHELINES
        # requirements est une liste de tuples (req, domain_name)
        all_req_ids = {str(req.id) for req, _ in requirements}
        orphan_req_ids = all_req_ids - mapped_requirements
        
        # Orphelines
        orphan_details = []
        for req_id in orphan_req_ids:
            # requirements est une liste de tuples (req, domain_name)
            req_tuple = next(((r, d) for r, d in requirements if str(r.id) == req_id), None)
            if req_tuple:
                req, domain_name = req_tuple
                orphan_details.append({
                    "id": str(req.id),
                    "official_code": req.official_code,
                    "title": req.title,
                    "requirement_text": req.requirement_text,
                    "domain": domain_name,
                    "subdomain": "",
                    "risk_level": req.risk_level,
                    "compliance_obligation": req.compliance_obligation,
                })
        
        return {
            "success": True,
            "generation_results": {
                "control_points": enriched_cps,
                "total_generated": total_generated,
                "coverage_percentage": coverage_percentage,
            },
            "preview_uncovered": {
                "count": len(orphan_details),
                "items": orphan_details,
            },
            "mapping_decisions": result.get("mapping_decisions", []),
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur génération: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/generate-from-framework/{framework_id}/stream")
async def generate_control_points_stream(
    framework_id: str,
    request: Request,
    current_user: User = Depends(require_permission("REFERENTIAL_READ")),
    db: Session = Depends(get_db),
):
    """
    Endpoint SSE pour la génération de points de contrôle avec progression en temps réel.
    Envoie des événements au fur et à mesure de la génération par lots.
    """

    async def event_generator():
        """Générateur d'événements SSE"""
        progress_queue = asyncio.Queue()

        async def progress_callback(batch_idx: int, total_batches: int, status: str, data: dict):
            """Callback appelé par le générateur pour chaque progression"""
            event_data = {
                "batch_index": batch_idx,
                "total_batches": total_batches,
                "status": status,
                **data
            }
            await progress_queue.put(event_data)

        try:
            # Convertir framework_id en UUID
            try:
                framework_uuid = UUID(framework_id)
            except ValueError:
                yield f"data: {json.dumps({'error': 'ID de référentiel invalide'})}\n\n"
                return

            # Récupérer le framework
            framework = db.query(Framework).filter(Framework.id == framework_uuid).first()
            if not framework:
                yield f"data: {json.dumps({'error': 'Référentiel introuvable'})}\n\n"
                return

            # Envoyer l'événement de démarrage
            yield f"data: {json.dumps({'status': 'initializing', 'message': 'Chargement des exigences...'})}\n\n"

            # Récupérer les exigences
            from sqlalchemy import case
            from src.models.audit import Domain

            requirements = db.query(Requirement)\
                .outerjoin(Domain, Requirement.domain_id == Domain.id)\
                .filter(Requirement.framework_id == framework_uuid)\
                .add_columns(
                    case(
                        (Domain.code_officiel != None, Domain.code_officiel),
                        else_=Domain.code
                    ).label('domain_name')
                )\
                .all()

            if not requirements:
                yield f"data: {json.dumps({'error': 'Aucune exigence trouvée'})}\n\n"
                return

            # Préparer les données
            req_data = []
            for req, domain_name in requirements:
                domain_label = domain_name if domain_name else "Non classé"
                req_data.append({
                    "id": str(req.id),
                    "code": req.official_code or f"REQ-{req.id}",
                    "official_code": req.official_code,
                    "title": req.title or "",
                    "text": req.requirement_text or "",
                    "requirement_text": req.requirement_text or "",
                    "domain": domain_label,
                    "subdomain": "",
                    "risk_level": req.risk_level or "MEDIUM",
                })

            yield f"data: {json.dumps({'status': 'loaded', 'total_requirements': len(req_data)})}\n\n"

            # Créer le générateur
            from src.services.deepseek_pc_generator import DeepSeekControlPointGenerator
            generator = DeepSeekControlPointGenerator(db=db)

            # Lancer la génération dans une tâche séparée
            async def run_generation():
                return await generator.generate(
                    requirements=req_data,
                    context={
                        "framework": {
                            "id": str(framework_uuid),
                            "name": framework.name,
                        }
                    },
                    progress_callback=progress_callback
                )

            generation_task = asyncio.create_task(run_generation())

            # Envoyer les événements de progression
            while not generation_task.done():
                try:
                    # Attendre un événement avec timeout
                    event_data = await asyncio.wait_for(progress_queue.get(), timeout=0.5)
                    yield f"data: {json.dumps(event_data)}\n\n"
                except asyncio.TimeoutError:
                    # Vérifier si le client est toujours connecté
                    if await request.is_disconnected():
                        generation_task.cancel()
                        return
                    continue

            # Récupérer le résultat final
            result = await generation_task

            # Enrichir et formater le résultat (même logique que l'endpoint POST)
            total_generated = len(result.get("control_points", []))
            total_requirements = len(requirements)

            mapped_requirements = set()
            for cp in result.get("control_points", []):
                for req_id in cp.get("mapped_requirements", []):
                    mapped_requirements.add(str(req_id).strip())

            actual_req_ids = {str(req.id) for req, _ in requirements}
            matched_requirements = mapped_requirements.intersection(actual_req_ids)
            coverage_percentage = (len(matched_requirements) / total_requirements * 100) if total_requirements > 0 else 0

            # Enrichir les PCs
            enriched_cps = []
            for cp in result.get("control_points", []):
                mapped_req_details = []
                mapped_req_ids = cp.get("mapped_requirements", [])

                for req_id in mapped_req_ids:
                    req_id_str = str(req_id).strip()
                    req_tuple = next(
                        ((r, d) for r, d in requirements if str(r.id) == req_id_str),
                        None
                    )
                    if req_tuple:
                        req, domain_name = req_tuple
                        mapped_req_details.append({
                            "id": str(req.id),
                            "official_code": req.official_code,
                            "title": req.title,
                            "requirement_text": req.requirement_text,
                            "domain": domain_name,
                            "subdomain": "",
                            "risk_level": req.risk_level,
                            "compliance_obligation": req.compliance_obligation,
                        })

                enriched_cps.append({
                    "id": cp.get("id", str(uuid4())),
                    "code": cp.get("cp_ref") or cp.get("code"),
                    "name": cp.get("title"),
                    "description": cp.get("description"),
                    "domain": cp.get("domain"),
                    "criticality": cp.get("criticality_level", "MEDIUM"),
                    "effort_estimation": cp.get("estimated_effort_hours", 8),
                    "ai_confidence": cp.get("ai_confidence", 0.7),
                    "rationale": cp.get("ai_explanation") or cp.get("rationale"),
                    "mapped_requirements": [str(rid) for rid in mapped_req_ids],
                    "mapped_requirements_details": mapped_req_details,
                    "status": "pending",
                })

            # Orphelines
            all_req_ids = {str(req.id) for req, _ in requirements}
            orphan_req_ids = all_req_ids - mapped_requirements

            orphan_details = []
            for req_id in orphan_req_ids:
                req_tuple = next(((r, d) for r, d in requirements if str(r.id) == req_id), None)
                if req_tuple:
                    req, domain_name = req_tuple
                    orphan_details.append({
                        "id": str(req.id),
                        "official_code": req.official_code,
                        "title": req.title,
                        "requirement_text": req.requirement_text,
                        "domain": domain_name,
                        "subdomain": "",
                        "risk_level": req.risk_level,
                        "compliance_obligation": req.compliance_obligation,
                    })

            # Envoyer le résultat final
            final_result = {
                "status": "completed",
                "success": True,
                "generation_results": {
                    "control_points": enriched_cps,
                    "total_generated": total_generated,
                    "coverage_percentage": coverage_percentage,
                },
                "preview_uncovered": {
                    "count": len(orphan_details),
                    "items": orphan_details,
                },
            }
            yield f"data: {json.dumps(final_result)}\n\n"

        except Exception as e:
            logger.error(f"❌ Erreur SSE: {e}", exc_info=True)
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
        }
    )


@router.post("/control-points/{cp_id}/save-complementary", summary="Sauvegarder un PC complémentaire")
async def save_complementary_control_point(
    cp_id: str,
    complementary_data: dict,
    current_user: User = Depends(require_permission("REFERENTIAL_READ")),
    db: Session = Depends(get_db)
):
    """
    Crée un 'Point de Contrôle complémentaire' rattaché au PC parent, 
    puis lie les mêmes exigences au nouveau PC.
    IMPORTANT : on utilise le helper _link_requirements_to_cp(..., mapping_method='ai_generation')
    pour tagger correctement l'origine IA sur les liaisons.
    """
    # 1) Vérifier le parent
    parent_cp = db.query(ControlPoint).filter_by(id=cp_id).first()
    if not parent_cp:
        raise HTTPException(status_code=404, detail="PC parent introuvable")

    # 2) Récupérer les exigences du parent
    rows = db.execute(text("""
        SELECT requirement_id
        FROM requirement_control_point
        WHERE control_point_id = :parent_id
    """), {"parent_id": cp_id}).fetchall()
    parent_req_ids = [str(r.requirement_id) for r in rows]

    # 3) Normaliser les données du nouveau PC
    crit_map = {"CRITICAL": "critical", "HIGH": "high", "MEDIUM": "medium", "LOW": "low"}
    criticality_in = (complementary_data.get("criticality") or "MEDIUM").upper()

    new_pc = ControlPoint(
        id=str(uuid4()),
        code=complementary_data.get("code") or f"CPL-{str(uuid4())[:8]}",
        name=complementary_data.get("name", "Contrôle complémentaire"),
        description=complementary_data.get("description", ""),
        category=complementary_data.get("category"),
        subcategory=complementary_data.get("subcategory"),
        criticality_level=crit_map.get(criticality_in, "medium"),
        implementation_guidance=complementary_data.get("implementation_guidance", ""),
        created_by="ai_complementary",       # on trace bien que c’est issu d’un flux IA
        ai_confidence=complementary_data.get("ai_confidence", 0.8),
        is_active=True
    )
    db.add(new_pc)
    db.flush()  # pour obtenir l'ID

    # 4) 🔗 Lier au nouveau PC TOUTES les exigences du parent
    #    >>> ICI la différence clé : on passe par le helper ET on force mapping_method=AI_METHOD
    _link_requirements_to_cp(db, str(new_pc.id), parent_req_ids, mapping_method=AI_METHOD)

    # 5) Commit (et éventuels traitements best-effort autour des embeddings)
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erreur création PC complémentaire : {e}")

    return {
        "success": True,
        "message": "PC complémentaire créé",
        "control_point": {
            "id": str(new_pc.id),
            "code": new_pc.code,
            "name": new_pc.name,
            "description": new_pc.description
        },
        "mapped_requirements_count": len(parent_req_ids)
    }

# Test à ajouter temporairement dans control_points.py

@router.get("/test-cp-query/{framework_id}")
def test_cp_query(framework_id: str, current_user: User = Depends(require_permission("REFERENTIAL_READ")), db: Session = Depends(get_db)):
    """Endpoint de test pour diagnostiquer la requête"""
    from sqlalchemy import text
    
    # 1. Vérifier les PCs liés à ce framework
    query1 = text("""
        SELECT 
            cp.id,
            cp.code,
            cp.name,
            cp.description,
            COUNT(DISTINCT rcp.requirement_id) as req_count
        FROM control_point cp
        INNER JOIN requirement_control_point rcp ON cp.id = rcp.control_point_id
        INNER JOIN requirement r ON r.id = rcp.requirement_id
        WHERE r.framework_id = :fw_id
        GROUP BY cp.id, cp.code, cp.name, cp.description
        ORDER BY cp.code
    """)
    
    result1 = db.execute(query1, {"fw_id": framework_id}).fetchall()
    
    # 2. Vérifier la table requirement_control_point
    query2 = text("""
        SELECT COUNT(*) as total
        FROM requirement_control_point rcp
        INNER JOIN requirement r ON r.id = rcp.requirement_id
        WHERE r.framework_id = :fw_id
    """)
    
    result2 = db.execute(query2, {"fw_id": framework_id}).scalar()
    
    # 3. Vérifier les exigences du framework
    query3 = text("""
        SELECT COUNT(*) as total
        FROM requirement
        WHERE framework_id = :fw_id
    """)
    
    result3 = db.execute(query3, {"fw_id": framework_id}).scalar()
    
    return {
        "framework_id": framework_id,
        "control_points_found": len(result1),
        "control_points": [
            {
                "id": str(row.id),
                "code": row.code,
                "name": row.name,
                "description": row.description[:100] if row.description else None,
                "requirement_count": row.req_count
            }
            for row in result1
        ],
        "total_mappings": result2,
        "total_requirements": result3
    }


# LIGNE 486-686 : REMPLACER TOUTE LA FONCTION

@router.post("/search-similar", summary="🔍 Rechercher des PCs similaires")
async def search_similar_control_points(
    request: Dict[str, Any],
    current_user: User = Depends(require_permission("REFERENTIAL_READ")),
    db: Session = Depends(get_db)
):
    """
    Recherche sémantique via la table control_point_embeddings EXISTANTE.
    """
    try:
        requirement_text = request.get("requirement_text", "").strip()
        domain = request.get("domain")
        subdomain = request.get("subdomain")
        min_similarity = float(request.get("min_similarity", 0.7))
        
        if not requirement_text or len(requirement_text) < 10:
            raise HTTPException(
                status_code=400,
                detail="Le texte de recherche doit contenir au moins 10 caractères"
            )
        
        logger.info(f"🔍 Recherche PC similaire pour: '{requirement_text[:100]}...'")
        
        # ✅ Utiliser ControlPointEmbeddingService (qui existe déjà)
        if not ControlPointEmbeddingService:
            raise HTTPException(
                status_code=503,
                detail="Le service d'embeddings n'est pas disponible. Veuillez contacter l'administrateur."
            )
        
        service = ControlPointEmbeddingService(db)
        
        # ✅ Appeler la méthode search_similar du service
        similar_pcs = service.search_similar(
            query_text=requirement_text,
            min_similarity=min_similarity,
            limit=10
        )
        
        return {
            "search_text": requirement_text[:200],
            "min_similarity": min_similarity,
            "total_found": len(similar_pcs),
            "similar_control_points": similar_pcs
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur recherche similarité: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Une erreur est survenue lors de la recherche. Si le problème persiste, veuillez contacter l'administrateur."
        )
    
# ============================================================================
# GÉNÉRATION DE POINTS DE CONTRÔLE
# ============================================================================

# Modèle Pydantic pour la requête

class GenerateFromFrameworkRequest(BaseModel):
    """Requête pour générer des PC depuis un framework"""
    framework_id: UUID = Field(..., description="ID du framework")
    batch_size: Optional[int] = Field(None, description="Taille des batchs")
    max_control_points: Optional[int] = Field(50, description="Nombre max de PC par exigence")

@router.post("/generate", summary="Générer un PC à partir d'une exigence")
async def generate_single_control_point(
    request_data: Dict[str, Any] = Body(...),  # ← Ajouter Body(...)
    current_user: User = Depends(require_permission("REFERENTIAL_READ")),
    db: Session = Depends(get_db),
    gen: DeepSeekControlPointGenerator = Depends(get_deepseek_generator)
):
    """
    Génère UN point de contrôle à partir d'UNE exigence.
    """
    try:
        start_time = time.time()
        
        # Extraire l'exigence
        req = request_data.get("requirement", {})
        
        if not req:
            raise HTTPException(
                status_code=400,
                detail="Le champ 'requirement' est obligatoire"
            )
        
        code = req.get("code", "")
        text = req.get("text", "")
        framework = req.get("framework", "ISO 27002")
        force_refresh = request_data.get("force_refresh", False)  # ✅ Nouveau paramètre

        if not text:
            raise HTTPException(
                status_code=400,
                detail="Le champ 'text' est obligatoire dans requirement"
            )

        # ✅ REDIS CACHE: Vérifier le cache d'abord (sauf si force_refresh)
        from src.utils.redis_manager import redis_manager
        import hashlib

        # Créer une clé de cache basée sur le texte + framework
        cache_key_data = f"{text}:{framework}"
        cache_hash = hashlib.md5(cache_key_data.encode()).hexdigest()
        cache_key = f"ai:control_point:{cache_hash}"

        if not force_refresh:
            cached_result = redis_manager.get(cache_key)
            if cached_result:
                logger.info(f"✅ Cache HIT pour PC: {code}")
                return {
                    "success": True,
                    "control_point": cached_result,
                    "metadata": {
                        "model_used": gen.model,
                        "generation_time_seconds": 0.001,  # Quasi instantané!
                        "requirement_code": code,
                        "cached": True  # ✅ Indique que c'est du cache
                    }
                }

        logger.info(f"🔄 Génération PC pour exigence: {code} (cache MISS)")

        # Préparer l'exigence
        req_data = {
            "id": str(uuid4()),
            "code": code or "REQ-001",
            "official_code": code or "",
            "title": text[:100],
            "text": text,
            "description": text,
        }

        # Contexte
        context = {
            "framework": {
                "name": framework,
                "locale": "fr"
            }
        }

        # Appeler le générateur
        result = await gen.generate(
            requirements=[req_data],
            context=context
        )
        
        control_points = result.get("control_points", [])
        
        if not control_points:
            raise HTTPException(
                status_code=500,
                detail="Le modèle n'a généré aucun point de contrôle"
            )
        
        # Prendre le premier PC
        pc = control_points[0]

        # ✅ REDIS CACHE: Mettre en cache le résultat pour 2h
        redis_manager.set(cache_key, pc, ttl=7200)
        logger.info(f"💾 PC mis en cache pour: {code}")

        generation_time = round(time.time() - start_time, 2)

        logger.info(f"✅ PC généré: {pc.get('code')} en {generation_time}s")

        return {
            "success": True,
            "control_point": pc,
            "metadata": {
                "model_used": gen.model,
                "generation_time_seconds": generation_time,
                "requirement_code": code,
                "cached": False  # ✅ Indique que c'est une nouvelle génération
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# Chercher la route POST /generate-from-framework/{framework_id}
# Vers la ligne 150-200

    
@router.post("/generate-from-requirement")
async def generate_control_point_from_requirement(
    payload: dict,
    db: Session = Depends(get_db),
):
    """Génère un PC ciblé pour une exigence spécifique"""
    try:
        requirement_id = payload.get("requirement_id")
        framework_id = payload.get("framework_id")
        
        logger.info(f"🎯 Génération PC ciblée pour exigence: {requirement_id}")
        
        # ✅ Convertir framework_id en UUID
        try:
            framework_uuid = UUID(framework_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="ID de référentiel invalide")
        
        # Récupérer l'exigence
        requirement = db.query(Requirement).filter(Requirement.id == requirement_id).first()
        if not requirement:
            raise HTTPException(status_code=404, detail="Exigence introuvable")
        
        # Récupérer le framework
        framework = db.query(Framework).filter(Framework.id == framework_uuid).first()
        if not framework:
            raise HTTPException(status_code=404, detail="Référentiel introuvable")
        
        # ✅ Préparer les données de l'exigence (dans une LISTE)
        domain_name = requirement.domain_rel.domain_title if requirement.domain_rel else "Non classé"
        
        req_data = [{  # ✅ LISTE avec UN élément
            "id": str(requirement.id),
            "code": requirement.official_code or f"REQ-{requirement.id}",
            "official_code": requirement.official_code,
            "title": requirement.title or "",
            "text": requirement.requirement_text or "",
            "requirement_text": requirement.requirement_text or "",
            "domain": domain_name,
            "subdomain": "",
            "risk_level": requirement.risk_level or "MEDIUM",
        }]
        
        # ✅ Créer une instance du générateur
        from src.services.deepseek_pc_generator import DeepSeekControlPointGenerator
        generator = DeepSeekControlPointGenerator(db=db)
        
        logger.info(f"🚀 Génération pour 1 exigence")
        
        # Générer
        result = await generator.generate_from_framework(
            framework={"id": str(framework_uuid), "name": framework.name},
            requirements=req_data,  # ✅ LISTE
        )
        
        # ✅ CALCULER total_generated à partir de control_points
        total_generated = len(result.get("control_points", []))
        
        # ✅ CALCULER coverage_percentage (pour 1 exigence)
        total_requirements = 1  # ✅ On traite 1 seule exigence
        mapped_requirements = set()
        for cp in result.get("control_points", []):
            for req_id in cp.get("mapped_requirements", []):
                mapped_requirements.add(req_id)
        
        coverage_percentage = (len(mapped_requirements) / total_requirements * 100) if total_requirements > 0 else 0
        
        logger.info(f"✅ Génération terminée:")
        logger.info(f"  - PCs générés: {total_generated}")
        logger.info(f"  - Couverture: {coverage_percentage:.1f}%")
        
        # Enrichir les PCs avec les détails de l'exigence
        enriched_cps = []
        for cp in result.get("control_points", []):
            # ✅ Pour une seule exigence, pas besoin de boucle
            mapped_req_details = [{
                "id": str(requirement.id),
                "official_code": requirement.official_code,
                "title": requirement.title,
                "requirement_text": requirement.requirement_text,
                "domain": domain_name,
                "subdomain": "",
                "risk_level": requirement.risk_level,
                "compliance_obligation": requirement.compliance_obligation,
            }]
            
            enriched_cps.append({
                "id": cp.get("id", str(uuid4())),
                "code": cp.get("cp_ref") or cp.get("code"),
                "name": cp.get("title"),
                "description": cp.get("description"),
                "domain": cp.get("domain"),
                "criticality": cp.get("criticality_level", "MEDIUM"),
                "effort_estimation": cp.get("estimated_effort_hours", 8),
                "ai_confidence": cp.get("ai_confidence", 0.7),
                "rationale": cp.get("ai_explanation") or cp.get("rationale"),
                "mapped_requirements": cp.get("mapped_requirements", []),
                "mapped_requirements_details": mapped_req_details,
                "status": "pending",
                "reused": cp.get("reused", False),
                "existing_code": cp.get("existing_code"),
                "deduplication_rationale": cp.get("deduplication_rationale"),
            })
        
        # ✅ Identifier les orphelines (si l'exigence n'a pas été couverte)
        orphan_details = []
        if str(requirement.id) not in mapped_requirements:
            orphan_details.append({
                "id": str(requirement.id),
                "official_code": requirement.official_code,
                "title": requirement.title,
                "requirement_text": requirement.requirement_text,
                "domain": domain_name,
                "subdomain": "",
                "risk_level": requirement.risk_level,
                "compliance_obligation": requirement.compliance_obligation,
            })
        
        return {
            "success": True,
            "generation_results": {
                "control_points": enriched_cps,
                "total_generated": total_generated,
                "coverage_percentage": coverage_percentage,
            },
            "preview_uncovered": {
                "count": len(orphan_details),
                "items": orphan_details,
            },
            "mapping_decisions": result.get("mapping_decisions", []),
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur génération: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/generator-status")
async def get_generator_status(
    gen: DeepSeekControlPointGenerator = Depends(get_deepseek_generator)
):
    """
    Retourne le statut et la configuration du générateur.
    
    Returns:
        Configuration actuelle du générateur
    """
    return {
        "status": "operational",
        "model": gen.model,
        "ollama_url": gen.ollama_url,
        "batch_size": gen.batch_size,
        "parameters": {
            "num_ctx": gen.num_ctx,
            "num_predict": gen.num_predict,
            "temperature": gen.temperature,
            "top_p": gen.top_p,
            "repeat_penalty": gen.repeat_penalty
        },
        "timeout": gen.timeout,
        "max_retries": gen.max_retries
    }


# ============================================================================
# GÉNÉRATION EMBEDDINGS
# ============================================================================

@router.post("/generate-embeddings", summary="Générer embeddings pour les PC")
async def generate_embeddings(
    db: Session = Depends(get_db),
    force_regenerate: bool = False,
    framework_id: Optional[str] = None,   # 👈 NEW
):
    """Génère ou régénère les embeddings pour les PC (global ou par référentiel)"""
    if not ControlPointEmbeddingService:
        raise HTTPException(503, "Service embeddings non disponible")

    service = ControlPointEmbeddingService(db)

    # 👇 Sélection des PCs selon le scope
    if framework_id:
        # Vérif framework
        fw = db.query(Framework).filter_by(id=framework_id).first()
        if not fw:
            raise HTTPException(404, "Référentiel introuvable")

        from ...models.audit import RequirementControlPoint, Requirement
        query = (
            db.query(ControlPoint)
              .join(RequirementControlPoint, RequirementControlPoint.control_point_id == ControlPoint.id)
              .join(Requirement, Requirement.id == RequirementControlPoint.requirement_id)
              .filter(Requirement.framework_id == framework_id, ControlPoint.is_active == True)
              .distinct()
        )
        control_points = query.all()
        scope_label = f"référentiel {fw.code}"
    else:
        control_points = db.query(ControlPoint).filter_by(is_active=True).all()
        scope_label = "tous les PC actifs"

    if not control_points:
        return {
            "success": True,
            "message": f"Aucun point de contrôle à traiter pour {scope_label}",
            "processed": 0,
            "scope": "framework" if framework_id else "global",
            "framework_id": framework_id,
        }

    logger.info(f"Génération embeddings pour {len(control_points)} PC ({scope_label})")

    processed = 0
    errors = []

    for cp in control_points:
        try:
            if not force_regenerate:
                from sqlalchemy import text
                check_query = text("""
                    SELECT COUNT(*) AS count
                    FROM control_point_embeddings
                    WHERE control_point_id = :cp_id
                """)
                result = db.execute(check_query, {"cp_id": str(cp.id)}).fetchone()
                if result and result.count > 0:
                    continue

            # Générer embedding
            service.generate_and_store_embedding(cp)
            processed += 1

            if processed % 10 == 0:
                db.commit()
                logger.info(f"Progress: {processed}/{len(control_points)} PC traités")

        except Exception as e:
            logger.error(f"Erreur embedding pour PC {cp.id}: {e}")
            errors.append({
                "control_point_id": str(cp.id),
                "code": cp.code,
                "error": str(e)
            })
            # pas de raise : on continue

    db.commit()
    logger.info(f"Embeddings générés : {processed}/{len(control_points)} PC ({scope_label})")

    return {
        "success": True,
        "message": "Embeddings générés avec succès",
        "total_control_points": len(control_points),
        "processed": processed,
        "skipped": len(control_points) - processed - len(errors),
        "errors_count": len(errors),
        "errors": errors[:10] if errors else [],
        "scope": "framework" if framework_id else "global",
        "framework_id": framework_id,
    }



@router.post("/generate-embeddings/{cp_id}", summary="Générer embedding pour un PC")
async def generate_embedding_for_cp(
    cp_id: str,
    db: Session = Depends(get_db)
):
    """Génère l'embedding pour un PC spécifique"""
    if not ControlPointEmbeddingService:
        raise HTTPException(503, "Service embeddings non disponible")
    
    cp = db.query(ControlPoint).filter_by(id=cp_id).first()
    if not cp:
        raise HTTPException(404, "Point de contrôle introuvable")
    
    try:
        service = ControlPointEmbeddingService(db)
        service.generate_and_store_embedding(cp)
        db.commit()
        
        return {
            "success": True,
            "message": f"Embedding généré pour {cp.code}",
            "control_point_id": str(cp.id)
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"Erreur génération embedding : {e}")
        raise HTTPException(500, f"Erreur : {str(e)}")


@router.get("/embeddings/stats", summary="Statistiques embeddings")
def embeddings_stats(db: Session = Depends(get_db)):
    """Statistiques sur les embeddings des PC"""
    from sqlalchemy import text
    
    stats_query = text("""
        SELECT 
            COUNT(DISTINCT cp.id) as total_control_points,
            COUNT(DISTINCT cpe.control_point_id) as with_embeddings,
            COUNT(DISTINCT cp.id) - COUNT(DISTINCT cpe.control_point_id) as without_embeddings
        FROM control_point cp
        LEFT JOIN control_point_embeddings cpe ON cp.id = cpe.control_point_id
        WHERE cp.is_active = true
    """)
    
    result = db.execute(stats_query).fetchone()
    
    total = result.total_control_points if result else 0
    with_emb = result.with_embeddings if result else 0
    without_emb = result.without_embeddings if result else 0
    
    coverage = (with_emb / total * 100) if total > 0 else 0
    
    return {
        "total_control_points": total,
        "with_embeddings": with_emb,
        "without_embeddings": without_emb,
        "coverage_percentage": round(coverage, 2)
    }


# ============================================================================
# FRAMEWORKS DISPONIBLES
# ============================================================================

@router.get("/frameworks-for-generation", summary="Liste des référentiels disponibles")
def frameworks_for_generation(db: Session = Depends(get_db)):
    """Retourne les référentiels ayant des exigences"""
    from sqlalchemy import func
    
    query = db.query(
        Framework.id,
        Framework.code,
        Framework.name,
        Framework.version,
        Framework.is_active,
        func.count(Requirement.id).label("requirements_count")
    ).outerjoin(
        Requirement, Framework.id == Requirement.framework_id
    ).group_by(
        Framework.id
    ).having(
        func.count(Requirement.id) > 0
    ).filter(
        Framework.is_active == True
    ).order_by(
        Framework.name
    )
    
    results = query.all()
    
    return {
        "frameworks": [
            {
                "id": str(row.id),
                "code": row.code,
                "name": row.name,
                "version": row.version,
                "requirements_count": row.requirements_count
            }
            for row in results
        ],
        "total": len(results)
    }


# ============================================================================
# SAUVEGARDE DES PC VALIDÉS
# ============================================================================

class SaveValidatedBody(BaseModel):
    framework_id: str
    control_points: List[dict]

@router.post("/save-validated", summary="Sauvegarder les PC validés")
async def save_validated(
    payload: SaveValidatedBody,
    db: Session = Depends(get_db)
):
    """
    Sauvegarde les points de contrôle validés et crée les liens requirement<->control_point.
    Règles:
      - Si 'existing_control_point_id' fourni -> réutilise ce PC.
      - Sinon, si 'code' existe déjà -> réutilise (pas de doublon).
      - Sinon, crée le PC et lie les exigences.
      - Génère les embeddings pour les NOUVEAUX PC uniquement (best effort).
    """
    if not payload.control_points:
        raise HTTPException(status_code=400, detail="Aucun point de contrôle transmis")

    fw = db.query(Framework).filter_by(id=payload.framework_id).first()
    if not fw:
        raise HTTPException(status_code=404, detail=f"Référentiel {payload.framework_id} non trouvé")

    logger.info("=== /save-validated ===")
    logger.info(f"Framework: {fw.code} ({fw.name})")
    logger.info(f"PC reçus: {len(payload.control_points)}")

    created_count = reused_count = total_mappings_created = 0
    created_pc_ids: List[str] = []
    errors: List[str] = []

    # ✅ ÉTAPE 1 : CRÉATION/RÉUTILISATION DES PC (code existant)
    for idx, cp_data in enumerate(payload.control_points):
        try:
            mm = _infer_mapping_method(
                source=cp_data.get("created_by"),
                explicit=cp_data.get("mapping_method"),
            )

            mapped_requirements = [
                r["id"] if isinstance(r, dict) else r
                for r in (cp_data.get("mapped_requirements_details") or [])
                if (isinstance(r, dict) and r.get("id")) or isinstance(r, str)
            ] or (cp_data.get("mapped_requirements") or [])
            mapped_requirements = [rid for rid in mapped_requirements if rid]

            existing_id = cp_data.get("existing_control_point_id")
            cp_code = (cp_data.get("code") or "").strip() or None

            # 1) Réutilisation explicite par ID
            if existing_id:
                existing_cp = db.query(ControlPoint).filter_by(id=existing_id).first()
                if existing_cp:
                    logger.info(f"[{idx+1}] Réutilise PC (id) {existing_cp.code} → liens x{len(mapped_requirements)}")
                    reused_count += 1
                    total_mappings_created += _link_requirements_to_cp(
                        db, existing_cp.id, mapped_requirements, mapping_method=mm
                    )
                    continue

            # 2) Réutilisation par code
            if cp_code:
                already = db.query(ControlPoint).filter_by(code=cp_code).first()
                if already:
                    logger.info(f"[{idx+1}] Réutilise PC (code) {already.code} → liens x{len(mapped_requirements)}")
                    reused_count += 1
                    total_mappings_created += _link_requirements_to_cp(
                        db, already.id, mapped_requirements, mapping_method=mm
                    )
                    continue

            # 3) Création du PC
            cp_id = _create_new_control_point(db, cp_data)
            db.flush()
            created_count += 1
            created_pc_ids.append(cp_id)  # ✅ On garde l'ID pour les embeddings
            logger.info(f"[{idx+1}] Nouveau PC créé: {cp_data.get('code')} → liens x{len(mapped_requirements)}")

            total_mappings_created += _link_requirements_to_cp(
                db, cp_id, mapped_requirements, mapping_method=mm
            )

        except IntegrityError:
            db.rollback()
            if cp_code:
                already = db.query(ControlPoint).filter_by(code=cp_code).first()
                if already:
                    logger.info(f"[{idx+1}] Collision→Réutilise {already.code} → liens x{len(mapped_requirements)}")
                    reused_count += 1
                    total_mappings_created += _link_requirements_to_cp(
                        db, already.id, mapped_requirements, mapping_method=mm
                    )
                else:
                    msg = f"[{idx+1}] Collision mais PC introuvable après rollback pour code={cp_code}"
                    logger.error(msg)
                    errors.append(msg)
            else:
                msg = f"[{idx+1}] Collision sans 'code' fourni"
                logger.error(msg)
                errors.append(msg)
        except Exception as e:
            db.rollback()
            msg = f"[{idx+1}] Erreur sauvegarde PC: {e}"
            logger.exception(msg)
            errors.append(msg)

    # Commit global des INSERTs de mapping
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Échec commit mappings: {e}")

    # ✅ ÉTAPE 2 : GÉNÉRATION DES EMBEDDINGS POUR LES PC CRÉÉS
    embeddings_generated = 0
    embeddings_failed = 0
    
    if created_pc_ids and ControlPointEmbeddingService:
        logger.info(f"🔄 Génération d'embeddings pour {len(created_pc_ids)} PC créés...")
        
        try:
            service = ControlPointEmbeddingService(db)
            
            for pc_id in created_pc_ids:
                try:
                    # Récupérer le PC
                    cp = db.query(ControlPoint).filter_by(id=pc_id).first()
                    if not cp:
                        logger.warning(f"⚠️ PC {pc_id} introuvable pour embedding")
                        continue
                    
                    # Générer l'embedding
                    service.generate_and_store_embedding(cp)
                    embeddings_generated += 1
                    logger.info(f"✅ Embedding généré pour PC {cp.code}")
                    
                except Exception as emb_error:
                    embeddings_failed += 1
                    logger.warning(f"⚠️ Erreur embedding pour PC {pc_id}: {emb_error}")
                    # On continue même si un embedding échoue
                    continue
            
            # Commit final des embeddings
            db.commit()
            logger.info(f"✅ Embeddings: {embeddings_generated} générés, {embeddings_failed} échoués")
            
        except Exception as e:
            logger.error(f"❌ Erreur globale génération embeddings: {e}")
            # On ne fait pas échouer la sauvegarde si les embeddings échouent
    
    else:
        if not ControlPointEmbeddingService:
            logger.warning("⚠️ Service d'embeddings non disponible")
        elif not created_pc_ids:
            logger.info("ℹ️ Aucun nouveau PC créé, pas d'embeddings à générer")

    # ✅ RETOUR AVEC INFO EMBEDDINGS
    return {
        "success": len(errors) == 0,
        "created": created_count,
        "reused": reused_count,
        "mappings_created": total_mappings_created,
        "embeddings_generated": embeddings_generated,  # ✅ AJOUTÉ
        "embeddings_failed": embeddings_failed,        # ✅ AJOUTÉ
        "errors": errors,
        "created_pc_ids": created_pc_ids,
    }



# LIGNE 907-950 : REMPLACER

def _create_new_control_point(db: Session, cp_data: dict) -> str:
    """Crée un nouveau point de contrôle et retourne son ID"""
    data = dict(cp_data)
    
    if "name" not in data and "title" in data:
        data["name"] = data.pop("title")

    if "category" not in data and "domain" in data:
        data["category"] = data.get("domain")
    if "subcategory" not in data and "subdomain" in data:
        data["subcategory"] = data.get("subdomain")

    if "criticality" in data:
        enum_map = {"CRITICAL": "critical", "HIGH": "high", "MEDIUM": "medium", "LOW": "low"}
        val = str(data.pop("criticality")).strip()
        data["criticality_level"] = enum_map.get(val.upper(), val.lower())

    new_cp = ControlPoint(
        id=str(uuid4()),
        code=data.get("code"),
        name=data.get("name"),
        description=data.get("description"),
        category=data.get("category"),
        subcategory=data.get("subcategory"),
        control_family=data.get("control_family"),
        risk_domains=data.get("risk_domains"),
        implementation_level=data.get("implementation_level", "basic"),
        estimated_effort_hours=data.get("effort_estimation") or data.get("estimated_effort_hours", 8),
        created_by=data.get("created_by", "human"),
        ai_confidence=data.get("ai_confidence"),
        is_active=bool(data.get("is_active", True)),
        criticality_level=data.get("criticality_level", "medium"),
        implementation_guidance=data.get("implementation_guidance"),
    )
    db.add(new_cp)
    db.flush()  # ✅ AJOUTER FLUSH POUR GÉNÉRER L'ID
    logger.info(f"Nouveau PC créé: {new_cp.code}")
    return str(new_cp.id)  # ✅ RETOURNER STRING


def _link_requirements_to_cp(
    db: Session,
    control_point_id: str,
    requirement_ids: List[str],
    mapping_method: str = HUMAN_METHOD,   # 👈 NEW
) -> int:
    """
    Crée les liens requirement <-> control_point dans 'requirement_control_point'.
    Idempotent (ON CONFLICT DO NOTHING). Retourne le nb de liens tentés (après dédup).
    """
    logger.info(
        f"🔍 _link_requirements_to_cp: cp_id={str(control_point_id)[:8]}..., "
        f"req_ids_preview={(requirement_ids or [])[:5]}, method={mapping_method}"
    )

    if not requirement_ids:
        return 0

    # Normalisation / dédup
    norm_ids: List[str] = []
    for rid in requirement_ids:
        if not rid:
            continue
        rid_str = rid if isinstance(rid, str) else (rid.get("id") if isinstance(rid, dict) else None)
        if rid_str:
            norm_ids.append(str(rid_str).strip())

    norm_ids = [r for r in dict.fromkeys([r for r in norm_ids if r])]
    if not norm_ids:
        return 0

    # INSERT avec mapping_method
    sql = text("""
        INSERT INTO requirement_control_point (requirement_id, control_point_id, mapping_method)
        VALUES (:rid, :cpid, :mm)
        ON CONFLICT DO NOTHING
    """)

    inserted_count = 0
    for rid in norm_ids:
        result = db.execute(sql, {"rid": rid, "cpid": str(control_point_id), "mm": mapping_method})
        inserted_count += result.rowcount

    logger.info(
        f"Mappings créés pour PC {str(control_point_id)[:8]}...: "
        f"{inserted_count}/{len(norm_ids)} (method={mapping_method})"
    )
    return inserted_count



# ============================================================================
# ENDPOINTS ADDITIONNELS
# ============================================================================


@router.get("/by-id/{cp_id}", summary="Détail d’un point de contrôle")
def get_control_point(cp_id: UUID, db: Session = Depends(get_db)):
    cp = db.query(ControlPoint).filter_by(id=str(cp_id)).first()
    if not cp:
        raise HTTPException(404, "Point de contrôle introuvable")
    return {
        "id": str(cp.id),
        "code": cp.code,
        "name": cp.name,
        "description": cp.description,
        # ...
    }



@router.get("/stats", summary="Stats globales")
def control_points_stats(db: Session = Depends(get_db)):
    total = db.query(ControlPoint).count()
    active = db.query(ControlPoint).filter_by(is_active=True).count()
    return {"total": total, "active": active}


# Test connexion IA
@router.get("/ai/health", summary="Vérifier la connexion à Ollama/DeepSeek")
async def ai_health():
    """Endpoint de diagnostic pour vérifier si l'IA est accessible"""
    try:
        from .openai_generator import test_ai_connection
        return await test_ai_connection()
    except ImportError:
        return {
            "status": "disabled",
            "message": "Module IA non installé"
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }
    
# backend/src/api/v1/control_points.py

@router.get("/framework/{framework_id}/coverage", summary="Couverture des exigences par des PC")
def get_framework_coverage(
    framework_id: str,
    db: Session = Depends(get_db)
):
    """Retourne les statistiques de couverture et les exigences sans PC"""
    from sqlalchemy import text
    
    # Récupérer toutes les exigences du référentiel
    total_reqs_query = text("""
        SELECT COUNT(*) as total
        FROM requirement
        WHERE framework_id = :framework_id
    """)
    total = db.execute(total_reqs_query, {"framework_id": framework_id}).scalar()
    
    # Récupérer les exigences avec PC
    covered_reqs_query = text("""
        SELECT COUNT(DISTINCT r.id) as covered
        FROM requirement r
        INNER JOIN requirement_control_point rcp ON r.id = rcp.requirement_id
        WHERE r.framework_id = :framework_id
    """)
    covered = db.execute(covered_reqs_query, {"framework_id": framework_id}).scalar()
    
    # Récupérer les exigences SANS PC (orphelines) avec domain_id
    orphan_reqs_query = text("""
        WITH orphans AS (
            SELECT r.*
            FROM requirement r
            WHERE r.framework_id = :framework_id
              AND NOT EXISTS (
                  SELECT 1 FROM requirement_control_point rcp
                  WHERE rcp.requirement_id = r.id
              )
        )
        SELECT 
            o.id,
            o.official_code,
            o.title,
            o.requirement_text,
            o.risk_level,
            d.level                              AS domain_level,
            COALESCE(dt.title, d.code)           AS domain_label,
            COALESCE(pt.title, p.code)           AS parent_label
        FROM orphans o
        LEFT JOIN domain d        ON d.id = o.domain_id
        LEFT JOIN domain_title dt ON dt.domain_id = d.id AND dt.is_primary = true AND dt.language='fr'
        LEFT JOIN domain p        ON p.id = d.parent_id
        LEFT JOIN domain_title pt ON pt.domain_id = p.id AND pt.is_primary = true AND pt.language='fr'
        ORDER BY o.official_code NULLS LAST
    """)
    
    orphans = db.execute(orphan_reqs_query, {"framework_id": framework_id}).fetchall()
    
    # Nombre de PC générés pour ce framework
    pc_count_query = text("""
        SELECT COUNT(DISTINCT cp.id) as pc_count
        FROM control_point cp
        INNER JOIN requirement_control_point rcp ON cp.id = rcp.control_point_id
        INNER JOIN requirement r ON rcp.requirement_id = r.id
        WHERE r.framework_id = :framework_id
          AND cp.is_active = true
    """)
    pc_count = db.execute(pc_count_query, {"framework_id": framework_id}).scalar()
    
    coverage_percentage = (covered / total * 100) if total > 0 else 0
    
    # Aplatir domain/subdomain
    def flatten(level, dom_label, parent_label):
        if level is not None and level >= 1:
            return (parent_label or dom_label or "N/A", dom_label or None)
        return (dom_label or "N/A", None)
    
    return {
        "framework_id": framework_id,
        "statistics": {
            "total_requirements": total or 0,
            "covered_requirements": covered or 0,
            "orphan_requirements": len(orphans),
            "coverage_percentage": round(coverage_percentage, 2),
            "total_control_points": pc_count or 0,
            "ratio_pc_per_requirement": round((pc_count or 0) / (total or 1), 2)
        },
        "orphan_requirements": [
            {
                "id": str(row.id),
                "official_code": row.official_code,
                "title": row.title,
                "requirement_text": row.requirement_text,
                "domain": flatten(row.domain_level, row.domain_label, row.parent_label)[0],
                "subdomain": flatten(row.domain_level, row.domain_label, row.parent_label)[1] or "",
                "risk_level": row.risk_level or ""
            }
            for row in orphans
        ]
    }

@router.post("/generate-orphan-requirements/{framework_id}", summary="Générer PC pour exigences sans couverture")
async def generate_for_orphans(
    framework_id: str,
    db: Session = Depends(get_db)
):
    """
    Génère des PC uniquement pour les exigences non couvertes (compat. domain_id).
    """
    if not DeepSeekControlPointGenerator:
        raise HTTPException(503, "Service de génération non disponible")
    
    fw = db.query(Framework).filter_by(id=framework_id).first()
    if not fw:
        raise HTTPException(404, f"Référentiel {framework_id} non trouvé")
    
    from sqlalchemy import text

    # On récupère les orphelines + labels de domaine et on aplatit
    orphan_query = text("""
        WITH orphans AS (
            SELECT r.*
            FROM requirement r
            WHERE r.framework_id = :framework_id
              AND NOT EXISTS (
                  SELECT 1 FROM requirement_control_point rcp
                  WHERE rcp.requirement_id = r.id
              )
        )
        SELECT 
            o.id,
            o.official_code,
            o.title,
            o.requirement_text,
            o.risk_level,
            o.tags,
            d.level                              AS domain_level,
            COALESCE(dt.title, d.code)           AS domain_label,
            COALESCE(pt.title, p.code)           AS parent_label
        FROM orphans o
        LEFT JOIN domain d        ON d.id = o.domain_id
        LEFT JOIN domain_title dt ON dt.domain_id = d.id AND dt.is_primary = true AND dt.language='fr'
        LEFT JOIN domain p        ON p.id = d.parent_id
        LEFT JOIN domain_title pt ON pt.domain_id = p.id AND pt.is_primary = true AND pt.language='fr'
        ORDER BY o.official_code NULLS LAST, o.created_at
    """)
    
    rows = db.execute(orphan_query, {"framework_id": str(fw.id)}).fetchall()
    if not rows:
        return {"success": True, "message": "Aucune exigence orpheline à traiter", "generated_count": 0}
    
    import json, re
    def _norm_tags(v):
        if v is None: return []
        if isinstance(v, (list, tuple)): return list(v)
        s = str(v).strip()
        if not s: return []
        if s.startswith('[') and s.endswith(']'):
            try:
                p = json.loads(s)
                return p if isinstance(p, list) else [p]
            except Exception:
                return [s]
        return [x.strip() for x in re.split(r"[;,]", s) if x.strip()]

    def flatten(level, dom_label, parent_label):
        if level is not None and level >= 1:
            return (parent_label or dom_label or "N/A", dom_label or None)
        return (dom_label or "N/A", None)

    orphan_reqs = []
    for r in rows:
        dom_txt, sub_txt = flatten(r.domain_level, r.domain_label, r.parent_label)
        orphan_reqs.append({
            "id": str(r.id),
            "official_code": r.official_code,
            "title": r.title,
            "requirement_text": r.requirement_text,
            "domain": dom_txt,
            "subdomain": sub_txt,
            "risk_level": r.risk_level,
            "tags": _norm_tags(r.tags)
        })
    
    gen = DeepSeekControlPointGenerator(db)
    try:
        result = await gen.generate_control_points_from_requirements(
            framework=fw,
            requirements=orphan_reqs,
            config={"min_confidence": 0.7}
        )
        
        generated_cps = result.get("control_points", []) or []
        
        # Sauvegarde + mappings
        created_pc_ids = []
        saved_count = 0
        for cp_data in generated_cps:
            try:
                cp_id = _create_new_control_point(db, cp_data)
                _link_requirements_to_cp(db, cp_id, cp_data.get("mapped_requirements", []))
                created_pc_ids.append(cp_id)
                saved_count += 1
            except Exception as e:
                logger.error(f"Erreur sauvegarde PC orphelin : {e}")
                db.rollback()
                continue
        
        db.commit()
        
        # Embeddings
        embeddings_generated = 0
        if created_pc_ids and ControlPointEmbeddingService:
            service = ControlPointEmbeddingService(db)
            for pc_id in created_pc_ids:
                try:
                    cp = db.query(ControlPoint).filter_by(id=pc_id).first()
                    if cp:
                        service.generate_and_store_embedding(cp)
                        embeddings_generated += 1
                except Exception as e:
                    logger.warning(f"Erreur embedding : {e}")
            db.commit()
        
        return {
            "success": True,
            "message": f"{saved_count} PC générés et sauvegardés pour orphelines",
            "orphan_requirements_count": len(orphan_reqs),
            "generated_control_points": saved_count,
            "embeddings_generated": embeddings_generated
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"Erreur génération orphelins : {e}")
        raise HTTPException(500, f"Erreur : {str(e)}")

    
# backend/src/api/v1/control_points.py

@router.post("/{cp_id}/regenerate", summary="Régénérer un PC spécifique")
async def regenerate_control_point(
    cp_id: str,
    db: Session = Depends(get_db)
):
    """
    Régénère un PC existant en demandant à l'IA de l'améliorer.
    Utile pour corriger un PC mal généré.
    """
    if not DeepSeekControlPointGenerator:
        raise HTTPException(503, "Service de génération non disponible")
    
    # Récupérer le PC actuel
    cp = db.query(ControlPoint).filter_by(id=cp_id).first()
    if not cp:
        raise HTTPException(404, "PC introuvable")
    
    # Récupérer les exigences mappées
    from sqlalchemy import text
    req_query = text("""
        SELECT r.id, r.official_code, r.title, r.requirement_text, 
               r.domain, r.subdomain, r.risk_level
        FROM requirement r
        INNER JOIN requirement_control_point rcp ON r.id = rcp.requirement_id
        WHERE rcp.control_point_id = :cp_id
    """)
    
    reqs = db.execute(req_query, {"cp_id": cp_id}).fetchall()
    
    if not reqs:
        raise HTTPException(400, "Aucune exigence mappée à ce PC")
    
    requirements = [
        {
            "id": str(row.id),
            "official_code": row.official_code,
            "title": row.title,
            "requirement_text": row.requirement_text,
            "domain": row.domain,
            "subdomain": row.subdomain,
            "risk_level": row.risk_level
        }
        for row in reqs
    ]
    
    gen = DeepSeekControlPointGenerator(db)
    
    try:
        # Prompt spécial pour régénération
        result = await gen.generate_control_points_from_requirements(
            requirements=requirements,
            framework=None,
            config={
                "mode": "regenerate",
                "existing_pc": {
                    "code": cp.code,
                    "name": cp.name,
                    "description": cp.description
                },
                "instruction": "Améliore ce PC existant ou propose une meilleure version"
            }
        )
        
        generated_cps = result.get("control_points", [])
        
        return {
            "success": True,
            "original_pc": {
                "id": str(cp.id),
                "code": cp.code,
                "name": cp.name,
                "description": cp.description
            },
            "suggested_improvements": generated_cps[:3],  # Max 3 suggestions
            "mapped_requirements": requirements
        }
        
    except Exception as e:
        logger.error(f"Erreur régénération : {e}")
        raise HTTPException(500, f"Erreur : {str(e)}")


@router.post("/{cp_id}/generate-complementary", summary="Générer PC complémentaires")
async def generate_complementary_pcs(
    cp_id: str,
    db: Session = Depends(get_db)
):
    """
    Génère des PC complémentaires pour mieux couvrir les exigences
    mappées à un PC existant.
    
    Stratégie: Décompose l'exigence en plusieurs PC si elle est complexe.
    """
    if not DeepSeekControlPointGenerator:
        raise HTTPException(503, "Service de génération non disponible")
    
    # Récupérer le PC actuel
    cp = db.query(ControlPoint).filter_by(id=cp_id).first()
    if not cp:
        raise HTTPException(404, "PC introuvable")
    
    # Récupérer les exigences
    from sqlalchemy import text
    req_query = text("""
        SELECT r.id, r.official_code, r.title, r.requirement_text, 
               r.domain, r.subdomain, r.risk_level
        FROM requirement r
        INNER JOIN requirement_control_point rcp ON r.id = rcp.requirement_id
        WHERE rcp.control_point_id = :cp_id
    """)
    
    reqs = db.execute(req_query, {"cp_id": cp_id}).fetchall()
    
    if not reqs:
        raise HTTPException(400, "Aucune exigence mappée")
    
    requirements = [
        {
            "id": str(row.id),
            "official_code": row.official_code,
            "title": row.title,
            "requirement_text": row.requirement_text,
            "domain": row.domain,
            "subdomain": row.subdomain,
            "risk_level": row.risk_level
        }
        for row in reqs
    ]
    
    gen = DeepSeekControlPointGenerator(db)
    
    try:
        # Prompt spécial pour génération complémentaire
        result = await gen.generate_control_points_from_requirements(
            requirements=requirements,
            framework=None,
            config={
                "mode": "complementary",
                "existing_pc": {
                    "code": cp.code,
                    "name": cp.name,
                    "description": cp.description
                },
                "instruction": "Génère 2-5 PC complémentaires DIFFÉRENTS pour couvrir tous les aspects de ces exigences. Ne reproduis PAS le PC existant."
            }
        )
        
        generated_cps = result.get("control_points", [])
        
        # Filtrer pour exclure le PC existant (si l'IA l'a recréé)
        complementary = [
            pc for pc in generated_cps 
            if pc.get("code") != cp.code
        ][:5]  # Max 5 complémentaires
        
        return {
            "success": True,
            "existing_pc": {
                "id": str(cp.id),
                "code": cp.code,
                "name": cp.name
            },
            "complementary_control_points": complementary,
            "mapped_requirements": requirements,
            "message": f"{len(complementary)} PC complémentaires générés"
        }
        
    except Exception as e:
        logger.error(f"Erreur génération complémentaire : {e}")
        raise HTTPException(500, f"Erreur : {str(e)}")
    
# backend/src/api/v1/control_points.py

@router.put("/{cp_id}", summary="Mettre à jour un PC et générer son embedding")
async def update_control_point(
    cp_id: str,
    updates: dict,
    generate_embedding: bool = True,  # Par défaut, génère l'embedding
    db: Session = Depends(get_db)
):
    """
    Met à jour un PC existant et génère automatiquement son embedding.
    
    Args:
        cp_id: ID du point de contrôle
        updates: Dictionnaire avec les champs à mettre à jour
        generate_embedding: Si True, génère l'embedding après sauvegarde
    """
    
    # Récupérer le PC existant
    cp = db.query(ControlPoint).filter_by(id=cp_id).first()
    if not cp:
        raise HTTPException(404, "Point de contrôle introuvable")
    
    # Appliquer les mises à jour
    allowed_fields = [
        'code', 'name', 'description', 'category', 'subcategory',
        'criticality_level', 'estimated_effort_hours', 'implementation_guidance',
        'control_family', 'risk_domains', 'implementation_level'
    ]
    
    for field, value in updates.items():
        if field in allowed_fields and hasattr(cp, field):
            setattr(cp, field, value)
    
    # Mettre à jour la date de modification
    from datetime import datetime
    cp.updated_at = datetime.utcnow()
    
    try:
        db.commit()
        db.refresh(cp)
        
        logger.info(f"PC {cp.code} mis à jour avec succès")
        
        # Générer l'embedding si demandé
        embedding_generated = False
        if generate_embedding and ControlPointEmbeddingService:
            try:
                logger.info(f"Génération embedding pour PC {cp.code}")
                service = ControlPointEmbeddingService(db)
                service.generate_and_store_embedding(cp)
                db.commit()
                embedding_generated = True
                logger.info(f"Embedding généré pour PC {cp.code}")
            except Exception as e:
                logger.warning(f"Erreur génération embedding : {e}")
                # Ne pas faire échouer la sauvegarde si l'embedding échoue
        
        return {
            "success": True,
            "message": "Point de contrôle mis à jour",
            "control_point": {
                "id": str(cp.id),
                "code": cp.code,
                "name": cp.name,
                "description": cp.description,
                "category": cp.category,
                "subcategory": cp.subcategory,
                "criticality_level": cp.criticality_level,
                "estimated_effort_hours": cp.estimated_effort_hours,
                "updated_at": cp.updated_at.isoformat() if cp.updated_at else None
            },
            "embedding_generated": embedding_generated
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"Erreur mise à jour PC : {e}")
        raise HTTPException(500, f"Erreur lors de la mise à jour : {str(e)}")


@router.post("/{cp_id}/apply-suggestion", summary="Appliquer une suggestion et générer embedding")
async def apply_suggestion(
    cp_id: str,
    suggestion: dict,
    db: Session = Depends(get_db)
):
    """
    Applique une suggestion d'amélioration générée par l'IA et génère l'embedding.
    """
    
    cp = db.query(ControlPoint).filter_by(id=cp_id).first()
    if not cp:
        raise HTTPException(404, "Point de contrôle introuvable")
    
    # Appliquer la suggestion
    cp.name = suggestion.get('name', cp.name)
    cp.description = suggestion.get('description', cp.description)
    cp.implementation_guidance = suggestion.get('implementation_guidance', cp.implementation_guidance)
    
    # Mettre à jour les champs optionnels si présents
    if 'category' in suggestion:
        cp.category = suggestion['category']
    if 'subcategory' in suggestion:
        cp.subcategory = suggestion['subcategory']
    if 'criticality' in suggestion:
        # Normaliser la criticité
        crit_map = {"CRITICAL": "critical", "HIGH": "high", "MEDIUM": "medium", "LOW": "low"}
        cp.criticality_level = crit_map.get(suggestion['criticality'].upper(), "medium")
    
    from datetime import datetime
    cp.updated_at = datetime.utcnow()
    
    try:
        db.commit()
        db.refresh(cp)
        
        # Générer l'embedding automatiquement
        embedding_generated = False
        if ControlPointEmbeddingService:
            try:
                service = ControlPointEmbeddingService(db)
                service.generate_and_store_embedding(cp)
                db.commit()
                embedding_generated = True
                logger.info(f"Embedding généré après application suggestion pour PC {cp.code}")
            except Exception as e:
                logger.warning(f"Erreur génération embedding : {e}")
        
        return {
            "success": True,
            "message": "Suggestion appliquée avec succès",
            "control_point": {
                "id": str(cp.id),
                "code": cp.code,
                "name": cp.name,
                "description": cp.description
            },
            "embedding_generated": embedding_generated
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"Erreur application suggestion : {e}")
        raise HTTPException(500, f"Erreur : {str(e)}")


@router.post("/{cp_id}/save-complementary", summary="Sauvegarder un PC complémentaire avec embedding")
async def save_complementary_pc(
    cp_id: str,  # PC parent pour référence
    complementary_data: dict,
    db: Session = Depends(get_db)
):
    """
    Sauvegarde un PC complémentaire généré et crée son embedding.
    """
    
    # Vérifier que le PC parent existe
    parent_cp = db.query(ControlPoint).filter_by(id=cp_id).first()
    if not parent_cp:
        raise HTTPException(404, "PC parent introuvable")
    
    # Récupérer les exigences mappées au PC parent
    from sqlalchemy import text
    req_query = text("""
        SELECT requirement_id 
        FROM requirement_control_point 
        WHERE control_point_id = :parent_id
    """)
    parent_reqs = db.execute(req_query, {"parent_id": cp_id}).fetchall()
    parent_req_ids = [str(row.requirement_id) for row in parent_reqs]
    
    # Normaliser les données
    crit_map = {"CRITICAL": "critical", "HIGH": "high", "MEDIUM": "medium", "LOW": "low"}
    criticality = complementary_data.get('criticality', 'MEDIUM').upper()
    
    # Créer le nouveau PC
    new_pc = ControlPoint(
        id=str(uuid4()),
        code=complementary_data.get('code'),
        name=complementary_data.get('name'),
        description=complementary_data.get('description'),
        category=complementary_data.get('category', parent_cp.category),
        subcategory=complementary_data.get('subcategory', parent_cp.subcategory),
        criticality_level=crit_map.get(criticality, 'medium'),
        estimated_effort_hours=complementary_data.get('estimated_effort_hours', 4),
        implementation_guidance=complementary_data.get('implementation_guidance', ''),
        control_family=complementary_data.get('control_family', parent_cp.control_family),
        created_by='ai_complementary',
        ai_confidence=complementary_data.get('ai_confidence', 0.8),
        is_active=True
    )
    
    db.add(new_pc)
    db.flush()
    
    # Mapper aux mêmes exigences que le PC parent
    from ...models.audit import RequirementControlPoint
    for req_id in parent_req_ids:
        mapping = RequirementControlPoint(
            id=str(uuid4()),
            requirement_id=req_id,
            control_point_id=str(new_pc.id)
        )
        db.add(mapping)
    
    try:
        db.commit()
        db.refresh(new_pc)
        
        logger.info(f"PC complémentaire {new_pc.code} créé")
        
        # Générer l'embedding automatiquement
        embedding_generated = False
        if ControlPointEmbeddingService:
            try:
                service = ControlPointEmbeddingService(db)
                service.generate_and_store_embedding(new_pc)
                db.commit()
                embedding_generated = True
                logger.info(f"Embedding généré pour PC complémentaire {new_pc.code}")
            except Exception as e:
                logger.warning(f"Erreur génération embedding : {e}")
        
        return {
            "success": True,
            "message": f"PC complémentaire {new_pc.code} créé avec succès",
            "control_point": {
                "id": str(new_pc.id),
                "code": new_pc.code,
                "name": new_pc.name,
                "description": new_pc.description
            },
            "mapped_requirements_count": len(parent_req_ids),
            "embedding_generated": embedding_generated
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"Erreur création PC complémentaire : {e}")
        raise HTTPException(500, f"Erreur : {str(e)}")



class ControlPointGenerationRequest(BaseModel):
    """Modèle pour la génération/liaison de PC"""
    manual_data: Optional[Dict[str, Any]] = None
    use_ai: bool = True
    framework_id: Optional[str] = None


@router.post(
    "/generate-or-link-for-requirement/{requirement_id}",
    response_model=Dict[str, Any],
    summary="Générer ou lier un PC pour une exigence"
)
async def generate_or_link_for_requirement(
    requirement_id: str,
    data: ControlPointGenerationRequest = Body(...),
    allow_multiple_pcs: bool = Query(False, description="Permet de créer plusieurs PC pour une même exigence"),
    db: Session = Depends(get_db),
):
    """
    Génère un PC pour une exigence (manuelle ou IA).
    
    Args:
        requirement_id: ID de l'exigence
        data: Données du PC (manual_data) ou config génération IA
        allow_multiple_pcs: Si True, permet de créer plusieurs PC pour une même exigence
    
    Returns:
        {
            "success": True,
            "action": "created" | "already_linked",
            "control_point": {...},
            "embedding_generated": True
        }
    """
    from sqlalchemy import text
    
    try:
        logger.info(f"🎯 Génération PC pour exigence: {requirement_id} (allow_multiple_pcs={allow_multiple_pcs})")
        
        # ✅ 1. Récupérer l'exigence avec domain/subdomain
        req_query = text("""
            SELECT 
                r.id,
                r.official_code,
                r.title,
                r.requirement_text,
                r.risk_level,
                r.framework_id,
                d.level AS domain_level,
                d.code AS domain_code,
                COALESCE(dt.title, d.code) AS domain_title,
                p.code AS parent_code,
                COALESCE(pt.title, p.code) AS parent_title
            FROM requirement r
            LEFT JOIN domain d ON r.domain_id = d.id
            LEFT JOIN domain_title dt ON dt.domain_id = d.id 
                AND dt.is_primary = true 
                AND dt.language = 'fr'
            LEFT JOIN domain p ON p.id = d.parent_id
            LEFT JOIN domain_title pt ON pt.domain_id = p.id 
                AND pt.is_primary = true 
                AND pt.language = 'fr'
            WHERE r.id = :req_id
        """)
        
        req_row = db.execute(req_query, {"req_id": requirement_id}).fetchone()
        if not req_row:
            raise HTTPException(status_code=404, detail="Exigence introuvable")

        # Déterminer domain/subdomain
        if req_row.domain_level == 0:
            domain_name = req_row.domain_title or req_row.domain_code or "Non catégorisé"
            subdomain_name = None
        elif req_row.domain_level == 1:
            domain_name = req_row.parent_title or req_row.parent_code or "Non catégorisé"
            subdomain_name = req_row.domain_title or req_row.domain_code
        else:
            domain_name = req_row.domain_title or "Non catégorisé"
            subdomain_name = None

        # ✅ 2. Récupérer le framework
        framework = db.query(Framework).filter(Framework.id == req_row.framework_id).first()
        if not framework:
            raise HTTPException(status_code=404, detail="Référentiel introuvable")

        # ✅ 3. Vérifier si déjà lié (UNIQUEMENT si allow_multiple_pcs=False)
        if not allow_multiple_pcs:
            check_link_query = text("""
                SELECT cp.id, cp.code, cp.name
                FROM control_point cp
                INNER JOIN requirement_control_point rcp ON cp.id = rcp.control_point_id
                WHERE rcp.requirement_id = :req_id
                LIMIT 1
            """)
            
            existing_link = db.execute(check_link_query, {"req_id": requirement_id}).fetchone()

            if existing_link:
                logger.info(f"⚠️ Exigence déjà liée au PC {existing_link.code}")
                return {
                    "success": True,
                    "action": "already_linked",
                    "control_point": {
                        "id": str(existing_link.id),
                        "code": existing_link.code,
                        "name": existing_link.name,
                    },
                    "message": f"Exigence déjà liée au PC {existing_link.code}"
                }

        # ✅ 4. CRÉATION DU PC (Manuelle ou IA)
        
        # CAS A : Données manuelles fournies
        if data.manual_data:
            logger.info("📝 Création PC avec données manuelles")
            manual_data = data.manual_data
            
            # Normaliser la criticité
            criticality_map = {
                "CRITICAL": "critical",
                "HIGH": "high",
                "MEDIUM": "medium",
                "LOW": "low"
            }
            
            # ✅ GÉNÉRATION CODE SI NON FOURNI (INLINE)
            if not manual_data.get("code"):
                from sqlalchemy import text
                
                # Compter les PC de cette catégorie
                category = manual_data.get("category") or domain_name or "GEN"
                count_query = text("""
                    SELECT COUNT(*) AS count
                    FROM control_point
                    WHERE category = :category
                """)
                
                count_result = db.execute(count_query, {"category": category}).scalar()
                counter = (count_result or 0) + 1
                
                # Construire le code (format: CP-XXX-NNN)
                prefix = category[:3].upper().replace(" ", "")
                manual_data["code"] = f"CP-{prefix}-{counter:03d}"
                
                logger.info(f"🔢 Code auto-généré: {manual_data['code']}")
            
            # ✅ CONVERSION risk_domains (STRING → JSON)
            risk_domains_raw = manual_data.get("risk_domains", "")
            
            if isinstance(risk_domains_raw, str):
                risk_domains_list = [
                    domain.strip() 
                    for domain in risk_domains_raw.split(",") 
                    if domain.strip()
                ]
            elif isinstance(risk_domains_raw, list):
                risk_domains_list = risk_domains_raw
            else:
                risk_domains_list = []
            
            import json
            risk_domains_json = json.dumps(risk_domains_list) if risk_domains_list else "[]"
            
            logger.info(f"📊 risk_domains: {risk_domains_json}")
            
            # ✅ CRÉATION PC AVEC JSONB VALIDE
            new_cp = ControlPoint(
                id=str(uuid4()),
                code=manual_data.get("code"),
                name=manual_data.get("name"),
                description=manual_data.get("description"),
                category=manual_data.get("category") or domain_name,
                subcategory=manual_data.get("subcategory") or subdomain_name or "",
                control_family=manual_data.get("control_family"),
                criticality_level=criticality_map.get(
                    (manual_data.get("criticality_level") or "MEDIUM").upper(),
                    "medium"
                ),
                implementation_level=manual_data.get("implementation_level", "level_1"),
                estimated_effort_hours=manual_data.get("estimated_effort_hours", 4),
                implementation_guidance=manual_data.get("implementation_guidance", ""),
                risk_domains=risk_domains_json,  # ✅ JSON valide
                created_by="manual",
                ai_confidence=None,
                is_active=True
            )
            
            db.add(new_cp)
            db.flush()
            
            logger.info(f"✅ PC manuel créé: {new_cp.code}")
        
        # CAS B : Génération IA
        elif data.use_ai:
            logger.info("🤖 Génération PC avec IA")
            
            if not DeepSeekControlPointGenerator:
                raise HTTPException(status_code=503, detail="Service de génération IA non disponible")

            requirement = {
                "id": str(req_row.id),
                "official_code": req_row.official_code,
                "title": req_row.title,
                "requirement_text": req_row.requirement_text,
                "domain": domain_name,
                "subdomain": subdomain_name or "",
                "risk_level": req_row.risk_level,
                "framework_id": str(req_row.framework_id),
            }

            generator = DeepSeekControlPointGenerator()

            result = await generator.generate_from_framework(
                framework={
                    "id": str(framework.id),
                    "code": framework.code,
                    "name": framework.name,
                    "locale": "fr"
                },
                requirements=[requirement]
            )

            if not result.get("control_points"):
                raise HTTPException(status_code=500, detail="Aucun PC généré par l'IA")

            pc_data = result["control_points"][0]

            # Normaliser la criticité
            criticality_map = {
                "CRITICAL": "critical",
                "HIGH": "high",
                "MEDIUM": "medium",
                "LOW": "low"
            }

            new_cp = ControlPoint(
                id=str(uuid4()),
                code=pc_data.get("cp_ref") or pc_data.get("code"),
                name=pc_data.get("title"),
                description=pc_data.get("description"),
                category=domain_name,
                subcategory=subdomain_name or "",
                criticality_level=criticality_map.get(
                    (pc_data.get("criticality") or "MEDIUM").upper(),
                    "medium"
                ),
                estimated_effort_hours=pc_data.get("estimated_effort_hours", 4),
                implementation_guidance=pc_data.get("implementation_guidance", ""),
                created_by="ai_orphan_handler",
                ai_confidence=pc_data.get("ai_confidence", 0.8),
                is_active=True
            )
            
            db.add(new_cp)
            db.flush()
            
            logger.info(f"✅ PC IA créé: {new_cp.code}")
        
        else:
            raise HTTPException(status_code=400, detail="Aucune donnée fournie (manual_data ou use_ai)")

        # ✅ 5. Lier l'exigence au PC
        link_query = text("""
            INSERT INTO requirement_control_point (requirement_id, control_point_id, mapping_method)
            VALUES (:req_id, :cp_id, :method)
            ON CONFLICT DO NOTHING
        """)
        
        mapping_method = "manual" if data.manual_data else "ai_generation"
        
        db.execute(link_query, {
            "req_id": requirement_id,
            "cp_id": str(new_cp.id),
            "method": mapping_method
        })
        
        db.commit()
        db.refresh(new_cp)

        # ✅ 6. Générer l'embedding (best effort)
        embedding_generated = False
        if ControlPointEmbeddingService:
            try:
                service = ControlPointEmbeddingService(db)
                service.generate_and_store_embedding(new_cp)
                db.commit()
                embedding_generated = True
                logger.info(f"✅ Embedding généré pour PC {new_cp.code}")
            except Exception as e:
                logger.warning(f"⚠️ Erreur embedding : {e}")

        logger.info(f"✅ PC {new_cp.code} créé pour exigence {req_row.official_code}")

        return {
            "success": True,
            "action": "created",
            "control_point": {
                "id": str(new_cp.id),
                "code": new_cp.code,
                "name": new_cp.name,
                "description": new_cp.description,
                "criticality_level": new_cp.criticality_level,
                "estimated_effort_hours": new_cp.estimated_effort_hours,
            },
            "embedding_generated": embedding_generated,
            "message": f"Nouveau PC {new_cp.code} créé et lié à l'exigence"
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur génération PC : {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    
    
def map_risk_to_criticality(risk_level: Optional[str]) -> str:
    """Convertir le niveau de risque en criticité"""
    if not risk_level:
        return "medium"
    
    risk_upper = risk_level.upper()
    if risk_upper in ["CRITICAL", "HIGH"]:
        return "high"
    elif risk_upper == "MEDIUM":
        return "medium"
    else:
        return "low"

@router.get("/framework/{framework_id}/orphan-requirements", summary="Exigences sans PC")
async def get_orphan_requirements(
    framework_id: str,
    db: Session = Depends(get_db)
):
    """
    Exigences du framework sans PC associé.
    Compatible domain_id : construit domain/subdomain lisibles via domain/domain_title
    """
    from sqlalchemy import text

    query = text("""
        WITH orphans AS (
            SELECT r.*
            FROM requirement r
            WHERE r.framework_id = :framework_id
              AND r.is_active = true
              AND NOT EXISTS (
                  SELECT 1 FROM requirement_control_point rcp
                  WHERE rcp.requirement_id = r.id
              )
        )
        SELECT 
            o.id,
            o.official_code,
            o.title,
            o.requirement_text,
            o.risk_level,
            o.compliance_obligation,
            o.tags,
            d.level                              AS domain_level,
            COALESCE(dt.title, d.code)           AS domain_label,
            COALESCE(pt.title, p.code)           AS parent_label
        FROM orphans o
        LEFT JOIN domain d        ON d.id = o.domain_id
        LEFT JOIN domain_title dt ON dt.domain_id = d.id AND dt.is_primary = true AND dt.language='fr'
        LEFT JOIN domain p        ON p.id = d.parent_id
        LEFT JOIN domain_title pt ON pt.domain_id = p.id AND pt.is_primary = true AND pt.language='fr'
        ORDER BY o.official_code NULLS LAST, o.created_at
    """)

    rows = db.execute(query, {"framework_id": framework_id}).fetchall()

    def flatten(level, dom_label, parent_label):
        if level is not None and level >= 1:
            return (parent_label or dom_label or "N/A", dom_label or None)
        return (dom_label or "N/A", None)

    items = []
    for r in rows:
        domain_txt, subdomain_txt = flatten(r.domain_level, r.domain_label, r.parent_label)
        items.append({
            "id": str(r.id),
            "official_code": r.official_code,
            "title": r.title,
            "requirement_text": r.requirement_text,
            "domain": domain_txt,
            "subdomain": subdomain_txt,
            "risk_level": r.risk_level,
            "compliance_obligation": r.compliance_obligation,
            "tags": r.tags or []
        })

    return {
        "framework_id": framework_id,
        "orphan_count": len(items),
        "orphan_requirements": items
    }


@router.get("/dashboard", summary="Tableau de bord des référentiels avec KPI")
def frameworks_dashboard(db: Session = Depends(get_db)):
    from sqlalchemy import text

    query = text("""
        SELECT 
            f.id, f.code, f.name, f.version, f.is_active,
            COUNT(DISTINCT r.id) as total_requirements,
            COUNT(DISTINCT rcp.requirement_id) as covered_requirements,
            COUNT(DISTINCT cp.id) as total_control_points
        FROM framework f
        LEFT JOIN requirement r ON r.framework_id = f.id
        LEFT JOIN requirement_control_point rcp ON r.id = rcp.requirement_id
        LEFT JOIN control_point cp ON cp.id = rcp.control_point_id
        WHERE f.is_active = true
        GROUP BY f.id
        ORDER BY f.name
    """)

    rows = db.execute(query).fetchall()

    results = []
    for row in rows:
        total = row.total_requirements or 0
        covered = row.covered_requirements or 0
        uncovered = total - covered
        pc_count = row.total_control_points or 0
        coverage = (covered / total * 100) if total > 0 else 0

        results.append({
            "id": str(row.id),
            "code": row.code,
            "name": row.name,
            "version": row.version,
            "is_active": row.is_active,
            "total_requirements": total,
            "covered_requirements": covered,
            "uncovered_requirements": uncovered,
            "total_control_points": pc_count,
            "coverage_percentage": round(coverage, 2),
        })

    return {"frameworks": results, "total": len(results)}

# LIGNE 2430-2500 : AJOUTER APRÈS l'endpoint DELETE /framework/{framework_id}/control-points

@router.delete(
    "/{control_point_id}",
    response_model=Dict[str, Any],
    summary="Supprimer un point de contrôle spécifique"
)
async def delete_control_point(
    control_point_id: str,
    db: Session = Depends(get_db),
):
    """
    Supprime un point de contrôle et toutes ses liaisons avec les exigences.
    
    Cascade automatique (définie dans le modèle SQLAlchemy):
    - requirement_control_point → ON DELETE CASCADE
    - control_point_embeddings → ON DELETE CASCADE
    
    Args:
        control_point_id: ID du point de contrôle à supprimer
    
    Returns:
        {
            "success": True,
            "control_point_code": "CP-AC001",
            "deleted_mappings": 3,
            "deleted_embeddings": 1
        }
    """
    from sqlalchemy import text as sql_text
    
    try:
        logger.info(f"🗑️ Suppression du PC: {control_point_id}")
        
        # ✅ 1. Vérifier l'existence du PC
        cp_check_query = sql_text("""
            SELECT id, code, name
            FROM control_point
            WHERE id = :cp_id
        """)
        
        cp_data = db.execute(cp_check_query, {"cp_id": control_point_id}).fetchone()
        
        if not cp_data:
            raise HTTPException(status_code=404, detail="Point de contrôle introuvable")
        
        cp_code = cp_data.code
        cp_name = cp_data.name
        
        # ✅ 2. Compter les liaisons avec les exigences
        count_mappings_query = sql_text("""
            SELECT COUNT(*) AS count
            FROM requirement_control_point
            WHERE control_point_id = :cp_id
        """)
        
        mappings_count = db.execute(count_mappings_query, {"cp_id": control_point_id}).scalar() or 0
        
        # ✅ 3. Compter les embeddings
        count_embeddings_query = sql_text("""
            SELECT COUNT(*) AS count
            FROM control_point_embeddings
            WHERE control_point_id = :cp_id
        """)
        
        embeddings_count = db.execute(count_embeddings_query, {"cp_id": control_point_id}).scalar() or 0
        
        # ✅ 4. Supprimer les liaisons avec les exigences (requirement_control_point)
        delete_mappings_query = sql_text("""
            DELETE FROM requirement_control_point
            WHERE control_point_id = :cp_id
        """)
        
        db.execute(delete_mappings_query, {"cp_id": control_point_id})
        
        logger.info(f"✅ {mappings_count} liaison(s) supprimée(s)")
        
        # ✅ 5. Supprimer les embeddings
        delete_embeddings_query = sql_text("""
            DELETE FROM control_point_embeddings
            WHERE control_point_id = :cp_id
        """)
        
        db.execute(delete_embeddings_query, {"cp_id": control_point_id})
        
        logger.info(f"✅ {embeddings_count} embedding(s) supprimé(s)")
        
        # ✅ 6. Supprimer le point de contrôle
        delete_cp_query = sql_text("""
            DELETE FROM control_point
            WHERE id = :cp_id
        """)
        
        db.execute(delete_cp_query, {"cp_id": control_point_id})
        
        db.commit()
        
        logger.info(f"✅ PC {cp_code} supprimé avec succès")
        
        return {
            "success": True,
            "control_point_id": control_point_id,
            "control_point_code": cp_code,
            "control_point_name": cp_name,
            "deleted_mappings": int(mappings_count),
            "deleted_embeddings": int(embeddings_count),
            "message": f"Point de contrôle {cp_code} supprimé avec succès"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur suppression PC {control_point_id}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la suppression: {str(e)}"
        )
    
@router.delete("/framework/{framework_id}/control-points", summary="Supprimer tous les PCs d'un référentiel (sans supprimer le référentiel)")
def delete_framework_control_points(
    framework_id: str,
    db: Session = Depends(get_db)
):
    """
    Supprime tous les Points de Contrôle rattachés au référentiel via ses exigences.
    - On calcule d'abord l'ensemble des control_point.id concernés.
    - On supprime ensuite ces control_points (ON DELETE CASCADE supprime mappings + embeddings).
    - Le framework, ses exigences et leurs embeddings NE SONT PAS supprimés.

    Effets de cascade confirmés par le schéma:
      requirement_control_point.control_point_id -> control_point(id) ON DELETE CASCADE
      control_point_embeddings.control_point_id  -> control_point(id) ON DELETE CASCADE
    """
    from sqlalchemy import text as sql_text

    try:
        # 1) Récupérer la liste des PC à supprimer (distincts)
        to_delete_sql = sql_text("""
            WITH cp_ids AS (
                SELECT DISTINCT cp.id AS control_point_id
                FROM control_point cp
                JOIN requirement_control_point rcp
                  ON rcp.control_point_id = cp.id
                JOIN requirement r
                  ON r.id = rcp.requirement_id
                WHERE r.framework_id = :framework_id
            )
            SELECT control_point_id FROM cp_ids
        """)
        cp_rows = db.execute(to_delete_sql, {"framework_id": framework_id}).fetchall()
        cp_ids = [str(row[0]) for row in cp_rows]

        if not cp_ids:
            return {
                "status": "ok",
                "framework_id": framework_id,
                "deleted_control_points": 0,
                "deleted_mappings": 0,
                "deleted_embeddings": 0,
                "message": "Aucun point de contrôle à supprimer pour ce référentiel."
            }

        # 2) Compter les mappings et embeddings qui vont disparaître (info)
        count_map_sql = sql_text("""
            SELECT COUNT(*) AS c
            FROM requirement_control_point
            WHERE control_point_id::text = ANY(:ids)
        """)
        count_emb_sql = sql_text("""
            SELECT COUNT(*) AS c
            FROM control_point_embeddings
            WHERE control_point_id::text = ANY(:ids)
        """)
        maps_before = db.execute(count_map_sql, {"ids": cp_ids}).scalar() or 0
        emb_before  = db.execute(count_emb_sql, {"ids": cp_ids}).scalar() or 0

        # 3) Désactiver temporairement les triggers pour éviter les erreurs
        db.execute(sql_text("ALTER TABLE question DISABLE TRIGGER ALL"))
        db.execute(sql_text("ALTER TABLE question_control_point DISABLE TRIGGER ALL"))
        db.execute(sql_text("ALTER TABLE requirement_control_point DISABLE TRIGGER ALL"))

        try:
            # 4) Supprimer d'abord les liens avec les questions (si existants)
            delete_question_links_sql = sql_text("""
                DELETE FROM question_control_point
                WHERE control_point_id::text = ANY(:ids)
            """)
            db.execute(delete_question_links_sql, {"ids": cp_ids})

            # 5) Supprimer les control_points (ON DELETE CASCADE pour requirement_control_point et embeddings)
            delete_sql = sql_text("""
                DELETE FROM control_point cp
                WHERE cp.id::text = ANY(:ids)
            """)
            res = db.execute(delete_sql, {"ids": cp_ids})
            deleted_cp = res.rowcount or 0

            # 6) Réactiver les triggers AVANT le commit
            db.execute(sql_text("ALTER TABLE question ENABLE TRIGGER ALL"))
            db.execute(sql_text("ALTER TABLE question_control_point ENABLE TRIGGER ALL"))
            db.execute(sql_text("ALTER TABLE requirement_control_point ENABLE TRIGGER ALL"))

            # 7) Commit une seule fois
            db.commit()

            return {
                "status": "ok",
                "framework_id": framework_id,
                "deleted_control_points": int(deleted_cp),
                "deleted_mappings": int(maps_before),     # supprimés par cascade
                "deleted_embeddings": int(emb_before),    # supprimés par cascade
                "message": "Tous les Points de Contrôle de ce référentiel ont été supprimés (référentiel conservé)."
            }

        except Exception as delete_error:
            # En cas d'erreur, réactiver les triggers avant de propager l'erreur
            try:
                db.execute(sql_text("ALTER TABLE question ENABLE TRIGGER ALL"))
                db.execute(sql_text("ALTER TABLE question_control_point ENABLE TRIGGER ALL"))
                db.execute(sql_text("ALTER TABLE requirement_control_point ENABLE TRIGGER ALL"))
            except Exception as trigger_error:
                logger.error(f"Erreur lors de la réactivation des triggers: {trigger_error}")
            raise delete_error

    except Exception as e:
        db.rollback()
        logger.error(f"Erreur suppression PCs du référentiel {framework_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erreur suppression PCs du référentiel: {str(e)}")

# ============================================================================
# FRAMEWORKS AYANT DES POINTS DE CONTRÔLE
# ============================================================================

@router.get("/frameworks-with-pc", summary="Référentiels ayant des Points de Contrôle")
def list_frameworks_with_pc(
    db: Session = Depends(get_db),
    limit: int = 50,
    offset: int = 0,
):
    """
    Retourne les frameworks qui ont AU MOINS 1 Point de Contrôle (via requirement_control_point).
    ⚠️ Utilisé par la vue Points de Contrôle (pas la génération IA).
    """
    from sqlalchemy import text as sql_text

    q = sql_text("""
        SELECT
            f.id::text                       AS framework_id,
            f.code,
            f.name,
            f.version,
            f.is_active,
            f.import_date,
            COALESCE(COUNT(DISTINCT r.id), 0)  AS total_requirements,
            COALESCE(COUNT(DISTINCT rcp.requirement_id), 0) AS covered_requirements,
            COALESCE(COUNT(DISTINCT cp.id), 0) AS total_control_points,
            BOOL_OR(cp.created_by ILIKE '%ai%' OR cp.created_by ILIKE '%gpt%') AS ai_generated
        FROM framework f
        LEFT JOIN requirement r
               ON r.framework_id = f.id
        LEFT JOIN requirement_control_point rcp
               ON rcp.requirement_id = r.id
        LEFT JOIN control_point cp
               ON cp.id = rcp.control_point_id
        GROUP BY f.id, f.code, f.name, f.version, f.is_active, f.import_date
        HAVING COUNT(DISTINCT cp.id) > 0
        ORDER BY f.created_at DESC NULLS LAST
        LIMIT :limit OFFSET :offset
    """)

    rows = db.execute(q, {"limit": limit, "offset": offset}).mappings().all()

    items = []
    for r in rows:
        total = int(r["total_requirements"] or 0)
        covered = int(r["covered_requirements"] or 0)
        pc_count = int(r["total_control_points"] or 0)
        coverage = round((covered / total * 100), 2) if total > 0 else 0.0

        items.append({
            "id": r["framework_id"],
            "code": r.get("code"),
            "name": r.get("name"),
            "version": r.get("version"),
            "is_active": r.get("is_active", True),
            "import_date": r.get("import_date"),
            "ai_generated": r.get("ai_generated", False),
            "requirements_count": total,
            "control_points_count": pc_count,
            "coverage_percentage": coverage
        })

    return {
        "frameworks": items,
        "total": len(items),
        "limit": limit,
        "offset": offset
    }

@router.get("/", summary="Lister les points de contrôle")
@cache_result(ttl=900, key_prefix="control_points_list")  # ✅ Cache 15min
def list_control_points(
    db: Session = Depends(get_db),
    limit: int = 50,
    offset: int = 0,
    framework_id: Optional[str] = None
):
    """Liste paginée des points de contrôle avec exigences mappées"""
    from sqlalchemy import text
    
    if framework_id:
        # Récupérer les PC liés à ce framework via les exigences
        cp_ids_query = text("""
            SELECT DISTINCT rcp.control_point_id
            FROM requirement_control_point rcp
            INNER JOIN requirement r ON r.id = rcp.requirement_id
            WHERE r.framework_id = :framework_id
        """)
        
        result = db.execute(cp_ids_query, {"framework_id": framework_id}).fetchall()
        cp_ids = [str(row[0]) for row in result]
        
        if not cp_ids:
            return {
                "control_points": [],
                "total": 0,
                "limit": limit,
                "offset": offset
            }
        
        items = db.query(ControlPoint).filter(
            ControlPoint.id.in_(cp_ids),
            ControlPoint.is_active == True
        ).order_by(ControlPoint.created_at.desc()).offset(offset).limit(limit).all()
    else:
        items = db.query(ControlPoint).filter(
            ControlPoint.is_active == True
        ).order_by(ControlPoint.created_at.desc()).offset(offset).limit(limit).all()
    
    # Enrichir avec exigences mappées
    result_pcs = []
    for cp in items:
        req_query = text("""
            SELECT r.id, r.official_code, r.title, r.requirement_text, 
                   d.level AS domain_level,
                   COALESCE(dt.title, d.code) AS domain_label,
                   COALESCE(pt.title, p.code) AS parent_label,
                   r.risk_level
            FROM requirement r
            INNER JOIN requirement_control_point rcp ON r.id = rcp.requirement_id
            LEFT JOIN domain d ON r.domain_id = d.id
            LEFT JOIN domain_title dt ON dt.domain_id = d.id AND dt.is_primary = true AND dt.language='fr'
            LEFT JOIN domain p ON p.id = d.parent_id
            LEFT JOIN domain_title pt ON pt.domain_id = p.id AND pt.is_primary = true AND pt.language='fr'
            WHERE rcp.control_point_id = :cp_id
            ORDER BY r.official_code
        """)
        
        reqs = db.execute(req_query, {"cp_id": str(cp.id)}).fetchall()
        
        def flatten(level, dom_label, parent_label):
            if level is not None and level >= 1:
                return (parent_label or dom_label or "N/A", dom_label or None)
            return (dom_label or "N/A", None)
        
        result_pcs.append({
            "id": str(cp.id),
            "code": cp.code,
            "name": getattr(cp, "name", None),
            "description": cp.description,
            "category": cp.category,
            "subcategory": cp.subcategory,
            "criticality_level": getattr(cp, "criticality_level", "medium"),
            "estimated_effort_hours": getattr(cp, "estimated_effort_hours", 0),
            "ai_confidence": float(getattr(cp, "ai_confidence", 0.0)) if getattr(cp, "ai_confidence", None) else None,
            "is_active": getattr(cp, "is_active", True),
            "created_at": str(getattr(cp, "created_at", "")),
            "status": "approved",
            "mapped_requirements_details": [
                {
                    "id": str(req.id),
                    "official_code": req.official_code or "",
                    "title": req.title or "",
                    "requirement_text": req.requirement_text or "",
                    "domain": flatten(req.domain_level, req.domain_label, req.parent_label)[0],
                    "subdomain": flatten(req.domain_level, req.domain_label, req.parent_label)[1] or "",
                    "risk_level": req.risk_level or ""
                }
                for req in reqs
            ]
        })

    return {
        "control_points": result_pcs,
        "total": len(result_pcs),
        "limit": limit,
        "offset": offset
    }

@router.get("/frameworks-with-pc-embeddings")
async def frameworks_with_pc_embeddings(
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """
    Liste uniquement les référentiels qui ont :
      - des exigences,
      - des points de contrôle liés à ces exigences,
      - et au moins un embedding pour ces PC.
    Implémentation optimisée avec EXISTS (rapide).
    """
    from sqlalchemy import text

    sql = text("""
        SELECT
            f.id, f.code, f.name, f.version, f.publisher, f.language, f.import_date,

            /* Compteurs calculés par sous-requêtes pour éviter les gros GROUP BY */
            (
              SELECT COUNT(1)
              FROM requirement r
              WHERE r.framework_id = f.id
            ) AS requirements_count,

            (
              SELECT COUNT(DISTINCT rcp.control_point_id)
              FROM requirement r
              JOIN requirement_control_point rcp ON rcp.requirement_id = r.id
              JOIN control_point cp ON cp.id = rcp.control_point_id AND cp.is_active = TRUE
              WHERE r.framework_id = f.id
            ) AS control_points_count,

            (
              SELECT COUNT(DISTINCT cpe.control_point_id)
              FROM requirement r
              JOIN requirement_control_point rcp ON rcp.requirement_id = r.id
              JOIN control_point_embeddings cpe ON cpe.control_point_id = rcp.control_point_id
              WHERE r.framework_id = f.id
            ) AS pc_with_embeddings

        FROM framework f
        WHERE f.is_active = TRUE

          /* Filtres rapides avec EXISTS pour ne garder que les frameworks pertinents */
          AND EXISTS (SELECT 1 FROM requirement r WHERE r.framework_id = f.id)
          AND EXISTS (
               SELECT 1
               FROM requirement r
               JOIN requirement_control_point rcp ON rcp.requirement_id = r.id
               JOIN control_point cp ON cp.id = rcp.control_point_id AND cp.is_active = TRUE
               WHERE r.framework_id = f.id
          )
          AND EXISTS (
               SELECT 1
               FROM requirement r
               JOIN requirement_control_point rcp ON rcp.requirement_id = r.id
               JOIN control_point_embeddings cpe ON cpe.control_point_id = rcp.control_point_id
               WHERE r.framework_id = f.id
          )

        ORDER BY f.import_date DESC NULLS LAST, f.name ASC
        LIMIT :limit OFFSET :offset
    """)

    rows = db.execute(sql, {"limit": limit, "offset": offset}).mappings().all()

    frameworks = []
    for r in rows:
        frameworks.append({
            "id": str(r["id"]),
            "code": r["code"],
            "name": r["name"],
            "version": r["version"],
            "publisher": r["publisher"],
            "language": r["language"],
            "import_date": r["import_date"].isoformat() if r["import_date"] else None,
            "requirements_count": int(r["requirements_count"] or 0),
            "control_points_count": int(r["control_points_count"] or 0),
            "pc_with_embeddings": int(r["pc_with_embeddings"] or 0),
        })

    return {"frameworks": frameworks, "total": len(frameworks)}

# ================================================================
# 🔹 GÉNÉRATION D’EMBEDDING POUR UN POINT DE CONTRÔLE
# ================================================================

@router.post("/search-similar", summary="Rechercher des PCs similaires")
async def search_similar_control_points(
    request: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """
    Recherche des PCs similaires basée sur un texte et des critères
    
    Payload attendu:
    {
        "requirement_text": "Texte de recherche",
        "domain": "A.8" (optionnel),
        "subdomain": "A.8.27" (optionnel),
        "min_similarity": 0.7 (optionnel, défaut 0.7)
    }
    """
    try:
        from src.services.ai_service import AIService
        
        requirement_text = request.get("requirement_text", "")
        domain = request.get("domain")
        subdomain = request.get("subdomain")
        min_similarity = request.get("min_similarity", 0.7)
        
        if not requirement_text or len(requirement_text.strip()) < 10:
            raise HTTPException(
                status_code=400,
                detail="Le texte de recherche doit contenir au moins 10 caractères"
            )
        
        logger.info(f"🔍 Recherche de PCs similaires pour: '{requirement_text[:100]}...'")
        
        # Initialiser le service AI
        ai_service = AIService()
        
        # Générer l'embedding du texte de recherche
        search_embedding = ai_service.generate_embedding(requirement_text)
        
        # Construire la requête SQL avec similarité cosine
        query = db.query(ControlPoint).filter(
            ControlPoint.embedding.isnot(None)
        )
        
        # Filtres optionnels par domaine/sous-domaine
        if domain:
            query = query.filter(ControlPoint.category == domain)
        if subdomain:
            query = query.filter(ControlPoint.subcategory == subdomain)
        
        control_points = query.all()
        
        # Calculer les similarités
        from src.utils.similarity import cosine_similarity
        
        similar_pcs = []
        for cp in control_points:
            if cp.embedding:
                similarity = cosine_similarity(search_embedding, cp.embedding)
                
                if similarity >= min_similarity:
                    # Compter les exigences liées
                    mapped_count = db.execute(
                        text("""
                            SELECT COUNT(*)
                            FROM requirement_control_point
                            WHERE control_point_id = :cp_id
                        """),
                        {"cp_id": cp.id}
                    ).scalar()
                    
                    similar_pcs.append({
                        "id": cp.id,
                        "code": cp.code,
                        "name": cp.name,
                        "description": cp.description,
                        "similarity_score": round(similarity, 4),
                        "criticality_level": cp.criticality_level,
                        "mapped_requirements_count": mapped_count or 0
                    })
        
        # Trier par similarité décroissante
        similar_pcs.sort(key=lambda x: x["similarity_score"], reverse=True)
        
        logger.info(f"✅ {len(similar_pcs)} PC(s) similaire(s) trouvé(s) (≥{min_similarity})")
        
        return {
            "search_text": requirement_text[:200],
            "min_similarity": min_similarity,
            "total_found": len(similar_pcs),
            "similar_control_points": similar_pcs[:10]  # Limiter à 10 résultats
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur recherche similarité: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{pc_id}/link-requirement", summary="Lier une exigence à un PC existant")
async def link_requirement_to_existing_pc(
    pc_id: str,
    request: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """Lie une exigence à un PC existant"""
    try:
        requirement_id = request.get("requirement_id")
        
        if not requirement_id:
            raise HTTPException(status_code=400, detail="requirement_id manquant")
        
        # Vérifier PC existe
        cp = db.query(ControlPoint).filter_by(id=pc_id).first()
        if not cp:
            raise HTTPException(status_code=404, detail="PC introuvable")
        
        # Vérifier exigence existe
        req = db.query(Requirement).filter_by(id=requirement_id).first()
        if not req:
            raise HTTPException(status_code=404, detail="Exigence introuvable")
        
        # Créer le mapping
        from sqlalchemy import text
        db.execute(
            text("""
                INSERT INTO requirement_control_point (requirement_id, control_point_id, mapping_method)
                VALUES (:req_id, :cp_id, 'manual')
                ON CONFLICT DO NOTHING
            """),
            {"req_id": requirement_id, "cp_id": pc_id}
        )
        
        db.commit()
        
        return {
            "success": True,
            "message": f"Exigence {req.official_code} liée au PC {cp.code}"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Erreur liaison : {e}")
        raise HTTPException(status_code=500, detail=str(e))


        
@router.post("/{control_point_id}/generate-embedding", status_code=200)
async def generate_embedding_for_single_control_point(
    control_point_id: str,
    db: Session = Depends(get_db),
):
    """
    Génère ou régénère l'embedding pour un seul point de contrôle.
    """
    try:
        from src.services.embedding_service import ControlPointEmbeddingService

        # Vérifie l'existence du point de contrôle
        cp = db.execute(
            text("SELECT id, name FROM control_point WHERE id = :id"),
            {"id": control_point_id},
        ).mappings().first()

        if not cp:
            raise HTTPException(status_code=404, detail="Point de contrôle introuvable")

        # Instancie le service d’embedding
        embedding_service = ControlPointEmbeddingService(db)

        # Génère l’embedding
        result = embedding_service.generate_embedding_for_control_point(control_point_id)

        return {
            "success": True,
            "control_point_id": control_point_id,
            "control_point_name": cp["name"],
            "embedding_generated": result is not None,
        }

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error(f"Erreur embedding pour PC {control_point_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Erreur embedding: {str(e)}")

# src/api/v1/control_points.py

@router.get("/")
async def list_control_points(
    framework_id: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Liste des points de contrôle, optionnellement filtrés par framework"""
    try:
        query = """
            SELECT 
                cp.id,
                cp.code,
                cp.name,
                cp.description
            FROM control_point cp
        """
        
        params = {}
        if framework_id:
            query += " WHERE cp.framework_id = :framework_id"
            params["framework_id"] = framework_id
        
        query += " ORDER BY cp.code"
        
        result = db.execute(text(query), params).fetchall()
        
        return [
            {
                "id": str(row.id),
                "code": row.code,
                "name": row.name,
                "description": row.description
            }
            for row in result
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
# REMPLACER LA ROUTE À LA LIGNE 3100 (environ)

@router.get("/{control_point_id}")
async def get_control_point_by_id(
    control_point_id: str,
    db: Session = Depends(get_db)
):
    """
    ✅ CORRECTION FINALE : Récupère un point de contrôle par son ID
    Utilise UNIQUEMENT les colonnes existantes dans la table
    """
    from sqlalchemy import text
    
    try:
        logger.info(f"🔍 Récupération PC par ID: {control_point_id}")
        
        # ✅ SELECT avec UNIQUEMENT les colonnes qui existent
        query = text("""
            SELECT
                cp.id,
                cp.code,
                cp.name,
                cp.description,
                cp.category,
                cp.subcategory,
                cp.control_family,
                cp.risk_domains,
                cp.implementation_level,
                cp.estimated_effort_hours,
                cp.criticality_level,
                cp.implementation_guidance,
                cp.created_by,
                cp.ai_confidence,
                cp.is_active,
                cp.created_at,
                cp.updated_at
            FROM control_point cp
            WHERE cp.id = :cp_id
            AND cp.is_active = true
            LIMIT 1
        """)
        
        row = db.execute(query, {"cp_id": control_point_id}).mappings().first()
        
        if not row:
            raise HTTPException(status_code=404, detail="Point de contrôle introuvable")
        
        result = {
            "id": str(row["id"]),
            "code": row["code"],
            "name": row["name"],
            "description": row["description"],
            "category": row["category"],
            "subcategory": row["subcategory"],
            "control_family": row["control_family"],
            "risk_domains": row["risk_domains"],
            "implementation_level": row["implementation_level"],
            "estimated_effort_hours": row["estimated_effort_hours"],
            "criticality_level": row["criticality_level"],
            "implementation_guidance": row["implementation_guidance"],
            "created_by": row["created_by"],
            "ai_confidence": float(row["ai_confidence"]) if row["ai_confidence"] else None,
            "is_active": row["is_active"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None
        }
        
        logger.info(f"✅ PC récupéré: {result['code']} - {result['name']}")
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"❌ Erreur get_control_point_by_id: {str(e)}")
        raise HTTPException(status_code=500, detail="Erreur serveur")


# ============================================================================
# MAPPING CROSS-RÉFÉRENTIEL CP → REQUIREMENTS (Validation Manuelle)
# ============================================================================

class AnalyzeReferentialRequest(BaseModel):
    """Requête d'analyse d'un référentiel pour mapping cross-ref"""
    referential_id: str = Field(..., description="UUID du référentiel source")
    limit: Optional[int] = Field(None, description="Limite du nombre de PCs (pour tests)")

class ProposedMappingModel(BaseModel):
    """Proposition de mapping IA"""
    control_point_id: str
    control_point: Dict[str, Any]
    matched_requirements: List[Dict[str, Any]]
    justification: str
    confidence: float
    no_match_reason: Optional[str] = None  # Raison si aucun match
    status: str = Field(default="pending")  # pending, approved, rejected

class AnalyzeReferentialResponse(BaseModel):
    """Réponse de l'analyse"""
    success: bool
    referential_id: str
    referential_name: str
    total_control_points: int  # Total CPs source à mapper
    control_points_mapped: int  # CPs avec au moins un match
    unmapped_control_points: int  # CPs sans correspondance
    total_target_requirements: int  # Total requirements du framework cible
    total_associations: int  # Total associations créées (CP → Req)
    proposed_mappings: List[ProposedMappingModel]
    message: str

class SaveMappingsRequest(BaseModel):
    """Requête de sauvegarde des mappings validés"""
    referential_id: str
    mappings: List[Dict[str, Any]]  # [{ control_point_id, requirement_ids: [], mapping_method }]

class SaveMappingsResponse(BaseModel):
    """Réponse de la sauvegarde"""
    success: bool
    mappings_created: int
    control_points_mapped: int
    requirements_linked: int
    message: str


@router.get("/mapping/analyze-referential/{source_referential_id}/stream", summary="Analyser un référentiel avec SSE (temps réel)")
async def stream_analyze_referential(
    source_referential_id: str,
    request: Request,
    db: Session = Depends(get_db),
    token: Optional[str] = Query(None)  # Token en query param pour SSE
):
    """
    Analyse un référentiel source et propose des mappings vers d'autres référentiels.

    Retourne un stream SSE (Server-Sent Events) pour progression en temps réel.

    Events:
    - initializing: Début de l'analyse
    - loaded: PCs et référentiels chargés
    - processing: Traitement batch en cours
    - batch_complete: Batch terminé
    - second_pass_started: Deuxième passe IA démarrée
    - second_pass_complete: Deuxième passe terminée
    - second_pass_error: Erreur deuxième passe
    - completed: Analyse terminée avec résultats
    - error: Erreur générale
    """

    # Vérifier le token (car EventSource ne supporte pas headers custom)
    if not token:
        async def error_generator():
            yield f"data: {json.dumps({'error': 'Token manquant'})}\n\n"
        return StreamingResponse(error_generator(), media_type="text/event-stream")

    # TODO: Valider le token JWT si nécessaire
    # user = verify_jwt_token(token)

    # Queue pour les événements de progression
    progress_queue = asyncio.Queue()

    async def progress_callback(event_data: dict):
        """Callback pour notifier le frontend de la progression."""
        await progress_queue.put(event_data)

    async def event_generator():
        try:
            # Convertir source_referential_id en UUID
            try:
                source_ref_uuid = UUID(source_referential_id)
            except ValueError:
                yield f"data: {json.dumps({'error': 'ID de référentiel invalide'})}\n\n"
                return

            # Vérifier que le référentiel existe
            from sqlalchemy import text as sql_text
            referential = db.execute(
                sql_text("SELECT id, name FROM framework WHERE id = CAST(:ref_id AS uuid)"),
                {"ref_id": source_referential_id}
            ).fetchone()

            if not referential:
                yield f"data: {json.dumps({'error': 'Référentiel introuvable'})}\n\n"
                return

            # Envoyer événement de démarrage
            yield f"data: {json.dumps({'status': 'initializing', 'message': 'Chargement des points de contrôle...'})}\n\n"

            # Récupérer le service
            from src.services.control_point_requirement_mapping_service import ControlPointRequirementMappingService
            import os

            # Configuration IA : Ollama en priorité, DeepSeek Cloud en fallback
            ollama_url = os.getenv('OLLAMA_URL', 'http://localhost:11434')
            ollama_model = os.getenv('OLLAMA_MODEL', 'deepseek-v3.1:671b-cloud')
            deepseek_api_key = os.getenv('DEEPSEEK_API_KEY')

            # Utiliser Ollama par défaut
            use_ollama = True
            if not ollama_url:
                # Fallback sur DeepSeek Cloud
                if not deepseek_api_key or deepseek_api_key.startswith('sk-xxxx'):
                    yield f"data: {json.dumps({'error': 'Ni OLLAMA_URL ni DEEPSEEK_API_KEY configurés'})}\n\n"
                    return
                use_ollama = False

            service = ControlPointRequirementMappingService(
                db=db,
                api_key=deepseek_api_key,
                use_ollama=use_ollama,
                ollama_url=ollama_url,
                ollama_model=ollama_model
            )

            # Lancer l'analyse dans une tâche séparée
            async def run_analysis():
                return await service.analyze_framework_for_proposals(
                    framework_id=source_referential_id,
                    limit=None,
                    progress_callback=progress_callback
                )

            analysis_task = asyncio.create_task(run_analysis())

            # Envoyer les événements de progression
            while not analysis_task.done():
                try:
                    # Attendre un événement avec timeout
                    event_data = await asyncio.wait_for(progress_queue.get(), timeout=0.5)
                    yield f"data: {json.dumps(event_data)}\n\n"
                except asyncio.TimeoutError:
                    # Vérifier si le client est toujours connecté
                    if await request.is_disconnected():
                        analysis_task.cancel()
                        return
                    continue

            # Récupérer le résultat final
            result = await analysis_task

            # Filtrer pour ne garder QUE les CPs avec au moins un mapping trouvé
            # Les CPs sans correspondance ne doivent PAS apparaître dans la liste de validation
            proposed_mappings_with_status = []
            rejected_count = 0
            for m in result.get("proposed_mappings", []):
                has_match = len(m.get('matched_requirements', [])) > 0

                if has_match:
                    # Ajouter uniquement les CPs qui ont au moins un mapping
                    mapping_with_status = {
                        **m,
                        "status": "pending"  # En attente de validation
                    }
                    proposed_mappings_with_status.append(mapping_with_status)
                else:
                    # Compter les CPs rejetés (sans mapping)
                    rejected_count += 1

            # Envoyer le résultat final
            final_result = {
                "status": "completed",
                "success": True,
                "results": {
                    "proposed_mappings": proposed_mappings_with_status,
                    "total_proposals": len(result.get("proposed_mappings", [])),
                    "referential_id": result.get("framework_id"),
                    "referential_name": result.get("framework_name"),
                    "total_control_points": result.get("total_source_control_points", 0),
                    "control_points_mapped": result.get("control_points_mapped", 0),
                    "unmapped_control_points": result.get("control_points_without_match", 0),
                    "total_target_requirements": result.get("total_target_requirements", 0),
                    "total_associations": result.get("total_associations", 0),
                    "message": f"{result.get('control_points_mapped', 0)}/{result.get('total_source_control_points', 0)} CPs mappés avec succès ({result.get('total_associations', 0)} associations créées)"
                }
            }
            yield f"data: {json.dumps(final_result)}\n\n"

        except Exception as e:
            logger.error(f"❌ Erreur SSE: {e}", exc_info=True)
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
        }
    )


@router.post("/mapping/analyze-referential", response_model=AnalyzeReferentialResponse, summary="Analyser un référentiel pour mapping cross-ref")
async def analyze_referential_for_mapping(
    request: AnalyzeReferentialRequest,
    db: Session = Depends(get_db)
):
    """
    Analyse les PCs non mappés d'un référentiel et propose des mappings vers des requirements

    Étapes :
    1. Récupère les PCs du référentiel source
    2. Identifie ceux qui ne sont PAS déjà mappés dans requirement_control_point
    3. Utilise l'IA pour proposer des mappings vers des requirements d'autres référentiels
    4. Retourne les propositions pour validation manuelle par l'utilisateur

    Args:
        referential_id: UUID du référentiel source
        limit: Limite optionnelle pour tests

    Returns:
        Liste de propositions de mapping avec justifications et scores de confiance
    """
    try:
        from src.services.control_point_requirement_mapping_service import ControlPointRequirementMappingService
        import os

        logger.info(f"🔍 Analyse du référentiel {request.referential_id} pour mapping cross-ref")

        # Configuration IA : Ollama en priorité, DeepSeek Cloud en fallback
        ollama_url = os.getenv('OLLAMA_URL', 'http://localhost:11434')
        ollama_model = os.getenv('OLLAMA_MODEL', 'deepseek-v3.1:671b-cloud')
        deepseek_api_key = os.getenv('DEEPSEEK_API_KEY')

        # Utiliser Ollama par défaut
        use_ollama = True
        if not ollama_url:
            # Fallback sur DeepSeek Cloud
            if not deepseek_api_key or deepseek_api_key.startswith('sk-xxxx'):
                raise HTTPException(
                    status_code=500,
                    detail="Ni OLLAMA_URL ni DEEPSEEK_API_KEY configurés"
                )
            use_ollama = False

        # Créer le service
        service = ControlPointRequirementMappingService(
            db=db,
            api_key=deepseek_api_key,
            use_ollama=use_ollama,
            ollama_url=ollama_url,
            ollama_model=ollama_model
        )

        # Lancer l'analyse (retourne propositions SANS sauvegarder)
        result = await service.analyze_framework_for_proposals(
            framework_id=request.referential_id,
            limit=request.limit
        )

        logger.info(f"✅ Analyse terminée : {len(result['proposed_mappings'])} propositions")

        # Filtrer pour ne garder QUE les CPs avec au moins un mapping trouvé
        # Les CPs sans correspondance ne doivent PAS apparaître dans la liste de validation
        proposed_mappings = []
        rejected_count = 0
        for m in result['proposed_mappings']:
            has_match = len(m.get('matched_requirements', [])) > 0

            if has_match:
                # Ajouter uniquement les CPs qui ont au moins un mapping
                proposed_mappings.append(
                    ProposedMappingModel(
                        control_point_id=m['control_point_id'],
                        control_point=m['control_point'],
                        matched_requirements=m['matched_requirements'],
                        justification=m['justification'],
                        confidence=m['confidence'],
                        no_match_reason=None,
                        status="pending"  # En attente de validation
                    )
                )
            else:
                # Compter les CPs rejetés (sans mapping)
                rejected_count += 1
                logger.info(f"   ⚠️  CP sans mapping ignoré: {m['control_point']['code']} - {m.get('no_match_reason', 'Raison non fournie')}")

        return AnalyzeReferentialResponse(
            success=True,
            referential_id=result['framework_id'],
            referential_name=result['framework_name'],
            total_control_points=result['total_source_control_points'],
            control_points_mapped=result['control_points_mapped'],
            unmapped_control_points=result['control_points_without_match'],
            total_target_requirements=result['total_target_requirements'],
            total_associations=result['total_associations'],
            proposed_mappings=proposed_mappings,
            message=f"{result['control_points_mapped']}/{result['total_source_control_points']} CPs mappés avec succès ({result['total_associations']} associations créées)"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur analyse référentiel: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de l'analyse: {str(e)}"
        )


@router.post("/mapping/save-validated", response_model=SaveMappingsResponse, summary="Sauvegarder les mappings validés")
async def save_validated_mappings(
    request: SaveMappingsRequest,
    db: Session = Depends(get_db)
):
    """
    Sauvegarde les mappings validés par l'utilisateur dans requirement_control_point

    Args:
        referential_id: UUID du référentiel source
        mappings: Liste des mappings approuvés [{control_point_id, requirement_ids, mapping_method}]

    Returns:
        Statistiques de sauvegarde
    """
    try:
        logger.info(f"💾 === DÉBUT SAUVEGARDE MAPPINGS ===")
        logger.info(f"💾 Référentiel ID: {request.referential_id}")
        logger.info(f"💾 Nombre de mappings reçus: {len(request.mappings)}")

        # Log du premier mapping comme exemple
        if request.mappings:
            first = request.mappings[0]
            logger.info(f"💾 Exemple premier mapping:")
            logger.info(f"   - CP ID: {first.get('control_point_id')}")
            logger.info(f"   - Requirement IDs: {first.get('requirement_ids', [])}")
            logger.info(f"   - Method: {first.get('mapping_method', 'manual')}")

        mappings_created = 0
        mappings_skipped = 0  # Compteur pour ON CONFLICT
        control_points_mapped = set()
        requirements_linked = set()

        for idx, mapping in enumerate(request.mappings):
            cp_id = mapping.get('control_point_id')
            req_ids = mapping.get('requirement_ids', [])
            method = mapping.get('mapping_method', 'manual')

            logger.info(f"💾 Traitement mapping {idx+1}/{len(request.mappings)}: CP {cp_id} → {len(req_ids)} requirements")

            if not cp_id or not req_ids:
                logger.warning(f"⚠️  Mapping {idx+1} ignoré: cp_id={cp_id}, req_ids={req_ids}")
                continue

            for req_id in req_ids:
                try:
                    # Vérifier d'abord si le mapping existe déjà
                    existing_check = db.execute(text("""
                        SELECT id FROM requirement_control_point
                        WHERE requirement_id = CAST(:req_id AS uuid)
                          AND control_point_id = CAST(:cp_id AS uuid)
                    """), {
                        "cp_id": cp_id,
                        "req_id": req_id
                    })

                    existing_mapping = existing_check.fetchone()

                    if existing_mapping:
                        # Mapping existe déjà
                        mappings_skipped += 1
                        logger.info(f"   ⏭️  Existe déjà: CP {cp_id} → Req {req_id} (ID existant: {existing_mapping[0]})")
                    else:
                        # Insérer le nouveau mapping
                        result = db.execute(text("""
                            INSERT INTO requirement_control_point (requirement_id, control_point_id, mapping_method)
                            VALUES (CAST(:req_id AS uuid), CAST(:cp_id AS uuid), :method)
                            RETURNING id
                        """), {
                            "cp_id": cp_id,
                            "req_id": req_id,
                            "method": method
                        })

                        inserted_row = result.fetchone()
                        if inserted_row:
                            mappings_created += 1
                            control_points_mapped.add(cp_id)
                            requirements_linked.add(req_id)
                            logger.info(f"   ✅ Inséré: CP {cp_id} → Req {req_id} (ID: {inserted_row[0]})")

                except Exception as e:
                    logger.error(f"❌ Erreur insertion mapping CP {cp_id} → Req {req_id}: {e}")
                    # En cas d'erreur, rollback et re-raise pour arrêter le processus
                    db.rollback()
                    raise

        db.commit()

        logger.info(f"💾 === RÉSUMÉ SAUVEGARDE ===")
        logger.info(f"✅ Mappings créés: {mappings_created}")
        logger.info(f"⏭️  Mappings ignorés (déjà existants): {mappings_skipped}")
        logger.info(f"📊 Total CPs mappés: {len(control_points_mapped)}")
        logger.info(f"📊 Total Requirements liés: {len(requirements_linked)}")

        return SaveMappingsResponse(
            success=True,
            mappings_created=mappings_created,
            control_points_mapped=len(control_points_mapped),
            requirements_linked=len(requirements_linked),
            message=f"{mappings_created} nouveaux liens créés entre {len(control_points_mapped)} PCs et {len(requirements_linked)} exigences"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur sauvegarde mappings: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la sauvegarde: {str(e)}"
        )


# ============================================================================
# MAPPING AUTOMATIQUE CP → QUESTIONS VIA IA (DEPRECATED - Pour compatibilité)
# ============================================================================

class MappingRequest(BaseModel):
    """Requête de mapping automatique"""
    questionnaire_id: Optional[str] = Field(None, description="UUID du questionnaire spécifique (optionnel)")
    limit: Optional[int] = Field(None, description="Limite du nombre de PCs à traiter (pour tests)")

class MappingResponse(BaseModel):
    """Réponse du mapping automatique"""
    success: bool
    questionnaires_analyzed: int
    total_mappings_created: int
    total_pcs_uncovered: int
    ai_calls: int
    errors: int
    message: str


@router.post("/mapping/auto", response_model=MappingResponse, summary="Mapping automatique CP → Questions via IA")
async def launch_auto_mapping(
    request: MappingRequest,
    db: Session = Depends(get_db)
):
    """
    Lance le mapping automatique des Control Points vers les Questions via IA

    Fonctionnement :
    - Identifie les PCs non couverts (sans mapping vers une question)
    - Utilise l'IA pour trouver les questions existantes qui couvrent chaque PC
    - Crée les mappings manquants
    - Ne modifie JAMAIS les mappings existants
    - Ne crée JAMAIS de nouvelles questions

    Args:
        questionnaire_id: UUID du questionnaire (si None = tous les questionnaires)
        limit: Limite du nombre de PCs à traiter (pour tests)

    Returns:
        Statistiques du mapping effectué
    """
    try:
        from src.services.control_point_question_mapping_service import ControlPointQuestionMappingService
        import os

        logger.info("🚀 Lancement du mapping automatique CP → Questions")

        # Récupérer la clé API DeepSeek
        deepseek_api_key = os.getenv('DEEPSEEK_API_KEY')
        if not deepseek_api_key:
            raise HTTPException(
                status_code=500,
                detail="DEEPSEEK_API_KEY non configurée dans les variables d'environnement"
            )

        # Créer le service
        service = ControlPointQuestionMappingService(db, deepseek_api_key)

        # Lancer le mapping
        stats = await service.map_control_points_to_questions(
            questionnaire_id=request.questionnaire_id,
            limit=request.limit
        )

        # Construire le message de résumé
        if stats.get('error'):
            message = stats['error']
        else:
            message = (
                f"Mapping terminé : {stats['total_mappings_created']} nouveaux mappings créés "
                f"sur {stats['questionnaires_analyzed']} questionnaire(s). "
                f"{stats['total_pcs_uncovered']} PC(s) restent non couverts."
            )

        logger.info(f"✅ {message}")

        return MappingResponse(
            success=not stats.get('error'),
            questionnaires_analyzed=stats.get('questionnaires_analyzed', 0),
            total_mappings_created=stats.get('total_mappings_created', 0),
            total_pcs_uncovered=stats.get('total_pcs_uncovered', 0),
            ai_calls=stats.get('ai_calls', 0),
            errors=stats.get('errors', 0),
            message=message
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur mapping automatique: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors du mapping automatique: {str(e)}"
        )