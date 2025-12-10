"""
Script pour vérifier le contenu de MinIO
"""
import os
from minio import Minio
from minio.error import S3Error

# Récupérer les credentials depuis .env ou utiliser les valeurs par défaut
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ROOT_USER = os.getenv("MINIO_ROOT_USER", "minioadmin")
MINIO_ROOT_PASSWORD = os.getenv("MINIO_ROOT_PASSWORD", "minioadmin123")
MINIO_BUCKET = os.getenv("MINIO_BUCKET_NAME", "audit-attachments")

print("=" * 60)
print("Vérification du contenu de MinIO")
print("=" * 60)
print(f"Endpoint: {MINIO_ENDPOINT}")
print(f"Bucket: {MINIO_BUCKET}")
print()

try:
    # Connexion à MinIO
    client = Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ROOT_USER,
        secret_key=MINIO_ROOT_PASSWORD,
        secure=False  # HTTP en local
    )

    print("[OK] Connexion a MinIO reussie")
    print()

    # Lister tous les buckets
    print("[BUCKETS] Buckets disponibles:")
    buckets = client.list_buckets()
    if not buckets:
        print("  [!] Aucun bucket trouve!")
    else:
        for bucket in buckets:
            print(f"  - {bucket.name} (cree le {bucket.creation_date})")
    print()

    # Vérifier si le bucket principal existe
    if client.bucket_exists(MINIO_BUCKET):
        print(f"[OK] Le bucket '{MINIO_BUCKET}' existe")
        print()

        # Lister les objets dans le bucket
        print(f"[FILES] Fichiers dans '{MINIO_BUCKET}':")
        objects = list(client.list_objects(MINIO_BUCKET, recursive=True))

        if not objects:
            print("  [!] Aucun fichier trouve dans le bucket!")
        else:
            total_size = 0
            for obj in objects:
                size_mb = obj.size / (1024 * 1024)
                total_size += obj.size
                print(f"  - {obj.object_name}")
                print(f"    Taille: {size_mb:.2f} MB")
                print(f"    Modifie: {obj.last_modified}")
                print()

            print(f"[STATS] Total: {len(objects)} fichiers, {total_size / (1024 * 1024):.2f} MB")
    else:
        print(f"[ERROR] Le bucket '{MINIO_BUCKET}' n'existe pas!")
        print("   Vous devez peut-etre executer le script d'initialisation.")

except S3Error as e:
    print(f"[ERROR] Erreur MinIO: {e}")
except Exception as e:
    print(f"[ERROR] Erreur: {e}")
    print(f"   Type: {type(e).__name__}")
