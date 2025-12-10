# backend/src/services/external_scanner/tls_audit.py
"""
Module d'audit TLS/SSL.

Utilise sslyze pour analyser la configuration TLS d'un serveur:
- Versions de protocoles supportées
- Cipher suites
- Certificat (validité, chaîne, etc.)
- Vulnérabilités connues (Heartbleed, ROBOT, etc.)
"""

import logging
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime

try:
    from sslyze import (
        ServerNetworkLocation,
        ServerNetworkConfiguration,
        Scanner,
        ServerScanRequest,
        ScanCommand
    )
    from sslyze.errors import ServerHostnameCouldNotBeResolved
    from sslyze.server_connectivity import check_connectivity_to_server
    SSLYZE_AVAILABLE = True
except ImportError as e:
    SSLYZE_AVAILABLE = False
    import logging
    logging.getLogger(__name__).warning(f"sslyze import failed: {e}")

logger = logging.getLogger(__name__)


@dataclass
class CertificateInfo:
    """Information sur le certificat SSL/TLS."""
    subject: str
    issuer: str
    serial_number: str
    not_before: Optional[datetime] = None
    not_after: Optional[datetime] = None
    is_expired: bool = False
    days_until_expiry: Optional[int] = None
    is_self_signed: bool = False
    signature_algorithm: Optional[str] = None
    public_key_algorithm: Optional[str] = None
    public_key_size: Optional[int] = None
    san_domains: list[str] = field(default_factory=list)


@dataclass
class TLSVulnerability:
    """Vulnérabilité TLS détectée."""
    name: str
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW, INFO
    description: str
    recommendation: str
    cve_ids: list[str] = field(default_factory=list)
    cvss_score: Optional[float] = None


@dataclass
class TLSAuditResult:
    """Résultat complet de l'audit TLS."""
    target: str
    port: int = 443

    # Protocoles supportés
    supports_ssl2: bool = False
    supports_ssl3: bool = False
    supports_tls10: bool = False
    supports_tls11: bool = False
    supports_tls12: bool = False
    supports_tls13: bool = False

    # Grade global (A, B, C, D, F)
    grade: str = "?"

    # Certificat
    certificate: Optional[CertificateInfo] = None
    certificate_chain_valid: bool = True

    # Cipher suites
    weak_ciphers: list[str] = field(default_factory=list)
    strong_ciphers: list[str] = field(default_factory=list)

    # Vulnérabilités
    vulnerabilities: list[TLSVulnerability] = field(default_factory=list)

    # Métadonnées
    scan_time: float = 0.0
    error: Optional[str] = None


