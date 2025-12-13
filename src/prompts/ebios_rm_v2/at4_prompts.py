"""
Prompts EBIOS RM v2 - Atelier 4 : Scenarios Operationnels

Ce module genere les prompts pour l'AT4 en declinant les scenarios strategiques (AT3)
en scenarios operationnels detailles avec chaine d'attaque.

Sortie attendue (JSON strict):
{
    "scenarios_operationnels": [
        {
            "reference": "SO01",
            "titre": "string",
            "description": "string",
            "strategic_scenario_ref": "SS01",
            "vulnerabilite": "string",
            "biens_supports": ["BS01", "BS02"],
            "evenement_redoute": "ER01",
            "etapes": [
                {
                    "ordre": 1,
                    "resume": "string",
                    "details": "string",
                    "actifs_cibles": ["BS01"],
                    "type_etape": "INITIAL_ACCESS|EXECUTION|PERSISTENCE|MOVEMENT|IMPACT"
                }
            ],
            "gravite": 1-4,
            "vraisemblance": 1-4,
            "score_operationnel": 1-16
        }
    ]
}

Contraintes:
- 1 a 3 scenarios operationnels par scenario strategique
- 3 a 7 etapes par scenario
- gravite = gravite de l'ER du SSxx (pas recalculee)
- vraisemblance entre 1 et 4
- score_operationnel = gravite × vraisemblance
"""

import json
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# ==============================================================================
# SCHEMA JSON POUR VALIDATION
# ==============================================================================

AT4_JSON_SCHEMA = {
    "type": "object",
    "required": ["scenarios_operationnels"],
    "properties": {
        "scenarios_operationnels": {
            "type": "array",
            "minItems": 1,
            "maxItems": 20,  # Max si plusieurs SSxx
            "items": {
                "type": "object",
                "required": ["reference", "titre", "description", "strategic_scenario_ref",
                            "vulnerabilite", "biens_supports", "evenement_redoute",
                            "etapes", "gravite", "vraisemblance", "score_operationnel"],
                "properties": {
                    "reference": {"type": "string", "pattern": "^SO[0-9]{2}$"},
                    "titre": {"type": "string", "minLength": 10, "maxLength": 200},
                    "description": {"type": "string", "minLength": 20, "maxLength": 1000},
                    "strategic_scenario_ref": {"type": "string", "pattern": "^SS[0-9]{2}$"},
                    "vulnerabilite": {"type": "string", "minLength": 10, "maxLength": 500},
                    "biens_supports": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string"}
                    },
                    "evenement_redoute": {"type": "string"},
                    "etapes": {
                        "type": "array",
                        "minItems": 3,
                        "maxItems": 7,
                        "items": {
                            "type": "object",
                            "required": ["ordre", "resume", "details"],
                            "properties": {
                                "ordre": {"type": "integer", "minimum": 1, "maximum": 7},
                                "resume": {"type": "string", "minLength": 5, "maxLength": 150},
                                "details": {"type": "string", "minLength": 10, "maxLength": 500},
                                "actifs_cibles": {
                                    "type": "array",
                                    "items": {"type": "string"}
                                },
                                "type_etape": {
                                    "type": "string",
                                    "enum": ["INITIAL_ACCESS", "EXECUTION", "PERSISTENCE",
                                            "PRIVILEGE_ESCALATION", "DEFENSE_EVASION",
                                            "CREDENTIAL_ACCESS", "DISCOVERY", "MOVEMENT",
                                            "COLLECTION", "EXFILTRATION", "IMPACT"]
                                }
                            }
                        }
                    },
                    "gravite": {"type": "integer", "minimum": 1, "maximum": 4},
                    "vraisemblance": {"type": "integer", "minimum": 1, "maximum": 4},
                    "score_operationnel": {"type": "integer", "minimum": 1, "maximum": 16}
                }
            }
        }
    }
}

# Types d'etapes alignes sur MITRE ATT&CK
TYPES_ETAPES = [
    "INITIAL_ACCESS",
    "EXECUTION",
    "PERSISTENCE",
    "PRIVILEGE_ESCALATION",
    "DEFENSE_EVASION",
    "CREDENTIAL_ACCESS",
    "DISCOVERY",
    "MOVEMENT",
    "COLLECTION",
    "EXFILTRATION",
    "IMPACT"
]


