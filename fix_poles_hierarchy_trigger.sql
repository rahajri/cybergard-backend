-- Fix poles hierarchy trigger to work with generated UUIDs

-- Fonction trigger améliorée
CREATE OR REPLACE FUNCTION update_pole_hierarchy_path()
RETURNS TRIGGER AS $$
BEGIN
    -- Si pas de parent, c'est un pôle racine
    IF NEW.parent_pole_id IS NULL THEN
        NEW.hierarchy_level := 1;
        -- Le path sera mis à jour après l'insertion via un UPDATE
        NEW.hierarchy_path := NULL;
    ELSE
        -- Récupérer le niveau et le path du parent
        SELECT hierarchy_level + 1, hierarchy_path
        INTO NEW.hierarchy_level, NEW.hierarchy_path
        FROM poles
        WHERE id = NEW.parent_pole_id;

        -- Si le parent n'a pas encore de path, on ne peut pas calculer le nôtre
        IF NEW.hierarchy_path IS NULL THEN
            NEW.hierarchy_path := NULL;
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Créer le trigger BEFORE pour calculer hierarchy_level
CREATE TRIGGER trg_poles_hierarchy_before
BEFORE INSERT OR UPDATE ON poles
FOR EACH ROW
EXECUTE FUNCTION update_pole_hierarchy_path();

-- Fonction pour mettre à jour le hierarchy_path AFTER insert
CREATE OR REPLACE FUNCTION update_pole_hierarchy_path_after()
RETURNS TRIGGER AS $$
BEGIN
    -- Mettre à jour le hierarchy_path après que l'ID soit généré
    IF NEW.parent_pole_id IS NULL THEN
        -- Pôle racine : path = /id
        UPDATE poles
        SET hierarchy_path = '/' || NEW.id::text
        WHERE id = NEW.id AND hierarchy_path IS NULL;
    ELSE
        -- Sous-pôle : path = parent_path/id
        UPDATE poles
        SET hierarchy_path = (
            SELECT hierarchy_path || '/' || NEW.id::text
            FROM poles
            WHERE id = NEW.parent_pole_id
        )
        WHERE id = NEW.id;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Créer le trigger AFTER pour mettre à jour hierarchy_path
CREATE TRIGGER trg_poles_hierarchy_after
AFTER INSERT ON poles
FOR EACH ROW
EXECUTE FUNCTION update_pole_hierarchy_path_after();

-- Mettre à jour les pôles existants qui n'ont pas de hierarchy_path
UPDATE poles
SET hierarchy_path = '/' || id::text
WHERE parent_pole_id IS NULL AND hierarchy_path IS NULL;

-- Mettre à jour les sous-pôles existants
UPDATE poles p
SET hierarchy_path = parent.hierarchy_path || '/' || p.id::text
FROM poles parent
WHERE p.parent_pole_id = parent.id
AND p.hierarchy_path IS NULL;
