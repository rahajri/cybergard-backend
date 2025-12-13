"""
Prompts EBIOS RM v2 - Atelier 6 : Plan de Traitement des Risques

Ce module gere la generation du plan de traitement selon la methodologie ANSSI.
AT6 consomme les scenarios de AT3, AT4 et AT5 pour produire:
- Une strategie de traitement par scenario
- Des actions de securite (1-5 par scenario)

Strategies de traitement ANSSI:
- REDUIRE : Mettre en place des mesures pour reduire le risque
- EVITER : Supprimer l'activite ou le bien support concerne
- TRANSFERER : Transferer le risque (assurance, sous-traitance)
- ACCEPTER : Accepter le risque en connaissance de cause

Regles selon le niveau de risque:
- CRITIQUE (12-16) : REDUIRE obligatoire
- IMPORTANT (8-11) : REDUIRE ou TRANSFERER
- MODERE (4-7) : REDUIRE ou ACCEPTER
- FAIBLE (1-3) : ACCEPTER possible
"""

import logging
import json
import re
from typing import Dict, Any, List, Optional
from enum import Enum

logger = logging.getLogger(__name__)


# ==============================================================================
# ENUMS ET CONSTANTES ANSSI
# ==============================================================================

class TreatmentStrategy(str, Enum):
    """Strategies de traitement ANSSI."""
    REDUIRE = "REDUIRE"
    EVITER = "EVITER"
    TRANSFERER = "TRANSFERER"
    ACCEPTER = "ACCEPTER"


class ActionCategory(str, Enum):
    """Categories d'actions ANSSI."""
    PREVENTIVE = "PREVENTIVE"
    DETECTIVE = "DETECTIVE"
    CORRECTIVE = "CORRECTIVE"


class ActionPriority(str, Enum):
    """Priorites d'actions."""
    HAUTE = "HAUTE"
    MOYENNE = "MOYENNE"
    BASSE = "BASSE"


# Regles de strategie selon le niveau de risque
STRATEGY_RULES = {
    "CRITIQUE": [TreatmentStrategy.REDUIRE],  # Obligatoire REDUIRE
    "IMPORTANT": [TreatmentStrategy.REDUIRE, TreatmentStrategy.TRANSFERER],
    "MODERE": [TreatmentStrategy.REDUIRE, TreatmentStrategy.ACCEPTER],
    "FAIBLE": [TreatmentStrategy.REDUIRE, TreatmentStrategy.EVITER,
               TreatmentStrategy.TRANSFERER, TreatmentStrategy.ACCEPTER]
}

# Priorite recommandee selon le niveau de risque
PRIORITY_BY_RISK_LEVEL = {
    "CRITIQUE": ActionPriority.HAUTE,
    "IMPORTANT": ActionPriority.HAUTE,
    "MODERE": ActionPriority.MOYENNE,
    "FAIBLE": ActionPriority.BASSE
}


# ==============================================================================
# PROMPTS SYSTEME ET UTILISATEUR
# ==============================================================================

def get_at6_system_prompt() -> str:
    """
    Retourne le prompt systeme pour la generation AT6.

    Ce prompt definit le role de l'IA et les regles strictes ANSSI.
    """
    return """[SYSTEM]

Tu appliques strictement la méthode EBIOS Risk Manager (ANSSI).
Tu te situes dans l'Atelier 6 : Plan de traitement des risques.

Objectif : produire un plan d'actions structuré pour chaque scénario de risque fourni.

Pour chaque scénario, tu dois produire :
- une stratégie de traitement : REDUIRE | EVITER | TRANSFERER | ACCEPTER
- une liste d'actions (1 à 5)
  Chaque action doit contenir :
    - label (très court, 5-10 mots max)
    - description (opérationnelle, 1-2 phrases)
    - categorie : PREVENTIVE | DETECTIVE | CORRECTIVE
    - priorite : HAUTE | MOYENNE | BASSE (selon niveau de risque)
    - risques_couverts : liste de références (SSxx, SOxx)

Contraintes strictes :
- Si le risque est CRITIQUE → la stratégie DOIT être REDUIRE (jamais accepter/transférer)
- Si le risque est IMPORTANT → REDUIRE ou TRANSFERER uniquement
- Si le risque est MODERE → REDUIRE ou ACCEPTER
- Si le risque est FAIBLE → ACCEPTER possible

Types d'actions :
- PREVENTIVE : Empêcher l'occurrence du risque (formation, durcissement, contrôle d'accès)
- DETECTIVE : Détecter l'occurrence du risque (monitoring, logs, alertes, audits)
- CORRECTIVE : Réagir et corriger après occurrence (plan de reprise, backup, incident response)

Priorités :
- HAUTE : Actions urgentes pour risques critiques ou importants
- MOYENNE : Actions planifiées pour risques modérés
- BASSE : Actions à long terme pour risques faibles

Réponds STRICTEMENT en JSON au format suivant (sans markdown, sans commentaires) :

{
  "plan_traitement": [
    {
      "scenario_ref": "SS01",
      "scenario_title": "Titre du scénario",
      "risk_level": "CRITIQUE",
      "strategie": "REDUIRE",
      "justification_strategie": "Justification du choix de stratégie",
      "actions": [
        {
          "label": "Renforcer l'authentification VPN",
          "description": "Mettre en place MFA obligatoire et revue trimestrielle des accès.",
          "categorie": "PREVENTIVE",
          "priorite": "HAUTE",
          "risques_couverts": ["SS01"],
          "responsable_suggere": "RSSI",
          "delai_suggere": "3 mois"
        }
      ]
    }
  ],
  "synthese": {
    "total_scenarios": 5,
    "total_actions": 12,
    "repartition_strategies": {
      "REDUIRE": 4,
      "ACCEPTER": 1
    },
    "repartition_priorites": {
      "HAUTE": 5,
      "MOYENNE": 5,
      "BASSE": 2
    }
  }
}"""


