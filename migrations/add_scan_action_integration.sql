-- Migration: Add scan-action integration
-- Date: 2024-12-02
-- Description:
--   1. Add code_scan to external_scan table (format: SCAN_XXX auto-incremented per tenant)
--   2. Add scan_id reference to published_action for actions generated from scans
--   3. Add source_type to published_action to distinguish action origin (campaign / scan)

-- ===========================================================================
-- 1. Add code_scan to external_scan table
-- ===========================================================================

ALTER TABLE external_scan
    ADD COLUMN IF NOT EXISTS code_scan VARCHAR(20);

-- Create unique index on code_scan per tenant
CREATE UNIQUE INDEX IF NOT EXISTS idx_external_scan_code_unique
    ON external_scan(tenant_id, code_scan)
    WHERE code_scan IS NOT NULL;

-- Create index for fast lookup
CREATE INDEX IF NOT EXISTS idx_external_scan_code
    ON external_scan(code_scan);

-- ===========================================================================
-- 2. Add scan_id and source_type to published_action table
-- ===========================================================================

-- Add scan_id column (nullable - only set for actions from scans)
ALTER TABLE published_action
    ADD COLUMN IF NOT EXISTS scan_id UUID REFERENCES external_scan(id) ON DELETE SET NULL;

-- Add source_type column (default 'campaign' for backward compatibility)
-- Values: 'campaign' | 'scan' | 'standalone'
ALTER TABLE published_action
    ADD COLUMN IF NOT EXISTS source_type VARCHAR(20) DEFAULT 'campaign';

-- Create index for filtering by source
CREATE INDEX IF NOT EXISTS idx_published_action_source_type
    ON published_action(source_type);

CREATE INDEX IF NOT EXISTS idx_published_action_scan_id
    ON published_action(scan_id)
    WHERE scan_id IS NOT NULL;

-- ===========================================================================
-- 3. Generate code_scan for existing scans
-- ===========================================================================

DO $$
DECLARE
    t_record RECORD;
    s_record RECORD;
    counter INTEGER;
BEGIN
    -- Pour chaque tenant
    FOR t_record IN SELECT DISTINCT tenant_id FROM external_scan WHERE tenant_id IS NOT NULL
    LOOP
        counter := 0;

        -- Pour chaque scan du tenant (ordonné par date de création)
        FOR s_record IN
            SELECT id FROM external_scan
            WHERE tenant_id = t_record.tenant_id
              AND (code_scan IS NULL OR code_scan = '')
            ORDER BY created_at ASC
        LOOP
            counter := counter + 1;
            UPDATE external_scan
            SET code_scan = 'SCAN_' || LPAD(counter::text, 3, '0')
            WHERE id = s_record.id;
        END LOOP;

        IF counter > 0 THEN
            RAISE NOTICE 'Tenant %: % scans coded', t_record.tenant_id, counter;
        END IF;
    END LOOP;
END $$;

-- ===========================================================================
-- 4. Update existing published_actions to set source_type correctly
-- ===========================================================================

-- Actions with campaign_id → source_type = 'campaign'
UPDATE published_action
SET source_type = 'campaign'
WHERE campaign_id IS NOT NULL
  AND (source_type IS NULL OR source_type = '');

-- Actions without campaign_id and without scan_id → source_type = 'standalone'
UPDATE published_action
SET source_type = 'standalone'
WHERE campaign_id IS NULL
  AND scan_id IS NULL
  AND (source_type IS NULL OR source_type = '' OR source_type = 'campaign');

-- ===========================================================================
-- 5. Create function to auto-generate code_scan on insert
-- ===========================================================================

CREATE OR REPLACE FUNCTION generate_code_scan()
RETURNS TRIGGER AS $$
DECLARE
    next_num INTEGER;
BEGIN
    IF NEW.code_scan IS NULL OR NEW.code_scan = '' THEN
        SELECT COALESCE(MAX(
            CAST(SUBSTRING(code_scan FROM 6) AS INTEGER)
        ), 0) + 1 INTO next_num
        FROM external_scan
        WHERE tenant_id = NEW.tenant_id
          AND code_scan IS NOT NULL
          AND code_scan ~ '^SCAN_[0-9]+$';

        NEW.code_scan := 'SCAN_' || LPAD(next_num::text, 3, '0');
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Drop trigger if exists (for idempotency)
DROP TRIGGER IF EXISTS trigger_generate_code_scan ON external_scan;

-- Create trigger
CREATE TRIGGER trigger_generate_code_scan
    BEFORE INSERT ON external_scan
    FOR EACH ROW
    EXECUTE FUNCTION generate_code_scan();

-- ===========================================================================
-- 6. Verify the changes
-- ===========================================================================

SELECT 'external_scan' as table_name,
       COUNT(*) as total,
       COUNT(code_scan) as with_code
FROM external_scan;

SELECT 'published_action by source_type' as description,
       source_type,
       COUNT(*) as count
FROM published_action
GROUP BY source_type;
