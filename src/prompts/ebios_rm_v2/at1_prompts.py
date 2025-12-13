"""
Prompts EBIOS RM v2 - Atelier 1 : Cadrage et socle de securite

Ce module genere les prompts pour l'AT1 en integrant les referentiels ANSSI
depuis les tables ref_ebios_*.

Sortie attendue (JSON strict):
{
    "valeurs_metier": [
        {"label": "string", "description": "string", "besoins_securite": ["D", "I", "C", "T"]}
    ],
    "biens_supports": [
        {"label": "string", "type": "MATERIEL|LOGICIEL|RESEAU|ORGANISATION|HUMAIN|LOCAUX", "description": "string"}
    ],
    "evenements_redoutes": [
        {"label": "string", "description": "string", "critere": "D|I|C|T", "gravite": 1-4}
    ]
}

Contraintes:
- 3 a 7 valeurs metier
- 5 a 12 biens supports
- 5 a 12 evenements redoutes
"""

import json
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# ==============================================================================
# SCHEMA JSON POUR VALIDATION
# ==============================================================================

AT1_JSON_SCHEMA = {
    "type": "object",
    "required": ["valeurs_metier", "biens_supports", "evenements_redoutes"],
    "properties": {
        "valeurs_metier": {
            "type": "array",
            "minItems": 3,
            "maxItems": 7,
            "items": {
                "type": "object",
                "required": ["label", "description"],
                "properties": {
                    "label": {"type": "string", "minLength": 3, "maxLength": 100},
                    "description": {"type": "string", "minLength": 10, "maxLength": 500},
                    "besoins_securite": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["D", "I", "C", "T"]}
                    }
                }
            }
        },
        "biens_supports": {
            "type": "array",
            "minItems": 5,
            "maxItems": 12,
            "items": {
                "type": "object",
                "required": ["label", "type", "description"],
                "properties": {
                    "label": {"type": "string", "minLength": 3, "maxLength": 100},
                    "type": {
                        "type": "string",
                        "enum": ["MATERIEL", "LOGICIEL", "RESEAU", "ORGANISATION", "HUMAIN", "LOCAUX"]
                    },
                    "description": {"type": "string", "minLength": 10, "maxLength": 500}
                }
            }
        },
        "evenements_redoutes": {
            "type": "array",
            "minItems": 5,
            "maxItems": 12,
            "items": {
                "type": "object",
                "required": ["label", "description", "gravite"],
                "properties": {
                    "label": {"type": "string", "minLength": 5, "maxLength": 150},
                    "description": {"type": "string", "minLength": 10, "maxLength": 500},
                    "critere": {"type": "string", "enum": ["D", "I", "C", "T"]},
                    "gravite": {"type": "integer", "minimum": 1, "maximum": 4}
                }
            }
        }
    }
}


# ==============================================================================
# SYSTEM PROMPT AT1 v2
# ==============================================================================

