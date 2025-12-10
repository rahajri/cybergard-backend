-- Migration: Add answer attachments system
-- Description: GED (mini document management) for question answer attachments with tenant isolation
-- Date: 2025-11-06

-- =====================================================
-- Table: answer_attachment
-- Description: Stores file attachments for question answers with full tenant isolation
-- =====================================================
CREATE TABLE IF NOT EXISTS answer_attachment (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Relations
    answer_id UUID NOT NULL REFERENCES question_answer(id) ON DELETE CASCADE,
    audit_id UUID NOT NULL REFERENCES audit(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL, -- Isolation par tenant (copié depuis audit.tenant_id)

    -- File metadata
    filename VARCHAR(255) NOT NULL, -- Nom de fichier stocké (UUID-based)
    original_filename VARCHAR(255) NOT NULL, -- Nom original du fichier uploadé
    file_path TEXT NOT NULL, -- Chemin relatif: uploads/{tenant_id}/{audit_id}/{answer_id}/{filename}
    file_size BIGINT NOT NULL, -- Taille en bytes
    mime_type VARCHAR(100) NOT NULL, -- Type MIME (application/pdf, image/jpeg, etc.)
    file_extension VARCHAR(10), -- Extension (.pdf, .jpg, etc.)

    -- Categorization
    attachment_type VARCHAR(50) DEFAULT 'evidence', -- 'evidence', 'screenshot', 'policy', 'report', 'other'
    description TEXT, -- Description optionnelle du document

    -- Security & validation
    checksum_sha256 VARCHAR(64), -- Checksum pour intégrité
    virus_scan_status VARCHAR(20) DEFAULT 'pending', -- 'pending', 'clean', 'infected', 'error'
    virus_scan_date TIMESTAMP,

    -- Versioning
    version INTEGER DEFAULT 1,
    is_current BOOLEAN DEFAULT TRUE, -- Only one version should be current per attachment name
    replaced_by UUID REFERENCES answer_attachment(id), -- Link to newer version

    -- Audit trail
    uploaded_by UUID REFERENCES users(id), -- Qui a uploadé
    uploaded_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    deleted_at TIMESTAMP, -- Soft delete
    is_active BOOLEAN DEFAULT TRUE,

    -- Constraints
    CONSTRAINT chk_file_size CHECK (file_size > 0 AND file_size <= 52428800), -- Max 50MB
    CONSTRAINT chk_virus_status CHECK (virus_scan_status IN ('pending', 'clean', 'infected', 'error', 'skipped')),
    CONSTRAINT chk_attachment_type CHECK (attachment_type IN ('evidence', 'screenshot', 'policy', 'report', 'certificate', 'log', 'other'))
);

-- =====================================================
-- Indexes for performance
-- =====================================================
CREATE INDEX idx_attachment_answer ON answer_attachment(answer_id) WHERE is_active = TRUE;
CREATE INDEX idx_attachment_audit ON answer_attachment(audit_id) WHERE is_active = TRUE;
CREATE INDEX idx_attachment_tenant ON answer_attachment(tenant_id) WHERE is_active = TRUE;
CREATE INDEX idx_attachment_uploaded_by ON answer_attachment(uploaded_by);
CREATE INDEX idx_attachment_virus_scan ON answer_attachment(virus_scan_status) WHERE virus_scan_status != 'clean';
CREATE INDEX idx_attachment_current ON answer_attachment(answer_id, original_filename) WHERE is_current = TRUE;

-- =====================================================
-- Unique constraint: One current version per answer + filename
-- =====================================================
CREATE UNIQUE INDEX uq_attachment_current ON answer_attachment(answer_id, original_filename)
WHERE is_current = TRUE AND is_active = TRUE;

-- =====================================================
-- Table: attachment_access_log
-- Description: Audit trail for file downloads/views (RGPD compliance)
-- =====================================================
CREATE TABLE IF NOT EXISTS attachment_access_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    attachment_id UUID NOT NULL REFERENCES answer_attachment(id) ON DELETE CASCADE,
    accessed_by UUID NOT NULL REFERENCES users(id),
    access_type VARCHAR(20) NOT NULL, -- 'view', 'download', 'delete'
    accessed_at TIMESTAMP DEFAULT NOW(),
    ip_address INET,
    user_agent TEXT,
    tenant_id UUID NOT NULL, -- Pour filtrage par tenant

    CONSTRAINT chk_access_type CHECK (access_type IN ('view', 'download', 'preview', 'delete', 'update'))
);

