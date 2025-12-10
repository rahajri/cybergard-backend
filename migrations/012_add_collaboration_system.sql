-- ============================================================================
-- Migration : Système de collaboration avec mentions
-- Description : Ajoute les tables pour gérer les contributeurs et mentions
-- ============================================================================

-- Table pour gérer les contributeurs invités sur un audit
CREATE TABLE IF NOT EXISTS audit_collaborator (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    audit_id UUID NOT NULL REFERENCES audit(id) ON DELETE CASCADE,
    invited_by UUID NOT NULL REFERENCES entity_member(id) ON DELETE CASCADE,
    collaborator_id UUID NOT NULL REFERENCES entity_member(id) ON DELETE CASCADE,
    invited_at TIMESTAMP NOT NULL DEFAULT NOW(),
    is_active BOOLEAN NOT NULL DEFAULT true,
    CONSTRAINT uq_audit_collaborator UNIQUE(audit_id, collaborator_id)
);

CREATE INDEX IF NOT EXISTS idx_audit_collaborator_audit ON audit_collaborator(audit_id);
CREATE INDEX IF NOT EXISTS idx_audit_collaborator_collaborator ON audit_collaborator(collaborator_id);

COMMENT ON TABLE audit_collaborator IS 'Gestion des contributeurs invités sur un audit par un AUDITE_RESP';
COMMENT ON COLUMN audit_collaborator.invited_by IS 'AUDITE_RESP qui a invité le collaborateur';
COMMENT ON COLUMN audit_collaborator.collaborator_id IS 'AUDITE_CONTRIB invité à collaborer sur cet audit';


-- Table pour les commentaires sur les questions avec support des @mentions
CREATE TABLE IF NOT EXISTS question_comment (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    question_id UUID NOT NULL REFERENCES question(id) ON DELETE CASCADE,
    audit_id UUID NOT NULL REFERENCES audit(id) ON DELETE CASCADE,
    author_id UUID NOT NULL REFERENCES entity_member(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    is_deleted BOOLEAN NOT NULL DEFAULT false
);

CREATE INDEX IF NOT EXISTS idx_question_comment_question ON question_comment(question_id);
CREATE INDEX IF NOT EXISTS idx_question_comment_audit ON question_comment(audit_id);
CREATE INDEX IF NOT EXISTS idx_question_comment_author ON question_comment(author_id);

COMMENT ON TABLE question_comment IS 'Commentaires sur les questions avec support des @mentions';
COMMENT ON COLUMN question_comment.content IS 'Contenu du commentaire avec mentions @utilisateur';


-- Table pour tracer les mentions dans les commentaires
CREATE TABLE IF NOT EXISTS comment_mention (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    comment_id UUID NOT NULL REFERENCES question_comment(id) ON DELETE CASCADE,
    mentioned_user_id UUID NOT NULL REFERENCES entity_member(id) ON DELETE CASCADE,
    is_read BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_comment_mention UNIQUE(comment_id, mentioned_user_id)
);

CREATE INDEX IF NOT EXISTS idx_comment_mention_comment ON comment_mention(comment_id);
CREATE INDEX IF NOT EXISTS idx_comment_mention_user ON comment_mention(mentioned_user_id);
CREATE INDEX IF NOT EXISTS idx_comment_mention_unread ON comment_mention(mentioned_user_id, is_read) WHERE is_read = false;

COMMENT ON TABLE comment_mention IS 'Traçabilité des mentions @utilisateur dans les commentaires';
COMMENT ON COLUMN comment_mention.is_read IS 'Indique si utilisateur mentionné a lu le commentaire';
