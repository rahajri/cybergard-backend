-- Migration: Rendre user_id nullable dans entity_member
-- Date: 2025-11-10
-- Description: Les CONTACTS (audités) sont dans entity_member UNIQUEMENT, pas dans users
--              Seuls les UTILISATEURS (employés du client) sont dans users
--              user_id doit être nullable pour supporter les contacts externes

-- 1. Rendre la colonne user_id nullable
ALTER TABLE entity_member
ALTER COLUMN user_id DROP NOT NULL;

-- 2. Vérification de la structure
\d entity_member

-- 3. Afficher les membres existants
SELECT
    em.id,
    em.user_id,
    em.email,
    em.first_name,
    em.last_name,
    em.roles,
    e.name as entity_name
FROM entity_member em
LEFT JOIN ecosystem_entity e ON em.entity_id = e.id
WHERE em.is_active = true
ORDER BY em.created_at DESC;
