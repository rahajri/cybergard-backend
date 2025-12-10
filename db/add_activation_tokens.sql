-- Migration: Ajout de la table activation_tokens pour l'activation de compte avec Keycloak
-- Date: 2025-01-04
-- Description: Crée une table pour stocker les tokens d'activation de compte envoyés par email

-- Créer la table activation_tokens si elle n'existe pas
CREATE TABLE IF NOT EXISTS activation_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token VARCHAR(255) NOT NULL UNIQUE,
    is_used BOOLEAN NOT NULL DEFAULT FALSE,
    used_at TIMESTAMP WITH TIME ZONE,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Index pour améliorer les performances
CREATE INDEX IF NOT EXISTS idx_activation_tokens_token ON activation_tokens(token);
CREATE INDEX IF NOT EXISTS idx_activation_tokens_user_id ON activation_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_activation_tokens_expires_at ON activation_tokens(expires_at);
CREATE INDEX IF NOT EXISTS idx_activation_tokens_is_used ON activation_tokens(is_used);

-- Commentaires pour la documentation
COMMENT ON TABLE activation_tokens IS 'Tokens d''activation de compte envoyés par email';
COMMENT ON COLUMN activation_tokens.id IS 'Identifiant unique du token';
COMMENT ON COLUMN activation_tokens.user_id IS 'Identifiant de l''utilisateur';
COMMENT ON COLUMN activation_tokens.token IS 'Token unique d''activation (UUID)';
COMMENT ON COLUMN activation_tokens.is_used IS 'Indique si le token a été utilisé';
COMMENT ON COLUMN activation_tokens.used_at IS 'Date et heure d''utilisation du token';
COMMENT ON COLUMN activation_tokens.expires_at IS 'Date et heure d''expiration du token';
COMMENT ON COLUMN activation_tokens.created_at IS 'Date de création du token';
COMMENT ON COLUMN activation_tokens.updated_at IS 'Date de dernière modification';

-- Trigger pour mettre à jour updated_at automatiquement
CREATE OR REPLACE FUNCTION update_activation_tokens_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER activation_tokens_updated_at
    BEFORE UPDATE ON activation_tokens
    FOR EACH ROW
    EXECUTE FUNCTION update_activation_tokens_updated_at();

-- Exemple de nettoyage automatique des tokens expirés (à exécuter périodiquement)
-- DELETE FROM activation_tokens WHERE expires_at < NOW() - INTERVAL '30 days';

COMMENT ON TRIGGER activation_tokens_updated_at ON activation_tokens IS 'Met à jour automatiquement updated_at lors d''une modification';
