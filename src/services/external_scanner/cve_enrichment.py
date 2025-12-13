# backend/src/services/external_scanner/cve_enrichment.py
"""
Module d'enrichissement CVE via NVD API.

Utilise l'API NVD (National Vulnerability Database) pour:
- Rechercher des CVE par CPE (Common Platform Enumeration)
- Enrichir les services détectés avec leurs vulnérabilités connues
- Récupérer les scores CVSS et les détails des CVE
"""

import os
import re
import logging
import httpx
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

# API NVD
NVD_API_BASE = "https://services.nvd.nist.gov/rest/json/cves/2.0"
NVD_API_KEY = os.getenv("NVD_API_KEY")


@dataclass
class CVEInfo:
    """Information sur une CVE."""
    cve_id: str
    description: str
    cvss_score: Optional[float] = None
    cvss_vector: Optional[str] = None
    cvss_version: str = "3.1"
    severity: str = "UNKNOWN"
    published_date: Optional[datetime] = None
    last_modified: Optional[datetime] = None
    references: list[str] = field(default_factory=list)
    cwe_ids: list[str] = field(default_factory=list)
    affected_products: list[str] = field(default_factory=list)


class CVEEnrichment:
    """
    Service d'enrichissement CVE via NVD API.

    Exemple:
        enricher = CVEEnrichment()
        cves = enricher.search_by_cpe("cpe:2.3:a:apache:http_server:2.4.49:*:*:*:*:*:*:*")
        for cve in cves:
            print(f"{cve.cve_id}: {cve.severity} ({cve.cvss_score})")
    """

    # Mapping des produits courants vers leurs CPE
    PRODUCT_CPE_MAP = {
        # Web Servers
        "apache": "cpe:2.3:a:apache:http_server",
        "nginx": "cpe:2.3:a:nginx:nginx",
        "iis": "cpe:2.3:a:microsoft:internet_information_services",

        # Databases
        "mysql": "cpe:2.3:a:mysql:mysql",
        "mariadb": "cpe:2.3:a:mariadb:mariadb",
        "postgresql": "cpe:2.3:a:postgresql:postgresql",
        "mongodb": "cpe:2.3:a:mongodb:mongodb",
        "redis": "cpe:2.3:a:redis:redis",

        # SSH
        "openssh": "cpe:2.3:a:openbsd:openssh",

        # FTP
        "vsftpd": "cpe:2.3:a:vsftpd_project:vsftpd",
        "proftpd": "cpe:2.3:a:proftpd_project:proftpd",

        # Mail
        "postfix": "cpe:2.3:a:postfix:postfix",
        "exim": "cpe:2.3:a:exim:exim",
        "dovecot": "cpe:2.3:a:dovecot:dovecot",

        # Other
        "php": "cpe:2.3:a:php:php",
        "nodejs": "cpe:2.3:a:nodejs:node.js",
        "tomcat": "cpe:2.3:a:apache:tomcat",
    }

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialise le service d'enrichissement CVE.

        Args:
            api_key: Clé API NVD (optionnelle mais recommandée pour rate limiting)
        """
        self.api_key = api_key or NVD_API_KEY
        self.client = httpx.AsyncClient(timeout=30.0)

    async def close(self):
        """Ferme le client HTTP."""
        await self.client.aclose()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def search_by_cpe(
        self,
        cpe: str,
        max_results: int = 20
    ) -> list[CVEInfo]:
        """
        Recherche les CVE pour un CPE donné.

        Args:
            cpe: CPE string (ex: "cpe:2.3:a:apache:http_server:2.4.49:*:*:*:*:*:*:*")
            max_results: Nombre maximum de résultats

        Returns:
            Liste de CVEInfo
        """
        logger.info(f"🔍 Recherche CVE pour: {cpe}")

        headers = {}
        if self.api_key:
            headers["apiKey"] = self.api_key

        params = {
            "cpeName": cpe,
            "resultsPerPage": max_results
        }

        try:
            response = await self.client.get(
                NVD_API_BASE,
                params=params,
                headers=headers
            )
            response.raise_for_status()
            data = response.json()

            cves = []
            for vuln in data.get("vulnerabilities", []):
                cve_data = vuln.get("cve", {})
                cve_info = self._parse_cve(cve_data)
                if cve_info:
                    cves.append(cve_info)

            logger.info(f"✅ {len(cves)} CVE trouvées pour {cpe}")
            return cves

        except httpx.HTTPStatusError as e:
            logger.error(f"❌ Erreur API NVD: {e}")
            return []
        except Exception as e:
            logger.error(f"❌ Erreur recherche CVE: {e}")
            return []

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def search_by_keyword(
        self,
        keyword: str,
        max_results: int = 10
    ) -> list[CVEInfo]:
        """
        Recherche les CVE par mot-clé.

        Args:
            keyword: Mot-clé de recherche (ex: "Apache 2.4.49")
            max_results: Nombre maximum de résultats

        Returns:
            Liste de CVEInfo
        """
        logger.info(f"🔍 Recherche CVE par keyword: {keyword}")

        headers = {}
        if self.api_key:
            headers["apiKey"] = self.api_key

        params = {
            "keywordSearch": keyword,
            "resultsPerPage": max_results
        }

        try:
            response = await self.client.get(
                NVD_API_BASE,
                params=params,
                headers=headers
            )
            response.raise_for_status()
            data = response.json()

            cves = []
            for vuln in data.get("vulnerabilities", []):
                cve_data = vuln.get("cve", {})
                cve_info = self._parse_cve(cve_data)
                if cve_info:
                    cves.append(cve_info)

            logger.info(f"✅ {len(cves)} CVE trouvées pour '{keyword}'")
            return cves

        except Exception as e:
            logger.error(f"❌ Erreur recherche CVE: {e}")
            return []

    async def get_cve_details(self, cve_id: str) -> Optional[CVEInfo]:
        """
        Récupère les détails d'une CVE spécifique.

        Args:
            cve_id: Identifiant CVE (ex: "CVE-2021-41773")

        Returns:
            CVEInfo ou None
        """
        logger.info(f"🔍 Récupération CVE: {cve_id}")

        headers = {}
        if self.api_key:
            headers["apiKey"] = self.api_key

        params = {"cveId": cve_id}

        try:
            response = await self.client.get(
                NVD_API_BASE,
                params=params,
                headers=headers
            )
            response.raise_for_status()
            data = response.json()

            vulns = data.get("vulnerabilities", [])
            if vulns:
                return self._parse_cve(vulns[0].get("cve", {}))

            return None

        except Exception as e:
            logger.error(f"❌ Erreur récupération CVE: {e}")
            return None

    def _parse_cve(self, cve_data: dict) -> Optional[CVEInfo]:
        """Parse les données CVE de l'API NVD."""
        try:
            cve_id = cve_data.get("id")
            if not cve_id:
                return None

            # Description
            descriptions = cve_data.get("descriptions", [])
            description = ""
            for desc in descriptions:
                if desc.get("lang") == "en":
                    description = desc.get("value", "")
                    break

            # CVSS Score
            metrics = cve_data.get("metrics", {})
            cvss_score = None
            cvss_vector = None
            cvss_version = "3.1"
            severity = "UNKNOWN"

            # Essayer CVSS 3.1 d'abord
            cvss31 = metrics.get("cvssMetricV31", [])
            if cvss31:
                cvss_data = cvss31[0].get("cvssData", {})
                cvss_score = cvss_data.get("baseScore")
                cvss_vector = cvss_data.get("vectorString")
                severity = cvss_data.get("baseSeverity", "UNKNOWN")
                cvss_version = "3.1"
            else:
                # Fallback CVSS 3.0
                cvss30 = metrics.get("cvssMetricV30", [])
                if cvss30:
                    cvss_data = cvss30[0].get("cvssData", {})
                    cvss_score = cvss_data.get("baseScore")
                    cvss_vector = cvss_data.get("vectorString")
                    severity = cvss_data.get("baseSeverity", "UNKNOWN")
                    cvss_version = "3.0"
                else:
                    # Fallback CVSS 2.0
                    cvss2 = metrics.get("cvssMetricV2", [])
                    if cvss2:
                        cvss_data = cvss2[0].get("cvssData", {})
                        cvss_score = cvss_data.get("baseScore")
                        cvss_vector = cvss_data.get("vectorString")
                        cvss_version = "2.0"
                        # Convertir severity pour v2
                        if cvss_score:
                            if cvss_score >= 9.0:
                                severity = "CRITICAL"
                            elif cvss_score >= 7.0:
                                severity = "HIGH"
                            elif cvss_score >= 4.0:
                                severity = "MEDIUM"
                            else:
                                severity = "LOW"

            # Dates
            published_date = None
            last_modified = None
            if cve_data.get("published"):
                try:
                    published_date = datetime.fromisoformat(
                        cve_data["published"].replace("Z", "+00:00")
                    )
                except Exception:
                    pass

            if cve_data.get("lastModified"):
                try:
                    last_modified = datetime.fromisoformat(
                        cve_data["lastModified"].replace("Z", "+00:00")
                    )
                except Exception:
                    pass

            # Références
            references = []
            for ref in cve_data.get("references", []):
                if ref.get("url"):
                    references.append(ref["url"])

            # CWE
            cwe_ids = []
            weaknesses = cve_data.get("weaknesses", [])
            for weakness in weaknesses:
                for desc in weakness.get("description", []):
                    if desc.get("value", "").startswith("CWE-"):
                        cwe_ids.append(desc["value"])

            return CVEInfo(
                cve_id=cve_id,
                description=description,
                cvss_score=cvss_score,
                cvss_vector=cvss_vector,
                cvss_version=cvss_version,
                severity=severity,
                published_date=published_date,
                last_modified=last_modified,
                references=references[:5],  # Limiter à 5 références
                cwe_ids=cwe_ids
            )

        except Exception as e:
            logger.warning(f"Erreur parsing CVE: {e}")
            return None

    def build_cpe_from_service(
        self,
        service_name: str,
        service_version: Optional[str] = None,
        service_product: Optional[str] = None
    ) -> Optional[str]:
        """
        Construit un CPE à partir des informations du service.

        Args:
            service_name: Nom du service (ex: "http", "ssh")
            service_version: Version du service
            service_product: Produit (ex: "Apache", "OpenSSH")

        Returns:
            CPE string ou None
        """
        # Normaliser le produit
        product = (service_product or service_name or "").lower()

        # Chercher dans le mapping
        for key, cpe_base in self.PRODUCT_CPE_MAP.items():
            if key in product:
                if service_version:
                    # Nettoyer la version
                    version = re.sub(r'[^0-9.]', '', service_version.split()[0])
                    return f"{cpe_base}:{version}:*:*:*:*:*:*:*"
                return f"{cpe_base}:*:*:*:*:*:*:*:*"

        return None


