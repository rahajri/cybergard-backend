-- ============================================================================
-- Script de migration du rôle SUPER_ADMIN
-- Date: 14 novembre 2025
-- ============================================================================
--
-- OBJECTIF:
-- 1. Nettoyer le compte SUPER_ADMIN (averroes2013@gmail.com)
--    - Supprimer les associations organisation
--    - Mettre tenant_id à NULL pour permettre l'accès multi-tenant
--
-- ============================================================================

BEGIN;

\echo '========================================';
\echo 'MIGRATION SUPER_ADMIN';
\echo '========================================';

-- ============================================================================
-- ÉTAPE 1: Afficher l'état AVANT migration
-- ============================================================================

\echo '';
\echo 'ÉTAT AVANT MIGRATION:';
\echo '========================================';

SELECT
    u.id,
    u.email,
    u.tenant_id,
    r.code as role_code
FROM users u
LEFT JOIN user_role ur ON u.id = ur.user_id
LEFT JOIN role r ON ur.role_id = r.id
WHERE u.email LIKE '%averroes%'
ORDER BY u.email;

-- ============================================================================
-- ÉTAPE 2: Nettoyer le compte SUPER_ADMIN (averroes2013@gmail.com)
-- ============================================================================

\echo '';
\echo 'NETTOYAGE SUPER_ADMIN (averroes2013@gmail.com):';
\echo '========================================';

-- 2.1 Supprimer les associations organisation
\echo 'Suppression des associations organisation pour SUPER_ADMIN...';
DELETE FROM user_organization_role
WHERE user_id = '260995ce-5c5e-4e4e-af12-9440e38cb9c6';

-- 2.2 Mettre tenant_id à NULL
\echo 'Mise à NULL du tenant_id pour SUPER_ADMIN...';
UPDATE users
SET tenant_id = NULL
WHERE id = '260995ce-5c5e-4e4e-af12-9440e38cb9c6';

\echo '✓ SUPER_ADMIN nettoyé';

-- ============================================================================
-- ÉTAPE 3: Vérification de la cohérence
-- ============================================================================

\echo '';
\echo 'VÉRIFICATION:';
\echo '========================================';

-- Vérifier que le rôle SUPER_ADMIN est bien assigné
DO $$
DECLARE
    super_admin_role_id UUID;
    v_user_id UUID;
    has_role BOOLEAN;
BEGIN
    -- Récupérer l'ID de l'utilisateur
    SELECT id INTO v_user_id FROM users WHERE email LIKE '%averroes%' LIMIT 1;

    IF v_user_id IS NULL THEN
        RAISE EXCEPTION 'Utilisateur SUPER_ADMIN introuvable';
    END IF;

    -- Récupérer l'ID du rôle SUPER_ADMIN
    SELECT id INTO super_admin_role_id FROM role WHERE code = 'SUPER_ADMIN';

    IF super_admin_role_id IS NULL THEN
        RAISE EXCEPTION 'Rôle SUPER_ADMIN introuvable';
    END IF;

    -- Vérifier si le rôle est assigné
    SELECT EXISTS(
        SELECT 1 FROM user_role ur
        WHERE ur.user_id = v_user_id
        AND ur.role_id = super_admin_role_id
    ) INTO has_role;

    IF NOT has_role THEN
        RAISE NOTICE 'Attribution du rôle SUPER_ADMIN...';
        INSERT INTO user_role (user_id, role_id)
        VALUES (v_user_id, super_admin_role_id)
        ON CONFLICT DO NOTHING;
        RAISE NOTICE '✓ Rôle SUPER_ADMIN assigné';
    ELSE
        RAISE NOTICE '✓ Rôle SUPER_ADMIN déjà assigné';
    END IF;

END $$;

-- ============================================================================
-- ÉTAPE 4: Afficher l'état APRÈS migration
-- ============================================================================

\echo '';
\echo 'ÉTAT APRÈS MIGRATION:';
\echo '========================================';

SELECT
    u.id,
    u.email,
    u.tenant_id,
    r.code as role_code,
    CASE
        WHEN u.tenant_id IS NULL THEN 'Multi-tenant (Plateforme)'
        ELSE 'Tenant spécifique'
    END as tenant_type
FROM users u
LEFT JOIN user_role ur ON u.id = ur.user_id
LEFT JOIN role r ON ur.role_id = r.id
WHERE u.email LIKE '%averroes%'
ORDER BY r.code, u.email;

-- ============================================================================
-- ÉTAPE 5: Vérifier les associations organisation
-- ============================================================================

\echo '';
\echo 'ASSOCIATIONS ORGANISATION:';
\echo '========================================';

SELECT
    u.email,
    o.name as organization_name,
    uor.role as org_role
FROM users u
JOIN user_organization_role uor ON u.id = uor.user_id
JOIN organizations o ON uor.organization_id = o.id
WHERE u.email LIKE '%averroes%'
ORDER BY u.email;

\echo '';
\echo '========================================';
\echo 'RÉSUMÉ DE LA MIGRATION:';
\echo '========================================';
\echo '✓ SUPER_ADMIN (averroes2013@gmail.com):';
\echo '    - tenant_id = NULL (accès multi-tenant)';
\echo '    - Aucune association organisation';
\echo '    - Rôle: SUPER_ADMIN';
\echo '';
\echo 'IMPORTANT:';
\echo '    - Pensez à synchroniser les rôles dans Keycloak';
\echo '    - Le rôle SUPER_ADMIN doit être assigné dans Keycloak';
\echo '';
\echo 'Pour valider: COMMIT;';
\echo 'Pour annuler: ROLLBACK;';

-- Ne pas auto-commit - laisser l'utilisateur décider
-- COMMIT;