def get_at1_system_prompt(referentiels: Dict[str, str]) -> str:
    """
    Genere le system prompt pour l'AT1 avec les referentiels ANSSI.

    Args:
        referentiels: Dict contenant les referentiels formates:
            - valeurs_metier: Texte des valeurs metier de reference
            - biens_supports: Texte des biens supports de reference
            - evenements_redoutes: Texte des evenements redoutes de reference
            - guides: Extraits des guides ANSSI pour AT1

    Returns:
        System prompt complet pour l'AT1
    """

    return f"""Tu es un expert en analyse de risques cybernetiques selon la methodologie EBIOS Risk Manager de l'ANSSI.

# MISSION
Tu realises l'Atelier 1 (AT1) - Cadrage et socle de securite.
Tu dois identifier les valeurs metier, biens supports et evenements redoutes pour l'organisation decrite.

# METHODOLOGIE ANSSI - ATELIER 1

{referentiels.get('guides', '')}

## Valeurs Metier
Les valeurs metier representent le patrimoine informationnel a proteger.
Elles peuvent etre de nature PROCESSUS ou INFORMATION.

**Referentiel ANSSI - Exemples de valeurs metier :**
{referentiels.get('valeurs_metier', 'Aucun referentiel disponible')}

## Biens Supports
Les biens supports sont les composants du SI qui supportent les valeurs metier.

**Referentiel ANSSI - Categories de biens supports :**
{referentiels.get('biens_supports', 'Aucun referentiel disponible')}

## Evenements Redoutes
Un evenement redoute correspond a une atteinte a une valeur metier.

**Referentiel ANSSI - Exemples d'evenements redoutes :**
{referentiels.get('evenements_redoutes', 'Aucun referentiel disponible')}

# ECHELLE DE GRAVITE (obligatoire)
- G1 (1) : Mineure - Aucun impact operationnel significatif
- G2 (2) : Significative - Mode degrade temporaire
- G3 (3) : Grave - Mode tres degrade, impacts financiers/juridiques
- G4 (4) : Critique - Survie de l'organisation menacee

# CRITERES DE SECURITE
- D : Disponibilite
- I : Integrite
- C : Confidentialite
- T : Tracabilite

# CONTRAINTES DE SORTIE
Tu DOIS retourner UNIQUEMENT un objet JSON valide avec la structure suivante.
Pas de texte avant ou apres le JSON. Pas de commentaires.

## Structure JSON obligatoire :
{{
    "valeurs_metier": [
        {{
            "label": "Nom court et explicite",
            "description": "Description detaillee de la valeur metier",
            "besoins_securite": ["D", "I", "C"]
        }}
    ],
    "biens_supports": [
        {{
            "label": "Nom du bien support",
            "type": "MATERIEL|LOGICIEL|RESEAU|ORGANISATION|HUMAIN|LOCAUX",
            "description": "Description du bien et son role"
        }}
    ],
    "evenements_redoutes": [
        {{
            "label": "Description de l'evenement redoute",
            "description": "Consequences detaillees",
            "critere": "D|I|C|T",
            "gravite": 1
        }}
    ]
}}

## Contraintes de cardinalite :
- valeurs_metier : entre 3 et 7 elements
- biens_supports : entre 5 et 12 elements
- evenements_redoutes : entre 5 et 12 elements

## Regles de qualite :
1. Chaque valeur metier doit etre liee a au moins un bien support
2. Chaque evenement redoute doit concerner au moins une valeur metier
3. La gravite doit etre coherente avec l'impact business
4. Les descriptions doivent etre specifiques au contexte de l'organisation
5. Utiliser le vocabulaire ANSSI (pas d'anglicismes inutiles)

IMPORTANT: Ta reponse doit etre UNIQUEMENT le JSON, sans aucun texte supplementaire.
"""


# ==============================================================================
# USER PROMPT AT1 v2
# ==============================================================================

def get_at1_user_prompt(
    organization_name: str,
    organization_description: str,
    sector: Optional[str] = None,
    additional_context: Optional[str] = None
) -> str:
    """
    Genere le user prompt pour l'AT1.

    Args:
        organization_name: Nom de l'organisation
        organization_description: Description de l'activite
        sector: Secteur d'activite (optionnel)
        additional_context: Contexte supplementaire (optionnel)

    Returns:
        User prompt pour l'AT1
    """

    sector_info = f"\nSecteur d'activite : {sector}" if sector else ""
    context_info = f"\n\nContexte supplementaire :\n{additional_context}" if additional_context else ""

    return f"""Realise l'Atelier 1 EBIOS RM pour l'organisation suivante :

**Organisation** : {organization_name}
{sector_info}

**Description de l'activite** :
{organization_description}
{context_info}

Genere les valeurs metier, biens supports et evenements redoutes en JSON.
Respecte strictement le format demande et les contraintes de cardinalite.
"""


# ==============================================================================
# VALIDATION DE LA REPONSE
# ==============================================================================