class TLSAuditor:
    """
    Auditeur TLS/SSL utilisant sslyze.

    Exemple:
        auditor = TLSAuditor()
        result = auditor.audit("example.com", 443)
        print(f"Grade: {result.grade}")
        for vuln in result.vulnerabilities:
            print(f"- {vuln.name}: {vuln.severity}")
    """

    def __init__(self, timeout: int = 60):
        """
        Initialise l'auditeur TLS.

        Args:
            timeout: Timeout en secondes
        """
        self.timeout = timeout

        if not SSLYZE_AVAILABLE:
            logger.warning("⚠️ sslyze non disponible - audit TLS limité")

    def audit(self, target: str, port: int = 443) -> TLSAuditResult:
        """
        Effectue un audit TLS complet.

        Args:
            target: Domaine ou IP à auditer
            port: Port TLS (défaut 443)

        Returns:
            TLSAuditResult avec toutes les informations
        """
        result = TLSAuditResult(target=target, port=port)
        start_time = datetime.now()

        if not SSLYZE_AVAILABLE:
            result.error = "sslyze non installé"
            return result

        try:
            # Créer la location et configuration du serveur (sslyze 6.x API)
            server_location = ServerNetworkLocation(
                hostname=target,
                port=port
            )
            # Utiliser la méthode de classe pour créer la config par défaut
            network_config = ServerNetworkConfiguration.default_for_server_location(server_location)

            # Tester la connectivité avec la nouvelle API sslyze 6.x
            # Dans sslyze 6.x, check_connectivity_to_server retourne un ServerTlsProbingResult
            # directement si la connexion réussit, ou lève une exception sinon
            logger.info(f"🔐 Audit TLS: {target}:{port}")

            try:
                server_probing_result = check_connectivity_to_server(
                    server_location=server_location,
                    network_configuration=network_config
                )
                # Si on arrive ici, la connexion a réussi
                logger.info(f"✅ Connexion TLS réussie: TLS {server_probing_result.highest_tls_version_supported}")
            except ServerHostnameCouldNotBeResolved as e:
                logger.error(f"❌ Résolution DNS échouée: {e}")
                result.error = f"Résolution DNS échouée: {e}"
                return result
            except Exception as e:
                logger.error(f"❌ Connexion TLS échouée: {e}")
                result.error = f"Connexion échouée: {e}"
                return result

            # Préparer le scan avec le résultat de connectivité
            scanner = Scanner()
            scan_request = ServerScanRequest(
                server_location=server_location,
                scan_commands={
                    ScanCommand.SSL_2_0_CIPHER_SUITES,
                    ScanCommand.SSL_3_0_CIPHER_SUITES,
                    ScanCommand.TLS_1_0_CIPHER_SUITES,
                    ScanCommand.TLS_1_1_CIPHER_SUITES,
                    ScanCommand.TLS_1_2_CIPHER_SUITES,
                    ScanCommand.TLS_1_3_CIPHER_SUITES,
                    ScanCommand.CERTIFICATE_INFO,
                    ScanCommand.HEARTBLEED,
                    ScanCommand.ROBOT,
                    ScanCommand.TLS_COMPRESSION,
                    ScanCommand.TLS_FALLBACK_SCSV,
                    ScanCommand.SESSION_RENEGOTIATION,
                }
            )

            # Exécuter le scan
            scanner.queue_scans([scan_request])

            # Récupérer les résultats
            for scan_result in scanner.get_results():
                # Protocoles supportés
                self._parse_cipher_results(scan_result, result)

                # Certificat
                self._parse_certificate(scan_result, result)

                # Vulnérabilités
                self._check_vulnerabilities(scan_result, result)

            # Calculer le grade
            result.grade = self._calculate_grade(result)

            # Temps de scan
            result.scan_time = (datetime.now() - start_time).total_seconds()

            logger.info(f"✅ Audit TLS terminé: Grade {result.grade}")

        except Exception as e:
            logger.error(f"❌ Erreur audit TLS: {e}")
            result.error = str(e)

        return result

    def _parse_cipher_results(self, scan_result, result: TLSAuditResult):
        """Parse les résultats des cipher suites (sslyze 6.x API)."""
        try:
            # Accéder aux résultats de scan (nouvelle API)
            scan_commands_results = scan_result.scan_result

            # SSL 2.0
            ssl2 = scan_commands_results.ssl_2_0_cipher_suites
            if ssl2 and ssl2.status.name == "COMPLETED" and ssl2.result:
                if ssl2.result.accepted_cipher_suites:
                    result.supports_ssl2 = True
                    for cipher in ssl2.result.accepted_cipher_suites:
                        result.weak_ciphers.append(f"SSL2:{cipher.cipher_suite.name}")

            # SSL 3.0
            ssl3 = scan_commands_results.ssl_3_0_cipher_suites
            if ssl3 and ssl3.status.name == "COMPLETED" and ssl3.result:
                if ssl3.result.accepted_cipher_suites:
                    result.supports_ssl3 = True
                    for cipher in ssl3.result.accepted_cipher_suites:
                        result.weak_ciphers.append(f"SSL3:{cipher.cipher_suite.name}")

            # TLS 1.0
            tls10 = scan_commands_results.tls_1_0_cipher_suites
            if tls10 and tls10.status.name == "COMPLETED" and tls10.result:
                if tls10.result.accepted_cipher_suites:
                    result.supports_tls10 = True

            # TLS 1.1
            tls11 = scan_commands_results.tls_1_1_cipher_suites
            if tls11 and tls11.status.name == "COMPLETED" and tls11.result:
                if tls11.result.accepted_cipher_suites:
                    result.supports_tls11 = True

            # TLS 1.2
            tls12 = scan_commands_results.tls_1_2_cipher_suites
            if tls12 and tls12.status.name == "COMPLETED" and tls12.result:
                if tls12.result.accepted_cipher_suites:
                    result.supports_tls12 = True
                    for cipher in tls12.result.accepted_cipher_suites:
                        name = cipher.cipher_suite.name
                        if self._is_weak_cipher(name):
                            result.weak_ciphers.append(f"TLS1.2:{name}")
                        else:
                            result.strong_ciphers.append(f"TLS1.2:{name}")

            # TLS 1.3
            tls13 = scan_commands_results.tls_1_3_cipher_suites
            if tls13 and tls13.status.name == "COMPLETED" and tls13.result:
                if tls13.result.accepted_cipher_suites:
                    result.supports_tls13 = True
                    for cipher in tls13.result.accepted_cipher_suites:
                        result.strong_ciphers.append(f"TLS1.3:{cipher.cipher_suite.name}")

        except Exception as e:
            logger.warning(f"Erreur parsing ciphers: {e}")

    def _parse_certificate(self, scan_result, result: TLSAuditResult):
        """Parse les informations du certificat (sslyze 6.x API)."""
        try:
            scan_commands_results = scan_result.scan_result
            cert_info = scan_commands_results.certificate_info

            if not cert_info or cert_info.status.name != "COMPLETED" or not cert_info.result:
                return

            deployment = cert_info.result.certificate_deployments[0]
            cert = deployment.received_certificate_chain[0]

            result.certificate = CertificateInfo(
                subject=cert.subject.rfc4514_string,
                issuer=cert.issuer.rfc4514_string,
                serial_number=str(cert.serial_number),
                not_before=cert.not_valid_before_utc,
                not_after=cert.not_valid_after_utc,
                signature_algorithm=cert.signature_algorithm_oid._name if hasattr(cert.signature_algorithm_oid, '_name') else str(cert.signature_algorithm_oid),
            )

            # Vérifier expiration
            from datetime import timezone
            now = datetime.now(timezone.utc)
            if cert.not_valid_after_utc:
                result.certificate.days_until_expiry = (cert.not_valid_after_utc - now).days
                result.certificate.is_expired = now > cert.not_valid_after_utc

            # Self-signed
            result.certificate.is_self_signed = cert.subject == cert.issuer

            # SAN (Subject Alternative Names)
            try:
                from cryptography import x509
                san_ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
                if san_ext:
                    result.certificate.san_domains = [str(name.value) for name in san_ext.value]
            except Exception:
                pass

            # Chaîne de validation
            result.certificate_chain_valid = deployment.verified_certificate_chain is not None

        except Exception as e:
            logger.warning(f"Erreur parsing certificat: {e}")

    def _check_vulnerabilities(self, scan_result, result: TLSAuditResult):
        """Vérifie les vulnérabilités connues (sslyze 6.x API)."""
        try:
            scan_commands_results = scan_result.scan_result

            # Heartbleed
            heartbleed = scan_commands_results.heartbleed
            if heartbleed and heartbleed.status.name == "COMPLETED" and heartbleed.result:
                if heartbleed.result.is_vulnerable_to_heartbleed:
                    result.vulnerabilities.append(TLSVulnerability(
                        name="Heartbleed",
                        severity="CRITICAL",
                        description="Le serveur est vulnérable à Heartbleed (CVE-2014-0160)",
                        recommendation="Mettre à jour OpenSSL immédiatement",
                        cve_ids=["CVE-2014-0160"],
                        cvss_score=9.8
                    ))

            # ROBOT
            robot = scan_commands_results.robot
            if robot and robot.status.name == "COMPLETED" and robot.result:
                robot_result = robot.result.robot_result
                if "VULNERABLE" in str(robot_result):
                    result.vulnerabilities.append(TLSVulnerability(
                        name="ROBOT Attack",
                        severity="HIGH",
                        description="Le serveur est vulnérable à l'attaque ROBOT",
                        recommendation="Désactiver les cipher suites RSA",
                        cve_ids=["CVE-2017-13099"],
                        cvss_score=7.5
                    ))

            # TLS Compression (CRIME)
            compression = scan_commands_results.tls_compression
            if compression and compression.status.name == "COMPLETED" and compression.result:
                if compression.result.supports_compression:
                    result.vulnerabilities.append(TLSVulnerability(
                        name="TLS Compression (CRIME)",
                        severity="MEDIUM",
                        description="La compression TLS est activée, vulnérable à CRIME",
                        recommendation="Désactiver la compression TLS",
                        cve_ids=["CVE-2012-4929"],
                        cvss_score=5.9
                    ))

            # Protocoles obsolètes
            if result.supports_ssl2:
                result.vulnerabilities.append(TLSVulnerability(
                    name="SSL 2.0 Enabled",
                    severity="CRITICAL",
                    description="SSL 2.0 est un protocole obsolète et non sécurisé",
                    recommendation="Désactiver SSL 2.0",
                    cvss_score=9.0
                ))

            if result.supports_ssl3:
                result.vulnerabilities.append(TLSVulnerability(
                    name="SSL 3.0 Enabled (POODLE)",
                    severity="HIGH",
                    description="SSL 3.0 est vulnérable à POODLE",
                    recommendation="Désactiver SSL 3.0",
                    cve_ids=["CVE-2014-3566"],
                    cvss_score=7.5
                ))

            if result.supports_tls10:
                result.vulnerabilities.append(TLSVulnerability(
                    name="TLS 1.0 Enabled",
                    severity="MEDIUM",
                    description="TLS 1.0 est obsolète et ne devrait plus être utilisé",
                    recommendation="Migrer vers TLS 1.2 ou 1.3",
                    cvss_score=5.0
                ))

            if result.supports_tls11:
                result.vulnerabilities.append(TLSVulnerability(
                    name="TLS 1.1 Enabled",
                    severity="LOW",
                    description="TLS 1.1 est obsolète",
                    recommendation="Migrer vers TLS 1.2 ou 1.3",
                    cvss_score=3.0
                ))

            # Certificat expiré
            if result.certificate and result.certificate.is_expired:
                result.vulnerabilities.append(TLSVulnerability(
                    name="Expired Certificate",
                    severity="HIGH",
                    description="Le certificat SSL/TLS est expiré",
                    recommendation="Renouveler le certificat immédiatement",
                    cvss_score=7.0
                ))

            # Certificat auto-signé
            if result.certificate and result.certificate.is_self_signed:
                result.vulnerabilities.append(TLSVulnerability(
                    name="Self-Signed Certificate",
                    severity="MEDIUM",
                    description="Le certificat est auto-signé",
                    recommendation="Utiliser un certificat signé par une CA reconnue",
                    cvss_score=5.0
                ))

            # Weak ciphers
            if result.weak_ciphers:
                result.vulnerabilities.append(TLSVulnerability(
                    name="Weak Cipher Suites",
                    severity="MEDIUM",
                    description=f"{len(result.weak_ciphers)} cipher suites faibles détectées",
                    recommendation="Désactiver les ciphers faibles et utiliser uniquement des ciphers modernes",
                    cvss_score=5.5
                ))

        except Exception as e:
            logger.warning(f"Erreur vérification vulnérabilités: {e}")

    def _is_weak_cipher(self, cipher_name: str) -> bool:
        """Vérifie si un cipher est considéré comme faible."""
        weak_patterns = [
            "NULL", "EXPORT", "DES", "RC4", "MD5",
            "anon", "ADH", "AECDH"
        ]
        return any(pattern in cipher_name.upper() for pattern in weak_patterns)

    def _calculate_grade(self, result: TLSAuditResult) -> str:
        """Calcule le grade TLS (A-F)."""
        score = 100

        # Pénalités protocoles
        if result.supports_ssl2:
            score -= 50
        if result.supports_ssl3:
            score -= 40
        if result.supports_tls10:
            score -= 20
        if result.supports_tls11:
            score -= 10

        # Bonus TLS 1.3
        if result.supports_tls13:
            score += 10

        # Pénalités vulnérabilités
        for vuln in result.vulnerabilities:
            if vuln.severity == "CRITICAL":
                score -= 40
            elif vuln.severity == "HIGH":
                score -= 25
            elif vuln.severity == "MEDIUM":
                score -= 15
            elif vuln.severity == "LOW":
                score -= 5

        # Pénalité weak ciphers
        score -= len(result.weak_ciphers) * 2

        # Certificat
        if result.certificate:
            if result.certificate.is_expired:
                score -= 30
            if result.certificate.is_self_signed:
                score -= 20

        # Calculer le grade
        if score >= 90:
            return "A"
        elif score >= 80:
            return "B"
        elif score >= 65:
            return "C"
        elif score >= 50:
            return "D"
        else:
            return "F"