# ==============================================================================
# SYSTEM PROMPT AT4 v2
# ==============================================================================

def get_at4_system_prompt(referentiels: Dict[str, str]) -> str:
    """
    Genere le system prompt pour l'AT4 avec les referentiels ANSSI.

    Args:
        referentiels: Dict contenant les referentiels formates:
            - guides: Extraits des guides ANSSI pour AT4
            - mitre_tactics: Tactiques MITRE (optionnel)

    Returns:
        System prompt complet pour l'AT4
    """

    return f"""Tu es un expert en cybersecurite appliquant la methode EBIOS Risk Manager de l'ANSSI.

# MISSION
Tu realises l'Atelier 4 (AT4) - Scenarios Operationnels.
Tu dois decliner des scenarios strategiques (AT3) en scenarios operationnels detailles avec chaine d'attaque.

# METHODOLOGIE ANSSI - ATELIER 4

{referentiels.get('guides', '')}

## Principe de l'AT4
- AT3 = "voix du risque" (Source de risque → Vulnerabilite strategique → Evenement redoute)
- AT4 = "mise en musique operationnelle" (enchainement d'etapes concretes d'attaque)

## Scenario Operationnel
Un scenario operationnel detaille COMMENT une attaque se deroule concretement.
Il part de la vulnerabilite strategique et aboutit a l'evenement redoute via une chaine d'etapes.

# TYPES D'ETAPES (inspires MITRE ATT&CK)
- INITIAL_ACCESS : Acces initial au systeme (phishing, exploit, VPN compromis)
- EXECUTION : Execution de code malveillant
- PERSISTENCE : Maintien de l'acces dans le temps
- PRIVILEGE_ESCALATION : Elevation de privileges
- DEFENSE_EVASION : Contournement des defenses
- CREDENTIAL_ACCESS : Vol d'identifiants
- DISCOVERY : Reconnaissance interne
- MOVEMENT : Deplacement lateral
- COLLECTION : Collecte de donnees
- EXFILTRATION : Exfiltration de donnees
- IMPACT : Impact final (chiffrement, destruction, divulgation)

# ECHELLE DE VRAISEMBLANCE (obligatoire)
- V1 (1) : Minime - Scenario theorique, tres peu probable
- V2 (2) : Significative - Possible mais necessite des conditions favorables
- V3 (3) : Forte - Probable, les conditions sont souvent reunies
- V4 (4) : Maximale - Tres probable, conditions frequemment reunies

# CONTRAINTES DE SORTIE
Tu DOIS retourner UNIQUEMENT un objet JSON valide avec la structure suivante.
Pas de texte avant ou apres le JSON. Pas de commentaires.

## Structure JSON obligatoire :
{{
    "scenarios_operationnels": [
        {{
            "reference": "SO01",
            "titre": "Titre explicite du scenario operationnel",
            "description": "Description generale du scenario operationnel",
            "strategic_scenario_ref": "SS01",
            "vulnerabilite": "Vulnerabilite strategique exploitee (reprise de AT3)",
            "biens_supports": ["BS01", "BS02"],
            "evenement_redoute": "ER01",
            "etapes": [
                {{
                    "ordre": 1,
                    "resume": "Resume court de l'etape",
                    "details": "Description detaillee de l'action de l'attaquant",
                    "actifs_cibles": ["BS01"],
                    "type_etape": "INITIAL_ACCESS"
                }},
                {{
                    "ordre": 2,
                    "resume": "Etape suivante...",
                    "details": "Details...",
                    "actifs_cibles": ["BS02"],
                    "type_etape": "MOVEMENT"
                }},
                {{
                    "ordre": 3,
                    "resume": "Etape finale d'impact",
                    "details": "Details de l'impact...",
                    "actifs_cibles": ["BS01", "BS02"],
                    "type_etape": "IMPACT"
                }}
            ],
            "gravite": 4,
            "vraisemblance": 3,
            "score_operationnel": 12
        }}
    ]
}}

## Contraintes de cardinalite :
- scenarios_operationnels : 1 a 3 par scenario strategique fourni
- etapes : entre 3 et 7 par scenario operationnel
- ordre : entiers croissants (1, 2, 3...)
- gravite : entier entre 1 et 4 (REPRENDRE la gravite de l'ER du scenario strategique)
- vraisemblance : entier entre 1 et 4
- score_operationnel : gravite × vraisemblance

## Regles de qualite :
1. Chaque scenario operationnel DOIT commencer par l'exploitation de la vulnerabilite strategique
2. Chaque scenario operationnel DOIT aboutir a l'evenement redoute du scenario strategique
3. Les biens supports utilises doivent etre ceux du scenario strategique
4. Les etapes doivent etre realistes et techniques
5. La derniere etape doit etre de type IMPACT et correspondre a l'evenement redoute
6. Le titre doit etre explicite et different du titre strategique
7. La description doit expliquer le "comment" de l'attaque

IMPORTANT: Ta reponse doit etre UNIQUEMENT le JSON, sans aucun texte supplementaire.
"""


