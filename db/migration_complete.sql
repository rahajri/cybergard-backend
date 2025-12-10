-- ================================================
-- SCRIPT DE RÉPARATION COMPLET - VERSION AUTONOME
-- ================================================

-- Configuration
SET client_encoding = 'UTF8';
SET client_min_messages = WARNING;
\timing on
\set ON_ERROR_STOP on

-- 🔒 TRANSACTION
BEGIN;

\echo '📊 Étape 1/9 : Diagnostic initial'
SELECT 
    'Questions orphelines' as metric,
    COUNT(*) as count
FROM question
WHERE questionnaire_id = 'd5c363e9-63c4-4bee-8b85-702bf29fd44d'
  AND requirement_id IS NULL;

\echo '🔄 Étape 2/9 : Création table mots-clés questions'
CREATE TEMP TABLE question_keywords AS
SELECT 
    q.id as question_id,
    q.question_text,
    q.framework_id,
    ARRAY_AGG(DISTINCT word) FILTER (WHERE LENGTH(word) > 5) as keywords
FROM question q,
     LATERAL regexp_split_to_table(LOWER(q.question_text), '\s+') AS word
WHERE q.questionnaire_id = 'd5c363e9-63c4-4bee-8b85-702bf29fd44d'
  AND q.requirement_id IS NULL
GROUP BY q.id, q.question_text, q.framework_id;

\echo '🔄 Étape 3/9 : Création table mots-clés exigences'
CREATE TEMP TABLE requirement_keywords AS
SELECT 
    r.id as requirement_id,
    r.official_code,
    r.title,
    r.requirement_text,
    r.framework_id,
    ARRAY_AGG(DISTINCT word) FILTER (WHERE LENGTH(word) > 5) as keywords
FROM requirement r,
     LATERAL regexp_split_to_table(LOWER(r.title || ' ' || r.requirement_text), '\s+') AS word
WHERE r.framework_id = '9d62babf-7ce4-4c69-800d-97a0fd0560df'
GROUP BY r.id, r.official_code, r.title, r.requirement_text, r.framework_id;

\echo '🔗 Étape 4/9 : Création table de correspondances'
CREATE TEMP TABLE question_requirement_matches AS
SELECT DISTINCT ON (qk.question_id)
    qk.question_id,
    rk.requirement_id,
    rk.official_code,
    rk.title,
    (
        COALESCE(ARRAY_LENGTH(ARRAY(
            SELECT UNNEST(qk.keywords) 
            INTERSECT 
            SELECT UNNEST(rk.keywords)
        ), 1), 0)::float / 
        NULLIF(ARRAY_LENGTH(qk.keywords, 1), 0)
    ) as keyword_match_score
FROM question_keywords qk
CROSS JOIN requirement_keywords rk
WHERE qk.framework_id = rk.framework_id
  AND (
      ARRAY_LENGTH(ARRAY(
          SELECT UNNEST(qk.keywords) 
          INTERSECT 
          SELECT UNNEST(rk.keywords)
      ), 1) >= 2
      OR qk.question_text ILIKE '%' || rk.title || '%'
      OR qk.question_text ILIKE '%' || rk.official_code || '%'
  )
ORDER BY qk.question_id, keyword_match_score DESC, LENGTH(rk.title) DESC;

\echo '📊 Étape 5/9 : Statistiques des correspondances'
SELECT 
    'Correspondances trouvées' as info,
    COUNT(*) as count,
    ROUND(AVG(keyword_match_score)::numeric, 3) as avg_score,
    ROUND(MIN(keyword_match_score)::numeric, 3) as min_score,
    ROUND(MAX(keyword_match_score)::numeric, 3) as max_score
FROM question_requirement_matches;

\echo '📋 Étape 6/9 : Aperçu top 10 correspondances'
SELECT 
    LEFT(q.question_text, 60) || '...' as question_preview,
    m.official_code,
    LEFT(m.title, 50) as requirement_title,
    ROUND(m.keyword_match_score::numeric, 3) as score
FROM question_requirement_matches m
JOIN question q ON q.id = m.question_id
ORDER BY m.keyword_match_score DESC
LIMIT 10;

