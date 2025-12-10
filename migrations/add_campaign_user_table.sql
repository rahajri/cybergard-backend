-- ============================================================================
-- Migration : Ajout de la table campaign_user
-- Description : Table d'assignation des utilisateurs aux campagnes
-- Version: 1.0
-- Date: 2025-11-09
-- ============================================================================

-- Table : campaign_user (Assignations utilisateurs aux campagnes)
-- Permet d'assigner des utilisateurs à une campagne pour la gestion, notifications, etc.
CREATE TABLE IF NOT EXISTS campaign_user (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  campaign_id UUID NOT NULL REFERENCES campaign(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

  -- Rôle de l'utilisateur dans la campagne
  role VARCHAR(50) DEFAULT 'viewer',
  -- 'owner' | 'manager' | 'auditor' | 'viewer'

  -- Assignation
  assigned_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
  assigned_by UUID REFERENCES users(id),

  -- Statut
  is_active BOOLEAN DEFAULT true,

  UNIQUE(campaign_id, user_id)
);

-- Index pour campaign_user
CREATE INDEX IF NOT EXISTS idx_campaign_user_campaign ON campaign_user(campaign_id);
CREATE INDEX IF NOT EXISTS idx_campaign_user_user ON campaign_user(user_id);
CREATE INDEX IF NOT EXISTS idx_campaign_user_role ON campaign_user(role);
CREATE INDEX IF NOT EXISTS idx_campaign_user_active ON campaign_user(is_active);
CREATE INDEX IF NOT EXISTS idx_campaign_user_assigned_by ON campaign_user(assigned_by);

-- Contrainte de vérification pour le rôle
ALTER TABLE campaign_user DROP CONSTRAINT IF EXISTS chk_campaign_user_role;
ALTER TABLE campaign_user ADD CONSTRAINT chk_campaign_user_role
  CHECK (role IN ('owner', 'manager', 'auditor', 'viewer'));

-- ============================================================================

-- Commentaires sur la table
COMMENT ON TABLE campaign_user IS 'Assignations d''utilisateurs aux campagnes pour gestion et notifications';
COMMENT ON COLUMN campaign_user.role IS 'Rôle de l''utilisateur: owner, manager, auditor, viewer';
COMMENT ON COLUMN campaign_user.is_active IS 'Indique si l''assignation est active (permet de désactiver sans supprimer)';

-- ============================================================================
-- FIN DE LA MIGRATION
-- ============================================================================
