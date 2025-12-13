"""
Routes API pour les questions
Redirige vers les endpoints du module questionnaires
"""
from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.orm import Session
from sqlalchemy import text
from uuid import UUID
from typing import Optional, Dict
import logging
import os
import httpx
import json
import hashlib

from src.database import get_db
from src.schemas.questionnaire import QuestionGenerationRequest
from src.services.deepseek_question_generator import DeepSeekQuestionGenerator
from src.services.question_i18n_service import QuestionI18nService
from src.models import Question

# ✅ REDIS CACHE
from src.utils.redis_manager import redis_manager

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/generate", status_code=status.HTTP_200_OK)
async def generate_questions(req: QuestionGenerationRequest, db: Session = Depends(get_db)):
    """
    Génère des questions soit à partir d'un framework (exigences),
    soit à partir d'une sélection de points de contrôle.
    """
    # ✅ REDIS CACHE: Créer une clé de cache basée sur les paramètres
    cache_data = f"{req.mode}:{req.framework_id or ''}:{','.join(map(str, req.control_point_ids or []))}"
    cache_hash = hashlib.md5(cache_data.encode()).hexdigest()
    cache_key = f"ai:questions:{cache_hash}"
    force_refresh = getattr(req, 'force_refresh', False)

    # Vérifier le cache (sauf si force_refresh)
    if not force_refresh:
        cached_result = redis_manager.get(cache_key)
        if cached_result:
            logger.info(f"✅ Cache HIT pour génération questions: {req.mode}")
            return {"questions": cached_result, "cached": True}

    logger.info(f"⚠️ Cache MISS pour génération questions: {req.mode}")

    # Validation de mode + paramètres
    if req.mode == "framework":
        if not req.framework_id:
            raise HTTPException(status_code=422, detail="framework_id requis pour mode=framework")
        # Charger le framework (facultatif: name/version pour contexte prompt)
        fw = db.execute(
            text("SELECT id, name, version FROM framework WHERE id::text = :fid LIMIT 1"),
            {"fid": req.framework_id},
        ).mappings().first()
        if not fw:
            raise HTTPException(status_code=404, detail="Framework introuvable")

    elif req.mode == "control_points":
        if not req.control_point_ids:
            raise HTTPException(status_code=422, detail="control_point_ids requis pour mode=control_points")
    else:
        raise HTTPException(status_code=422, detail="mode invalide (attendu: framework | control_points)")

    # ✅ Instancier le générateur avec la session DB
    gen = DeepSeekQuestionGenerator(db_session=db)

    try:
        questions = await gen.generate_questions(req)
        questions_data = [q.dict() if hasattr(q, "dict") else q for q in questions]

        # ✅ REDIS CACHE: Mettre en cache pour 2h
        redis_manager.set(cache_key, questions_data, ttl=7200)
        logger.info(f"💾 Questions mises en cache pour: {req.mode}")

        return {"questions": questions_data, "cached": False}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Erreur pendant la génération de questions")
        raise HTTPException(status_code=500, detail="Erreur interne pendant la génération IA") from e


@router.post("/{question_id}/translate")
async def translate_question(
    question_id: str,
    target_language: str = Body(..., embed=True, description="Code langue cible (en, es, de, it, pt)"),
    db: Session = Depends(get_db)
):
    """
    Traduit une question vers une langue cible via IA (DeepSeek).

    Utilisé par le bouton "Traduire" dans l'interface de duplication de questionnaires.

    **Args:**
    - question_id: UUID de la question à traduire
    - target_language: Code langue (en, es, de, it, pt)

    **Returns:**
    - question_text: Texte traduit
    - help_text: Texte d'aide traduit (si présent)
    - saved: True si sauvegardé automatiquement
    """
    try:
        # Récupérer la question
        question = db.query(Question).filter(Question.id == UUID(question_id)).first()

        if not question:
            raise HTTPException(status_code=404, detail="Question non trouvée")

        # Vérifier si traduction existe déjà
        existing = QuestionI18nService.get_translation(db, question.id, target_language)
        if existing:
            logger.info(f"✅ Traduction existante retournée pour question {question_id}")
            return {
                "question_text": existing.question_text,
                "help_text": existing.help_text,
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

Translate the following French question into {target_lang_name}:

FRENCH QUESTION:
{question.question_text}
"""

        if question.help_text:
            prompt += f"""
FRENCH HELP TEXT:
{question.help_text}
"""

        prompt += f"""
INSTRUCTIONS:
- Translate accurately while preserving technical terminology
- Keep the same tone (formal/professional)
- Maintain any acronyms (ISO, GDPR, DPO, etc.)
- Return ONLY valid JSON with this structure:
{{
  "question_text": "translated question",
  "help_text": "translated help text or null"
}}

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
                    "content": "You are a professional translator. Always respond with valid JSON only."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": 0.3,
            "max_tokens": 500
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

        # Extraire le JSON
        start = content.find('{')
        end = content.rfind('}') + 1
        if start == -1 or end <= start:
            raise ValueError("Pas de JSON trouvé dans la réponse IA")

        json_str = content[start:end]
        translation = json.loads(json_str)

        logger.info(f"✅ Traduction générée: {question.question_text[:50]}... → {translation['question_text'][:50]}...")

        # Sauvegarder la traduction
        QuestionI18nService.create_translation(
            db=db,
            question_id=question.id,
            language_code=target_language,
            question_text=translation['question_text'],
            help_text=translation.get('help_text'),
            commit=True
        )

        return {
            "question_text": translation['question_text'],
            "help_text": translation.get('help_text'),
            "saved": True,
            "already_existed": False
        }

    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        logger.error(f"❌ Erreur parsing JSON de la réponse IA: {e}")
        raise HTTPException(
            status_code=500,
            detail="Erreur de format dans la réponse IA"
        )
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
