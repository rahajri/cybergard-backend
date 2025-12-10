-- ============================================================================
-- Script de nettoyage des données de test
-- ATTENTION: Préserve les catégories et pôles UNIVERSELS (is_base_template = true)
-- Date: 14 novembre 2025
-- ============================================================================

BEGIN;

-- ============================================================================
-- ÉTAPE 1: Afficher les statistiques AVANT suppression
-- ============================================================================

\echo '========================================';
\echo 'STATISTIQUES AVANT SUPPRESSION';
\echo '========================================';

SELECT 'Categories universelles' AS table_name, COUNT(*) AS count
FROM categories WHERE is_base_template = true OR tenant_id IS NULL;

SELECT 'Categories tenant-specific' AS table_name, COUNT(*) AS count
FROM categories WHERE tenant_id IS NOT NULL;

SELECT 'Poles universels' AS table_name, COUNT(*) AS count
FROM poles WHERE is_base_template = true OR tenant_id IS NULL;

SELECT 'Poles tenant-specific' AS table_name, COUNT(*) AS count
FROM poles WHERE tenant_id IS NOT NULL;

SELECT 'Ecosystem entities' AS table_name, COUNT(*) AS count
FROM ecosystem_entity;

SELECT 'Users' AS table_name, COUNT(*) AS count
FROM users;

SELECT 'Campaigns' AS table_name, COUNT(*) AS count
FROM campaign;

SELECT 'Question answers' AS table_name, COUNT(*) AS count
FROM question_answer;

\echo '';

