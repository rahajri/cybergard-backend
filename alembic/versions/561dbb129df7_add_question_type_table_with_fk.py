"""add_question_type_table_with_fk

Revision ID: 561dbb129df7
Revises: b6b0ed51a6cf
Create Date: 2025-11-08 18:55:46.484666

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '561dbb129df7'
down_revision: Union[str, None] = 'b6b0ed51a6cf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Crée la table question_type et ajoute une contrainte FK sur question.response_type.

    Étapes:
    1. Créer table question_type avec les 7 types standards
    2. Insérer les données de référence
    3. Vérifier que toutes les questions existantes ont un type valide
    4. Ajouter contrainte FK sur question.response_type
    """

    # 1. Créer la table question_type
    op.create_table(
        'question_type',
        sa.Column('code', sa.String(30), primary_key=True, comment='Code technique du type'),
        sa.Column('label', sa.String(100), nullable=False, comment='Libellé affiché'),
        sa.Column('description', sa.Text, nullable=True, comment='Description détaillée du type'),
        sa.Column('icon', sa.String(50), nullable=True, comment='Icône (ex: "check-circle" pour boolean)'),
        sa.Column('has_options', sa.Boolean, default=False, nullable=False, comment='Indique si le type nécessite des options (choix)'),
        sa.Column('display_order', sa.Integer, nullable=False, comment='Ordre d\'affichage dans l\'UI'),
        sa.Column('is_active', sa.Boolean, default=True, nullable=False, comment='Type activé ou désactivé'),
        sa.Column('validation_schema', sa.JSON, nullable=True, comment='Schéma de validation JSON optionnel'),
        sa.Column('created_at', sa.DateTime, server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime, server_default=sa.text('now()'), nullable=False),
    )

    # 2. Insérer les 7 types de questions standards
    op.execute("""
        INSERT INTO question_type (code, label, description, icon, has_options, display_order, is_active, validation_schema) VALUES
        (
            'boolean',
            'Oui/Non (Booléen)',
            'Question binaire avec réponse Oui ou Non. Utilisée pour vérifier l''existence d''un document, processus ou dispositif formel.',
            'check-circle',
            false,
            1,
            true,
            '{"type": "boolean", "requires_comment_if_no": true}'::jsonb
        ),
        (
            'single_choice',
            'Choix unique',
            'Question à choix unique parmi plusieurs options. Type principal (30%) pour évaluer fréquence, niveau de maturité, méthode ou outil utilisé.',
            'list',
            true,
            2,
            true,
            '{"type": "single_choice", "min_options": 2, "max_options": 10, "requires_selection": true}'::jsonb
        ),
        (
            'multiple_choice',
            'Choix multiples',
            'Question permettant la sélection de plusieurs options. Utilisée pour identifier les outils déployés, mesures appliquées, etc.',
            'check-square',
            true,
            3,
            true,
            '{"type": "multiple_choice", "min_options": 2, "max_options": 15, "min_selections": 1, "allow_other": true}'::jsonb
        ),
        (
            'open',
            'Texte libre',
            'Question ouverte nécessitant une réponse textuelle détaillée. Pour description de processus, liste d''outils, explications.',
            'file-text',
            false,
            4,
            true,
            '{"type": "open", "min_length": 10, "max_length": 2000, "multiline": true}'::jsonb
        ),
        (
            'number',
            'Nombre',
            'Question demandant une valeur numérique (délai, compteur, pourcentage). Pour mesurer des métriques quantifiables.',
            'hash',
            false,
            5,
            true,
            '{"type": "number", "min": 0, "max": 999999, "allow_decimals": true, "unit": null}'::jsonb
        ),
        (
            'date',
            'Date',
            'Question demandant une date précise (dernière revue, dernier test, date d''expiration).',
            'calendar',
            false,
            6,
            true,
            '{"type": "date", "format": "YYYY-MM-DD", "allow_future": true}'::jsonb
        ),
        (
            'rating',
            'Échelle de notation',
            'Question avec échelle de notation (ex: 1-5). Pour évaluer le niveau d''implémentation ou de maturité.',
            'star',
            false,
            7,
            true,
            '{"type": "rating", "min": 1, "max": 5, "scale_labels": ["Non implémenté", "Incomplet", "Partiel", "Complet", "Optimisé"]}'::jsonb
        )
    """)

    # 3. Vérifier les données existantes (si la table question contient des données)
    # Normaliser les types invalides vers "open" (fallback sûr)
    op.execute("""
        UPDATE question
        SET response_type = 'open'
        WHERE response_type NOT IN (
            'boolean', 'single_choice', 'multiple_choice',
            'open', 'number', 'date', 'rating'
        )
    """)

    # 4. Ajouter la contrainte FK sur question.response_type
    op.create_foreign_key(
        'fk_question_response_type',  # Nom de la contrainte
        'question',                    # Table source
        'question_type',               # Table cible
        ['response_type'],             # Colonne source
        ['code'],                      # Colonne cible
        ondelete='RESTRICT'            # Empêcher suppression si utilisé
    )

    # 5. Ajouter un index pour performance
    op.create_index(
        'idx_question_response_type',
        'question',
        ['response_type']
    )


def downgrade() -> None:
    """
    Rollback: supprime la contrainte FK et la table question_type.
    """
    # 1. Supprimer l'index
    op.drop_index('idx_question_response_type', table_name='question')

    # 2. Supprimer la contrainte FK
    op.drop_constraint('fk_question_response_type', 'question', type_='foreignkey')

    # 3. Supprimer la table question_type
    op.drop_table('question_type')
