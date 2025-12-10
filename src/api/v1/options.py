"""
Endpoints API pour la gestion des options réutilisables
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.orm import Session
from typing import List, Optional
import logging
import os
import httpx
import json
from uuid import UUID

from src.database import get_db
from src.services.option_service import OptionService
from src.models.option import Option, OptionI18n

# ✅ REDIS CACHE
from src.utils.redis_manager import cache_result

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/options", tags=["options"])


@router.get("/suggestions")
@cache_result(ttl=1800, key_prefix="options_suggestions")  # ✅ Cache 30min
def get_option_suggestions(
    category: Optional[str] = Query(None, description="Filtrer par catégorie (yes_no, frequency, etc.)"),
    language: str = Query("fr", description="Code langue (fr, en, es, etc.)"),
    db: Session = Depends(get_db)
):
    """
    Liste toutes les options réutilisables pour l'autocomplete.

    Utilisé dans l'interface pour suggérer des options existantes lors de la création de questions.

    **Exemples de catégories :**
    - `yes_no` : Oui, Non, Partiellement, NSP, N/A
    - `frequency` : Quotidienne, Hebdomadaire, Mensuelle, etc.
    - `compliance` : Totalement conforme, Largement conforme, etc.

    **Réponse :**
    ```json
    [
      {
        "id": "uuid",
        "value_key": "yes",
        "value": "Oui",
        "default_value": "Oui",
        "category": "yes_no",
        "is_system": true
      },
      ...
    ]
    ```
    """
    try:
        options = OptionService.get_all_options(
            db=db,
            category=category,
            language=language
        )
        logger.info(f"📋 [OPTIONS_API] {len(options)} options retournées (category={category}, lang={language})")
        return options

    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération des options: {e}")
        raise HTTPException(status_code=500, detail="Erreur lors de la récupération des options")


@router.get("/categories")
def get_option_categories(
    db: Session = Depends(get_db)
):
    """
    Liste toutes les catégories d'options disponibles.

    **Réponse :**
    ```json
    [
      {"category": "yes_no", "count": 5},
      {"category": "frequency", "count": 6},
      {"category": "compliance", "count": 5}
    ]
    ```
    """
    try:
        from sqlalchemy import func
        from src.models.option import Option

        categories = db.query(
            Option.category,
            func.count(Option.id).label('count')
        ).group_by(Option.category).all()

        result = [
            {"category": cat, "count": count}
            for cat, count in categories
            if cat is not None
        ]

        logger.info(f"📋 [OPTIONS_API] {len(result)} catégories retournées")
        return result

    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération des catégories: {e}")
        raise HTTPException(status_code=500, detail="Erreur lors de la récupération des catégories")


@router.post("/{option_id}/translate")
async def translate_option(
    option_id: str,
    target_language: str = Body(..., embed=True, description="Code langue cible (en, es, de, it, pt)"),
    db: Session = Depends(get_db)
):
    """
    Traduit une option vers une langue cible via IA (DeepSeek).

    Utilisé par le bouton "Traduire" dans l'interface de gestion des options.

    **Args:**
    - option_id: UUID de l'option à traduire
    - target_language: Code langue (en, es, de, it, pt)

    **Returns:**
    - translated_value: Valeur traduite
    - saved: True si sauvegardé automatiquement
    - already_existed: True si la traduction existait déjà

    **Exemple:**
    ```bash
    curl -X POST http://localhost:8000/api/v1/options/{uuid}/translate \\
      -H "Content-Type: application/json" \\
      -d '{"target_language": "en"}'
    ```

    **Réponse:**
    ```json
    {
      "translated_value": "Yes",
      "saved": true,
      "already_existed": false
    }
    ```
    """
    try:
        # Récupérer l'option
        option = db.query(Option).filter(Option.id == UUID(option_id)).first()

        if not option:
            raise HTTPException(status_code=404, detail="Option non trouvée")

        # Vérifier si traduction existe déjà
        existing = db.query(OptionI18n).filter(
            OptionI18n.option_id == option.id,
            OptionI18n.language_code == target_language
        ).first()

        if existing:
            logger.info(f"✅ Traduction existante retournée pour option {option_id}")
            return {
                "translated_value": existing.translated_value,
                "saved": True,
                "already_existed": True
            }

        # Préparer le prompt pour DeepSeek
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise HTTPException(
                status_code=500,
                detail="DEEPSEEK_API_KEY non configurée"
            )

        language_names = {
            "en": "English",
            "es": "Spanish",
            "de": "German",
            "it": "Italian",
            "pt": "Portuguese"
        }

        target_lang_name = language_names.get(target_language, target_language)

        prompt = f"""You are a professional translator specialized in cybersecurity audit terminology.

Translate the following French option value into {target_lang_name}:

FRENCH VALUE: "{option.default_value}"

INSTRUCTIONS:
- Translate accurately while preserving the meaning
- Keep it concise (this is a form option)
- Maintain any technical terms
- Return ONLY the translated text, no quotes, no explanation

TRANSLATION:"""

        # Appeler DeepSeek API
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": "deepseek-chat",
            "messages": [
                {
                    "role": "system",
                    "content": "You are a professional translator. Always respond with ONLY the translation, no extra text."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": 0.3,
            "max_tokens": 100
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers=headers,
                json=payload
            )
            response.raise_for_status()

        result = response.json()
        content = result["choices"][0]["message"]["content"].strip()

        # Nettoyer les guillemets si présents
        translation = content.strip('"').strip("'")

        logger.info(f"✅ Traduction générée: {option.default_value} → {translation}")

        # Sauvegarder la traduction
        option_i18n = OptionI18n(
            option_id=option.id,
            language_code=target_language,
            translated_value=translation
        )
        db.add(option_i18n)
        db.commit()

        return {
            "translated_value": translation,
            "saved": True,
            "already_existed": False
        }

    except HTTPException:
        raise
    except httpx.HTTPStatusError as e:
        logger.error(f"❌ Erreur API DeepSeek: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur API DeepSeek: {e.response.status_code}"
        )
    except Exception as e:
        logger.exception(f"❌ Erreur lors de la traduction: {e}")
        raise HTTPException(
            status_code=500,
            detail="Erreur interne lors de la traduction"
        )
