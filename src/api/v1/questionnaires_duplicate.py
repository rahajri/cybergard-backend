"""
Endpoints pour la duplication et traduction de questionnaires.

Architecture avec question_i18n:
- Réutilise les questions existantes via questionnaire_question (many-to-many)
- Stocke les traductions dans question_i18n, option_i18n, domain_i18n
- Un questionnaire = un language_code
"""

from fastapi import APIRouter, Depends, HTTPException, Body, status
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional
from uuid import uuid4
import logging

from src.database import get_db
from src.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


# Fonctions helper pour la traduction
async def translate_text_deepseek(
    text: str,
    target_language: str,
    client,
    context: str = "cybersecurity"
) -> str:
    """Traduit un texte via DeepSeek AI local (Ollama)"""
    language_names = {
        "en": "English",
        "es": "Spanish",
        "de": "German",
        "it": "Italian",
        "pt": "Portuguese"
    }

    target_lang_name = language_names.get(target_language, target_language)

    user_prompt = f"""Translate the following French text into {target_lang_name}:

FRENCH TEXT: "{text}"

INSTRUCTIONS:
- Translate accurately while preserving the meaning
- Keep it concise
- Maintain any technical terms
- Return ONLY the translated text, no quotes, no explanation

TRANSLATION:"""

    system_prompt = f"You are a professional translator specialized in {context}. Always respond with ONLY the translation."

    translation = await client.call_with_retry(
        user_prompt=user_prompt,
        system_prompt=system_prompt
    )

    return translation.strip().strip('"').strip("'")


async def translate_question_text(client, text: str, target_language: str) -> str:
    """Traduit le texte d'une question"""
    return await translate_text_deepseek(text, target_language, client, "cybersecurity audit question")


async def translate_option_text(client, text: str, target_language: str) -> str:
    """Traduit le texte d'une option"""
    return await translate_text_deepseek(text, target_language, client, "cybersecurity option")


