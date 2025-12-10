-- Migration: Ajout de language_code au questionnaire
-- Date: 2025-11-09

-- Ajouter la colonne language_code (défaut 'fr' pour les questionnaires existants)
ALTER TABLE questionnaire 
ADD COLUMN IF NOT EXISTS language_code VARCHAR(10) DEFAULT 'fr';

-- Créer un index pour améliorer les performances
CREATE INDEX IF NOT EXISTS idx_questionnaire_language ON questionnaire(language_code);

-- Commentaire
COMMENT ON COLUMN questionnaire.language_code IS 'Code ISO de la langue du questionnaire (fr, en, es, de, it, pt, etc.)';
