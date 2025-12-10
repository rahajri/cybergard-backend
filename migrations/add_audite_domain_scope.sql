-- Migration: Ajout du système de périmètre de domaines pour les audités responsables
-- Date: 2025-11-12
-- Description: Permet de définir quels domaines du questionnaire chaque audité peut voir/remplir

-- Table pour stocker le périmètre de domaines assigné à chaque audité dans une campagne
CREATE TABLE IF NOT EXISTS audite_domain_scope (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id UUID NOT NULL,
    entity_member_id UUID NOT NULL,
    -- Array de domain IDs (ex: ['D1', 'D1.1', 'D2'])
    -- NULL ou [] signifie "aucun domaine"
    domain_ids TEXT[] DEFAULT '{}',
    -- Si TRUE, l'audité a accès à TOUS les domaines (ignore domain_ids)
    all_domains BOOLEAN DEFAULT false,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),

    -- Contrainte: un seul périmètre par audité par campagne
    UNIQUE(campaign_id, entity_member_id),

    -- Foreign keys
    FOREIGN KEY (campaign_id) REFERENCES campaign(id) ON DELETE CASCADE
    -- Note: entity_member n'a pas de FK car c'est une table sans PK définie
);

-- Index pour optimiser les requêtes
CREATE INDEX IF NOT EXISTS idx_audite_domain_scope_campaign ON audite_domain_scope(campaign_id);
CREATE INDEX IF NOT EXISTS idx_audite_domain_scope_member ON audite_domain_scope(entity_member_id);

-- Commentaires
COMMENT ON TABLE audite_domain_scope IS 'Définit le périmètre de domaines accessibles pour chaque audité responsable dans une campagne';
COMMENT ON COLUMN audite_domain_scope.domain_ids IS 'Liste des IDs de domaines accessibles (ex: [''D1'', ''D1.1'', ''D2'']). Vide = aucun domaine';
COMMENT ON COLUMN audite_domain_scope.all_domains IS 'Si TRUE, l''audité a accès à tous les domaines du questionnaire';
