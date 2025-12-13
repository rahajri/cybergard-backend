"""
Prompts EBIOS RM v2 - Atelier 3 : Scenarios Strategiques

Ce module genere les prompts pour l'AT3 en integrant la notion obligatoire
de VULNERABILITE STRATEGIQUE selon la methode ANSSI.

Un scenario strategique = source de risque + vulnerabilite strategique +
                          biens supports + evenement redoute

Sortie attendue (JSON strict):
{
    "scenarios_strategiques": [
        {
            "code": "SS01",
            "title": "string",
            "description": "string",
            "source_risque_id": "SRxx",
            "vulnerability_code": "VS01",
            "vulnerability_label": "string",
            "assets_ids": ["BSxx", "BSyy"],
            "feared_event_id": "ERxx",
            "severity": 1-4,
            "likelihood": 1-4,
            "score": 1-16,
            "justification": "string"
        }
    ]
}

Contraintes:
- 3 a 6 scenarios strategiques
- vulnerabilite strategique obligatoire
- score = severity * likelihood
"""

import json
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# ==============================================================================
# SCHEMA JSON POUR VALIDATION
# ==============================================================================

AT3_JSON_SCHEMA = {
    "type": "object",
    "required": ["scenarios_strategiques"],
    "properties": {
        "scenarios_strategiques": {
            "type": "array",
            "minItems": 3,
            "maxItems": 6,
            "items": {
                "type": "object",
                "required": [
                    "code", "title", "description", "source_risque_id",
                    "vulnerability_code", "vulnerability_label",
                    "assets_ids", "feared_event_id",
                    "severity", "likelihood", "score"
                ],
                "properties": {
                    "code": {"type": "string", "pattern": "^SS\\d{2}$"},
                    "title": {"type": "string", "minLength": 10, "maxLength": 200},
                    "description": {"type": "string", "minLength": 20, "maxLength": 1000},
                    "source_risque_id": {"type": "string"},
                    "vulnerability_code": {"type": "string", "pattern": "^VS\\d{2}$"},
                    "vulnerability_label": {"type": "string", "minLength": 10, "maxLength": 300},
                    "assets_ids": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string"}
                    },
                    "feared_event_id": {"type": "string"},
                    "severity": {"type": "integer", "minimum": 1, "maximum": 4},
                    "likelihood": {"type": "integer", "minimum": 1, "maximum": 4},
                    "score": {"type": "integer", "minimum": 1, "maximum": 16},
                    "justification": {"type": "string", "maxLength": 500}
                }
            }
        }
    }
}


# ==============================================================================
# SYSTEM PROMPT AT3 v2
# ==============================================================================