CREATE INDEX idx_access_log_attachment ON attachment_access_log(attachment_id);
CREATE INDEX idx_access_log_user ON attachment_access_log(accessed_by);
CREATE INDEX idx_access_log_tenant ON attachment_access_log(tenant_id);
CREATE INDEX idx_access_log_date ON attachment_access_log(accessed_at);

-- =====================================================
-- Function: Update timestamp automatiquement
-- =====================================================
CREATE OR REPLACE FUNCTION update_attachment_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_attachment_updated
BEFORE UPDATE ON answer_attachment
FOR EACH ROW
EXECUTE FUNCTION update_attachment_timestamp();

-- =====================================================
-- Function: Propager tenant_id depuis audit
-- =====================================================
CREATE OR REPLACE FUNCTION set_attachment_tenant_id()
RETURNS TRIGGER AS $$
BEGIN
    -- Auto-populate tenant_id from audit table
    IF NEW.tenant_id IS NULL THEN
        SELECT tenant_id INTO NEW.tenant_id
        FROM audit
        WHERE id = NEW.audit_id;
    END IF;

    -- Validate that answer belongs to the audit
    IF NOT EXISTS (
        SELECT 1 FROM question_answer
        WHERE id = NEW.answer_id AND audit_id = NEW.audit_id
    ) THEN
        RAISE EXCEPTION 'Answer % does not belong to audit %', NEW.answer_id, NEW.audit_id;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_attachment_set_tenant
BEFORE INSERT ON answer_attachment
FOR EACH ROW
EXECUTE FUNCTION set_attachment_tenant_id();

-- =====================================================
-- View: Attachment summary avec métadonnées enrichies
-- =====================================================
CREATE OR REPLACE VIEW v_attachment_summary AS
SELECT
    att.id,
    att.answer_id,
    att.audit_id,
    att.tenant_id,
    att.original_filename,
    att.file_size,
    att.mime_type,
    att.file_extension,
    att.attachment_type,
    att.description,
    att.virus_scan_status,
    att.version,
    att.is_current,
    att.uploaded_at,
    u.email AS uploaded_by_email,
    u.full_name AS uploaded_by_name,
    aud.name AS audit_name,
    q.text AS question_text,
    -- Stats
    (SELECT COUNT(*) FROM attachment_access_log WHERE attachment_id = att.id) AS access_count,
    (SELECT MAX(accessed_at) FROM attachment_access_log WHERE attachment_id = att.id) AS last_accessed_at
FROM answer_attachment att
LEFT JOIN users u ON att.uploaded_by = u.id
LEFT JOIN audit aud ON att.audit_id = aud.id
LEFT JOIN question_answer qa ON att.answer_id = qa.id
LEFT JOIN question q ON qa.question_id = q.id
WHERE att.is_active = TRUE;

-- =====================================================
-- Comments pour documentation
-- =====================================================
COMMENT ON TABLE answer_attachment IS 'Stores file attachments for question answers with full tenant isolation and versioning support';
COMMENT ON COLUMN answer_attachment.tenant_id IS 'Tenant isolation - automatically populated from audit.tenant_id';
COMMENT ON COLUMN answer_attachment.file_path IS 'Relative path: uploads/{tenant_id}/{audit_id}/{answer_id}/{filename}';
COMMENT ON COLUMN answer_attachment.checksum_sha256 IS 'SHA-256 hash for file integrity verification';
COMMENT ON COLUMN answer_attachment.virus_scan_status IS 'Status of antivirus scan - files with status!=clean should not be downloadable';
COMMENT ON COLUMN answer_attachment.is_current IS 'Only one version per answer+filename should be current';

COMMENT ON TABLE attachment_access_log IS 'Audit trail for file access (RGPD compliance) - tracks who accessed which file when';
