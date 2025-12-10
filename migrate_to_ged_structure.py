"""
Script de migration vers la nouvelle structure GED organisée par campagne

Ancienne structure: {tenant_id}/{audit_id}/{answer_id}/{filename}
Nouvelle structure: tenant-{tenant_id}/campaigns/{campaign_id}/evidence/{entity_id}/{question_id}/{filename}

Ce script:
1. Liste tous les fichiers dans MinIO
2. Récupère les informations depuis la base de données (campaign_id, entity_id, question_id)
3. Copie les fichiers vers la nouvelle structure
4. Met à jour les file_path dans answer_attachment
5. Conserve les anciens fichiers (pas de suppression automatique)
"""
import os
import sys
from pathlib import Path

# Ajouter le répertoire parent au PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.database import SessionLocal
from src.services.file_storage_service import FileStorageService
from src.services.ged_path_service import GEDPathService
from sqlalchemy import text
from minio.commonconfig import CopySource
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

print("=" * 80)
print("MIGRATION VERS STRUCTURE GED PAR CAMPAGNE")
print("=" * 80)
print()

# Connexion base de données
db = SessionLocal()

# Connexion MinIO
storage_service = FileStorageService()

try:
    # 1. Récupérer tous les documents avec leurs infos de campagne
    print("[1/5] Récupération des documents depuis la base de données...")

    query = text("""
        SELECT
            aa.id as attachment_id,
            aa.file_path as old_path,
            aa.original_filename,
            aa.tenant_id,
            aa.audit_id,
            aa.answer_id,
            qa.question_id,
            a.evaluated_org_id as entity_id,
            c.id as campaign_id,
            c.title as campaign_title
        FROM answer_attachment aa
        INNER JOIN question_answer qa ON aa.answer_id = qa.id
        INNER JOIN audit a ON aa.audit_id = a.id
        LEFT JOIN campaign c ON a.name LIKE '%' || c.title || '%'
        WHERE aa.is_active = true
          AND aa.deleted_at IS NULL
          AND aa.file_path IS NOT NULL
    """)

    documents = db.execute(query).fetchall()

    print(f"      Trouvés: {len(documents)} documents à migrer")
    print()

    if len(documents) == 0:
        print("[INFO] Aucun document à migrer!")
        exit(0)

    # 2. Afficher un aperçu
    print("[2/5] Aperçu de la migration:")
    print()

    # Compter par campagne
    campaigns = {}
    for doc in documents:
        camp_id = str(doc.campaign_id) if doc.campaign_id else "SANS_CAMPAGNE"
        campaigns[camp_id] = campaigns.get(camp_id, 0) + 1

    for camp_id, count in campaigns.items():
        if camp_id == "SANS_CAMPAGNE":
            print(f"      ⚠️  Documents sans campagne: {count}")
        else:
            print(f"      - Campagne {camp_id[:8]}...: {count} documents")

    print()

    # 3. Demander confirmation
    print("[3/5] Migration en mode DRY-RUN (simulation)")
    print("      Les fichiers ne seront PAS copiés, seulement analysés.")
    print()

    response = input("Voulez-vous continuer? (o/n): ")
    if response.lower() != 'o':
        print("Migration annulée.")
        exit(0)

    print()
    print("[4/5] Simulation de la migration...")
    print()

    migrated = 0
    skipped = 0
    errors = 0

    for doc in documents:
        try:
            # Ignorer si pas de campagne
            if not doc.campaign_id:
                logger.warning(f"⚠️  Document {doc.attachment_id} sans campagne - IGNORÉ")
                skipped += 1
                continue

            # Construire nouveau chemin
            new_path = GEDPathService.build_evidence_path(
                tenant_id=doc.tenant_id,
                campaign_id=doc.campaign_id,
                filename=Path(doc.old_path).name,  # Garder le nom de fichier unique
                question_id=doc.question_id,
                entity_id=doc.entity_id
            )

            print(f"  [{migrated + 1}/{len(documents)}] {doc.original_filename}")
            print(f"      Ancien: {doc.old_path}")
            print(f"      Nouveau: {new_path}")

            # En mode DRY-RUN, on ne copie pas réellement
            # Pour activer la copie réelle, décommenter le code ci-dessous:

            # # Copier le fichier vers le nouveau chemin
            # storage_service.client.copy_object(
            #     bucket_name=storage_service.bucket_name,
            #     object_name=new_path,
            #     source=CopySource(storage_service.bucket_name, doc.old_path)
            # )

            # # Mettre à jour la base de données
            # db.execute(
            #     text("UPDATE answer_attachment SET file_path = :new_path WHERE id = :id"),
            #     {"new_path": new_path, "id": doc.attachment_id}
            # )

            migrated += 1
            print(f"      ✓ Migration simulée")
            print()

        except Exception as e:
            logger.error(f"❌ Erreur pour {doc.original_filename}: {e}")
            errors += 1
            print()

    # 5. Résumé
    print()
    print("=" * 80)
    print("[5/5] RÉSUMÉ DE LA SIMULATION")
    print("=" * 80)
    print()
    print(f"Total documents analysés: {len(documents)}")
    print(f"  - Simulés avec succès: {migrated}")
    print(f"  - Ignorés (sans campagne): {skipped}")
    print(f"  - Erreurs: {errors}")
    print()

    if skipped > 0:
        print("⚠️  ATTENTION: Des documents n'ont pas de campagne associée.")
        print("   Ces documents ne peuvent pas être migrés vers la nouvelle structure.")
        print("   Vérifiez la logique de liaison audit -> campagne dans la requête SQL.")
        print()

    print("=" * 80)
    print("MIGRATION EN MODE DRY-RUN TERMINÉE")
    print("=" * 80)
    print()
    print("Pour activer la migration réelle:")
    print("1. Ouvrir ce fichier dans un éditeur")
    print("2. Décommenter les lignes 125-135 (copie MinIO + update BDD)")
    print("3. Relancer le script")
    print()
    print("⚠️  IMPORTANT: Faire un backup de la base de données avant!")
    print()

except Exception as e:
    logger.error(f"❌ Erreur fatale: {e}")
    import traceback
    traceback.print_exc()

finally:
    db.close()
