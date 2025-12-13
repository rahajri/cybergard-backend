"""
Prompts EBIOS RM v2 - Atelier 2 : Sources de risques

Ce module genere les prompts pour l'AT2 en integrant les referentiels ANSSI
depuis les tables ref_ebios_sr (sources de risque) et ref_ebios_ov (objectifs vises).

Sortie attendue (JSON strict):
{
    "sources_risque": [
        {
            "label": "string",
            "categorie": "string",
            "description": "string",
            "objectifs_vises": ["string"],
            "pertinence": 1-4,
            "liens_evenements_redoutes": ["ER01", "ER02"]
        }
    ]
}

Contraintes:
- 4 a 10 sources de risque
- pertinence : entier entre 1 et 4
- objectifs_vises : 1 a 5 items
"""

import json
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# ==============================================================================
# SCHEMA JSON POUR VALIDATION
# ==============================================================================

AT2_JSON_SCHEMA = {
    "type": "object",
    "required": ["sources_risque"],
    "properties": {
        "sources_risque": {
            "type": "array",
            "minItems": 4,
            "maxItems": 10,
            "items": {
                "type": "object",
                "required": ["label", "categorie", "description", "objectifs_vises", "pertinence"],
                "properties": {
                    "label": {"type": "string", "minLength": 3, "maxLength": 150},
                    "categorie": {"type": "string", "minLength": 3, "maxLength": 50},
                    "description": {"type": "string", "minLength": 10, "maxLength": 500},
                    "objectifs_vises": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 5,
                        "items": {"type": "string", "minLength": 3, "maxLength": 100}
                    },
                    "pertinence": {"type": "integer", "minimum": 1, "maximum": 4},
                    "liens_evenements_redoutes": {
                        "type": "array",
                        "items": {"type": "string"}
                    }
                }
            }
        }
    }
}

# Categories standard de sources de risque (ref_ebios_sr)
CATEGORIES_SOURCES_RISQUE = [
    "CYBERCRIMINELS",
    "APT",           # Advanced Persistent Threat / Etat-nation
    "HACKTIVISTE",
    "EMPLOYE_MALVEILLANT",
    "EMPLOYE_NEGLIGENT",
    "FOURNISSEUR_NEGLIGENT",
    "PRESTATAIRE_MALVEILLANT",
    "CONCURRENT",
    "ACTEUR_OPPORTUNISTE",
    "TERRORISTE"
]


# ==============================================================================
# SYSTEM PROMPT AT2 v2
# ==============================================================================

