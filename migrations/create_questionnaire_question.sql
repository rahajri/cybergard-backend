-- Migration: Création de la table de liaison questionnaire_question
-- Date: 2025-11-09
-- But: Permettre à plusieurs questionnaires de partager les mêmes questions (many-to-many)

CREATE TABLE IF NOT EXISTS questionnaire_question (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    questionnaire_id UUID NOT NULL REFERENCES questionnaire(id) ON DELETE CASCADE,
    question_id UUID NOT NULL REFERENCES question(id) ON DELETE CASCADE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Contrainte unique : une question ne peut être ajoutée qu'une fois par questionnaire
    CONSTRAINT unique_questionnaire_question UNIQUE (questionnaire_id, question_id)
);

-- Index pour améliorer les performances
CREATE INDEX IF NOT EXISTS idx_qq_questionnaire ON questionnaire_question(questionnaire_id);
CREATE INDEX IF NOT EXISTS idx_qq_question ON questionnaire_question(question_id);
CREATE INDEX IF NOT EXISTS idx_qq_sort_order ON questionnaire_question(questionnaire_id, sort_order);

-- Commentaires
COMMENT ON TABLE questionnaire_question IS 'Table de liaison many-to-many entre questionnaires et questions';
COMMENT ON COLUMN questionnaire_question.questionnaire_id IS 'Référence vers le questionnaire';
COMMENT ON COLUMN questionnaire_question.question_id IS 'Référence vers la question';
COMMENT ON COLUMN questionnaire_question.sort_order IS 'Ordre d''affichage de la question dans ce questionnaire';

-- Migrer les données existantes depuis question.questionnaire_id vers questionnaire_question
INSERT INTO questionnaire_question (questionnaire_id, question_id, sort_order, created_at)
SELECT 
    questionnaire_id,
    id as question_id,
    sort_order,
    created_at
FROM question
WHERE questionnaire_id IS NOT NULL
ON CONFLICT (questionnaire_id, question_id) DO NOTHING;

-- NOTE: On garde la colonne questionnaire_id dans question pour compatibilité
-- mais elle sera progressivement obsolète au profit de questionnaire_question