\echo '⚡ Étape 7/9 : Mise à jour'

-- Créer un CTE avec les numéros de séquence
WITH question_numbers AS (
    SELECT 
        q.id as question_id,
        m.requirement_id,
        m.official_code,
        ROW_NUMBER() OVER (PARTITION BY m.requirement_id ORDER BY q.sort_order) as question_number
    FROM question q
    JOIN question_requirement_matches m ON m.question_id = q.id
)
UPDATE question q
SET 
    requirement_id = qn.requirement_id,
    question_code = 'Q-ISO27002-' || REPLACE(qn.official_code, '.', '') || '-' || LPAD(qn.question_number::text, 3, '0'),
    chapter = COALESCE(
        (SELECT COALESCE(dt.title, d.code) 
         FROM requirement r2
         LEFT JOIN domain d ON d.id = r2.domain_id
         LEFT JOIN domain_title dt ON dt.domain_id = d.id 
                                    AND dt.is_primary = true 
                                    AND dt.language = 'fr'
         WHERE r2.id = qn.requirement_id
         LIMIT 1),
        q.chapter
    ),
    questionnaire_status = 'draft',
    estimated_time_minutes = COALESCE(q.estimated_time_minutes, 5)
FROM question_numbers qn
WHERE q.id = qn.question_id;

\echo '📊 Étape 8/9 : Statistiques après mise à jour'
SELECT 
    'Total questions' as metric,
    COUNT(*) as count,
    '100%' as percentage
FROM question
WHERE questionnaire_id = 'd5c363e9-63c4-4bee-8b85-702bf29fd44d'

UNION ALL

SELECT 
    'Questions liées',
    COUNT(*),
    ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM question WHERE questionnaire_id = 'd5c363e9-63c4-4bee-8b85-702bf29fd44d'), 1)::text || '%'
FROM question
WHERE questionnaire_id = 'd5c363e9-63c4-4bee-8b85-702bf29fd44d'
  AND requirement_id IS NOT NULL

UNION ALL

SELECT 
    'Questions orphelines',
    COUNT(*),
    ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM question WHERE questionnaire_id = 'd5c363e9-63c4-4bee-8b85-702bf29fd44d'), 1)::text || '%'
FROM question
WHERE questionnaire_id = 'd5c363e9-63c4-4bee-8b85-702bf29fd44d'
  AND requirement_id IS NULL;

\echo '🔗 Étape 9/9 : Peuplement table de liaison'
INSERT INTO question_requirement (question_id, requirement_id)
SELECT q.id, q.requirement_id
FROM question q
WHERE q.questionnaire_id = 'd5c363e9-63c4-4bee-8b85-702bf29fd44d'
  AND q.requirement_id IS NOT NULL
ON CONFLICT DO NOTHING;

\echo '✅ Vérification liaisons créées'
SELECT 
    'Liaisons créées' as info,
    COUNT(*) as count
FROM question_requirement qr
JOIN question q ON q.id = qr.question_id
WHERE q.questionnaire_id = 'd5c363e9-63c4-4bee-8b85-702bf29fd44d';

\echo '📋 Échantillon de questions réparées (15 premières)'
SELECT 
    q.question_code,
    r.official_code,
    LEFT(q.question_text, 50) || '...' as question,
    LEFT(r.title, 40) as requirement
FROM question q
JOIN requirement r ON r.id = q.requirement_id
WHERE q.questionnaire_id = 'd5c363e9-63c4-4bee-8b85-702bf29fd44d'
ORDER BY r.official_code, q.question_code
LIMIT 15;

\echo '🧹 Nettoyage tables temporaires'
DROP TABLE IF EXISTS question_keywords;
DROP TABLE IF EXISTS requirement_keywords;
DROP TABLE IF EXISTS question_requirement_matches;

-- ✅ VALIDATION FINALE
COMMIT;

\echo ''
\echo '✅✅✅ Migration terminée avec succès! ✅✅✅'
\echo '📊 Vérifiez les statistiques ci-dessus'
\echo ''