def get_at3_system_prompt(referentiels: Dict[str, str]) -> str:
    """
    Genere le system prompt pour l'AT3 avec les referentiels ANSSI.

    Args:
        referentiels: Dict contenant les referentiels formates:
            - sources_risque: Texte des sources de risque
            - biens_supports: Texte des biens supports
            - evenements_redoutes: Texte des evenements redoutes
            - guides: Extraits des guides ANSSI pour AT3

    Returns:
        System prompt complet pour l'AT3
    """

    return f"""Tu es un expert en analyse de risques cybernetiques selon la methodologie EBIOS Risk Manager de l'ANSSI.

# MISSION
Tu realises l'Atelier 3 (AT3) - Scenarios Strategiques.
Tu dois construire des scenarios strategiques qui decrivent comment une source de risque
pourrait atteindre ses objectifs en exploitant des vulnerabilites.

# METHODOLOGIE ANSSI - ATELIER 3

{referentiels.get('guides', '')}

## Definition d'un Scenario Strategique
Un scenario strategique decrit le chemin d'attaque a haut niveau :
- QUI attaque (source de risque)
- COMMENT (vulnerabilite strategique exploitee)
- QUOI est cible (biens supports)
- QUEL impact (evenement redoute)

## CONCEPT CLE : Vulnerabilite Strategique (OBLIGATOIRE)
La vulnerabilite strategique est une faiblesse structurelle de l'organisation
qui permet a la source de risque d'atteindre son objectif.

**Exemples de vulnerabilites strategiques :**
- VS01 - Absence de segmentation reseau entre SI bureautique et industriel
- VS02 - Dependance critique a un prestataire unique sans plan B
- VS03 - Manque de sensibilisation des utilisateurs aux risques phishing
- VS04 - Obsolescence des systemes critiques sans correctifs de securite
- VS05 - Absence de chiffrement des donnees sensibles en transit

## Referentiels disponibles

**Sources de risque (AT2) :**
{referentiels.get('sources_risque', 'Aucun referentiel disponible')}

**Biens supports (AT1) :**
{referentiels.get('biens_supports', 'Aucun referentiel disponible')}

**Evenements redoutes (AT1) :**
{referentiels.get('evenements_redoutes', 'Aucun referentiel disponible')}

# ECHELLES DE SCORING

## Gravite (severity) - Impact sur les valeurs metier
- G1 (1) : Mineure - Aucun impact operationnel significatif
- G2 (2) : Significative - Mode degrade temporaire
- G3 (3) : Grave - Mode tres degrade, impacts financiers/juridiques
- G4 (4) : Critique - Survie de l'organisation menacee

## Vraisemblance (likelihood) - Probabilite de realisation
- V1 (1) : Peu probable - Scenario theorique, peu d'elements favorables
- V2 (2) : Possible - Scenario realiste mais conditions peu reunies
- V3 (3) : Probable - Conditions favorables, motivations fortes
- V4 (4) : Tres probable - Scenario quasi certain, precedents connus

## Score Strategique
score = severity × likelihood (1 a 16)
- 1-4 : Risque faible (vert)
- 5-8 : Risque modere (jaune)
- 9-12 : Risque important (orange)
- 13-16 : Risque critique (rouge)

# CONTRAINTES DE SORTIE
Tu DOIS retourner UNIQUEMENT un objet JSON valide avec la structure suivante.
Pas de texte avant ou apres le JSON. Pas de commentaires.

## Structure JSON obligatoire :
{{
    "scenarios_strategiques": [
        {{
            "code": "SS01",
            "title": "Titre explicite du scenario",
            "description": "Description narrative du chemin d'attaque strategique",
            "source_risque_id": "SR01",
            "vulnerability_code": "VS01",
            "vulnerability_label": "Description de la vulnerabilite strategique exploitee",
            "assets_ids": ["BS01", "BS02"],
            "feared_event_id": "ER01",
            "severity": 3,
            "likelihood": 2,
            "score": 6,
            "justification": "Justification du scoring"
        }}
    ]
}}

## Contraintes de cardinalite :
- scenarios_strategiques : entre 3 et 6 elements
- assets_ids : au moins 1 bien support par scenario
- vulnerability_label : OBLIGATOIRE et descriptif (min 10 caracteres)

## Regles de qualite :
1. Chaque scenario doit avoir une vulnerabilite strategique UNIQUE et pertinente
2. Le code vulnerabilite est sequentiel (VS01, VS02, ...)
3. Les liens source/biens/evenement doivent etre coherents
4. Le score DOIT etre egal a severity × likelihood
5. La justification doit expliquer les choix de scoring
6. Prioriser les scenarios a fort impact (score >= 9)

IMPORTANT: Ta reponse doit etre UNIQUEMENT le JSON, sans aucun texte supplementaire.
"""


# ==============================================================================
# USER PROMPT AT3 v2
# ==============================================================================

