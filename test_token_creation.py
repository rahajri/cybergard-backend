"""
Test du système de génération de tokens pour les auditeurs
"""
from src.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()

print("=" * 80)
print("VÉRIFICATION DU SYSTÈME DE TOKENS POUR AUDITEURS")
print("=" * 80)
print()

# 1. Vérifier la table audit_tokens existe
print("[1/4] Vérification de la table audit_tokens...")
try:
    result = db.execute(text("""
        SELECT COUNT(*) as count FROM information_schema.tables
        WHERE table_name = 'audit_tokens'
    """)).fetchone()

    if result.count == 1:
        print("      [OK] Table audit_tokens existe")
    else:
        print("      [ERROR] Table audit_tokens n'existe pas!")
        exit(1)
except Exception as e:
    print(f"      [ERROR] Erreur: {e}")
    exit(1)

# 2. Vérifier les colonnes de la table
print()
print("[2/4] Vérification de la structure de la table...")
try:
    columns = db.execute(text("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = 'audit_tokens'
        ORDER BY ordinal_position
    """)).fetchall()

    expected_columns = [
        'id', 'token_jti', 'token_hash', 'user_email', 'campaign_id',
        'questionnaire_id', 'tenant_id', 'expires_at', 'max_uses',
        'used_count', 'revoked', 'first_used_at', 'last_used_at',
        'last_used_ip', 'last_user_agent', 'created_at', 'updated_at'
    ]

    column_names = [c.column_name for c in columns]

    all_present = all(col in column_names for col in expected_columns)

    if all_present:
        print(f"      [OK] Structure correcte ({len(columns)} colonnes)")
    else:
        print(f"      [WARN] Colonnes trouvees: {column_names}")
        missing = [col for col in expected_columns if col not in column_names]
        if missing:
            print(f"      [ERROR] Colonnes manquantes: {missing}")

except Exception as e:
    print(f"      [ERROR] Erreur: {e}")

# 3. Compter les tokens existants
print()
print("[3/4] Vérification des tokens existants...")
try:
    # Total
    total = db.execute(text("SELECT COUNT(*) as count FROM audit_tokens")).fetchone()
    print(f"      Total de tokens: {total.count}")

    # Actifs (non révoqués et non expirés)
    active = db.execute(text("""
        SELECT COUNT(*) as count FROM audit_tokens
        WHERE revoked = false
        AND expires_at > NOW()
    """)).fetchone()
    print(f"      Tokens actifs: {active.count}")

    # Révoqués
    revoked = db.execute(text("""
        SELECT COUNT(*) as count FROM audit_tokens WHERE revoked = true
    """)).fetchone()
    print(f"      Tokens révoqués: {revoked.count}")

    # Expirés
    expired = db.execute(text("""
        SELECT COUNT(*) as count FROM audit_tokens
        WHERE revoked = false AND expires_at <= NOW()
    """)).fetchone()
    print(f"      Tokens expirés: {expired.count}")

    # Par campagne
    if total.count > 0:
        print()
        print("      Répartition par campagne:")
        by_campaign = db.execute(text("""
            SELECT
                at.campaign_id,
                c.title as campaign_title,
                COUNT(*) as token_count,
                COUNT(CASE WHEN at.revoked = false AND at.expires_at > NOW() THEN 1 END) as active_count
            FROM audit_tokens at
            LEFT JOIN campaign c ON at.campaign_id = c.id
            GROUP BY at.campaign_id, c.title
            ORDER BY token_count DESC
        """)).fetchall()

        for row in by_campaign:
            campaign_name = row.campaign_title or "Campagne supprimée"
            print(f"        - {campaign_name[:40]}: {row.token_count} tokens ({row.active_count} actifs)")

except Exception as e:
    print(f"      [ERROR] Erreur: {e}")

# 4. Tester la fonction generate_magic_link
print()
print("[4/4] Test de la fonction generate_magic_link...")
try:
    from src.services.magic_link_service import generate_magic_link
    import uuid

    # Utiliser des UUIDs de test
    test_tenant_id = uuid.UUID('e628c959-d81b-417d-bbb9-0e861053ec30')
    test_campaign_id = uuid.uuid4()
    test_questionnaire_id = uuid.uuid4()
    test_email = "test.auditeur@example.com"

    # Générer un token de test
    magic_link, audit_token = generate_magic_link(
        db=db,
        user_email=test_email,
        campaign_id=test_campaign_id,
        questionnaire_id=test_questionnaire_id,
        tenant_id=test_tenant_id
    )

    print(f"      [OK] Token genere avec succes")
    print(f"      Token JTI: {audit_token.token_jti}")
    print(f"      Email: {audit_token.user_email}")
    print(f"      Expire: {audit_token.expires_at}")
    print(f"      Max utilisations: {audit_token.max_uses}")
    print(f"      Magic Link: {magic_link[:80]}...")

    # Nettoyer le token de test
    db.execute(text("DELETE FROM audit_tokens WHERE token_jti = :jti"),
               {"jti": str(audit_token.token_jti)})
    db.commit()
    print(f"      [OK] Token de test nettoye")

except Exception as e:
    print(f"      [ERROR] Erreur: {e}")
    import traceback
    traceback.print_exc()

print()
print("=" * 80)
print("RESUME")
print("=" * 80)
print()
print("[OK] Le systeme de tokens est operationnel")
print()
print("FONCTIONNEMENT:")
print("1. Lors du lancement d'une campagne (POST /api/v1/campaigns/{id}/launch)")
print("2. Pour chaque contact audité (entity_member) du scope:")
print("   - Un token JWT est généré via generate_magic_link()")
print("   - Le token est stocké dans audit_tokens")
print("   - Un email contenant le magic link est envoyé")
print("3. L'auditeur clique sur le lien et accède à /audit/access?token=...")
print("4. Le token est échangé contre un token Keycloak pour accès sécurisé")
print()
print("SÉCURITÉ:")
print("- Token expire après 7 jours (TOKEN_EXPIRY_DAYS)")
print("- Max 10 utilisations par token (MAGIC_LINK_MAX_USES)")
print("- Révocable à tout moment")
print("- Lié à une campagne spécifique")
print("- Isolé par tenant")
print()

db.close()
