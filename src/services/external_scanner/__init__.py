# backend/src/services/external_scanner/__init__.py
"""
Module Scanner Externe (ASM - Attack Surface Management)

Ce module fournit les outils pour scanner des cibles externes:
- Scan de ports avec nmap
- Audit TLS avec sslyze
- Enrichissement CVE via NVD API
- Calcul de score d'exposition

V1 Features:
- nmap_client: Wrapper Python pour nmap
- tls_audit: Audit TLS/SSL complet
- cve_enrichment: Enrichissement automatique des CVE
- scoring: Calcul du score d'exposition (0-100)
- engine: Orchestrateur du pipeline de scan
"""

from .nmap_client import NmapClient
from .tls_audit import TLSAuditor
from .cve_enrichment import CVEEnrichment
from .scoring import ExposureScoring
from .engine import ScanEngine

__all__ = [
    "NmapClient",
    "TLSAuditor",
    "CVEEnrichment",
    "ExposureScoring",
    "ScanEngine"
]