def get_at3_user_prompt(
    organization_name: str,
    organization_description: str,
    sector: Optional[str] = None,
    at1_data: Optional[Dict[str, Any]] = None,
    at2_data: Optional[Dict[str, Any]] = None,
    additional_context: Optional[str] = None
) -> str:
    """
    Genere le user prompt pour l'AT3.

    Args:
        organization_name: Nom de l'organisation
        organization_description: Description de l'activite
        sector: Secteur d'activite (optionnel)
        at1_data: Donnees de l'Atelier 1 (VM, BS, ER)
        at2_data: Donnees de l'Atelier 2 (sources de risque)
        additional_context: Contexte supplementaire (optionnel)

    Returns:
        User prompt pour l'AT3
    """

    sector_info = f"\nSecteur d'activite : {sector}" if sector else ""
    context_info = f"\n\nContexte supplementaire :\n{additional_context}" if additional_context else ""

    # Formatter les donnees AT1
    at1_section = ""
    if at1_data:
        vm_list = at1_data.get("valeurs_metier", [])
        bs_list = at1_data.get("biens_supports", [])
        er_list = at1_data.get("evenements_redoutes", [])

        # Biens supports avec identifiants
        bs_text = "\n".join([
            f"  - BS{str(i+1).zfill(2)}: [{bs.get('type', 'N/A')}] {bs.get('label', 'N/A')} - {bs.get('description', '')[:80]}..."
            for i, bs in enumerate(bs_list[:10])
        ]) if bs_list else "  Aucun bien support defini"

        # Evenements redoutes avec identifiants et gravite
        er_text = "\n".join([
            f"  - ER{str(i+1).zfill(2)}: {er.get('label', 'N/A')} (G{er.get('gravite', '?')}) - {er.get('critere', 'N/A')}"
            for i, er in enumerate(er_list[:10])
        ]) if er_list else "  Aucun evenement redoute defini"

        at1_section = f"""

# DONNEES DE L'ATELIER 1 (Cadrage)

## Biens Supports (BSxx) :
{bs_text}

## Evenements Redoutes (ERxx) :
{er_text}
"""

    # Formatter les donnees AT2
    at2_section = ""
    if at2_data:
        sr_list = at2_data.get("sources_risque", at2_data.get("risk_sources", []))

        sr_text = "\n".join([
            f"  - SR{str(i+1).zfill(2)}: {sr.get('label', 'N/A')} ({sr.get('categorie', sr.get('category', 'N/A'))}) - Pertinence: {sr.get('pertinence', sr.get('relevance', '?'))}/4"
            for i, sr in enumerate(sr_list[:8])
        ]) if sr_list else "  Aucune source de risque definie"

        at2_section = f"""

# DONNEES DE L'ATELIER 2 (Sources de Risques)

## Sources de Risques (SRxx) :
{sr_text}
"""

    return f"""Realise l'Atelier 3 EBIOS RM (Scenarios Strategiques) pour l'organisation suivante :

**Organisation** : {organization_name}
{sector_info}

**Description de l'activite** :
{organization_description}
{at1_section}
{at2_section}
{context_info}

Genere les scenarios strategiques en JSON.
Pour chaque scenario :
1. Selectionne une source de risque pertinente (SRxx)
2. Identifie une VULNERABILITE STRATEGIQUE unique (VSxx) - OBLIGATOIRE
3. Liste les biens supports cibles (BSxx)
4. Associe l'evenement redoute coherent (ERxx)
5. Evalue la gravite (1-4) et la vraisemblance (1-4)
6. Calcule le score strategique (gravite × vraisemblance)
7. Justifie le scoring

Respecte strictement le format demande et les contraintes.
"""


# ==============================================================================
# VALIDATION DE LA REPONSE
# ==============================================================================

