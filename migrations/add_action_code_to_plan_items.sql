-- Migration: Add code_action column to action_plan_item and published_action tables
-- Date: 2024-11-30
-- Description: Add unique action code for each action
--   - Format campagne: ACT_CAMP_XXX_NNN (XXX = numéro campagne, NNN = numéro séquentiel)
--   - Format standalone: ACT_NNN (NNN = numéro séquentiel global)

-- ===========================================================================
-- 1. Add code_action to action_plan_item table
-- ===========================================================================

ALTER TABLE action_plan_item
    ADD COLUMN IF NOT EXISTS code_action VARCHAR(20);

-- Create unique index on code_action per tenant (allows NULL but unique non-null values)
CREATE UNIQUE INDEX IF NOT EXISTS idx_action_plan_item_code_unique
    ON action_plan_item(tenant_id, code_action)
    WHERE code_action IS NOT NULL;

-- ===========================================================================
-- 2. Add code_action to published_action table
-- ===========================================================================

ALTER TABLE published_action
    ADD COLUMN IF NOT EXISTS code_action VARCHAR(20);

-- Create unique index on code_action per tenant
CREATE UNIQUE INDEX IF NOT EXISTS idx_published_action_code_unique
    ON published_action(tenant_id, code_action)
    WHERE code_action IS NOT NULL;

-- Create index for fast lookup by code
CREATE INDEX IF NOT EXISTS idx_published_action_code
    ON published_action(code_action);

-- ===========================================================================
-- 3. Add code_action to action table (standalone actions)
-- ===========================================================================

ALTER TABLE action
    ADD COLUMN IF NOT EXISTS code_action VARCHAR(20);

-- Create unique index on code_action per tenant
CREATE UNIQUE INDEX IF NOT EXISTS idx_action_code_unique
    ON action(tenant_id, code_action)
    WHERE code_action IS NOT NULL;

-- Create index for fast lookup
CREATE INDEX IF NOT EXISTS idx_action_code
    ON action(code_action);

-- ===========================================================================
-- 4. Generate codes for existing action_plan_items (per tenant, per campaign)
-- Format campagne: ACT_CAMP_XXX_NNN (XXX = numéro campagne)
-- ===========================================================================

DO $$
DECLARE
    t_record RECORD;
    c_record RECORD;
    ap_record RECORD;
    item_record RECORD;
    campaign_counter INTEGER;
    item_counter INTEGER;
    campaign_code_prefix TEXT;
BEGIN
    -- Pour chaque tenant
    FOR t_record IN SELECT DISTINCT tenant_id FROM action_plan_item WHERE tenant_id IS NOT NULL
    LOOP
        campaign_counter := 0;

        -- Pour chaque campagne du tenant (ordonnée par date de création)
        FOR c_record IN
            SELECT DISTINCT c.id, c.created_at
            FROM campaign c
            JOIN action_plan ap ON ap.campaign_id = c.id
            JOIN action_plan_item api ON api.action_plan_id = ap.id
            WHERE c.tenant_id = t_record.tenant_id
            ORDER BY c.created_at ASC
        LOOP
            campaign_counter := campaign_counter + 1;
            campaign_code_prefix := 'ACT_CAMP_' || LPAD(campaign_counter::text, 3, '0') || '_';
            item_counter := 0;

            -- Pour chaque action_plan de cette campagne
            FOR ap_record IN
                SELECT DISTINCT api.action_plan_id
                FROM action_plan_item api
                JOIN action_plan ap ON ap.id = api.action_plan_id
                WHERE ap.campaign_id = c_record.id
            LOOP
                -- Pour chaque item sans code
                FOR item_record IN
                    SELECT id FROM action_plan_item
                    WHERE action_plan_id = ap_record.action_plan_id
                      AND (code_action IS NULL OR code_action = '')
                    ORDER BY order_index ASC, created_at ASC
                LOOP
                    item_counter := item_counter + 1;
                    UPDATE action_plan_item
                    SET code_action = campaign_code_prefix || LPAD(item_counter::text, 3, '0')
                    WHERE id = item_record.id;
                END LOOP;
            END LOOP;

            IF item_counter > 0 THEN
                RAISE NOTICE 'Campaign %: % items coded with prefix %', c_record.id, item_counter, campaign_code_prefix;
            END IF;
        END LOOP;
    END LOOP;
END $$;

-- ===========================================================================
-- 5. Copy codes from action_plan_item to published_action
-- ===========================================================================

UPDATE published_action pa
SET code_action = api.code_action
FROM action_plan_item api
WHERE pa.action_plan_item_id = api.id
  AND api.code_action IS NOT NULL
  AND (pa.code_action IS NULL OR pa.code_action = '');

-- ===========================================================================
-- 6. Generate codes for standalone actions (in action table)
-- ===========================================================================

DO $$
DECLARE
    t_record RECORD;
    a_record RECORD;
    counter INTEGER;
    max_code INTEGER;
BEGIN
    -- Pour chaque tenant
    FOR t_record IN SELECT DISTINCT tenant_id FROM action WHERE tenant_id IS NOT NULL
    LOOP
        -- Trouver le max code existant pour ce tenant (dans toutes les tables)
        SELECT COALESCE(MAX(CAST(SUBSTRING(code_action FROM 5) AS INTEGER)), 0) INTO max_code
        FROM (
            SELECT code_action FROM action_plan_item WHERE tenant_id = t_record.tenant_id AND code_action IS NOT NULL
            UNION ALL
            SELECT code_action FROM published_action WHERE tenant_id = t_record.tenant_id AND code_action IS NOT NULL
            UNION ALL
            SELECT code_action FROM action WHERE tenant_id = t_record.tenant_id AND code_action IS NOT NULL
        ) all_codes
        WHERE code_action ~ '^ACT_[0-9]+$';

        counter := max_code;

        -- Pour chaque action standalone sans code
        FOR a_record IN
            SELECT id FROM action
            WHERE tenant_id = t_record.tenant_id
              AND (code_action IS NULL OR code_action = '')
            ORDER BY created_at ASC
        LOOP
            counter := counter + 1;
            UPDATE action
            SET code_action = 'ACT_' || LPAD(counter::text, 3, '0')
            WHERE id = a_record.id;
        END LOOP;

        IF counter > max_code THEN
            RAISE NOTICE 'Tenant %: % standalone actions coded (starting from %)', t_record.tenant_id, counter - max_code, max_code + 1;
        END IF;
    END LOOP;
END $$;

-- ===========================================================================
-- 7. Verify the changes
-- ===========================================================================

SELECT 'action_plan_item' as table_name, COUNT(*) as total,
       COUNT(code_action) as with_code
FROM action_plan_item
UNION ALL
SELECT 'published_action', COUNT(*), COUNT(code_action)
FROM published_action
UNION ALL
SELECT 'action', COUNT(*), COUNT(code_action)
FROM action;
