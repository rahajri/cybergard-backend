"""
Service IA pour le module EBIOS RM

Génération assistée par IA pour chaque atelier EBIOS:
- AT1: Cadrage (valeurs métier, biens supports, événements redoutés)
- AT2: Sources de risques
- AT3: Scénarios stratégiques
- AT4: Scénarios opérationnels
- AT5: Risques et traitement

Utilise DeepSeek via l'API existante avec cache Redis.
"""

import json
import logging
import os
from datetime import datetime
from typing import Dict, Any, List, Optional

from src.utils.redis_manager import redis_manager

logger = logging.getLogger(__name__)

# Configuration DeepSeek
DEEPSEEK_API_URL = os.getenv("DEEPSEEK_API_URL", "http://localhost:11434/api/generate")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-r1:14b")


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
        Appelle le service IA avec mise en cache.

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

        try:
            # Import du service DeepSeek
            from src.services.deepseek_service import generate_with_deepseek

            # Appel à l'IA
            response = await generate_with_deepseek(
                prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=0.7,
                max_tokens=4000
            )

            # Parser la réponse JSON
            result = EbiosAIService._parse_json_response(response)

            # Mettre en cache
            if redis_manager.is_connected and result:
                redis_manager.set(
                    f"ebios:ai:{cache_key}",
                    json.dumps(result, ensure_ascii=False),
                    ttl=86400  # 24h
                )

            return result

        except ImportError:
            logger.warning("⚠️ Service DeepSeek non disponible, utilisation de données mock")
            return EbiosAIService._get_mock_response(cache_key)

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

    @staticmethod
    def _get_mock_response(cache_key: str) -> Dict[str, Any]:
        """
        Retourne des données mock pour le développement.
        """
        if "at1" in cache_key:
            return {
                "business_values": [
                    {"label": "Données clients", "description": "Informations personnelles et commerciales des clients", "criticality": 4},
                    {"label": "Continuité de service", "description": "Capacité à maintenir les services en ligne", "criticality": 4},
                    {"label": "Réputation", "description": "Image de marque et confiance des clients", "criticality": 3}
                ],
                "assets": [
                    {"label": "Base de données clients", "type": "Données", "description": "PostgreSQL avec données clients", "criticality": 4},
                    {"label": "Serveur web", "type": "Serveur", "description": "Serveurs applicatifs", "criticality": 3},
                    {"label": "Réseau interne", "type": "Réseau", "description": "Infrastructure réseau LAN", "criticality": 3}
                ],
                "feared_events": [
                    {"label": "Fuite de données clients", "dimension": "CONFIDENTIALITY", "severity": 4, "justification": "Impact RGPD majeur"},
                    {"label": "Indisponibilité des services", "dimension": "AVAILABILITY", "severity": 3, "justification": "Perte de revenus"},
                    {"label": "Altération des données", "dimension": "INTEGRITY", "severity": 4, "justification": "Décisions erronées"}
                ]
            }

        if "at2" in cache_key:
            return {
                "risk_sources": [
                    {"label": "Cybercriminel organisé", "relevance": 4, "is_selected": True, "objectives": [{"label": "Vol de données pour revente"}]},
                    {"label": "Concurrent", "relevance": 2, "is_selected": True, "objectives": [{"label": "Espionnage industriel"}]},
                    {"label": "Employé mécontent", "relevance": 3, "is_selected": True, "objectives": [{"label": "Sabotage interne"}]}
                ]
            }

        return {"message": "Mock data - Service IA non disponible"}
