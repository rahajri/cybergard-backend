-- ================================================
-- ENRICHISSEMENT DES QUESTIONS
-- Remplir validation_rules, evidence_types, etc.
-- ================================================

BEGIN;

-- 📊 État initial
SELECT 
    'État AVANT enrichissement' as phase,
    COUNT(*) as total_questions,
    COUNT(*) FILTER (WHERE validation_rules::text = '{}') as rules_vides,
    COUNT(*) FILTER (WHERE evidence_types::text = '[]') as evidence_vides,
    COUNT(*) FILTER (WHERE ai_params IS NULL) as params_null
FROM question
WHERE questionnaire_id = 'd5c363e9-63c4-4bee-8b85-702bf29fd44d';

-- ⚡ 1️⃣ Remplir validation_rules selon response_type
UPDATE question
SET validation_rules = 
    CASE response_type
        WHEN 'yes_no' THEN 
            '{"requires_comment_if_no": true, "requires_evidence_if_no": true}'::jsonb
        
        WHEN 'single_choice' THEN 
            '{"requires_selection": true}'::jsonb
        
        WHEN 'multiple_choice' THEN 
            '{"min_selections": 1}'::jsonb
        
        WHEN 'rating' THEN 
            '{"min": 1, "max": 5, "requires_comment_if_low": true}'::jsonb
        
        WHEN 'number' THEN 
            '{"min": 0, "max": 100, "type": "integer"}'::jsonb
        
        WHEN 'date' THEN 
            '{"format": "YYYY-MM-DD", "min_date": "2020-01-01"}'::jsonb
        
        WHEN 'open' THEN 
            '{"min_length": 10, "max_length": 500}'::jsonb
        
        ELSE 
            '{}'::jsonb
    END
WHERE questionnaire_id = 'd5c363e9-63c4-4bee-8b85-702bf29fd44d'
  AND validation_rules::text = '{}';

-- ⚡ 2️⃣ Remplir evidence_types selon difficulty_level
UPDATE question
SET evidence_types = 
    CASE 
        WHEN difficulty_level IN ('hard', 'critical') THEN 
            '["document", "screenshot", "policy", "procedure"]'::jsonb
        
        WHEN difficulty_level = 'medium' THEN 
            '["document", "screenshot"]'::jsonb
        
        ELSE 
            '["document"]'::jsonb
    END
WHERE questionnaire_id = 'd5c363e9-63c4-4bee-8b85-702bf29fd44d'
  AND evidence_types::text = '[]';

-- ⚡ 3️⃣ Remplir ai_params (traçabilité IA)
UPDATE question
SET ai_params = jsonb_build_object(
    'model', ai_model,
    'temperature', 0.7,
    'max_tokens', 2000,
    'generation_mode', generation_source,
    'confidence_threshold', 0.6
)
WHERE questionnaire_id = 'd5c363e9-63c4-4bee-8b85-702bf29fd44d'
  AND ai_params IS NULL
  AND ai_generated = true;

-- ⚡ 4️⃣ Générer generation_prompt (reconstitué)
UPDATE question
SET generation_prompt = 
    'Générer une question d''audit pour l''exigence ' || 
    COALESCE((SELECT r.official_code FROM requirement r WHERE r.id = question.requirement_id), '[N/A]') ||
    ' : ' ||
    COALESCE((SELECT LEFT(r.title, 80) FROM requirement r WHERE r.id = question.requirement_id), '[N/A]')
WHERE questionnaire_id = 'd5c363e9-63c4-4bee-8b85-702bf29fd44d'
  AND generation_prompt IS NULL
  AND requirement_id IS NOT NULL;

-- ⚡ 5️⃣ Ajuster estimated_time_minutes selon difficulty
UPDATE question
SET estimated_time_minutes = 
    CASE difficulty_level
        WHEN 'easy' THEN 2
        WHEN 'basic' THEN 3
        WHEN 'medium' THEN 5
        WHEN 'hard' THEN 10
        WHEN 'critical' THEN 15
        ELSE 5
    END
WHERE questionnaire_id = 'd5c363e9-63c4-4bee-8b85-702bf29fd44d'
  AND (estimated_time_minutes IS NULL OR estimated_time_minutes <= 2);

-- 📊 État final
SELECT 
    'État APRÈS enrichissement' as phase,
    COUNT(*) as total_questions,
    COUNT(*) FILTER (WHERE validation_rules::text = '{}') as rules_vides,
    COUNT(*) FILTER (WHERE evidence_types::text = '[]') as evidence_vides,
    COUNT(*) FILTER (WHERE ai_params IS NULL) as params_null,
    COUNT(*) FILTER (WHERE generation_prompt IS NOT NULL) as avec_prompt,
    ROUND(AVG(estimated_time_minutes)) as temps_moyen_minutes
FROM question
WHERE questionnaire_id = 'd5c363e9-63c4-4bee-8b85-702bf29fd44d';

-- 📋 Échantillon de questions enrichies
SELECT 
    question_code,
    response_type,
    difficulty_level,
    estimated_time_minutes,
    validation_rules::text as rules,
    evidence_types::text as evidence,
    CASE WHEN ai_params IS NOT NULL THEN '✅' ELSE '❌' END as ai_params,
    CASE WHEN generation_prompt IS NOT NULL THEN '✅' ELSE '❌' END as prompt
FROM question
WHERE questionnaire_id = 'd5c363e9-63c4-4bee-8b85-702bf29fd44d'
ORDER BY sort_order
LIMIT 10;

COMMIT;

\echo '✅ Enrichissement terminé avec succès!'