# ==============================================================================
# USER PROMPT AT4 v2
# ==============================================================================

def get_at4_user_prompt(
    organization_name: str,
    organization_description: str,
    sector: Optional[str] = None,
    strategic_scenarios: Optional[List[Dict[str, Any]]] = None,
    at1_data: Optional[Dict[str, Any]] = None,
    additional_context: Optional[str] = None
) -> str:
    """
    Genere le user prompt pour l'AT4.

    Args:
        organization_name: Nom de l'organisation
        organization_description: Description de l'activite
        sector: Secteur d'activite (optionnel)
        strategic_scenarios: Liste des scenarios strategiques AT3
        at1_data: Donnees de l'Atelier 1 (biens supports pour reference)
        additional_context: Contexte supplementaire (optionnel)

    Returns:
        User prompt pour l'AT4
    """

    sector_info = f"\nSecteur d'activite : {sector}" if sector else ""
    context_info = f"\n\nContexte supplementaire :\n{additional_context}" if additional_context else ""

    # Formatter les scenarios strategiques
    ss_section = ""
    if strategic_scenarios:
        ss_items = []
        for i, ss in enumerate(strategic_scenarios):
            code = ss.get("code", f"SS{str(i+1).zfill(2)}")
            title = ss.get("title", ss.get("titre", "Sans titre"))

            # Source de risque
            source = ss.get("source_risque", {})
            if isinstance(source, dict):
                source_label = source.get("label", "Non definie")
                source_code = source.get("code", "")
            else:
                source_label = str(source) if source else "Non definie"
                source_code = ""

            # Vulnerabilite strategique
            vuln_code = ss.get("vulnerability_code", "")
            vuln_label = ss.get("vulnerability_label", ss.get("vulnerabilite", "Non definie"))

            # Biens supports
            assets = ss.get("assets_ids", ss.get("biens_supports", []))
            if isinstance(assets, list):
                assets_str = ", ".join([str(a) for a in assets])
            else:
                assets_str = str(assets)

            # Evenement redoute
            er = ss.get("feared_event", ss.get("evenement_redoute", {}))
            if isinstance(er, dict):
                er_label = er.get("label", "Non defini")
                er_code = er.get("code", ss.get("feared_event_id", ""))
            else:
                er_label = str(er) if er else "Non defini"
                er_code = ss.get("feared_event_id", "")

            # Gravite et scores
            severity = ss.get("severity", ss.get("gravite", 3))
            likelihood = ss.get("likelihood", ss.get("vraisemblance", 2))
            score = ss.get("score", ss.get("score_strategique", severity * likelihood))

            ss_item = f"""
### Scenario Strategique {code}
- **Titre** : {title}
- **Source de risque** : {source_label} {f'({source_code})' if source_code else ''}
- **Vulnerabilite strategique** : {vuln_code} - {vuln_label}
- **Biens supports** : {assets_str}
- **Evenement redoute** : {er_code} - {er_label}
- **Gravite** : {severity}/4
- **Vraisemblance strategique** : {likelihood}/4
- **Score strategique** : {score}
"""
            ss_items.append(ss_item)

        ss_section = f"""

# SCENARIOS STRATEGIQUES A DECLINER (AT3)

{chr(10).join(ss_items)}
"""

    # Formatter les biens supports de reference (AT1)
    bs_section = ""
    if at1_data:
        bs_list = at1_data.get("biens_supports", [])
        if bs_list:
            bs_items = [f"  - {bs.get('code', f'BS{str(i+1).zfill(2)}')} [{bs.get('type', 'N/A')}] : {bs.get('label', 'N/A')}"
                       for i, bs in enumerate(bs_list[:10])]
            bs_section = f"""

# REFERENCE DES BIENS SUPPORTS (AT1)

{chr(10).join(bs_items)}
"""

    return f"""Realise l'Atelier 4 EBIOS RM (Scenarios Operationnels) pour l'organisation suivante :

**Organisation** : {organization_name}
{sector_info}

**Description de l'activite** :
{organization_description}
{ss_section}
{bs_section}
{context_info}

# TACHE

Pour CHAQUE scenario strategique ci-dessus, genere 1 a 3 scenarios operationnels detailles.

Chaque scenario operationnel doit :
1. Commencer par l'exploitation de la vulnerabilite strategique
2. Detailler la chaine d'attaque en 3 a 7 etapes
3. Aboutir a l'evenement redoute du scenario strategique
4. REPRENDRE la gravite de l'evenement redoute (ne pas la modifier)
5. Proposer une vraisemblance operationnelle (1-4)
6. Calculer le score operationnel = gravite × vraisemblance

Respecte strictement le format JSON demande.
"""


