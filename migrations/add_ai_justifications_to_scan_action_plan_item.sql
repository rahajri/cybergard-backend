-- Migration: Add ai_justifications column to scan_action_plan_item
-- Date: 2024-12-07
-- Description: Adds ai_justifications column for storing AI-generated justifications
--              for each scan action plan item (vulnerability).
--
-- Structure JSON:
-- {
--   "why_action": "Pourquoi corriger cette vulnérabilité",
--   "why_severity": "Justification de la sévérité",
--   "why_priority": "Justification de la priorité P1/P2/P3",
--   "why_role": "Justification du rôle suggéré",
--   "why_due_days": "Justification du délai recommandé"
-- }

-- Add ai_justifications column (JSONB for better querying)
ALTER TABLE scan_action_plan_item
ADD COLUMN IF NOT EXISTS ai_justifications JSONB DEFAULT NULL;

-- Add comment for documentation
COMMENT ON COLUMN scan_action_plan_item.ai_justifications IS 'AI-generated justifications for the action (why_action, why_severity, why_priority, why_role, why_due_days)';

-- Verify column was added
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'scan_action_plan_item'
  AND column_name = 'ai_justifications';
