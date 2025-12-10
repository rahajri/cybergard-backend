-- Migration: Update existing scan actions with CVE data
-- Date: 2024-12-07
-- Description: Met à jour les actions existantes issues de scans pour récupérer
--              les données CVE depuis leurs scan_action_plan_item sources.
--
-- NOTE: scan_action_plan_item.cve_ids est de type JSONB (tableau JSON)
--       published_action.cve_ids est de type TEXT[] (tableau PostgreSQL)
--       La conversion JSONB -> TEXT[] se fait via jsonb_array_elements_text()

-- Mise à jour des actions qui ont un scan_action_plan_item_id mais pas de CVE
-- Conversion JSONB -> TEXT[]
UPDATE published_action pa
SET
    cve_ids = (
        SELECT ARRAY(
            SELECT jsonb_array_elements_text(sapi.cve_ids)
        )
    ),
    cvss_score = sapi.cvss_score,
    cve_source_url = CASE
        WHEN sapi.cve_ids IS NOT NULL AND jsonb_array_length(sapi.cve_ids) > 0
        THEN 'https://nvd.nist.gov/vuln/detail/' || (sapi.cve_ids->>0)
        ELSE NULL
    END,
    updated_at = NOW()
FROM scan_action_plan_item sapi
WHERE pa.scan_action_plan_item_id = sapi.id
  AND pa.source_type = 'scan'
  AND (pa.cve_ids IS NULL OR array_length(pa.cve_ids, 1) IS NULL OR array_length(pa.cve_ids, 1) = 0);

-- Également mettre à jour via scan_id pour les anciennes actions qui n'ont pas scan_action_plan_item_id
-- mais qui peuvent être liées via le code_action et le scan
UPDATE published_action pa
SET
    cve_ids = (
        SELECT ARRAY(
            SELECT jsonb_array_elements_text(sapi.cve_ids)
        )
    ),
    cvss_score = sapi.cvss_score,
    cve_source_url = CASE
        WHEN sapi.cve_ids IS NOT NULL AND jsonb_array_length(sapi.cve_ids) > 0
        THEN 'https://nvd.nist.gov/vuln/detail/' || (sapi.cve_ids->>0)
        ELSE NULL
    END,
    scan_action_plan_item_id = sapi.id,
    updated_at = NOW()
FROM scan_action_plan_item sapi
JOIN scan_action_plan sap ON sapi.scan_action_plan_id = sap.id
WHERE pa.scan_id = sap.scan_id
  AND pa.code_action = sapi.code_action
  AND pa.source_type = 'scan'
  AND pa.scan_action_plan_item_id IS NULL
  AND (pa.cve_ids IS NULL OR array_length(pa.cve_ids, 1) IS NULL OR array_length(pa.cve_ids, 1) = 0);

-- Vérification: Afficher les actions mises à jour
SELECT
    pa.id,
    pa.code_action,
    pa.title,
    pa.cve_ids,
    pa.cvss_score,
    pa.cve_source_url,
    pa.scan_action_plan_item_id
FROM published_action pa
WHERE pa.source_type = 'scan'
ORDER BY pa.updated_at DESC
LIMIT 20;
