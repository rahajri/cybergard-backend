# backend/src/services/external_scanner/engine.py
"""
Moteur d'orchestration du scan externe.

Coordonne les différentes étapes du scan:
1. Scan nmap (ports et services)
2. Audit TLS (si ports HTTPS détectés)
3. Enrichissement CVE
4. Calcul du score d'exposition
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional
from dataclasses import dataclass, field
from uuid import UUID

from .nmap_client import NmapClient, scan_services
from .tls_audit import TLSAuditor, scan_tls_vulnerabilities
from .cve_enrichment import CVEEnrichment, enrich_with_vulns
from .scoring import ExposureScoring, calculate_exposure_score

logger = logging.getLogger(__name__)


@dataclass
class ScanConfig:
    """Configuration du scan."""
    # Timeouts
    nmap_timeout: int = 300
    tls_timeout: int = 60
    cve_timeout: int = 30

    # Ports
    ports: Optional[str] = None  # None = ports courants
    scan_all_ports: bool = False

    # Features
    enable_tls_audit: bool = True
    enable_cve_enrichment: bool = True
    enable_vuln_scripts: bool = False  # Scripts NSE vulnérabilités

    # Limites
    max_cve_per_service: int = 10


@dataclass
class TLSDetails:
    """Détails complets de l'audit TLS."""
    # Protocoles supportés
    protocols: dict = field(default_factory=lambda: {
        "ssl2": False,
        "ssl3": False,
        "tls10": False,
        "tls11": False,
        "tls12": False,
        "tls13": False
    })

    # Certificat
    certificate: dict = field(default_factory=dict)
    # Structure: {
    #   "subject": str, "issuer": str, "serial_number": str,
    #   "not_before": str, "not_after": str,
    #   "is_expired": bool, "days_until_expiry": int,
    #   "is_self_signed": bool, "signature_algorithm": str,
    #   "public_key_algorithm": str, "public_key_size": int,
    #   "san_domains": []
    # }

    # Cipher suites
    ciphers: dict = field(default_factory=lambda: {
        "strong": [],
        "weak": []
    })

    # Grade global
    grade: Optional[str] = None

    # Erreur (si échec)
    error: Optional[str] = None


@dataclass
class InfraInfo:
    """Informations sur l'infrastructure détectée."""
    # Système d'exploitation
    os_name: Optional[str] = None  # Ex: "Linux 4.15 - 5.6", "Windows Server 2019"
    os_family: Optional[str] = None  # Ex: "Linux", "Windows", "FreeBSD"
    os_vendor: Optional[str] = None  # Ex: "Linux", "Microsoft", "Apple"
    os_version: Optional[str] = None  # Ex: "4.X", "2019", "10.15"
    os_accuracy: int = 0  # Pourcentage de confiance (0-100)
    os_type: Optional[str] = None  # Ex: "general purpose", "router", "WAP", "firewall"
    os_cpe: Optional[str] = None  # CPE pour identification précise

    # Réseau
    ip_address: Optional[str] = None
    hostname: Optional[str] = None

    # Technologie web détectée (headers, etc.)
    web_server: Optional[str] = None  # Ex: "nginx/1.18.0", "Apache/2.4.41"
    technologies: list[str] = field(default_factory=list)  # Ex: ["PHP", "WordPress", "jQuery"]


@dataclass
class ScanResult:
    """Résultat complet du scan."""
    # Identifiants
    target_id: Optional[UUID] = None
    scan_id: Optional[UUID] = None
    target_value: str = ""
    target_type: str = ""

    # Statut
    status: str = "PENDING"  # PENDING, RUNNING, SUCCESS, ERROR
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error_message: Optional[str] = None

    # Résultats
    services: list[dict] = field(default_factory=list)
    vulnerabilities: list[dict] = field(default_factory=list)

    # Informations infrastructure
    infra_info: Optional[InfraInfo] = None

    # Détails TLS complets
    tls_details: Optional[TLSDetails] = None

    # Score
    exposure_score: int = 0
    tls_grade: Optional[str] = None

    # Résumé
    summary: dict = field(default_factory=dict)

    # Données brutes du scan (pour stockage)
    scan_data: dict = field(default_factory=dict)

    # Commande nmap exécutée
    raw_command: Optional[str] = None

    # Durée
    scan_duration_seconds: float = 0.0


