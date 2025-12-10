-- Script pour assigner le rôle SUPER_ADMIN à l'utilisateur admin@cybergard.fr
-- À exécuter dans pgAdmin ou psql

-- 1. Vérifier l'utilisateur Super Admin
SELECT id, email, first_name, last_name, tenant_id, is_active
FROM users
WHERE email = 'admin@cybergard.fr';

-- 2. Vérifier les rôles disponibles
SELECT id, code, name, description
FROM role
WHERE code IN ('SUPER_ADMIN', 'PLATFORM_ADMIN');

-- 3. Vérifier si le Super Admin a déjà un rôle
SELECT u.email, r.code AS role_code, r.name AS role_name, ur.assigned_at
FROM users u
LEFT JOIN user_role ur ON u.id = ur.user_id
LEFT JOIN role r ON ur.role_id = r.id
WHERE u.email = 'admin@cybergard.fr';

-- 4. Assigner le rôle SUPER_ADMIN s'il n'existe pas
INSERT INTO user_role (user_id, role_id, assigned_at)
SELECT u.id, r.id, NOW()
FROM users u, role r
WHERE u.email = 'admin@cybergard.fr'
  AND r.code = 'SUPER_ADMIN'
  AND NOT EXISTS (
    SELECT 1 FROM user_role ur
    WHERE ur.user_id = u.id AND ur.role_id = r.id
  );

-- 5. Vérifier l'assignation
SELECT u.email, r.code AS role_code, r.name AS role_name, ur.assigned_at
FROM users u
JOIN user_role ur ON u.id = ur.user_id
JOIN role r ON ur.role_id = r.id
WHERE u.email = 'admin@cybergard.fr';
