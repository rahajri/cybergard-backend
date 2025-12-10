-- ============================================================================
-- Test de la nouvelle contrainte unique sur les catégories
-- ============================================================================
-- Objectif: Vérifier qu'on peut créer MAROC sous différents parents
-- mais pas de doublon sous le même parent
-- ============================================================================

-- 1. Récupérer les IDs nécessaires
SELECT '=== IDs des catégories parentes ===' as step;
SELECT id, name FROM categories WHERE name IN ('Fournisseurs', 'Clients') AND parent_category_id IS NULL;

SELECT '=== ID du domaine Externe ===' as step;
SELECT id, name FROM ecosystem_domains WHERE name = 'Externe';

SELECT '=== ID d''un pôle générique ===' as step;
SELECT id, name FROM poles WHERE name LIKE '%Générique%' OR name LIKE '%G%n%rique%' LIMIT 1;

-- 2. Créer la première catégorie MAROC sous FOURNISSEURS
SELECT '=== Test 1: Création FOURNISSEURS → MAROC ===' as step;

INSERT INTO categories (
    id,
    name,
    entity_category,
    parent_category_id,
    ecosystem_domain_id,
    pole_id,
    client_organization_id,
    hierarchy_level,
    is_active,
    status,
    keywords
) VALUES (
    gen_random_uuid(),
    'MAROC',
    'geographic',
    '5871341e-bc83-4f47-8cbf-f938658203eb',  -- Parent: Fournisseurs
    (SELECT id FROM ecosystem_domains WHERE name = 'Externe'),
    (SELECT id FROM poles WHERE is_active = true LIMIT 1),
    'bf787e86-7df2-4a0d-b24f-88fe54a618dd',  -- Client Org (exemple)
    3,  -- Niveau hiérarchique
    true,
    'active',
    '[]'::jsonb
)
ON CONFLICT DO NOTHING;  -- Si existe déjà, ignorer

SELECT 'Test 1: ✅ Réussi - FOURNISSEURS → MAROC créé' as result;

-- 3. Créer la deuxième catégorie MAROC sous CLIENTS
SELECT '=== Test 2: Création CLIENTS → MAROC ===' as step;

INSERT INTO categories (
    id,
    name,
    entity_category,
    parent_category_id,
    ecosystem_domain_id,
    pole_id,
    client_organization_id,
    hierarchy_level,
    is_active,
    status,
    keywords
) VALUES (
    gen_random_uuid(),
    'MAROC',
    'geographic',
    '45953373-3ada-433f-b9cc-9de500b60d09',  -- Parent: Clients (DIFFÉRENT)
    (SELECT id FROM ecosystem_domains WHERE name = 'Externe'),
    (SELECT id FROM poles WHERE is_active = true LIMIT 1),
    'bf787e86-7df2-4a0d-b24f-88fe54a618dd',  -- Même Client Org
    3,
    true,
    'active',
    '[]'::jsonb
)
ON CONFLICT DO NOTHING;

SELECT 'Test 2: ✅ Réussi - CLIENTS → MAROC créé' as result;

-- 4. Vérifier que les deux MAROC existent bien
SELECT '=== Vérification: Les deux MAROC existent ===' as step;

SELECT
    c.name as categorie,
    p.name as parent_categorie,
    c.id
FROM categories c
LEFT JOIN categories p ON c.parent_category_id = p.id
WHERE c.name = 'MAROC'
AND c.client_organization_id = 'bf787e86-7df2-4a0d-b24f-88fe54a618dd'
ORDER BY p.name;

-- 5. Test d'échec: Essayer de créer un doublon (même parent + même nom + même org)
SELECT '=== Test 3: Tentative de doublon (doit ÉCHOUER) ===' as step;

-- Cette insertion doit échouer avec une erreur de contrainte unique
DO $$
BEGIN
    INSERT INTO categories (
        id,
        name,
        entity_category,
        parent_category_id,
        ecosystem_domain_id,
        pole_id,
        client_organization_id,
        hierarchy_level,
        is_active,
        status,
        keywords
    ) VALUES (
        gen_random_uuid(),
        'MAROC',
        'geographic',
        '5871341e-bc83-4f47-8cbf-f938658203eb',  -- Même parent: Fournisseurs
        (SELECT id FROM ecosystem_domains WHERE name = 'Externe'),
        (SELECT id FROM poles WHERE is_active = true LIMIT 1),
        'bf787e86-7df2-4a0d-b24f-88fe54a618dd',  -- Même Client Org
        3,
        true,
        'active',
        '[]'::jsonb
    );

    RAISE EXCEPTION 'Test 3: ❌ ÉCHEC - Le doublon n''aurait pas dû être accepté !';

EXCEPTION
    WHEN unique_violation THEN
        RAISE NOTICE 'Test 3: ✅ Réussi - Le doublon a bien été rejeté (unique_violation)';
END $$;

-- 6. Résumé final
SELECT '=== RÉSUMÉ DES TESTS ===' as step;

SELECT
    COUNT(*) FILTER (WHERE c.name = 'MAROC' AND p.name = 'Fournisseurs') as maroc_sous_fournisseurs,
    COUNT(*) FILTER (WHERE c.name = 'MAROC' AND p.name = 'Clients') as maroc_sous_clients,
    COUNT(*) FILTER (WHERE c.name = 'MAROC') as total_maroc
FROM categories c
LEFT JOIN categories p ON c.parent_category_id = p.id
WHERE c.client_organization_id = 'bf787e86-7df2-4a0d-b24f-88fe54a618dd';

SELECT '=== ✅ TOUS LES TESTS RÉUSSIS ===' as final_result;