async def enrich_with_vulns(service: dict) -> list[dict]:
    """
    Enrichit un service avec ses vulnérabilités CVE.

    Args:
        service: Dictionnaire avec les infos du service

    Returns:
        Liste de vulnérabilités détectées
    """
    enricher = CVEEnrichment()
    vulnerabilities = []

    try:
        # Construire le CPE
        cpe = enricher.build_cpe_from_service(
            service_name=service.get("service_name", ""),
            service_version=service.get("service_version"),
            service_product=service.get("service_product")
        )

        if cpe:
            # Rechercher les CVE
            cves = await enricher.search_by_cpe(cpe, max_results=10)

            for cve in cves:
                vulnerabilities.append({
                    "port": service.get("port"),
                    "protocol": service.get("protocol", "tcp"),
                    "service_name": service.get("service_name"),
                    "service_version": service.get("service_version"),
                    "vulnerability_type": "SERVICE_VULN",
                    "severity": cve.severity,
                    "title": cve.cve_id,
                    "description": cve.description[:500] if cve.description else None,
                    "recommendation": f"Mettre à jour {service.get('service_name')} vers une version corrigée",
                    "cve_ids": [cve.cve_id],
                    "cvss_score": cve.cvss_score,
                    "cvss_vector": cve.cvss_vector,
                    "references": cve.references
                })

        # Recherche par keyword si pas de CPE
        elif service.get("service_version"):
            keyword = f"{service.get('service_name')} {service.get('service_version')}"
            cves = await enricher.search_by_keyword(keyword, max_results=5)

            for cve in cves:
                vulnerabilities.append({
                    "port": service.get("port"),
                    "protocol": service.get("protocol", "tcp"),
                    "service_name": service.get("service_name"),
                    "service_version": service.get("service_version"),
                    "vulnerability_type": "SERVICE_VULN",
                    "severity": cve.severity,
                    "title": cve.cve_id,
                    "description": cve.description[:500] if cve.description else None,
                    "recommendation": f"Vérifier si {service.get('service_name')} est affecté et mettre à jour",
                    "cve_ids": [cve.cve_id],
                    "cvss_score": cve.cvss_score,
                    "cvss_vector": cve.cvss_vector,
                    "references": cve.references
                })

    except Exception as e:
        logger.error(f"Erreur enrichissement CVE: {e}")
    finally:
        await enricher.close()

    return vulnerabilities