class ScanEngine:
    """
    Moteur principal du scan externe.

    Exemple:
        engine = ScanEngine()
        result = await engine.run_scan(
            target_type="DOMAIN",
            target_value="example.com"
        )
        print(f"Score: {result.exposure_score}")
        print(f"Vulnérabilités: {len(result.vulnerabilities)}")
    """

    def __init__(self, config: Optional[ScanConfig] = None):
        """
        Initialise le moteur de scan.

        Args:
            config: Configuration du scan
        """
        self.config = config or ScanConfig()
        self.nmap_client = NmapClient(timeout=self.config.nmap_timeout)
        self.tls_auditor = TLSAuditor(timeout=self.config.tls_timeout)
        self.cve_enricher = CVEEnrichment()
        self.scorer = ExposureScoring()

    async def run_scan(
        self,
        target_type: str,
        target_value: str,
        target_id: Optional[UUID] = None,
        scan_id: Optional[UUID] = None
    ) -> ScanResult:
        """
        Exécute un scan complet sur une cible.

        Args:
            target_type: Type de cible (DOMAIN, IP, SUBDOMAIN)
            target_value: Valeur de la cible
            target_id: ID de la cible (optionnel)
            scan_id: ID du scan (optionnel)

        Returns:
            ScanResult avec tous les résultats
        """
        result = ScanResult(
            target_id=target_id,
            scan_id=scan_id,
            target_type=target_type,
            target_value=target_value,
            status="RUNNING",
            started_at=datetime.now(timezone.utc)
        )

        logger.info(f"🚀 Démarrage scan: {target_type} -> {target_value}")

        try:
            # Étape 1: Scan nmap (ports, services, OS)
            logger.info("📡 Étape 1/4: Scan des ports, services et OS...")
            nmap_result = await self._scan_ports_and_os(target_type, target_value)
            result.services = nmap_result["services"]
            result.infra_info = nmap_result["infra_info"]
            result.raw_command = nmap_result.get("raw_command")
            logger.info(f"   ✅ {len(result.services)} services détectés")
            if result.infra_info and result.infra_info.os_name:
                logger.info(f"   ✅ OS détecté: {result.infra_info.os_name} ({result.infra_info.os_accuracy}% confiance)")

            # Étape 2: Audit TLS
            tls_vulnerabilities = []
            if self.config.enable_tls_audit:
                logger.info("🔐 Étape 2/4: Audit TLS...")
                tls_result = await self._audit_tls(target_value, result.services)
                tls_vulnerabilities = tls_result.get("vulnerabilities", [])
                result.tls_grade = tls_result.get("grade")
                result.tls_details = tls_result.get("tls_details")
                logger.info(f"   ✅ Grade TLS: {result.tls_grade}, {len(tls_vulnerabilities)} issues")

            # Étape 3: Enrichissement CVE
            cve_vulnerabilities = []
            if self.config.enable_cve_enrichment:
                logger.info("🔍 Étape 3/4: Enrichissement CVE...")
                cve_vulnerabilities = await self._enrich_cve(result.services)
                logger.info(f"   ✅ {len(cve_vulnerabilities)} CVE détectées")

            # Combiner les vulnérabilités
            all_vulnerabilities = []

            # Vulnérabilités des ports sensibles exposés
            port_vulnerabilities = self._check_exposed_ports(result.services)
            all_vulnerabilities.extend(port_vulnerabilities)

            # Vulnérabilités TLS
            all_vulnerabilities.extend(tls_vulnerabilities)

            # Vulnérabilités CVE
            all_vulnerabilities.extend(cve_vulnerabilities)

            result.vulnerabilities = all_vulnerabilities

            # Étape 4: Calcul du score
            logger.info("📊 Étape 4/4: Calcul du score d'exposition...")
            score_result = self.scorer.calculate(
                vulnerabilities=all_vulnerabilities,
                services=result.services,
                tls_grade=result.tls_grade
            )
            result.exposure_score = score_result.score

            # Générer le résumé
            result.summary = self._generate_summary(
                services=result.services,
                vulnerabilities=all_vulnerabilities,
                score_result=score_result,
                tls_grade=result.tls_grade,
                infra_info=result.infra_info
            )

            # Construire scan_data avec toutes les données brutes
            result.scan_data = self._build_scan_data(
                services=result.services,
                tls_details=result.tls_details,
                infra_info=result.infra_info,
                raw_command=result.raw_command
            )

            # Finaliser
            result.status = "SUCCESS"
            result.finished_at = datetime.now(timezone.utc)
            result.scan_duration_seconds = (
                result.finished_at - result.started_at
            ).total_seconds()

            logger.info(
                f"✅ Scan terminé: Score {result.exposure_score}/100, "
                f"{len(result.vulnerabilities)} vulnérabilités en "
                f"{result.scan_duration_seconds:.1f}s"
            )

        except Exception as e:
            logger.error(f"❌ Erreur scan: {e}")
            result.status = "ERROR"
            result.error_message = str(e)
            result.finished_at = datetime.now(timezone.utc)
            if result.started_at:
                result.scan_duration_seconds = (
                    result.finished_at - result.started_at
                ).total_seconds()

        return result

    async def _scan_ports_and_os(
        self,
        target_type: str,
        target_value: str
    ) -> dict:
        """
        Scan les ports avec nmap et détecte l'OS.

        Returns:
            Dict avec 'services' et 'infra_info'
        """
        # Exécuter en thread car nmap est synchrone
        loop = asyncio.get_event_loop()

        if self.config.scan_all_ports:
            nmap_result = await loop.run_in_executor(
                None,
                lambda: self.nmap_client.full_scan(target_value, detect_os=True)
            )
        elif self.config.ports:
            nmap_result = await loop.run_in_executor(
                None,
                lambda: self.nmap_client.scan_target(
                    target_value,
                    ports=self.config.ports,
                    arguments="-sV -T4 -O --osscan-guess"
                )
            )
        else:
            nmap_result = await loop.run_in_executor(
                None,
                lambda: self.nmap_client.quick_scan(target_value, detect_os=True)
            )

        # Convertir en liste de dictionnaires
        services = []
        web_server = None
        technologies = []

        for svc in nmap_result.services:
            if svc.state == "open":
                service_info = {
                    "port": svc.port,
                    "protocol": svc.protocol,
                    "service_name": svc.service_name,
                    "service_version": f"{svc.service_product or ''} {svc.service_version or ''}".strip() or None,
                    "service_product": svc.service_product,
                    "service_banner": svc.service_banner,
                    "cpe": svc.cpe
                }
                services.append(service_info)

                # Détecter le serveur web
                if svc.port in [80, 443, 8080, 8443] and svc.service_product:
                    web_server = f"{svc.service_product} {svc.service_version or ''}".strip()
                    if svc.service_product:
                        technologies.append(svc.service_product)

        # Construire les informations d'infrastructure
        infra_info = InfraInfo(
            ip_address=nmap_result.target_ip,
            hostname=nmap_result.hostname,
            web_server=web_server,
            technologies=list(set(technologies))
        )

        # Ajouter les infos OS si disponibles
        if nmap_result.os_info:
            infra_info.os_name = nmap_result.os_info.name
            infra_info.os_family = nmap_result.os_info.family
            infra_info.os_vendor = nmap_result.os_info.vendor
            infra_info.os_version = nmap_result.os_info.os_gen
            infra_info.os_accuracy = nmap_result.os_info.accuracy
            infra_info.os_type = nmap_result.os_info.os_type
            infra_info.os_cpe = nmap_result.os_info.cpe
        elif nmap_result.os_match:
            # Fallback sur os_match simple
            infra_info.os_name = nmap_result.os_match

        return {
            "services": services,
            "infra_info": infra_info,
            "raw_command": nmap_result.command_line
        }

    async def _audit_tls(
        self,
        target_value: str,
        services: list[dict]
    ) -> dict:
        """Audit TLS sur les ports HTTPS."""
        # Trouver les ports HTTPS
        tls_ports = []
        for svc in services:
            port = svc.get("port")
            service_name = svc.get("service_name", "").lower()
            if port in [443, 8443, 9443] or "https" in service_name or "ssl" in service_name:
                tls_ports.append(port)

        if not tls_ports:
            # Essayer le port 443 par défaut
            tls_ports = [443]

        vulnerabilities = []
        grade = None
        tls_details = TLSDetails()

        for port in tls_ports[:3]:  # Limiter à 3 ports
            try:
                # Exécuter en thread car sslyze est synchrone
                loop = asyncio.get_event_loop()
                tls_result = await loop.run_in_executor(
                    None,
                    lambda p=port: self.tls_auditor.audit(target_value, p)
                )

                if not tls_result.error:
                    grade = tls_result.grade
                    tls_details.grade = grade

                    # Stocker les protocoles supportés
                    tls_details.protocols = {
                        "ssl2": tls_result.supports_ssl2,
                        "ssl3": tls_result.supports_ssl3,
                        "tls10": tls_result.supports_tls10,
                        "tls11": tls_result.supports_tls11,
                        "tls12": tls_result.supports_tls12,
                        "tls13": tls_result.supports_tls13
                    }

                    # Stocker les ciphers
                    tls_details.ciphers = {
                        "strong": tls_result.strong_ciphers,
                        "weak": tls_result.weak_ciphers
                    }

                    # Stocker les infos du certificat
                    if tls_result.certificate:
                        cert = tls_result.certificate
                        tls_details.certificate = {
                            "subject": cert.subject,
                            "issuer": cert.issuer,
                            "serial_number": cert.serial_number,
                            "not_before": cert.not_before.isoformat() if cert.not_before else None,
                            "not_after": cert.not_after.isoformat() if cert.not_after else None,
                            "is_expired": cert.is_expired,
                            "days_until_expiry": cert.days_until_expiry,
                            "is_self_signed": cert.is_self_signed,
                            "signature_algorithm": cert.signature_algorithm,
                            "public_key_algorithm": cert.public_key_algorithm,
                            "public_key_size": cert.public_key_size,
                            "san_domains": cert.san_domains
                        }

                    for vuln in tls_result.vulnerabilities:
                        vulnerabilities.append({
                            "port": port,
                            "protocol": "tcp",
                            "service_name": "https",
                            "vulnerability_type": "TLS_WEAK",
                            "severity": vuln.severity,
                            "title": vuln.name,
                            "description": vuln.description,
                            "recommendation": vuln.recommendation,
                            "cve_ids": vuln.cve_ids,
                            "cvss_score": vuln.cvss_score
                        })
                else:
                    tls_details.error = tls_result.error

            except Exception as e:
                logger.warning(f"Erreur TLS port {port}: {e}")
                tls_details.error = str(e)

        return {
            "grade": grade,
            "vulnerabilities": vulnerabilities,
            "tls_details": tls_details
        }

    async def _enrich_cve(self, services: list[dict]) -> list[dict]:
        """Enrichit les services avec les CVE."""
        all_vulnerabilities = []

        for svc in services:
            # Seulement si on a une version
            if not svc.get("service_version") and not svc.get("cpe"):
                continue

            try:
                vulns = await enrich_with_vulns(svc)
                # Limiter le nombre de CVE par service
                all_vulnerabilities.extend(
                    vulns[:self.config.max_cve_per_service]
                )
            except Exception as e:
                logger.warning(f"Erreur enrichissement CVE pour {svc}: {e}")

        return all_vulnerabilities

    def _check_exposed_ports(self, services: list[dict]) -> list[dict]:
        """Vérifie les ports sensibles exposés."""
        vulnerabilities = []

        # Ports critiques
        critical_ports = {
            21: ("FTP", "Le service FTP est obsolète et non sécurisé"),
            23: ("Telnet", "Telnet transmet les données en clair"),
            139: ("NetBIOS", "NetBIOS expose des informations sensibles"),
            445: ("SMB", "SMB est souvent ciblé par des attaques"),
            1433: ("MSSQL", "Base de données exposée publiquement"),
            3389: ("RDP", "RDP est souvent ciblé par des attaques bruteforce"),
            5900: ("VNC", "VNC expose un accès bureau à distance"),
        }

        for svc in services:
            port = svc.get("port")
            if port in critical_ports:
                name, desc = critical_ports[port]
                vulnerabilities.append({
                    "port": port,
                    "protocol": svc.get("protocol", "tcp"),
                    "service_name": svc.get("service_name", name.lower()),
                    "vulnerability_type": "PORT_EXPOSED",
                    "severity": "HIGH",
                    "title": f"Port sensible exposé: {port}/{name}",
                    "description": desc,
                    "recommendation": f"Fermer le port {port} ou le protéger par un VPN/firewall",
                    "cve_ids": [],
                    "cvss_score": 7.5
                })

        return vulnerabilities

    def _build_scan_data(
        self,
        services: list[dict],
        tls_details: Optional[TLSDetails],
        infra_info: Optional[InfraInfo],
        raw_command: Optional[str]
    ) -> dict:
        """
        Construit le dictionnaire scan_data avec toutes les données brutes.

        Ce dictionnaire sera stocké en JSON et servira pour l'affichage détaillé.
        """
        scan_data = {
            "services": services,
            "raw_command": raw_command
        }

        # Ajouter les détails TLS
        if tls_details:
            scan_data["tls_details"] = {
                "protocols": tls_details.protocols,
                "certificate": tls_details.certificate,
                "ciphers": tls_details.ciphers,
                "grade": tls_details.grade,
                "error": tls_details.error
            }

        # Ajouter les infos d'infrastructure
        if infra_info:
            scan_data["infrastructure"] = {
                "os_name": infra_info.os_name,
                "os_family": infra_info.os_family,
                "os_vendor": infra_info.os_vendor,
                "os_version": infra_info.os_version,
                "os_accuracy": infra_info.os_accuracy,
                "os_type": infra_info.os_type,
                "os_cpe": infra_info.os_cpe,
                "ip_address": infra_info.ip_address,
                "hostname": infra_info.hostname,
                "web_server": infra_info.web_server,
                "technologies": infra_info.technologies
            }

        return scan_data

    def _generate_summary(
        self,
        services: list[dict],
        vulnerabilities: list[dict],
        score_result,
        tls_grade: Optional[str],
        infra_info: Optional[InfraInfo] = None
    ) -> dict:
        """Génère le résumé du scan."""
        # Compter par sévérité
        severity_counts = {
            "CRITICAL": 0,
            "HIGH": 0,
            "MEDIUM": 0,
            "LOW": 0,
            "INFO": 0
        }

        for vuln in vulnerabilities:
            severity = vuln.get("severity", "INFO").upper()
            if severity in severity_counts:
                severity_counts[severity] += 1

        summary = {
            "nb_services_exposed": len(services),
            "nb_vuln_critical": severity_counts["CRITICAL"],
            "nb_vuln_high": severity_counts["HIGH"],
            "nb_vuln_medium": severity_counts["MEDIUM"],
            "nb_vuln_low": severity_counts["LOW"],
            "nb_vuln_info": severity_counts["INFO"],
            "nb_vuln_total": len(vulnerabilities),
            "exposure_score": score_result.score,
            "risk_level": score_result.risk_level,
            "tls_grade": tls_grade,
            "ports_scanned": len(services),
            "scan_duration_seconds": 0  # Sera mis à jour
        }

        # Ajouter les informations d'infrastructure
        if infra_info:
            summary["infrastructure"] = {
                "os_name": infra_info.os_name,
                "os_family": infra_info.os_family,
                "os_vendor": infra_info.os_vendor,
                "os_version": infra_info.os_version,
                "os_accuracy": infra_info.os_accuracy,
                "os_type": infra_info.os_type,
                "os_cpe": infra_info.os_cpe,
                "ip_address": infra_info.ip_address,
                "hostname": infra_info.hostname,
                "web_server": infra_info.web_server,
                "technologies": infra_info.technologies
            }

        return summary


async def run_external_scan(
    target_type: str,
    target_value: str,
    target_id: Optional[UUID] = None,
    scan_id: Optional[UUID] = None,
    config: Optional[ScanConfig] = None
) -> ScanResult:
    """
    Fonction helper pour exécuter un scan externe.

    Args:
        target_type: Type de cible
        target_value: Valeur de la cible
        target_id: ID de la cible
        scan_id: ID du scan
        config: Configuration du scan

    Returns:
        Résultat du scan
    """
    engine = ScanEngine(config)
    return await engine.run_scan(
        target_type=target_type,
        target_value=target_value,
        target_id=target_id,
        scan_id=scan_id
    )
