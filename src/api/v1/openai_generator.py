# backend/src/api/v1/openai_generator.py
"""
Générateur de points de contrôle via DeepSeek (Ollama) + fallback algorithmique
Version corrigée avec :
- Imports fixes (chemins relatifs corrects)
- Prompts optimisés pour générer plus de PC
- Gestion d'erreurs robuste
- Parsing JSON amélioré
- Timeouts adaptés aux gros référentiels
"""

import asyncio
import json
import logging
import re
from typing import List, Dict, Any, Optional
from datetime import datetime
import httpx
from uuid import uuid4
import asyncio

# CORRECTION CRITIQUE : Imports relatifs corrects
from ...config import settings
from ...models.audit import Requirement, Framework, ControlPoint
from ...schemas.control_point import (
    ControlPointGenerationRequest,
    GeneratedControlPoint,
    RequirementInfo,
    CriticalityLevel,
    ControlPointGenerationResult,
)

logger = logging.getLogger(__name__)



# LIGNE 42-50 : Remplacer UNIQUEMENT le __init__
class DeepSeekControlPointGenerator:
    def __init__(self):
        """Initialise le générateur avec la config depuis settings"""
        from src.config import settings
        
        # ✅ CORRECTION : Forcer le bon port
        self.ollama_url = "http://localhost:11434"  # ✅ PORT CORRIGÉ ICI
        self.model = "deepseek-v3.1:671b-cloud"
        
        logger.info(f"[PCGen] 🔧 Ollama URL: {self.ollama_url}")
        logger.info(f"[PCGen] 🔧 Modèle: {self.model}")
        
        # ✅ Paramètres par défaut (sans dépendance à settings.get_model_config)
        self.ai_enabled = getattr(settings, 'ai_generation_enabled', True)
        self.batch_size = 10
        self.num_predict = 4096
        self.num_ctx = 16384
        self.temperature = 0.05
        self.top_p = 0.9
        self.repeat_penalty = 1.1
        self.timeout = getattr(settings, 'ai_timeout_seconds', 600)
        self.max_retries = getattr(settings, 'ai_max_retries', 3)
        
        logger.info(f"[PCGen] 🔧 Batch size: {self.batch_size}")
        logger.info(f"[PCGen] 🔧 Context: {self.num_ctx} tokens")
        logger.info(f"[PCGen] 🔧 Max output: {self.num_predict} tokens")
        
        # Initialisation du client HTTP
        self._client = None
        
        # Cumul des résultats
        self._result: Dict[str, Any] = {
            "control_points": [],
            "mappings": [],
            "true_uncovered_requirement_ids": [],
        }


    # Chercher la méthode generate_control_points_from_requirements (ligne ~100-120)

    async def generate_control_points_from_requirements(
        self,
        requirements: List[Dict[str, Any]],
        framework: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Génère des points de contrôle depuis une liste d'exigences.
        
        Args:
            requirements: Liste d'exigences normalisées
            framework: Référentiel (optionnel)
            
        Returns:
            Dictionnaire avec les points de contrôle générés
        """
        try:
            logger.info(f"🔄 Génération PC pour {len(requirements)} exigences")
            
            # ❌ SUPPRIMER CETTE LIGNE (ligne 112)
            # svc = PCGenService(db_session=self.db)
            
            # ✅ REMPLACER PAR : Utiliser directement le générateur (self)
            # self EST DÉJÀ une instance de DeepSeekControlPointGenerator
            
            # Normaliser les exigences
            norm_reqs = []
            for req in requirements:
                if isinstance(req, dict):
                    norm_reqs.append({
                        "code": req.get("code", ""),
                        "exigence": req.get("exigence", req.get("text", "")),
                        "framework": req.get("framework", "ISO27001")
                    })
            
            # ✅ Appeler la méthode generate_from_framework directement
            result = await self.generate_from_framework(
                framework=framework or {"name": "ISO27001"},
                requirements=norm_reqs
            )
            
            logger.info(f"✅ {len(result.get('points_de_controle', []))} PC générés")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Erreur génération PC: {e}", exc_info=True)
            raise

    async def _call_deepseek_with_retry(
        self, prompt: str, num_predict: int, attempt: int = 1
    ) -> str:
        """
        Appelle l'API Ollama/DeepSeek avec retry automatique.
        """
        if not self.ollama_url:
            raise RuntimeError("ollama_url non configuré")
        
        # ✅ URL correcte pour /api/chat
        url = f"{self.ollama_url}/api/chat"
        
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "Tu es un expert en cybersécurité et en normes ISO 27001/27002."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "stream": False,
            "options": {
                "num_predict": num_predict,
                "num_ctx": self.num_ctx,
                "temperature": self.temperature,
                "top_p": self.top_p,
                "repeat_penalty": self.repeat_penalty,
            },
        }
        
        logger.debug(f"[PCGen] 📤 Appel Ollama: {url}")
        logger.debug(f"[PCGen] 📤 Modèle: {self.model}")
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                
                data = response.json()
                
                # ✅ Extraire la réponse (format /api/chat)
                if "message" in data and "content" in data["message"]:
                    return data["message"]["content"]
                elif "response" in data:
                    # Format /api/generate (fallback)
                    return data["response"]
                else:
                    logger.error(f"[PCGen] Format de réponse inattendu: {data}")
                    return ""
        
        except httpx.HTTPStatusError as e:
            logger.error(f"[PCGen] ❌ Ollama HTTP error: {e}")
            logger.error(f"[PCGen] ❌ URL: {url}")
            logger.error(f"[PCGen] ❌ Modèle: {self.model}")
            
            if attempt < self.max_retries:
                wait = 2 ** attempt
                logger.warning(f"[PCGen] ⏳ Retry {attempt}/{self.max_retries} dans {wait}s...")
                await asyncio.sleep(wait)
                return await self._call_deepseek_with_retry(prompt, num_predict, attempt + 1)
            else:
                raise RuntimeError(f"Échec DeepSeek après {self.max_retries} tentatives: {e}")
        
        except Exception as e:
            logger.error(f"[PCGen] Erreur appel DeepSeek: {e}")
            raise RuntimeError(f"Erreur DeepSeek: {e}")

    def _build_optimized_prompt(
        self, framework, requirements: list, existing_cps: list, config: dict
    ) -> str:
        """Prompt avec RÉUTILISATION en priorité absolue"""
        
        def _short(txt: str, n: int = 400):
            if not txt:
                return ""
            t = str(txt).strip().replace("\n", " ")
            return (t[:n] + "...") if len(t) > n else t

        req_summaries = [{
            "id": r.get("id"),
            "code": r.get("official_code") or "",
            "title": r.get("title") or "",
            "text": _short(r.get("requirement_text"), 400),
            "domain": r.get("domain") or "",
            "subdomain": r.get("subdomain") or "",
        } for r in requirements[:150]]

        existing_summaries = [{
            "id": e.get("id"),
            "code": e.get("code"),
            "name": e.get("name"),
            "desc": _short(e.get("description"), 300),
            "category": e.get("category") or "",
        } for e in (existing_cps or [])[:200]]

        min_conf = float((config or {}).get("min_confidence", 0.7))
        fw_code = getattr(framework, "code", "") if framework else ""
        fw_name = getattr(framework, "name", "") if framework else ""

        # Extraire les IDs pour validation
        all_req_ids = [r.get("id") for r in req_summaries if r.get("id")]

        return f"""Expert cybersécurité français : génère des points de contrôle depuis des exigences.

🔴 RÈGLE ABSOLUE : Les {len(req_summaries)} exigences ci-dessous DOIVENT TOUTES apparaître dans mapped_requirements.

IDS À MAPPER OBLIGATOIREMENT (vérifiez que TOUS ces IDs apparaissent) :
{json.dumps(all_req_ids[:50], ensure_ascii=False)}
{'... (liste complète fournie)' if len(all_req_ids) > 50 else ''}

EXIGENCES À TRAITER ({len(req_summaries)}) :
{json.dumps(req_summaries, ensure_ascii=False, indent=1)[:8000]}

PC EXISTANTS ({len(existing_summaries)}) :
{json.dumps(existing_summaries, ensure_ascii=False, indent=1)[:6000]}

FORMAT JSON ATTENDU :
{{
  "control_points": [
    {{
      "code": "DOMAIN.CTRL.001",
      "name": "Nom descriptif du contrôle",
      "description": "...",
      "category": "Domaine",
      "subcategory": "Sous-domaine",
      "criticality": "MEDIUM",
      "estimated_effort_hours": 8,
      "ai_confidence": 0.8,
      "mapped_requirements": ["id1", "id2", "id3"]  // MIN 1 ID, TOUS LES IDS DOIVENT APPARAITRE
    }}
  ],
  "validation": {{
    "total_input": {len(req_summaries)},
    "total_mapped": <nombre d'IDs uniques mappés>,
    "unmapped_ids": []  // DOIT ÊTRE VIDE
  }}
}}

VÉRIFICATION FINALE OBLIGATOIRE :
1. Compter tous les IDs uniques dans mapped_requirements
2. Si < {len(req_summaries)} → RECOMMENCER
3. validation.unmapped_ids DOIT être []

Référentiel : {fw_code} - {fw_name}

JSON UNIQUEMENT :""".strip()

    def _parse_deepseek_response(
        self, response_content: str, requirements: List[Requirement]
    ) -> List[GeneratedControlPoint]:
        """Parse robuste avec fallback regex"""
        try:
            cleaned = self._clean_json_response(response_content)
            parsed = json.loads(cleaned)

            if "control_points" not in parsed:
                raise ValueError("Clé 'control_points' manquante")

            control_points: List[GeneratedControlPoint] = []
            for cp_data in parsed["control_points"]:
                try:
                    mreqs = cp_data.get("mapped_requirements") or []
                    normalized_mreqs = []
                    for m in mreqs:
                        rid = m.get("id") if isinstance(m, dict) else m
                        normalized_mreqs.append(RequirementInfo(
                            id=str(rid),
                            official_code=None,
                            title=None,
                            requirement_text=None,
                            domain=cp_data.get("category", "") or "",
                            subdomain=cp_data.get("subcategory", "") or "",
                            confidence_score=float(cp_data.get("ai_confidence", 0.75)),
                        ).dict())

                    cp_data["mapped_requirements"] = normalized_mreqs
                    cp_data["id"] = cp_data.get("id") or str(uuid4())
                    cp_data.setdefault("ai_confidence", 0.75)
                    cp_data.setdefault("estimated_effort_hours", 8)
                    cp_data.setdefault("criticality", "MEDIUM")
                    cp_data.setdefault("status", "approved")
                    cp_data.setdefault("category", "")

                    control_point = GeneratedControlPoint(**cp_data)
                    setattr(control_point, "existing_control_point_id", cp_data.get("existing_control_point_id"))
                    control_points.append(control_point)
                    
                except Exception as e:
                    logger.warning(f"PC invalide ignoré : {e}")
                    continue

            logger.info(f"✅ {len(control_points)} PC parsés")
            return control_points

        except json.JSONDecodeError as e:
            logger.error(f"JSON invalide : {e}")
            logger.error(f"Réponse brute : {response_content[:500]}")
            raise Exception("Réponse DeepSeek non parseable")

    def _clean_json_response(self, content: str) -> str:
        """Nettoyage robuste avec fallback regex"""
        c = (content or "").strip()

        # Retirer markdown
        if "```json" in c:
            try:
                c = c.split("```json", 1)[1].split("```", 1)[0]
            except:
                pass
        elif "```" in c:
            parts = c.split("```")
            for part in parts:
                part = part.strip()
                if part.startswith("{") and part.endswith("}"):
                    c = part
                    break

        # Extraire accolades
        if not c.startswith("{"):
            start = c.find("{")
            if start != -1:
                c = c[start:]
        if not c.endswith("}"):
            end = c.rfind("}")
            if end != -1:
                c = c[:end + 1]

        # Fallback regex si toujours invalide
        if not c.strip().startswith("{"):
            match = re.search(r'\{[\s\S]*"control_points"[\s\S]*\}', content)
            if match:
                c = match.group(0)

        return c.strip()

    async def _fallback_via_existing_api(self, framework: Optional[Framework], cfg: Dict[str, Any]) -> Dict[str, Any]:
        """Fallback algorithmique amélioré"""
        if not framework:
            return {"control_points": [], "total_generated": 0}

        from ...models.audit import Domain
        
        requirements = self.db.query(Requirement).filter_by(framework_id=framework.id).all()
        if not requirements:
            return {"control_points": [], "total_generated": 0}

        logger.info(f"🔧 Fallback algorithmique : {len(requirements)} exigences")

        # Regrouper par domain_id avec jointure
        groups: Dict[str, List[Requirement]] = {}
        for req in requirements:
            if req.domain_id:
                domain_obj = self.db.query(Domain).filter_by(id=req.domain_id).first()
                key = domain_obj.name if domain_obj else "Général"
            else:
                key = "Général"
            
            groups.setdefault(key, []).append(req)

        cps = []
        counter = 1

        logger.info(f"📊 Groupes créés : {len(groups)} groupes")

        for group_name, reqs in groups.items():
            logger.info(f"  - Groupe '{group_name}' : {len(reqs)} exigences")
            
            for i in range(0, len(reqs), 10):
                sub_reqs = reqs[i:i+10]
                
                code = f"{group_name[:3].upper()}.CTRL.{counter:03d}"
                mr_ids = [str(r.id) for r in sub_reqs]
                
                cps.append({
                    "id": str(uuid4()),
                    "code": code,
                    "name": f"Contrôles {group_name}",
                    "description": f"Consolidation de {len(sub_reqs)} exigences du groupe {group_name}",
                    "category": group_name,
                    "subcategory": "",
                    "control_family": group_name,
                    "criticality": "MEDIUM",
                    "estimated_effort_hours": min(len(sub_reqs) * 4, 80),
                    "ai_confidence": 0.7,
                    "ai_explanation": f"Fallback algorithmique - {len(sub_reqs)} exigences",
                    "mapped_requirements": mr_ids,
                    "status": "approved",
                })
                
                logger.info(f"    -> PC {code} créé avec {len(mr_ids)} exigences")
                counter += 1

        logger.info(f"✅ Fallback : {len(cps)} PC générés")
        return {"control_points": cps, "total_generated": len(cps)}

    # API historique conservée pour compatibilité
    async def generate_control_points(self, request: ControlPointGenerationRequest) -> ControlPointGenerationResult:
        """Point d'entrée historique Pydantic"""
        start_time = datetime.now()
        try:
            requirements = self.db.query(Requirement).filter_by(framework_id=request.framework_id).all()
            if not requirements:
                return ControlPointGenerationResult(
                    total_generated=0, control_points=[], processing_time=0.0,
                    framework_coverage=0.0, success=False,
                    error_message="Aucune exigence trouvée"
                )

            if getattr(settings, 'ai_generation_enabled', False) and self.ollama_url:
                try:
                    framework = self.db.query(Framework).filter_by(id=request.framework_id).first()
                    result = await self.generate_control_points_from_requirements(
                        requirements=requirements, framework=framework,
                        config={"max_control_points": request.max_control_points,
                               "min_confidence": request.min_confidence}
                    )
                    pt = (datetime.now() - start_time).total_seconds()
                    return self._build_success_result(result["control_points"], requirements, pt, "deepseek")
                except Exception as e:
                    logger.warning(f"DeepSeek échoué : {e}")

            framework = self.db.query(Framework).filter_by(id=request.framework_id).first()
            result = await self._fallback_via_existing_api(framework, {})
            pt = (datetime.now() - start_time).total_seconds()
            return self._build_success_result(result["control_points"], requirements, pt, "algorithmic")

        except Exception as e:
            pt = (datetime.now() - start_time).total_seconds()
            return ControlPointGenerationResult(
                total_generated=0, control_points=[], processing_time=pt,
                framework_coverage=0.0, success=False, error_message=str(e)
            )

    def _build_success_result(self, control_points, requirements, processing_time, method):
        total_reqs = len(requirements)
        mapped = sum(len(cp.get("mapped_requirements", [])) if isinstance(cp, dict) else len(cp.mapped_requirements) for cp in control_points)
        coverage = (mapped / total_reqs * 100) if total_reqs > 0 else 0
        
        return ControlPointGenerationResult(
            total_generated=len(control_points),
            control_points=control_points,
            processing_time=processing_time,
            framework_coverage=coverage,
            success=True,
            generation_method=method,
        )


# Diagnostics
def validate_ai_integration():
    try:
        if getattr(settings, 'ai_generation_enabled', False) and getattr(settings, 'ollama_url', None):
            print(f"✅ DeepSeek configuré : {settings.ollama_url}")
            print(f"📊 Modèle : {getattr(settings, 'ollama_model', 'N/A')}")
        else:
            print("⚠️ Mode algorithmique uniquement")
    except Exception as e:
        print(f"❌ Erreur validation : {e}")


async def test_ai_connection() -> Dict[str, Any]:
    try:
        if not getattr(settings, 'ai_generation_enabled', False):
            return {"status": "disabled", "message": "IA désactivée"}

        ollama_url = getattr(settings, 'ollama_url', None)
        if not ollama_url:
            return {"status": "not_configured", "message": "URL Ollama manquante"}

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{ollama_url}/api/chat",
                json={"model": settings.ollama_model, "messages": [{"role": "user", "content": "Test"}], "stream": False},
            )

        if resp.status_code == 200:
            return {"status": "healthy", "provider": "deepseek", "model": settings.ollama_model, "url": ollama_url}

        return {"status": "connection_failed", "message": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}