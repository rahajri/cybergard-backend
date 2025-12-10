-- Migration: Extend code_action column length from VARCHAR(20) to VARCHAR(30)
-- Date: 2024-12-03
-- Reason: Le format des codes scan (ACT_SCAN_4857D3FD_001) fait 21 caractères,
--         ce qui dépasse la limite actuelle de 20 caractères.

-- ===========================================================================
-- 1. Étendre la colonne code_action dans published_action
-- ===========================================================================

ALTER TABLE published_action
    ALTER COLUMN code_action TYPE VARCHAR(30);

-- ===========================================================================
-- 2. Étendre la colonne code_action dans action_plan_item (par cohérence)
-- ===========================================================================

ALTER TABLE action_plan_item
    ALTER COLUMN code_action TYPE VARCHAR(30);

-- ===========================================================================
-- 3. Étendre la colonne code_action dans action (par cohérence)
-- ===========================================================================

ALTER TABLE action
    ALTER COLUMN code_action TYPE VARCHAR(30);

-- ===========================================================================
-- Vérification
-- ===========================================================================

SELECT
    table_name,
    column_name,
    data_type,
    character_maximum_length
FROM information_schema.columns
WHERE column_name = 'code_action'
  AND table_schema = 'public'
ORDER BY table_name;
