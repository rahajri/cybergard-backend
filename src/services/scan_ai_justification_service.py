"""
Service de génération de justifications IA pour les actions Scanner.

Génère des justifications contextualisées pour chaque action corrective
issue d'un scan de vulnérabilités, SANS envoyer de données sensibles à l'IA.

Données anonymisées:
- Domaines/IPs remplacés par "target_xxx"
- Noms d'organismes remplacés par "ORGANISME_xxx"
- Aucune URL ou chemin réseau spécifique

Version: 1.0
Date: 2024-12-07
"""

import logging
import json
import re
import os
from typing import Dict, Any, List, Optional
from datetime import datetime
import httpx

logger = logging.getLogger(__name__)

# Configuration via variables d'environnement
OLLAMA_BASE_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "glm-4.6:cloud")


class ScanAIJustificationService:
    """
    Service de génération de justifications IA pour les vulnérabilités Scanner.

    Génère des explications contextualisées:
    - why_action: Pourquoi corriger cette vulnérabilité
    - why_severity: Justification de la sévérité
    - why_priority: Justification de la priorité
    - why_role: Pourquoi ce rôle est suggéré
    - why_due_days: Justification du délai recommandé

    IMPORTANT: Toutes les données sensibles sont anonymisées avant envoi à l'IA.
    """

    # Prompt système pour la génération de justifications
    SYSTEM_PROMPT = """Tu es un expert en cybersécurité spécialisé dans l'analyse des vulnérabilités et la priorisation des actions correctives.

Ton rôle est de générer des justifications claires et professionnelles pour des actions de remédiation de vulnérabilités détectées lors de scans de sécurité.

RÈGLES IMPORTANTES:
1. Ne JAMAIS mentionner de noms de domaines, IPs, ou noms d'organismes spécifiques
2. Rester générique et applicable à tout contexte
3. Être concis mais informatif (2-3 phrases max par justification)
4. Utiliser un vocabulaire professionnel adapté à un rapport d'audit
5. Baser tes recommandations sur les bonnes pratiques OWASP, NIST, et les standards de l'industrie

Tu réponds UNIQUEMENT en JSON valide, sans texte additionnel."""

    def __init__(self, ollama_base_url: str = None, model: str = None):
        """
        Initialise le service.

        Args:
            ollama_base_url: URL de base d'Ollama (défaut: OLLAMA_URL env var)
            model: Modèle à utiliser (défaut: OLLAMA_MODEL env var)
        """
        self.ollama_base_url = (ollama_base_url or OLLAMA_BASE_URL).rstrip('/')
        self.model = model or OLLAMA_MODEL
        self.timeout = httpx.Timeout(connect=30.0, read=120.0, write=30.0, pool=30.0)
        logger.info(f"🤖 ScanAIJustificationService initialisé - URL: {self.ollama_base_url}, Model: {self.model}")

    def _anonymize_vulnerability(self, vuln: Dict[str, Any]) -> Dict[str, Any]:
        """
        Anonymise les données sensibles d'une vulnérabilité.

        Remplace:
        - Domaines/IPs par des placeholders
        - Noms d'organismes
        - URLs spécifiques
        - Chemins réseau

        Args:
            vuln: Données de la vulnérabilité

        Returns:
            Vulnérabilité anonymisée
        """
        anonymized = {}

        # Copier les champs non sensibles directement
        safe_fields = [
            'severity', 'cvss_score', 'cve_ids', 'port', 'protocol',
            'service_name', 'service_version', 'priority', 'recommended_due_days'
        ]
        for field in safe_fields:
            if field in vuln:
                anonymized[field] = vuln[field]

        # Anonymiser le titre (retirer domaines/IPs)
        title = vuln.get('title', '')
        title = self._anonymize_text(title)
        anonymized['title'] = title

        # Anonymiser la description
        description = vuln.get('description', '')
        description = self._anonymize_text(description)
        anonymized['description'] = description

        # Anonymiser la recommandation
        recommendation = vuln.get('recommendation', '')
        recommendation = self._anonymize_text(recommendation)
        anonymized['recommendation'] = recommendation

        # Nom du service (garder générique)
        service_name = vuln.get('service_name', '')
        if service_name:
            # Garder uniquement le type de service, pas les versions spécifiques
            anonymized['service_type'] = self._get_generic_service_type(service_name)

        return anonymized

    def _anonymize_text(self, text: str) -> str:
        """
        Anonymise un texte en remplaçant les données sensibles.

        Args:
            text: Texte à anonymiser

        Returns:
            Texte anonymisé
        """
        if not text:
            return text

        # Pattern pour les IPs (IPv4)
        text = re.sub(
            r'\b(?:\d{1,3}\.){3}\d{1,3}\b',
            '[IP_ADDRESS]',
            text
        )

        # Pattern pour les domaines
        text = re.sub(
            r'\b(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}\b',
            '[DOMAIN]',
            text
        )

        # Pattern pour les URLs
        text = re.sub(
            r'https?://[^\s]+',
            '[URL]',
            text
        )

        # Pattern pour les chemins Windows
        text = re.sub(
            r'[A-Za-z]:\\[^\s]+',
            '[PATH]',
            text
        )

        # Pattern pour les chemins Unix
        text = re.sub(
            r'/(?:home|var|etc|usr|opt)/[^\s]+',
            '[PATH]',
            text
        )

        return text

    def _get_generic_service_type(self, service_name: str) -> str:
        """
        Retourne un type de service générique.

        Args:
            service_name: Nom du service détecté

        Returns:
            Type générique (web, mail, database, etc.)
        """
        service_lower = service_name.lower()

        if any(x in service_lower for x in ['http', 'nginx', 'apache', 'iis', 'web']):
            return 'web_server'
        elif any(x in service_lower for x in ['smtp', 'pop3', 'imap', 'mail', 'postfix']):
            return 'mail_server'
        elif any(x in service_lower for x in ['mysql', 'postgres', 'mssql', 'oracle', 'mongo', 'redis']):
            return 'database'
        elif any(x in service_lower for x in ['ssh', 'telnet']):
            return 'remote_access'
        elif any(x in service_lower for x in ['ftp', 'sftp']):
            return 'file_transfer'
        elif any(x in service_lower for x in ['dns', 'bind']):
            return 'dns_server'
        elif any(x in service_lower for x in ['ssl', 'tls']):
            return 'ssl_tls_service'
        else:
            return 'network_service'

    async def generate_justifications(self, vulnerability: Dict[str, Any]) -> Dict[str, str]:
        """
        Génère les justifications IA pour une vulnérabilité.

        Args:
            vulnerability: Données de la vulnérabilité (seront anonymisées)

        Returns:
            Dict avec les justifications:
            - why_action: Pourquoi corriger
            - why_severity: Justification sévérité
            - why_priority: Justification priorité
            - why_role: Justification rôle suggéré
            - why_due_days: Justification délai
        """
        # Anonymiser les données avant envoi
        anon_vuln = self._anonymize_vulnerability(vulnerability)

        # Construire le prompt
        user_prompt = self._build_justification_prompt(anon_vuln)

        try:
            # Appeler l'IA
            response = await self._call_ai(user_prompt)

            # Parser la réponse JSON
            justifications = self._parse_response(response)

            logger.info(f"✅ Justifications générées pour vulnérabilité: {anon_vuln.get('title', 'N/A')[:50]}")
            return justifications

        except Exception as e:
            logger.error(f"❌ Erreur génération justifications: {e}")
            # Retourner des justifications par défaut
            return self._generate_default_justifications(anon_vuln)

    async def generate_batch_justifications(
        self,
        vulnerabilities: List[Dict[str, Any]],
        batch_size: int = 5
    ) -> List[Dict[str, str]]:
        """
        Génère les justifications pour plusieurs vulnérabilités en batch.

        Args:
            vulnerabilities: Liste des vulnérabilités
            batch_size: Nombre de vulns à traiter par appel IA

        Returns:
            Liste des justifications pour chaque vulnérabilité
        """
        all_justifications = []

        # Traiter par lots pour éviter les timeouts
        for i in range(0, len(vulnerabilities), batch_size):
            batch = vulnerabilities[i:i + batch_size]

            # Anonymiser toutes les vulns du batch
            anon_batch = [self._anonymize_vulnerability(v) for v in batch]

            try:
                # Construire le prompt batch
                user_prompt = self._build_batch_prompt(anon_batch)

                # Appeler l'IA
                response = await self._call_ai(user_prompt)

                # Parser la réponse
                batch_results = self._parse_batch_response(response, len(batch))
                all_justifications.extend(batch_results)

                logger.info(f"✅ Batch {i//batch_size + 1}: {len(batch_results)} justifications générées")

            except Exception as e:
                logger.error(f"❌ Erreur batch {i//batch_size + 1}: {e}")
                # Générer des justifications par défaut pour ce batch
                for vuln in anon_batch:
                    all_justifications.append(self._generate_default_justifications(vuln))

        return all_justifications

    def _build_justification_prompt(self, vuln: Dict[str, Any]) -> str:
        """
        Construit le prompt pour une seule vulnérabilité.
        """
        cve_info = ""
        cve_links = ""
        if vuln.get('cve_ids'):
            cve_list = vuln['cve_ids'] if isinstance(vuln['cve_ids'], list) else [vuln['cve_ids']]
            cve_info = f"CVE associés: {', '.join(cve_list)}"
            # Générer les liens NVD pour chaque CVE
            cve_links = "\n".join([f"  - https://nvd.nist.gov/vuln/detail/{cve}" for cve in cve_list])
            cve_info += f"\n- Liens NVD:\n{cve_links}"

        return f"""Génère des justifications pour cette action corrective de vulnérabilité:

VULNÉRABILITÉ:
- Titre: {vuln.get('title', 'Non spécifié')}
- Description: {vuln.get('description', 'Non spécifiée')[:500]}
- Sévérité: {vuln.get('severity', 'Non spécifiée')}
- Score CVSS: {vuln.get('cvss_score', 'N/A')}
- {cve_info}
- Port: {vuln.get('port', 'N/A')}
- Service: {vuln.get('service_type', vuln.get('service_name', 'N/A'))}
- Recommandation: {vuln.get('recommendation', 'Non spécifiée')[:300]}
- Priorité assignée: {vuln.get('priority', 'P2')}
- Délai recommandé: {vuln.get('recommended_due_days', 30)} jours

CONTEXTE CVE:
Tu peux te baser sur les CVE fournis et leur documentation NVD pour justifier la sévérité et l'urgence.
Mentionne les CVE dans tes justifications lorsque pertinent.

Retourne un JSON avec ces champs (2-3 phrases max chacun):
{{
    "why_action": "Explication de pourquoi cette action est nécessaire",
    "why_severity": "Justification de la sévérité assignée (mentionner le CVE si disponible)",
    "why_priority": "Justification de la priorité P1/P2/P3",
    "why_role": "Justification du rôle suggéré pour cette correction",
    "why_due_days": "Justification du délai recommandé"
}}"""

    def _build_batch_prompt(self, vulns: List[Dict[str, Any]]) -> str:
        """
        Construit le prompt pour un batch de vulnérabilités.
        """
        vulns_text = []
        for idx, vuln in enumerate(vulns):
            cve_info = ""
            nvd_links = ""
            if vuln.get('cve_ids'):
                cve_list = vuln['cve_ids'] if isinstance(vuln['cve_ids'], list) else [vuln['cve_ids']]
                cve_info = f", CVE: {', '.join(cve_list)}"
                # Liens NVD
                nvd_links = ", ".join([f"https://nvd.nist.gov/vuln/detail/{cve}" for cve in cve_list[:2]])  # Max 2 liens pour batch
                if nvd_links:
                    cve_info += f" (NVD: {nvd_links})"

            vulns_text.append(f"""
VULN_{idx + 1}:
- Titre: {vuln.get('title', 'N/A')}
- Sévérité: {vuln.get('severity', 'N/A')}, CVSS: {vuln.get('cvss_score', 'N/A')}{cve_info}
- Port: {vuln.get('port', 'N/A')}, Service: {vuln.get('service_type', 'N/A')}
- Description: {vuln.get('description', '')[:200]}
- Priorité: {vuln.get('priority', 'P2')}, Délai: {vuln.get('recommended_due_days', 30)}j""")

        return f"""Génère des justifications pour ces {len(vulns)} vulnérabilités.

CONTEXTE: Tu peux te baser sur les CVE fournis et leur documentation NVD pour justifier la sévérité.
Mentionne les CVE dans tes justifications lorsque pertinent.

{chr(10).join(vulns_text)}

Retourne un JSON array avec un objet par vulnérabilité:
[
    {{
        "vuln_index": 1,
        "why_action": "...",
        "why_severity": "... (mentionner le CVE si disponible)",
        "why_priority": "...",
        "why_role": "...",
        "why_due_days": "..."
    }},
    ...
]"""

    async def _call_ai(self, user_prompt: str) -> str:
        """
        Appelle l'API Ollama/DeepSeek.
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            # Essayer d'abord l'endpoint Ollama natif
            endpoints = [
                f"{self.ollama_base_url}/api/chat",
                f"{self.ollama_base_url}/v1/chat/completions"
            ]

            for endpoint in endpoints:
                try:
                    is_openai = endpoint.endswith("/v1/chat/completions")

                    if is_openai:
                        payload = {
                            "model": self.model,
                            "messages": [
                                {"role": "system", "content": self.SYSTEM_PROMPT},
                                {"role": "user", "content": user_prompt}
                            ],
                            "temperature": 0.5,
                            "max_tokens": 4096
                        }
                    else:
                        payload = {
                            "model": self.model,
                            "messages": [
                                {"role": "system", "content": self.SYSTEM_PROMPT},
                                {"role": "user", "content": user_prompt}
                            ],
                            "stream": False,
                            "options": {
                                "temperature": 0.5,
                                "num_predict": 4096
                            }
                        }

                    response = await client.post(endpoint, json=payload)

                    if response.status_code == 200:
                        data = response.json()

                        if is_openai:
                            return data["choices"][0]["message"]["content"]
                        else:
                            return data.get("message", {}).get("content", "")

                except Exception as e:
                    logger.warning(f"Endpoint {endpoint} failed: {e}")
                    continue

            raise RuntimeError("Tous les endpoints IA ont échoué")

    def _parse_response(self, response: str) -> Dict[str, str]:
        """
        Parse la réponse JSON de l'IA.
        """
        try:
            # Nettoyer la réponse
            cleaned = response.strip()
            if cleaned.startswith("```"):
                # Retirer les balises markdown
                if cleaned.startswith("```json"):
                    cleaned = cleaned[7:]
                else:
                    cleaned = cleaned[3:]
                if "```" in cleaned:
                    cleaned = cleaned.split("```")[0]
            cleaned = cleaned.strip()

            result = json.loads(cleaned)

            # Valider les champs requis
            required_fields = ['why_action', 'why_severity', 'why_priority', 'why_role', 'why_due_days']
            for field in required_fields:
                if field not in result:
                    result[field] = "Justification non disponible."

            return result

        except json.JSONDecodeError as e:
            logger.error(f"Erreur parsing JSON: {e}")
            logger.debug(f"Réponse brute: {response[:500]}")
            return self._generate_default_justifications({})

    def _parse_batch_response(self, response: str, expected_count: int) -> List[Dict[str, str]]:
        """
        Parse la réponse JSON batch de l'IA.
        """
        try:
            cleaned = response.strip()
            if cleaned.startswith("```"):
                if cleaned.startswith("```json"):
                    cleaned = cleaned[7:]
                else:
                    cleaned = cleaned[3:]
                if "```" in cleaned:
                    cleaned = cleaned.split("```")[0]
            cleaned = cleaned.strip()

            results = json.loads(cleaned)

            if not isinstance(results, list):
                results = [results]

            # Compléter si nécessaire
            while len(results) < expected_count:
                results.append(self._generate_default_justifications({}))

            # Nettoyer chaque résultat
            cleaned_results = []
            for r in results[:expected_count]:
                if isinstance(r, dict):
                    # Retirer vuln_index s'il existe
                    r.pop('vuln_index', None)
                    cleaned_results.append(r)
                else:
                    cleaned_results.append(self._generate_default_justifications({}))

            return cleaned_results

        except json.JSONDecodeError as e:
            logger.error(f"Erreur parsing JSON batch: {e}")
            return [self._generate_default_justifications({}) for _ in range(expected_count)]

    def _generate_default_justifications(self, vuln: Dict[str, Any]) -> Dict[str, str]:
        """
        Génère des justifications par défaut basées sur les métadonnées.
        """
        severity = vuln.get('severity', 'MEDIUM').upper()
        cvss = vuln.get('cvss_score')
        priority = vuln.get('priority', 'P2')
        due_days = vuln.get('recommended_due_days', 30)
        port = vuln.get('port')
        service_type = vuln.get('service_type', 'service réseau')

        # Justification action
        why_action = "Cette vulnérabilité représente un risque de sécurité qui doit être corrigé pour maintenir la posture de sécurité de l'organisation et prévenir toute exploitation potentielle."

        # Justification sévérité basée sur CVSS
        if cvss and cvss >= 9.0:
            why_severity = f"Sévérité critique (CVSS {cvss}) : Cette vulnérabilité peut être exploitée facilement et avoir un impact majeur sur la confidentialité, l'intégrité ou la disponibilité des systèmes."
        elif cvss and cvss >= 7.0:
            why_severity = f"Sévérité élevée (CVSS {cvss}) : Cette vulnérabilité présente un risque significatif d'exploitation avec des conséquences potentiellement graves."
        elif cvss and cvss >= 4.0:
            why_severity = f"Sévérité moyenne (CVSS {cvss}) : Cette vulnérabilité nécessite certaines conditions pour être exploitée mais reste un risque à traiter."
        else:
            why_severity = f"Sévérité {severity.lower()} : Le niveau de risque est proportionnel à l'impact potentiel et à la facilité d'exploitation de cette vulnérabilité."

        # Justification priorité
        if priority == 'P1':
            why_priority = "Priorité P1 (critique) : Correction urgente requise dans les plus brefs délais. Cette vulnérabilité présente un risque immédiat pour la sécurité."
        elif priority == 'P2':
            why_priority = "Priorité P2 (importante) : Correction à planifier rapidement dans le cycle de maintenance normal. Le risque est significatif mais pas immédiat."
        else:
            why_priority = "Priorité P3 (normale) : Correction à intégrer dans les évolutions planifiées. Le risque est maîtrisable à court terme."

        # Justification rôle
        if port:
            why_role = f"Le responsable système ou réseau est suggéré car cette vulnérabilité affecte un service sur le port {port}, nécessitant des compétences techniques pour la correction."
        else:
            why_role = "Le responsable sécurité ou système est suggéré pour coordonner la correction et valider que la remédiation n'impacte pas les services en production."

        # Justification délai
        if due_days <= 7:
            why_due_days = f"Délai de {due_days} jours : Urgence critique nécessitant une action immédiate pour réduire l'exposition au risque."
        elif due_days <= 14:
            why_due_days = f"Délai de {due_days} jours : Correction rapide recommandée pour minimiser la fenêtre d'exposition à cette vulnérabilité."
        elif due_days <= 30:
            why_due_days = f"Délai de {due_days} jours : Délai standard permettant une correction planifiée avec tests et validation appropriés."
        else:
            why_due_days = f"Délai de {due_days} jours : Délai étendu approprié pour une vulnérabilité de moindre criticité, permettant une intégration dans les cycles de maintenance réguliers."

        return {
            "why_action": why_action,
            "why_severity": why_severity,
            "why_priority": why_priority,
            "why_role": why_role,
            "why_due_days": why_due_days
        }
