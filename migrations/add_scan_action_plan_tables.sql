-- Migration: Add Scan Action Plan tables
-- Date: 2024-12-02
-- Description:
--   Tables séparées pour les plans d'action des scans (sans impact sur les campagnes)
--   - scan_action_plan: Plan d'action généré depuis un scan
--   - scan_action_plan_item: Items du plan (vulnérabilités)

-- ===========================================================================
-- 1. Create scan_action_plan table
-- ===========================================================================

CREATE TABLE IF NOT EXISTS scan_action_plan (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Lien vers le scan source
    scan_id UUID NOT NULL REFERENCES external_scan(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,

    -- Code du scan (copié pour référence rapide)
    code_scan VARCHAR(20),

    -- Statut: DRAFT, PUBLISHED
    status VARCHAR(20) NOT NULL DEFAULT 'DRAFT',

    -- Métadonnées du scan
    target_value VARCHAR(255),
    target_type VARCHAR(50),
    exposure_score INTEGER,

    -- Statistiques
    total_items INTEGER DEFAULT 0,
    critical_count INTEGER DEFAULT 0,
    high_count INTEGER DEFAULT 0,
    medium_count INTEGER DEFAULT 0,
    low_count INTEGER DEFAULT 0,
    validated_count INTEGER DEFAULT 0,
    excluded_count INTEGER DEFAULT 0,

    -- Dates
    generated_at TIMESTAMP,
    published_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    -- Utilisateurs
    generated_by UUID REFERENCES users(id),
    published_by UUID REFERENCES users(id),

    -- Contrainte unicité: un seul plan par scan
    CONSTRAINT uq_scan_action_plan_scan UNIQUE (scan_id)
);

-- Index
CREATE INDEX IF NOT EXISTS idx_scan_action_plan_tenant ON scan_action_plan(tenant_id);
CREATE INDEX IF NOT EXISTS idx_scan_action_plan_status ON scan_action_plan(status);
CREATE INDEX IF NOT EXISTS idx_scan_action_plan_code ON scan_action_plan(code_scan);

-- ===========================================================================
-- 2. Create scan_action_plan_item table
-- ===========================================================================

CREATE TABLE IF NOT EXISTS scan_action_plan_item (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Liens
    scan_action_plan_id UUID NOT NULL REFERENCES scan_action_plan(id) ON DELETE CASCADE,
    vulnerability_id UUID REFERENCES external_service_vulnerability(id) ON DELETE SET NULL,
    tenant_id UUID NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,

    -- Code de l'action (format: ACT_SCAN_XXX_NNN)
    code_action VARCHAR(30),

    -- Statut: PROPOSED, VALIDATED, EXCLUDED, PUBLISHED
    status VARCHAR(20) NOT NULL DEFAULT 'PROPOSED',

    -- Ordre
    order_index INTEGER NOT NULL DEFAULT 0,

    -- Inclusion
    included BOOLEAN DEFAULT TRUE,

    -- Contenu
    title VARCHAR(500) NOT NULL,
    description TEXT NOT NULL,
    recommendation TEXT,

    -- Infos techniques
    port INTEGER,
    protocol VARCHAR(20),
    service_name VARCHAR(100),
    service_version VARCHAR(100),

    -- CVE
    cve_ids TEXT[],
    cvss_score FLOAT,

    -- Classification
    severity VARCHAR(50) NOT NULL,
    priority VARCHAR(10) NOT NULL,
    recommended_due_days INTEGER NOT NULL DEFAULT 30,

    -- Assignation
    suggested_role VARCHAR(100),
    assigned_user_id UUID,

    -- Entité écosystème
    entity_id UUID,
    entity_name VARCHAR(255),

    -- Action publiée
    created_action_id UUID,

    -- Dates
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Index
CREATE INDEX IF NOT EXISTS idx_scan_action_plan_item_plan ON scan_action_plan_item(scan_action_plan_id);
CREATE INDEX IF NOT EXISTS idx_scan_action_plan_item_tenant ON scan_action_plan_item(tenant_id);
CREATE INDEX IF NOT EXISTS idx_scan_action_plan_item_status ON scan_action_plan_item(status);
CREATE INDEX IF NOT EXISTS idx_scan_action_plan_item_code ON scan_action_plan_item(code_action);
CREATE INDEX IF NOT EXISTS idx_scan_action_plan_item_vuln ON scan_action_plan_item(vulnerability_id);

-- ===========================================================================
-- 3. Update published_action table for scan support
-- ===========================================================================

-- Add scan_action_plan_item_id reference
ALTER TABLE published_action
    ADD COLUMN IF NOT EXISTS scan_action_plan_item_id UUID REFERENCES scan_action_plan_item(id) ON DELETE SET NULL;

-- Add index
CREATE INDEX IF NOT EXISTS idx_published_action_scan_item ON published_action(scan_action_plan_item_id)
    WHERE scan_action_plan_item_id IS NOT NULL;

-- ===========================================================================
-- 4. Function to generate code_action for scan items
-- ===========================================================================

CREATE OR REPLACE FUNCTION generate_scan_action_code()
RETURNS TRIGGER AS $$
DECLARE
    plan_code VARCHAR(20);
    next_num INTEGER;
BEGIN
    IF NEW.code_action IS NULL OR NEW.code_action = '' THEN
        -- Récupérer le code_scan du plan
        SELECT code_scan INTO plan_code
        FROM scan_action_plan
        WHERE id = NEW.scan_action_plan_id;

        -- Trouver le prochain numéro
        SELECT COALESCE(MAX(order_index), 0) + 1 INTO next_num
        FROM scan_action_plan_item
        WHERE scan_action_plan_id = NEW.scan_action_plan_id;

        -- Générer le code: ACT_SCAN_001_001
        NEW.code_action := 'ACT_' || COALESCE(plan_code, 'SCAN_000') || '_' || LPAD(next_num::text, 3, '0');
        NEW.order_index := next_num;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger
DROP TRIGGER IF EXISTS trigger_generate_scan_action_code ON scan_action_plan_item;
CREATE TRIGGER trigger_generate_scan_action_code
    BEFORE INSERT ON scan_action_plan_item
    FOR EACH ROW
    EXECUTE FUNCTION generate_scan_action_code();

-- ===========================================================================
-- 5. Verify tables created
-- ===========================================================================

SELECT 'scan_action_plan' as table_name, COUNT(*) as rows FROM scan_action_plan
UNION ALL
SELECT 'scan_action_plan_item', COUNT(*) FROM scan_action_plan_item;
