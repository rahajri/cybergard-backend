# backend/src/services/external_scanner/report_generator.py
"""
Module de génération de rapports IA pour les scans externes.

Utilise Ollama pour générer des rapports d'analyse de sécurité:
- Résumé exécutif
- Analyse des risques
- Recommandations prioritaires
- Plan d'action
"""

import os
import logging
import httpx
from typing import Optional
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")


@dataclass
class ScanReportData:
    """Données d'entrée pour la génération de rapport."""
    target_value: str
    target_type: str
    scan_date: datetime
    exposure_score: int
    risk_level: str
    tls_grade: Optional[str]
    services: list[dict]
    vulnerabilities: list[dict]
    summary: dict


@dataclass
class GeneratedReport:
    """Rapport généré par l'IA."""
    title: str
    executive_summary: str
    risk_analysis: str
    findings: list[dict]
    recommendations: list[dict]
    action_plan: str
    conclusion: str
    generated_at: datetime
    model_used: str


class ScanReportGenerator:
    """
    Générateur de rapports d'analyse de sécurité.

    Utilise Ollama pour produire des rapports en français avec:
    - Résumé exécutif pour la direction
    - Analyse technique des vulnérabilités
    - Recommandations priorisées
    - Plan d'action concret
    """

    SYSTEM_PROMPT = """Tu es un expert en cybersécurité spécialisé dans l'analyse de surface d'attaque externe (ASM - Attack Surface Management).
Tu génères des rapports d'audit de sécurité professionnels en français.

Ton rôle:
- Analyser les résultats de scans de sécurité
- Identifier les risques critiques
- Proposer des recommandations actionnables
- Rédiger des rapports clairs pour différentes audiences (direction et technique)

Style de rédaction:
- Professionnel et factuel
- Utilise des listes à puces pour la clarté
- Priorise les recommandations (Critique > Haute > Moyenne > Basse)
- Inclus des références aux bonnes pratiques (ISO 27001, CIS, OWASP)
"""

    def __init__(
        self,
        ollama_url: str = OLLAMA_URL,
        model: str = OLLAMA_MODEL,
        timeout: int = 120
    ):
        """
        Initialise le générateur de rapports.

        Args:
            ollama_url: URL du serveur Ollama
            model: Modèle à utiliser
            timeout: Timeout en secondes
        """
        self.ollama_url = ollama_url
        self.model = model
        self.timeout = timeout
        self.client = httpx.AsyncClient(timeout=timeout)

    async def close(self):
        """Ferme le client HTTP."""
        await self.client.aclose()

    async def generate_report(
        self,
        scan_data: ScanReportData
    ) -> GeneratedReport:
        """
        Génère un rapport complet pour un scan.

        Args:
            scan_data: Données du scan

        Returns:
            Rapport généré
        """
        logger.info(f"📝 Génération rapport pour {scan_data.target_value}")

        # Préparer le contexte
        context = self._prepare_context(scan_data)

        # Générer les différentes sections
        executive_summary = await self._generate_section(
            "executive_summary",
            context,
            scan_data
        )

        risk_analysis = await self._generate_section(
            "risk_analysis",
            context,
            scan_data
        )

        recommendations = await self._generate_recommendations(context, scan_data)

        action_plan = await self._generate_section(
            "action_plan",
            context,
            scan_data
        )

        conclusion = await self._generate_section(
            "conclusion",
            context,
            scan_data
        )

        # Construire les findings
        findings = self._build_findings(scan_data.vulnerabilities)

        return GeneratedReport(
            title=f"Rapport d'Analyse de Sécurité - {scan_data.target_value}",
            executive_summary=executive_summary,
            risk_analysis=risk_analysis,
            findings=findings,
            recommendations=recommendations,
            action_plan=action_plan,
            conclusion=conclusion,
            generated_at=datetime.utcnow(),
            model_used=self.model
        )

    def _prepare_context(self, scan_data: ScanReportData) -> str:
        """Prépare le contexte pour le prompt."""
        # Compter les vulnérabilités par sévérité
        severity_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "INFO": 0}
        for vuln in scan_data.vulnerabilities:
            severity = vuln.get("severity", "INFO").upper()
            if severity in severity_counts:
                severity_counts[severity] += 1

        # Lister les CVE critiques
        critical_cves = []
        for vuln in scan_data.vulnerabilities:
            if vuln.get("severity") == "CRITICAL":
                cve_ids = vuln.get("cve_ids", [])
                critical_cves.extend(cve_ids)

        # Lister les ports exposés
        exposed_ports = list(set([
            f"{s.get('port')}/{s.get('protocol', 'tcp')} ({s.get('service_name', 'unknown')})"
            for s in scan_data.services
        ]))

        context = f"""
## Informations du Scan

- **Cible**: {scan_data.target_value}
- **Type**: {scan_data.target_type}
- **Date du scan**: {scan_data.scan_date.strftime('%d/%m/%Y %H:%M')}
- **Score d'exposition**: {scan_data.exposure_score}/100
- **Niveau de risque**: {scan_data.risk_level}
- **Grade TLS**: {scan_data.tls_grade or 'Non évalué'}

## Résumé des Découvertes

- Services exposés: {len(scan_data.services)}
- Vulnérabilités totales: {len(scan_data.vulnerabilities)}
  - Critiques: {severity_counts['CRITICAL']}
  - Hautes: {severity_counts['HIGH']}
  - Moyennes: {severity_counts['MEDIUM']}
  - Basses: {severity_counts['LOW']}
  - Informatives: {severity_counts['INFO']}

## Ports Exposés
{chr(10).join(['- ' + p for p in exposed_ports[:20]])}

## CVE Critiques Détectées
{chr(10).join(['- ' + cve for cve in critical_cves[:10]]) if critical_cves else '- Aucune CVE critique détectée'}

## Vulnérabilités Détaillées
"""
        # Ajouter les 10 premières vulnérabilités les plus critiques
        sorted_vulns = sorted(
            scan_data.vulnerabilities,
            key=lambda v: {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}.get(v.get("severity", "INFO"), 5)
        )

        for i, vuln in enumerate(sorted_vulns[:10], 1):
            context += f"""
### {i}. {vuln.get('title', 'Vulnérabilité')}
- **Sévérité**: {vuln.get('severity', 'INFO')}
- **Type**: {vuln.get('vulnerability_type', 'N/A')}
- **Port**: {vuln.get('port', 'N/A')}/{vuln.get('protocol', 'tcp')}
- **Service**: {vuln.get('service_name', 'N/A')} {vuln.get('service_version', '')}
- **CVSS**: {vuln.get('cvss_score', 'N/A')}
- **Description**: {(vuln.get('description', '') or '')[:200]}...
"""

        return context

    async def _generate_section(
        self,
        section_type: str,
        context: str,
        scan_data: ScanReportData
    ) -> str:
        """Génère une section du rapport."""
        prompts = {
            "executive_summary": f"""
Génère un résumé exécutif (2-3 paragraphes) pour un rapport de sécurité.

Contexte:
{context}

Le résumé doit:
- Être compréhensible par des non-techniciens (direction)
- Mentionner le score d'exposition ({scan_data.exposure_score}/100)
- Identifier les risques principaux
- Donner une vue d'ensemble de la posture de sécurité

Rédige en français, de manière professionnelle et concise.
""",
            "risk_analysis": f"""
Analyse les risques de sécurité identifiés lors du scan.

Contexte:
{context}

L'analyse doit:
- Évaluer l'impact potentiel des vulnérabilités critiques
- Identifier les vecteurs d'attaque possibles
- Estimer la probabilité d'exploitation
- Classifier les risques par priorité

Rédige en français avec des sous-sections claires.
""",
            "action_plan": f"""
Propose un plan d'action concret pour remédier aux vulnérabilités.

Contexte:
{context}

Le plan doit:
- Être structuré par priorité (immédiat, court terme, moyen terme)
- Inclure des actions spécifiques et mesurables
- Identifier les responsables potentiels
- Proposer des indicateurs de suivi

Format: liste numérotée avec délais suggérés.
""",
            "conclusion": f"""
Rédige une conclusion pour ce rapport de sécurité.

Contexte:
- Score d'exposition: {scan_data.exposure_score}/100
- Niveau de risque: {scan_data.risk_level}
- Vulnérabilités critiques: {sum(1 for v in scan_data.vulnerabilities if v.get('severity') == 'CRITICAL')}

La conclusion doit:
- Résumer la posture de sécurité globale
- Souligner l'urgence des remédiations si nécessaire
- Proposer une date de rescan recommandée
- Encourager une approche proactive

2-3 paragraphes en français.
"""
        }

        prompt = prompts.get(section_type, "")
        if not prompt:
            return ""

        return await self._call_ollama(prompt)

    async def _generate_recommendations(
        self,
        context: str,
        scan_data: ScanReportData
    ) -> list[dict]:
        """Génère les recommandations priorisées."""
        prompt = f"""
Génère des recommandations de sécurité basées sur ce scan.

Contexte:
{context}

Pour chaque recommandation, fournis:
1. Titre court
2. Priorité (CRITIQUE, HAUTE, MOYENNE, BASSE)
3. Description de l'action
4. Bénéfice attendu
5. Effort estimé (faible, moyen, élevé)

Format de réponse (JSON):
[
  {{
    "title": "Titre de la recommandation",
    "priority": "CRITIQUE|HAUTE|MOYENNE|BASSE",
    "description": "Description de l'action à réaliser",
    "benefit": "Bénéfice de cette action",
    "effort": "faible|moyen|élevé"
  }}
]

Génère 5-10 recommandations, les plus critiques en premier.
Réponds UNIQUEMENT avec le JSON, sans texte avant ou après.
"""

        response = await self._call_ollama(prompt)

        # Parser le JSON
        try:
            import json
            # Nettoyer la réponse
            response = response.strip()
            if response.startswith("```json"):
                response = response[7:]
            if response.startswith("```"):
                response = response[3:]
            if response.endswith("```"):
                response = response[:-3]

            recommendations = json.loads(response)
            return recommendations if isinstance(recommendations, list) else []
        except Exception as e:
            logger.warning(f"Erreur parsing recommandations: {e}")
            # Fallback: générer des recommandations basiques
            return self._generate_fallback_recommendations(scan_data)

    def _generate_fallback_recommendations(
        self,
        scan_data: ScanReportData
    ) -> list[dict]:
        """Génère des recommandations par défaut si l'IA échoue."""
        recommendations = []

        # Recommandations basées sur les vulnérabilités
        critical_count = sum(1 for v in scan_data.vulnerabilities if v.get("severity") == "CRITICAL")
        high_count = sum(1 for v in scan_data.vulnerabilities if v.get("severity") == "HIGH")

        if critical_count > 0:
            recommendations.append({
                "title": "Corriger les vulnérabilités critiques",
                "priority": "CRITIQUE",
                "description": f"Remédier aux {critical_count} vulnérabilités critiques identifiées",
                "benefit": "Réduction significative du risque d'exploitation",
                "effort": "élevé"
            })

        if high_count > 0:
            recommendations.append({
                "title": "Traiter les vulnérabilités hautes",
                "priority": "HAUTE",
                "description": f"Planifier la correction des {high_count} vulnérabilités de haute sévérité",
                "benefit": "Amélioration de la posture de sécurité",
                "effort": "moyen"
            })

        # TLS
        if scan_data.tls_grade and scan_data.tls_grade not in ["A", "A+"]:
            recommendations.append({
                "title": "Améliorer la configuration TLS",
                "priority": "HAUTE",
                "description": f"Grade actuel: {scan_data.tls_grade}. Désactiver les protocoles obsolètes et les ciphers faibles",
                "benefit": "Protection des données en transit",
                "effort": "moyen"
            })

        # Ports exposés
        risky_ports = [s.get("port") for s in scan_data.services if s.get("port") in [21, 23, 3389, 445]]
        if risky_ports:
            recommendations.append({
                "title": "Fermer les ports sensibles",
                "priority": "CRITIQUE",
                "description": f"Ports à risque exposés: {', '.join(map(str, risky_ports))}",
                "benefit": "Réduction de la surface d'attaque",
                "effort": "faible"
            })

        return recommendations

    def _build_findings(self, vulnerabilities: list[dict]) -> list[dict]:
        """Construit la liste des findings pour le rapport."""
        findings = []

        for vuln in vulnerabilities:
            findings.append({
                "title": vuln.get("title", "Vulnérabilité détectée"),
                "severity": vuln.get("severity", "INFO"),
                "type": vuln.get("vulnerability_type", "UNKNOWN"),
                "port": vuln.get("port"),
                "service": vuln.get("service_name"),
                "description": vuln.get("description", ""),
                "cve_ids": vuln.get("cve_ids", []),
                "cvss_score": vuln.get("cvss_score"),
                "recommendation": vuln.get("recommendation", "")
            })

        # Trier par sévérité
        severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
        findings.sort(key=lambda x: severity_order.get(x["severity"], 5))

        return findings

    async def _call_ollama(self, prompt: str) -> str:
        """Appelle l'API Ollama pour générer du texte."""
        try:
            response = await self.client.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "system": self.SYSTEM_PROMPT,
                    "stream": False,
                    "options": {
                        "temperature": 0.7,
                        "top_p": 0.9,
                        "num_predict": 2048
                    }
                }
            )
            response.raise_for_status()
            data = response.json()
            return data.get("response", "")

        except httpx.ConnectError:
            logger.error(f"❌ Impossible de se connecter à Ollama sur {self.ollama_url}")
            return "[Erreur: Service IA non disponible]"
        except Exception as e:
            logger.error(f"❌ Erreur Ollama: {e}")
            return f"[Erreur lors de la génération: {e}]"


async def generate_scan_report(
    scan_data: dict,
    target_data: dict,
    vulnerabilities: list[dict],
    services: list[dict]
) -> GeneratedReport:
    """
    Fonction helper pour générer un rapport de scan.

    Args:
        scan_data: Données du scan
        target_data: Données de la cible
        vulnerabilities: Liste des vulnérabilités
        services: Liste des services

    Returns:
        Rapport généré
    """
    generator = ScanReportGenerator()

    try:
        summary = scan_data.get("summary", {})

        report_data = ScanReportData(
            target_value=target_data.get("value", "Unknown"),
            target_type=target_data.get("type", "DOMAIN"),
            scan_date=scan_data.get("finished_at") or datetime.utcnow(),
            exposure_score=summary.get("exposure_score", 0),
            risk_level=summary.get("risk_level", "UNKNOWN"),
            tls_grade=summary.get("tls_grade"),
            services=services,
            vulnerabilities=vulnerabilities,
            summary=summary
        )

        return await generator.generate_report(report_data)

    finally:
        await generator.close()
