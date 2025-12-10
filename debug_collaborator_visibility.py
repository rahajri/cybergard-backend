"""
Debug why contrib1@ac2m.ma doesn't appear in @ mentions
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import create_engine, text

# Database URL
db_url = 'postgresql://postgres:postgres@localhost:5432/audit_platform'

engine = create_engine(db_url)

print('\n' + '=' * 80)
print('DEBUG: VISIBILITY DU CONTRIBUTEUR contrib1@ac2m.ma')
print('=' * 80 + '\n')

with engine.connect() as conn:
    # 1. Get contributor info
    print('[1] INFO CONTRIBUTEUR\n')
    contrib_query = text('''
        SELECT
            em.id,
            em.email,
            em.first_name,
            em.last_name,
            em.entity_id,
            em.roles,
            em.is_active,
            ee.name as entity_name
        FROM entity_member em
        LEFT JOIN ecosystem_entity ee ON em.entity_id = ee.id
        WHERE em.email = 'contrib1@ac2m.ma'
    ''')

    contrib = conn.execute(contrib_query).fetchone()

    if contrib:
        print(f'  ID: {contrib.id}')
        print(f'  Email: {contrib.email}')
        print(f'  Nom: {contrib.first_name} {contrib.last_name}')
        print(f'  Entite ID: {contrib.entity_id}')
        print(f'  Entite Nom: {contrib.entity_name}')
        print(f'  Roles: {contrib.roles}')
        print(f'  Actif: {contrib.is_active}')
        print()

        # 2. Get campaigns where this entity is in scope
        print('[2] CAMPAGNES INCLUANT CETTE ENTITE\n')
        campaigns_query = text('''
            SELECT
                c.id,
                c.title,
                cs.entity_ids
            FROM campaign c
            LEFT JOIN campaign_scope cs ON c.scope_id = cs.id
            WHERE :entity_id = ANY(CAST(cs.entity_ids AS uuid[]))
            ORDER BY c.created_at DESC
        ''')

        campaigns = conn.execute(campaigns_query, {'entity_id': str(contrib.entity_id)}).fetchall()

        if campaigns:
            for camp in campaigns:
                print(f'  Campaign: {camp.title}')
                print(f'  ID: {camp.id}')
                print(f'  Entites dans scope: {len(camp.entity_ids)} entite(s)')
                print(f'  -' * 40)
        else:
            print('  AUCUNE CAMPAGNE TROUVEE!')
            print('  => Le contributeur ne peut pas apparaitre car son entite')
            print('     n\'est dans le scope d\'aucune campagne.')
        print()

        # 3. Check audite_domain_scope
        print('[3] DOMAINES ATTRIBUES (audite_domain_scope)\n')
        domain_scope_query = text('''
            SELECT
                ads.id,
                ads.campaign_id,
                ads.domain_ids,
                c.title as campaign_title
            FROM audite_domain_scope ads
            LEFT JOIN campaign c ON ads.campaign_id = c.id
            WHERE ads.entity_member_id = :member_id
        ''')

        domain_scopes = conn.execute(domain_scope_query, {'member_id': str(contrib.id)}).fetchall()

        if domain_scopes:
            for ds in domain_scopes:
                print(f'  Campaign: {ds.campaign_title}')
                print(f'  Domaines: {ds.domain_ids}')
                print(f'  -' * 40)
        else:
            print('  AUCUN DOMAINE ATTRIBUE')
            print('  => Normal pour audite_contrib (transverse)')
        print()

    else:
        print('  CONTRIBUTEUR INTROUVABLE!\n')

print('=' * 80)
print('FIN DU DEBUG')
print('=' * 80 + '\n')
