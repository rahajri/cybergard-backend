-- Migration: Ajouter contrainte d'unicité email par tenant
-- Date: 2025-11-13
-- Description: Garantir qu'un email est unique au sein d'un même tenant et d'une même entité

-- ============================================================================
-- PARTIE 1: Table USERS (utilisateurs internes avec tenant_id)
-- ============================================================================

-- Étape 1.1: Vérifier s'il existe des doublons email/tenant dans users
SELECT
    'Vérification doublons dans users' as etape,
    email,
    tenant_id,
    COUNT(*) as count
FROM users
WHERE tenant_id IS NOT NULL
GROUP BY email, tenant_id
HAVING COUNT(*) > 1;

-- Étape 1.2: Supprimer l'ancienne contrainte d'unicité globale sur email
-- (Cette contrainte empêche un même email d'exister pour différents tenants)
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_email_key;

-- Étape 1.3: Créer une contrainte d'unicité composée (email + tenant_id)
-- Cela permet:
-- - Un même email pour différents tenants (OK)
-- - Mais pas le même email deux fois pour le même tenant (INTERDIT)
CREATE UNIQUE INDEX IF NOT EXISTS users_email_tenant_unique
ON users (email, tenant_id)
WHERE tenant_id IS NOT NULL;

-- Étape 1.4: Pour les utilisateurs sans tenant_id (cas rare, normalement dans entity_member),
-- on garde une contrainte d'unicité simple sur l'email
-- Cela garantit qu'un email NULL tenant peut exister une seule fois
CREATE UNIQUE INDEX IF NOT EXISTS users_email_null_tenant_unique
ON users (email)
WHERE tenant_id IS NULL;

-- ============================================================================
-- PARTIE 2: Table ENTITY_MEMBER (contacts externes/audités)
-- ============================================================================

-- Étape 2.1: Vérifier s'il existe des doublons email/entity dans entity_member
SELECT
    'Vérification doublons dans entity_member' as etape,
    email,
    entity_id,
    COUNT(*) as count
FROM entity_member
WHERE email IS NOT NULL
GROUP BY email, entity_id
HAVING COUNT(*) > 1;

-- Étape 2.2: Créer une contrainte d'unicité composée (email + entity_id)
-- Cela garantit qu'un email est unique par entité écosystème
CREATE UNIQUE INDEX IF NOT EXISTS entity_member_email_entity_unique
ON entity_member (email, entity_id)
WHERE email IS NOT NULL;

-- ============================================================================
-- VÉRIFICATION FINALE
-- ============================================================================

-- Vérification des contraintes créées pour users
SELECT
    'users_email_tenant_unique' as constraint_name,
    COUNT(*) as total_users_with_tenant
FROM users
WHERE tenant_id IS NOT NULL
UNION ALL
SELECT
    'users_email_null_tenant_unique' as constraint_name,
    COUNT(*) as total_users_without_tenant
FROM users
WHERE tenant_id IS NULL
UNION ALL
-- Vérification des contraintes créées pour entity_member
SELECT
    'entity_member_email_entity_unique' as constraint_name,
    COUNT(*) as total_contacts_with_email
FROM entity_member
WHERE email IS NOT NULL;

-- Afficher toutes les contraintes d'unicité créées
SELECT
    tablename,
    indexname,
    indexdef
FROM pg_indexes
WHERE indexname IN (
    'users_email_tenant_unique',
    'users_email_null_tenant_unique',
    'entity_member_email_entity_unique'
)
ORDER BY tablename, indexname;