-- ============================================================================
-- ÉTAPE 2: Supprimer les données dépendantes (dans l'ordre)
-- ============================================================================

\echo '========================================';
\echo 'SUPPRESSION DES DONNÉES DÉPENDANTES';
\echo '========================================';

-- 2.1 Supprimer les réponses aux questions
\echo 'Suppression des question_answer...';
DELETE FROM question_answer;

-- 2.2 Supprimer les commentaires sur les questions
\echo 'Suppression des question_comment...';
DELETE FROM question_comment;

-- 2.3 Supprimer les assignations de campagne utilisateurs
\echo 'Suppression des campaign_user...';
DELETE FROM campaign_user;

-- 2.4 Supprimer les scopes de domaine d'audit
\echo 'Suppression des audite_domain_scope...';
DELETE FROM audite_domain_scope;

-- 2.5 Supprimer les tokens d'audit
\echo 'Suppression des audit_tokens...';
DELETE FROM audit_tokens;

-- 2.6 Supprimer toutes les campagnes (AVANT campaign_scope)
\echo 'Suppression des campaign...';
DELETE FROM campaign;

-- 2.7 Supprimer les scopes de campagne
\echo 'Suppression des campaign_scope...';
DELETE FROM campaign_scope;

\echo '';

-- ============================================================================
-- ÉTAPE 3: Supprimer les relations d'entités ecosystem
-- ============================================================================

\echo '========================================';
\echo 'SUPPRESSION DES RELATIONS ECOSYSTEM';
\echo '========================================';

-- 3.1 Supprimer les relations entre entités
\echo 'Suppression des entity_relationship...';
DELETE FROM entity_relationship;

-- 3.2 Supprimer les membres d'entités
\echo 'Suppression des entity_member...';
DELETE FROM entity_member;

-- 3.3 Supprimer les activations de questionnaires d'entités
\echo 'Suppression des entity_questionnaire_activation...';
DELETE FROM entity_questionnaire_activation;

-- 3.4 Supprimer les activations de frameworks d'entités
\echo 'Suppression des entity_framework_activation...';
DELETE FROM entity_framework_activation;

-- 3.5 Supprimer les documents d'entités
\echo 'Suppression des entity_document...';
DELETE FROM entity_document;

-- 3.6 Supprimer les scope_template liés aux entités
\echo 'Suppression des scope_template...';
DELETE FROM scope_template;

\echo '';

-- ============================================================================
-- ÉTAPE 4: Supprimer les entités ecosystem (avec catégories)
-- ============================================================================

\echo '========================================';
\echo 'SUPPRESSION DES ENTITÉS ECOSYSTEM';
\echo '========================================';

-- 4.1 Supprimer les entités qui ont une catégorie (externes)
\echo 'Suppression des ecosystem_entity avec category_id...';
DELETE FROM ecosystem_entity WHERE category_id IS NOT NULL;

-- 4.2 Supprimer les entités qui ont un pôle (internes)
\echo 'Suppression des ecosystem_entity avec pole_id...';
DELETE FROM ecosystem_entity WHERE pole_id IS NOT NULL;

-- 4.3 Supprimer toutes les autres entités restantes
\echo 'Suppression des ecosystem_entity restantes...';
DELETE FROM ecosystem_entity;

\echo '';

-- ============================================================================
-- ÉTAPE 5: Supprimer les catégories TENANT-SPECIFIC uniquement
-- ============================================================================

\echo '========================================';
\echo 'SUPPRESSION DES CATÉGORIES TENANT-SPECIFIC';
\echo '========================================';

-- IMPORTANT: Ne supprimer QUE les catégories avec tenant_id
-- Préserver les catégories universelles (is_base_template = true)
\echo 'Suppression des categories tenant-specific (préserve les universelles)...';
DELETE FROM categories
WHERE tenant_id IS NOT NULL
  AND (is_base_template = false OR is_base_template IS NULL);

\echo '';

-- ============================================================================
-- ÉTAPE 6: Supprimer les pôles TENANT-SPECIFIC uniquement
-- ============================================================================

\echo '========================================';
\echo 'SUPPRESSION DES PÔLES TENANT-SPECIFIC';
\echo '========================================';

-- IMPORTANT: Ne supprimer QUE les pôles avec tenant_id
-- Préserver les pôles universels (is_base_template = true)
\echo 'Suppression des poles tenant-specific (préserve les universels)...';
DELETE FROM poles
WHERE tenant_id IS NOT NULL
  AND (is_base_template = false OR is_base_template IS NULL);

\echo '';

-- ============================================================================
-- ÉTAPE 7: Supprimer les rôles utilisateur-organisation
-- ============================================================================

\echo '========================================';
\echo 'SUPPRESSION DES RÔLES UTILISATEUR';
\echo '========================================';

\echo 'Suppression des user_organization_role...';
DELETE FROM user_organization_role;

\echo 'Suppression des user_audit_role...';
DELETE FROM user_audit_role;

\echo 'Suppression des user_perimeter_role...';
DELETE FROM user_perimeter_role;

\echo 'Suppression des user_role...';
DELETE FROM user_role;

\echo '';

-- ============================================================================
-- ÉTAPE 8: Supprimer les utilisateurs NON-ADMIN
-- ============================================================================

\echo '========================================';
\echo 'SUPPRESSION DES UTILISATEURS';
\echo '========================================';

-- IMPORTANT: Préserver les utilisateurs admin Keycloak
-- Ne supprimer que les utilisateurs de test (qui ne sont pas admin)
\echo 'Suppression des users (préserve les admins avec @admin dans email)...';
DELETE FROM users
WHERE email NOT LIKE '%@admin.%'
  AND email NOT LIKE '%admin%';

\echo '';

-- ============================================================================
-- ÉTAPE 9: Afficher les statistiques APRÈS suppression
-- ============================================================================

\echo '========================================';
\echo 'STATISTIQUES APRÈS SUPPRESSION';
\echo '========================================';

SELECT 'Categories universelles' AS table_name, COUNT(*) AS count
FROM categories WHERE is_base_template = true OR tenant_id IS NULL;

SELECT 'Categories tenant-specific' AS table_name, COUNT(*) AS count
FROM categories WHERE tenant_id IS NOT NULL;

SELECT 'Poles universels' AS table_name, COUNT(*) AS count
FROM poles WHERE is_base_template = true OR tenant_id IS NULL;

SELECT 'Poles tenant-specific' AS table_name, COUNT(*) AS count
FROM poles WHERE tenant_id IS NOT NULL;

SELECT 'Ecosystem entities' AS table_name, COUNT(*) AS count
FROM ecosystem_entity;

SELECT 'Users (after cleanup)' AS table_name, COUNT(*) AS count
FROM users;

SELECT 'Campaigns' AS table_name, COUNT(*) AS count
FROM campaign;

SELECT 'Question answers' AS table_name, COUNT(*) AS count
FROM question_answer;

\echo '';
\echo '========================================';
\echo 'DONNÉES UNIVERSELLES PRÉSERVÉES:';
\echo '========================================';

SELECT 'CATEGORIES UNIVERSELLES:' AS info;
SELECT id, name, entity_category, is_base_template
FROM categories
WHERE is_base_template = true OR tenant_id IS NULL
ORDER BY name;

SELECT 'POLES UNIVERSELS:' AS info;
SELECT id, name, short_code, is_base_template
FROM poles
WHERE is_base_template = true OR tenant_id IS NULL
ORDER BY name;

\echo '';
\echo '========================================';
\echo 'NETTOYAGE TERMINÉ';
\echo '========================================';
\echo 'Pour valider: COMMIT;';
\echo 'Pour annuler: ROLLBACK;';

-- Ne pas auto-commit - laisser l'utilisateur décider
-- COMMIT;
