-- ============================================================================
-- Script de création d'une organisation de développement
-- Pour permettre au SUPER_ADMIN de tester l'interface client
-- Date: 14 novembre 2025
-- ============================================================================
--
-- OBJECTIF:
-- Créer une organisation de test pour le développement
-- L'associer temporairement au SUPER_ADMIN pour lui permettre de tester
--
-- NOTE: En production, le SUPER_ADMIN ne devrait PAS avoir d'organisation
-- ============================================================================

BEGIN;

\echo '========================================';
\echo 'CRÉATION ORGANISATION DE DÉVELOPPEMENT';
\echo '========================================';

DO $$
DECLARE
    v_tenant_id UUID;
    v_org_id UUID;
    v_user_id UUID;
    v_org_count INTEGER;
    v_category_id UUID;
BEGIN
    -- ========================================================================
    -- 1. Vérifier combien d'organisations existent
    -- ========================================================================

    SELECT COUNT(*) INTO v_org_count FROM organizations;

    RAISE NOTICE 'Organisations existantes: %', v_org_count;

    -- ========================================================================
    -- 2. Récupérer ou créer un tenant de développement
    -- ========================================================================

    -- Chercher un tenant existant
    SELECT id INTO v_tenant_id FROM tenant WHERE name = 'Développement' LIMIT 1;

    IF v_tenant_id IS NULL THEN
        -- Créer un tenant de développement
        v_tenant_id := gen_random_uuid();

        INSERT INTO tenant (
            id,
            name,
            is_active,
            subscription_type,
            max_users,
            max_organizations
        ) VALUES (
            v_tenant_id,
            'Développement',
            true,
            'enterprise',
            100,
            10
        );

        RAISE NOTICE '✓ Tenant de développement créé: %', v_tenant_id;
    ELSE
        RAISE NOTICE '✓ Tenant de développement existant: %', v_tenant_id;
    END IF;

    -- ========================================================================
    -- 3. Créer une organisation de développement (table organization)
    -- ========================================================================

    v_org_id := gen_random_uuid();

    INSERT INTO organization (
        id,
        name,
        domain,
        tenant_id,
        subscription_type,
        email,
        country_code,
        is_active,
        is_platform_owner
    ) VALUES (
        v_org_id,
        'Organisation de Développement',
        'dev.cyberguard.local',
        v_tenant_id,
        'enterprise',
        'dev@cyberguard.local',
        'FR',
        true,
        false  -- ❌ PAS propriétaire de la plateforme (c'est une organisation client)
    );

    RAISE NOTICE '✓ Organisation de développement créée: %', v_org_id;

    -- ========================================================================
    -- 4. Associer le SUPER_ADMIN à cette organisation (TEMPORAIRE)
    -- ========================================================================

    -- Récupérer l'ID du SUPER_ADMIN
    SELECT id INTO v_user_id FROM users WHERE email LIKE '%averroes%' LIMIT 1;

    IF v_user_id IS NULL THEN
        RAISE EXCEPTION 'SUPER_ADMIN introuvable';
    END IF;

    -- Mettre à jour default_org_id (mais garder tenant_id = NULL pour le multi-tenant)
    UPDATE users
    SET default_org_id = v_org_id
    WHERE id = v_user_id;

    RAISE NOTICE '✓ SUPER_ADMIN associé à l''organisation (default_org_id)';

    -- Créer une entrée dans user_organization_role (optionnel - pour cohérence)
    INSERT INTO user_organization_role (
        id,
        user_id,
        organization_id,
        role,
        is_active,
        created_at
    ) VALUES (
        gen_random_uuid(),
        v_user_id,
        v_org_id,
        'admin',
        true,
        now()
    )
    ON CONFLICT DO NOTHING;

    RAISE NOTICE '✓ Entrée user_organization_role créée';

    -- ========================================================================
    -- 5. Afficher le résumé
    -- ========================================================================

    RAISE NOTICE '';
    RAISE NOTICE '========================================';
    RAISE NOTICE 'RÉSUMÉ';
    RAISE NOTICE '========================================';
    RAISE NOTICE 'Tenant ID: %', v_tenant_id;
    RAISE NOTICE 'Organization ID: %', v_org_id;
    RAISE NOTICE 'User ID: %', v_user_id;
    RAISE NOTICE '';
    RAISE NOTICE '✅ L''organisation de développement a été créée';
    RAISE NOTICE '✅ Le SUPER_ADMIN peut maintenant accéder à l''interface client';
    RAISE NOTICE '';
    RAISE NOTICE '⚠️  NOTE: En production, le SUPER_ADMIN ne devrait PAS';
    RAISE NOTICE '    avoir d''organisation associée (tenant_id = NULL)';
    RAISE NOTICE '';
    RAISE NOTICE 'Pour valider: COMMIT;';
    RAISE NOTICE 'Pour annuler: ROLLBACK;';

END $$;

-- Ne pas auto-commit - laisser l'utilisateur décider
-- COMMIT;
