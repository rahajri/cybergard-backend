# backend/src/services/file_storage_service.py
"""
Service de gestion du stockage des fichiers avec MinIO
- Chiffrement automatique (SSE-S3)
- Isolation par tenant
- Versioning
- URLs pré-signées temporaires
- Structure GED organisée par campagne
"""
import os
import hashlib
import mimetypes
from typing import Optional, BinaryIO, List, Tuple
from uuid import UUID, uuid4
from datetime import timedelta, datetime
from pathlib import Path

from minio import Minio
from minio.error import S3Error
from minio.commonconfig import CopySource
from urllib3.response import HTTPResponse

import logging
from .ged_path_service import GEDPathService

logger = logging.getLogger(__name__)


class FileStorageService:
    """
    Service de stockage de fichiers avec MinIO.
    Gère le chiffrement, versioning, et isolation tenant.
    """

    def __init__(
        self,
        endpoint: str = None,
        access_key: str = None,
        secret_key: str = None,
        secure: bool = False,
        bucket_name: str = "audit-attachments"
    ):
        """
        Initialise le client MinIO.

        Args:
            endpoint: URL de MinIO (ex: localhost:9000)
            access_key: Access key MinIO
            secret_key: Secret key MinIO
            secure: True pour HTTPS
            bucket_name: Nom du bucket principal
        """
        self.endpoint = endpoint or os.getenv("MINIO_ENDPOINT", "localhost:9000")
        self.access_key = access_key or os.getenv("MINIO_ROOT_USER", "minioadmin")
        self.secret_key = secret_key or os.getenv("MINIO_ROOT_PASSWORD", "minioadmin123")
        self.secure = secure or os.getenv("MINIO_SECURE", "false").lower() == "true"
        self.bucket_name = bucket_name

        try:
            self.client = Minio(
                self.endpoint,
                access_key=self.access_key,
                secret_key=self.secret_key,
                secure=self.secure
            )
            logger.info(f"✅ MinIO client initialized: {self.endpoint}")

            # Vérifier que le bucket existe
            if not self.client.bucket_exists(self.bucket_name):
                logger.warning(f"⚠️  Bucket {self.bucket_name} n'existe pas. Lancer init_minio.py")

        except Exception as e:
            logger.error(f"❌ Erreur initialisation MinIO : {e}")
            raise

    def _build_object_path(
        self,
        tenant_id: UUID,
        audit_id: UUID,
        answer_id: UUID,
        filename: str
    ) -> str:
        """
        Construit le chemin de l'objet avec isolation tenant.

        Format: {tenant_id}/{audit_id}/{answer_id}/{filename}

        Args:
            tenant_id: ID du tenant (isolation)
            audit_id: ID de l'audit
            answer_id: ID de la réponse
            filename: Nom du fichier (UUID-based pour unicité)

        Returns:
            Chemin complet de l'objet
        """
        return f"{tenant_id}/{audit_id}/{answer_id}/{filename}"

    def _compute_sha256(self, file_data: BinaryIO) -> str:
        """
        Calcule le hash SHA-256 d'un fichier.

        Args:
            file_data: Données du fichier

        Returns:
            Hash SHA-256 en hexadécimal
        """
        sha256_hash = hashlib.sha256()
        file_data.seek(0)  # Reset au début

        for byte_block in iter(lambda: file_data.read(4096), b""):
            sha256_hash.update(byte_block)

        file_data.seek(0)  # Reset pour lecture ultérieure
        return sha256_hash.hexdigest()

    def upload_file(
        self,
        file_data: BinaryIO,
        original_filename: str,
        tenant_id: UUID,
        audit_id: UUID,
        answer_id: UUID,
        content_type: Optional[str] = None
    ) -> Tuple[str, str, int]:
        """
        Upload un fichier vers MinIO avec chiffrement automatique.

        Args:
            file_data: Données du fichier (binary stream)
            original_filename: Nom original du fichier
            tenant_id: ID du tenant
            audit_id: ID de l'audit
            answer_id: ID de la réponse
            content_type: Type MIME (détecté automatiquement si None)

        Returns:
            Tuple (object_path, checksum_sha256, file_size)

        Raises:
            S3Error: En cas d'erreur MinIO
        """
        try:
            # Générer nom unique pour éviter collisions
            file_ext = Path(original_filename).suffix
            unique_filename = f"{uuid4()}{file_ext}"

            # Construire chemin avec isolation tenant
            object_path = self._build_object_path(
                tenant_id, audit_id, answer_id, unique_filename
            )

            # Détecter type MIME si non fourni
            if not content_type:
                content_type, _ = mimetypes.guess_type(original_filename)
                content_type = content_type or "application/octet-stream"

            # Calculer checksum AVANT upload
            checksum = self._compute_sha256(file_data)

            # Obtenir taille fichier
            file_data.seek(0, 2)  # Aller à la fin
            file_size = file_data.tell()
            file_data.seek(0)  # Reset au début

            # Encoder le nom de fichier en base64 pour supporter les caractères non-ASCII
            import base64
            original_filename_b64 = base64.b64encode(original_filename.encode('utf-8')).decode('ascii')

            # Upload vers MinIO avec chiffrement SSE-S3 automatique
            self.client.put_object(
                bucket_name=self.bucket_name,
                object_name=object_path,
                data=file_data,
                length=file_size,
                content_type=content_type,
                metadata={
                    "original-filename-b64": original_filename_b64,  # Nom encodé en base64
                    "tenant-id": str(tenant_id),
                    "audit-id": str(audit_id),
                    "answer-id": str(answer_id),
                    "checksum-sha256": checksum,
                    "uploaded-at": datetime.utcnow().isoformat()
                }
            )

            logger.info(
                f"✅ Fichier uploadé : {object_path} "
                f"(tenant={tenant_id}, size={file_size}, checksum={checksum[:16]}...)"
            )

            return object_path, checksum, file_size

        except S3Error as e:
            logger.error(f"❌ Erreur upload MinIO : {e}")
            raise
        except Exception as e:
            logger.error(f"❌ Erreur upload : {e}")
            raise

    def download_file(
        self,
        object_path: str,
        tenant_id: UUID
    ) -> HTTPResponse:
        """
        Télécharge un fichier depuis MinIO.

        Vérifie que le fichier appartient bien au tenant (sécurité).

        Args:
            object_path: Chemin de l'objet
            tenant_id: ID du tenant (vérification)

        Returns:
            Response HTTP avec données du fichier

        Raises:
            PermissionError: Si le fichier n'appartient pas au tenant
            S3Error: En cas d'erreur MinIO
        """
        try:
            # Vérification sécurité : le chemin doit commencer par le tenant_id
            if not object_path.startswith(str(tenant_id)):
                logger.error(
                    f"🚨 SECURITY: Tentative d'accès fichier autre tenant ! "
                    f"tenant={tenant_id}, path={object_path}"
                )
                raise PermissionError("Accès non autorisé à ce fichier")

            # Télécharger le fichier
            response = self.client.get_object(
                bucket_name=self.bucket_name,
                object_name=object_path
            )

            logger.info(f"✅ Fichier téléchargé : {object_path} (tenant={tenant_id})")
            return response

        except S3Error as e:
            logger.error(f"❌ Erreur download MinIO : {e}")
            raise
        except PermissionError:
            raise
        except Exception as e:
            logger.error(f"❌ Erreur download : {e}")
            raise

    def get_presigned_url(
        self,
        object_path: str,
        tenant_id: UUID,
        expires: timedelta = timedelta(hours=1)
    ) -> str:
        """
        Génère une URL pré-signée temporaire pour téléchargement.

        Permet de partager un lien de téléchargement sans authentification,
        valide pendant une durée limitée.

        Args:
            object_path: Chemin de l'objet
            tenant_id: ID du tenant (vérification)
            expires: Durée de validité de l'URL (défaut: 1h)

        Returns:
            URL pré-signée

        Raises:
            PermissionError: Si le fichier n'appartient pas au tenant
        """
        try:
            # Vérification sécurité
            if not object_path.startswith(str(tenant_id)):
                raise PermissionError("Accès non autorisé à ce fichier")

            url = self.client.presigned_get_object(
                bucket_name=self.bucket_name,
                object_name=object_path,
                expires=expires
            )

            logger.info(
                f"✅ URL pré-signée générée : {object_path} "
                f"(tenant={tenant_id}, expires={expires})"
            )
            return url

        except Exception as e:
            logger.error(f"❌ Erreur génération URL : {e}")
            raise

    def delete_file(
        self,
        object_path: str,
        tenant_id: UUID
    ) -> bool:
        """
        Supprime un fichier (soft delete via versioning si activé).

        Args:
            object_path: Chemin de l'objet
            tenant_id: ID du tenant (vérification)

        Returns:
            True si succès

        Raises:
            PermissionError: Si le fichier n'appartient pas au tenant
        """
        try:
            # Vérification sécurité
            if not object_path.startswith(str(tenant_id)):
                raise PermissionError("Accès non autorisé à ce fichier")

            self.client.remove_object(
                bucket_name=self.bucket_name,
                object_name=object_path
            )

            logger.info(f"✅ Fichier supprimé : {object_path} (tenant={tenant_id})")
            return True

        except S3Error as e:
            logger.error(f"❌ Erreur suppression MinIO : {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Erreur suppression : {e}")
            return False

    def list_files(
        self,
        tenant_id: UUID,
        audit_id: Optional[UUID] = None,
        prefix: Optional[str] = None
    ) -> List[dict]:
        """
        Liste les fichiers d'un tenant (ou d'un audit spécifique).

        Args:
            tenant_id: ID du tenant
            audit_id: ID de l'audit (optionnel, filtre)
            prefix: Préfixe supplémentaire (optionnel)

        Returns:
            Liste des objets avec métadonnées
        """
        try:
            # Construire le préfixe de recherche
            if audit_id:
                search_prefix = f"{tenant_id}/{audit_id}/"
            else:
                search_prefix = f"{tenant_id}/"

            if prefix:
                search_prefix += prefix

            objects = self.client.list_objects(
                bucket_name=self.bucket_name,
                prefix=search_prefix,
                recursive=True
            )

            files = []
            for obj in objects:
                files.append({
                    "object_name": obj.object_name,
                    "size": obj.size,
                    "last_modified": obj.last_modified,
                    "etag": obj.etag,
                    "is_dir": obj.is_dir
                })

            logger.info(
                f"✅ Liste fichiers : {len(files)} trouvés "
                f"(tenant={tenant_id}, prefix={search_prefix})"
            )
            return files

        except S3Error as e:
            logger.error(f"❌ Erreur liste fichiers : {e}")
            return []

    def get_file_metadata(
        self,
        object_path: str,
        tenant_id: UUID
    ) -> dict:
        """
        Récupère les métadonnées d'un fichier sans le télécharger.

        Args:
            object_path: Chemin de l'objet
            tenant_id: ID du tenant (vérification)

        Returns:
            Métadonnées du fichier
        """
        try:
            # Vérification sécurité
            if not object_path.startswith(str(tenant_id)):
                raise PermissionError("Accès non autorisé à ce fichier")

            stat = self.client.stat_object(
                bucket_name=self.bucket_name,
                object_name=object_path
            )

            metadata = {
                "object_name": stat.object_name,
                "size": stat.size,
                "etag": stat.etag,
                "content_type": stat.content_type,
                "last_modified": stat.last_modified,
                "metadata": stat.metadata,
                "version_id": stat.version_id
            }

            return metadata

        except S3Error as e:
            logger.error(f"❌ Erreur récupération métadonnées : {e}")
            raise

    # ========================================================================
    # NOUVELLE STRUCTURE GED PAR CAMPAGNE
    # ========================================================================

    def upload_evidence(
        self,
        file_data: BinaryIO,
        original_filename: str,
        tenant_id: UUID,
        campaign_id: UUID,
        entity_id: Optional[UUID] = None,
        question_id: Optional[UUID] = None,
        content_type: Optional[str] = None
    ) -> Tuple[str, str, int]:
        """
        Upload une pièce justificative (evidence) dans la structure GED par campagne

        Args:
            file_data: Données du fichier
            original_filename: Nom original du fichier
            tenant_id: ID du tenant
            campaign_id: ID de la campagne
            entity_id: ID de l'entité auditée (optionnel)
            question_id: ID de la question (optionnel)
            content_type: Type MIME (détecté automatiquement si None)

        Returns:
            Tuple (object_path, checksum_sha256, file_size)
        """
        try:
            # Générer nom unique
            file_ext = Path(original_filename).suffix
            unique_filename = f"{uuid4()}{file_ext}"

            # Construire chemin avec nouvelle structure GED
            object_path = GEDPathService.build_evidence_path(
                tenant_id=tenant_id,
                campaign_id=campaign_id,
                filename=unique_filename,
                question_id=question_id,
                entity_id=entity_id
            )

            # Détecter type MIME
            if not content_type:
                content_type, _ = mimetypes.guess_type(original_filename)
                content_type = content_type or "application/octet-stream"

            # Calculer checksum
            checksum = self._compute_sha256(file_data)

            # Obtenir taille
            file_data.seek(0, 2)
            file_size = file_data.tell()
            file_data.seek(0)

            # Encoder nom original
            import base64
            original_filename_b64 = base64.b64encode(original_filename.encode('utf-8')).decode('ascii')

            # Upload vers MinIO
            self.client.put_object(
                bucket_name=self.bucket_name,
                object_name=object_path,
                data=file_data,
                length=file_size,
                content_type=content_type,
                metadata={
                    "original-filename-b64": original_filename_b64,
                    "tenant-id": str(tenant_id),
                    "campaign-id": str(campaign_id),
                    "entity-id": str(entity_id) if entity_id else "",
                    "question-id": str(question_id) if question_id else "",
                    "checksum-sha256": checksum,
                    "document-type": "evidence",
                    "uploaded-at": datetime.utcnow().isoformat()
                }
            )

            logger.info(
                f"✅ Evidence uploadée : {object_path} "
                f"(campaign={campaign_id}, size={file_size})"
            )

            return object_path, checksum, file_size

        except Exception as e:
            logger.error(f"❌ Erreur upload evidence : {e}")
            raise

    def upload_report(
        self,
        file_data: BinaryIO,
        filename: str,
        tenant_id: UUID,
        campaign_id: UUID,
        report_type: str = "final",
        version: Optional[str] = None,
        content_type: Optional[str] = None,
        metadata: Optional[dict] = None
    ) -> Tuple[str, str, int]:
        """
        Upload un rapport dans la structure GED par campagne

        Args:
            file_data: Données du fichier
            filename: Nom du fichier
            tenant_id: ID du tenant
            campaign_id: ID de la campagne
            report_type: Type de rapport ("preliminary", "final", "synthesis", "correction")
            version: Version du rapport (pour les corrections, ex: "v1", "v2")
            content_type: Type MIME
            metadata: Métadonnées additionnelles

        Returns:
            Tuple (object_path, checksum_sha256, file_size)
        """
        try:
            # Construire chemin avec nouvelle structure GED
            object_path = GEDPathService.build_report_path(
                tenant_id=tenant_id,
                campaign_id=campaign_id,
                report_type=report_type,
                filename=filename,
                version=version
            )

            # Détecter type MIME
            if not content_type:
                content_type, _ = mimetypes.guess_type(filename)
                content_type = content_type or "application/pdf"

            # Calculer checksum
            checksum = self._compute_sha256(file_data)

            # Obtenir taille
            file_data.seek(0, 2)
            file_size = file_data.tell()
            file_data.seek(0)

            # Préparer métadonnées
            upload_metadata = {
                "tenant-id": str(tenant_id),
                "campaign-id": str(campaign_id),
                "report-type": report_type,
                "checksum-sha256": checksum,
                "document-type": "report",
                "uploaded-at": datetime.utcnow().isoformat()
            }

            if version:
                upload_metadata["version"] = version

            if metadata:
                # Normaliser les valeurs pour MinIO (US-ASCII uniquement)
                def normalize_for_minio(value: str) -> str:
                    """Convertit une chaîne en ASCII pour MinIO."""
                    import unicodedata
                    # Normaliser et remplacer les caractères non-ASCII
                    normalized = unicodedata.normalize('NFKD', str(value))
                    return normalized.encode('ascii', 'ignore').decode('ascii')

                upload_metadata.update({f"custom-{k}": normalize_for_minio(v) for k, v in metadata.items()})

            # Upload vers MinIO
            self.client.put_object(
                bucket_name=self.bucket_name,
                object_name=object_path,
                data=file_data,
                length=file_size,
                content_type=content_type,
                metadata=upload_metadata
            )

            logger.info(
                f"✅ Rapport uploadé : {object_path} "
                f"(campaign={campaign_id}, type={report_type}, size={file_size})"
            )

            return object_path, checksum, file_size

        except Exception as e:
            logger.error(f"❌ Erreur upload rapport : {e}")
            raise

    def download_file_ged(
        self,
        object_path: str,
        tenant_id: UUID
    ) -> HTTPResponse:
        """
        Télécharge un fichier depuis la structure GED

        Vérifie que le fichier appartient au tenant via la nouvelle structure.

        Args:
            object_path: Chemin de l'objet (format GED)
            tenant_id: ID du tenant

        Returns:
            Response HTTP avec données du fichier

        Raises:
            PermissionError: Si le fichier n'appartient pas au tenant
        """
        try:
            # Vérifier que le chemin appartient au tenant
            path_tenant_id = GEDPathService.get_tenant_from_path(object_path)

            if not path_tenant_id or path_tenant_id != str(tenant_id):
                logger.error(
                    f"🚨 SECURITY: Tentative d'accès fichier autre tenant ! "
                    f"tenant={tenant_id}, path={object_path}"
                )
                raise PermissionError("Accès non autorisé à ce fichier")

            # Télécharger le fichier
            response = self.client.get_object(
                bucket_name=self.bucket_name,
                object_name=object_path
            )

            logger.info(f"✅ Fichier GED téléchargé : {object_path}")
            return response

        except PermissionError:
            raise
        except Exception as e:
            logger.error(f"❌ Erreur download GED : {e}")
            raise

    def list_campaign_documents(
        self,
        tenant_id: UUID,
        campaign_id: UUID,
        document_type: Optional[str] = None
    ) -> List[dict]:
        """
        Liste tous les documents d'une campagne

        Args:
            tenant_id: ID du tenant
            campaign_id: ID de la campagne
            document_type: Type de document ("evidence", "report", None pour tous)

        Returns:
            Liste de dictionnaires avec infos des documents
        """
        try:
            base_path = GEDPathService.build_campaign_base_path(tenant_id, campaign_id)

            if document_type:
                base_path = f"{base_path}/{document_type}/"

            objects = self.client.list_objects(
                bucket_name=self.bucket_name,
                prefix=base_path,
                recursive=True
            )

            documents = []
            for obj in objects:
                parsed = GEDPathService.parse_path(obj.object_name)
                documents.append({
                    "path": obj.object_name,
                    "filename": parsed.get("filename"),
                    "document_type": parsed.get("document_type"),
                    "size": obj.size,
                    "last_modified": obj.last_modified,
                    "etag": obj.etag,
                    "entity_id": parsed.get("entity_id"),
                    "question_id": parsed.get("question_id"),
                    "report_type": parsed.get("report_type"),
                    "version": parsed.get("version")
                })

            logger.info(f"📋 Listés {len(documents)} documents pour campagne {campaign_id}")
            return documents

        except Exception as e:
            logger.error(f"❌ Erreur listing documents : {e}")
            raise
