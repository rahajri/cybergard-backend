-- Migration: Create external scan tables for ASM module
-- Date: 2024-12-02
-- Description: Creates all necessary tables for external vulnerability scanning

-- Create enum types if they don't exist
DO $$ BEGIN
    CREATE TYPE externaltargettype AS ENUM ('DOMAIN', 'SUBDOMAIN', 'IP', 'IP_RANGE', 'EMAIL_DOMAIN');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE scanfrequency AS ENUM ('MANUAL', 'DAILY', 'WEEKLY', 'MONTHLY');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE scanstatus AS ENUM ('NEVER', 'SUCCESS', 'ERROR');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE scanexecutionstatus AS ENUM ('PENDING', 'RUNNING', 'SUCCESS', 'ERROR', 'CANCELLED');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE severitylevel AS ENUM ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE vulnerabilitytype AS ENUM ('PORT_EXPOSED', 'SERVICE_VULN', 'TLS_WEAK', 'CERT_ISSUE', 'HEADER_MISSING', 'MISCONFIGURATION');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Create external_target table
CREATE TABLE IF NOT EXISTS external_target (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    entity_id UUID, -- Optional link to ecosystem_entity (no FK constraint for now)
    type externaltargettype NOT NULL,
    value VARCHAR(255) NOT NULL,
    label VARCHAR(255),
    description TEXT,
    scan_frequency scanfrequency DEFAULT 'MANUAL',
    is_active BOOLEAN DEFAULT true,
    last_scan_at TIMESTAMP,
    last_scan_status scanstatus DEFAULT 'NEVER',
    last_exposure_score INTEGER,
    created_by UUID,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    deleted_at TIMESTAMP
);

-- Create indexes for external_target
CREATE INDEX IF NOT EXISTS ix_external_target_tenant_id ON external_target(tenant_id);
CREATE INDEX IF NOT EXISTS ix_external_target_tenant_type ON external_target(tenant_id, type);
CREATE INDEX IF NOT EXISTS ix_external_target_value ON external_target(value);
CREATE INDEX IF NOT EXISTS ix_external_target_entity ON external_target(entity_id);

-- Create external_scan table
CREATE TABLE IF NOT EXISTS external_scan (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code_scan VARCHAR(20),
    external_target_id UUID NOT NULL REFERENCES external_target(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL,
    entity_id UUID, -- Optional link to ecosystem_entity
    status scanexecutionstatus DEFAULT 'PENDING',
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    error_message TEXT,
    summary JSONB,
    scan_data JSONB, -- Complete scan data for detailed display
    report_generated BOOLEAN DEFAULT false,
    report_id UUID,
    triggered_by UUID,
    trigger_type VARCHAR(50) DEFAULT 'manual',
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Create indexes for external_scan
CREATE INDEX IF NOT EXISTS ix_external_scan_target ON external_scan(external_target_id);
CREATE INDEX IF NOT EXISTS ix_external_scan_tenant ON external_scan(tenant_id);
CREATE INDEX IF NOT EXISTS ix_external_scan_status ON external_scan(status);
CREATE INDEX IF NOT EXISTS ix_external_scan_created ON external_scan(created_at);
CREATE INDEX IF NOT EXISTS ix_external_scan_entity ON external_scan(entity_id);
CREATE INDEX IF NOT EXISTS ix_external_scan_code ON external_scan(code_scan);

-- GIN index for efficient JSONB queries on scan_data
CREATE INDEX IF NOT EXISTS ix_external_scan_scan_data ON external_scan USING GIN (scan_data jsonb_path_ops);

-- Partial index for scans with TLS details
CREATE INDEX IF NOT EXISTS ix_external_scan_has_tls ON external_scan ((scan_data ? 'tls_details')) WHERE scan_data IS NOT NULL;

-- Create external_service_vulnerability table
CREATE TABLE IF NOT EXISTS external_service_vulnerability (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_scan_id UUID NOT NULL REFERENCES external_scan(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL,
    port INTEGER,
    protocol VARCHAR(20),
    service_name VARCHAR(100),
    service_version VARCHAR(100),
    service_banner TEXT,
    vulnerability_type vulnerabilitytype NOT NULL,
    severity severitylevel NOT NULL,
    cve_ids JSONB,
    cvss_score FLOAT,
    cvss_vector VARCHAR(100),
    title VARCHAR(255) NOT NULL,
    description TEXT,
    recommendation TEXT,
    "references" JSONB,
    is_remediated BOOLEAN DEFAULT false,
    remediated_at TIMESTAMP,
    remediated_by UUID,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Create indexes for external_service_vulnerability
CREATE INDEX IF NOT EXISTS ix_vuln_scan ON external_service_vulnerability(external_scan_id);
CREATE INDEX IF NOT EXISTS ix_vuln_tenant ON external_service_vulnerability(tenant_id);
CREATE INDEX IF NOT EXISTS ix_vuln_severity ON external_service_vulnerability(severity);
CREATE INDEX IF NOT EXISTS ix_vuln_type ON external_service_vulnerability(vulnerability_type);

-- Create external_email_exposure table (for future OSINT features)
CREATE TABLE IF NOT EXISTS external_email_exposure (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_scan_id UUID NOT NULL REFERENCES external_scan(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL,
    email VARCHAR(255) NOT NULL,
    breach_count INTEGER DEFAULT 0,
    last_breach_date DATE,
    sources JSONB,
    recommendation TEXT,
    is_remediated BOOLEAN DEFAULT false,
    remediated_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Create indexes for external_email_exposure
CREATE INDEX IF NOT EXISTS ix_email_scan ON external_email_exposure(external_scan_id);
CREATE INDEX IF NOT EXISTS ix_email_address ON external_email_exposure(email);
CREATE INDEX IF NOT EXISTS ix_email_tenant ON external_email_exposure(tenant_id);

-- Add comments
COMMENT ON TABLE external_target IS 'Targets to scan (domains, IPs, subdomains) for ASM module';
COMMENT ON TABLE external_scan IS 'Scan execution history with results';
COMMENT ON TABLE external_service_vulnerability IS 'Vulnerabilities detected during scans';
COMMENT ON TABLE external_email_exposure IS 'Email exposures found via OSINT (V2 feature)';
COMMENT ON COLUMN external_scan.scan_data IS 'Complete scan data including services, TLS details, infrastructure info, and raw nmap command';

-- Verification query
SELECT
    tablename
FROM pg_tables
WHERE schemaname = 'public'
AND tablename LIKE 'external%'
ORDER BY tablename;
