-- Afficher les 20 correspondances les plus faibles
SELECT 
    LEFT(q.question_text, 60) || '...' as question,
    m.official_code,
    LEFT(m.title, 50) as requirement,
    ROUND(m.keyword_match_score::numeric, 3) as score,
    CASE 
        WHEN m.keyword_match_score >= 0.5 THEN 'Ã¢Å“â€¦ Bon'
        WHEN m.keyword_match_score >= 0.3 THEN 'Ã¢Å¡Â Ã¯Â¸Â Moyen'
        ELSE 'Ã¢ÂÅ’ Faible'
    END as evaluation
FROM question_requirement_matches m
JOIN question q ON q.id = m.question_id
ORDER BY m.keyword_match_score ASC
LIMIT 20;