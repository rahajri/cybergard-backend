-- Migration: Add CVE columns to published_action table
-- Date: 2024-12-07
-- Description: Adds cve_ids, cvss_score, cve_source_url and scan_action_plan_item_id columns
--              to support CVE tracking for actions generated from scanner vulnerabilities.

-- Add cve_ids column (array of strings for CVE identifiers)
ALTER TABLE published_action
ADD COLUMN IF NOT EXISTS cve_ids TEXT[] DEFAULT '{}';

-- Add cvss_score column (float for CVSS score 0.0-10.0)
ALTER TABLE published_action
ADD COLUMN IF NOT EXISTS cvss_score FLOAT;

-- Add cve_source_url column (link to NVD or other CVE source)
ALTER TABLE published_action
ADD COLUMN IF NOT EXISTS cve_source_url VARCHAR(500);

-- Add scan_action_plan_item_id column (FK to scan_action_plan_item)
ALTER TABLE published_action
ADD COLUMN IF NOT EXISTS scan_action_plan_item_id UUID REFERENCES scan_action_plan_item(id) ON DELETE SET NULL;

-- Create GIN index on cve_ids for faster lookups
CREATE INDEX IF NOT EXISTS ix_published_action_cve_ids
ON published_action USING GIN (cve_ids);

-- Verify columns were added
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'published_action'
  AND column_name IN ('cve_ids', 'cvss_score', 'cve_source_url', 'scan_action_plan_item_id')
ORDER BY column_name;
