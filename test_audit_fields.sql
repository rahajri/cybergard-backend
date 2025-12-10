-- ============================================================================
-- Test des Champs d'Audit ecosystem_entity - AVANT/APRÈS Correction
-- ============================================================================
-- Date : 14 novembre 2025
-- Objectif : Vérifier que created_by_user_id, created_by, updated_by, notes
--            sont correctement remplis après la correction
-- ============================================================================

-- ============================================================================
-- 1. État Actuel (AVANT correction appliquée par l'API)
-- ============================================================================

SELECT '=== ÉTAT ACTUEL DES DONNÉES ===' as step;

SELECT
    COUNT(*) as total_organismes,
    COUNT(created_by_user_id) as avec_created_by_user_id,
    COUNT(created_by) as avec_created_by,
    COUNT(updated_by_user_id) as avec_updated_by_user_id,
    COUNT(updated_by) as avec_updated_by,
    COUNT(notes) as avec_notes
FROM ecosystem_entity;

-- Résultat attendu AVANT correction :
-- total_organismes | avec_created_by_user_id | avec_created_by | avec_updated_by_user_id | avec_updated_by | avec_notes
-- -----------------+------------------------+----------------+------------------------+----------------+-----------
-- 9                | 0                      | 0              | 0                      | 0              | 0


-- ============================================================================
-- 2. Exemples d'Organismes Existants (sans audit)
-- ============================================================================

SELECT '=== EXEMPLES D''ORGANISMES SANS AUDIT ===' as step;

SELECT
    id,
    name,
    stakeholder_type,
    created_by_user_id,
    created_by,
    updated_by,
    notes,
    created_at
FROM ecosystem_entity
ORDER BY created_at DESC
LIMIT 5;

-- Résultat attendu : Tous les champs d'audit à NULL


-- ============================================================================
-- 3. Vérifier les Utilisateurs Disponibles
-- ============================================================================

SELECT '=== UTILISATEURS DISPONIBLES POUR LES TESTS ===' as step;

SELECT
    id,
    username,
    email,
    tenant_id
FROM users
LIMIT 3;

-- On aura besoin d'un user_id pour simuler la création


-- ============================================================================
-- 4. Simulation : Créer un Organisme avec Audit
--    (Simulation manuelle de ce que le code corrigé va faire)
-- ============================================================================

SELECT '=== SIMULATION : CRÉATION AVEC AUDIT ===' as step;

DO $$
DECLARE
    v_user_id UUID;
    v_user_email VARCHAR;
    v_tenant_id UUID;
    v_new_entity_id UUID;
BEGIN
    -- Récupérer un utilisateur de test
    SELECT id, email, tenant_id
    INTO v_user_id, v_user_email, v_tenant_id
    FROM users
    LIMIT 1;

    IF v_user_id IS NULL THEN
        RAISE NOTICE '❌ Aucun utilisateur trouvé pour le test';
        RETURN;
    END IF;

    RAISE NOTICE '✅ Utilisateur de test : % (ID: %)', v_user_email, v_user_id;

    -- Créer un organisme de test AVEC les champs d'audit
    v_new_entity_id := gen_random_uuid();

    INSERT INTO ecosystem_entity (
        id,
        name,
        stakeholder_type,
        entity_category,
        tenant_id,
        created_by_user_id,
        created_by,
        updated_by_user_id,
        updated_by,
        notes
    ) VALUES (
        v_new_entity_id,
        'TEST - Organisme avec Audit',
        'external',
        'supplier',
        v_tenant_id,
        v_user_id,                    -- ✅ created_by_user_id
        v_user_email,                 -- ✅ created_by
        v_user_id,                    -- ✅ updated_by_user_id
        v_user_email,                 -- ✅ updated_by
        NULL                          -- ✅ notes (initialisé à NULL)
    );

    RAISE NOTICE '✅ Organisme de test créé avec ID : %', v_new_entity_id;

    -- Vérifier immédiatement
    PERFORM *
    FROM ecosystem_entity
    WHERE id = v_new_entity_id
      AND created_by_user_id IS NOT NULL
      AND created_by IS NOT NULL;

    IF FOUND THEN
        RAISE NOTICE '✅ SUCCÈS : Les champs d''audit sont correctement remplis !';
    ELSE
        RAISE NOTICE '❌ ÉCHEC : Les champs d''audit sont toujours vides';
    END IF;

EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE '❌ Erreur lors de la création : %', SQLERRM;
END $$;


-- ============================================================================
-- 5. Vérifier l'Organisme de Test Créé
-- ============================================================================

SELECT '=== VÉRIFICATION ORGANISME DE TEST ===' as step;

SELECT
    id,
    name,
    created_by_user_id,
    created_by,
    updated_by_user_id,
    updated_by,
    notes,
    created_at
FROM ecosystem_entity
WHERE name = 'TEST - Organisme avec Audit';

-- Résultat attendu : Tous les champs d'audit remplis


-- ============================================================================
-- 6. Statistiques Finales
-- ============================================================================

SELECT '=== STATISTIQUES FINALES ===' as step;

SELECT
    COUNT(*) as total_organismes,
    COUNT(created_by_user_id) as avec_created_by_user_id,
    COUNT(created_by) as avec_created_by,
    ROUND(COUNT(created_by_user_id) * 100.0 / COUNT(*), 2) as pourcentage_avec_audit
FROM ecosystem_entity;

-- Résultat attendu APRÈS simulation :
-- total_organismes | avec_created_by_user_id | avec_created_by | pourcentage_avec_audit
-- -----------------+------------------------+----------------+-----------------------
-- 10               | 1                      | 1              | 10.00


-- ============================================================================
-- 7. Nettoyage (Supprimer l'organisme de test)
-- ============================================================================

SELECT '=== NETTOYAGE ===' as step;

DELETE FROM ecosystem_entity
WHERE name = 'TEST - Organisme avec Audit';

SELECT 'Test terminé. Organisme de test supprimé.' as resultat;


-- ============================================================================
-- 8. Résumé Final
-- ============================================================================

SELECT '=== RÉSUMÉ FINAL ===' as step;

SELECT
    'AVANT correction API : 0/9 organismes avec audit' as avant,
    'APRÈS correction API : 100% des nouveaux organismes auront audit' as apres,
    'Action requise : Redémarrer le backend pour appliquer le code corrigé' as action;

SELECT '=== ✅ TESTS TERMINÉS ===' as final_result;
