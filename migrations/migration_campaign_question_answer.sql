-- ============================================================================
-- Migration: Remplacer audit_id par campaign_id dans question_answer
-- Description:
--   - Ajoute campaign_id à question_answer
--   - Rend audit_id nullable (pour compatibilité avec anciens audits)
--   - Supprime la table evaluation (remplacée par campaign)
-- ============================================================================

BEGIN;

-- 1. Ajouter la colonne campaign_id à question_answer
ALTER TABLE question_answer
ADD COLUMN campaign_id UUID;

-- 2. Rendre audit_id nullable (pour compatibilité avec anciens audits)
ALTER TABLE question_answer
ALTER COLUMN audit_id DROP NOT NULL;

-- 3. Ajouter la contrainte FK vers campaign
ALTER TABLE question_answer
ADD CONSTRAINT question_answer_campaign_id_fkey
FOREIGN KEY (campaign_id) REFERENCES campaign(id) ON DELETE CASCADE;

-- 4. Créer un index sur campaign_id
CREATE INDEX idx_question_answer_campaign ON question_answer(campaign_id);

-- 5. Modifier les contraintes UNIQUE pour supporter campaign_id
-- Supprimer les anciennes contraintes qui ne concernent que audit_id
ALTER TABLE question_answer DROP CONSTRAINT IF EXISTS uq_qanswer_current;
ALTER TABLE question_answer DROP CONSTRAINT IF EXISTS uq_question_answer_current;
ALTER TABLE question_answer DROP CONSTRAINT IF EXISTS uq_qanswer_version;

-- 6. Créer de nouvelles contraintes qui supportent les deux modes (audit et campaign)
-- Une seule réponse "current" par audit/question OU par campaign/question
CREATE UNIQUE INDEX uq_question_answer_audit_current
ON question_answer(audit_id, question_id)
WHERE is_current = true AND audit_id IS NOT NULL;

CREATE UNIQUE INDEX uq_question_answer_campaign_current
ON question_answer(campaign_id, question_id)
WHERE is_current = true AND campaign_id IS NOT NULL;

-- Version unique par audit/question OU par campaign/question
CREATE UNIQUE INDEX uq_question_answer_audit_version
ON question_answer(audit_id, question_id, version)
WHERE audit_id IS NOT NULL;

CREATE UNIQUE INDEX uq_question_answer_campaign_version
ON question_answer(campaign_id, question_id, version)
WHERE campaign_id IS NOT NULL;

-- 7. Ajouter une contrainte CHECK pour s'assurer qu'au moins un de audit_id ou campaign_id est renseigné
ALTER TABLE question_answer
ADD CONSTRAINT chk_question_answer_parent
CHECK (
    (audit_id IS NOT NULL AND campaign_id IS NULL) OR
    (audit_id IS NULL AND campaign_id IS NOT NULL)
);

-- 8. Supprimer la table evaluation (remplacée par campaign)
-- D'abord supprimer les contraintes FK qui pointent vers evaluation
-- (Il n'y en a normalement pas selon le schéma actuel)

DROP TABLE IF EXISTS evaluation CASCADE;

-- 9. Ajouter un commentaire pour documenter la migration
COMMENT ON COLUMN question_answer.campaign_id IS 'Lien vers la campagne (nouveau système remplaçant audit)';
COMMENT ON COLUMN question_answer.audit_id IS 'Lien vers audit (ancien système, conservé pour compatibilité)';

COMMIT;

-- ============================================================================
-- Vérifications post-migration
-- ============================================================================

-- Vérifier la structure de question_answer
\d question_answer

-- Vérifier que la table evaluation a été supprimée
SELECT COUNT(*) FROM pg_tables WHERE schemaname = 'public' AND tablename = 'evaluation';
