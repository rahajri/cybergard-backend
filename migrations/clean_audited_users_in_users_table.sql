-- Migration: Nettoyer les utilisateurs audités dans la table users
-- Date: 2025-11-10
-- Description: Les utilisateurs audités (AUDITE_RESP, AUDITE_CONTRIB) ne doivent avoir
--              qu'un enregistrement minimal dans 'users' (pour FK) sans password ni token.
--              Leur profil complet est dans 'entity_member'.

-- 1. Nettoyer les password_hash des utilisateurs audités (ils accèdent via magic links)
UPDATE users
SET password_hash = ''
WHERE tenant_id IS NULL
AND id IN (
    SELECT DISTINCT user_id
    FROM entity_member
    WHERE roles @> '["audite_resp"]'::jsonb
       OR roles @> '["audite_contrib"]'::jsonb
);

-- 2. Supprimer les tokens d'activation des utilisateurs audités (pas nécessaires)
DELETE FROM activation_tokens
WHERE user_id IN (
    SELECT DISTINCT em.user_id
    FROM entity_member em
    WHERE em.roles @> '["audite_resp"]'::jsonb
       OR em.roles @> '["audite_contrib"]'::jsonb
);

-- Vérification
SELECT
    u.id,
    u.email,
    u.first_name,
    u.last_name,
    u.tenant_id,
    u.password_hash = '' as no_password,
    em.roles,
    e.name as entity_name
FROM users u
LEFT JOIN entity_member em ON u.id = em.user_id
LEFT JOIN ecosystem_entity e ON em.entity_id = e.id
WHERE u.tenant_id IS NULL
AND em.roles IS NOT NULL
ORDER BY u.created_at DESC;