# ==============================================================================
# VALIDATION DE LA REPONSE
# ==============================================================================

def validate_at4_response(response: str) -> Dict[str, Any]:
    """
    Valide et parse la reponse JSON de l'IA pour l'AT4.

    Args:
        response: Reponse brute de l'IA

    Returns:
        Dict avec:
            - valid: bool
            - data: dict (si valide)
            - errors: list (si invalide)
            - stats: dict (statistiques)
    """

    errors = []
    data = None

    # 1. Nettoyer la reponse (enlever markdown si present)
    cleaned = response.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    if cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    # 2. Parser le JSON
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        return {
            "valid": False,
            "data": None,
            "errors": [f"JSON invalide: {str(e)}"],
            "raw_response": response,
            "stats": {}
        }

    # 3. Valider la structure
    if "scenarios_operationnels" not in data:
        return {
            "valid": False,
            "data": data,
            "errors": ["Cle manquante: scenarios_operationnels"],
            "raw_response": response,
            "stats": {}
        }

    scenarios = data.get("scenarios_operationnels", [])
    so_count = len(scenarios)

    # 4. Valider les cardinalites
    if so_count < 1:
        errors.append(f"Aucun scenario operationnel genere")
    if so_count > 20:
        errors.append(f"Trop de scenarios operationnels: {so_count} (max: 20)")

    # 5. Valider et corriger chaque scenario
    total_etapes = 0
    for i, so in enumerate(scenarios):
        # Reference
        ref = so.get("reference", "")
        if not ref:
            so["reference"] = f"SO{str(i+1).zfill(2)}"
        elif not ref.startswith("SO"):
            so["reference"] = f"SO{str(i+1).zfill(2)}"

        # Champs obligatoires
        if not so.get("titre"):
            errors.append(f"Scenario [{i}]: titre manquant")
        if not so.get("description"):
            errors.append(f"Scenario [{i}]: description manquante")
        if not so.get("strategic_scenario_ref"):
            errors.append(f"Scenario [{i}]: strategic_scenario_ref manquant")
        if not so.get("vulnerabilite"):
            errors.append(f"Scenario [{i}]: vulnerabilite manquante")

        # Biens supports
        bs = so.get("biens_supports", [])
        if not bs or len(bs) == 0:
            errors.append(f"Scenario [{i}]: biens_supports manquants")

        # Evenement redoute
        if not so.get("evenement_redoute"):
            errors.append(f"Scenario [{i}]: evenement_redoute manquant")

        # Etapes
        etapes = so.get("etapes", [])
        etapes_count = len(etapes)
        total_etapes += etapes_count

        if etapes_count < 3:
            errors.append(f"Scenario [{i}]: trop peu d'etapes ({etapes_count}, min: 3)")
        elif etapes_count > 7:
            # Tronquer a 7 etapes
            so["etapes"] = etapes[:7]
            logger.warning(f"Scenario [{i}]: etapes tronquees de {etapes_count} a 7")

        # Valider chaque etape
        for j, etape in enumerate(so.get("etapes", [])):
            if not etape.get("ordre"):
                etape["ordre"] = j + 1
            if not etape.get("resume"):
                errors.append(f"Scenario [{i}] Etape [{j}]: resume manquant")
            if not etape.get("details"):
                errors.append(f"Scenario [{i}] Etape [{j}]: details manquants")

            # Type d'etape - valider ou corriger
            type_etape = etape.get("type_etape", "")
            if type_etape and type_etape not in TYPES_ETAPES:
                # Essayer de corriger
                type_upper = type_etape.upper().replace(" ", "_")
                if type_upper in TYPES_ETAPES:
                    etape["type_etape"] = type_upper
                else:
                    logger.warning(f"Scenario [{i}] Etape [{j}]: type_etape non standard '{type_etape}'")

        # Gravite
        gravite = so.get("gravite")
        if gravite is None:
            errors.append(f"Scenario [{i}]: gravite manquante")
        elif not isinstance(gravite, int) or gravite < 1 or gravite > 4:
            if isinstance(gravite, (int, float)):
                so["gravite"] = max(1, min(4, int(gravite)))
            else:
                errors.append(f"Scenario [{i}]: gravite invalide {gravite}")

        # Vraisemblance
        vraisemblance = so.get("vraisemblance")
        if vraisemblance is None:
            errors.append(f"Scenario [{i}]: vraisemblance manquante")
        elif not isinstance(vraisemblance, int) or vraisemblance < 1 or vraisemblance > 4:
            if isinstance(vraisemblance, (int, float)):
                so["vraisemblance"] = max(1, min(4, int(vraisemblance)))
            else:
                errors.append(f"Scenario [{i}]: vraisemblance invalide {vraisemblance}")

        # Score operationnel - recalculer pour coherence
        g = so.get("gravite", 0)
        v = so.get("vraisemblance", 0)
        if isinstance(g, int) and isinstance(v, int):
            expected_score = g * v
            actual_score = so.get("score_operationnel")
            if actual_score != expected_score:
                so["score_operationnel"] = expected_score
                logger.info(f"Scenario [{i}]: score_operationnel corrige de {actual_score} a {expected_score}")

    return {
        "valid": len(errors) == 0,
        "data": data,
        "errors": errors,
        "stats": {
            "scenarios_operationnels": so_count,
            "total_etapes": total_etapes,
            "avg_etapes_per_scenario": round(total_etapes / so_count, 1) if so_count > 0 else 0
        }
    }


# ==============================================================================
# FONCTION UTILITAIRE POUR GENERATION COMPLETE
# ==============================================================================

def build_at4_messages(
    referentiels: Dict[str, str],
    organization_name: str,
    organization_description: str,
    sector: Optional[str] = None,
    strategic_scenarios: Optional[List[Dict[str, Any]]] = None,
    at1_data: Optional[Dict[str, Any]] = None,
    additional_context: Optional[str] = None
) -> List[Dict[str, str]]:
    """
    Construit les messages complets pour l'appel IA AT4.

    Args:
        referentiels: Referentiels ANSSI formates (guides)
        organization_name: Nom de l'organisation
        organization_description: Description
        sector: Secteur (optionnel)
        strategic_scenarios: Scenarios strategiques AT3
        at1_data: Donnees AT1 pour reference biens supports
        additional_context: Contexte additionnel (optionnel)

    Returns:
        Liste de messages au format OpenAI/Ollama
    """

    return [
        {
            "role": "system",
            "content": get_at4_system_prompt(referentiels)
        },
        {
            "role": "user",
            "content": get_at4_user_prompt(
                organization_name,
                organization_description,
                sector,
                strategic_scenarios,
                at1_data,
                additional_context
            )
        }
    ]
