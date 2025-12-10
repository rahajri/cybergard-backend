-- Migration: Add columns for standalone actions in the 'action' table
-- Date: 2024-11-30
-- Description: Add missing columns to support standalone actions created from the Actions menu

-- Make audit_id nullable (for standalone actions without audit)
ALTER TABLE action
    ALTER COLUMN audit_id DROP NOT NULL;

-- Add tenant_id column
ALTER TABLE action
    ADD COLUMN IF NOT EXISTS tenant_id UUID REFERENCES tenant(id);

-- Add objective column
ALTER TABLE action
    ADD COLUMN IF NOT EXISTS objective TEXT;

-- Add deliverables column
ALTER TABLE action
    ADD COLUMN IF NOT EXISTS deliverables TEXT;

-- Add severity column (critical, major, minor, info)
ALTER TABLE action
    ADD COLUMN IF NOT EXISTS severity VARCHAR(50) DEFAULT 'minor';

-- Add suggested_role column
ALTER TABLE action
    ADD COLUMN IF NOT EXISTS suggested_role VARCHAR(100);

-- Add entity_id column
ALTER TABLE action
    ADD COLUMN IF NOT EXISTS entity_id UUID;

-- Add entity_name column
ALTER TABLE action
    ADD COLUMN IF NOT EXISTS entity_name VARCHAR(255);

-- Add recommended_due_days column
ALTER TABLE action
    ADD COLUMN IF NOT EXISTS recommended_due_days INTEGER DEFAULT 30;

-- Add source_question_ids column (array of UUIDs)
ALTER TABLE action
    ADD COLUMN IF NOT EXISTS source_question_ids UUID[];

-- Add control_point_ids column (array of UUIDs)
ALTER TABLE action
    ADD COLUMN IF NOT EXISTS control_point_ids UUID[];

-- Change priority column from INTEGER to VARCHAR(10) for P1, P2, P3 values
-- First check if it's already VARCHAR
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'action'
        AND column_name = 'priority'
        AND data_type = 'integer'
    ) THEN
        ALTER TABLE action ALTER COLUMN priority TYPE VARCHAR(10) USING
            CASE
                WHEN priority = 1 THEN 'P1'
                WHEN priority = 2 THEN 'P2'
                WHEN priority = 3 THEN 'P3'
                ELSE 'P2'
            END;
        ALTER TABLE action ALTER COLUMN priority SET DEFAULT 'P2';
    END IF;
END $$;

-- Create index on tenant_id for better query performance
CREATE INDEX IF NOT EXISTS idx_action_tenant_id ON action(tenant_id);

-- Create index on entity_id for filtering by entity
CREATE INDEX IF NOT EXISTS idx_action_entity_id ON action(entity_id);

-- Verify the changes
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'action'
ORDER BY ordinal_position;
