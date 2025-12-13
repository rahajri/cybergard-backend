"""
Service IA pour le module EBIOS RM

Génération assistée par IA pour chaque atelier EBIOS:
- AT1: Cadrage (valeurs métier, biens supports, événements redoutés)
- AT2: Sources de risques
- AT3: Scénarios stratégiques
- AT4: Scénarios opérationnels
- AT5: Risques et traitement

Utilise DeepSeek via l'API existante avec cache Redis.

Versions supportees:
- 'legacy': Comportement original (retrocompatibilite)
- 'ebios_rm_v2': Pipeline conforme ANSSI avec referentiels
"""

import json
import logging
import os
import re
from datetime import datetime
from typing import Dict, Any, List, Optional
from uuid import UUID

import httpx
from sqlalchemy.orm import Session
from sqlalchemy import text

from src.utils.redis_manager import redis_manager

logger = logging.getLogger(__name__)

# Configuration Ollama
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "glm-4.6:cloud")


class EbiosAIService:
    """
    Service de génération IA pour EBIOS RM.

    Génère du contenu structuré pour chaque atelier selon la méthodologie ANSSI.
    """

    # ==========================================================================
    # PROMPTS SYSTÈMES PAR ATELIER
    # ==========================================================================

    SYSTEM_PROMPT_AT1 = """
Tu es un expert en analyse de risques cybersécurité selon la méthodologie EBIOS Risk Manager de l'ANSSI.
Tu assistes l'utilisateur dans l'Atelier 1 : Cadrage et socle de sécurité.

Ton rôle est de :
1. Identifier les VALEURS MÉTIER essentielles de l'organisation
2. Identifier les BIENS SUPPORTS (systèmes, applications, données) qui soutiennent ces valeurs
3. Identifier les ÉVÉNEMENTS REDOUTÉS (impacts négatifs sur les valeurs métier)

Réponds UNIQUEMENT en JSON valide avec la structure suivante :
{
  "business_values": [
    {
      "label": "Nom de la valeur métier",
      "description": "Description détaillée",
      "criticality": 1-4 (1=faible, 4=critique)
    }
  ],
  "assets": [
    {
      "label": "Nom du bien support",
      "type": "Serveur|Application|Réseau|Données|Personnel|...",
      "description": "Description",
      "criticality": 1-4,
      "linked_business_value": "Nom de la valeur métier liée"
    }
  ],
  "feared_events": [
    {
      "label": "Description de l'événement redouté",
      "dimension": "CONFIDENTIALITY|INTEGRITY|AVAILABILITY",
      "severity": 1-4 (gravité de l'impact),
      "justification": "Justification du niveau de gravité",
      "linked_business_value": "Nom de la valeur métier impactée",
      "linked_asset": "Nom du bien support concerné"
    }
  ]
}
"""

    SYSTEM_PROMPT_AT2 = """
Tu es un expert en analyse de risques cybersécurité selon la méthodologie EBIOS Risk Manager de l'ANSSI.
Tu assistes l'utilisateur dans l'Atelier 2 : Sources de risques.

Ton rôle est d'identifier les SOURCES DE RISQUES potentielles et leurs OBJECTIFS.

Catégories typiques de sources de risques :
- Cybercriminel organisé
- État-nation
- Hacktiviste
- Employé malveillant
- Prestataire négligent
- Concurrent
- Acteur opportuniste

Réponds UNIQUEMENT en JSON valide :
{
  "risk_sources": [
    {
      "label": "Nom de la source de risque",
      "description": "Description et motivation",
      "relevance": 1-4 (pertinence pour cette organisation),
      "justification": "Pourquoi cette source est pertinente",
      "is_selected": true,
      "objectives": [
        {
          "label": "Objectif visé par cette source",
          "description": "Description de l'objectif"
        }
      ]
    }
  ]
}
"""

    SYSTEM_PROMPT_AT3 = """
Tu es un expert en analyse de risques cybersécurité selon la méthodologie EBIOS Risk Manager de l'ANSSI.
Tu assistes l'utilisateur dans l'Atelier 3 : Scénarios stratégiques.

Ton rôle est de construire des SCÉNARIOS STRATÉGIQUES qui décrivent :
- Comment une source de risque pourrait atteindre ses objectifs
- Le chemin d'attaque à haut niveau (parties prenantes de l'écosystème traversées)
- La gravité et vraisemblance du scénario

Réponds UNIQUEMENT en JSON valide :
{
  "strategic_scenarios": [
    {
      "code": "SS01",
      "title": "Titre du scénario stratégique",
      "description": "Description narrative du scénario",
      "attack_path": {
        "steps": ["Étape 1", "Étape 2", "..."],
        "stakeholders_involved": ["Partie prenante 1", "..."]
      },
      "linked_feared_event": "Label de l'événement redouté ciblé",
      "linked_risk_source": "Label de la source de risque",
      "severity": 1-4,
      "likelihood_raw": 1-4,
      "justification": "Justification des scores"
    }
  ]
}
"""

    SYSTEM_PROMPT_AT4 = """
Tu es un expert en analyse de risques cybersécurité selon la méthodologie EBIOS Risk Manager de l'ANSSI.
Tu assistes l'utilisateur dans l'Atelier 4 : Scénarios opérationnels.

Ton rôle est de détailler les SCÉNARIOS OPÉRATIONNELS :
- Séquences techniques d'attaque
- Techniques MITRE ATT&CK utilisées
- Évaluation de la vraisemblance technique

Réponds UNIQUEMENT en JSON valide :
{
  "operational_scenarios": [
    {
      "code": "SO01",
      "title": "Titre du scénario opérationnel",
      "description": "Description technique",
      "linked_strategic_scenario": "Code du scénario stratégique (ex: SS01)",
      "likelihood": 1-4,
      "justification": "Justification technique de la vraisemblance",
      "steps": [
        {
          "order": 1,
          "action": "Action technique",
          "technique": "T1566 - Phishing (exemple MITRE ATT&CK)",
          "description": "Description détaillée"
        }
      ]
    }
  ]
}
"""

    SYSTEM_PROMPT_AT5 = """
Tu es un expert en analyse de risques cybersécurité selon la méthodologie EBIOS Risk Manager de l'ANSSI.
Tu assistes l'utilisateur dans l'Atelier 5 : Traitement des risques.

Ton rôle est de :
1. Synthétiser les RISQUES à partir des scénarios
2. Calculer les scores (gravité × vraisemblance, max 16)
3. Proposer des stratégies de traitement

Niveaux de criticité :
- 1-4 : Faible (vert)
- 5-8 : Modéré (jaune)
- 9-12 : Important (orange)
- 13-16 : Critique (rouge)

Réponds UNIQUEMENT en JSON valide :
{
  "risks": [
    {
      "code": "R01",
      "label": "Libellé du risque",
      "description": "Description complète",
      "severity": 1-4,
      "likelihood": 1-4,
      "justification": "Justification des scores",
      "linked_strategic_scenario": "SS01",
      "linked_operational_scenario": "SO01",
      "linked_feared_event": "Label de l'événement redouté",
      "treatment_strategy": "REDUCE|ACCEPT|TRANSFER|AVOID",
      "treatment_recommendation": "Recommandation de traitement"
    }
  ]
}
"""

    SYSTEM_PROMPT_ACTIONS = """
Tu es un expert en cybersécurité. Génère des actions de traitement des risques.

Pour chaque risque fourni, propose des actions concrètes et mesurables.

Réponds UNIQUEMENT en JSON valide :
{
  "actions": [
    {
      "risk_code": "R01",
      "title": "Titre de l'action",
      "description": "Description détaillée de l'action",
      "priority": "HIGH|MEDIUM|LOW",
      "category": "TECHNIQUE|ORGANISATIONNEL|HUMAIN",
      "expected_impact": "Impact attendu sur le risque"
    }
  ]
}
"""

    # ==========================================================================
    # MÉTHODES DE GÉNÉRATION
    # ==========================================================================

    @staticmethod
    async def generate_at1(
        context: Dict[str, Any],
        regenerate: bool = False
    ) -> Dict[str, Any]:
        """
        Génère le contenu de l'Atelier 1 (Cadrage).

        Args:
            context: Contexte du projet (description, périmètre, secteur...)
            regenerate: Force la régénération même si du contenu existe

        Returns:
            Dict avec business_values, assets, feared_events
        """
        user_prompt = f"""
Analyse le contexte suivant et génère les éléments de l'Atelier 1 EBIOS RM.

CONTEXTE DU PROJET :
- Description : {context.get('description', 'Non fournie')}
- Secteur d'activité : {context.get('sector', 'Non spécifié')}
- Taille de l'organisation : {context.get('org_size', 'Non spécifiée')}
- Périmètre : {context.get('scope', 'Non défini')}

INFORMATIONS COMPLÉMENTAIRES :
{context.get('additional_info', 'Aucune')}

Génère au minimum :
- 3 valeurs métier essentielles
- 5 biens supports critiques
- 5 événements redoutés majeurs

Adapte ta réponse au contexte spécifique de cette organisation.
"""

        return await EbiosAIService._call_ai(
            system_prompt=EbiosAIService.SYSTEM_PROMPT_AT1,
            user_prompt=user_prompt,
            cache_key=f"ebios_at1_{hash(str(context))}",
            regenerate=regenerate
        )

    @staticmethod
    async def generate_at2(
        context: Dict[str, Any],
        at1_data: Dict[str, Any],
        regenerate: bool = False
    ) -> Dict[str, Any]:
        """
        Génère le contenu de l'Atelier 2 (Sources de risques).

        Args:
            context: Contexte du projet
            at1_data: Données de l'Atelier 1 (valeurs, biens, événements)
            regenerate: Force la régénération

        Returns:
            Dict avec risk_sources et leurs objectives
        """
        user_prompt = f"""
Analyse le contexte et les éléments de l'Atelier 1 pour identifier les sources de risques.

CONTEXTE DU PROJET :
- Description : {context.get('description', 'Non fournie')}
- Secteur : {context.get('sector', 'Non spécifié')}

VALEURS MÉTIER IDENTIFIÉES :
{json.dumps(at1_data.get('business_values', []), indent=2, ensure_ascii=False)}

BIENS SUPPORTS CRITIQUES :
{json.dumps(at1_data.get('assets', []), indent=2, ensure_ascii=False)}

ÉVÉNEMENTS REDOUTÉS :
{json.dumps(at1_data.get('feared_events', []), indent=2, ensure_ascii=False)}

Génère au minimum 5 sources de risques pertinentes avec leurs objectifs.
Ordonne-les par pertinence décroissante.
"""

        return await EbiosAIService._call_ai(
            system_prompt=EbiosAIService.SYSTEM_PROMPT_AT2,
            user_prompt=user_prompt,
            cache_key=f"ebios_at2_{hash(str(context))}_{hash(str(at1_data))}",
            regenerate=regenerate
        )

    @staticmethod
    async def generate_at3(
        context: Dict[str, Any],
        at1_data: Dict[str, Any],
        at2_data: Dict[str, Any],
        regenerate: bool = False
    ) -> Dict[str, Any]:
        """
        Génère le contenu de l'Atelier 3 (Scénarios stratégiques).
        """
        user_prompt = f"""
Construis des scénarios stratégiques basés sur les ateliers précédents.

CONTEXTE :
{context.get('description', 'Non fourni')}

ÉVÉNEMENTS REDOUTÉS :
{json.dumps(at1_data.get('feared_events', []), indent=2, ensure_ascii=False)}

SOURCES DE RISQUES SÉLECTIONNÉES :
{json.dumps([s for s in at2_data.get('risk_sources', []) if s.get('is_selected', True)], indent=2, ensure_ascii=False)}

Génère au minimum 3 scénarios stratégiques réalistes.
Chaque scénario doit lier une source de risque à un événement redouté.
"""

        return await EbiosAIService._call_ai(
            system_prompt=EbiosAIService.SYSTEM_PROMPT_AT3,
            user_prompt=user_prompt,
            cache_key=f"ebios_at3_{hash(str(at1_data))}_{hash(str(at2_data))}",
            regenerate=regenerate
        )

    @staticmethod
    async def generate_at4(
        context: Dict[str, Any],
        at3_data: Dict[str, Any],
        regenerate: bool = False
    ) -> Dict[str, Any]:
        """
        Génère le contenu de l'Atelier 4 (Scénarios opérationnels).
        """
        user_prompt = f"""
Détaille les scénarios opérationnels pour chaque scénario stratégique.

SCÉNARIOS STRATÉGIQUES :
{json.dumps(at3_data.get('strategic_scenarios', []), indent=2, ensure_ascii=False)}

Pour chaque scénario stratégique, génère au moins un scénario opérationnel détaillé
avec les étapes techniques et les techniques MITRE ATT&CK associées.
"""

        return await EbiosAIService._call_ai(
            system_prompt=EbiosAIService.SYSTEM_PROMPT_AT4,
            user_prompt=user_prompt,
            cache_key=f"ebios_at4_{hash(str(at3_data))}",
            regenerate=regenerate
        )

    @staticmethod
    async def generate_at5(
        at1_data: Dict[str, Any],
        at3_data: Dict[str, Any],
        at4_data: Dict[str, Any],
        regenerate: bool = False
    ) -> Dict[str, Any]:
        """
        Génère les risques de l'Atelier 5.
        """
        user_prompt = f"""
Synthétise les risques à partir des scénarios.

ÉVÉNEMENTS REDOUTÉS :
{json.dumps(at1_data.get('feared_events', []), indent=2, ensure_ascii=False)}

SCÉNARIOS STRATÉGIQUES :
{json.dumps(at3_data.get('strategic_scenarios', []), indent=2, ensure_ascii=False)}

SCÉNARIOS OPÉRATIONNELS :
{json.dumps(at4_data.get('operational_scenarios', []), indent=2, ensure_ascii=False)}

Génère un risque pour chaque combinaison scénario stratégique / opérationnel.
Calcule le score = gravité × vraisemblance.
Propose une stratégie de traitement pour chaque risque.
"""

        return await EbiosAIService._call_ai(
            system_prompt=EbiosAIService.SYSTEM_PROMPT_AT5,
            user_prompt=user_prompt,
            cache_key=f"ebios_at5_{hash(str(at3_data))}_{hash(str(at4_data))}",
            regenerate=regenerate
        )

    @staticmethod
    async def generate_actions(
        risks: List[Dict[str, Any]],
        regenerate: bool = False
    ) -> Dict[str, Any]:
        """
        Génère des actions de traitement pour les risques.
        """
        user_prompt = f"""
Génère des actions de traitement pour les risques suivants :

RISQUES :
{json.dumps(risks, indent=2, ensure_ascii=False)}

Pour chaque risque, propose au moins une action concrète et réaliste.
Priorise les actions selon l'impact attendu sur le risque.
"""

        return await EbiosAIService._call_ai(
            system_prompt=EbiosAIService.SYSTEM_PROMPT_ACTIONS,
            user_prompt=user_prompt,
            cache_key=f"ebios_actions_{hash(str(risks))}",
            regenerate=regenerate
        )

    # ==========================================================================
    # MÉTHODE INTERNE D'APPEL IA
    # ==========================================================================

    @staticmethod
    async def _call_ai(
        system_prompt: str,
        user_prompt: str,
        cache_key: str,
        regenerate: bool = False
    ) -> Dict[str, Any]:
        """
        Appelle Ollama avec mise en cache.

        Args:
            system_prompt: Prompt système
            user_prompt: Prompt utilisateur
            cache_key: Clé de cache Redis
            regenerate: Force la régénération

        Returns:
            Dict parsé depuis la réponse JSON de l'IA
        """
        # Vérifier le cache
        if not regenerate and redis_manager.is_connected:
            cached = redis_manager.get(f"ebios:ai:{cache_key}")
            if cached:
                logger.info(f"✅ Cache HIT pour {cache_key}")
                try:
                    return json.loads(cached)
                except json.JSONDecodeError:
                    pass

        logger.info(f"🤖 Génération IA pour {cache_key}")
        logger.info(f"📡 Ollama URL: {OLLAMA_URL}, Model: {OLLAMA_MODEL}")

        try:
            # Combiner system_prompt et user_prompt pour Ollama /api/generate
            full_prompt = f"{system_prompt}\n\n{user_prompt}"

            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{OLLAMA_URL}/api/generate",
                    json={
                        "model": OLLAMA_MODEL,
                        "prompt": full_prompt,
                        "stream": False,
                        "options": {
                            "temperature": 0.3,
                            "num_ctx": 8192,
                            "num_predict": 4096
                        }
                    }
                )

                if response.status_code != 200:
                    logger.error(f"❌ Ollama error: {response.status_code} - {response.text}")
                    raise RuntimeError(f"Ollama error: {response.status_code}")

                data = response.json()
                ai_response = data.get("response", "")

                logger.info(f"✅ Ollama response received ({len(ai_response)} chars)")

            # Parser la réponse JSON
            result = EbiosAIService._parse_json_response(ai_response)

            # Mettre en cache
            if redis_manager.is_connected and result:
                redis_manager.set(
                    f"ebios:ai:{cache_key}",
                    json.dumps(result, ensure_ascii=False),
                    ttl=86400  # 24h
                )

            return result

        except httpx.TimeoutException:
            logger.error(f"❌ Ollama timeout")
            raise RuntimeError("Ollama timeout - la génération a pris trop de temps")

        except Exception as e:
            logger.error(f"❌ Erreur génération IA: {e}")
            raise

    @staticmethod
    def _parse_json_response(response: str) -> Dict[str, Any]:
        """
        Parse la réponse IA en JSON.
        Gère les cas où le JSON est entouré de markdown.
        """
        # Nettoyer la réponse
        text = response.strip()

        # Retirer les blocs de code markdown
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]

        if text.endswith("```"):
            text = text[:-3]

        text = text.strip()

        # Parser le JSON
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"❌ Erreur parsing JSON: {e}")
            logger.debug(f"Réponse brute: {text[:500]}")
            return {}

    # ==========================================================================
    # PIPELINE V2 - CONFORME ANSSI
    # ==========================================================================

    @staticmethod
    async def generate_at1_v2(
        db: Session,
        project_id: str,
        context: Dict[str, Any],
        regenerate: bool = False
    ) -> Dict[str, Any]:
        """
        Genere le contenu de l'Atelier 1 avec le pipeline v2 (conforme ANSSI).

        Cette methode :
        1. Charge les referentiels ANSSI depuis la base
        2. Genere le prompt enrichi
        3. Valide strictement la reponse JSON
        4. Journalise l'appel IA

        Args:
            db: Session SQLAlchemy
            project_id: UUID du projet EBIOS
            context: Contexte du projet (description, secteur, etc.)
            regenerate: Force la regeneration meme si cache existe

        Returns:
            Dict avec valeurs_metier, biens_supports, evenements_redoutes
        """
        from src.services.ebios_reference_service import EbiosReferenceService
        from src.prompts.ebios_rm_v2.at1_prompts import (
            build_at1_messages,
            validate_at1_response
        )

        logger.info(f"🚀 Generation AT1 v2 pour projet {project_id}")

        # 1. Charger les referentiels ANSSI
        ref_service = EbiosReferenceService(db)
        referentiels = ref_service.get_referentiels_for_at1()

        logger.info(f"📚 Referentiels charges - Guides: {len(referentiels.get('guides', '').split('---'))}")

        # 2. Construire les messages
        messages = build_at1_messages(
            referentiels=referentiels,
            organization_name=context.get("name", "Organisation"),
            organization_description=context.get("description", ""),
            sector=context.get("sector"),
            additional_context=context.get("additional_info")
        )

        # 3. Cache key pour cette generation
        cache_key = f"ebios_at1_v2_{project_id}_{hash(str(context))}"

        # Verifier le cache
        if not regenerate and redis_manager.is_connected:
            cached = redis_manager.get(f"ebios:ai:{cache_key}")
            if cached:
                logger.info(f"✅ Cache HIT pour AT1 v2")
                try:
                    return json.loads(cached)
                except json.JSONDecodeError:
                    pass

        # 4. Appel IA via Ollama
        start_time = datetime.utcnow()
        raw_response = ""

        try:
            # Combiner system et user prompt pour Ollama
            full_prompt = f"{messages[0]['content']}\n\n{messages[1]['content']}"

            logger.info(f"📡 Appel Ollama: {OLLAMA_URL}, Model: {OLLAMA_MODEL}")

            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{OLLAMA_URL}/api/generate",
                    json={
                        "model": OLLAMA_MODEL,
                        "prompt": full_prompt,
                        "stream": False,
                        "options": {
                            "temperature": 0.3,
                            "num_ctx": 8192,
                            "num_predict": 4096
                        }
                    }
                )

                if response.status_code != 200:
                    logger.error(f"❌ Ollama error: {response.status_code} - {response.text}")
                    return {
                        "success": False,
                        "data": None,
                        "errors": [f"Ollama error: {response.status_code}"],
                        "stats": {}
                    }

                data = response.json()
                raw_response = data.get("response", "")

                logger.info(f"✅ Ollama response received ({len(raw_response)} chars)")

            # 5. Valider la reponse
            validation_result = validate_at1_response(raw_response)

            if not validation_result["valid"]:
                logger.warning(f"⚠️ Validation AT1 v2 echouee: {validation_result['errors']}")
                # Journaliser l'echec
                await EbiosAIService._log_ai_generation(
                    db=db,
                    project_id=project_id,
                    atelier="AT1",
                    version="ebios_rm_v2",
                    prompt_system=messages[0]["content"][:2000],
                    prompt_user=messages[1]["content"],
                    raw_response=raw_response[:5000],
                    parsed_response=None,
                    success=False,
                    error_message="; ".join(validation_result["errors"]),
                    duration_ms=int((datetime.utcnow() - start_time).total_seconds() * 1000)
                )
                # Retourner quand meme les donnees partielles
                return {
                    "success": False,
                    "data": validation_result.get("data"),
                    "errors": validation_result["errors"],
                    "stats": validation_result.get("stats", {})
                }

            # 6. Succes - mettre en cache et journaliser
            result_data = validation_result["data"]

            if redis_manager.is_connected:
                redis_manager.set(
                    f"ebios:ai:{cache_key}",
                    json.dumps(result_data, ensure_ascii=False),
                    ttl=86400
                )

            await EbiosAIService._log_ai_generation(
                db=db,
                project_id=project_id,
                atelier="AT1",
                version="ebios_rm_v2",
                prompt_system=messages[0]["content"][:2000],
                prompt_user=messages[1]["content"],
                raw_response=raw_response[:5000],
                parsed_response=result_data,
                success=True,
                error_message=None,
                duration_ms=int((datetime.utcnow() - start_time).total_seconds() * 1000)
            )

            logger.info(f"✅ AT1 v2 genere avec succes: {validation_result['stats']}")

            return {
                "success": True,
                "data": result_data,
                "stats": validation_result["stats"]
            }

        except httpx.TimeoutException:
            logger.error(f"❌ Ollama timeout")
            return {
                "success": False,
                "data": None,
                "errors": ["Ollama timeout - la génération a pris trop de temps"],
                "stats": {}
            }

        except Exception as e:
            logger.error(f"❌ Erreur generation AT1 v2: {e}")

            await EbiosAIService._log_ai_generation(
                db=db,
                project_id=project_id,
                atelier="AT1",
                version="ebios_rm_v2",
                prompt_system=messages[0]["content"][:2000] if messages else "",
                prompt_user=messages[1]["content"] if messages else "",
                raw_response=raw_response[:5000] if raw_response else "",
                parsed_response=None,
                success=False,
                error_message=str(e),
                duration_ms=int((datetime.utcnow() - start_time).total_seconds() * 1000)
            )
            raise

    @staticmethod
    async def _log_ai_generation(
        db: Session,
        project_id: str,
        atelier: str,
        version: str,
        prompt_system: str,
        prompt_user: str,
        raw_response: str,
        parsed_response: Optional[Dict],
        success: bool,
        error_message: Optional[str],
        duration_ms: int
    ) -> None:
        """
        Journalise un appel de generation IA dans ai_generation_logs.

        Args:
            db: Session SQLAlchemy
            project_id: UUID du projet
            atelier: Code atelier (AT1, AT2, etc.)
            version: Version du pipeline (legacy, ebios_rm_v2)
            prompt_system: Prompt systeme (tronque si necessaire)
            prompt_user: Prompt utilisateur
            raw_response: Reponse brute de l'IA (tronquee si necessaire)
            parsed_response: Reponse parsee en JSON
            success: Succes de la generation
            error_message: Message d'erreur si echec
            duration_ms: Duree en millisecondes
        """
        try:
            query = text("""
                INSERT INTO ai_generation_logs
                (project_id, atelier, version, prompt_system, prompt_user,
                 raw_response, parsed_response, success, error_message,
                 duration_ms, created_at)
                VALUES
                (CAST(:project_id AS uuid), :atelier, :version, :prompt_system,
                 :prompt_user, :raw_response, :parsed_response::jsonb, :success,
                 :error_message, :duration_ms, :created_at)
            """)

            db.execute(query, {
                "project_id": project_id,
                "atelier": atelier,
                "version": version,
                "prompt_system": prompt_system,
                "prompt_user": prompt_user,
                "raw_response": raw_response,
                "parsed_response": json.dumps(parsed_response) if parsed_response else None,
                "success": success,
                "error_message": error_message,
                "duration_ms": duration_ms,
                "created_at": datetime.utcnow()
            })
            db.commit()

            logger.debug(f"📝 Log IA enregistre: {atelier} v{version} - {'OK' if success else 'FAIL'}")

        except Exception as e:
            logger.error(f"❌ Erreur journalisation IA: {e}")
            # Ne pas lever d'exception pour ne pas casser le flux principal

    # ==========================================================================
    # DISPATCHER SELON VERSION
    # ==========================================================================

    @staticmethod
    async def generate_at1_dispatch(
        db: Session,
        project_id: str,
        context: Dict[str, Any],
        regenerate: bool = False
    ) -> Dict[str, Any]:
        """
        Dispatcher pour AT1 - choisit le pipeline selon analysis_version du projet.

        Args:
            db: Session SQLAlchemy
            project_id: UUID du projet
            context: Contexte du projet
            regenerate: Force regeneration

        Returns:
            Resultat de generation selon le pipeline choisi
        """
        # Verifier la version du projet
        from src.services.ebios_reference_service import EbiosReferenceService

        ref_service = EbiosReferenceService(db)
        is_v2 = ref_service.is_ebios_rm_v2_enabled(project_id)

        if is_v2:
            logger.info(f"🔀 Dispatch AT1 vers pipeline v2 pour projet {project_id}")
            return await EbiosAIService.generate_at1_v2(
                db=db,
                project_id=project_id,
                context=context,
                regenerate=regenerate
            )
        else:
            logger.info(f"🔀 Dispatch AT1 vers pipeline legacy pour projet {project_id}")
            # Pipeline legacy - comportement original
            result = await EbiosAIService.generate_at1(
                context=context,
                regenerate=regenerate
            )
            return {"success": True, "data": result}

    # ==========================================================================
    # PIPELINE V2 - AT2 CONFORME ANSSI
    # ==========================================================================

    @staticmethod
    async def generate_at2_v2(
        db: Session,
        project_id: str,
        context: Dict[str, Any],
        at1_data: Optional[Dict[str, Any]] = None,
        regenerate: bool = False
    ) -> Dict[str, Any]:
        """
        Genere le contenu de l'Atelier 2 avec le pipeline v2 (conforme ANSSI).

        Cette methode :
        1. Charge les referentiels ANSSI (sources de risque, objectifs vises)
        2. Integre les donnees AT1 dans le prompt
        3. Genere le prompt enrichi
        4. Valide strictement la reponse JSON
        5. Journalise l'appel IA

        Args:
            db: Session SQLAlchemy
            project_id: UUID du projet EBIOS
            context: Contexte du projet (description, secteur, etc.)
            at1_data: Donnees de l'AT1 (valeurs metier, biens supports, ER)
            regenerate: Force la regeneration meme si cache existe

        Returns:
            Dict avec sources_risque
        """
        from src.services.ebios_reference_service import EbiosReferenceService
        from src.prompts.ebios_rm_v2.at2_prompts import (
            build_at2_messages,
            validate_at2_response
        )

        logger.info(f"🚀 Generation AT2 v2 pour projet {project_id}")

        # 1. Charger les referentiels ANSSI pour AT2
        ref_service = EbiosReferenceService(db)
        referentiels = ref_service.get_referentiels_for_at2()

        logger.info(f"📚 Referentiels AT2 charges - Sources: {len(referentiels.get('sources_risque', '').split(chr(10)))}")

        # 2. Construire les messages
        messages = build_at2_messages(
            referentiels=referentiels,
            organization_name=context.get("name", "Organisation"),
            organization_description=context.get("description", ""),
            sector=context.get("sector"),
            at1_data=at1_data,
            additional_context=context.get("additional_info")
        )

        # 3. Cache key pour cette generation
        at1_hash = hash(str(at1_data)) if at1_data else "no_at1"
        cache_key = f"ebios_at2_v2_{project_id}_{hash(str(context))}_{at1_hash}"

        # Verifier le cache
        if not regenerate and redis_manager.is_connected:
            cached = redis_manager.get(f"ebios:ai:{cache_key}")
            if cached:
                logger.info(f"✅ Cache HIT pour AT2 v2")
                try:
                    return json.loads(cached)
                except json.JSONDecodeError:
                    pass

        # 4. Appel IA via Ollama
        start_time = datetime.utcnow()
        raw_response = ""

        try:
            # Combiner system et user prompt pour Ollama
            full_prompt = f"{messages[0]['content']}\n\n{messages[1]['content']}"

            logger.info(f"📡 Appel Ollama AT2: {OLLAMA_URL}, Model: {OLLAMA_MODEL}")

            async with httpx.AsyncClient(timeout=180.0) as client:
                response = await client.post(
                    f"{OLLAMA_URL}/api/generate",
                    json={
                        "model": OLLAMA_MODEL,
                        "prompt": full_prompt,
                        "stream": False,
                        "options": {
                            "temperature": 0.3,
                            "num_ctx": 8192,
                            "num_predict": 4096
                        }
                    }
                )

                if response.status_code != 200:
                    logger.error(f"❌ Ollama error AT2: {response.status_code} - {response.text}")
                    return {
                        "success": False,
                        "data": None,
                        "errors": [f"Ollama error: {response.status_code}"],
                        "stats": {}
                    }

                data = response.json()
                raw_response = data.get("response", "")

                logger.info(f"✅ Ollama AT2 response received ({len(raw_response)} chars)")

            # 5. Valider la reponse
            validation_result = validate_at2_response(raw_response)

            if not validation_result["valid"]:
                logger.warning(f"⚠️ Validation AT2 v2 echouee: {validation_result['errors']}")
                # Journaliser l'echec
                await EbiosAIService._log_ai_generation(
                    db=db,
                    project_id=project_id,
                    atelier="AT2",
                    version="ebios_rm_v2",
                    prompt_system=messages[0]["content"][:2000],
                    prompt_user=messages[1]["content"],
                    raw_response=raw_response[:5000],
                    parsed_response=None,
                    success=False,
                    error_message="; ".join(validation_result["errors"]),
                    duration_ms=int((datetime.utcnow() - start_time).total_seconds() * 1000)
                )
                # Retourner quand meme les donnees partielles
                return {
                    "success": False,
                    "data": validation_result.get("data"),
                    "errors": validation_result["errors"],
                    "stats": validation_result.get("stats", {})
                }

            # 6. Succes - mettre en cache et journaliser
            result_data = validation_result["data"]

            if redis_manager.is_connected:
                redis_manager.set(
                    f"ebios:ai:{cache_key}",
                    json.dumps(result_data, ensure_ascii=False),
                    ttl=86400
                )

            await EbiosAIService._log_ai_generation(
                db=db,
                project_id=project_id,
                atelier="AT2",
                version="ebios_rm_v2",
                prompt_system=messages[0]["content"][:2000],
                prompt_user=messages[1]["content"],
                raw_response=raw_response[:5000],
                parsed_response=result_data,
                success=True,
                error_message=None,
                duration_ms=int((datetime.utcnow() - start_time).total_seconds() * 1000)
            )

            logger.info(f"✅ AT2 v2 genere avec succes: {validation_result['stats']}")

            return {
                "success": True,
                "data": result_data,
                "stats": validation_result["stats"]
            }

        except httpx.TimeoutException:
            logger.error(f"❌ Ollama timeout AT2")
            return {
                "success": False,
                "data": None,
                "errors": ["Ollama timeout - la génération a pris trop de temps"],
                "stats": {}
            }

        except Exception as e:
            logger.error(f"❌ Erreur generation AT2 v2: {e}")

            await EbiosAIService._log_ai_generation(
                db=db,
                project_id=project_id,
                atelier="AT2",
                version="ebios_rm_v2",
                prompt_system=messages[0]["content"][:2000] if messages else "",
                prompt_user=messages[1]["content"] if messages else "",
                raw_response=raw_response[:5000] if raw_response else "",
                parsed_response=None,
                success=False,
                error_message=str(e),
                duration_ms=int((datetime.utcnow() - start_time).total_seconds() * 1000)
            )
            raise

    @staticmethod
    async def generate_at2_dispatch(
        db: Session,
        project_id: str,
        context: Dict[str, Any],
        at1_data: Optional[Dict[str, Any]] = None,
        regenerate: bool = False
    ) -> Dict[str, Any]:
        """
        Dispatcher pour AT2 - choisit le pipeline selon analysis_version du projet.

        Args:
            db: Session SQLAlchemy
            project_id: UUID du projet
            context: Contexte du projet
            at1_data: Donnees AT1 (valeurs metier, biens supports, ER)
            regenerate: Force regeneration

        Returns:
            Resultat de generation selon le pipeline choisi
        """
        # Verifier la version du projet
        from src.services.ebios_reference_service import EbiosReferenceService

        ref_service = EbiosReferenceService(db)
        is_v2 = ref_service.is_ebios_rm_v2_enabled(project_id)

        if is_v2:
            logger.info(f"🔀 Dispatch AT2 vers pipeline v2 pour projet {project_id}")
            return await EbiosAIService.generate_at2_v2(
                db=db,
                project_id=project_id,
                context=context,
                at1_data=at1_data,
                regenerate=regenerate
            )
        else:
            logger.info(f"🔀 Dispatch AT2 vers pipeline legacy pour projet {project_id}")
            # Pipeline legacy - comportement original
            result = await EbiosAIService.generate_at2(
                context=context,
                at1_data=at1_data or {},
                regenerate=regenerate
            )
            return {"success": True, "data": result}

    # ==========================================================================
    # PIPELINE V2 - AT3 CONFORME ANSSI (Scenarios Strategiques)
    # ==========================================================================

    @staticmethod
    async def generate_at3_v2(
        db: Session,
        project_id: str,
        context: Dict[str, Any],
        at1_data: Optional[Dict[str, Any]] = None,
        at2_data: Optional[Dict[str, Any]] = None,
        regenerate: bool = False
    ) -> Dict[str, Any]:
        """
        Genere le contenu de l'Atelier 3 avec le pipeline v2 (conforme ANSSI).

        Nouveaute ANSSI : Introduction obligatoire de la VULNERABILITE STRATEGIQUE.
        Un scenario strategique = source + vulnerabilite + biens + evenement redoute.

        Args:
            db: Session SQLAlchemy
            project_id: UUID du projet EBIOS
            context: Contexte du projet (description, secteur, etc.)
            at1_data: Donnees de l'AT1 (valeurs metier, biens supports, ER)
            at2_data: Donnees de l'AT2 (sources de risque)
            regenerate: Force la regeneration meme si cache existe

        Returns:
            Dict avec scenarios_strategiques incluant vulnerabilite strategique
        """
        from src.services.ebios_reference_service import EbiosReferenceService
        from src.prompts.ebios_rm_v2.at3_prompts import (
            build_at3_messages,
            validate_at3_response
        )

        logger.info(f"🚀 Generation AT3 v2 pour projet {project_id}")

        # 1. Charger les referentiels ANSSI pour AT3
        ref_service = EbiosReferenceService(db)
        referentiels = ref_service.get_referentiels_for_at3()

        logger.info(f"📚 Referentiels AT3 charges")

        # 2. Construire les messages
        messages = build_at3_messages(
            referentiels=referentiels,
            organization_name=context.get("name", "Organisation"),
            organization_description=context.get("description", ""),
            sector=context.get("sector"),
            at1_data=at1_data,
            at2_data=at2_data,
            additional_context=context.get("additional_info")
        )

        # 3. Cache key pour cette generation
        at1_hash = hash(str(at1_data)) if at1_data else "no_at1"
        at2_hash = hash(str(at2_data)) if at2_data else "no_at2"
        cache_key = f"ebios_at3_v2_{project_id}_{hash(str(context))}_{at1_hash}_{at2_hash}"

        # Verifier le cache
        if not regenerate and redis_manager.is_connected:
            cached = redis_manager.get(f"ebios:ai:{cache_key}")
            if cached:
                logger.info(f"✅ Cache HIT pour AT3 v2")
                try:
                    return json.loads(cached)
                except json.JSONDecodeError:
                    pass

        # 4. Appel IA via Ollama
        start_time = datetime.utcnow()
        raw_response = ""

        try:
            # Combiner system et user prompt pour Ollama
            full_prompt = f"{messages[0]['content']}\n\n{messages[1]['content']}"

            logger.info(f"📡 Appel Ollama AT3: {OLLAMA_URL}, Model: {OLLAMA_MODEL}")

            async with httpx.AsyncClient(timeout=180.0) as client:
                response = await client.post(
                    f"{OLLAMA_URL}/api/generate",
                    json={
                        "model": OLLAMA_MODEL,
                        "prompt": full_prompt,
                        "stream": False,
                        "options": {
                            "temperature": 0.3,
                            "num_ctx": 8192,
                            "num_predict": 4096
                        }
                    }
                )

                if response.status_code != 200:
                    logger.error(f"❌ Ollama error AT3: {response.status_code} - {response.text}")
                    return {
                        "success": False,
                        "data": None,
                        "errors": [f"Ollama error: {response.status_code}"],
                        "stats": {}
                    }

                data = response.json()
                raw_response = data.get("response", "")

                logger.info(f"✅ Ollama AT3 response received ({len(raw_response)} chars)")

            # 5. Valider la reponse
            validation_result = validate_at3_response(raw_response)

            if not validation_result["valid"]:
                logger.warning(f"⚠️ Validation AT3 v2 echouee: {validation_result['errors']}")
                # Journaliser l'echec
                await EbiosAIService._log_ai_generation(
                    db=db,
                    project_id=project_id,
                    atelier="AT3",
                    version="ebios_rm_v2",
                    prompt_system=messages[0]["content"][:2000],
                    prompt_user=messages[1]["content"],
                    raw_response=raw_response[:5000],
                    parsed_response=None,
                    success=False,
                    error_message="; ".join(validation_result["errors"]),
                    duration_ms=int((datetime.utcnow() - start_time).total_seconds() * 1000)
                )
                # Retourner quand meme les donnees partielles
                return {
                    "success": False,
                    "data": validation_result.get("data"),
                    "errors": validation_result["errors"],
                    "stats": validation_result.get("stats", {})
                }

            # 6. Succes - mettre en cache et journaliser
            result_data = validation_result["data"]

            if redis_manager.is_connected:
                redis_manager.set(
                    f"ebios:ai:{cache_key}",
                    json.dumps(result_data, ensure_ascii=False),
                    ttl=86400
                )

            await EbiosAIService._log_ai_generation(
                db=db,
                project_id=project_id,
                atelier="AT3",
                version="ebios_rm_v2",
                prompt_system=messages[0]["content"][:2000],
                prompt_user=messages[1]["content"],
                raw_response=raw_response[:5000],
                parsed_response=result_data,
                success=True,
                error_message=None,
                duration_ms=int((datetime.utcnow() - start_time).total_seconds() * 1000)
            )

            logger.info(f"✅ AT3 v2 genere avec succes: {validation_result['stats']}")

            return {
                "success": True,
                "data": result_data,
                "stats": validation_result["stats"]
            }

        except httpx.TimeoutException:
            logger.error(f"❌ Ollama timeout AT3")
            return {
                "success": False,
                "data": None,
                "errors": ["Ollama timeout - la génération a pris trop de temps"],
                "stats": {}
            }

        except Exception as e:
            logger.error(f"❌ Erreur generation AT3 v2: {e}")

            await EbiosAIService._log_ai_generation(
                db=db,
                project_id=project_id,
                atelier="AT3",
                version="ebios_rm_v2",
                prompt_system=messages[0]["content"][:2000] if messages else "",
                prompt_user=messages[1]["content"] if messages else "",
                raw_response=raw_response[:5000] if raw_response else "",
                parsed_response=None,
                success=False,
                error_message=str(e),
                duration_ms=int((datetime.utcnow() - start_time).total_seconds() * 1000)
            )
            raise

    @staticmethod
    async def generate_at3_dispatch(
        db: Session,
        project_id: str,
        context: Dict[str, Any],
        at1_data: Optional[Dict[str, Any]] = None,
        at2_data: Optional[Dict[str, Any]] = None,
        regenerate: bool = False
    ) -> Dict[str, Any]:
        """
        Dispatcher pour AT3 - choisit le pipeline selon analysis_version du projet.

        Args:
            db: Session SQLAlchemy
            project_id: UUID du projet
            context: Contexte du projet
            at1_data: Donnees AT1 (valeurs metier, biens supports, ER)
            at2_data: Donnees AT2 (sources de risque)
            regenerate: Force regeneration

        Returns:
            Resultat de generation selon le pipeline choisi
        """
        # Verifier la version du projet
        from src.services.ebios_reference_service import EbiosReferenceService

        ref_service = EbiosReferenceService(db)
        is_v2 = ref_service.is_ebios_rm_v2_enabled(project_id)

        if is_v2:
            logger.info(f"🔀 Dispatch AT3 vers pipeline v2 pour projet {project_id}")
            return await EbiosAIService.generate_at3_v2(
                db=db,
                project_id=project_id,
                context=context,
                at1_data=at1_data,
                at2_data=at2_data,
                regenerate=regenerate
            )
        else:
            logger.info(f"🔀 Dispatch AT3 vers pipeline legacy pour projet {project_id}")
            # Pipeline legacy - comportement original
            result = await EbiosAIService.generate_at3(
                context=context,
                at1_data=at1_data or {},
                at2_data=at2_data or {},
                regenerate=regenerate
            )
            return {"success": True, "data": result}

    # ==========================================================================
    # PIPELINE V2 - AT4 CONFORME ANSSI (Scenarios Operationnels)
    # ==========================================================================

    @staticmethod
    async def generate_at4_v2(
        db: Session,
        project_id: str,
        context: Dict[str, Any],
        at1_data: Optional[Dict[str, Any]] = None,
        at3_data: Optional[Dict[str, Any]] = None,
        regenerate: bool = False
    ) -> Dict[str, Any]:
        """
        Genere le contenu de l'Atelier 4 avec le pipeline v2 (conforme ANSSI).

        AT4 decline les scenarios strategiques (AT3) en scenarios operationnels
        detailles avec chaine d'attaque.

        Args:
            db: Session SQLAlchemy
            project_id: UUID du projet EBIOS
            context: Contexte du projet (description, secteur, etc.)
            at1_data: Donnees de l'AT1 (biens supports pour reference)
            at3_data: Donnees de l'AT3 (scenarios strategiques)
            regenerate: Force la regeneration meme si cache existe

        Returns:
            Dict avec scenarios_operationnels incluant chaines d'attaque
        """
        from src.services.ebios_reference_service import EbiosReferenceService
        from src.prompts.ebios_rm_v2.at4_prompts import (
            build_at4_messages,
            validate_at4_response
        )

        logger.info(f"🚀 Generation AT4 v2 pour projet {project_id}")

        # 1. Charger les referentiels ANSSI pour AT4
        ref_service = EbiosReferenceService(db)
        referentiels = ref_service.get_referentiels_for_at4()

        logger.info(f"📚 Referentiels AT4 charges")

        # 2. Extraire les scenarios strategiques de AT3
        strategic_scenarios = []
        if at3_data:
            strategic_scenarios = at3_data.get("scenarios_strategiques", [])

        if not strategic_scenarios:
            logger.warning("⚠️ Aucun scenario strategique fourni pour AT4")
            return {
                "success": False,
                "data": None,
                "errors": ["Aucun scenario strategique (AT3) fourni. Generez d'abord l'AT3."],
                "stats": {}
            }

        logger.info(f"📊 {len(strategic_scenarios)} scenarios strategiques a decliner")

        # 3. Construire les messages
        messages = build_at4_messages(
            referentiels=referentiels,
            organization_name=context.get("name", "Organisation"),
            organization_description=context.get("description", ""),
            sector=context.get("sector"),
            strategic_scenarios=strategic_scenarios,
            at1_data=at1_data,
            additional_context=context.get("additional_info")
        )

        # 4. Cache key pour cette generation
        at1_hash = hash(str(at1_data)) if at1_data else "no_at1"
        at3_hash = hash(str(at3_data)) if at3_data else "no_at3"
        cache_key = f"ebios_at4_v2_{project_id}_{hash(str(context))}_{at1_hash}_{at3_hash}"

        # Verifier le cache
        if not regenerate and redis_manager.is_connected:
            cached = redis_manager.get(f"ebios:ai:{cache_key}")
            if cached:
                logger.info(f"✅ Cache HIT pour AT4 v2")
                try:
                    return json.loads(cached)
                except json.JSONDecodeError:
                    pass

        # 5. Appel IA via Ollama
        start_time = datetime.utcnow()
        raw_response = ""

        try:
            # Combiner system et user prompt pour Ollama
            full_prompt = f"{messages[0]['content']}\n\n{messages[1]['content']}"

            logger.info(f"📡 Appel Ollama AT4: {OLLAMA_URL}, Model: {OLLAMA_MODEL}")

            async with httpx.AsyncClient(timeout=240.0) as client:
                response = await client.post(
                    f"{OLLAMA_URL}/api/generate",
                    json={
                        "model": OLLAMA_MODEL,
                        "prompt": full_prompt,
                        "stream": False,
                        "options": {
                            "temperature": 0.3,
                            "num_ctx": 8192,
                            "num_predict": 6144  # Plus long pour les chaines d'attaque
                        }
                    }
                )

                if response.status_code != 200:
                    logger.error(f"❌ Ollama error AT4: {response.status_code} - {response.text}")
                    return {
                        "success": False,
                        "data": None,
                        "errors": [f"Ollama error: {response.status_code}"],
                        "stats": {}
                    }

                data = response.json()
                raw_response = data.get("response", "")

                logger.info(f"✅ Ollama AT4 response received ({len(raw_response)} chars)")

            # 6. Valider la reponse
            validation_result = validate_at4_response(raw_response)

            if not validation_result["valid"]:
                logger.warning(f"⚠️ Validation AT4 v2 echouee: {validation_result['errors']}")
                # Journaliser l'echec
                await EbiosAIService._log_ai_generation(
                    db=db,
                    project_id=project_id,
                    atelier="AT4",
                    version="ebios_rm_v2",
                    prompt_system=messages[0]["content"][:2000],
                    prompt_user=messages[1]["content"],
                    raw_response=raw_response[:5000],
                    parsed_response=None,
                    success=False,
                    error_message="; ".join(validation_result["errors"]),
                    duration_ms=int((datetime.utcnow() - start_time).total_seconds() * 1000)
                )
                # Retourner quand meme les donnees partielles
                return {
                    "success": False,
                    "data": validation_result.get("data"),
                    "errors": validation_result["errors"],
                    "stats": validation_result.get("stats", {})
                }

            # 7. Succes - mettre en cache et journaliser
            result_data = validation_result["data"]

            if redis_manager.is_connected:
                redis_manager.set(
                    f"ebios:ai:{cache_key}",
                    json.dumps(result_data, ensure_ascii=False),
                    ttl=86400
                )

            await EbiosAIService._log_ai_generation(
                db=db,
                project_id=project_id,
                atelier="AT4",
                version="ebios_rm_v2",
                prompt_system=messages[0]["content"][:2000],
                prompt_user=messages[1]["content"],
                raw_response=raw_response[:5000],
                parsed_response=result_data,
                success=True,
                error_message=None,
                duration_ms=int((datetime.utcnow() - start_time).total_seconds() * 1000)
            )

            logger.info(f"✅ AT4 v2 genere avec succes: {validation_result['stats']}")

            return {
                "success": True,
                "data": result_data,
                "stats": validation_result["stats"]
            }

        except httpx.TimeoutException:
            logger.error(f"❌ Ollama timeout AT4")
            return {
                "success": False,
                "data": None,
                "errors": ["Ollama timeout - la génération a pris trop de temps"],
                "stats": {}
            }

        except Exception as e:
            logger.error(f"❌ Erreur generation AT4 v2: {e}")

            await EbiosAIService._log_ai_generation(
                db=db,
                project_id=project_id,
                atelier="AT4",
                version="ebios_rm_v2",
                prompt_system=messages[0]["content"][:2000] if messages else "",
                prompt_user=messages[1]["content"] if messages else "",
                raw_response=raw_response[:5000] if raw_response else "",
                parsed_response=None,
                success=False,
                error_message=str(e),
                duration_ms=int((datetime.utcnow() - start_time).total_seconds() * 1000)
            )
            raise

    @staticmethod
    async def generate_at4_dispatch(
        db: Session,
        project_id: str,
        context: Dict[str, Any],
        at1_data: Optional[Dict[str, Any]] = None,
        at3_data: Optional[Dict[str, Any]] = None,
        regenerate: bool = False
    ) -> Dict[str, Any]:
        """
        Dispatcher pour AT4 - choisit le pipeline selon analysis_version du projet.

        Args:
            db: Session SQLAlchemy
            project_id: UUID du projet
            context: Contexte du projet
            at1_data: Donnees AT1 (biens supports)
            at3_data: Donnees AT3 (scenarios strategiques)
            regenerate: Force regeneration

        Returns:
            Resultat de generation selon le pipeline choisi
        """
        # Verifier la version du projet
        from src.services.ebios_reference_service import EbiosReferenceService

        ref_service = EbiosReferenceService(db)
        is_v2 = ref_service.is_ebios_rm_v2_enabled(project_id)

        if is_v2:
            logger.info(f"🔀 Dispatch AT4 vers pipeline v2 pour projet {project_id}")
            return await EbiosAIService.generate_at4_v2(
                db=db,
                project_id=project_id,
                context=context,
                at1_data=at1_data,
                at3_data=at3_data,
                regenerate=regenerate
            )
        else:
            logger.info(f"🔀 Dispatch AT4 vers pipeline legacy pour projet {project_id}")
            # Pipeline legacy - comportement original
            result = await EbiosAIService.generate_at4(
                context=context,
                at1_data=at1_data or {},
                at3_data=at3_data or {},
                regenerate=regenerate
            )
            return {"success": True, "data": result}

    # ==========================================================================
    # PIPELINE V2 - AT5 CONFORME ANSSI (Matrice des Risques)
    # ==========================================================================

    @staticmethod
    async def generate_at5_v2(
        db: Session,
        project_id: str,
        at3_data: Optional[Dict[str, Any]] = None,
        at4_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Genere la matrice des risques AT5 avec le pipeline v2 (conforme ANSSI).

        AT5 ne fait PAS appel a l'IA - il consomme les donnees de AT3 et AT4
        et applique les regles de classification ANSSI.

        Classification ANSSI :
        - Score 1-3  : FAIBLE
        - Score 4-7  : MODERE
        - Score 8-11 : IMPORTANT
        - Score 12-16: CRITIQUE

        Args:
            db: Session SQLAlchemy
            project_id: UUID du projet EBIOS
            at3_data: Donnees de l'AT3 (scenarios strategiques)
            at4_data: Donnees de l'AT4 (scenarios operationnels)

        Returns:
            Dict avec matrice, scenarios, statistiques
        """
        from src.prompts.ebios_rm_v2.at5_prompts import (
            generate_at5_matrix,
            RiskMatrixService
        )

        logger.info(f"🚀 Generation AT5 v2 (Matrice des risques) pour projet {project_id}")

        # Verifier les donnees d'entree
        ss_count = len(at3_data.get("scenarios_strategiques", [])) if at3_data else 0
        so_count = len(at4_data.get("scenarios_operationnels", [])) if at4_data else 0

        logger.info(f"📊 Entrees AT5: {ss_count} scenarios strategiques, {so_count} scenarios operationnels")

        if ss_count == 0 and so_count == 0:
            logger.warning("⚠️ Aucun scenario fourni pour AT5")
            return {
                "success": False,
                "data": None,
                "errors": ["Aucun scenario fourni. Generez d'abord AT3 et/ou AT4."],
                "stats": {}
            }

        # Generer la matrice (pas d'appel IA)
        start_time = datetime.utcnow()

        try:
            result = generate_at5_matrix(at3_data, at4_data)

            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

            if result["success"]:
                logger.info(f"✅ AT5 v2 genere avec succes en {duration_ms}ms: {result.get('stats', {})}")

                # Journaliser le calcul
                await EbiosAIService._log_ai_generation(
                    db=db,
                    project_id=project_id,
                    atelier="AT5",
                    version="ebios_rm_v2",
                    prompt_system="[Calcul matriciel - pas d'IA]",
                    prompt_user=f"SS: {ss_count}, SO: {so_count}",
                    raw_response="",
                    parsed_response=result.get("stats"),
                    success=True,
                    error_message=None,
                    duration_ms=duration_ms
                )

                return {
                    "success": True,
                    "data": result["data"],
                    "warnings": result.get("warnings", []),
                    "stats": result.get("stats", {})
                }
            else:
                logger.warning(f"⚠️ AT5 v2 echoue: {result.get('errors', [])}")
                return result

        except Exception as e:
            logger.error(f"❌ Erreur generation AT5 v2: {e}")
            return {
                "success": False,
                "data": None,
                "errors": [str(e)],
                "stats": {}
            }

    @staticmethod
    async def generate_at5_dispatch(
        db: Session,
        project_id: str,
        at3_data: Optional[Dict[str, Any]] = None,
        at4_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Dispatcher pour AT5 - choisit le pipeline selon analysis_version du projet.

        Args:
            db: Session SQLAlchemy
            project_id: UUID du projet
            at3_data: Donnees AT3 (scenarios strategiques)
            at4_data: Donnees AT4 (scenarios operationnels)

        Returns:
            Resultat de generation selon le pipeline choisi
        """
        # Verifier la version du projet
        from src.services.ebios_reference_service import EbiosReferenceService

        ref_service = EbiosReferenceService(db)
        is_v2 = ref_service.is_ebios_rm_v2_enabled(project_id)

        if is_v2:
            logger.info(f"🔀 Dispatch AT5 vers pipeline v2 pour projet {project_id}")
            return await EbiosAIService.generate_at5_v2(
                db=db,
                project_id=project_id,
                at3_data=at3_data,
                at4_data=at4_data
            )
        else:
            logger.info(f"🔀 Dispatch AT5 vers pipeline legacy pour projet {project_id}")
            # Pipeline legacy - comportement original (si existant)
            # AT5 legacy peut simplement retourner les scores bruts
            result = await EbiosAIService.generate_at5(
                at3_data=at3_data or {},
                at4_data=at4_data or {}
            )
            return {"success": True, "data": result}

    # ==========================================================================
    # AT6 - PLAN DE TRAITEMENT DES RISQUES (v2 ANSSI)
    # ==========================================================================

    @staticmethod
    async def generate_at6_v2(
        db: Session,
        project_id: str,
        at3_data: Optional[Dict[str, Any]] = None,
        at4_data: Optional[Dict[str, Any]] = None,
        at5_data: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
        campaign_ref: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Genere le plan de traitement AT6 selon la methodologie ANSSI.

        AT6 consomme les scenarios de AT3, AT4 et AT5 pour produire:
        - Une strategie de traitement par scenario (REDUIRE/EVITER/TRANSFERER/ACCEPTER)
        - Des actions de securite (1-5 par scenario)
        - Des codes actions normalises

        Args:
            db: Session SQLAlchemy
            project_id: UUID du projet EBIOS RM
            at3_data: Scenarios strategiques (AT3)
            at4_data: Scenarios operationnels (AT4)
            at5_data: Matrice des risques (AT5)
            context: Contexte additionnel (organisation, mission, etc.)
            campaign_ref: Reference campagne pour generation des codes actions

        Returns:
            Dict avec success, data (plan_traitement), errors, warnings, stats
        """
        from src.prompts.ebios_rm_v2.at6_prompts import (
            build_at6_messages,
            validate_at6_response,
            generate_action_codes,
            export_actions_for_module
        )

        logger.info(f"🎯 Demarrage generation AT6 v2 pour projet {project_id}")

        # Validation des entrees
        if not at3_data and not at4_data:
            return {
                "success": False,
                "data": None,
                "errors": ["AT6 necessite au moins les donnees AT3 ou AT4"],
                "warnings": [],
                "stats": {}
            }

        # Construire les messages pour l'IA
        messages = build_at6_messages(
            at3_data=at3_data,
            at4_data=at4_data,
            at5_data=at5_data,
            context=context
        )

        try:
            # Verifier le cache Redis
            import hashlib
            import json as json_module

            at3_hash = hashlib.md5(str(at3_data).encode()).hexdigest()[:8] if at3_data else "no_at3"
            at4_hash = hashlib.md5(str(at4_data).encode()).hexdigest()[:8] if at4_data else "no_at4"
            at5_hash = hashlib.md5(str(at5_data).encode()).hexdigest()[:8] if at5_data else "no_at5"
            cache_key = f"ebios_at6_v2_{project_id}_{at3_hash}_{at4_hash}_{at5_hash}"

            cached_result = await EbiosAIService._get_cached_result(cache_key)
            if cached_result:
                logger.info(f"✅ AT6 v2: Resultat trouve en cache")
                return cached_result

            # Appel Ollama
            logger.info(f"🤖 AT6 v2: Appel Ollama pour generation plan de traitement...")

            response = await EbiosAIService._call_ollama(
                messages=messages,
                model="qwen2.5:14b",  # Modele capable de generer du JSON structure
                temperature=0.3,  # Temperature basse pour coherence
                max_tokens=8000   # Plan de traitement peut etre long
            )

            if not response:
                return {
                    "success": False,
                    "data": None,
                    "errors": ["Pas de reponse de l'IA"],
                    "warnings": [],
                    "stats": {}
                }

            # Valider la reponse
            validation_result = validate_at6_response(response)

            if not validation_result["success"] and not validation_result.get("data"):
                logger.error(f"❌ AT6 v2: Validation echouee - {validation_result['errors']}")
                return validation_result

            # Generer les codes actions si campaign_ref fourni
            plan_data = validation_result["data"]
            if campaign_ref and plan_data:
                plan_data = generate_action_codes(plan_data, campaign_ref)
                logger.info(f"✅ AT6 v2: Codes actions generes avec prefix {campaign_ref}")

            # Preparer le resultat final
            result = {
                "success": True,
                "data": plan_data,
                "errors": validation_result.get("errors", []),
                "warnings": validation_result.get("warnings", []),
                "stats": validation_result.get("stats", {})
            }

            # Mettre en cache (TTL 1h)
            await EbiosAIService._cache_result(cache_key, result, ttl=3600)

            logger.info(
                f"✅ AT6 v2: Generation reussie - "
                f"{result['stats'].get('scenarios_traites', 0)} scenarios, "
                f"{result['stats'].get('total_actions', 0)} actions"
            )

            return result

        except Exception as e:
            logger.error(f"❌ Erreur generation AT6 v2: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "data": None,
                "errors": [str(e)],
                "warnings": [],
                "stats": {}
            }

    @staticmethod
    async def generate_at6_dispatch(
        db: Session,
        project_id: str,
        at3_data: Optional[Dict[str, Any]] = None,
        at4_data: Optional[Dict[str, Any]] = None,
        at5_data: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
        campaign_ref: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Dispatcher pour AT6 - choisit le pipeline selon analysis_version du projet.

        Args:
            db: Session SQLAlchemy
            project_id: UUID du projet
            at3_data: Donnees AT3 (scenarios strategiques)
            at4_data: Donnees AT4 (scenarios operationnels)
            at5_data: Donnees AT5 (matrice des risques)
            context: Contexte additionnel
            campaign_ref: Reference campagne pour codes actions

        Returns:
            Resultat de generation selon le pipeline choisi
        """
        from src.services.ebios_reference_service import EbiosReferenceService

        ref_service = EbiosReferenceService(db)
        is_v2 = ref_service.is_ebios_rm_v2_enabled(project_id)

        if is_v2:
            logger.info(f"🔀 Dispatch AT6 vers pipeline v2 pour projet {project_id}")
            return await EbiosAIService.generate_at6_v2(
                db=db,
                project_id=project_id,
                at3_data=at3_data,
                at4_data=at4_data,
                at5_data=at5_data,
                context=context,
                campaign_ref=campaign_ref
            )
        else:
            logger.info(f"🔀 Dispatch AT6 vers pipeline legacy pour projet {project_id}")
            # Pipeline legacy - generer plan d'actions simplifie
            result = await EbiosAIService.generate_at6_legacy(
                at3_data=at3_data or {},
                at4_data=at4_data or {},
                at5_data=at5_data or {}
            )
            return {"success": True, "data": result}

    @staticmethod
    async def generate_at6_legacy(
        at3_data: Dict[str, Any],
        at4_data: Dict[str, Any],
        at5_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Pipeline legacy pour AT6 - comportement original.

        Genere un plan d'actions simplifie sans les contraintes strictes ANSSI.

        Args:
            at3_data: Scenarios strategiques
            at4_data: Scenarios operationnels
            at5_data: Matrice des risques

        Returns:
            Plan de traitement simplifie
        """
        logger.info("📋 AT6 Legacy: Generation plan de traitement simplifie")

        # Construire un plan basique a partir des scenarios
        plan = []

        # Traiter les scenarios strategiques
        for ss in at3_data.get("scenarios_strategiques", []):
            plan.append({
                "scenario_ref": ss.get("code", "SS??"),
                "scenario_title": ss.get("title", ss.get("titre", "")),
                "risk_level": "MODERE",
                "strategie": "REDUIRE",
                "actions": [{
                    "label": f"Traiter le scenario {ss.get('code', '')}",
                    "description": f"Mettre en place des mesures pour reduire le risque lie a {ss.get('title', '')}",
                    "categorie": "PREVENTIVE",
                    "priorite": "MOYENNE",
                    "risques_couverts": [ss.get("code", "")]
                }]
            })

        # Traiter les scenarios operationnels
        for so in at4_data.get("scenarios_operationnels", []):
            plan.append({
                "scenario_ref": so.get("reference", "SO??"),
                "scenario_title": so.get("titre", so.get("title", "")),
                "risk_level": "MODERE",
                "strategie": "REDUIRE",
                "actions": [{
                    "label": f"Traiter le scenario {so.get('reference', '')}",
                    "description": f"Mettre en place des mesures pour contrer la chaine d'attaque",
                    "categorie": "PREVENTIVE",
                    "priorite": "MOYENNE",
                    "risques_couverts": [so.get("reference", "")]
                }]
            })

        return {
            "plan_traitement": plan,
            "synthese": {
                "total_scenarios": len(plan),
                "total_actions": len(plan),
                "mode": "legacy"
            }
        }
