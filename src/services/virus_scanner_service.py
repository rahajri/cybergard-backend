# backend/src/services/virus_scanner_service.py
"""
Service de scan antivirus avec ClamAV
"""
import os
import logging
from typing import BinaryIO, Dict, Optional
import clamd
from io import BytesIO

logger = logging.getLogger(__name__)


class VirusScannerService:
    """
    Service de scan antivirus avec ClamAV.

    Supporte :
    - Scan de fichiers en mémoire
    - Scan de fichiers sur disque
    - Connexion TCP ou Unix socket
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        timeout: int = 30
    ):
        """
        Initialise la connexion à ClamAV.

        Args:
            host: Host ClamAV (défaut: localhost)
            port: Port ClamAV (défaut: 3310)
            timeout: Timeout en secondes
        """
        self.host = host or os.getenv("CLAMAV_HOST", "localhost")
        self.port = port or int(os.getenv("CLAMAV_PORT", "3310"))
        self.timeout = timeout
        self.enabled = os.getenv("CLAMAV_ENABLED", "true").lower() == "true"

        if not self.enabled:
            logger.warning("⚠️  Scan antivirus désactivé (CLAMAV_ENABLED=false)")
            self.client = None
            return

        try:
            # Tenter connexion TCP
            self.client = clamd.ClamdNetworkSocket(
                host=self.host,
                port=self.port,
                timeout=self.timeout
            )

            # Test de connexion
            self.client.ping()
            logger.info(f"✅ ClamAV connecté : {self.host}:{self.port}")

        except Exception as e:
            logger.error(f"❌ Erreur connexion ClamAV : {e}")
            logger.warning("⚠️  Scan antivirus désactivé (ClamAV non disponible)")
            self.enabled = False
            self.client = None

    async def scan_file(self, file_data: BinaryIO) -> Dict[str, any]:
        """
        Scanne un fichier en mémoire.

        Args:
            file_data: Données du fichier (binary stream)

        Returns:
            Dict avec résultat du scan:
            {
                "is_clean": bool,
                "virus_name": Optional[str],
                "scan_result": str,  # "OK", "FOUND", "ERROR"
                "details": Optional[str]
            }

        Raises:
            Exception si erreur technique (pas si virus trouvé)
        """
        if not self.enabled or not self.client:
            logger.info("Scan antivirus ignoré (désactivé)")
            return {
                "is_clean": True,
                "virus_name": None,
                "scan_result": "SKIPPED",
                "details": "Scan antivirus désactivé"
            }

        try:
            # Reset au début du fichier
            file_data.seek(0)

            # Scan
            result = self.client.instream(file_data)

            # Parse résultat
            # Format: {'stream': ('FOUND', 'Eicar-Test-Signature')}
            # ou     {'stream': ('OK', None)}
            stream_result = result.get("stream")

            if not stream_result:
                raise Exception("Résultat scan invalide")

            scan_status, virus_name = stream_result

            is_clean = (scan_status == "OK")

            scan_result = {
                "is_clean": is_clean,
                "virus_name": virus_name if not is_clean else None,
                "scan_result": scan_status,
                "details": f"Virus détecté: {virus_name}" if not is_clean else "Aucun virus détecté"
            }

            if not is_clean:
                logger.warning(f"🦠 VIRUS DÉTECTÉ : {virus_name}")
            else:
                logger.info("✅ Scan antivirus : fichier propre")

            return scan_result

        except clamd.ConnectionError as e:
            logger.error(f"❌ Erreur connexion ClamAV : {e}")
            raise Exception("Service antivirus indisponible")

        except Exception as e:
            logger.error(f"❌ Erreur scan antivirus : {e}")
            raise

    async def scan_file_path(self, file_path: str) -> Dict[str, any]:
        """
        Scanne un fichier sur disque.

        Args:
            file_path: Chemin du fichier

        Returns:
            Dict avec résultat du scan
        """
        if not self.enabled or not self.client:
            return {
                "is_clean": True,
                "virus_name": None,
                "scan_result": "SKIPPED",
                "details": "Scan antivirus désactivé"
            }

        try:
            result = self.client.scan(file_path)

            # Format: {'/path/to/file': ('FOUND', 'Virus-Name')}
            file_result = result.get(file_path)

            if not file_result:
                raise Exception("Résultat scan invalide")

            scan_status, virus_name = file_result

            is_clean = (scan_status == "OK")

            return {
                "is_clean": is_clean,
                "virus_name": virus_name if not is_clean else None,
                "scan_result": scan_status,
                "details": f"Virus détecté: {virus_name}" if not is_clean else "Aucun virus détecté"
            }

        except Exception as e:
            logger.error(f"❌ Erreur scan fichier {file_path} : {e}")
            raise

    def get_version(self) -> Optional[str]:
        """Récupère la version de ClamAV"""
        if not self.enabled or not self.client:
            return None

        try:
            return self.client.version()
        except Exception as e:
            logger.error(f"Erreur récupération version ClamAV : {e}")
            return None

    def get_stats(self) -> Optional[Dict]:
        """Récupère les statistiques de ClamAV"""
        if not self.enabled or not self.client:
            return None

        try:
            return self.client.stats()
        except Exception as e:
            logger.error(f"Erreur récupération stats ClamAV : {e}")
            return None

    def reload_database(self) -> bool:
        """Recharge la base de signatures"""
        if not self.enabled or not self.client:
            return False

        try:
            self.client.reload()
            logger.info("✅ Base de signatures ClamAV rechargée")
            return True
        except Exception as e:
            logger.error(f"❌ Erreur rechargement signatures : {e}")
            return False
