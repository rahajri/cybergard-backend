-- Migration: Supprimer les contacts (audités) de la table users
-- Date: 2025-11-10
-- Description: Les CONTACTS sont maintenant UNIQUEMENT dans entity_member
--              Ils ne doivent PAS être dans users
--              Cette migration nettoie les contacts qui ont été créés avant ce changement

-- 1. Lister les contacts à supprimer (pour vérification)
SELECT
    u.id,
    u.email,
    u.first_name,
    u.last_name,
    u.tenant_id,
    em.roles,
    e.name as entity_name
FROM users u
LEFT JOIN entity_member em ON u.id = em.user_id
LEFT JOIN ecosystem_entity e ON em.entity_id = e.id
WHERE u.tenant_id IS NULL
AND em.user_id IS NOT NULL
AND (em.roles @> '["audite_resp"]'::jsonb OR em.roles @> '["audite_contrib"]'::jsonb);

-- 2. Mettre à jour entity_member : user_id = NULL pour les contacts
UPDATE entity_member
SET user_id = NULL
WHERE user_id IN (
    SELECT u.id
    FROM users u
    INNER JOIN entity_member em ON u.id = em.user_id
    WHERE u.tenant_id IS NULL
    AND (em.roles @> '["audite_resp"]'::jsonb OR em.roles @> '["audite_contrib"]'::jsonb)
);

-- 3. Supprimer les contacts de la table users
DELETE FROM users
WHERE tenant_id IS NULL
AND id IN (
    SELECT DISTINCT user_id
    FROM entity_member
    WHERE user_id IS NOT NULL
    AND (roles @> '["audite_resp"]'::jsonb OR roles @> '["audite_contrib"]'::jsonb)
);

-- 4. Vérification finale : contacts dans entity_member avec user_id=NULL
SELECT
    em.id,
    em.user_id as should_be_null,
    em.email,
    em.first_name,
    em.last_name,
    em.roles,
    e.name as entity_name
FROM entity_member em
LEFT JOIN ecosystem_entity e ON em.entity_id = e.id
WHERE em.is_active = true
AND (em.roles @> '["audite_resp"]'::jsonb OR em.roles @> '["audite_contrib"]'::jsonb)
ORDER BY em.created_at DESC;
