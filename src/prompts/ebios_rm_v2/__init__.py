"""
Module de prompts EBIOS RM v2 (conforme ANSSI)

Ce module contient les prompts optimises pour la generation IA
selon la methodologie EBIOS Risk Manager de l'ANSSI.

Ateliers supportes:
- AT1: Cadrage et socle de securite (valeurs metier, biens supports, evenements redoutes)
- AT2: Sources de risque (a venir)
- AT3: Scenarios strategiques (a venir)
- AT4: Scenarios operationnels (a venir)
- AT5: Traitement des risques (a venir)
"""

from .at1_prompts import (
    get_at1_system_prompt,
    get_at1_user_prompt,
    AT1_JSON_SCHEMA,
    validate_at1_response
)

__all__ = [
    "get_at1_system_prompt",
    "get_at1_user_prompt",
    "AT1_JSON_SCHEMA",
    "validate_at1_response"
]