def get_at2_system_prompt(referentiels: Dict[str, str]) -> str:
    """
    Genere le system prompt pour l'AT2 avec les referentiels ANSSI.

    Args:
        referentiels: Dict contenant les referentiels formates:
            - sources_risque: Texte des sources de risque de reference
            - objectifs_vises: Texte des objectifs vises de reference
            - guides: Extraits des guides ANSSI pour AT2

    Returns:
        System prompt complet pour l'AT2
    """

    return f"""Tu es un expert en analyse de risques cybernetiques selon la methodologie EBIOS Risk Manager de l'ANSSI.

# MISSION
Tu realises l'Atelier 2 (AT2) - Sources de risques.
Tu dois identifier les sources de risques pertinentes pour l'organisation et leurs objectifs vises.

# METHODOLOGIE ANSSI - ATELIER 2

{referentiels.get('guides', '')}

## Sources de Risques
Une source de risque est un element (personne, groupe, organisation) susceptible d'etre a l'origine d'un risque.
Elle se caracterise par sa motivation, ses ressources et son expertise.

**Referentiel ANSSI - Categories de sources de risques :**
{referentiels.get('sources_risque', 'Aucun referentiel disponible')}

## Objectifs Vises
Les objectifs vises representent les finalites de l'attaquant (gain financier, espionnage, sabotage, etc.).

**Referentiel ANSSI - Objectifs vises types :**
{referentiels.get('objectifs_vises', 'Aucun referentiel disponible')}

# ECHELLE DE PERTINENCE (obligatoire)
- P1 (1) : Faible - Source peu probable dans ce contexte
- P2 (2) : Moderee - Source possible mais peu motivee
- P3 (3) : Elevee - Source probable et motivee
- P4 (4) : Tres elevee - Source tres probable et fortement motivee

# CATEGORIES DE SOURCES (a utiliser)
- CYBERCRIMINELS : Groupes structures visant le gain financier
- APT : Etats-nations ou groupes sponsorises (espionnage, sabotage)
- HACKTIVISTE : Militants ideologiques (reputation, denonciation)
- EMPLOYE_MALVEILLANT : Personnel interne avec intentions malveillantes
- EMPLOYE_NEGLIGENT : Personnel interne sans intention malveillante
- FOURNISSEUR_NEGLIGENT : Prestataire/fournisseur non securise
- PRESTATAIRE_MALVEILLANT : Prestataire avec intentions malveillantes
- CONCURRENT : Concurrence deloyale, espionnage industriel
- ACTEUR_OPPORTUNISTE : Attaquant non cible (scan, exploitation automatisee)
- TERRORISTE : Groupes terroristes (destabilisation, sabotage)

# CONTRAINTES DE SORTIE
Tu DOIS retourner UNIQUEMENT un objet JSON valide avec la structure suivante.
Pas de texte avant ou apres le JSON. Pas de commentaires.

## Structure JSON obligatoire :
{{
    "sources_risque": [
        {{
            "label": "Nom explicite de la source de risque",
            "categorie": "CYBERCRIMINELS|APT|HACKTIVISTE|...",
            "description": "Description detaillee : motivations, ressources, expertise",
            "objectifs_vises": [
                "Objectif 1 (ex: Gain financier)",
                "Objectif 2 (ex: Vol de donnees)"
            ],
            "pertinence": 1,
            "liens_evenements_redoutes": ["ER01", "ER02"]
        }}
    ]
}}

## Contraintes de cardinalite :
- sources_risque : entre 4 et 10 elements
- objectifs_vises : entre 1 et 5 par source
- pertinence : entier entre 1 et 4

## Regles de qualite :
1. Adapter les sources au secteur d'activite de l'organisation
2. Mettre en avant les prestataires et sous-traitants si le perimetre le justifie
3. Chaque source doit avoir au moins un objectif vise pertinent
4. Les liens vers les evenements redoutes doivent etre coherents
5. Utiliser les categories standard ANSSI pour le champ "categorie"
6. La description doit expliquer POURQUOI cette source est pertinente

IMPORTANT: Ta reponse doit etre UNIQUEMENT le JSON, sans aucun texte supplementaire.
"""


# ==============================================================================
# USER PROMPT AT2 v2
# ==============================================================================

def get_at2_user_prompt(
    organization_name: str,
    organization_description: str,
    sector: Optional[str] = None,
    at1_data: Optional[Dict[str, Any]] = None,
    additional_context: Optional[str] = None
) -> str:
    """
    Genere le user prompt pour l'AT2.

    Args:
        organization_name: Nom de l'organisation
        organization_description: Description de l'activite
        sector: Secteur d'activite (optionnel)
        at1_data: Donnees de l'Atelier 1 (valeurs metier, biens supports, ER)
        additional_context: Contexte supplementaire (optionnel)

    Returns:
        User prompt pour l'AT2
    """

    sector_info = f"\nSecteur d'activite : {sector}" if sector else ""
    context_info = f"\n\nContexte supplementaire :\n{additional_context}" if additional_context else ""

    # Formatter les donnees AT1 si disponibles
    at1_section = ""
    if at1_data:
        vm_list = at1_data.get("valeurs_metier", [])
        bs_list = at1_data.get("biens_supports", [])
        er_list = at1_data.get("evenements_redoutes", [])

        # Valeurs metier resumees
        vm_text = "\n".join([
            f"  - {vm.get('label', 'N/A')}: {vm.get('description', '')[:100]}..."
            for vm in vm_list[:5]
        ]) if vm_list else "  Aucune valeur metier definie"

        # Biens supports resumes
        bs_text = "\n".join([
            f"  - [{bs.get('type', 'N/A')}] {bs.get('label', 'N/A')}"
            for bs in bs_list[:8]
        ]) if bs_list else "  Aucun bien support defini"

        # Evenements redoutes resumes avec gravite
        er_text = "\n".join([
            f"  - ER{str(i+1).zfill(2)}: {er.get('label', 'N/A')} (G{er.get('gravite', '?')})"
            for i, er in enumerate(er_list[:8])
        ]) if er_list else "  Aucun evenement redoute defini"

        at1_section = f"""

# DONNEES DE L'ATELIER 1 (Cadrage)

## Valeurs Metier identifiees :
{vm_text}

## Biens Supports critiques :
{bs_text}

## Evenements Redoutes (avec gravite) :
{er_text}
"""

    return f"""Realise l'Atelier 2 EBIOS RM (Sources de risques) pour l'organisation suivante :

**Organisation** : {organization_name}
{sector_info}

**Description de l'activite** :
{organization_description}
{at1_section}
{context_info}

Genere les sources de risques en JSON.
Pour chaque source, identifie :
- Son label et sa categorie
- Sa description (motivations, ressources)
- Ses objectifs vises
- Son niveau de pertinence (1-4)
- Les liens vers les evenements redoutes concernes (ERxx)

Respecte strictement le format demande et les contraintes de cardinalite.
"""


