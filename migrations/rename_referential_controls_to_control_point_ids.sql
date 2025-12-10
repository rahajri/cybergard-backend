-- Migration: Renommer referential_controls → control_point_ids
-- Date: 2025-01-23
-- Description: Clarifier le nom du champ pour refléter qu'il contient des IDs de control points

-- Étape 1: Renommer la colonne
ALTER TABLE action_plan_item
RENAME COLUMN referential_controls TO control_point_ids;

-- Étape 2: Ajouter un commentaire pour documenter le champ
COMMENT ON COLUMN action_plan_item.control_point_ids IS
'Array des IDs de control points (UUID[]) associés à cette action, déduits des questions sources via la table question_control_point';

-- Vérification
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'action_plan_item'
  AND column_name = 'control_point_ids';
