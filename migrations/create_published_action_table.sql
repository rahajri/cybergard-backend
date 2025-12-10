-- Migration: Création de la table published_action
-- Description: Table pour stocker les actions publiées depuis le plan d'action IA
-- Date: 2024-11-30

-- ============================================================================
-- Table: published_action
-- Actions opérationnelles publiées depuis le plan d'action
-- ============================================================================

CREATE TABLE IF NOT EXISTS published_action (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Liens vers le plan d'action source
    action_plan_item_id UUID NOT NULL REFERENCES action_plan_item(id) ON DELETE CASCADE,
    action_plan_id UUID NOT NULL REFERENCES action_plan(id) ON DELETE CASCADE,
    campaign_id UUID NOT NULL REFERENCES campaign(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,

    -- Contenu de l'action (copié depuis action_plan_item)
    title VARCHAR(500) NOT NULL,
    description TEXT NOT NULL,
    objective TEXT,
    deliverables TEXT,

    -- Classification
    severity VARCHAR(50) NOT NULL,  -- critical, major, minor, info
    priority VARCHAR(10) NOT NULL,  -- P1, P2, P3

    -- Statut de l'action
    status VARCHAR(50) NOT NULL DEFAULT 'pending',  -- pending, in_progress, completed, blocked

    -- Assignation
    suggested_role VARCHAR(100) NOT NULL,
    assigned_user_id UUID,  -- Pas de FK car peut référencer users OU entity_member
    assignment_method VARCHAR(50) NOT NULL DEFAULT 'unassigned',

    -- Entité concernée
    entity_id UUID,
    entity_name VARCHAR(255),

    -- Dates
    due_date TIMESTAMP WITH TIME ZONE,
    recommended_due_days INTEGER NOT NULL,

    -- Sources et contrôles
    source_question_ids UUID[] NOT NULL DEFAULT '{}',
    control_point_ids UUID[] NOT NULL DEFAULT '{}',

    -- Justifications IA
    ai_justifications JSONB,

    -- Suivi
    progress_notes TEXT,
    completion_date TIMESTAMP WITH TIME ZONE,

    -- Métadonnées
    published_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    published_by UUID REFERENCES users(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Index pour les recherches fréquentes
CREATE INDEX IF NOT EXISTS idx_published_action_tenant_id ON published_action(tenant_id);
CREATE INDEX IF NOT EXISTS idx_published_action_campaign_id ON published_action(campaign_id);
CREATE INDEX IF NOT EXISTS idx_published_action_action_plan_id ON published_action(action_plan_id);
CREATE INDEX IF NOT EXISTS idx_published_action_status ON published_action(status);
CREATE INDEX IF NOT EXISTS idx_published_action_priority ON published_action(priority);
CREATE INDEX IF NOT EXISTS idx_published_action_severity ON published_action(severity);
CREATE INDEX IF NOT EXISTS idx_published_action_entity_id ON published_action(entity_id);
CREATE INDEX IF NOT EXISTS idx_published_action_due_date ON published_action(due_date);
CREATE INDEX IF NOT EXISTS idx_published_action_assigned_user_id ON published_action(assigned_user_id);

-- Index composite pour filtrage courant
CREATE INDEX IF NOT EXISTS idx_published_action_tenant_status ON published_action(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_published_action_tenant_priority ON published_action(tenant_id, priority);

-- Commentaires
COMMENT ON TABLE published_action IS 'Actions opérationnelles publiées depuis le plan d''action IA';
COMMENT ON COLUMN published_action.status IS 'Statut: pending, in_progress, completed, blocked';
COMMENT ON COLUMN published_action.severity IS 'Sévérité: critical, major, minor, info';
COMMENT ON COLUMN published_action.priority IS 'Priorité: P1, P2, P3';
COMMENT ON COLUMN published_action.action_plan_item_id IS 'Référence vers l''item du plan d''action source';
