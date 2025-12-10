-- Migration: Nettoyer entity_member des utilisateurs internes
-- Date: 2025-11-10
-- Description: Supprime de entity_member les utilisateurs qui appartiennent au tenant
--              (ce sont des membres internes, pas des audités externes)

-- Afficher les utilisateurs qui vont être supprimés (pour vérification)
SELECT
    u.email,
    u.tenant_id,
    em.entity_id,
    em.roles,
    'SERA SUPPRIME' as action
FROM users u
INNER JOIN entity_member em ON u.id = em.user_id
WHERE u.tenant_id IS NOT NULL
  AND NOT (em.roles::jsonb ? 'audite_resp' OR em.roles::jsonb ? 'audite_contrib');

-- Supprimer les membres internes de entity_member
-- entity_member doit contenir UNIQUEMENT les employés des organismes audités
DELETE FROM entity_member em
USING users u
WHERE em.user_id = u.id
  AND u.tenant_id IS NOT NULL
  AND NOT (em.roles::jsonb ? 'audite_resp' OR em.roles::jsonb ? 'audite_contrib');

-- Vérification finale : afficher tous les membres restants dans entity_member
SELECT
    em.id,
    u.email,
    u.tenant_id IS NOT NULL as has_tenant,
    em.roles,
    ee.name as entity_name
FROM entity_member em
JOIN users u ON em.user_id = u.id
JOIN ecosystem_entity ee ON em.entity_id = ee.id
ORDER BY u.email;
