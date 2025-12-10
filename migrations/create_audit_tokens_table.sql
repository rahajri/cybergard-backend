-- Migration : Création de la table audit_tokens pour les liens magiques
-- Date : 2025-11-10
-- Description : Table pour gérer les tokens JWT d'accès direct aux audits (sans mot de passe)

CREATE TABLE IF NOT EXISTS audit_tokens (
    -- Identifiant
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Token JWT
    token_jti UUID UNIQUE NOT NULL,  -- JWT ID (claim "jti") pour révocation ciblée
    token_hash TEXT UNIQUE NOT NULL,  -- Hash SHA256 du token complet pour vérification

    -- Informations utilisateur
    user_email TEXT NOT NULL,
    campaign_id UUID NOT NULL,  -- Lien vers la campagne d'audit
    questionnaire_id UUID,  -- Questionnaire spécifique (peut être NULL si multi-questionnaires)
    tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,

    -- Sécurité et limites
    expires_at TIMESTAMPTZ NOT NULL,  -- Date d'expiration du token
    max_uses INT DEFAULT 10,  -- Nombre maximal d'utilisations autorisées
    used_count INT DEFAULT 0,  -- Nombre d'utilisations effectuées
    revoked BOOLEAN DEFAULT FALSE,  -- Token révoqué manuellement

    -- Traçabilité
    first_used_at TIMESTAMPTZ,  -- Première utilisation du lien
    last_used_at TIMESTAMPTZ,  -- Dernière utilisation
    last_used_ip INET,  -- Dernière IP utilisée
    last_user_agent TEXT,  -- Dernier User-Agent

    -- Métadonnées
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Index pour optimiser les requêtes
CREATE INDEX IF NOT EXISTS idx_audit_tokens_jti ON audit_tokens(token_jti) WHERE revoked = FALSE;
CREATE INDEX IF NOT EXISTS idx_audit_tokens_hash ON audit_tokens(token_hash) WHERE revoked = FALSE;
CREATE INDEX IF NOT EXISTS idx_audit_tokens_email ON audit_tokens(user_email);
CREATE INDEX IF NOT EXISTS idx_audit_tokens_campaign ON audit_tokens(campaign_id);
CREATE INDEX IF NOT EXISTS idx_audit_tokens_expires ON audit_tokens(expires_at) WHERE revoked = FALSE;
CREATE INDEX IF NOT EXISTS idx_audit_tokens_tenant ON audit_tokens(tenant_id);

-- Trigger pour mettre à jour updated_at
CREATE OR REPLACE FUNCTION update_audit_tokens_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_audit_tokens_updated_at
    BEFORE UPDATE ON audit_tokens
    FOR EACH ROW
    EXECUTE FUNCTION update_audit_tokens_updated_at();

-- Commentaires
COMMENT ON TABLE audit_tokens IS 'Tokens JWT pour accès direct aux audits sans authentification par mot de passe';
COMMENT ON COLUMN audit_tokens.token_jti IS 'JWT ID unique pour identifier et révoquer un token spécifique';
COMMENT ON COLUMN audit_tokens.token_hash IS 'Hash SHA256 du token complet pour vérification en base';
COMMENT ON COLUMN audit_tokens.max_uses IS 'Nombre maximal d''utilisations du lien (défaut: 10)';
COMMENT ON COLUMN audit_tokens.revoked IS 'Token révoqué manuellement (sécurité ou fin de campagne)';