def get_at6_user_prompt(scenarios_data: Dict[str, Any]) -> str:
    """
    Construit le prompt utilisateur avec les scenarios.

    Args:
        scenarios_data: Dict contenant les scenarios strategiques et operationnels

    Returns:
        Prompt utilisateur formate
    """
    # Preparer le JSON des scenarios
    scenarios_json = json.dumps(scenarios_data, ensure_ascii=False, indent=2)

    return f"""Voici la liste des scénarios de risque issus de l'analyse EBIOS RM (AT3, AT4 et AT5) :

{scenarios_json}

Instructions :
1. Analyse chaque scénario et son niveau de risque
2. Détermine la stratégie de traitement appropriée selon les règles ANSSI
3. Propose 1 à 5 actions concrètes par scénario
4. Assure-toi que les actions sont :
   - Spécifiques et actionnables
   - Adaptées au contexte de l'organisation
   - Cohérentes avec le niveau de risque

IMPORTANT : Réponds uniquement en JSON valide, sans markdown ni commentaires.
Le JSON doit commencer par {{ et se terminer par }}."""


# ==============================================================================
# FONCTIONS DE CONSTRUCTION DES MESSAGES
# ==============================================================================

def build_at6_messages(
    at3_data: Optional[Dict[str, Any]],
    at4_data: Optional[Dict[str, Any]],
    at5_data: Optional[Dict[str, Any]],
    context: Optional[Dict[str, Any]] = None
) -> List[Dict[str, str]]:
    """
    Construit les messages pour l'appel IA AT6.

    Args:
        at3_data: Donnees AT3 (scenarios strategiques)
        at4_data: Donnees AT4 (scenarios operationnels)
        at5_data: Donnees AT5 (matrice des risques avec niveaux)
        context: Contexte additionnel (mission, organisation, etc.)

    Returns:
        Liste de messages [{role, content}]
    """
    # Consolider les scenarios avec leurs niveaux de risque
    scenarios_combined = consolidate_scenarios_for_at6(at3_data, at4_data, at5_data)

    # Ajouter le contexte si disponible
    if context:
        scenarios_combined["contexte"] = {
            "organisation": context.get("organization_name", "Organisation"),
            "mission": context.get("mission", ""),
            "valeurs_metier": context.get("business_values", []),
            "biens_supports": context.get("supporting_assets", [])
        }

    return [
        {"role": "system", "content": get_at6_system_prompt()},
        {"role": "user", "content": get_at6_user_prompt(scenarios_combined)}
    ]