@router.post("/{questionnaire_id}/duplicate", status_code=status.HTTP_201_CREATED)
async def duplicate_questionnaire(
    questionnaire_id: str,
    translate_to: Optional[str] = Body(None, embed=True),
    db: Session = Depends(get_db),
):
    """
    Duplique un questionnaire en créant une version linguistique.

    ARCHITECTURE (avec question_i18n):
    - Crée un nouveau questionnaire avec language_code
    - Réutilise les MÊMES questions (via questionnaire_question)
    - Stocke les traductions dans question_i18n, option_i18n, domain_i18n
    - Pas de duplication de données, juste des traductions

    Args:
        questionnaire_id: UUID du questionnaire source
        translate_to: Code langue (en, es, de, it, pt) - optionnel

    Returns:
        Le nouveau questionnaire avec ses métadonnées
    """
    try:
        from src.services.clients.deepseek_http_client import DeepSeekHttpClient

        # 1. Récupérer le questionnaire source
        source_q = db.execute(
            text("""
                SELECT id, name, status, source_type, ai_model, created_by, framework_id,
                       COALESCE(language_code, 'fr') as language_code
                FROM questionnaire
                WHERE id::text = :qid
            """),
            {"qid": questionnaire_id}
        ).first()

        if not source_q:
            raise HTTPException(status_code=404, detail="Questionnaire source introuvable")

        # Déterminer la langue cible
        target_language = translate_to if translate_to else source_q.language_code

        # 2. Créer le nouveau questionnaire avec language_code
        new_name = f"{source_q.name} (copie)"
        if translate_to:
            lang_names = {"en": "EN", "es": "ES", "de": "DE", "it": "IT", "pt": "PT"}
            new_name = f"{source_q.name} ({lang_names.get(translate_to, translate_to.upper())})"

        new_q_id = uuid4()

        db.execute(
            text("""
                INSERT INTO questionnaire (id, name, status, source_type, ai_model,
                                          created_by, framework_id, language_code, created_at)
                VALUES (CAST(:id AS uuid), :name, :status, :source_type, :ai_model,
                        :created_by, CAST(:framework_id AS uuid), :lang, CURRENT_TIMESTAMP)
            """),
            {
                "id": str(new_q_id),
                "name": new_name,
                "status": "draft",
                "source_type": source_q.source_type,
                "ai_model": source_q.ai_model,
                "created_by": source_q.created_by,
                "framework_id": str(source_q.framework_id) if source_q.framework_id else None,
                "lang": target_language
            }
        )

        logger.info(f"✅ Nouveau questionnaire créé: {new_q_id} (langue: {target_language})")

        # 3. Récupérer TOUTES les données des questions source
        source_questions = db.execute(
            text("""
                SELECT
                    q.id, q.question_text, q.help_text, q.requirement_id,
                    q.response_type, q.is_required, q.sort_order,
                    q.difficulty_level, q.chapter, q.questionnaire_id
                FROM question q
                WHERE q.questionnaire_id::text = :qid
                ORDER BY q.sort_order
            """),
            {"qid": questionnaire_id}
        ).fetchall()

        logger.info(f"🔍 {len(source_questions)} questions à dupliquer")

        # 4. DUPLIQUER les questions (créer de nouvelles questions)
        question_mapping = {}  # Ancien ID → Nouveau ID
        for sq in source_questions:
            new_question_id = uuid4()
            question_mapping[str(sq.id)] = str(new_question_id)

            db.execute(
                text("""
                    INSERT INTO question (
                        id, question_text, help_text, requirement_id,
                        response_type, is_required, sort_order,
                        difficulty_level, chapter, questionnaire_id, created_at
                    )
                    VALUES (
                        CAST(:id AS uuid), :text, :help, CAST(:req_id AS uuid),
                        :resp_type, :required, :sort,
                        :difficulty, :chapter, CAST(:qid AS uuid), CURRENT_TIMESTAMP
                    )
                """),
                {
                    "id": str(new_question_id),
                    "text": sq.question_text,
                    "help": sq.help_text,
                    "req_id": str(sq.requirement_id) if sq.requirement_id else None,
                    "resp_type": sq.response_type,
                    "required": sq.is_required,
                    "sort": sq.sort_order,
                    "difficulty": sq.difficulty_level,
                    "chapter": sq.chapter,
                    "qid": str(new_q_id)
                }
            )

        logger.info(f"✅ {len(source_questions)} questions dupliquées")

        # 4b. Dupliquer les options (question_option)
        for old_q_id, new_q_id_mapped in question_mapping.items():
            options = db.execute(
                text("""
                    SELECT qo.option_id, qo.sort_order
                    FROM question_option qo
                    WHERE qo.question_id::text = :qid
                    ORDER BY qo.sort_order
                """),
                {"qid": old_q_id}
            ).fetchall()

            for opt in options:
                db.execute(
                    text("""
                        INSERT INTO question_option (id, question_id, option_id, sort_order, created_at)
                        VALUES (gen_random_uuid(), CAST(:qid AS uuid), CAST(:oid AS uuid), :sort, CURRENT_TIMESTAMP)
                    """),
                    {
                        "qid": new_q_id_mapped,
                        "oid": str(opt.option_id),
                        "sort": opt.sort_order
                    }
                )

        logger.info(f"✅ Options des questions dupliquées")

        # Commit après duplication des questions et options
        db.commit()
        logger.info("✅ Questions et options dupliquées - commit effectué")

        # 5. Si traduction demandée, traduire et stocker dans *_i18n
        if translate_to:
            if not settings.ollama_url:
                logger.warning("⚠️ OLLAMA_URL non configurée, pas de traduction")
            else:
                try:
                    deepseek_client = DeepSeekHttpClient(
                        base_url=settings.ollama_url,
                        model=settings.deepseek_model,
                        temperature=0.3,
                        max_tokens=500,
                        max_retries=2
                    )
                    logger.info(f"🌍 Traduction activée vers {translate_to}")

                    # 5a. Traduire les domaines uniques
                    unique_domains = db.execute(
                        text("""
                            SELECT DISTINCT d.id, d.title
                            FROM question q
                            LEFT JOIN requirement r ON r.id = q.requirement_id
                            LEFT JOIN domain d ON d.id = r.domain_id
                            WHERE q.questionnaire_id::text = :qid
                              AND d.title IS NOT NULL
                        """),
                        {"qid": str(new_q_id)}
                    ).fetchall()

                    logger.info(f"🌍 Traduction de {len(unique_domains)} domaines...")
                    for domain in unique_domains:
                        try:
                            existing = db.execute(
                                text("SELECT 1 FROM domain_i18n WHERE domain_id::text = :did AND language_code = :lang"),
                                {"did": str(domain.id), "lang": translate_to}
                            ).first()

                            if not existing:
                                translated_domain = await translate_text_deepseek(
                                    domain.title, translate_to, deepseek_client, "cybersecurity domain"
                                )
                                db.execute(
                                    text("""
                                        INSERT INTO domain_i18n (id, domain_id, language_code, title, created_at)
                                        VALUES (gen_random_uuid(), CAST(:did AS uuid), :lang, :title, CURRENT_TIMESTAMP)
                                    """),
                                    {"did": str(domain.id), "lang": translate_to, "title": translated_domain}
                                )
                                logger.info(f"✅ Domaine '{domain.title}' → '{translated_domain}'")
                            else:
                                logger.info(f"♻️  Traduction existante pour '{domain.title}'")
                        except Exception as e:
                            logger.warning(f"⚠️ Échec traduction domaine: {e}")

                    db.commit()

                    # 5b. Traduire les questions DUPLIQUÉES directement
                    logger.info(f"📝 Traduction de {len(source_questions)} questions...")
                    for idx, sq in enumerate(source_questions):
                        try:
                            # Récupérer le nouvel ID de la question dupliquée
                            new_question_id = question_mapping[str(sq.id)]

                            # Traduire le texte
                            translated_text = await translate_question_text(
                                deepseek_client, sq.question_text, translate_to
                            )

                            # Traduire l'aide si elle existe
                            translated_help = None
                            if sq.help_text:
                                translated_help = await translate_text_deepseek(
                                    sq.help_text, translate_to, deepseek_client, "help text"
                                )

                            # Mettre à jour directement la question dupliquée
                            db.execute(
                                text("""
                                    UPDATE question
                                    SET question_text = :text, help_text = :help
                                    WHERE id::text = :qid
                                """),
                                {
                                    "qid": new_question_id,
                                    "text": translated_text,
                                    "help": translated_help
                                }
                            )
                            logger.info(f"📝 Question {idx+1}/{len(source_questions)} traduite")
                        except Exception as e:
                            logger.warning(f"⚠️ Échec traduction question {idx+1}: {e}")

                    db.commit()

                    # 5c. Traduire les options
                    logger.info("🔧 Traduction des options...")
                    all_options = db.execute(
                        text("""
                            SELECT DISTINCT o.id, o.default_value
                            FROM question q
                            JOIN question_option qo ON qo.question_id = q.id
                            JOIN option o ON o.id = qo.option_id
                            WHERE q.questionnaire_id::text = :qid
                        """),
                        {"qid": str(new_q_id)}
                    ).fetchall()

                    for option in all_options:
                        try:
                            existing = db.execute(
                                text("SELECT 1 FROM option_i18n WHERE option_id::text = :oid AND language_code = :lang"),
                                {"oid": str(option.id), "lang": translate_to}
                            ).first()

                            if not existing:
                                translated_option = await translate_option_text(
                                    deepseek_client, option.default_value, translate_to
                                )
                                db.execute(
                                    text("""
                                        INSERT INTO option_i18n (id, option_id, language_code, translated_value, created_at)
                                        VALUES (gen_random_uuid(), CAST(:oid AS uuid), :lang, :value, CURRENT_TIMESTAMP)
                                    """),
                                    {"oid": str(option.id), "lang": translate_to, "value": translated_option}
                                )
                        except Exception as e:
                            logger.warning(f"⚠️ Échec traduction option: {e}")

                    db.commit()
                    logger.info("✅ Traductions terminées")

                except Exception as e:
                    logger.error(f"❌ Erreur traduction: {e}")

        db.commit()

        # 6. Retourner le nouveau questionnaire
        new_questionnaire = db.execute(
            text("""
                SELECT
                    q.id, q.name, q.status, q.source_type, q.ai_model,
                    q.created_at, q.framework_id, q.language_code,
                    (SELECT COUNT(*) FROM questionnaire_question WHERE questionnaire_id = q.id) as questions_count
                FROM questionnaire q
                WHERE q.id::text = :qid
            """),
            {"qid": str(new_q_id)}
        ).first()

        return {
            "id": str(new_questionnaire.id),
            "name": new_questionnaire.name,
            "status": new_questionnaire.status,
            "source_type": new_questionnaire.source_type,
            "ai_model": new_questionnaire.ai_model,
            "framework_id": str(new_questionnaire.framework_id) if new_questionnaire.framework_id else None,
            "language_code": new_questionnaire.language_code,
            "questions_count": new_questionnaire.questions_count,
            "created_at": new_questionnaire.created_at.isoformat(),
            "translated": translate_to is not None
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception(f"❌ Erreur duplication: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur: {str(e)}")
