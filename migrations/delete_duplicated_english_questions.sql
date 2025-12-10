-- Migration: Suppression des questions anglaises dupliquées
-- Date: 2025-11-09
-- But: Supprimer les questions dupliquées dans la table question après migration vers question_i18n

DO $$
DECLARE
    questions_to_delete INT;
    questionnaire_rec RECORD;
BEGIN
    -- Compter les questions à supprimer
    SELECT COUNT(*) INTO questions_to_delete
    FROM question q
    JOIN questionnaire qn ON qn.id = q.questionnaire_id
    WHERE qn.language_code = 'en';

    RAISE NOTICE 'Nombre de questions anglaises à supprimer: %', questions_to_delete;

    -- Supprimer les questions pour chaque questionnaire anglais
    FOR questionnaire_rec IN
        SELECT id, name, language_code
        FROM questionnaire
        WHERE language_code = 'en'
    LOOP
        RAISE NOTICE 'Suppression des questions du questionnaire: % (ID: %)',
            questionnaire_rec.name, questionnaire_rec.id;

        -- Supprimer les questions (CASCADE supprimera automatiquement question_option)
        DELETE FROM question
        WHERE questionnaire_id = questionnaire_rec.id;

        RAISE NOTICE '  -> Questions supprimées pour ce questionnaire';
    END LOOP;

    RAISE NOTICE 'Suppression terminée';
END $$;

-- Vérification
SELECT
    'Questions restantes dans questionnaires EN' as type,
    COUNT(*) as count
FROM question q
JOIN questionnaire qn ON qn.id = q.questionnaire_id
WHERE qn.language_code = 'en'

UNION ALL

SELECT
    'Traductions dans question_i18n' as type,
    COUNT(*) as count
FROM question_i18n
WHERE language_code = 'en'

UNION ALL

SELECT
    'Liens dans questionnaire_question (EN)' as type,
    COUNT(*) as count
FROM questionnaire_question qq
JOIN questionnaire qn ON qn.id = qq.questionnaire_id
WHERE qn.language_code = 'en';
