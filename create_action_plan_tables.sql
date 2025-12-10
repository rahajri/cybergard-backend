-- ============================================================================
-- Migration : Création des tables pour le module Plan d'Action IA
-- Date : 2024-11-22
-- ============================================================================

-- Table action_plan
CREATE TABLE IF NOT EXISTS action_plan (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id UUID NOT NULL UNIQUE REFERENCES campaign(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,

    -- Statut du plan
    status VARCHAR(50) NOT NULL DEFAULT 'NOT_STARTED',

    -- Métadonnées de génération
    summary_title VARCHAR(500),
    overall_risk_level VARCHAR(50),
    dominant_language VARCHAR(10),

    -- Statistiques du plan
    total_actions INTEGER DEFAULT 0,
    critical_count INTEGER DEFAULT 0,
    major_count INTEGER DEFAULT 0,
    minor_count INTEGER DEFAULT 0,
    info_count INTEGER DEFAULT 0,

    -- Progression de génération (JSON)
    generation_progress JSONB,

    -- Dates
    generated_at TIMESTAMP WITH TIME ZONE,
    published_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Auditeurs
    generated_by UUID REFERENCES users(id),
    published_by UUID REFERENCES users(id),

    -- Contraintes
    CONSTRAINT action_plan_status_check CHECK (
        status IN ('NOT_STARTED', 'GENERATING', 'DRAFT', 'PUBLISHED')
    )
);

-- Index pour performance
CREATE INDEX idx_action_plan_campaign ON action_plan(campaign_id);
CREATE INDEX idx_action_plan_tenant ON action_plan(tenant_id);
CREATE INDEX idx_action_plan_status ON action_plan(status);

-- Table action_plan_item
CREATE TABLE IF NOT EXISTS action_plan_item (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    action_plan_id UUID NOT NULL REFERENCES action_plan(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,

    -- Statut de l'item
    status VARCHAR(50) NOT NULL DEFAULT 'PROPOSED',

    -- Ordre d'affichage
    order_index INTEGER NOT NULL DEFAULT 0,

    -- Inclusion/exclusion
    included BOOLEAN DEFAULT TRUE,

    -- Contenu de l'action
    title VARCHAR(500) NOT NULL,
    description TEXT NOT NULL,

    -- Classification
    severity VARCHAR(50) NOT NULL,
    priority VARCHAR(10) NOT NULL,

    -- Délai recommandé (en jours)
    recommended_due_days INTEGER NOT NULL,

    -- Assignation
    suggested_role VARCHAR(100) NOT NULL,
    assigned_user_id UUID REFERENCES users(id),
    assignment_method VARCHAR(50) NOT NULL DEFAULT 'unassigned',

    -- Sources (questions ayant généré cette action)
    source_question_ids UUID[] NOT NULL DEFAULT '{}',

    -- Contrôles référentiels liés
    referential_controls TEXT[] NOT NULL DEFAULT '{}',

    -- Justifications IA (JSON)
    ai_justifications JSONB,

    -- Action opérationnelle créée (après publication)
    created_action_id UUID,

    -- Dates
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Contraintes
    CONSTRAINT action_plan_item_status_check CHECK (
        status IN ('PROPOSED', 'VALIDATED', 'EXCLUDED', 'PUBLISHED')
    ),
    CONSTRAINT action_plan_item_severity_check CHECK (
        severity IN ('info', 'minor', 'major', 'critical')
    ),
    CONSTRAINT action_plan_item_priority_check CHECK (
        priority IN ('P1', 'P2', 'P3')
    ),
    CONSTRAINT action_plan_item_assignment_method_check CHECK (
        assignment_method IN ('direct', 'fallback_manager', 'fallback_owner', 'audit_resp', 'manual', 'unassigned')
    )
);

-- Index pour performance
CREATE INDEX idx_action_plan_item_action_plan ON action_plan_item(action_plan_id);
CREATE INDEX idx_action_plan_item_tenant ON action_plan_item(tenant_id);
CREATE INDEX idx_action_plan_item_status ON action_plan_item(status);
CREATE INDEX idx_action_plan_item_severity ON action_plan_item(severity);
CREATE INDEX idx_action_plan_item_priority ON action_plan_item(priority);
CREATE INDEX idx_action_plan_item_assigned_user ON action_plan_item(assigned_user_id);

-- Trigger pour mettre à jour updated_at automatiquement
CREATE OR REPLACE FUNCTION update_action_plan_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER action_plan_updated_at_trigger
    BEFORE UPDATE ON action_plan
    FOR EACH ROW
    EXECUTE FUNCTION update_action_plan_updated_at();

CREATE TRIGGER action_plan_item_updated_at_trigger
    BEFORE UPDATE ON action_plan_item
    FOR EACH ROW
    EXECUTE FUNCTION update_action_plan_updated_at();

-- Commentaires
COMMENT ON TABLE action_plan IS 'Plans d''action générés par l''IA pour les campagnes d''audit';
COMMENT ON TABLE action_plan_item IS 'Items individuels (actions) d''un plan d''action';

COMMENT ON COLUMN action_plan.status IS 'NOT_STARTED, GENERATING, DRAFT, PUBLISHED';
COMMENT ON COLUMN action_plan.generation_progress IS 'Progression de la génération (phases 1-4)';
COMMENT ON COLUMN action_plan_item.ai_justifications IS 'Justifications IA : why_action, why_severity, why_priority, why_role, why_due_days';

-- Migration complétée
SELECT 'Tables action_plan et action_plan_item créées avec succès' AS status;