def consolidate_scenarios_for_at6(
    at3_data: Optional[Dict[str, Any]],
    at4_data: Optional[Dict[str, Any]],
    at5_data: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Consolide les scenarios AT3, AT4 et AT5 pour AT6.

    AT6 a besoin de:
    - Reference du scenario (SSxx ou SOxx)
    - Titre et description
    - Niveau de risque (depuis AT5)
    - Score (G x V)
    - Biens supports concernes
    - Vulnerabilite strategique (depuis AT3)

    Args:
        at3_data: Scenarios strategiques
        at4_data: Scenarios operationnels
        at5_data: Matrice des risques

    Returns:
        Dict consolide pour le prompt AT6
    """
    consolidated = {
        "scenarios_strategiques": [],
        "scenarios_operationnels": []
    }

    # Map des niveaux de risque depuis AT5
    risk_levels_map = {}
    if at5_data:
        # Extraire les niveaux de AT5
        for ss in at5_data.get("strategic_scenarios", []):
            ref = ss.get("reference", ss.get("code", ""))
            risk_levels_map[ref] = {
                "level": ss.get("level", "MODERE"),
                "score": ss.get("score", 0),
                "gravity": ss.get("gravity", 0),
                "likelihood": ss.get("likelihood", 0)
            }

        for so in at5_data.get("operational_scenarios", []):
            ref = so.get("reference", "")
            risk_levels_map[ref] = {
                "level": so.get("level", "MODERE"),
                "score": so.get("score", 0),
                "gravity": so.get("gravity", 0),
                "likelihood": so.get("likelihood", 0)
            }

    # Traiter les scenarios strategiques (AT3)
    if at3_data:
        for ss in at3_data.get("scenarios_strategiques", []):
            ref = ss.get("code", "SS??")
            risk_info = risk_levels_map.get(ref, {})

            consolidated["scenarios_strategiques"].append({
                "reference": ref,
                "titre": ss.get("title", ss.get("titre", "Sans titre")),
                "description": ss.get("description", ""),
                "vulnerabilite_strategique": ss.get("vulnerability_label", ""),
                "biens_supports": ss.get("assets_ids", []),
                "evenement_redoute": ss.get("feared_event_id", ""),
                "gravite": risk_info.get("gravity", ss.get("severity", 0)),
                "vraisemblance": risk_info.get("likelihood", ss.get("likelihood", 0)),
                "score": risk_info.get("score", ss.get("score", 0)),
                "niveau_risque": risk_info.get("level", "MODERE")
            })

    # Traiter les scenarios operationnels (AT4)
    if at4_data:
        for so in at4_data.get("scenarios_operationnels", []):
            ref = so.get("reference", "SO??")
            risk_info = risk_levels_map.get(ref, {})

            # Extraire les etapes de la chaine d'attaque
            etapes_resume = []
            for etape in so.get("etapes", []):
                etapes_resume.append({
                    "ordre": etape.get("ordre", 0),
                    "resume": etape.get("resume", ""),
                    "type": etape.get("type_etape", "")
                })

            consolidated["scenarios_operationnels"].append({
                "reference": ref,
                "titre": so.get("titre", so.get("title", "Sans titre")),
                "description": so.get("description", ""),
                "scenario_strategique_parent": so.get("strategic_scenario_ref", ""),
                "vulnerabilite": so.get("vulnerabilite", ""),
                "biens_supports": so.get("biens_supports", []),
                "chaine_attaque": etapes_resume,
                "gravite": risk_info.get("gravity", so.get("gravite", 0)),
                "vraisemblance": risk_info.get("likelihood", so.get("vraisemblance", 0)),
                "score": risk_info.get("score", so.get("score_operationnel", 0)),
                "niveau_risque": risk_info.get("level", "MODERE")
            })

    return consolidated


# ==============================================================================
# VALIDATION DE LA REPONSE IA
# ==============================================================================

def validate_at6_response(response_text: str) -> Dict[str, Any]:
    """
    Valide et nettoie la reponse IA pour AT6.

    Args:
        response_text: Texte brut de la reponse IA

    Returns:
        Dict avec success, data, errors, warnings, stats
    """
    errors = []
    warnings = []
    stats = {
        "scenarios_traites": 0,
        "total_actions": 0,
        "strategies": {},
        "categories": {},
        "priorites": {}
    }

    # Nettoyer le markdown si present
    cleaned = response_text.strip()
    if cleaned.startswith("```"):
        # Retirer les balises markdown
        cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
        cleaned = re.sub(r'\s*```$', '', cleaned)

    # Parser le JSON
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        # Essayer de trouver le JSON dans le texte
        json_match = re.search(r'\{[\s\S]*\}', cleaned)
        if json_match:
            try:
                data = json.loads(json_match.group())
            except json.JSONDecodeError:
                errors.append(f"JSON invalide: {str(e)}")
                return {
                    "success": False,
                    "data": None,
                    "errors": errors,
                    "warnings": warnings,
                    "stats": stats
                }
        else:
            errors.append(f"JSON invalide: {str(e)}")
            return {
                "success": False,
                "data": None,
                "errors": errors,
                "warnings": warnings,
                "stats": stats
            }

    # Valider la structure
    if "plan_traitement" not in data:
        errors.append("Champ 'plan_traitement' manquant")
        return {
            "success": False,
            "data": None,
            "errors": errors,
            "warnings": warnings,
            "stats": stats
        }

    plan = data["plan_traitement"]
    if not isinstance(plan, list):
        errors.append("'plan_traitement' doit etre une liste")
        return {
            "success": False,
            "data": None,
            "errors": errors,
            "warnings": warnings,
            "stats": stats
        }

    # Valider et corriger chaque scenario
    validated_plan = []
    for i, scenario in enumerate(plan):
        validated_scenario, scenario_errors, scenario_warnings = validate_scenario_treatment(scenario, i)

        if validated_scenario:
            validated_plan.append(validated_scenario)

            # Mettre a jour les stats
            stats["scenarios_traites"] += 1
            strategy = validated_scenario.get("strategie", "REDUIRE")
            stats["strategies"][strategy] = stats["strategies"].get(strategy, 0) + 1

            for action in validated_scenario.get("actions", []):
                stats["total_actions"] += 1
                cat = action.get("categorie", "PREVENTIVE")
                prio = action.get("priorite", "MOYENNE")
                stats["categories"][cat] = stats["categories"].get(cat, 0) + 1
                stats["priorites"][prio] = stats["priorites"].get(prio, 0) + 1

        errors.extend(scenario_errors)
        warnings.extend(scenario_warnings)

    # Reconstruire la reponse validee
    validated_data = {
        "plan_traitement": validated_plan,
        "synthese": data.get("synthese", {
            "total_scenarios": stats["scenarios_traites"],
            "total_actions": stats["total_actions"],
            "repartition_strategies": stats["strategies"],
            "repartition_priorites": stats["priorites"]
        })
    }

    return {
        "success": len(errors) == 0 or len(validated_plan) > 0,
        "data": validated_data,
        "errors": errors,
        "warnings": warnings,
        "stats": stats
    }


def validate_scenario_treatment(
    scenario: Dict[str, Any],
    index: int
) -> tuple:
    """
    Valide un scenario individuel du plan de traitement.

    Args:
        scenario: Donnees du scenario
        index: Index dans la liste

    Returns:
        Tuple (validated_scenario, errors, warnings)
    """
    errors = []
    warnings = []

    # Verifier les champs requis
    scenario_ref = scenario.get("scenario_ref", f"SCENARIO_{index}")
    risk_level = scenario.get("risk_level", "MODERE")
    strategie = scenario.get("strategie", "REDUIRE")
    actions = scenario.get("actions", [])

    # Valider la strategie selon le niveau de risque
    allowed_strategies = STRATEGY_RULES.get(risk_level, STRATEGY_RULES["MODERE"])
    allowed_values = [s.value for s in allowed_strategies]

    if strategie not in allowed_values:
        warnings.append(
            f"{scenario_ref}: Strategie '{strategie}' non recommandee pour niveau {risk_level}. "
            f"Strategies autorisees: {allowed_values}"
        )
        # Corriger automatiquement pour CRITIQUE
        if risk_level == "CRITIQUE" and strategie != "REDUIRE":
            strategie = "REDUIRE"
            warnings.append(f"{scenario_ref}: Strategie forcee a REDUIRE (risque CRITIQUE)")

    # Valider les actions
    validated_actions = []
    if not actions:
        warnings.append(f"{scenario_ref}: Aucune action definie")
    elif len(actions) > 5:
        warnings.append(f"{scenario_ref}: Plus de 5 actions ({len(actions)}), seules les 5 premieres seront conservees")
        actions = actions[:5]

    for j, action in enumerate(actions):
        validated_action, action_errors, action_warnings = validate_action(action, scenario_ref, j, risk_level)
        if validated_action:
            validated_actions.append(validated_action)
        errors.extend(action_errors)
        warnings.extend(action_warnings)

    # Construire le scenario valide
    validated_scenario = {
        "scenario_ref": scenario_ref,
        "scenario_title": scenario.get("scenario_title", ""),
        "risk_level": risk_level,
        "strategie": strategie,
        "justification_strategie": scenario.get("justification_strategie", ""),
        "actions": validated_actions
    }

    return validated_scenario, errors, warnings


def validate_action(
    action: Dict[str, Any],
    scenario_ref: str,
    index: int,
    risk_level: str
) -> tuple:
    """
    Valide une action individuelle.

    Args:
        action: Donnees de l'action
        scenario_ref: Reference du scenario parent
        index: Index de l'action
        risk_level: Niveau de risque du scenario

    Returns:
        Tuple (validated_action, errors, warnings)
    """
    errors = []
    warnings = []

    # Champs requis
    label = action.get("label", "")
    if not label:
        warnings.append(f"{scenario_ref}/Action[{index}]: Label manquant")
        label = f"Action {index + 1}"

    description = action.get("description", "")
    if not description:
        warnings.append(f"{scenario_ref}/Action[{index}]: Description manquante")

    # Valider la categorie
    categorie = action.get("categorie", "PREVENTIVE")
    valid_categories = [c.value for c in ActionCategory]
    if categorie not in valid_categories:
        warnings.append(f"{scenario_ref}/Action[{index}]: Categorie invalide '{categorie}', defaut PREVENTIVE")
        categorie = "PREVENTIVE"

    # Valider la priorite
    priorite = action.get("priorite", "MOYENNE")
    valid_priorities = [p.value for p in ActionPriority]
    if priorite not in valid_priorities:
        warnings.append(f"{scenario_ref}/Action[{index}]: Priorite invalide '{priorite}', defaut MOYENNE")
        priorite = "MOYENNE"

    # Verifier coherence priorite/niveau de risque
    expected_priority = PRIORITY_BY_RISK_LEVEL.get(risk_level, ActionPriority.MOYENNE)
    if risk_level == "CRITIQUE" and priorite != "HAUTE":
        warnings.append(f"{scenario_ref}/Action[{index}]: Priorite devrait etre HAUTE pour risque CRITIQUE")

    # Risques couverts
    risques_couverts = action.get("risques_couverts", [scenario_ref])
    if not isinstance(risques_couverts, list):
        risques_couverts = [scenario_ref]

    validated_action = {
        "label": label,
        "description": description,
        "categorie": categorie,
        "priorite": priorite,
        "risques_couverts": risques_couverts,
        "responsable_suggere": action.get("responsable_suggere", ""),
        "delai_suggere": action.get("delai_suggere", "")
    }

    return validated_action, errors, warnings


# ==============================================================================
# GENERATION DES CODES D'ACTIONS
# ==============================================================================

def generate_action_codes(
    plan_data: Dict[str, Any],
    campaign_ref: str
) -> Dict[str, Any]:
    """
    Genere les codes d'actions normalises pour le plan de traitement.

    Format: ACT_RISK_<RefCamp>_<numero>
    Exemple: ACT_RISK_C2025-001_001

    Args:
        plan_data: Plan de traitement valide
        campaign_ref: Reference de la campagne/projet

    Returns:
        Plan avec codes d'actions ajoutes
    """
    action_counter = 0

    for scenario in plan_data.get("plan_traitement", []):
        for action in scenario.get("actions", []):
            action_counter += 1
            action["code_action"] = f"ACT_RISK_{campaign_ref}_{action_counter:03d}"

    return plan_data


# ==============================================================================
# EXPORT POUR LE MODULE ACTIONS
# ==============================================================================

def export_actions_for_module(
    plan_data: Dict[str, Any],
    campaign_id: str,
    project_id: str
) -> List[Dict[str, Any]]:
    """
    Exporte les actions au format du module Actions existant.

    Args:
        plan_data: Plan de traitement valide
        campaign_id: ID de la campagne
        project_id: ID du projet EBIOS

    Returns:
        Liste d'actions au format du module Actions
    """
    exported_actions = []

    for scenario in plan_data.get("plan_traitement", []):
        scenario_ref = scenario.get("scenario_ref", "")
        risk_level = scenario.get("risk_level", "MODERE")
        strategie = scenario.get("strategie", "REDUIRE")

        for action in scenario.get("actions", []):
            exported_action = {
                "titre": action.get("label", ""),
                "description": action.get("description", ""),
                "categorie": action.get("categorie", "PREVENTIVE"),
                "priorite": action.get("priorite", "MOYENNE"),
                "code_action": action.get("code_action", ""),
                "scenario_ref": scenario_ref,
                "risques_couverts": action.get("risques_couverts", []),
                "strategie_traitement": strategie,
                "niveau_risque": risk_level,
                "responsable_suggere": action.get("responsable_suggere", ""),
                "delai_suggere": action.get("delai_suggere", ""),
                "campaign_id": campaign_id,
                "project_id": project_id,
                "type": "PLAN_TRAITEMENT_EBIOS_RM",
                "status": "A_VALIDER"
            }
            exported_actions.append(exported_action)

    return exported_actions
