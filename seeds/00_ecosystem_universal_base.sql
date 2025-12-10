-- ============================================================================
-- SEED : Structure universelle de l'écosystème
-- À exécuter UNE SEULE FOIS lors de l'initialisation de la plateforme
-- ============================================================================

DO $$ 
DECLARE
    v_internal_domain_id UUID;
    v_external_domain_id UUID;
BEGIN
    RAISE NOTICE '🌍 Création de la structure universelle de l''écosystème';

    -- ========================================================================
    -- 1. DOMAINES UNIVERSELS
    -- ========================================================================
    
    -- DOMAINE INTERNE
    INSERT INTO ecosystem_entity (
        id,
        tenant_id,
        client_organization_id,
        name,
        stakeholder_type,
        entity_category,
        is_domain,
        is_base_template,
        hierarchy_level,
        parent_entity_id,
        status,
        is_active,
        country_code,
        created_at,
        updated_at
    ) VALUES (
        gen_random_uuid(),
        NULL,               -- Universel
        NULL,               -- Universel
        'Interne',
        'internal',
        'domain',
        TRUE,               -- C'est un domaine
        TRUE,               -- Template universel
        1,
        NULL,               -- Pas de parent
        'active',
        TRUE,
        'FR',
        NOW(),
        NOW()
    ) RETURNING id INTO v_internal_domain_id;

    RAISE NOTICE '✅ Domaine INTERNE créé : %', v_internal_domain_id;

    -- DOMAINE EXTERNE
    INSERT INTO ecosystem_entity (
        id,
        tenant_id,
        client_organization_id,
        name,
        stakeholder_type,
        entity_category,
        is_domain,
        is_base_template,
        hierarchy_level,
        parent_entity_id,
        status,
        is_active,
        country_code,
        created_at,
        updated_at
    ) VALUES (
        gen_random_uuid(),
        NULL,
        NULL,
        'Externe',
        'external',
        'domain',
        TRUE,
        TRUE,
        1,
        NULL,
        'active',
        TRUE,
        'FR',
        NOW(),
        NOW()
    ) RETURNING id INTO v_external_domain_id;

    RAISE NOTICE '✅ Domaine EXTERNE créé : %', v_external_domain_id;

    -- ========================================================================
    -- 2. CATÉGORIES INTERNES UNIVERSELLES
    -- ========================================================================
    
    INSERT INTO ecosystem_entity (
        id,
        tenant_id,
        client_organization_id,
        name,
        stakeholder_type,
        entity_category,
        is_domain,
        is_base_template,
        parent_entity_id,
        hierarchy_level,
        status,
        is_active,
        country_code,
        created_at,
        updated_at
    ) VALUES 
    (
        gen_random_uuid(),
        NULL,
        NULL,
        'Pôle IT',
        'internal',
        'pole',
        FALSE,              -- Pas un domaine
        TRUE,               -- Template universel
        v_internal_domain_id,
        2,
        'active',
        TRUE,
        'FR',
        NOW(),
        NOW()
    ),
    (
        gen_random_uuid(),
        NULL,
        NULL,
        'Pôle RH',
        'internal',
        'pole',
        FALSE,
        TRUE,
        v_internal_domain_id,
        2,
        'active',
        TRUE,
        'FR',
        NOW(),
        NOW()
    ),
    (
        gen_random_uuid(),
        NULL,
        NULL,
        'Pôle Finance',
        'internal',
        'pole',
        FALSE,
        TRUE,
        v_internal_domain_id,
        2,
        'active',
        TRUE,
        'FR',
        NOW(),
        NOW()
    );

    RAISE NOTICE '✅ Catégories INTERNES créées : Pôle IT, RH, Finance';

    -- ========================================================================
    -- 3. CATÉGORIES EXTERNES UNIVERSELLES
    -- ========================================================================
    
    INSERT INTO ecosystem_entity (
        id,
        tenant_id,
        client_organization_id,
        name,
        stakeholder_type,
        entity_category,
        is_domain,
        is_base_template,
        parent_entity_id,
        hierarchy_level,
        status,
        is_active,
        country_code,
        created_at,
        updated_at
    ) VALUES 
    (
        gen_random_uuid(),
        NULL,
        NULL,
        'Clients',
        'external',
        'clients',
        FALSE,
        TRUE,
        v_external_domain_id,
        2,
        'active',
        TRUE,
        'FR',
        NOW(),
        NOW()
    ),
    (
        gen_random_uuid(),
        NULL,
        NULL,
        'Fournisseurs',
        'external',
        'fournisseurs',
        FALSE,
        TRUE,
        v_external_domain_id,
        2,
        'active',
        TRUE,
        'FR',
        NOW(),
        NOW()
    );

    RAISE NOTICE '✅ Catégories EXTERNES créées : Clients, Fournisseurs';
    
    RAISE NOTICE '🎉 Structure universelle initialisée avec succès !';
    RAISE NOTICE '📊 Résumé :';
    RAISE NOTICE '   • 2 domaines (Interne, Externe)';
    RAISE NOTICE '   • 5 catégories de base';
    RAISE NOTICE '   • Toutes les entités avec tenant_id = NULL (universelles)';

END $$;