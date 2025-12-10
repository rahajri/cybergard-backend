-- Migration: Link external_target to ecosystem_entity
-- Date: 2024-12-02
-- Description:
--   Ajoute la possibilité de lier une cible de scan (domaine, IP) à une entité
--   de l'écosystème. Un organisme peut avoir plusieurs cibles (domaines, IPs).
--   Cela permet d'agréger les vulnérabilités par entité dans la vue Écosystème.

-- ===========================================================================
-- 1. Add entity_id column to external_target
-- ===========================================================================

ALTER TABLE external_target
    ADD COLUMN IF NOT EXISTS entity_id UUID REFERENCES ecosystem_entity(id) ON DELETE SET NULL;

-- Index for efficient entity-based queries
CREATE INDEX IF NOT EXISTS idx_external_target_entity ON external_target(entity_id)
    WHERE entity_id IS NOT NULL;

-- ===========================================================================
-- 2. Add entity_id to external_scan (denormalized for performance)
-- ===========================================================================

ALTER TABLE external_scan
    ADD COLUMN IF NOT EXISTS entity_id UUID REFERENCES ecosystem_entity(id) ON DELETE SET NULL;

-- Index
CREATE INDEX IF NOT EXISTS idx_external_scan_entity ON external_scan(entity_id)
    WHERE entity_id IS NOT NULL;

-- ===========================================================================
-- 3. Create view for ecosystem vulnerability aggregation
-- ===========================================================================

-- Vue pour agréger les vulnérabilités par entité
CREATE OR REPLACE VIEW ecosystem_vulnerability_summary AS
SELECT
    ee.id AS entity_id,
    ee.name AS entity_name,
    ee.tenant_id,
    COUNT(DISTINCT et.id) AS target_count,
    COUNT(DISTINCT es.id) AS scan_count,
    COUNT(DISTINCT esv.id) AS vulnerability_count,
    SUM(CASE WHEN esv.severity = 'CRITICAL' THEN 1 ELSE 0 END) AS critical_count,
    SUM(CASE WHEN esv.severity = 'HIGH' THEN 1 ELSE 0 END) AS high_count,
    SUM(CASE WHEN esv.severity = 'MEDIUM' THEN 1 ELSE 0 END) AS medium_count,
    SUM(CASE WHEN esv.severity = 'LOW' THEN 1 ELSE 0 END) AS low_count,
    MAX(esv.cvss_score) AS max_cvss,
    AVG(esv.cvss_score)::NUMERIC(3,1) AS avg_cvss,
    MAX(es.finished_at) AS last_scan_at,
    -- Calcul du grade basé sur le CVSS max
    CASE
        WHEN MAX(esv.cvss_score) IS NULL OR MAX(esv.cvss_score) < 2 THEN 'A'
        WHEN MAX(esv.cvss_score) < 4 THEN 'B'
        WHEN MAX(esv.cvss_score) < 6 THEN 'C'
        WHEN MAX(esv.cvss_score) < 8 THEN 'D'
        ELSE 'E'
    END AS security_grade
FROM ecosystem_entity ee
LEFT JOIN external_target et ON et.entity_id = ee.id AND et.deleted_at IS NULL
LEFT JOIN external_scan es ON es.entity_id = ee.id AND es.status = 'SUCCESS'
LEFT JOIN external_service_vulnerability esv ON esv.external_scan_id = es.id AND esv.is_remediated = false
WHERE ee.is_active = true
GROUP BY ee.id, ee.name, ee.tenant_id;

-- ===========================================================================
-- 4. Function to auto-populate entity_id in external_scan from target
-- ===========================================================================

CREATE OR REPLACE FUNCTION populate_scan_entity_id()
RETURNS TRIGGER AS $$
BEGIN
    -- Si entity_id n'est pas déjà défini, le récupérer depuis la target
    IF NEW.entity_id IS NULL THEN
        SELECT entity_id INTO NEW.entity_id
        FROM external_target
        WHERE id = NEW.external_target_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger
DROP TRIGGER IF EXISTS trigger_populate_scan_entity_id ON external_scan;
CREATE TRIGGER trigger_populate_scan_entity_id
    BEFORE INSERT ON external_scan
    FOR EACH ROW
    EXECUTE FUNCTION populate_scan_entity_id();

-- ===========================================================================
-- 5. Update existing scans to populate entity_id from targets
-- ===========================================================================

UPDATE external_scan es
SET entity_id = et.entity_id
FROM external_target et
WHERE es.external_target_id = et.id
  AND es.entity_id IS NULL
  AND et.entity_id IS NOT NULL;

-- ===========================================================================
-- 6. Verify changes
-- ===========================================================================

SELECT 'external_target entity_id column' as check_name,
       COUNT(*) FILTER (WHERE entity_id IS NOT NULL) as targets_with_entity,
       COUNT(*) as total_targets
FROM external_target;

SELECT 'external_scan entity_id column' as check_name,
       COUNT(*) FILTER (WHERE entity_id IS NOT NULL) as scans_with_entity,
       COUNT(*) as total_scans
FROM external_scan;