def validate_at3_response(response: str) -> Dict[str, Any]:
    """
    Valide et parse la reponse JSON de l'IA pour l'AT3.

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
    if "scenarios_strategiques" not in data:
        return {
            "valid": False,
            "data": data,
            "errors": ["Cle manquante: scenarios_strategiques"],
            "raw_response": response,
            "stats": {}
        }

    scenarios = data.get("scenarios_strategiques", [])
    ss_count = len(scenarios)

    # 4. Valider les cardinalites
    if ss_count < 3:
        errors.append(f"Trop peu de scenarios strategiques: {ss_count} (min: 3)")
    if ss_count > 6:
        errors.append(f"Trop de scenarios strategiques: {ss_count} (max: 6)")

    # 5. Valider chaque scenario
    total_score = 0
    high_risk_count = 0

    for i, ss in enumerate(scenarios):
        code = ss.get("code", f"SS{str(i+1).zfill(2)}")

        # Champs obligatoires
        if not ss.get("title"):
            errors.append(f"{code}: title manquant")
        if not ss.get("description"):
            errors.append(f"{code}: description manquante")
        if not ss.get("source_risque_id"):
            errors.append(f"{code}: source_risque_id manquant")

        # Vulnerabilite strategique OBLIGATOIRE
        vuln_label = ss.get("vulnerability_label", "")
        if not vuln_label or len(vuln_label) < 10:
            errors.append(f"{code}: vulnerability_label manquant ou trop court (OBLIGATOIRE)")

        vuln_code = ss.get("vulnerability_code", "")
        if not vuln_code:
            # Auto-generer si manquant
            ss["vulnerability_code"] = f"VS{str(i+1).zfill(2)}"

        # Biens supports
        assets = ss.get("assets_ids", [])
        if not assets or len(assets) == 0:
            errors.append(f"{code}: assets_ids manquant (min 1 bien support)")

        # Evenement redoute
        if not ss.get("feared_event_id"):
            errors.append(f"{code}: feared_event_id manquant")

        # Scoring
        severity = ss.get("severity")
        likelihood = ss.get("likelihood")
        score = ss.get("score")

        if severity is None or not isinstance(severity, int) or severity < 1 or severity > 4:
            errors.append(f"{code}: severity invalide (doit etre 1-4)")
            severity = 2  # Valeur par defaut

        if likelihood is None or not isinstance(likelihood, int) or likelihood < 1 or likelihood > 4:
            errors.append(f"{code}: likelihood invalide (doit etre 1-4)")
            likelihood = 2  # Valeur par defaut

        # Verifier et corriger le score
        expected_score = severity * likelihood
        if score != expected_score:
            logger.warning(f"{code}: Score corrige de {score} a {expected_score}")
            ss["score"] = expected_score

        total_score += ss.get("score", expected_score)
        if ss.get("score", expected_score) >= 9:
            high_risk_count += 1

    return {
        "valid": len(errors) == 0,
        "data": data,
        "errors": errors,
        "stats": {
            "scenarios_strategiques": ss_count,
            "average_score": round(total_score / ss_count, 1) if ss_count > 0 else 0,
            "high_risk_count": high_risk_count
        }
    }


# ==============================================================================
# FONCTION UTILITAIRE POUR GENERATION COMPLETE
# ==============================================================================

def build_at3_messages(
    referentiels: Dict[str, str],
    organization_name: str,
    organization_description: str,
    sector: Optional[str] = None,
    at1_data: Optional[Dict[str, Any]] = None,
    at2_data: Optional[Dict[str, Any]] = None,
    additional_context: Optional[str] = None
) -> List[Dict[str, str]]:
    """
    Construit les messages complets pour l'appel IA AT3.

    Args:
        referentiels: Referentiels ANSSI formates
        organization_name: Nom de l'organisation
        organization_description: Description
        sector: Secteur (optionnel)
        at1_data: Donnees AT1 (optionnel)
        at2_data: Donnees AT2 (optionnel)
        additional_context: Contexte additionnel (optionnel)

    Returns:
        Liste de messages au format OpenAI/Ollama
    """

    return [
        {
            "role": "system",
            "content": get_at3_system_prompt(referentiels)
        },
        {
            "role": "user",
            "content": get_at3_user_prompt(
                organization_name,
                organization_description,
                sector,
                at1_data,
                at2_data,
                additional_context
            )
        }
    ]
