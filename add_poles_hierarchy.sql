-- Migration: Ajouter le support de la hiérarchie pour les pôles
-- Date: 2025-11-13

-- Ajouter les colonnes de hiérarchie à la table poles
ALTER TABLE poles
ADD COLUMN IF NOT EXISTS parent_pole_id UUID REFERENCES poles(id) ON DELETE SET NULL,
ADD COLUMN IF NOT EXISTS hierarchy_level INTEGER DEFAULT 1,
ADD COLUMN IF NOT EXISTS hierarchy_path TEXT;

-- Index pour améliorer les performances des requêtes hiérarchiques
CREATE INDEX IF NOT EXISTS idx_poles_parent_pole_id ON poles(parent_pole_id);
CREATE INDEX IF NOT EXISTS idx_poles_hierarchy_level ON poles(hierarchy_level);

-- Mettre à jour les pôles existants avec hierarchy_level = 1 (niveau racine)
UPDATE poles
SET hierarchy_level = 1,
    hierarchy_path = '/' || id::text
WHERE parent_pole_id IS NULL AND hierarchy_level IS NULL;

-- Fonction trigger pour calculer automatiquement hierarchy_level et hierarchy_path
CREATE OR REPLACE FUNCTION update_pole_hierarchy_path()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.parent_pole_id IS NULL THEN
        NEW.hierarchy_level := 1;
        NEW.hierarchy_path := '/' || NEW.id::text;
    ELSE
        SELECT hierarchy_level + 1, hierarchy_path || '/' || NEW.id::text
        INTO NEW.hierarchy_level, NEW.hierarchy_path
        FROM poles WHERE id = NEW.parent_pole_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Créer le trigger
DROP TRIGGER IF EXISTS trg_poles_hierarchy ON poles;
CREATE TRIGGER trg_poles_hierarchy
BEFORE INSERT OR UPDATE ON poles
FOR EACH ROW
EXECUTE FUNCTION update_pole_hierarchy_path();

-- Commentaires
COMMENT ON COLUMN poles.parent_pole_id IS 'ID du pôle parent (NULL pour les pôles racine)';
COMMENT ON COLUMN poles.hierarchy_level IS 'Niveau hiérarchique (1 = racine, 2 = sous-pôle, etc.)';
COMMENT ON COLUMN poles.hierarchy_path IS 'Chemin hiérarchique complet (/uuid1/uuid2/uuid3)';
COMMENT ON FUNCTION update_pole_hierarchy_path() IS 'Calcule automatiquement hierarchy_level et hierarchy_path pour les pôles';
