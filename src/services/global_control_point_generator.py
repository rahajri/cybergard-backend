# backend/src/services/global_control_point_generator.py

import logging
from typing import List, Dict, Any, Optional, Tuple, Set
from sqlalchemy.orm import Session
from sqlalchemy import text
from uuid import uuid4

from ..config import settings
from ..models.audit import Framework, ControlPoint, Requirement

logger = logging.getLogger(__name__)

class GlobalControlPointGenerator:
    """
    Générateur global de points de contrôle avec logique anti-doublon
    et cross-référentiel. Maintient l'unicité des points de contrôle
    tout en gérant les mappings N-N avec les exigences.
    """
    def __init__(self, db_session: Session):
    self.db = db_session
    self.existing_control_points = []
    self.control_point_cache = {}
    logger.info("[GlobalControlPointGenerator] Initialisé avec session DB")
    
    def __init__(self, db_session: Session):
        self.db = db_session
        self.existing_control_points = []
        self.control_point_cache = {}

    async def initialize_global_context(self):
        """Charge tous les points de contrôle existants pour éviter les doublons"""
        try:
            query = text("""
                SELECT cp.*, 
                       COUNT(rcp.requirement_id) as mapped_requirements_count
                FROM control_point cp
                LEFT JOIN requirement_control_point rcp ON rcp.control_point_id = cp.id
                WHERE cp.is_active = true
                GROUP BY cp.id
                ORDER BY cp.created_at
            """)
            
            result = self.db.execute(query)
            rows = result.fetchall()
            
            self.existing_control_points = []
            for row in rows:
                cp_data = {
                    "id": row.id,
                    "code": row.code,
                    "name": row.name,
                    "description": row.description,
                    "category": row.category,
                    "subcategory": row.subcategory,
                    "criticality_level": row.criticality_level,
                    "keywords": self._extract_keywords(row.name, row.description),
                    "mapped_requirements_count": row.mapped_requirements_count
                }
                self.existing_control_points.append(cp_data)
                
                # Cache pour recherche rapide
                if row.code:
                    self.control_point_cache[row.code.lower()] = cp_data
                    
            logger.info(f"Contexte global initialisé: {len(self.existing_control_points)} points de contrôle existants")
            
        except Exception as e:
            logger.error(f"Erreur initialisation contexte global: {e}")
            self.existing_control_points = []

    def _extract_keywords(self, name: str, description: str) -> Set[str]:
        """Extrait les mots-clés d'un point de contrôle pour la détection de doublons"""
        text = f"{name or ''} {description or ''}".lower()
        # Mots-clés techniques importants
        keywords = set()
        important_terms = [
            'mfa', 'authentification', 'sauvegarde', 'backup', 'logging', 'monitoring',
            'firewall', 'antivirus', 'chiffrement', 'encryption', 'formation', 'training',
            'incident', 'vulnerabilité', 'patch', 'access', 'accès', 'réseau', 'network',
            'données', 'data', 'privacy', 'confidentialité', 'intégrité', 'disponibilité'
        ]
        
        for term in important_terms:
            if term in text:
                keywords.add(term)
        
        return keywords

    async def check_for_existing_control_point(
        self, 
        proposed_cp: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Vérifie si un point de contrôle similaire existe déjà
        
        Args:
            proposed_cp: Données du point de contrôle proposé
            
        Returns:
            Point de contrôle existant si trouvé, None sinon
        """
        proposed_name = proposed_cp.get("name", "").lower()
        proposed_code = proposed_cp.get("code", "").lower()
        proposed_keywords = self._extract_keywords(
            proposed_cp.get("name", ""),
            proposed_cp.get("description", "")
        )
        
        # 1. Vérification par code exact
        if proposed_code and proposed_code in self.control_point_cache:
            logger.info(f"Point de contrôle existant trouvé par code: {proposed_code}")
            return self.control_point_cache[proposed_code]
        
        # 2. Vérification par similarité de nom (> 80%)
        for existing in self.existing_control_points:
            existing_name = existing["name"].lower()
            
            # Similarité simple par mots communs
            proposed_words = set(proposed_name.split())
            existing_words = set(existing_name.split())
            
            if proposed_words and existing_words:
                similarity = len(proposed_words & existing_words) / len(proposed_words | existing_words)
                if similarity > 0.8:
                    logger.info(f"Point de contrôle similaire trouvé par nom: {existing['name']} (similarité: {similarity:.2f})")
                    return existing
        
        # 3. Vérification par mots-clés techniques
        for existing in self.existing_control_points:
            existing_keywords = existing.get("keywords", set())
            
            # Si on a au moins 2 mots-clés techniques en commun
            common_keywords = proposed_keywords & existing_keywords
            if len(common_keywords) >= 2:
                logger.info(f"Point de contrôle similaire trouvé par mots-clés: {existing['name']} (mots communs: {common_keywords})")
                return existing
        
        return None

    async def generate_with_anti_duplicate_logic(
        self,
        framework_id: str,
        requirements: List[Requirement],
        generation_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Génère des points de contrôle en évitant les doublons
        et en réutilisant les points existants quand c'est approprié
        """
        try:
            # 1. Initialiser le contexte global
            await self.initialize_global_context()
            
            # 2. Analyser les exigences pour identifier les besoins
            required_controls = await self._analyze_requirements_for_controls(requirements)
            
            # 3. Pour chaque contrôle requis, vérifier s'il existe ou le créer
            final_control_points = []
            new_control_points = []
            reused_control_points = []
            
            for required_control in required_controls:
                existing = await self.check_for_existing_control_point(required_control)
                
                if existing:
                    # Réutiliser le point existant
                    reused_control_points.append(existing)
                    final_control_points.append(existing)
                    
                    # Créer les nouveaux mappings avec les exigences de ce référentiel
                    await self._create_requirement_mappings(
                        existing["id"], 
                        required_control["mapped_requirements"],
                        "reuse_existing"
                    )
                    
                else:
                    # Créer un nouveau point de contrôle
                    new_cp = await self._create_new_control_point(required_control)
                    if new_cp:
                        new_control_points.append(new_cp)
                        final_control_points.append(new_cp)
                        
                        # Ajouter au cache pour éviter les doublons dans cette session
                        if new_cp.get("code"):
                            self.control_point_cache[new_cp["code"].lower()] = new_cp
            
            # 4. Construire le résultat
            result = {
                "success": True,
                "total_control_points": len(final_control_points),
                "new_created": len(new_control_points),
                "existing_reused": len(reused_control_points),
                "control_points": final_control_points,
                "cross_referential_mappings": await self._analyze_cross_referential_coverage(final_control_points),
                "framework": {
                    "id": framework_id,
                    "coverage_percentage": len(final_control_points) / len(requirements) * 100 if requirements else 0
                }
            }
            
            logger.info(f"Génération terminée: {len(new_control_points)} créés, {len(reused_control_points)} réutilisés")
            return result
            
        except Exception as e:
            logger.error(f"Erreur génération avec anti-doublon: {e}")
            raise e

    async def _analyze_requirements_for_controls(
        self, 
        requirements: List[Requirement]
    ) -> List[Dict[str, Any]]:
        """
        Analyse les exigences pour déterminer quels points de contrôle sont nécessaires
        Regroupe les exigences similaires sous les mêmes contrôles
        """
        # Regroupement par domaine et concepts
        control_groups = {}
        
        for req in requirements:
            # Identifier le domaine principal
            domain = req.domain or "General"
            
            # Identifier les concepts clés
            concepts = self._identify_control_concepts(req)
            
            for concept in concepts:
                group_key = f"{domain}_{concept}"
                
                if group_key not in control_groups:
                    control_groups[group_key] = {
                        "domain": domain,
                        "concept": concept,
                        "requirements": [],
                        "criticality_scores": []
                    }
                
                control_groups[group_key]["requirements"].append({
                    "id": req.id,
                    "official_code": req.official_code,
                    "title": req.title,
                    "risk_level": req.risk_level
                })
                
                # Score de criticité
                risk_score = {"low": 1, "medium": 2, "high": 3, "critical": 4}.get(req.risk_level, 2)
                control_groups[group_key]["criticality_scores"].append(risk_score)
        
        # Convertir en points de contrôle proposés
        proposed_controls = []
        for group_key, group_data in control_groups.items():
            if len(group_data["requirements"]) >= 1:  # Au moins 1 exigence
                avg_criticality = sum(group_data["criticality_scores"]) / len(group_data["criticality_scores"])
                criticality_level = {1: "LOW", 2: "MEDIUM", 3: "HIGH", 4: "CRITICAL"}[round(avg_criticality)]
                
                proposed_controls.append({
                    "code": f"CP_{group_data['domain'].upper()[:3]}_{group_data['concept'].upper()[:3]}",
                    "name": f"Contrôle {group_data['concept']} - {group_data['domain']}",
                    "description": f"Point de contrôle pour la gestion {group_data['concept'].lower()} dans le domaine {group_data['domain']}",
                    "category": group_data["domain"],
                    "subcategory": group_data["concept"],
                    "criticality_level": criticality_level,
                    "mapped_requirements": group_data["requirements"],
                    "estimated_effort_hours": len(group_data["requirements"]) * 2
                })
        
        return proposed_controls

    def _identify_control_concepts(self, requirement: Requirement) -> List[str]:
        """Identifie les concepts de contrôle dans une exigence"""
        text = f"{requirement.title} {requirement.requirement_text}".lower()
        
        concepts = []
        concept_keywords = {
            "authentification": ["authentification", "mfa", "2fa", "login", "mot de passe", "password"],
            "sauvegarde": ["sauvegarde", "backup", "restauration", "archivage"],
            "logging": ["log", "journalisation", "trace", "audit trail", "monitoring"],
            "accès": ["accès", "access", "autorisation", "permission", "privilège"],
            "chiffrement": ["chiffrement", "encryption", "cryptage", "clé", "certificat"],
            "réseau": ["réseau", "network", "firewall", "segmentation", "périmètre"],
            "formation": ["formation", "training", "sensibilisation", "awareness"],
            "incident": ["incident", "crise", "continuité", "recovery", "plan"],
            "vulnérabilité": ["vulnérabilité", "patch", "mise à jour", "correctif"],
            "données": ["données", "data", "information", "confidentialité", "privacy"]
        }
        
        for concept, keywords in concept_keywords.items():
            if any(keyword in text for keyword in keywords):
                concepts.append(concept)
        
        return concepts if concepts else ["general"]

    async def _create_new_control_point(self, control_data: Dict[str, Any]) -> Dict[str, Any]:
        """Crée un nouveau point de contrôle unique"""
        try:
            cp_id = str(uuid4())
            
            # Générer un code unique
            base_code = control_data["code"]
            final_code = await self._ensure_unique_code(base_code)
            
            cp_sql = text("""
                INSERT INTO control_point (
                    id, code, name, description, category, subcategory,
                    criticality_level, estimated_effort_hours, 
                    created_by, ai_confidence, is_active, created_at
                )
                VALUES (
                    :id, :code, :name, :description, :category, :subcategory,
                    :criticality, :effort, 'global_ai_generator', 0.85, true, NOW()
                )
            """)
            
            self.db.execute(cp_sql, {
                "id": cp_id,
                "code": final_code,
                "name": control_data["name"],
                "description": control_data["description"],
                "category": control_data["category"],
                "subcategory": control_data["subcategory"],
                "criticality": control_data["criticality_level"],
                "effort": control_data["estimated_effort_hours"]
            })
            
            # Créer les mappings avec les exigences
            await self._create_requirement_mappings(
                cp_id,
                control_data["mapped_requirements"],
                "ai_generation"
            )
            
            self.db.commit()
            
            new_cp = {
                "id": cp_id,
                "code": final_code,
                "name": control_data["name"],
                "description": control_data["description"],
                "category": control_data["category"],
                "subcategory": control_data["subcategory"],
                "criticality_level": control_data["criticality_level"]
            }
            
            logger.info(f"Nouveau point de contrôle créé: {final_code} - {control_data['name']}")
            return new_cp
            
        except Exception as e:
            logger.error(f"Erreur création point de contrôle: {e}")
            self.db.rollback()
            return None

    async def _ensure_unique_code(self, base_code: str) -> str:
        """S'assure que le code est unique"""
        counter = 1
        candidate_code = base_code
        
        while True:
            existing = self.db.execute(
                text("SELECT 1 FROM control_point WHERE code = :code"),
                {"code": candidate_code}
            ).first()
            
            if not existing:
                return candidate_code
            
            counter += 1
            candidate_code = f"{base_code}_{counter:03d}"
            
            if counter > 999:  # Sécurité
                candidate_code = f"{base_code}_{uuid4().hex[:8]}"
                break
        
        return candidate_code

    async def _create_requirement_mappings(
        self,
        control_point_id: str,
        requirements: List[Dict[str, Any]],
        method: str
    ):
        """Crée les mappings exigence-point de contrôle"""
        for req in requirements:
            mapping_sql = text("""
                INSERT INTO requirement_control_point (
                    id, requirement_id, control_point_id, confidence_score,
                    mapping_method, created_by, created_at
                )
                VALUES (:id, :req_id, :cp_id, :confidence, :method, 'global_generator', NOW())
                ON CONFLICT (requirement_id, control_point_id) DO NOTHING
            """)
            
            self.db.execute(mapping_sql, {
                "id": str(uuid4()),
                "req_id": req["id"],
                "cp_id": control_point_id,
                "confidence": 0.85,
                "method": method
            })

    async def _analyze_cross_referential_coverage(
        self, 
        control_points: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Analyse la couverture cross-référentielle"""
        try:
            # Récupérer les statistiques de couverture
            coverage_sql = text("""
                SELECT 
                    f.name as framework_name,
                    COUNT(DISTINCT r.id) as total_requirements,
                    COUNT(DISTINCT rcp.requirement_id) as covered_requirements
                FROM framework f
                LEFT JOIN requirement r ON r.framework_id = f.id
                LEFT JOIN requirement_control_point rcp ON rcp.requirement_id = r.id
                WHERE f.is_active = true
                GROUP BY f.id, f.name
            """)
            
            result = self.db.execute(coverage_sql)
            coverage_stats = {}
            
            for row in result:
                coverage_percentage = (row.covered_requirements / row.total_requirements * 100) if row.total_requirements > 0 else 0
                coverage_stats[row.framework_name] = {
                    "total_requirements": row.total_requirements,
                    "covered_requirements": row.covered_requirements,
                    "coverage_percentage": coverage_percentage
                }
            
            return coverage_stats
            
        except Exception as e:
            logger.error(f"Erreur analyse cross-référentielle: {e}")
            return {}


# Factory function
def create_global_control_point_generator(db_session: Session) -> GlobalControlPointGenerator:
    """Crée une instance du générateur global"""
    return GlobalControlPointGenerator(db_session)