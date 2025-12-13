"""Add EBIOS RM ANSSI reference tables

Revision ID: o1p2q3r4s5t6
Revises: n1o2p3q4r5s6
Create Date: 2024-12-10

Tables de reference ANSSI pour la methode EBIOS Risk Manager :
- ref_ebios_sr : Sources de risque types (11 entrees)
- ref_ebios_bs : Biens supports types (18 entrees)
- ref_ebios_vm : Valeurs metier types (15 entrees)
- ref_ebios_er : Evenements redoutes types (18 entrees)
- ref_ebios_ov : Objectifs vises types (8 entrees)
- ref_ebios_guides : Extraits guides ANSSI
- ai_generation_logs : Journalisation des appels IA
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'o1p2q3r4s5t6'
down_revision = 'i1j2k3l4m5n6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ===========================================================================
    # TABLE: ref_ebios_sr
    # Sources de Risque types ANSSI (11 categories)
    # ===========================================================================
    op.create_table(
        'ref_ebios_sr',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('label', sa.String(255), nullable=False),
        sa.Column('categorie', sa.String(50), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('motivations', postgresql.JSONB(), nullable=True, server_default='[]'),
        sa.Column('ressources', sa.String(50), nullable=True),
        sa.Column('sophistication', sa.String(50), nullable=True),
        sa.Column('tags', postgresql.JSONB(), nullable=True, server_default='[]'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=True, onupdate=sa.func.now()),
    )

    op.create_index('ix_ref_ebios_sr_categorie', 'ref_ebios_sr', ['categorie'])

    # Commentaires sur la table
    op.execute("COMMENT ON TABLE ref_ebios_sr IS 'Referentiel des sources de risque types EBIOS RM (ANSSI)'")
    op.execute("COMMENT ON COLUMN ref_ebios_sr.categorie IS 'Categorie ANSSI: ETATIQUE, CYBERCRIMINELS, TERRORISTE, ACTIVISTE, CONCURRENT, OFFICINE, AMATEUR, VENGEUR, MALVEILLANT, FOURNISSEUR, INTERNE'")
    op.execute("COMMENT ON COLUMN ref_ebios_sr.ressources IS 'Niveau de ressources: FAIBLES, MODEREES, ELEVEES, TRES_ELEVEES, VARIABLES'")
    op.execute("COMMENT ON COLUMN ref_ebios_sr.sophistication IS 'Niveau de sophistication: FAIBLE, MODEREE, ELEVEE, TRES_ELEVEE, VARIABLE'")

    # ===========================================================================
    # TABLE: ref_ebios_bs
    # Biens Supports types ANSSI (18 entrees)
    # ===========================================================================
    op.create_table(
        'ref_ebios_bs',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('label', sa.String(255), nullable=False),
        sa.Column('type', sa.String(50), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('exemples', postgresql.JSONB(), nullable=True, server_default='[]'),
        sa.Column('tags', postgresql.JSONB(), nullable=True, server_default='[]'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=True, onupdate=sa.func.now()),
    )

    op.create_index('ix_ref_ebios_bs_type', 'ref_ebios_bs', ['type'])

    op.execute("COMMENT ON TABLE ref_ebios_bs IS 'Referentiel des biens supports types EBIOS RM (ANSSI)'")
    op.execute("COMMENT ON COLUMN ref_ebios_bs.type IS 'Type de bien: MATERIEL, LOGICIEL, RESEAU, APPLICATION, DONNEES, INFRASTRUCTURE, ORGANISATION, HUMAIN, LOCAUX'")

    # ===========================================================================
    # TABLE: ref_ebios_vm
    # Valeurs Metier types ANSSI (15 entrees)
    # ===========================================================================
    op.create_table(
        'ref_ebios_vm',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('label', sa.String(255), nullable=False),
        sa.Column('nature', sa.String(50), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('exemples', postgresql.JSONB(), nullable=True, server_default='[]'),
        sa.Column('besoins_securite', postgresql.JSONB(), nullable=True, server_default='[]'),
        sa.Column('tags', postgresql.JSONB(), nullable=True, server_default='[]'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=True, onupdate=sa.func.now()),
    )

    op.create_index('ix_ref_ebios_vm_nature', 'ref_ebios_vm', ['nature'])

    op.execute("COMMENT ON TABLE ref_ebios_vm IS 'Referentiel des valeurs metier types EBIOS RM (ANSSI)'")
    op.execute("COMMENT ON COLUMN ref_ebios_vm.nature IS 'Nature de la valeur: PROCESSUS, INFORMATION, SAVOIR_FAIRE'")
    op.execute("COMMENT ON COLUMN ref_ebios_vm.besoins_securite IS 'Besoins de securite: Disponibilite, Integrite, Confidentialite, Tracabilite'")

    # ===========================================================================
    # TABLE: ref_ebios_er
    # Evenements Redoutes types ANSSI (18 entrees)
    # ===========================================================================
    op.create_table(
        'ref_ebios_er',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('label', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('critere_atteint', sa.String(50), nullable=True),
        sa.Column('gravite_default', sa.Integer(), nullable=True),
        sa.Column('impacts_types', postgresql.JSONB(), nullable=True, server_default='[]'),
        sa.Column('tags', postgresql.JSONB(), nullable=True, server_default='[]'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=True, onupdate=sa.func.now()),
    )

    op.create_index('ix_ref_ebios_er_critere', 'ref_ebios_er', ['critere_atteint'])
    op.create_index('ix_ref_ebios_er_gravite', 'ref_ebios_er', ['gravite_default'])

    # Contrainte sur gravite_default (1-4)
    op.create_check_constraint(
        'ck_ref_ebios_er_gravite_range',
        'ref_ebios_er',
        'gravite_default >= 1 AND gravite_default <= 4'
    )

    op.execute("COMMENT ON TABLE ref_ebios_er IS 'Referentiel des evenements redoutes types EBIOS RM (ANSSI)'")
    op.execute("COMMENT ON COLUMN ref_ebios_er.critere_atteint IS 'Critere de securite atteint: DISPONIBILITE, INTEGRITE, CONFIDENTIALITE, TRACABILITE'")
    op.execute("COMMENT ON COLUMN ref_ebios_er.gravite_default IS 'Gravite par defaut (1=Mineure, 2=Significative, 3=Grave, 4=Critique)'")

    # ===========================================================================
    # TABLE: ref_ebios_ov
    # Objectifs Vises types ANSSI (8 entrees)
    # ===========================================================================
    op.create_table(
        'ref_ebios_ov',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('label', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('finalites', postgresql.JSONB(), nullable=True, server_default='[]'),
        sa.Column('secteurs_cibles', postgresql.JSONB(), nullable=True, server_default='[]'),
        sa.Column('sources_typiques', postgresql.JSONB(), nullable=True, server_default='[]'),
        sa.Column('tags', postgresql.JSONB(), nullable=True, server_default='[]'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=True, onupdate=sa.func.now()),
    )

    op.execute("COMMENT ON TABLE ref_ebios_ov IS 'Referentiel des objectifs vises types EBIOS RM (ANSSI)'")

    # ===========================================================================
    # TABLE: ref_ebios_guides
    # Extraits des guides ANSSI pour enrichir les prompts IA
    # ===========================================================================
    op.create_table(
        'ref_ebios_guides',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('atelier', sa.String(10), nullable=False),
        sa.Column('titre', sa.String(255), nullable=True),
        sa.Column('extrait', sa.Text(), nullable=False),
        sa.Column('reference_pdf', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=True, onupdate=sa.func.now()),
    )

    op.create_index('ix_ref_ebios_guides_atelier', 'ref_ebios_guides', ['atelier'])

    op.execute("COMMENT ON TABLE ref_ebios_guides IS 'Extraits des guides ANSSI pour enrichir les prompts IA'")
    op.execute("COMMENT ON COLUMN ref_ebios_guides.atelier IS 'Atelier concerne: AT1, AT2, AT3, AT4, AT5, COMMUN'")

    # ===========================================================================
    # TABLE: ai_generation_logs
    # Journalisation des appels IA pour les ateliers EBIOS
    # ===========================================================================
    op.create_table(
        'ai_generation_logs',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('project_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('risk_project.id', ondelete='CASCADE'), nullable=True),
        sa.Column('atelier', sa.String(10), nullable=False),
        sa.Column('input', sa.Text(), nullable=True),
        sa.Column('output', sa.Text(), nullable=True),
        sa.Column('model', sa.String(100), nullable=True),
        sa.Column('tokens_used', sa.Integer(), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='success'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    op.create_index('ix_ai_generation_logs_project', 'ai_generation_logs', ['project_id'])
    op.create_index('ix_ai_generation_logs_atelier', 'ai_generation_logs', ['atelier'])
    op.create_index('ix_ai_generation_logs_created', 'ai_generation_logs', ['created_at'])
    op.create_index('ix_ai_generation_logs_status', 'ai_generation_logs', ['status'])

    op.execute("COMMENT ON TABLE ai_generation_logs IS 'Journalisation des appels IA pour les ateliers EBIOS'")
    op.execute("COMMENT ON COLUMN ai_generation_logs.atelier IS 'Atelier: AT1, AT2, AT3, AT4, AT5, AT6'")
    op.execute("COMMENT ON COLUMN ai_generation_logs.status IS 'Statut: success, error, timeout'")


def downgrade() -> None:
    # Supprimer les tables dans l'ordre inverse
    op.drop_table('ai_generation_logs')
    op.drop_table('ref_ebios_guides')
    op.drop_table('ref_ebios_ov')
    op.drop_table('ref_ebios_er')
    op.drop_table('ref_ebios_vm')
    op.drop_table('ref_ebios_bs')
    op.drop_table('ref_ebios_sr')
