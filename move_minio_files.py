"""
Script pour déplacer les fichiers MinIO vers le bon dossier tenant
"""
import os
from minio import Minio
from minio.commonconfig import CopySource

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ROOT_USER = os.getenv("MINIO_ROOT_USER", "minioadmin")
MINIO_ROOT_PASSWORD = os.getenv("MINIO_ROOT_PASSWORD", "minioadmin123")
MINIO_BUCKET = os.getenv("MINIO_BUCKET_NAME", "audit-attachments")

OLD_TENANT = "00000000-0000-0000-0000-000000000000"
NEW_TENANT = "e628c959-d81b-417d-bbb9-0e861053ec30"

print("=" * 80)
print("DÉPLACEMENT DES FICHIERS MINIO")
print("=" * 80)
print()

# Connexion MinIO
client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ROOT_USER,
    secret_key=MINIO_ROOT_PASSWORD,
    secure=False
)

print(f"[1/3] Recherche des fichiers dans {OLD_TENANT}/...")
objects = list(client.list_objects(MINIO_BUCKET, prefix=f"{OLD_TENANT}/", recursive=True))
print(f"      Trouvés: {len(objects)} fichiers")
print()

if len(objects) == 0:
    print("[INFO] Aucun fichier à déplacer!")
    exit(0)

print(f"[2/3] Copie vers {NEW_TENANT}/...")
moved = 0
errors = 0

for obj in objects:
    try:
        # Nouveau chemin
        new_path = obj.object_name.replace(OLD_TENANT, NEW_TENANT, 1)

        # Copier
        client.copy_object(
            bucket_name=MINIO_BUCKET,
            object_name=new_path,
            source=CopySource(MINIO_BUCKET, obj.object_name)
        )

        print(f"  [OK] {obj.object_name} -> {new_path}")
        moved += 1

    except Exception as e:
        print(f"  [ERROR] {obj.object_name}: {e}")
        errors += 1

print()
print(f"[3/3] Suppression des anciens fichiers...")
for obj in objects:
    try:
        client.remove_object(MINIO_BUCKET, obj.object_name)
    except Exception as e:
        print(f"  [ERROR] Impossible de supprimer {obj.object_name}: {e}")

print()
print("=" * 80)
print(f"[TERMINÉ] Déplacés: {moved} | Erreurs: {errors}")
print("=" * 80)