def scan_tls_vulnerabilities(
    target_type: str,
    target_value: str,
    services: list[dict]
) -> list[dict]:
    """
    Fonction helper pour scanner les vulnérabilités TLS.

    Args:
        target_type: Type de cible
        target_value: Valeur de la cible
        services: Liste des services détectés par nmap

    Returns:
        Liste de vulnérabilités TLS détectées
    """
    auditor = TLSAuditor()
    vulnerabilities = []

    # Trouver les ports HTTPS
    tls_ports = [443, 8443, 9443]
    ports_to_scan = []

    for svc in services:
        if svc.get("port") in tls_ports or "https" in svc.get("service_name", "").lower():
            ports_to_scan.append(svc.get("port", 443))

    # Scanner chaque port TLS
    for port in set(ports_to_scan) or [443]:
        result = auditor.audit(target_value, port)

        for vuln in result.vulnerabilities:
            vulnerabilities.append({
                "port": port,
                "protocol": "tcp",
                "service_name": "https",
                "service_version": None,
                "vulnerability_type": "TLS_WEAK",
                "severity": vuln.severity,
                "title": vuln.name,
                "description": vuln.description,
                "recommendation": vuln.recommendation,
                "cve_ids": vuln.cve_ids,
                "cvss_score": vuln.cvss_score,
                "tls_grade": result.grade
            })

    return vulnerabilities
