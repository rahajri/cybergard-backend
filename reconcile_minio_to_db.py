"""
Script de réconciliation MinIO -> PostgreSQL
Crée les entrées manquantes dans answer_attachment pour les fichiers orphelins dans MinIO
"""
import os
import sys
from minio import Minio
from sqlalchemy import text
from src.database import SessionLocal
from datetime import datetime
import uuid

# Configuration MinIO
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ROOT_USER = os.getenv("MINIO_ROOT_USER", "minioadmin")
MINIO_ROOT_PASSWORD = os.getenv("MINIO_ROOT_PASSWORD", "minioadmin123")
MINIO_BUCKET = os.getenv("MINIO_BUCKET_NAME", "audit-attachments")

print("=" * 80)
print("RECONCILIATION MinIO -> PostgreSQL")
print("=" * 80)
print()

# Connexion MinIO
client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ROOT_USER,
    secret_key=MINIO_ROOT_PASSWORD,
    secure=False
)

# Connexion DB
db = SessionLocal()

try:
    # Récupérer tous les objets MinIO
    print("[1/4] Lecture des fichiers dans MinIO...")
    objects = list(client.list_objects(MINIO_BUCKET, recursive=True))
    print(f"      Trouves: {len(objects)} fichiers")
    print()

    # Vérifier quels fichiers existent déjà en BDD
    print("[2/4] Verification dans la base de donnees...")
    existing_files = set()
    result = db.execute(text("SELECT file_path FROM answer_attachment")).fetchall()
    for row in result:
        existing_files.add(row[0])
    print(f"      Deja en BDD: {len(existing_files)} fichiers")
    print()

    # Identifier les fichiers manquants
    missing = []
    for obj in objects:
        if obj.object_name not in existing_files:
            missing.append(obj)

    print(f"[3/4] Fichiers orphelins a ajouter: {len(missing)}")
    print()

    if len(missing) == 0:
        print("[OK] Aucune reconciliation necessaire!")
        sys.exit(0)

    # Créer les entrées manquantes
    print("[4/4] Creation des entrees dans answer_attachment...")
    created = 0
    errors = 0

    for obj in missing:
        try:
            # Parser le chemin: tenant_id/audit_id/answer_id/filename.ext
            parts = obj.object_name.split('/')
            if len(parts) != 4:
                print(f"  [SKIP] Chemin invalide: {obj.object_name}")
                continue

            tenant_id = parts[0]
            audit_id = parts[1]
            answer_id = parts[2]
            filename = parts[3]

            # Extraire extension
            file_ext = filename.split('.')[-1] if '.' in filename else None

            # Déterminer le mime_type depuis l'extension
            mime_mapping = {
                'pdf': 'application/pdf',
                'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                'txt': 'text/plain',
                'md': 'text/markdown',
                'jpg': 'image/jpeg',
                'jpeg': 'image/jpeg',
                'png': 'image/png'
            }
            mime_type = mime_mapping.get(file_ext.lower() if file_ext else '', 'application/octet-stream')

            # Tenter de récupérer les métadonnées
            try:
                stat = client.stat_object(MINIO_BUCKET, obj.object_name)
                metadata = stat.metadata
                original_filename = metadata.get('original-filename', filename)

                # Décoder si base64
                if 'original-filename-b64' in metadata:
                    import base64
                    try:
                        original_filename = base64.b64decode(metadata['original-filename-b64']).decode('utf-8')
                    except:
                        pass
            except:
                original_filename = filename

            # Vérifier que answer_id existe
            answer_check = db.execute(
                text("SELECT id FROM question_answer WHERE id = :aid AND audit_id = :aud"),
                {"aid": answer_id, "aud": audit_id}
            ).fetchone()

            if not answer_check:
                print(f"  [SKIP] Answer inexistante: {obj.object_name}")
                continue

            # Créer l'entrée
            insert_query = text("""
                INSERT INTO answer_attachment (
                    id, answer_id, audit_id, tenant_id,
                    filename, original_filename, file_path,
                    file_size, mime_type, file_extension,
                    attachment_type, virus_scan_status,
                    is_active, uploaded_at
                ) VALUES (
                    :id, :answer_id, :audit_id, :tenant_id,
                    :filename, :original_filename, :file_path,
                    :file_size, :mime_type, :file_extension,
                    'evidence', 'skipped',
                    true, :uploaded_at
                )
            """)

            db.execute(insert_query, {
                "id": str(uuid.uuid4()),
                "answer_id": answer_id,
                "audit_id": audit_id,
                "tenant_id": tenant_id,
                "filename": filename,
                "original_filename": original_filename,
                "file_path": obj.object_name,
                "file_size": obj.size,
                "mime_type": mime_type,
                "file_extension": file_ext,
                "uploaded_at": obj.last_modified
            })

            created += 1
            print(f"  [OK] {original_filename} ({obj.size / 1024:.1f} KB)")

        except Exception as e:
            errors += 1
            print(f"  [ERROR] {obj.object_name}: {e}")
            continue

    # Commit toutes les insertions
    db.commit()

    print()
    print("=" * 80)
    print(f"[TERMINE] Crees: {created} | Erreurs: {errors} | Total: {len(missing)}")
    print("=" * 80)

except Exception as e:
    print(f"[FATAL] Erreur: {e}")
    import traceback
    traceback.print_exc()
    db.rollback()
finally:
    db.close()
