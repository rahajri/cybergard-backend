-- ================================================================
-- Script de nettoyage de la campagne ISO 27001
-- Date: 12/11/2025
--
-- Ce script supprime TOUTES les données liées à la campagne
-- pour repartir sur des tests propres
-- ================================================================

-- ID de la campagne à supprimer
\set campaign_id 'cf805bf4-3efa-4a44-a5f0-c2a3b11e7fcb'
\set scope_id '2b2f8bce-ef97-4140-b4ab-16ac65dd0927'

BEGIN;

-- ================================================================
-- ÉTAPE 1 : Suppression des magic links (audit_tokens)
-- ================================================================
DELETE FROM audit_tokens
WHERE campaign_id = :'campaign_id';
-- Résultat attendu: 2 lignes supprimées

-- ================================================================
-- ÉTAPE 2 : Suppression des réponses (question_answer)
-- ================================================================
DELETE FROM question_answer
WHERE campaign_id = :'campaign_id';
-- Résultat attendu: 0 lignes (aucune réponse enregistrée)

-- ================================================================
-- ÉTAPE 3 : Suppression des audits liés à la campagne
-- Note: Les audits n'ont pas de campaign_id direct
--       Ils sont liés via question_answer ou par le nom
-- ================================================================
DELETE FROM audit
WHERE name LIKE '%ISO 27001%';
-- Résultat attendu: 0 lignes (déjà nettoyé précédemment)

-- ================================================================
-- ÉTAPE 4 : Suppression des assignations de pilotes (campaign_user)
-- ================================================================
DELETE FROM campaign_user
WHERE campaign_id = :'campaign_id';
-- Résultat attendu: 2 lignes supprimées

-- ================================================================
-- ÉTAPE 5 : Suppression de la campagne
-- ================================================================
DELETE FROM campaign
WHERE id = :'campaign_id';
-- Résultat attendu: 1 ligne supprimée

-- ================================================================
-- ÉTAPE 6 : Suppression du scope de la campagne
-- ================================================================
DELETE FROM campaign_scope
WHERE id = :'scope_id';
-- Résultat attendu: 1 ligne supprimée

-- ================================================================
-- VERIFICATION FINALE
-- ================================================================
SELECT
    'Campagnes restantes' as table_name,
    COUNT(*)::text as count
FROM campaign

UNION ALL

SELECT
    'Scopes restants',
    COUNT(*)::text
FROM campaign_scope

UNION ALL

SELECT
    'Assignations restantes',
    COUNT(*)::text
FROM campaign_user

UNION ALL

SELECT
    'Magic links restants',
    COUNT(*)::text
FROM audit_tokens

UNION ALL

SELECT
    'Audits restants',
    COUNT(*)::text
FROM audit

UNION ALL

SELECT
    'Réponses restantes',
    COUNT(*)::text
FROM question_answer;

COMMIT;

-- ================================================================
-- Fin du nettoyage
-- ================================================================
