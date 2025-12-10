-- ============================================================================
-- Script d'initialisation de l'organisation par défaut
-- Crée une organisation et l'associe à l'utilisateur super-admin
-- Date: 14 novembre 2025
-- ============================================================================

BEGIN;

-- ============================================================================
-- 1. Vérifier si une organisation existe déjà
-- ============================================================================

DO $$
DECLARE
    org_count INTEGER;
    tenant_count INTEGER;
    user_id UUID;
    tenant_id UUID;
    org_id UUID;
BEGIN
    -- Compter les organisations existantes
    SELECT COUNT(*) INTO org_count FROM organizations;

    IF org_count > 0 THEN
        RAISE NOTICE 'Une organisation existe déjà. Script annulé.';
        ROLLBACK;
        RETURN;
    END IF;

    RAISE NOTICE '========================================';
    RAISE NOTICE 'INITIALISATION ORGANISATION PAR DÉFAUT';
    RAISE NOTICE '========================================';

    -- ========================================================================
    -- 2. Créer un tenant par défaut si nécessaire
    -- ========================================================================

    SELECT COUNT(*) INTO tenant_count FROM tenant;

    IF tenant_count = 0 THEN
        RAISE NOTICE 'Création du tenant par défaut...';

        tenant_id := gen_random_uuid();

        INSERT INTO tenant (
            id,
            name,
            domain,
            is_active,
            subscription_plan,
            created_at
        ) VALUES (
            tenant_id,
            'CYBERGUARD Default',
            'default.cyberguard.local',
            true,
            'enterprise',
            now()
        );

        RAISE NOTICE '✓ Tenant créé: %', tenant_id;
    ELSE
        -- Utiliser le premier tenant existant
        SELECT id INTO tenant_id FROM tenant LIMIT 1;
        RAISE NOTICE '✓ Tenant existant utilisé: %', tenant_id;
    END IF;

    -- ========================================================================
    -- 3. Créer l'organisation par défaut
    -- ========================================================================

    RAISE NOTICE 'Création de l''organisation par défaut...';

    org_id := gen_random_uuid();

    INSERT INTO organizations (
        id,
        name,
        short_name,
        legal_name,
        tenant_id,
        organization_type,
        industry_sector,
        employee_count,
        is_active,
        is_platform_owner,
        created_at
    ) VALUES (
        org_id,
        'Organisation par défaut',
        'DEFAULT',
        'Organisation par défaut CYBERGUARD',
        tenant_id,
        'private_company',
        'information_technology',
        '50-249',
        true,
        true,
        now()
    );

    RAISE NOTICE '✓ Organisation créée: %', org_id;

    -- ========================================================================
    -- 4. Associer l'utilisateur super-admin à l'organisation
    -- ========================================================================

    RAISE NOTICE 'Association de l''utilisateur à l''organisation...';

    -- Récupérer l'ID de l'utilisateur (le premier utilisateur admin)
    SELECT id INTO user_id
    FROM users
    WHERE email LIKE '%averroes%' OR email LIKE '%admin%'
    ORDER BY created_at ASC
    LIMIT 1;

    IF user_id IS NULL THEN
        RAISE NOTICE '⚠ Aucun utilisateur admin trouvé';
    ELSE
        -- Mettre à jour le tenant_id de l'utilisateur
        UPDATE users
        SET tenant_id = tenant_id
        WHERE id = user_id;

        -- Créer une entrée dans user_organization_role
        INSERT INTO user_organization_role (
            id,
            user_id,
            organization_id,
            role,
            created_at
        ) VALUES (
            gen_random_uuid(),
            user_id,
            org_id,
            'admin',
            now()
        )
        ON CONFLICT DO NOTHING;

        RAISE NOTICE '✓ Utilisateur % associé à l''organisation', user_id;
    END IF;

    -- ========================================================================
    -- 5. Afficher le résumé
    -- ========================================================================

    RAISE NOTICE '';
    RAISE NOTICE '========================================';
    RAISE NOTICE 'RÉSUMÉ DE L''INITIALISATION';
    RAISE NOTICE '========================================';
    RAISE NOTICE 'Tenant ID: %', tenant_id;
    RAISE NOTICE 'Organization ID: %', org_id;
    RAISE NOTICE 'User ID: %', COALESCE(user_id::TEXT, 'Aucun');
    RAISE NOTICE '';
    RAISE NOTICE 'Pour valider: COMMIT;';
    RAISE NOTICE 'Pour annuler: ROLLBACK;';

END $$;

-- Ne pas auto-commit - laisser l'utilisateur décider
-- COMMIT;