# ==============================================================================
# VALIDATION DE LA REPONSE
# ==============================================================================

def validate_at2_response(response: str) -> Dict[str, Any]:
    """
    Valide et parse la reponse JSON de l'IA pour l'AT2.

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
    if "sources_risque" not in data:
        return {
            "valid": False,
            "data": data,
            "errors": ["Cle manquante: sources_risque"],
            "raw_response": response,
            "stats": {}
        }

    sources = data.get("sources_risque", [])
    sr_count = len(sources)

    # 4. Valider les cardinalites
    if sr_count < 4:
        errors.append(f"Trop peu de sources de risque: {sr_count} (min: 4)")
    if sr_count > 10:
        errors.append(f"Trop de sources de risque: {sr_count} (max: 10)")

    # 5. Valider chaque source
    for i, sr in enumerate(sources):
        # Champs obligatoires
        if not sr.get("label"):
            errors.append(f"Source [{i}]: label manquant")
        if not sr.get("categorie"):
            errors.append(f"Source [{i}]: categorie manquante")
        if not sr.get("description"):
            errors.append(f"Source [{i}]: description manquante")

        # Objectifs vises
        objectifs = sr.get("objectifs_vises", [])
        if not objectifs or len(objectifs) == 0:
            errors.append(f"Source [{i}]: objectifs_vises manquants")
        elif len(objectifs) > 5:
            errors.append(f"Source [{i}]: trop d'objectifs_vises ({len(objectifs)}, max: 5)")

        # Pertinence
        pertinence = sr.get("pertinence")
        if pertinence is None:
            errors.append(f"Source [{i}]: pertinence manquante")
        elif not isinstance(pertinence, int) or pertinence < 1 or pertinence > 4:
            # Tenter de corriger (clamp)
            if isinstance(pertinence, (int, float)):
                sr["pertinence"] = max(1, min(4, int(pertinence)))
            else:
                errors.append(f"Source [{i}]: pertinence invalide {pertinence} (doit etre 1-4)")

        # Categorie - avertissement si non standard
        categorie = sr.get("categorie", "").upper()
        if categorie and categorie not in CATEGORIES_SOURCES_RISQUE:
            logger.warning(f"Source [{i}]: categorie non standard '{categorie}'")
            # Ne pas bloquer, juste avertir

    return {
        "valid": len(errors) == 0,
        "data": data,
        "errors": errors,
        "stats": {
            "sources_risque": sr_count,
            "total_objectifs": sum(len(sr.get("objectifs_vises", [])) for sr in sources)
        }
    }


# ==============================================================================
# FONCTION UTILITAIRE POUR GENERATION COMPLETE
# ==============================================================================

def build_at2_messages(
    referentiels: Dict[str, str],
    organization_name: str,
    organization_description: str,
    sector: Optional[str] = None,
    at1_data: Optional[Dict[str, Any]] = None,
    additional_context: Optional[str] = None
) -> List[Dict[str, str]]:
    """
    Construit les messages complets pour l'appel IA AT2.

    Args:
        referentiels: Referentiels ANSSI formates (sources_risque, objectifs_vises, guides)
        organization_name: Nom de l'organisation
        organization_description: Description
        sector: Secteur (optionnel)
        at1_data: Donnees AT1 (optionnel)
        additional_context: Contexte additionnel (optionnel)

    Returns:
        Liste de messages au format OpenAI/Ollama
    """

    return [
        {
            "role": "system",
            "content": get_at2_system_prompt(referentiels)
        },
        {
            "role": "user",
            "content": get_at2_user_prompt(
                organization_name,
                organization_description,
                sector,
                at1_data,
                additional_context
            )
        }
    ]
