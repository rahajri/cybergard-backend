-- Migration: Création de la table domain_i18n pour les traductions des domaines
-- Date: 2025-11-09

CREATE TABLE IF NOT EXISTS domain_i18n (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain_id UUID NOT NULL REFERENCES domain(id) ON DELETE CASCADE,
    language_code VARCHAR(10) NOT NULL,
    title VARCHAR(500) NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Contrainte unique : un domaine ne peut avoir qu'une seule traduction par langue
    CONSTRAINT unique_domain_language UNIQUE (domain_id, language_code)
);

-- Index pour améliorer les performances de recherche
CREATE INDEX IF NOT EXISTS idx_domain_i18n_domain_id ON domain_i18n(domain_id);
CREATE INDEX IF NOT EXISTS idx_domain_i18n_language ON domain_i18n(language_code);

-- Commentaires
COMMENT ON TABLE domain_i18n IS 'Traductions des domaines dans différentes langues';
COMMENT ON COLUMN domain_i18n.domain_id IS 'Référence vers le domaine source';
COMMENT ON COLUMN domain_i18n.language_code IS 'Code ISO de la langue (en, es, de, it, pt, etc.)';
COMMENT ON COLUMN domain_i18n.title IS 'Titre du domaine traduit';
COMMENT ON COLUMN domain_i18n.description IS 'Description du domaine traduite (optionnelle)';
