# backend/src/services/external_scanner/nmap_client.py
"""
Client Nmap pour le scan de ports et services.

Utilise python-nmap comme wrapper autour de nmap.
Fournit des méthodes pour:
- Scan de ports TCP/UDP
- Détection de services et versions
- Détection de vulnérabilités (scripts NSE)
"""

import nmap
import logging
from typing import Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ServiceInfo:
    """Information sur un service détecté."""
    port: int
    protocol: str  # tcp, udp
    state: str  # open, closed, filtered
    service_name: str
    service_version: Optional[str] = None
    service_product: Optional[str] = None
    service_banner: Optional[str] = None
    cpe: Optional[str] = None  # Common Platform Enumeration


@dataclass
class OSInfo:
    """Information sur le système d'exploitation détecté."""
    name: Optional[str] = None  # Ex: "Linux 4.15 - 5.6"
    accuracy: int = 0  # Pourcentage de confiance (0-100)
    family: Optional[str] = None  # Ex: "Linux", "Windows", "FreeBSD"
    vendor: Optional[str] = None  # Ex: "Linux", "Microsoft", "Apple"
    os_gen: Optional[str] = None  # Ex: "4.X", "2019"
    os_type: Optional[str] = None  # Ex: "general purpose", "router", "WAP"
    cpe: Optional[str] = None  # Ex: "cpe:/o:linux:linux_kernel"


@dataclass
class NmapScanResult:
    """Résultat d'un scan nmap."""
    target: str
    target_ip: Optional[str] = None
    hostname: Optional[str] = None
    state: str = "unknown"  # up, down
    services: list[ServiceInfo] = field(default_factory=list)
    os_match: Optional[str] = None
    os_info: Optional[OSInfo] = None  # Informations OS détaillées
    os_matches: list[OSInfo] = field(default_factory=list)  # Tous les OS potentiels
    scan_time: float = 0.0
    command_line: Optional[str] = None
    error: Optional[str] = None


