-- Migration: Add code_action column to the 'action' table
-- Date: 2024-11-30
-- Description: Add unique action code (format: ACT_XXX) for each action

-- Add code_action column
ALTER TABLE action
    ADD COLUMN IF NOT EXISTS code_action VARCHAR(20);

-- Create unique index on code_action (allows NULL but unique non-null values)
CREATE UNIQUE INDEX IF NOT EXISTS idx_action_code_unique
    ON action(code_action)
    WHERE code_action IS NOT NULL;

-- Create index on tenant_id + code_action for fast lookup
CREATE INDEX IF NOT EXISTS idx_action_tenant_code
    ON action(tenant_id, code_action);

-- Generate codes for existing actions that don't have one
-- Format: ACT_001, ACT_002, etc. (per tenant)
DO $$
DECLARE
    t_record RECORD;
    a_record RECORD;
    counter INTEGER;
BEGIN
    -- Pour chaque tenant
    FOR t_record IN SELECT DISTINCT tenant_id FROM action WHERE tenant_id IS NOT NULL
    LOOP
        counter := 0;
        -- Pour chaque action de ce tenant sans code
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

        RAISE NOTICE 'Tenant %: % actions coded', t_record.tenant_id, counter;
    END LOOP;
END $$;

-- Verify the changes
SELECT id, code_action, title, tenant_id, created_at
FROM action
ORDER BY tenant_id, code_action
LIMIT 20;
