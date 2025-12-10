# src/services/coverage_service.py
"""
Service de calcul de couverture multi-référentiels
Permet de calculer les taux de conformité cross-référentiels basés sur les mappings d'exigences
"""

import logging
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime

from ..models.audit import Framework, Requirement, Audit
from ..database import get_db

logger = logging.getLogger(__name__)

class CrossReferentialCoverageService:
    """Service principal pour calculer la couverture multi-référentiels"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def calculate_multi_framework_coverage(self, audit_id: str) -> Dict[str, dict]:
        """
        Calculer la couverture pour tous les référentiels basé sur un audit
        
        Args:
            audit_id: ID de l'audit
            
        Returns:
            Dict avec la couverture par framework
        """
        
        coverage_results = {}
        
        try:
            # Récupérer tous les référentiels actifs
            frameworks = self.db.query(Framework).filter_by(is_active=True).all()
            
            for framework in frameworks:
                coverage = self._calculate_framework_coverage(audit_id, framework.id)
                coverage_results[framework.code] = {
                    'framework_id': str(framework.id),
                    'name': framework.name,
                    'version': framework.version,
                    'coverage_percentage': coverage['percentage'],
                    'covered_requirements': coverage['covered'],
                    'total_requirements': coverage['total'],
                    'calculation_method': coverage['method'],
                    'breakdown': coverage.get('breakdown', {})
                }
            
            # Sauvegarder les résultats en base
            self._store_coverage_results(audit_id, coverage_results)
            
            return coverage_results
            
        except Exception as e:
            logger.error(f"Error calculating multi-framework coverage for audit {audit_id}: {str(e)}")
            raise
    
    def _calculate_framework_coverage(self, audit_id: str, framework_id: str) -> Dict:
        """
        Calculer la couverture pour un référentiel spécifique
        
        Args:
            audit_id: ID de l'audit
            framework_id: ID du référentiel
            
        Returns:
            Dict avec les métriques de couverture
        """
        
        # Méthode 1: Couverture directe (réponses directes au référentiel)
        direct_coverage = self._calculate_direct_coverage(audit_id, framework_id)
        
        # Méthode 2: Couverture via mapping cross-référentiel
        cross_coverage = self._calculate_cross_mapped_coverage(audit_id, framework_id)
        
        # Méthode hybride: combinaison intelligente
        hybrid_coverage = self._calculate_hybrid_coverage(direct_coverage, cross_coverage)
        
        return hybrid_coverage
    
    def _calculate_direct_coverage(self, audit_id: str, framework_id: str) -> Dict:
        """
        Couverture basée sur les réponses directes aux questions du référentiel
        
        Args:
            audit_id: ID de l'audit
            framework_id: ID du référentiel
            
        Returns:
            Dict avec métriques de couverture directe
        """
        
        try:
            result = self.db.execute(text("""
                SELECT 
                    COUNT(DISTINCT r.id) as total_requirements,
                    COUNT(DISTINCT CASE 
                        WHEN qa.status = 'submitted' AND qa.response_value_bool = true 
                        THEN r.id 
                    END) as covered_requirements
                FROM requirement r
                LEFT JOIN requirement_control_point rcp ON rcp.requirement_id = r.id
                LEFT JOIN question q ON q.control_point_id = rcp.control_point_id
                LEFT JOIN question_answer qa ON qa.question_id = q.id AND qa.audit_id = :audit_id
                WHERE r.framework_id = :framework_id
            """), {"audit_id": audit_id, "framework_id": framework_id}).fetchone()
            
            total = result.total_requirements if result.total_requirements else 0
            covered = result.covered_requirements if result.covered_requirements else 0
            
            return {
                'percentage': round((covered / total * 100), 2) if total > 0 else 0,
                'covered': covered,
                'total': total,
                'method': 'direct'
            }
            
        except Exception as e:
            logger.error(f"Error calculating direct coverage: {str(e)}")
            return {'percentage': 0, 'covered': 0, 'total': 0, 'method': 'direct'}
    
    def _calculate_cross_mapped_coverage(self, audit_id: str, framework_id: str) -> Dict:
        """
        Couverture via mappings cross-référentiels
        
        Args:
            audit_id: ID de l'audit
            framework_id: ID du référentiel cible
            
        Returns:
            Dict avec métriques de couverture cross-référentiel
        """
        
        try:
            # Récupérer toutes les exigences du framework cible
            target_requirements = self.db.execute(text("""
                SELECT DISTINCT r.id
                FROM requirement r
                WHERE r.framework_id = :framework_id
            """), {"framework_id": framework_id}).fetchall()
            
            covered_via_mapping = 0
            
            for req_row in target_requirements:
                # Vérifier si cette exigence est couverte via mapping cross-référentiel
                is_covered = self.db.execute(text("""
                    SELECT COUNT(*) > 0 as is_covered
                    FROM requirement_mapping rm
                    JOIN requirement source_req ON source_req.id = rm.source_requirement_id
                    JOIN requirement_control_point rcp ON rcp.requirement_id = source_req.id
                    JOIN question q ON q.control_point_id = rcp.control_point_id
                    JOIN question_answer qa ON qa.question_id = q.id
                    WHERE rm.target_requirement_id = :target_req_id
                    AND qa.audit_id = :audit_id
                    AND qa.status = 'submitted'
                    AND qa.response_value_bool = true
                    AND rm.validation_status = 'approved'
                    AND rm.semantic_similarity >= 0.75
                """), {
                    "target_req_id": req_row.id,
                    "audit_id": audit_id
                }).fetchone()
                
                if is_covered and is_covered.is_covered:
                    covered_via_mapping += 1
            
            total = len(target_requirements)
            
            return {
                'percentage': round((covered_via_mapping / total * 100), 2) if total > 0 else 0,
                'covered': covered_via_mapping,
                'total': total,
                'method': 'cross_mapped'
            }
            
        except Exception as e:
            logger.error(f"Error calculating cross-mapped coverage: {str(e)}")
            return {'percentage': 0, 'covered': 0, 'total': 0, 'method': 'cross_mapped'}
    
    def _calculate_hybrid_coverage(self, direct: Dict, cross: Dict) -> Dict:
        """
        Combinaison intelligente des méthodes directe et cross-référentiel
        
        Args:
            direct: Résultats de la couverture directe
            cross: Résultats de la couverture cross-référentiel
            
        Returns:
            Dict avec la meilleure couverture combinée
        """
        
        # Prendre le meilleur des deux mondes sans double comptage
        total = max(direct['total'], cross['total'])
        
        if total == 0:
            return {
                'percentage': 0,
                'covered': 0,
                'total': 0,
                'method': 'hybrid',
                'breakdown': {'direct': direct, 'cross_mapped': cross}
            }
        
        # Combinaison intelligente : direct + cross non redondant
        combined_coverage = max(direct['covered'], cross['covered'])
        
        return {
            'percentage': round((combined_coverage / total * 100), 2),
            'covered': combined_coverage,
            'total': total,
            'method': 'hybrid',
            'breakdown': {
                'direct': direct,
                'cross_mapped': cross
            }
        }
    
    def _store_coverage_results(self, audit_id: str, coverage_results: Dict):
        """
        Sauvegarder les résultats de couverture en base
        
        Args:
            audit_id: ID de l'audit
            coverage_results: Résultats de couverture par framework
        """
        
        try:
            for framework_code, coverage in coverage_results.items():
                # Insérer ou mettre à jour la couverture
                self.db.execute(text("""
                    INSERT INTO cross_referential_coverage 
                    (audit_id, framework_id, coverage_percentage, covered_requirements, 
                     total_requirements, calculation_method)
                    VALUES (:audit_id, :framework_id, :coverage_percentage, :covered_requirements,
                            :total_requirements, :calculation_method)
                    ON CONFLICT (audit_id, framework_id)
                    DO UPDATE SET
                        coverage_percentage = EXCLUDED.coverage_percentage,
                        covered_requirements = EXCLUDED.covered_requirements,
                        total_requirements = EXCLUDED.total_requirements,
                        calculation_method = EXCLUDED.calculation_method,
                        calculated_at = NOW()
                """), {
                    "audit_id": audit_id,
                    "framework_id": coverage['framework_id'],
                    "coverage_percentage": coverage['coverage_percentage'],
                    "covered_requirements": coverage['covered_requirements'],
                    "total_requirements": coverage['total_requirements'],
                    "calculation_method": coverage['calculation_method']
                })
            
            self.db.commit()
            
        except Exception as e:
            logger.error(f"Error storing coverage results: {str(e)}")
            self.db.rollback()
    
    def get_coverage_history(self, audit_id: str) -> List[Dict]:
        """
        Récupérer l'historique des calculs de couverture
        
        Args:
            audit_id: ID de l'audit
            
        Returns:
            Liste des calculs de couverture historiques
        """
        
        try:
            results = self.db.execute(text("""
                SELECT 
                    crc.calculated_at,
                    crc.coverage_percentage,
                    crc.calculation_method,
                    f.code as framework_code,
                    f.name as framework_name
                FROM cross_referential_coverage crc
                JOIN framework f ON f.id = crc.framework_id
                WHERE crc.audit_id = :audit_id
                ORDER BY crc.calculated_at DESC, f.code
            """), {"audit_id": audit_id}).fetchall()
            
            return [
                {
                    "calculated_at": row.calculated_at.isoformat(),
                    "coverage_percentage": float(row.coverage_percentage),
                    "calculation_method": row.calculation_method,
                    "framework_code": row.framework_code,
                    "framework_name": row.framework_name
                }
                for row in results
            ]
            
        except Exception as e:
            logger.error(f"Error retrieving coverage history: {str(e)}")
            return []
    
    def get_framework_comparison(self, audit_ids: List[str]) -> Dict:
        """
        Comparer la couverture entre plusieurs audits
        
        Args:
            audit_ids: Liste des IDs d'audit à comparer
            
        Returns:
            Dict avec comparaison des couvertures
        """
        
        try:
            comparison_data = {}
            
            for audit_id in audit_ids:
                coverage = self.calculate_multi_framework_coverage(audit_id)
                comparison_data[audit_id] = coverage
            
            return {
                "audits_compared": len(audit_ids),
                "frameworks_coverage": comparison_data,
                "comparison_summary": self._generate_comparison_summary(comparison_data)
            }
            
        except Exception as e:
            logger.error(f"Error generating framework comparison: {str(e)}")
            return {}
    
    def _generate_comparison_summary(self, comparison_data: Dict) -> Dict:
        """
        Générer un résumé de comparaison entre audits
        
        Args:
            comparison_data: Données de comparaison
            
        Returns:
            Dict avec résumé statistique
        """
        
        if not comparison_data:
            return {}
        
        # Extraire les frameworks communs
        all_frameworks = set()
        for audit_data in comparison_data.values():
            all_frameworks.update(audit_data.keys())
        
        summary = {}
        
        for framework in all_frameworks:
            percentages = []
            for audit_data in comparison_data.values():
                if framework in audit_data:
                    percentages.append(audit_data[framework]['coverage_percentage'])
            
            if percentages:
                summary[framework] = {
                    "min_coverage": min(percentages),
                    "max_coverage": max(percentages),
                    "avg_coverage": round(sum(percentages) / len(percentages), 2),
                    "audits_count": len(percentages)
                }
        
        return summary

# Fonctions helper pour l'utilisation externe
def calculate_audit_coverage(audit_id: str) -> Dict:
    """
    Fonction helper pour calculer la couverture d'un audit
    
    Args:
        audit_id: ID de l'audit
        
    Returns:
        Dict avec résultats de couverture
    """
    
    db = next(get_db())
    try:
        service = CrossReferentialCoverageService(db)
        return service.calculate_multi_framework_coverage(audit_id)
    finally:
        db.close()

def get_coverage_summary(audit_id: str) -> Dict:
    """
    Fonction helper pour obtenir un résumé de couverture
    
    Args:
        audit_id: ID de l'audit
        
    Returns:
        Dict avec résumé de couverture
    """
    
    coverage_data = calculate_audit_coverage(audit_id)
    
    if not coverage_data:
        return {}
    
    percentages = [data['coverage_percentage'] for data in coverage_data.values()]
    
    return {
        "audit_id": audit_id,
        "total_frameworks": len(coverage_data),
        "average_coverage": round(sum(percentages) / len(percentages), 2) if percentages else 0,
        "best_framework": max(coverage_data.items(), key=lambda x: x[1]['coverage_percentage'])[0] if coverage_data else None,
        "worst_framework": min(coverage_data.items(), key=lambda x: x[1]['coverage_percentage'])[0] if coverage_data else None,
        "frameworks_above_80": len([p for p in percentages if p >= 80]),
        "frameworks_below_50": len([p for p in percentages if p < 50])
    }