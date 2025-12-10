-- Migration: Création de la table option_i18n pour les traductions d'options
-- Date: 2025-11-09
-- But: Stocker les traductions des options dans différentes langues

CREATE TABLE IF NOT EXISTS option_i18n (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    option_id UUID NOT NULL REFERENCES option(id) ON DELETE CASCADE,
    language_code VARCHAR(10) NOT NULL,
    translated_value VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Contrainte unique : une option ne peut avoir qu'une seule traduction par langue
    CONSTRAINT unique_option_language UNIQUE (option_id, language_code)
);

-- Index pour améliorer les performances
CREATE INDEX IF NOT EXISTS idx_option_i18n_option_id ON option_i18n(option_id);
CREATE INDEX IF NOT EXISTS idx_option_i18n_language ON option_i18n(language_code);

-- Commentaires
COMMENT ON TABLE option_i18n IS 'Traductions des options de réponse dans différentes langues';
COMMENT ON COLUMN option_i18n.option_id IS 'Référence vers l''option originale';
COMMENT ON COLUMN option_i18n.language_code IS 'Code de la langue (en, es, de, it, pt, etc.)';
COMMENT ON COLUMN option_i18n.translated_value IS 'Valeur de l''option traduite';
