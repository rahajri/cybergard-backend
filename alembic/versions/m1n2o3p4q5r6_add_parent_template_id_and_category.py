"""Add parent_template_id and template_category to report_template

Revision ID: m1n2o3p4q5r6
Revises: l1m2n3o4p5q6
Create Date: 2024-12-08

Cette migration ajoute:
- parent_template_id: Lien vers le template maître (pour traçabilité des duplications)
- template_category: Catégorie du template ('audit', 'ebios', 'scan')

Cela permet de:
1. Distinguer les templates d'audit des templates EBIOS
2. Tracer l'origine des templates dupliqués pour les tenants
3. Filtrer correctement les templates selon le contexte
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision = 'm1n2o3p4q5r6'
down_revision = 'l1m2n3o4p5q6'
branch_labels = None
depends_on = None


def upgrade():
    """Ajoute parent_template_id et template_category à report_template."""

    # 1. Ajouter la colonne parent_template_id (auto-référence vers le template maître)
    op.add_column('report_template', sa.Column('parent_template_id', UUID(as_uuid=True), nullable=True))

    # 2. Créer la FK vers report_template (auto-référence)
    op.create_foreign_key(
        'fk_report_template_parent',
        'report_template',
        'report_template',
        ['parent_template_id'],
        ['id'],
        ondelete='SET NULL'
    )

    # 3. Créer un index pour les recherches par parent
    op.create_index('idx_report_template_parent', 'report_template', ['parent_template_id'])

    # 4. Ajouter la colonne template_category
    # Valeurs: 'audit' (campagnes d'audit), 'ebios' (EBIOS RM), 'scan' (scanner externe)
    op.add_column('report_template', sa.Column('template_category', sa.String(50), nullable=True, server_default='audit'))

    # 5. Créer un index pour les recherches par catégorie
    op.create_index('idx_report_template_category', 'report_template', ['template_category'])

    # 6. Mettre à jour les templates existants avec leur catégorie
    # Templates EBIOS (identifiés par leur code ou nom)
    op.execute("""
        UPDATE report_template
        SET template_category = 'ebios'
        WHERE code LIKE '%EBIOS%'
           OR code LIKE '%ebios%'
           OR name ILIKE '%ebios%'
           OR name ILIKE '%risk manager%'
    """)

    # Templates Scanner (identifiés par leur report_scope)
    op.execute("""
        UPDATE report_template
        SET template_category = 'scan'
        WHERE report_scope IN ('scan_individual', 'scan_ecosystem', 'scan_both')
    """)

    # Le reste reste en 'audit' (valeur par défaut)
    op.execute("""
        UPDATE report_template
        SET template_category = 'audit'
        WHERE template_category IS NULL
    """)

    # 7. Tenter de retrouver les relations parent pour les templates existants
    # Basé sur la correspondance de code (si SYSTEM_X existe et X existe pour un tenant)
    # Note: Cette logique peut être affinée selon les conventions de nommage
    op.execute("""
        UPDATE report_template child
        SET parent_template_id = parent.id
        FROM report_template parent
        WHERE parent.is_system = true
          AND child.is_system = false
          AND child.parent_template_id IS NULL
          AND (
              -- Correspondance par préfixe de code
              (parent.code IS NOT NULL AND child.code LIKE parent.code || '%')
              OR
              -- Correspondance par nom similaire et même catégorie
              (parent.name IS NOT NULL
               AND child.name ILIKE '%' || parent.name || '%'
               AND parent.template_category = child.template_category
               AND parent.report_scope = child.report_scope)
          )
    """)


def downgrade():
    """Supprime parent_template_id et template_category."""

    # 1. Supprimer l'index sur category
    op.drop_index('idx_report_template_category', table_name='report_template')

    # 2. Supprimer la colonne template_category
    op.drop_column('report_template', 'template_category')

    # 3. Supprimer l'index sur parent
    op.drop_index('idx_report_template_parent', table_name='report_template')

    # 4. Supprimer la FK
    op.drop_constraint('fk_report_template_parent', 'report_template', type_='foreignkey')

    # 5. Supprimer la colonne parent_template_id
    op.drop_column('report_template', 'parent_template_id')
