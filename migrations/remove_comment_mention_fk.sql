-- Migration: Supprimer la contrainte FK sur comment_mention.mentioned_user_id
-- pour permettre les mentions vers entity_member ET users (auditeurs)

-- Étape 1: Trouver le nom de la contrainte
DO $$
DECLARE
    constraint_name TEXT;
BEGIN
    -- Récupérer le nom de la contrainte FK
    SELECT tc.constraint_name INTO constraint_name
    FROM information_schema.table_constraints AS tc
    JOIN information_schema.key_column_usage AS kcu
      ON tc.constraint_name = kcu.constraint_name
      AND tc.table_schema = kcu.table_schema
    WHERE tc.constraint_type = 'FOREIGN KEY'
      AND tc.table_name = 'comment_mention'
      AND kcu.column_name = 'mentioned_user_id'
      AND tc.table_schema = 'public';

    -- Supprimer la contrainte si elle existe
    IF constraint_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE comment_mention DROP CONSTRAINT %I', constraint_name);
        RAISE NOTICE 'Contrainte FK % supprimée avec succès', constraint_name;
    ELSE
        RAISE NOTICE 'Aucune contrainte FK trouvée sur mentioned_user_id';
    END IF;
END $$;

-- Vérification finale
SELECT
    tc.constraint_name,
    tc.table_name,
    kcu.column_name,
    ccu.table_name AS foreign_table_name,
    ccu.column_name AS foreign_column_name
FROM information_schema.table_constraints AS tc
JOIN information_schema.key_column_usage AS kcu
  ON tc.constraint_name = kcu.constraint_name
  AND tc.table_schema = kcu.table_schema
JOIN information_schema.constraint_column_usage AS ccu
  ON ccu.constraint_name = tc.constraint_name
  AND ccu.table_schema = tc.table_schema
WHERE tc.constraint_type = 'FOREIGN KEY'
  AND tc.table_name = 'comment_mention'
  AND tc.table_schema = 'public';