class NmapClient:
    """
    Client wrapper pour nmap.

    Exemple d'utilisation:
        client = NmapClient(timeout=300)
        result = client.scan_target("example.com", ports="1-1000")
        for service in result.services:
            print(f"{service.port}/{service.protocol}: {service.service_name}")
    """

    # Ports les plus couramment exposés et sensibles
    COMMON_PORTS = "21,22,23,25,53,80,110,111,135,139,143,443,445,993,995,1723,3306,3389,5432,5900,8080,8443"

    # Ports web
    WEB_PORTS = "80,443,8080,8443,8000,8888,9000,9443"

    # Top 1000 ports (par défaut nmap)
    TOP_1000 = None  # nmap utilise son propre top 1000

    def __init__(
        self,
        timeout: int = 300,
        max_retries: int = 2,
        arguments: str = "-sV"
    ):
        """
        Initialise le client nmap.

        Args:
            timeout: Timeout en secondes pour le scan
            max_retries: Nombre de tentatives en cas d'échec
            arguments: Arguments nmap par défaut
        """
        self.timeout = timeout
        self.max_retries = max_retries
        self.default_arguments = arguments
        self._scanner = nmap.PortScanner()

    def scan_target(
        self,
        target: str,
        ports: Optional[str] = None,
        arguments: Optional[str] = None,
        sudo: bool = False
    ) -> NmapScanResult:
        """
        Scan une cible avec nmap.

        Args:
            target: Cible (domaine, IP, ou range CIDR)
            ports: Ports à scanner (ex: "22,80,443" ou "1-1000")
            arguments: Arguments nmap additionnels
            sudo: Utiliser sudo pour scans SYN (nécessite privileges)

        Returns:
            NmapScanResult avec les services détectés
        """
        result = NmapScanResult(target=target)

        # Construire les arguments
        args = arguments or self.default_arguments

        # Ajouter timeout
        args += f" --host-timeout {self.timeout}s"

        # Ports par défaut si non spécifiés
        port_arg = f"-p {ports}" if ports else ""

        logger.info(f"🔍 Scan nmap: {target} {port_arg} {args}")

        try:
            # Exécuter le scan
            self._scanner.scan(
                hosts=target,
                ports=ports,
                arguments=args,
                sudo=sudo,
                timeout=self.timeout
            )

            # Récupérer la commande exécutée
            result.command_line = self._scanner.command_line()

            # Parser les résultats
            if target in self._scanner.all_hosts():
                host_info = self._scanner[target]

                # État de l'hôte
                result.state = host_info.state()

                # Hostname
                if "hostnames" in host_info and host_info["hostnames"]:
                    result.hostname = host_info["hostnames"][0].get("name")

                # Adresse IP
                if "addresses" in host_info:
                    result.target_ip = host_info["addresses"].get("ipv4")

                # Services TCP
                if "tcp" in host_info:
                    for port, info in host_info["tcp"].items():
                        service = ServiceInfo(
                            port=port,
                            protocol="tcp",
                            state=info.get("state", "unknown"),
                            service_name=info.get("name", "unknown"),
                            service_version=info.get("version"),
                            service_product=info.get("product"),
                            service_banner=info.get("extrainfo"),
                            cpe=info.get("cpe") if info.get("cpe") else None
                        )
                        result.services.append(service)

                # Services UDP (si scannés)
                if "udp" in host_info:
                    for port, info in host_info["udp"].items():
                        service = ServiceInfo(
                            port=port,
                            protocol="udp",
                            state=info.get("state", "unknown"),
                            service_name=info.get("name", "unknown"),
                            service_version=info.get("version"),
                            service_product=info.get("product"),
                            service_banner=info.get("extrainfo"),
                            cpe=info.get("cpe") if info.get("cpe") else None
                        )
                        result.services.append(service)

                # OS Detection (si disponible)
                if "osmatch" in host_info and host_info["osmatch"]:
                    result.os_match = host_info["osmatch"][0].get("name")

                    # Parser tous les OS possibles
                    for os_match in host_info["osmatch"]:
                        os_classes = os_match.get("osclass", [])
                        os_class = os_classes[0] if os_classes else {}

                        os_info = OSInfo(
                            name=os_match.get("name"),
                            accuracy=int(os_match.get("accuracy", 0)),
                            family=os_class.get("osfamily"),
                            vendor=os_class.get("vendor"),
                            os_gen=os_class.get("osgen"),
                            os_type=os_class.get("type"),
                            cpe=os_class.get("cpe", [None])[0] if os_class.get("cpe") else None
                        )
                        result.os_matches.append(os_info)

                    # Prendre le meilleur match comme OS principal
                    if result.os_matches:
                        result.os_info = result.os_matches[0]

            # Temps de scan
            result.scan_time = float(self._scanner.scanstats().get("elapsed", 0))

            logger.info(
                f"✅ Scan terminé: {len(result.services)} services détectés "
                f"en {result.scan_time:.1f}s"
            )

        except nmap.PortScannerError as e:
            logger.error(f"❌ Erreur nmap: {e}")
            result.error = str(e)
        except Exception as e:
            logger.error(f"❌ Erreur inattendue: {e}")
            result.error = str(e)

        return result

    def quick_scan(self, target: str, detect_os: bool = True) -> NmapScanResult:
        """
        Scan rapide des ports les plus courants.

        Args:
            target: Cible à scanner
            detect_os: Activer la détection d'OS (nécessite privilèges root/capabilities)

        Returns:
            Résultat du scan
        """
        # -sV: Version detection
        # -O: OS detection (nécessite root/capabilities)
        # -T4: Timing agressif
        args = "-sV -T4"
        if detect_os:
            args += " -O --osscan-guess"  # OS detection avec devinette si incertain

        result = self.scan_target(
            target=target,
            ports=self.COMMON_PORTS,
            arguments=args
        )

        # Si erreur liée aux privilèges root pour OS detection, retry sans -O
        if result.error and "root privileges" in result.error.lower():
            logger.warning("⚠️ OS detection requires root privileges, retrying without -O")
            result = self.scan_target(
                target=target,
                ports=self.COMMON_PORTS,
                arguments="-sV -T4"  # Sans -O
            )
            if not result.error:
                result.os_match = "OS detection disabled (requires root)"

        return result

    def web_scan(self, target: str) -> NmapScanResult:
        """
        Scan ciblé sur les ports web.

        Args:
            target: Cible à scanner

        Returns:
            Résultat du scan
        """
        return self.scan_target(
            target=target,
            ports=self.WEB_PORTS,
            arguments="-sV -T4 --script=http-title,http-headers"
        )

    def full_scan(self, target: str, detect_os: bool = True) -> NmapScanResult:
        """
        Scan complet (top 1000 ports + version + OS detection).

        Args:
            target: Cible à scanner
            detect_os: Activer la détection d'OS (nécessite privilèges root/capabilities)

        Returns:
            Résultat du scan
        """
        # -sV: Version detection
        # -sC: Scripts par défaut
        # -O: OS detection (nécessite root/capabilities)
        # -T4: Timing agressif
        args = "-sV -sC -T4"
        if detect_os:
            args += " -O --osscan-guess"

        result = self.scan_target(
            target=target,
            ports=None,  # Top 1000 par défaut
            arguments=args
        )

        # Si erreur liée aux privilèges root pour OS detection, retry sans -O
        if result.error and "root privileges" in result.error.lower():
            logger.warning("⚠️ OS detection requires root privileges, retrying without -O")
            result = self.scan_target(
                target=target,
                ports=None,
                arguments="-sV -sC -T4"  # Sans -O
            )
            if not result.error:
                result.os_match = "OS detection disabled (requires root)"

        return result

    def vuln_scan(self, target: str, ports: Optional[str] = None) -> NmapScanResult:
        """
        Scan avec scripts de vulnérabilité NSE.

        Args:
            target: Cible à scanner
            ports: Ports spécifiques (optionnel)

        Returns:
            Résultat du scan avec vulnérabilités détectées
        """
        return self.scan_target(
            target=target,
            ports=ports or self.COMMON_PORTS,
            arguments="-sV --script=vuln -T4"
        )


def scan_services(target_type: str, target_value: str) -> list[dict]:
    """
    Fonction helper pour scanner les services d'une cible.

    Args:
        target_type: Type de cible (DOMAIN, IP, etc.)
        target_value: Valeur de la cible

    Returns:
        Liste de dictionnaires avec les services détectés
    """
    client = NmapClient(timeout=300)
    result = client.quick_scan(target_value)

    services = []
    for svc in result.services:
        if svc.state == "open":
            services.append({
                "port": svc.port,
                "protocol": svc.protocol,
                "service_name": svc.service_name,
                "service_version": f"{svc.service_product or ''} {svc.service_version or ''}".strip() or None,
                "service_banner": svc.service_banner,
                "cpe": svc.cpe
            })

    return services
