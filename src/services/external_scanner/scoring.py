# backend/src/services/external_scanner/scoring.py
"""
Module de calcul du score d'exposition.

Calcule un score de 0 à 100 basé sur:
- Nombre et sévérité des vulnérabilités
- Ports sensibles exposés
- Configuration TLS
- Services à risque
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ScoringWeights:
    """Poids pour le calcul du score."""
    # Vulnérabilités par sévérité
    vuln_critical: int = 25
    vuln_high: int = 15
    vuln_medium: int = 8
    vuln_low: int = 3
    vuln_info: int = 1

    # Ports sensibles
    port_critical: int = 15  # Telnet, FTP, etc.
    port_high: int = 10  # RDP, SMB, etc.
    port_medium: int = 5  # Database ports

    # TLS
    tls_grade_penalty: dict = field(default_factory=lambda: {
        "A": 0,
        "B": 5,
        "C": 15,
        "D": 25,
        "F": 40
    })

    # Services à risque
    risky_service: int = 10


class ExposureScoring:
    """
    Calculateur de score d'exposition.

    Le score va de 0 (aucune exposition) à 100+ (exposition critique).
    Un score supérieur à 100 indique une exposition très critique.

    Exemple:
        scorer = ExposureScoring()
        result = scorer.calculate(
            vulnerabilities=[...],
            services=[...],
            tls_grade="B"
        )
        print(f"Score: {result.score}/100")
    """

    # Ports considérés comme critiques (à ne jamais exposer)
    CRITICAL_PORTS = {
        21,    # FTP
        23,    # Telnet
        69,    # TFTP
        111,   # RPC
        135,   # MSRPC
        137,   # NetBIOS
        138,   # NetBIOS
        139,   # NetBIOS
        445,   # SMB
        512,   # rexec
        513,   # rlogin
        514,   # rsh/syslog
        1433,  # MSSQL
        1521,  # Oracle
        2049,  # NFS
        5800,  # VNC HTTP
        5900,  # VNC
        6000,  # X11
    }

    # Ports à risque élevé
    HIGH_RISK_PORTS = {
        22,    # SSH (si exposé publiquement)
        25,    # SMTP
        53,    # DNS
        110,   # POP3
        143,   # IMAP
        161,   # SNMP
        389,   # LDAP
        636,   # LDAPS
        1723,  # PPTP VPN
        3306,  # MySQL
        3389,  # RDP
        5432,  # PostgreSQL
        5985,  # WinRM HTTP
        5986,  # WinRM HTTPS
        6379,  # Redis
        8080,  # HTTP Alt
        9200,  # Elasticsearch
        27017, # MongoDB
    }

    # Services à risque (versions anciennes, mal configurés)
    RISKY_SERVICES = [
        "telnet",
        "ftp",
        "rsh",
        "rlogin",
        "rexec",
        "finger",
        "tftp",
        "snmp",
    ]

    def __init__(self, weights: Optional[ScoringWeights] = None):
        """
        Initialise le calculateur de score.

        Args:
            weights: Poids personnalisés pour le calcul
        """
        self.weights = weights or ScoringWeights()

    def calculate(
        self,
        vulnerabilities: list[dict],
        services: list[dict],
        tls_grade: Optional[str] = None
    ) -> "ScoringResult":
        """
        Calcule le score d'exposition.

        Args:
            vulnerabilities: Liste des vulnérabilités détectées
            services: Liste des services exposés
            tls_grade: Grade TLS (A, B, C, D, F)

        Returns:
            ScoringResult avec le détail du score
        """
        result = ScoringResult()

        # 1. Score des vulnérabilités
        vuln_score = self._calculate_vuln_score(vulnerabilities, result)

        # 2. Score des ports exposés
        port_score = self._calculate_port_score(services, result)

        # 3. Score TLS
        tls_score = self._calculate_tls_score(tls_grade, result)

        # 4. Score des services à risque
        service_score = self._calculate_service_score(services, result)

        # Score total (plafonné à 100 pour l'affichage)
        raw_score = vuln_score + port_score + tls_score + service_score
        result.raw_score = raw_score
        result.score = min(100, raw_score)

        # Déterminer le niveau de risque
        result.risk_level = self._get_risk_level(result.score)

        # Compteurs
        result.total_vulnerabilities = len(vulnerabilities)
        result.total_services = len(services)

        logger.info(
            f"📊 Score d'exposition: {result.score}/100 "
            f"(raw: {result.raw_score}) - {result.risk_level}"
        )

        return result

    def _calculate_vuln_score(
        self,
        vulnerabilities: list[dict],
        result: "ScoringResult"
    ) -> int:
        """Calcule le score lié aux vulnérabilités."""
        score = 0

        for vuln in vulnerabilities:
            severity = vuln.get("severity", "INFO").upper()

            if severity == "CRITICAL":
                score += self.weights.vuln_critical
                result.nb_critical += 1
            elif severity == "HIGH":
                score += self.weights.vuln_high
                result.nb_high += 1
            elif severity == "MEDIUM":
                score += self.weights.vuln_medium
                result.nb_medium += 1
            elif severity == "LOW":
                score += self.weights.vuln_low
                result.nb_low += 1
            else:
                score += self.weights.vuln_info
                result.nb_info += 1

        result.vuln_score = score
        return score

    def _calculate_port_score(
        self,
        services: list[dict],
        result: "ScoringResult"
    ) -> int:
        """Calcule le score lié aux ports exposés."""
        score = 0

        for svc in services:
            port = svc.get("port")
            if not port:
                continue

            if port in self.CRITICAL_PORTS:
                score += self.weights.port_critical
                result.critical_ports.append(port)
            elif port in self.HIGH_RISK_PORTS:
                score += self.weights.port_high
                result.high_risk_ports.append(port)
            else:
                score += self.weights.port_medium
                result.other_ports.append(port)

        result.port_score = score
        result.nb_services_exposed = len(services)
        return score

    def _calculate_tls_score(
        self,
        tls_grade: Optional[str],
        result: "ScoringResult"
    ) -> int:
        """Calcule le score lié à la configuration TLS."""
        if not tls_grade:
            return 0

        result.tls_grade = tls_grade
        penalty = self.weights.tls_grade_penalty.get(tls_grade.upper(), 20)
        result.tls_score = penalty

        return penalty

    def _calculate_service_score(
        self,
        services: list[dict],
        result: "ScoringResult"
    ) -> int:
        """Calcule le score lié aux services à risque."""
        score = 0

        for svc in services:
            service_name = svc.get("service_name", "").lower()

            for risky in self.RISKY_SERVICES:
                if risky in service_name:
                    score += self.weights.risky_service
                    result.risky_services.append(service_name)
                    break

        result.service_score = score
        return score

    def _get_risk_level(self, score: int) -> str:
        """Détermine le niveau de risque basé sur le score."""
        if score >= 80:
            return "CRITICAL"
        elif score >= 60:
            return "HIGH"
        elif score >= 40:
            return "MEDIUM"
        elif score >= 20:
            return "LOW"
        else:
            return "INFO"


@dataclass
class ScoringResult:
    """Résultat du calcul de score."""
    # Score final
    score: int = 0
    raw_score: int = 0
    risk_level: str = "INFO"

    # Décomposition du score
    vuln_score: int = 0
    port_score: int = 0
    tls_score: int = 0
    service_score: int = 0

    # Compteurs vulnérabilités
    nb_critical: int = 0
    nb_high: int = 0
    nb_medium: int = 0
    nb_low: int = 0
    nb_info: int = 0
    total_vulnerabilities: int = 0

    # Compteurs services
    nb_services_exposed: int = 0
    total_services: int = 0

    # Détails
    critical_ports: list[int] = field(default_factory=list)
    high_risk_ports: list[int] = field(default_factory=list)
    other_ports: list[int] = field(default_factory=list)
    risky_services: list[str] = field(default_factory=list)
    tls_grade: Optional[str] = None

    def to_dict(self) -> dict:
        """Convertit le résultat en dictionnaire."""
        return {
            "exposure_score": self.score,
            "raw_score": self.raw_score,
            "risk_level": self.risk_level,
            "breakdown": {
                "vulnerabilities": self.vuln_score,
                "ports": self.port_score,
                "tls": self.tls_score,
                "services": self.service_score
            },
            "vulnerabilities": {
                "critical": self.nb_critical,
                "high": self.nb_high,
                "medium": self.nb_medium,
                "low": self.nb_low,
                "info": self.nb_info,
                "total": self.total_vulnerabilities
            },
            "services": {
                "exposed": self.nb_services_exposed,
                "critical_ports": self.critical_ports,
                "high_risk_ports": self.high_risk_ports,
                "risky_services": self.risky_services
            },
            "tls_grade": self.tls_grade
        }


def calculate_exposure_score(
    vulnerabilities: list[dict],
    services: list[dict],
    tls_grade: Optional[str] = None
) -> dict:
    """
    Fonction helper pour calculer le score d'exposition.

    Args:
        vulnerabilities: Liste des vulnérabilités
        services: Liste des services exposés
        tls_grade: Grade TLS

    Returns:
        Dictionnaire avec le résumé du score
    """
    scorer = ExposureScoring()
    result = scorer.calculate(
        vulnerabilities=vulnerabilities,
        services=services,
        tls_grade=tls_grade
    )
    return result.to_dict()
