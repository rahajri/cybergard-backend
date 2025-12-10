-- Migration: Allow NULL for campaign-related fields in published_action
-- Date: 2024-12-03
-- Reason: published_action peut maintenant provenir de scans (source_type='scan')
--         où les champs action_plan_item_id, action_plan_id, campaign_id sont NULL

-- ===========================================================================
-- 1. Supprimer les contraintes de clé étrangère existantes
-- ===========================================================================

ALTER TABLE published_action
    DROP CONSTRAINT IF EXISTS published_action_action_plan_id_fkey;

ALTER TABLE published_action
    DROP CONSTRAINT IF EXISTS published_action_action_plan_item_id_fkey;

ALTER TABLE published_action
    DROP CONSTRAINT IF EXISTS published_action_campaign_id_fkey;

-- ===========================================================================
-- 2. Rendre les colonnes nullable
-- ===========================================================================

ALTER TABLE published_action
    ALTER COLUMN action_plan_item_id DROP NOT NULL;

ALTER TABLE published_action
    ALTER COLUMN action_plan_id DROP NOT NULL;

ALTER TABLE published_action
    ALTER COLUMN campaign_id DROP NOT NULL;

-- ===========================================================================
-- 3. Recréer les contraintes de clé étrangère (sans NOT NULL)
-- ===========================================================================

ALTER TABLE published_action
    ADD CONSTRAINT published_action_action_plan_id_fkey
    FOREIGN KEY (action_plan_id) REFERENCES action_plan(id) ON DELETE CASCADE;

ALTER TABLE published_action
    ADD CONSTRAINT published_action_action_plan_item_id_fkey
    FOREIGN KEY (action_plan_item_id) REFERENCES action_plan_item(id) ON DELETE CASCADE;

ALTER TABLE published_action
    ADD CONSTRAINT published_action_campaign_id_fkey
    FOREIGN KEY (campaign_id) REFERENCES campaign(id) ON DELETE CASCADE;

-- ===========================================================================
-- 4. Ajouter une contrainte CHECK pour garantir la cohérence
-- ===========================================================================

-- source_type='campaign' => campaign_id, action_plan_id, action_plan_item_id doivent être NOT NULL
-- source_type='scan' => scan_id, scan_action_plan_item_id doivent être NOT NULL

ALTER TABLE published_action
    DROP CONSTRAINT IF EXISTS check_source_type_consistency;

ALTER TABLE published_action
    ADD CONSTRAINT check_source_type_consistency CHECK (
        (source_type = 'campaign' AND campaign_id IS NOT NULL AND action_plan_id IS NOT NULL AND action_plan_item_id IS NOT NULL)
        OR
        (source_type = 'scan' AND scan_id IS NOT NULL AND scan_action_plan_item_id IS NOT NULL)
    );

-- ===========================================================================
-- Vérification
-- ===========================================================================

SELECT column_name, is_nullable, data_type
FROM information_schema.columns
WHERE table_name = 'published_action'
  AND column_name IN ('action_plan_item_id', 'action_plan_id', 'campaign_id', 'scan_id', 'scan_action_plan_item_id', 'source_type')
ORDER BY column_name;
