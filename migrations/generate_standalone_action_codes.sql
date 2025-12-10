-- Migration: Generate code_action for standalone actions
-- Date: 2024-11-30
-- Description: Generate ACT_NNN codes for standalone actions in the 'action' table
--   - Format standalone: ACT_NNN (NNN = numéro séquentiel global par tenant)

-- ===========================================================================
-- 1. Generate codes for standalone actions (in action table)
-- ===========================================================================

DO $$
DECLARE
    t_record RECORD;
    a_record RECORD;
    counter INTEGER;
    max_standalone_code INTEGER;
BEGIN
    -- Pour chaque tenant
    FOR t_record IN SELECT DISTINCT tenant_id FROM action WHERE tenant_id IS NOT NULL
    LOOP
        -- Trouver le max code standalone existant pour ce tenant
        -- Pattern: ACT_NNN (3 chiffres minimum)
        SELECT COALESCE(MAX(
            CAST(SUBSTRING(code_action FROM 'ACT_([0-9]+)$') AS INTEGER)
        ), 0) INTO max_standalone_code
        FROM action
        WHERE tenant_id = t_record.tenant_id
          AND code_action IS NOT NULL
          AND code_action ~ '^ACT_[0-9]+$';

        counter := max_standalone_code;

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

            RAISE NOTICE 'Action % -> ACT_%', a_record.id, LPAD(counter::text, 3, '0');
        END LOOP;

        IF counter > max_standalone_code THEN
            RAISE NOTICE 'Tenant %: % standalone actions coded (ACT_% to ACT_%)',
                t_record.tenant_id,
                counter - max_standalone_code,
                LPAD((max_standalone_code + 1)::text, 3, '0'),
                LPAD(counter::text, 3, '0');
        END IF;
    END LOOP;
END $$;

-- ===========================================================================
-- 2. Verify the changes
-- ===========================================================================

SELECT
    id,
    code_action,
    title,
    tenant_id,
    created_at
FROM action
WHERE code_action IS NOT NULL
ORDER BY created_at ASC;

-- ===========================================================================
-- 3. Summary
-- ===========================================================================

SELECT
    'action (standalone)' as table_name,
    COUNT(*) as total,
    COUNT(code_action) as with_code,
    COUNT(*) - COUNT(code_action) as without_code
FROM action;
