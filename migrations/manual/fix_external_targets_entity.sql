-- Migration : Associer les cibles externes (external_target) à des entités
-- Date: 2024-12-03
-- Description: Les cibles créées avant l'ajout du champ entity_id n'ont pas d'entité associée.
--              Ce script permet de les associer manuellement.

-- ============================================================================
-- ÉTAPE 1: Vérifier l'état actuel
-- ============================================================================

-- Voir toutes les cibles sans entité associée
SELECT id, value, label, entity_id FROM external_target WHERE entity_id IS NULL ORDER BY value;

-- Voir les entités disponibles
SELECT id, name, short_name FROM ecosystem_entity WHERE is_active = true ORDER BY name;

-- ============================================================================
-- ÉTAPE 2: Créer les entités manquantes (si nécessaire)
-- ============================================================================

-- Récupérer le tenant_id depuis une cible existante
-- SET @tenant_id = (SELECT tenant_id FROM external_target LIMIT 1);

-- Créer les entités pour chaque domaine
-- IMPORTANT: Exécuter ces commandes UNE PAR UNE et adapter selon vos besoins

-- Exemple pour créer l'entité "MakeItSafe"
/*
INSERT INTO ecosystem_entity (id, tenant_id, name, short_name, stakeholder_type, is_active, created_at, updated_at)
SELECT
    gen_random_uuid(),
    (SELECT tenant_id FROM external_target LIMIT 1),
    'MakeItSafe',
    'MIS',
    'CLIENT',
    true,
    NOW(),
    NOW()
WHERE NOT EXISTS (SELECT 1 FROM ecosystem_entity WHERE name = 'MakeItSafe');
*/

-- ============================================================================
-- ÉTAPE 3: Associer les cibles aux entités
-- ============================================================================

-- Association manuelle - Remplacer les IDs par les vrais
-- Exemple: Associer makeitsafe.fr à l'entité MakeItSafe

/*
UPDATE external_target
SET entity_id = (SELECT id FROM ecosystem_entity WHERE name = 'MakeItSafe' LIMIT 1)
WHERE value LIKE '%makeitsafe%' AND entity_id IS NULL;

UPDATE external_target
SET entity_id = (SELECT id FROM ecosystem_entity WHERE name = 'Cybergard' LIMIT 1)
WHERE value LIKE '%cybergard%' AND entity_id IS NULL;
*/

-- ============================================================================
-- ÉTAPE 3: Propager entity_id aux scans existants
-- ============================================================================

-- Après avoir mis à jour les targets, copier l'entity_id vers les scans
-- qui n'en ont pas encore

UPDATE external_scan es
SET entity_id = et.entity_id
FROM external_target et
WHERE es.external_target_id = et.id
  AND es.entity_id IS NULL
  AND et.entity_id IS NOT NULL;

-- ============================================================================
-- ÉTAPE 4: Vérifier le résultat
-- ============================================================================

-- Vérifier que les associations sont correctes
SELECT
    es.id as scan_id,
    et.value as target_value,
    es.entity_id as scan_entity_id,
    et.entity_id as target_entity_id,
    ee.name as entity_name
FROM external_scan es
LEFT JOIN external_target et ON es.external_target_id = et.id
LEFT JOIN ecosystem_entity ee ON COALESCE(es.entity_id, et.entity_id) = ee.id
WHERE es.tenant_id = (SELECT tenant_id FROM external_target LIMIT 1)
ORDER BY es.created_at DESC
LIMIT 20;

-- Compter les scans avec/sans entité
SELECT
    CASE
        WHEN COALESCE(es.entity_id, et.entity_id) IS NULL THEN 'Interne (pas d''entité)'
        ELSE 'Externe (entité associée)'
    END as type_scan,
    COUNT(*) as count
FROM external_scan es
LEFT JOIN external_target et ON es.external_target_id = et.id
GROUP BY 1;
