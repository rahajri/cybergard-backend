# src/services/cross_referential_service.py
"""
Service de mapping cross-référentiel entre exigences
Détecte automatiquement les équivalences sémantiques entre différents référentiels
"""

import logging
from typing import Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime
import uuid

from ..models.audit import Requirement, Framework
from ..database import get_db
from .embedding_service import RequirementEmbeddingService

logger = logging.getLogger(__name__)

class CrossReferentialMappingService:
    """Service pour détecter et gérer les mappings cross-référentiels"""
    
    def __init__(self, db: Session):
        self.db = db
        self.embedding_service = RequirementEmbeddingService(db)
    
    def detect_cross_mappings(self, new_framework_id: str, 
                            similarity_threshold: float = 0.75,
                            auto_validate_threshold: float = 0.95) -> Dict:
        """
        Détecter automatiquement les mappings lors d'un nouvel import de référentiel
        
        Args:
            new_framework_id: ID du nouveau référentiel importé
            similarity_threshold: Seuil minimum de similarité pour créer un mapping
            auto_validate_threshold: Seuil pour validation automatique
            
        Returns:
            Dict avec résultats de la détection
        """
        
        try:
            # Récupérer les nouvelles exigences
            new_requirements = self.db.query(Requirement).filter_by(
                framework_id=new_framework_id
            ).all()
            
            if not new_requirements:
                return {"error": "No requirements found for framework"}
            
            mappings_detected = []
            auto_validated = 0
            pending_validation = 0
            
            for new_req in new_requirements:
                # Chercher les exigences similaires dans les autres frameworks
                similar_reqs = self.embedding_service.find_similar_requirements(
                    query_text=self._create_embedding_text(new_req),
                    limit=10
                )
                
                for similar in similar_reqs:
                    similarity_score = similar.get('similarity_score', 0)
                    
                    # Filtrer par seuil et éviter l'auto-mapping
                    if (similarity_score >= similarity_threshold and 
                        similar['requirement_id'] != str(new_req.id)):
                        
                        # Vérifier que ce n'est pas du même framework
                        target_req = self.db.query(Requirement).filter_by(
                            id=similar['requirement_id']
                        ).first()
                        
                        if target_req and target_req.framework_id != new_framework_id:
                            mapping_data = {
                                'source_requirement_id': str(new_req.id),
                                'target_requirement_id': similar['requirement_id'],
                                'mapping_type': self._determine_mapping_type(similarity_score),
                                'semantic_similarity': similarity_score,
                                'domain_match': self._check_domain_match(new_req, similar),
                                'confidence_score': similarity_score,
                                'mapping_rationale': self._generate_mapping_rationale(
                                    new_req, similar, similarity_score
                                ),
                                'created_by': 'ai',
                                'validation_status': 'approved' if similarity_score >= auto_validate_threshold else 'pending'
                            }
                            
                            mappings_detected.append(mapping_data)
                            
                            if similarity_score >= auto_validate_threshold:
                                auto_validated += 1
                            else:
                                pending_validation += 1
            
            # Éliminer les doublons
            unique_mappings = self._remove_duplicate_mappings(mappings_detected)
            
            # Stocker les mappings
            stored_mappings = self._store_mappings(unique_mappings)
            
            return {
                "framework_id": new_framework_id,
                "total_requirements_analyzed": len(new_requirements),
                "mappings_detected": len(stored_mappings),
                "auto_validated": auto_validated,
                "pending_validation": pending_validation,
                "similarity_threshold": similarity_threshold,
                "status": "completed",
                "mappings": stored_mappings[:10]  # Retourner les 10 premiers pour exemple
            }
            
        except Exception as e:
            logger.error(f"Error detecting cross mappings: {str(e)}")
            raise
    
    def _create_embedding_text(self, req: Requirement) -> str:
        """Créer le texte pour la similarité sans dépendre de req.domain/subdomain (supprimés)."""
        parts = []
        if getattr(req, "title", None):
            parts.append(req.title)
        if getattr(req, "requirement_text", None):
            parts.append(req.requirement_text)
        # Optionnel: si ton modèle expose chapter_path/tags
        if getattr(req, "chapter_path", None):
            parts.append(req.chapter_path)
        return " | ".join(parts)
    
    def _determine_mapping_type(self, similarity_score: float) -> str:
        """Déterminer le type de mapping basé sur le score de similarité"""
        if similarity_score >= 0.95:
            return 'equivalent'
        elif similarity_score >= 0.85:
            return 'similar'
        elif similarity_score >= 0.75:
            return 'related'
        else:
            return 'weak_relation'
    
    def _check_domain_match(self, req1: Requirement, req2_data: Dict) -> bool:
        """Comparer les labels de domaine si disponibles dans target_data."""
        label1 = getattr(req1, "domain_label", None) or getattr(req1, "chapter_path", None)
        label2 = req2_data.get("domain_label") or req2_data.get("domain") or req2_data.get("chapter_path")
        if label1 and label2:
            return str(label1).strip().lower() == str(label2).strip().lower()
        return False

    
    def _generate_mapping_rationale(self, source_req: Requirement, target_data: Dict, similarity_score: float) -> str:
        """Explication du mapping (similarité + éventuel match de domaine)"""
        rationale_parts = [f"Semantic similarity: {similarity_score:.3f}"]
        try:
            src_dom = getattr(source_req, "domain_label", None) or getattr(source_req, "chapter_path", None)
            tgt_dom = target_data.get("domain_label") or target_data.get("domain") or target_data.get("chapter_path")
            if src_dom and tgt_dom and str(src_dom).strip().lower() == str(tgt_dom).strip().lower():
                rationale_parts.append(f"Same domain: {src_dom}")
        except Exception:
            pass
        return " | ".join(rationale_parts)

    
    def _remove_duplicate_mappings(self, mappings: List[Dict]) -> List[Dict]:
        """Éliminer les mappings en double"""
        seen = set()
        unique_mappings = []
        
        for mapping in mappings:
            # Créer une clé unique pour éviter les doublons
            key = tuple(sorted([
                mapping['source_requirement_id'],
                mapping['target_requirement_id']
            ]))
            
            if key not in seen:
                seen.add(key)
                unique_mappings.append(mapping)
        
        return unique_mappings
    
    def _store_mappings(self, mappings: List[Dict]) -> List[str]:
        """
        Stocker les mappings en base de données
        
        Args:
            mappings: Liste des mappings à stocker
            
        Returns:
            Liste des IDs des mappings créés
        """
        
        try:
            stored_ids = []
            
            for mapping in mappings:
                mapping_id = str(uuid.uuid4())
                
                # Stocker le mapping
                self.db.execute(text("""
                    INSERT INTO requirement_mapping 
                    (id, source_requirement_id, target_requirement_id, mapping_type,
                     confidence_score, semantic_similarity, domain_match, created_by,
                     validation_status, mapping_rationale)
                    VALUES (:id, :source_req_id, :target_req_id, :mapping_type,
                            :confidence_score, :semantic_similarity, :domain_match,
                            :created_by, :validation_status, :mapping_rationale)
                    ON CONFLICT (source_requirement_id, target_requirement_id)
                    DO UPDATE SET
                        semantic_similarity = EXCLUDED.semantic_similarity,
                        confidence_score = EXCLUDED.confidence_score,
                        mapping_rationale = EXCLUDED.mapping_rationale
                """), {
                    "id": mapping_id,
                    "source_req_id": mapping['source_requirement_id'],
                    "target_req_id": mapping['target_requirement_id'],
                    "mapping_type": mapping['mapping_type'],
                    "confidence_score": mapping['confidence_score'],
                    "semantic_similarity": mapping['semantic_similarity'],
                    "domain_match": mapping['domain_match'],
                    "created_by": mapping['created_by'],
                    "validation_status": mapping['validation_status'],
                    "mapping_rationale": mapping['mapping_rationale']
                })
                
                stored_ids.append(mapping_id)
            
            self.db.commit()
            return stored_ids
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error storing mappings: {str(e)}")
            raise
    
    def get_cross_referential_coverage(self, requirement_id: str) -> List[Dict]:
        """
        Retourne les exigences équivalentes (mappings) dans d'autres référentiels,
        avec libellés de domaine calculés via domain/domain_title.
        """
        try:
            results = self.db.execute(text("""
                SELECT 
                    rm.id AS mapping_id,
                    rm.mapping_type,
                    rm.semantic_similarity,
                    rm.validation_status,

                    r.id AS requirement_id,
                    r.official_code,
                    r.title,
                    r.requirement_text,

                    f.name  AS framework_name,
                    f.code  AS framework_code,

                    d.level AS domain_level,
                    COALESCE(dt.title, d.code) AS domain_label,
                    COALESCE(pt.title, p.code) AS parent_label
                FROM requirement_mapping rm
                JOIN requirement r           ON r.id = rm.target_requirement_id
                JOIN framework f             ON f.id = r.framework_id
                LEFT JOIN domain d           ON d.id = r.domain_id
                LEFT JOIN domain_title dt    ON dt.domain_id = d.id AND dt.is_primary = true AND dt.language='fr'
                LEFT JOIN domain p           ON p.id = d.parent_id
                LEFT JOIN domain_title pt    ON pt.domain_id = p.id AND pt.is_primary = true AND pt.language='fr'
                WHERE rm.source_requirement_id = :rid
                AND rm.validation_status IN ('pending','validated','auto_validated')
                ORDER BY rm.semantic_similarity DESC NULLS LAST, r.official_code
            """), {"rid": requirement_id}).mappings().all()

            def flatten(level, dom, parent):
                if level is not None and level >= 1:
                    return (parent or dom or "N/A", dom or None)
                return (dom or "N/A", None)

            items = []
            for row in results:
                dom_txt, sub_txt = flatten(row["domain_level"], row["domain_label"], row["parent_label"])
                items.append({
                    "mapping_id": row["mapping_id"],
                    "mapping_type": row["mapping_type"],
                    "semantic_similarity": float(row["semantic_similarity"] or 0),
                    "validation_status": row["validation_status"],
                    "requirement_id": str(row["requirement_id"]),
                    "official_code": row["official_code"],
                    "title": row["title"],
                    "framework_name": row["framework_name"],
                    "framework_code": row["framework_code"],
                    "domain": dom_txt,
                    "subdomain": sub_txt,
                })
            return items

        except Exception as e:
            logger.error(f"Error fetching cross coverage: {str(e)}")
            raise
    
    def validate_mapping(self, mapping_id: str, user_id: str, 
                        approved: bool, rationale: str = None) -> bool:
        """
        Valider ou rejeter un mapping
        
        Args:
            mapping_id: ID du mapping
            user_id: ID de l'utilisateur qui valide
            approved: True si approuvé, False si rejeté
            rationale: Justification de la décision
            
        Returns:
            True si la validation a réussi
        """
        
        try:
            status = 'approved' if approved else 'rejected'
            
            self.db.execute(text("""
                UPDATE requirement_mapping
                SET validation_status = :status,
                    validated_by = :user_id,
                    validation_date = NOW(),
                    mapping_rationale = COALESCE(:rationale, mapping_rationale)
                WHERE id = :mapping_id
            """), {
                "status": status,
                "user_id": user_id,
                "rationale": rationale,
                "mapping_id": mapping_id
            })
            
            self.db.commit()
            return True
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error validating mapping {mapping_id}: {str(e)}")
            return False
    
    def get_pending_mappings(self, framework_id: str = None, limit: int = 50) -> List[Dict]:
        """
        Récupérer les mappings en attente de validation
        
        Args:
            framework_id: Filtrer par framework (optionnel)
            limit: Nombre maximum de résultats
            
        Returns:
            Liste des mappings en attente
        """
        
        try:
            sql = """
                SELECT 
                    rm.id as mapping_id,
                    rm.mapping_type,
                    rm.semantic_similarity,
                    rm.confidence_score,
                    rm.mapping_rationale,
                    rm.created_at,
                    r1.official_code as source_code,
                    r1.title as source_title,
                    f1.name as source_framework,
                    r2.official_code as target_code,
                    r2.title as target_title,
                    f2.name as target_framework
                FROM requirement_mapping rm
                JOIN requirement r1 ON rm.source_requirement_id = r1.id
                JOIN framework f1 ON r1.framework_id = f1.id
                JOIN requirement r2 ON rm.target_requirement_id = r2.id
                JOIN framework f2 ON r2.framework_id = f2.id
                WHERE rm.validation_status = 'pending'
            """
            
            params = {}
            
            if framework_id:
                sql += " AND (r1.framework_id = :framework_id OR r2.framework_id = :framework_id)"
                params["framework_id"] = framework_id
            
            sql += " ORDER BY rm.semantic_similarity DESC LIMIT :limit"
            params["limit"] = limit
            
            results = self.db.execute(text(sql), params).fetchall()
            
            return [
                {
                    "mapping_id": str(row.mapping_id),
                    "mapping_type": row.mapping_type,
                    "semantic_similarity": float(row.semantic_similarity),
                    "confidence_score": float(row.confidence_score),
                    "mapping_rationale": row.mapping_rationale,
                    "created_at": row.created_at.isoformat(),
                    "source": {
                        "code": row.source_code,
                        "title": row.source_title,
                        "framework": row.source_framework
                    },
                    "target": {
                        "code": row.target_code,
                        "title": row.target_title,
                        "framework": row.target_framework
                    }
                }
                for row in results
            ]
            
        except Exception as e:
            logger.error(f"Error getting pending mappings: {str(e)}")
            return []
    
    def get_mapping_statistics(self, framework_id: str = None) -> Dict:
        """
        Obtenir des statistiques sur les mappings
        
        Args:
            framework_id: Filtrer par framework (optionnel)
            
        Returns:
            Dictionnaire avec les statistiques
        """
        
        try:
            sql_base = """
                FROM requirement_mapping rm
                JOIN requirement r1 ON rm.source_requirement_id = r1.id
                JOIN requirement r2 ON rm.target_requirement_id = r2.id
            """
            
            where_clause = ""
            params = {}
            
            if framework_id:
                where_clause = " WHERE (r1.framework_id = :framework_id OR r2.framework_id = :framework_id)"
                params["framework_id"] = framework_id
            
            # Statistiques générales
            stats_result = self.db.execute(text(f"""
                SELECT 
                    COUNT(*) as total_mappings,
                    COUNT(CASE WHEN rm.validation_status = 'approved' THEN 1 END) as approved,
                    COUNT(CASE WHEN rm.validation_status = 'pending' THEN 1 END) as pending,
                    COUNT(CASE WHEN rm.validation_status = 'rejected' THEN 1 END) as rejected,
                    AVG(rm.semantic_similarity) as avg_similarity,
                    COUNT(CASE WHEN rm.mapping_type = 'equivalent' THEN 1 END) as equivalent,
                    COUNT(CASE WHEN rm.mapping_type = 'similar' THEN 1 END) as similar,
                    COUNT(CASE WHEN rm.mapping_type = 'related' THEN 1 END) as related
                {sql_base} {where_clause}
            """), params).fetchone()
            
            return {
                "total_mappings": stats_result.total_mappings,
                "validation_status": {
                    "approved": stats_result.approved,
                    "pending": stats_result.pending,
                    "rejected": stats_result.rejected
                },
                "mapping_types": {
                    "equivalent": stats_result.equivalent,
                    "similar": stats_result.similar,
                    "related": stats_result.related
                },
                "average_similarity": float(stats_result.avg_similarity) if stats_result.avg_similarity else 0.0,
                "approval_rate": round((stats_result.approved / stats_result.total_mappings * 100), 2) if stats_result.total_mappings > 0 else 0
            }
            
        except Exception as e:
            logger.error(f"Error getting mapping statistics: {str(e)}")
            return {}

# Fonctions helper pour l'utilisation externe
def detect_mappings_for_framework(framework_id: str) -> Dict:
    """
    Fonction helper pour détecter les mappings d'un nouveau framework
    
    Args:
        framework_id: ID du framework
        
    Returns:
        Dict avec résultats de la détection
    """
    
    db = next(get_db())
    try:
        service = CrossReferentialMappingService(db)
        return service.detect_cross_mappings(framework_id)
    finally:
        db.close()

def get_framework_equivalencies(requirement_id: str) -> List[Dict]:
    """
    Fonction helper pour obtenir les équivalences d'une exigence
    
    Args:
        requirement_id: ID de l'exigence
        
    Returns:
        Liste des exigences équivalentes
    """
    
    db = next(get_db())
    try:
        service = CrossReferentialMappingService(db)
        return service.get_cross_referential_coverage(requirement_id)
    finally:
        db.close()