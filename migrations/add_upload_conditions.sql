-- Migration: Add upload conditions to questions
-- Description: Support conditional file upload based on answer values
-- Date: 2025-11-06

-- Ajouter une colonne pour les conditions d'upload
ALTER TABLE question
ADD COLUMN IF NOT EXISTS upload_conditions JSONB DEFAULT NULL;

-- Commentaire
COMMENT ON COLUMN question.upload_conditions IS 'Conditions requiring file upload based on answer values. Format: {"required_for_values": ["Oui", "Partiellement"], "attachment_types": ["evidence", "policy"], "min_files": 1, "help_text": "Veuillez joindre..."}';

-- Exemples de structures dans validation_rules (déjà existant)
COMMENT ON COLUMN question.validation_rules IS 'Validation rules for the question. Can include: min_length, max_length, min/max values, required patterns, upload requirements, etc.';

-- Index pour recherche rapide des questions avec upload obligatoire
CREATE INDEX IF NOT EXISTS idx_question_upload_required
ON question ((upload_conditions IS NOT NULL AND upload_conditions != 'null'::jsonb))
WHERE upload_conditions IS NOT NULL;

-- Mise à jour de la vue summary (si existe)
-- Pour inclure les infos d'upload
