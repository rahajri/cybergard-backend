-- Migration: Add scan_data column to external_scan table
-- Date: 2024-12-02
-- Description: Adds a JSONB column to store complete scan data including
--              services, TLS details, infrastructure info, and raw command

-- Add the scan_data column to external_scan table
ALTER TABLE external_scan
ADD COLUMN IF NOT EXISTS scan_data JSONB;

-- Comment on the column
COMMENT ON COLUMN external_scan.scan_data IS 'Complete scan data including services, TLS details, infrastructure info, and raw nmap command';

-- Create a GIN index for efficient JSON queries
CREATE INDEX IF NOT EXISTS ix_external_scan_scan_data
ON external_scan USING GIN (scan_data jsonb_path_ops);

-- Add a partial index for scans with TLS details
CREATE INDEX IF NOT EXISTS ix_external_scan_has_tls
ON external_scan ((scan_data ? 'tls_details'))
WHERE scan_data IS NOT NULL;

-- Verification query (to check the migration was applied)
-- SELECT column_name, data_type
-- FROM information_schema.columns
-- WHERE table_name = 'external_scan' AND column_name = 'scan_data';
