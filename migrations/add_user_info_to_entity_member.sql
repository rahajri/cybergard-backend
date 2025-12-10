-- Migration: Ajouter les informations utilisateur à la table entity_member
-- Date: 2025-11-10
-- Description: Ajoute email, first_name, last_name à entity_member pour éviter les jointures

-- Ajouter les nouvelles colonnes
ALTER TABLE entity_member
ADD COLUMN IF NOT EXISTS email TEXT,
ADD COLUMN IF NOT EXISTS first_name TEXT,
ADD COLUMN IF NOT EXISTS last_name TEXT;

-- Remplir les colonnes avec les données existantes depuis la table users
UPDATE entity_member em
SET
    email = u.email,
    first_name = u.first_name,
    last_name = u.last_name
FROM users u
WHERE em.user_id = u.id;

-- Créer un index sur l'email pour les recherches
CREATE INDEX IF NOT EXISTS idx_entity_member_email ON entity_member(email);

-- Commenter les nouvelles colonnes
COMMENT ON COLUMN entity_member.email IS 'Email de l''utilisateur (dénormalisé depuis users)';
COMMENT ON COLUMN entity_member.first_name IS 'Prénom de l''utilisateur (dénormalisé depuis users)';
COMMENT ON COLUMN entity_member.last_name IS 'Nom de l''utilisateur (dénormalisé depuis users)';
