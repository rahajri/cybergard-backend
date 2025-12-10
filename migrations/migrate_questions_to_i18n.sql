-- Migration: Déplacer les questions traduites vers question_i18n
-- Date: 2025-11-09
-- But: Migrer les questions dupliquées en anglais vers la table question_i18n

-- 1. Identifier les questionnaires en anglais et leurs questions
-- 2. Créer les entrées dans question_i18n
-- 3. Lier les questionnaires anglais aux questions françaises d'origine

DO $$
DECLARE
    questionnaire_rec RECORD;
    question_rec RECORD;
    original_question_id UUID;
BEGIN
    -- Pour chaque questionnaire en anglais
    FOR questionnaire_rec IN
        SELECT id, name, language_code
        FROM questionnaire
        WHERE language_code = 'en'
    LOOP
        RAISE NOTICE 'Traitement du questionnaire: % (ID: %)', questionnaire_rec.name, questionnaire_rec.id;

        -- Pour chaque question de ce questionnaire
        FOR question_rec IN
            SELECT id, question_text, help_text, requirement_id, response_type,
                   is_required, sort_order, difficulty_level, chapter
            FROM question
            WHERE questionnaire_id = questionnaire_rec.id
        LOOP
            -- Trouver la question française d'origine (même requirement_id, même sort_order)
            SELECT q.id INTO original_question_id
            FROM question q
            JOIN questionnaire qn ON qn.id = q.questionnaire_id
            WHERE qn.language_code = 'fr'
              AND q.requirement_id = question_rec.requirement_id
              AND q.sort_order = question_rec.sort_order
            LIMIT 1;

            IF original_question_id IS NOT NULL THEN
                -- Créer l'entrée dans question_i18n
                INSERT INTO question_i18n (id, question_id, language_code, question_text, help_text, created_at)
                VALUES (
                    gen_random_uuid(),
                    original_question_id,
                    'en',
                    question_rec.question_text,
                    question_rec.help_text,
                    CURRENT_TIMESTAMP
                )
                ON CONFLICT (question_id, language_code) DO UPDATE
                SET question_text = EXCLUDED.question_text,
                    help_text = EXCLUDED.help_text;

                -- Lier le questionnaire anglais à la question française
                INSERT INTO questionnaire_question (id, questionnaire_id, question_id, sort_order, created_at)
                VALUES (
                    gen_random_uuid(),
                    questionnaire_rec.id,
                    original_question_id,
                    question_rec.sort_order,
                    CURRENT_TIMESTAMP
                )
                ON CONFLICT (questionnaire_id, question_id) DO NOTHING;

                RAISE NOTICE '  -> Question migrée: % -> %', question_rec.id, original_question_id;
            ELSE
                RAISE WARNING '  -> Question sans correspondance française: %', question_rec.id;
            END IF;
        END LOOP;
    END LOOP;

    RAISE NOTICE 'Migration terminée';
END $$;

-- Vérification
SELECT
    'Questionnaires EN' as type,
    COUNT(*) as count
FROM questionnaire
WHERE language_code = 'en'

UNION ALL

SELECT
    'Traductions dans question_i18n' as type,
    COUNT(*) as count
FROM question_i18n
WHERE language_code = 'en';

-- ATTENTION : Ne pas supprimer les anciennes questions dupliquées pour le moment
-- On les garde pour vérification. Suppression manuelle après validation.
