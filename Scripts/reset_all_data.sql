-- ============================================================================
-- Script de réinitialisation complète de la base de données
-- Supprime TOUTES les données (sauf les catégories/pôles universels)
-- Date: 14 novembre 2025
-- ============================================================================
--
-- OBJECTIF:
-- 1. Supprimer tous les tenants et organisations
-- 2. Supprimer tous les utilisateurs (sauf SUPER_ADMIN)
-- 3. Préserver les catégories et pôles universels
-- 4. Nettoyer toutes les données de test
--
-- ============================================================================

BEGIN;

\echo '========================================';
\echo 'RÉINITIALISATION COMPLÈTE';
\echo '========================================';

-- ============================================================================
-- ÉTAPE 1: Supprimer les données liées aux audits et campagnes
-- ============================================================================

\echo '';
\echo 'Suppression des données d''audit...';

DELETE FROM question_comment;
DELETE FROM question_answer;
DELETE FROM audite_domain_scope;
DELETE FROM audit_tokens;
DELETE FROM campaign_user;
DELETE FROM campaign;
DELETE FROM campaign_scope;
DELETE FROM audit;  -- ✅ IMPORTANT: Supprimer les audits avant les organisations

\echo '✓ Données d''audit supprimées';

-- ============================================================================
-- ÉTAPE 2: Supprimer les données d'écosystème
-- ============================================================================

\echo '';
\echo 'Suppression des données d''écosystème...';

DELETE FROM entity_member;
DELETE FROM entity_relationship;
DELETE FROM entity_framework_activation;
DELETE FROM entity_questionnaire_activation;
DELETE FROM ecosystem_entity;

\echo '✓ Données d''écosystème supprimées';

-- ============================================================================
-- ÉTAPE 3: Nettoyer les utilisateurs AVANT de supprimer les organisations
-- ============================================================================

\echo '';
\echo 'Nettoyage des utilisateurs...';

-- Supprimer les utilisateurs non-admin
DELETE FROM users WHERE email NOT LIKE '%averroes%';

-- Nettoyer le SUPER_ADMIN (retirer les liens vers organisation)
UPDATE users
SET tenant_id = NULL, default_org_id = NULL
WHERE email LIKE '%averroes%';

\echo '✓ Utilisateurs nettoyés';

-- ============================================================================
-- ÉTAPE 4: Supprimer les organisations et relations
-- ============================================================================

\echo '';
\echo 'Suppression des organisations...';

DELETE FROM user_organization_role;
DELETE FROM organization_relationship;
DELETE FROM org_relationship;
DELETE FROM organizations WHERE is_platform_owner = false;
DELETE FROM organization WHERE is_platform_owner = false;

\echo '✓ Organisations supprimées';

-- ============================================================================
-- ÉTAPE 5: Supprimer les tenants
-- ============================================================================

\echo '';
\echo 'Suppression des tenants...';

DELETE FROM tenant;

\echo '✓ Tenants supprimés';

-- ============================================================================
-- ÉTAPE 6: Supprimer les catégories NON-UNIVERSELLES
-- ============================================================================

\echo '';
\echo 'Suppression des catégories non-universelles...';

DELETE FROM category_relationships
WHERE parent_category_id IN (
    SELECT id FROM categories WHERE is_base_template = false OR tenant_id IS NOT NULL
)
OR child_category_id IN (
    SELECT id FROM categories WHERE is_base_template = false OR tenant_id IS NOT NULL
);

DELETE FROM categories
WHERE is_base_template = false OR tenant_id IS NOT NULL;

\echo '✓ Catégories non-universelles supprimées';

-- ============================================================================
-- ÉTAPE 7: Supprimer les pôles NON-UNIVERSELS
-- ============================================================================

\echo '';
\echo 'Suppression des pôles non-universels...';

DELETE FROM poles
WHERE is_base_template = false OR tenant_id IS NOT NULL;

\echo '✓ Pôles non-universels supprimés';

-- ============================================================================
-- ÉTAPE 8: Afficher les statistiques finales
-- ============================================================================

\echo '';
\echo '========================================';
\echo 'STATISTIQUES APRÈS RÉINITIALISATION';
\echo '========================================';

SELECT
    'Tenants' as table_name,
    COUNT(*) as count
FROM tenant
UNION ALL
SELECT 'Organizations (avec s)', COUNT(*) FROM organizations
UNION ALL
SELECT 'Organization (sans s)', COUNT(*) FROM organization
UNION ALL
SELECT 'Users', COUNT(*) FROM users
UNION ALL
SELECT 'Categories', COUNT(*) FROM categories
UNION ALL
SELECT 'Categories universelles', COUNT(*) FROM categories WHERE is_base_template = true
UNION ALL
SELECT 'Poles', COUNT(*) FROM poles
UNION ALL
SELECT 'Poles universels', COUNT(*) FROM poles WHERE is_base_template = true
UNION ALL
SELECT 'Ecosystem entities', COUNT(*) FROM ecosystem_entity
UNION ALL
SELECT 'Campaigns', COUNT(*) FROM campaign;

\echo '';
\echo '========================================';
\echo 'VÉRIFICATION SUPER_ADMIN';
\echo '========================================';

SELECT
    u.id,
    u.email,
    u.tenant_id,
    u.default_org_id,
    r.code as role
FROM users u
LEFT JOIN user_role ur ON u.id = ur.user_id
LEFT JOIN role r ON ur.role_id = r.id
WHERE u.email LIKE '%averroes%';

\echo '';
\echo '========================================';
\echo 'RÉSUMÉ';
\echo '========================================';
\echo '✓ Base de données réinitialisée';
\echo '✓ SUPER_ADMIN préservé (tenant_id = NULL, default_org_id = NULL)';
\echo '✓ Catégories universelles préservées';
\echo '✓ Pôles universels préservés';
\echo '';
\echo 'Pour valider: COMMIT;';
\echo 'Pour annuler: ROLLBACK;';

-- Ne pas auto-commit - laisser l'utilisateur décider
-- COMMIT;
