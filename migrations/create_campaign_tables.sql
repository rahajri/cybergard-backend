-- ============================================================================
-- Migration : Création des tables pour le module Campagnes
-- Version: 1.0
-- Date: 2025-11-09
-- ============================================================================

-- Table : campaign_scope (Périmètres Réutilisables)
-- Périmètres d'audit réutilisables entre campagnes
CREATE TABLE IF NOT EXISTS campaign_scope (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenant(id) ON DELETE CASCADE,
  name VARCHAR(255) NOT NULL,
  description TEXT,

  -- Entités incluses
  entity_ids UUID[] NOT NULL,

  -- Auditeurs assignés
  auditor_ids UUID[] NOT NULL,

  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
  created_by UUID REFERENCES users(id)
);

-- Index pour campaign_scope
CREATE INDEX IF NOT EXISTS idx_campaign_scope_tenant ON campaign_scope(tenant_id);
CREATE INDEX IF NOT EXISTS idx_campaign_scope_active ON campaign_scope(is_active);
CREATE INDEX IF NOT EXISTS idx_campaign_scope_created_by ON campaign_scope(created_by);

-- ============================================================================

-- Table : campaign (Campagnes d'audit)
CREATE TABLE IF NOT EXISTS campaign (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenant(id) ON DELETE CASCADE,
  questionnaire_id UUID REFERENCES questionnaire(id),
  title VARCHAR(255) NOT NULL,
  description TEXT,

  -- Scope
  scope_id UUID REFERENCES campaign_scope(id),

  -- Récurrence
  recurrence_type VARCHAR(50), -- 'once' | 'monthly' | 'quarterly' | 'yearly'
  recurrence_interval INTEGER DEFAULT 1,
  next_occurrence_date DATE,
  recurrence_end_date DATE,

  -- Statut
  status VARCHAR(50) DEFAULT 'draft',
  -- 'draft' | 'ongoing' | 'late' | 'frozen' | 'completed' | 'cancelled'

  -- Dates
  launch_date DATE,
  due_date DATE,
  frozen_date DATE,

  created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
  created_by UUID REFERENCES users(id)
);

-- Index pour campaign
CREATE INDEX IF NOT EXISTS idx_campaign_tenant ON campaign(tenant_id);
CREATE INDEX IF NOT EXISTS idx_campaign_questionnaire ON campaign(questionnaire_id);
CREATE INDEX IF NOT EXISTS idx_campaign_scope ON campaign(scope_id);
CREATE INDEX IF NOT EXISTS idx_campaign_status ON campaign(status);
CREATE INDEX IF NOT EXISTS idx_campaign_recurrence_type ON campaign(recurrence_type);
CREATE INDEX IF NOT EXISTS idx_campaign_launch_date ON campaign(launch_date);
CREATE INDEX IF NOT EXISTS idx_campaign_due_date ON campaign(due_date);
CREATE INDEX IF NOT EXISTS idx_campaign_created_by ON campaign(created_by);

-- Contrainte de vérification pour le statut
ALTER TABLE campaign DROP CONSTRAINT IF EXISTS chk_campaign_status;
ALTER TABLE campaign ADD CONSTRAINT chk_campaign_status
  CHECK (status IN ('draft', 'ongoing', 'late', 'frozen', 'completed', 'cancelled'));

-- Contrainte de vérification pour le type de récurrence
ALTER TABLE campaign DROP CONSTRAINT IF EXISTS chk_campaign_recurrence_type;
ALTER TABLE campaign ADD CONSTRAINT chk_campaign_recurrence_type
  CHECK (recurrence_type IS NULL OR recurrence_type IN ('once', 'monthly', 'quarterly', 'yearly'));

-- ============================================================================

-- Table : evaluation (Évaluations)
-- Instances d'évaluation dans une campagne
CREATE TABLE IF NOT EXISTS evaluation (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  campaign_id UUID REFERENCES campaign(id) ON DELETE CASCADE,
  entity_id UUID REFERENCES ecosystem_entity(id),
  assigned_auditor_id UUID REFERENCES users(id),

  -- Statuts
  status VARCHAR(50) DEFAULT 'pending',
  -- 'pending' → 'in_progress' → 'self_eval_complete'
  -- → 'audit_in_progress' → 'audit_complete' → 'closed'

  -- Dates
  started_at TIMESTAMPTZ,
  self_eval_completed_at TIMESTAMPTZ,
  audit_started_at TIMESTAMPTZ,
  audit_completed_at TIMESTAMPTZ,
  closed_at TIMESTAMPTZ,

  created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Index pour evaluation
CREATE INDEX IF NOT EXISTS idx_evaluation_campaign ON evaluation(campaign_id);
CREATE INDEX IF NOT EXISTS idx_evaluation_entity ON evaluation(entity_id);
CREATE INDEX IF NOT EXISTS idx_evaluation_auditor ON evaluation(assigned_auditor_id);
CREATE INDEX IF NOT EXISTS idx_evaluation_status ON evaluation(status);

-- Contrainte de vérification pour le statut
ALTER TABLE evaluation DROP CONSTRAINT IF EXISTS chk_evaluation_status;
ALTER TABLE evaluation ADD CONSTRAINT chk_evaluation_status
  CHECK (status IN ('pending', 'in_progress', 'self_eval_complete', 'audit_in_progress', 'audit_complete', 'closed'));

-- ============================================================================

-- Trigger pour mettre à jour updated_at automatiquement
CREATE OR REPLACE FUNCTION update_campaign_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Appliquer le trigger sur campaign
DROP TRIGGER IF EXISTS trg_campaign_updated_at ON campaign;
CREATE TRIGGER trg_campaign_updated_at
    BEFORE UPDATE ON campaign
    FOR EACH ROW
    EXECUTE FUNCTION update_campaign_updated_at();

-- Appliquer le trigger sur campaign_scope
DROP TRIGGER IF EXISTS trg_campaign_scope_updated_at ON campaign_scope;
CREATE TRIGGER trg_campaign_scope_updated_at
    BEFORE UPDATE ON campaign_scope
    FOR EACH ROW
    EXECUTE FUNCTION update_campaign_updated_at();

-- Appliquer le trigger sur evaluation
DROP TRIGGER IF EXISTS trg_evaluation_updated_at ON evaluation;
CREATE TRIGGER trg_evaluation_updated_at
    BEFORE UPDATE ON evaluation
    FOR EACH ROW
    EXECUTE FUNCTION update_campaign_updated_at();

-- ============================================================================

-- Commentaires sur les tables
COMMENT ON TABLE campaign_scope IS 'Périmètres réutilisables pour les campagnes d''audit';
COMMENT ON TABLE campaign IS 'Campagnes d''audit avec récurrence et gestion de statuts';
COMMENT ON TABLE evaluation IS 'Instances d''évaluation individuelles dans une campagne';

COMMENT ON COLUMN campaign.recurrence_type IS 'Type de récurrence: once, monthly, quarterly, yearly';
COMMENT ON COLUMN campaign.status IS 'Statut: draft, ongoing, late, frozen, completed, cancelled';
COMMENT ON COLUMN evaluation.status IS 'Statut: pending, in_progress, self_eval_complete, audit_in_progress, audit_complete, closed';

-- ============================================================================
-- FIN DE LA MIGRATION
-- ============================================================================