def validate_at1_response(response: str) -> Dict[str, Any]:
    """
    Valide et parse la reponse JSON de l'IA pour l'AT1.

    Args:
        response: Reponse brute de l'IA

    Returns:
        Dict avec:
            - valid: bool
            - data: dict (si valide)
            - errors: list (si invalide)

    Raises:
        ValueError: Si le JSON est invalide
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
            "raw_response": response
        }

    # 3. Valider la structure
    required_keys = ["valeurs_metier", "biens_supports", "evenements_redoutes"]
    for key in required_keys:
        if key not in data:
            errors.append(f"Cle manquante: {key}")

    if errors:
        return {"valid": False, "data": data, "errors": errors, "raw_response": response}

    # 4. Valider les cardinalites
    vm_count = len(data.get("valeurs_metier", []))
    bs_count = len(data.get("biens_supports", []))
    er_count = len(data.get("evenements_redoutes", []))

    if vm_count < 3:
        errors.append(f"Trop peu de valeurs metier: {vm_count} (min: 3)")
    if vm_count > 7:
        errors.append(f"Trop de valeurs metier: {vm_count} (max: 7)")

    if bs_count < 5:
        errors.append(f"Trop peu de biens supports: {bs_count} (min: 5)")
    if bs_count > 12:
        errors.append(f"Trop de biens supports: {bs_count} (max: 12)")

    if er_count < 5:
        errors.append(f"Trop peu d'evenements redoutes: {er_count} (min: 5)")
    if er_count > 12:
        errors.append(f"Trop d'evenements redoutes: {er_count} (max: 12)")

    # 5. Valider les types de biens supports
    valid_types = {"MATERIEL", "LOGICIEL", "RESEAU", "ORGANISATION", "HUMAIN", "LOCAUX"}
    for i, bs in enumerate(data.get("biens_supports", [])):
        if bs.get("type") not in valid_types:
            errors.append(f"Bien support [{i}]: type invalide '{bs.get('type')}'")

    # 6. Valider les gravites
    for i, er in enumerate(data.get("evenements_redoutes", [])):
        gravite = er.get("gravite")
        if gravite is None:
            errors.append(f"Evenement redoute [{i}]: gravite manquante")
        elif not isinstance(gravite, int) or gravite < 1 or gravite > 4:
            errors.append(f"Evenement redoute [{i}]: gravite invalide {gravite} (doit etre 1-4)")

    # 7. Valider les criteres de securite
    valid_criteres = {"D", "I", "C", "T"}
    for i, er in enumerate(data.get("evenements_redoutes", [])):
        critere = er.get("critere")
        if critere and critere not in valid_criteres:
            errors.append(f"Evenement redoute [{i}]: critere invalide '{critere}'")

    for i, vm in enumerate(data.get("valeurs_metier", [])):
        besoins = vm.get("besoins_securite", [])
        for besoin in besoins:
            if besoin not in valid_criteres:
                errors.append(f"Valeur metier [{i}]: besoin securite invalide '{besoin}'")

    return {
        "valid": len(errors) == 0,
        "data": data,
        "errors": errors,
        "stats": {
            "valeurs_metier": vm_count,
            "biens_supports": bs_count,
            "evenements_redoutes": er_count
        }
    }


# ==============================================================================
# FONCTION UTILITAIRE POUR GENERATION COMPLETE
# ==============================================================================

def build_at1_messages(
    referentiels: Dict[str, str],
    organization_name: str,
    organization_description: str,
    sector: Optional[str] = None,
    additional_context: Optional[str] = None
) -> List[Dict[str, str]]:
    """
    Construit les messages complets pour l'appel IA AT1.

    Args:
        referentiels: Referentiels ANSSI formates
        organization_name: Nom de l'organisation
        organization_description: Description
        sector: Secteur (optionnel)
        additional_context: Contexte additionnel (optionnel)

    Returns:
        Liste de messages au format OpenAI/DeepSeek
    """

    return [
        {
            "role": "system",
            "content": get_at1_system_prompt(referentiels)
        },
        {
            "role": "user",
            "content": get_at1_user_prompt(
                organization_name,
                organization_description,
                sector,
                additional_context
            )
        }
    ]
