# NOUVELLE LOGIQUE DE DUPLICATION - À intégrer dans questionnaires.py

# Remplace toute la logique de duplication actuelle (lignes 899-1196 environ)
# Cette nouvelle approche NE DUPLIQUE PAS les questions, mais utilise question_i18n

"""
        # 3. Récupérer toutes les questions du questionnaire source (juste les IDs)
        source_questions = db.execute(
            text("""
                SELECT id, question_text, help_text, requirement_id
                FROM question
                WHERE questionnaire_id::text = :qid
                ORDER BY sort_order
            """),
            {"qid": questionnaire_id}
        ).fetchall()

        logger.info(f"🔍 {len(source_questions)} questions du questionnaire source")

        # 4. Si traduction demandée, préparer le client DeepSeek et traduire
        if translate_to:
            from src.config import settings
            from src.services.clients.deepseek_http_client import DeepSeekHttpClient

            if not settings.ollama_url:
                logger.warning("⚠️ OLLAMA_URL non configurée, duplication sans traduction")
                translate_to = None
            else:
                try:
                    deepseek_client = DeepSeekHttpClient(
                        base_url=settings.ollama_url,
                        model=settings.deepseek_model,
                        temperature=0.3,
                        max_tokens=500,
                        max_retries=2
                    )
                    logger.info(f"🌍 Traduction activée vers {translate_to} via {settings.ollama_url}")

                    # 4a. Traduire les domaines uniques et les stocker dans domain_i18n
                    unique_domains = db.execute(
                        text("""
                            SELECT DISTINCT d.id, d.title
                            FROM question q
                            LEFT JOIN requirement r ON r.id = q.requirement_id
                            LEFT JOIN domain d ON d.id = r.domain_id
                            WHERE q.questionnaire_id::text = :qid
                              AND d.title IS NOT NULL
                        """),
                        {"qid": questionnaire_id}
                    ).fetchall()

                    logger.info(f"🌍 Traduction de {len(unique_domains)} domaines uniques...")
                    for domain in unique_domains:
                        try:
                            # Vérifier si traduction existe
                            existing_translation = db.execute(
                                text("""
                                    SELECT title FROM domain_i18n
                                    WHERE domain_id::text = :domain_id AND language_code = :lang
                                """),
                                {"domain_id": str(domain.id), "lang": translate_to}
                            ).first()

                            if not existing_translation:
                                # Traduire
                                translated_domain = await translate_text_deepseek(
                                    domain.title,
                                    translate_to,
                                    deepseek_client,
                                    context="cybersecurity domain name"
                                )

                                # Insérer dans domain_i18n
                                db.execute(
                                    text("""
                                        INSERT INTO domain_i18n (id, domain_id, language_code, title, created_at)
                                        VALUES (gen_random_uuid(), :domain_id, :lang, :title, CURRENT_TIMESTAMP)
                                        ON CONFLICT (domain_id, language_code)
                                        DO UPDATE SET title = :title, updated_at = CURRENT_TIMESTAMP
                                    """),
                                    {"domain_id": domain.id, "lang": translate_to, "title": translated_domain}
                                )
                                logger.info(f"✅ Domaine '{domain.title}' → '{translated_domain}'")
                            else:
                                logger.info(f"♻️  Traduction existante pour domaine '{domain.title}'")

                        except Exception as e:
                            logger.warning(f"⚠️ Échec traduction domaine '{domain.title}': {e}")

                    db.commit()  # Commit les traductions de domaines
                    logger.info(f"✅ {len(unique_domains)} domaines traduits")

                    # 4b. Traduire les questions et stocker dans question_i18n
                    logger.info(f"📝 Traduction de {len(source_questions)} questions...")
                    for idx, source_question in enumerate(source_questions):
                        try:
                            # Vérifier si traduction existe
                            existing_question_i18n = db.execute(
                                text("""
                                    SELECT question_text FROM question_i18n
                                    WHERE question_id::text = :qid AND language_code = :lang
                                """),
                                {"qid": str(source_question.id), "lang": translate_to}
                            ).first()

                            if not existing_question_i18n:
                                # Traduire question_text
                                translated_text = await translate_question_text(
                                    deepseek_client,
                                    source_question.question_text,
                                    translate_to
                                )

                                # Traduire help_text si existe
                                translated_help = None
                                if source_question.help_text:
                                    translated_help = await translate_text_deepseek(
                                        source_question.help_text,
                                        translate_to,
                                        deepseek_client,
                                        context="cybersecurity help text"
                                    )

                                # Insérer dans question_i18n
                                db.execute(
                                    text("""
                                        INSERT INTO question_i18n (id, question_id, language_code, question_text, help_text, created_at)
                                        VALUES (gen_random_uuid(), :qid, :lang, :text, :help, CURRENT_TIMESTAMP)
                                    """),
                                    {
                                        "qid": source_question.id,
                                        "lang": translate_to,
                                        "text": translated_text,
                                        "help": translated_help
                                    }
                                )

                                logger.info(f"📝 Question {idx+1}/{len(source_questions)} traduite")
                            else:
                                logger.info(f"♻️  Traduction existante pour question {idx+1}")

                        except Exception as e:
                            logger.warning(f"⚠️ Échec traduction question {idx+1}: {e}")

                    db.commit()  # Commit les traductions de questions
                    logger.info(f"✅ {len(source_questions)} questions traduites et sauvegardées")

                    # 4c. Traduire les options et stocker dans option_i18n
                    logger.info(f"🔧 Traduction des options...")
                    all_options = db.execute(
                        text("""
                            SELECT DISTINCT o.id, o.default_value
                            FROM question_option qo
                            JOIN option o ON o.id = qo.option_id
                            JOIN question q ON q.id = qo.question_id
                            WHERE q.questionnaire_id::text = :qid
                        """),
                        {"qid": questionnaire_id}
                    ).fetchall()

                    for option in all_options:
                        try:
                            existing_option_i18n = db.execute(
                                text("""
                                    SELECT value FROM option_i18n
                                    WHERE option_id::text = :oid AND language_code = :lang
                                """),
                                {"oid": str(option.id), "lang": translate_to}
                            ).first()

                            if not existing_option_i18n:
                                translated_option = await translate_option_text(
                                    deepseek_client,
                                    option.default_value,
                                    translate_to
                                )

                                db.execute(
                                    text("""
                                        INSERT INTO option_i18n (id, option_id, language_code, value, created_at)
                                        VALUES (gen_random_uuid(), :oid, :lang, :value, CURRENT_TIMESTAMP)
                                    """),
                                    {"oid": option.id, "lang": translate_to, "value": translated_option}
                                )

                        except Exception as e:
                            logger.warning(f"⚠️ Échec traduction option: {e}")

                    db.commit()
                    logger.info(f"✅ Options traduites")

                except Exception as e:
                    logger.error(f"❌ Erreur initialisation client DeepSeek: {e}")
                    translate_to = None

        # 5. Le nouveau questionnaire est prêt (il pointe vers les mêmes questions)
        # Les traductions sont stockées dans question_i18n, option_i18n, domain_i18n
        # et seront récupérées automatiquement par le GET endpoint selon language_code

        db.commit()
        logger.info(f"✅ Questionnaire {questionnaire_id} dupliqué avec succès -> {new_q_id}")

        # 6. Retourner le nouveau questionnaire
        new_questionnaire = db.execute(
            text("""
                SELECT
                    q.id, q.name, q.status, q.source_type, q.ai_model,
                    q.created_at, q.framework_id, q.language_code,
                    (SELECT COUNT(*) FROM question WHERE questionnaire_id = q.id) as questions_count
                FROM questionnaire q
                WHERE q.id = :qid
            """),
            {"qid": new_q_id}
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
        logger.exception(f"❌ Erreur duplication questionnaire: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur lors de la duplication: {str(e)}")
"""
