import asyncio
import json
import logging
import math
import re
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4
from sqlalchemy.orm import Session
from src.models.audit import ControlPoint 
import httpx
from ..config import settings

from src.dependencies import get_deepseek_generator

logger = logging.getLogger(__name__)

# En haut du fichier
logging.basicConfig(
    level=logging.DEBUG,  # ✅ Changer de INFO à DEBUG
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

class DeepSeekControlPointGenerator:
    """Générateur de points de contrôle via DeepSeek/Ollama"""
    UUIDISH = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)

    def __init__(
        self,
        db: Optional[Session] = None,
        ollama_url: str = "http://localhost:11434",
        model: str = "deepseek-v3.1:671b-cloud",
        batch_size: int = 10,
        num_ctx: int = 16384,
        num_predict: int = 4096,
        temperature: float = 0.05,
        top_p: float = 0.9,
        top_k: int = 40,
        repeat_penalty: float = 1.1,
        timeout: float = 600.0,
        max_retries: int = 3,
        ai_enabled: bool = True
    ):
        """
        Initialise le générateur DeepSeek.
        
        Args:
            db: Session SQLAlchemy pour déduplication (NOUVEAU)
            ollama_url: URL de l'API Ollama
            model: Nom du modèle (ex: deepseek-v3.1:671b-cloud)
            batch_size: Nombre d'exigences par batch
            num_ctx: Taille du contexte
            num_predict: Nombre max de tokens à générer
            temperature: Créativité (0.0-1.0, défaut 0.05)
            top_p: Nucleus sampling
            top_k: Top-k sampling
            repeat_penalty: Pénalité de répétition
            timeout: Timeout des requêtes HTTP (secondes)
            max_retries: Nombre de tentatives max
            ai_enabled: Activer/désactiver la génération IA
        """
        self.db = db
        self.existing_control_points_cache = {}  # ✅ Initialisation correcte ici
        self.ollama_url = ollama_url.rstrip("/")
        self.model = model
        self.batch_size = batch_size
        self.num_ctx = num_ctx
        self.num_predict = num_predict
        self.temperature = temperature
        self.top_p = top_p
        self.top_k = top_k
        self.repeat_penalty = repeat_penalty
        self.timeout = timeout
        self.max_retries = max_retries
        self.ai_enabled = ai_enabled
        
        # ✅ Initialiser le résultat (pour éviter AttributeError plus tard)
        self._result: Dict[str, Any] = {
            "control_points": [],
            "mappings": [],
            "true_uncovered_requirement_ids": []
        }
        
        if self.db:
            self._load_existing_control_points()
        
        logger.info(
            f"[PCGen] ✅ Initialisé | Model={self.model} | Batch={self.batch_size} | "
            f"Ollama={self.ollama_url} | IA={self.ai_enabled} | "
            f"Cache PCs={len(self.existing_control_points_cache)}"
        )

    # ---------------------------
    #           PUBLIC
    # ---------------------------
    # LIGNE ~90 : Après __init__, AVANT _build_system_prompt

    def _load_existing_control_points(self) -> None:
        """
        Charge tous les points de contrôle existants en cache.
        Permet la déduplication et le cross-référentiel.
        """
        if not self.db:
            logger.warning("[PCGen] ⚠️ Pas de session DB, déduplication désactivée")
            return
        
        try:
            existing_cps = self.db.query(ControlPoint).all()
            self.existing_control_points_cache = {
                cp.code: cp for cp in existing_cps if cp.code
            }
            
            logger.info(
                f"[PCGen] 💾 {len(self.existing_control_points_cache)} PCs "
                f"existants chargés en cache"
            )
            
            if self.existing_control_points_cache:
                first_5 = list(self.existing_control_points_cache.keys())[:5]
                logger.debug(f"[PCGen] 📋 Aperçu cache: {first_5}")
            
        except Exception as e:
            logger.error(f"[PCGen] ❌ Erreur chargement cache PCs: {e}", exc_info=True)
            self.existing_control_points_cache = {}

    def _select_model_for_requirement(self, requirement: Dict[str, Any]) -> str:
        """
        Sélectionne le modèle approprié selon la complexité de l'exigence.
        
        Returns:
            str: Nom du modèle à utiliser
        """
        # Récupérer la config
        use_auto = settings.AI_AUTO_MODEL_SELECTION
        use_advanced_for_critical = settings.AI_USE_ADVANCED_FOR_CRITICAL
        
        if not use_auto:
            # Utiliser le modèle par défaut
            return settings.OLLAMA_MODEL
        
        # Critères pour utiliser DeepSeek (modèle avancé)
        req_text = requirement.get("text", "").lower()
        req_code = requirement.get("code", "")
        
        # Cas 1 : Exigences critiques marquées
        if use_advanced_for_critical:
            criticality = requirement.get("criticality", "").upper()
            if criticality in ["HIGH", "CRITICAL"]:
                logger.info(f"[PCGen] 🎯 Utilisation DeepSeek pour {req_code} (criticité: {criticality})")
                return settings.OLLAMA_MODEL_ADVANCED
        
        # Cas 2 : Exigences techniques complexes
        complex_keywords = [
            "cryptographie", "chiffrement", "encryption",
            "architecture", "authentification multi-facteur",
            "segmentation", "micro-segmentation",
            "zero trust", "détection d'intrusion"
        ]
        
        if any(keyword in req_text for keyword in complex_keywords):
            logger.info(f"[PCGen] 🎯 Utilisation DeepSeek pour {req_code} (complexité détectée)")
            return settings.OLLAMA_MODEL_ADVANCED
        
        # Cas 3 : Domaines spécialisés (NIST, CIS, etc.)
        if any(framework in req_code for framework in ["NIST", "CIS", "PCI-DSS"]):
            logger.info(f"[PCGen] 🎯 Utilisation DeepSeek pour {req_code} (framework spécialisé)")
            return settings.OLLAMA_MODEL_ADVANCED
        
        # Par défaut : Mistral (rapide et efficace)
        logger.info(f"[PCGen] ⚡ Utilisation Mistral pour {req_code} (génération standard)")
        return settings.OLLAMA_MODEL


    async def _call_deepseek(
        self, 
        prompt: str, 
        model: Optional[str] = None
    ) -> str:
        """
        Appelle Ollama avec le modèle spécifié ou par défaut.
        """
        if model is None:
            model = settings.OLLAMA_MODEL
        
        logger.info(f"[PCGen] 🤖 Utilisation du modèle: {model}")
        
        # Adapter les paramètres selon le modèle
        if "mistral" in model.lower():
            params = {
                "num_ctx": settings.MISTRAL_NUM_CTX,
                "num_predict": settings.MISTRAL_MAX_TOKENS,
                "temperature": settings.MISTRAL_TEMPERATURE,
                "top_p": settings.AI_TOP_P,
                "repeat_penalty": settings.AI_REPEAT_PENALTY,
            }
        else:  # DeepSeek ou autre
            params = {
                "num_ctx": settings.DEEPSEEK_NUM_CTX,
                "num_predict": settings.DEEPSEEK_MAX_TOKENS,
                "temperature": settings.DEEPSEEK_TEMPERATURE,
                "top_p": settings.AI_TOP_P,
                "repeat_penalty": settings.AI_REPEAT_PENALTY,
            }
    
        # ✅ Appeler Ollama avec les bons paramètres
        try:
            messages = [{"role": "user", "content": prompt}]
            
            payload = {
                "model": model,
                "messages": messages,
                "stream": False,
                "options": params
            }
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(f"{self.ollama_url}/api/chat", json=payload)
                resp.raise_for_status()
                data = resp.json()
                
                content = data.get("message", {}).get("content", "")
                
                if not content:
                    raise RuntimeError("Réponse vide du modèle")
                
                return content
                
        except Exception as e:
            logger.error(f"[PCGen] Erreur appel Ollama: {e}")
            raise RuntimeError(f"Échec appel {model}: {str(e)}")
        

    # LIGNE 233-280 : Remplacer toute la méthode _call_ollama_chat

    # LIGNE 360-375 : Remplacer tout le bloc

    async def _call_ollama_chat(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        retry_count: int = 0,
    ) -> Dict[str, Any]:
        """
        Appelle Ollama /api/chat avec gestion des retries et déduplication.
        """
        if retry_count >= self.max_retries:
            raise RuntimeError(f"Trop de tentatives ({self.max_retries}) – échec définitif.")

        # ✅ CONSTRUIRE LA LISTE DES PCS EXISTANTS
        existing_pcs_summary = []
        for code, cp in self.existing_control_points_cache.items():
            existing_pcs_summary.append({
                "code": code,
                "name": cp.name or "",
                "description": (cp.description or "")[:150],
                "category": cp.category or "Non classé"
            })
        
        existing_pcs_count = len(existing_pcs_summary)

        # ⚠️ IMPORTANT : Augmenter la limite pour un meilleur cross-référentiel
        # Avec 150 PCs * ~150 chars = ~22KB, on reste sous les limites de contexte (16K tokens)
        max_pcs_in_prompt = 100  # Augmenté de 20 à 100 pour meilleur cross-référentiel

        existing_pcs_json = json.dumps(
            existing_pcs_summary[:max_pcs_in_prompt],
            indent=2,
            ensure_ascii=False
        )
        
        # ✅ PROMPT SYSTÈME ENRICHI AVEC DÉDUPLICATION
        enhanced_system_prompt = f"""Tu es un expert en cybersécurité et conformité.

🎯 MISSION CRITIQUE : DÉDUPLICATION ET CROSS-RÉFÉRENTIEL

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🌐 QU'EST-CE QU'UN CROSS-RÉFÉRENTIEL ?

Le CROSS-RÉFÉRENTIEL est le principe fondamental de mutualisation des contrôles :

💡 **Principe clé** :
Un MÊME Point de Contrôle peut satisfaire PLUSIEURS exigences de DIFFÉRENTS référentiels
(ISO 27001, ISO 27002, NIST, RGPD, etc.)

🎯 **Exemple concret** :
┌─────────────────────────────────────────────────────────────┐
│ PC-A.5.15 "Politique de contrôle d'accès"                   │
│                                                              │
│ Satisfait simultanément :                                    │
│ ✓ ISO 27001:2022 → A.5.15 (Contrôle d'accès)               │
│ ✓ ISO 27002:2022 → 5.15 (Contrôle d'accès)                 │
│ ✓ NIST CSF → PR.AC-1 (Gestion des identités)               │
│ ✓ RGPD → Art. 32 (Limitation des accès)                    │
└─────────────────────────────────────────────────────────────┘

📈 **Bénéfices** :
- 1 PC implémenté = 4 exigences couvertes
- Réduction des coûts d'audit (gain de 75%)
- Cohérence entre référentiels
- Simplification de la conformité

⚠️ **TON OBJECTIF PRINCIPAL** :
MAXIMISER la réutilisation des PCs existants pour créer un maximum de liens cross-référentiels

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📚 BASE DE CONNAISSANCE : {existing_pcs_count} PCs EXISTANTS EN BASE

{existing_pcs_json if existing_pcs_count > 0 else "⚠️ AUCUN PC EXISTANT - Tu peux créer librement"}

{f"(Affichage limité à {max_pcs_in_prompt}/{existing_pcs_count} PCs)" if existing_pcs_count > max_pcs_in_prompt else ""}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔥 PROCESSUS OBLIGATOIRE D'ANALYSE (ÉTAPE PAR ÉTAPE) :

Pour CHAQUE exigence que tu traites, tu DOIS suivre ce processus :

┌─────────────────────────────────────────────────────────────┐
│ ÉTAPE 1 : COMPRENDRE L'EXIGENCE                             │
│ → Quel est l'objectif de sécurité ?                         │
│ → Quel domaine (accès, chiffrement, sauvegarde, etc.) ?     │
│ → Quelle action concrète doit être mise en place ?          │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│ ÉTAPE 2 : ANALYSER SYSTÉMATIQUEMENT LA LISTE COMPLÈTE       │
│ ⚠️ TU DOIS PARCOURIR **TOUS** LES PCs EXISTANTS !          │
│                                                              │
│ Pour chaque PC existant, demande-toi :                       │
│ ✓ Ce PC couvre-t-il le même objectif de sécurité ?          │
│ ✓ Ce PC agit-il sur le même domaine ?                       │
│ ✓ Ce PC répond-il à cette nouvelle exigence ?               │
│                                                              │
│ ⚠️ Ne te contente PAS des 2-3 premiers PCs !                │
│ ⚠️ Parcours TOUTE la liste jusqu'à la fin !                 │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│ ÉTAPE 3 : DÉCISION                                          │
│                                                              │
│ ✅ SI un PC existant correspond :                           │
│    → RENVOIE sa référence exacte (ex: "PC-A.5.15")         │
│    → Indique "reused": true                                 │
│    → Renseigne "existing_code": "PC-A.5.15"                │
│    → Explique pourquoi dans "deduplication_rationale"      │
│                                                              │
│ ❌ SI AUCUN PC existant ne correspond :                     │
│    → CRÉE un nouveau PC                                     │
│    → Indique "reused": false                                │
│    → Renseigne "existing_code": null                        │
│    → Explique pourquoi dans "deduplication_rationale"      │
└─────────────────────────────────────────────────────────────┘

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️ RÈGLES D'UNICITÉ (CRITIQUE POUR LE CROSS-RÉFÉRENTIEL) :

1. ✅ **TOUJOURS ANALYSER LA LISTE COMPLÈTE** des PCs existants avant de créer
2. ✅ **Un PC = Un objectif de contrôle UNIQUE** (ex: "Gestion des mots de passe")
3. ✅ **RÉUTILISE** un PC existant si son objectif correspond (même partiellement)
4. ✅ **RENVOIE LA RÉFÉRENCE EXACTE** du PC existant (ex: "PC-A.5.15")
5. ✅ **Un même PC peut couvrir plusieurs exigences** de différents référentiels
6. ❌ **NE CRÉE PAS** un nouveau PC si un existant fait déjà le travail
7. ❌ **NE DUPLIQUE JAMAIS** un contrôle qui existe déjà

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔍 CRITÈRES DE RÉUTILISATION (Sois LARGE dans ta recherche) :

✅ RÉUTILISE si :
- Même domaine (ex: Contrôle d'accès, Chiffrement, Sauvegarde)
- Même type de contrôle (ex: Authentification, Journalisation, Formation)
- Objectif équivalent ou similaire (ex: "Sécuriser les mots de passe")
- Même finalité de sécurité (ex: Protection des données, Continuité)
- ⚠️ Même si la formulation diffère légèrement entre référentiels !

❌ CRÉE UNIQUEMENT si :
- AUCUN PC existant ne couvre cet objectif
- L'exigence introduit un nouveau type de contrôle jamais vu
- Le domaine est totalement différent de tous les PCs existants
- ⚠️ Tu as parcouru TOUTE la liste et rien ne correspond

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📋 FORMAT DE RÉPONSE JSON OBLIGATOIRE :

⚠️ CHAMPS OBLIGATOIRES À NE JAMAIS OMETTRE :
- criticality_level (LOW|MEDIUM|HIGH|CRITICAL)
- estimated_effort_hours (nombre entier : 2, 3, 4, 6, 8, 12, 16, 24, 40, 60, 80)

{{
  "control_points": [
    {{
      "cp_ref": "CP-DOMAINE.X.Y",
      "title": "Titre du contrôle",
      "description": "Description détaillée (minimum 50 mots)",
      "category": "Catégorie",

      "criticality_level": "LOW|MEDIUM|HIGH|CRITICAL",  ← ⚠️ OBLIGATOIRE ! VARIE CETTE VALEUR !
      "estimated_effort_hours": 8,  ← ⚠️ OBLIGATOIRE ! VARIE CETTE VALEUR (2,3,4,6,8,12,16,24,40,60,80) !

      "ai_confidence": 0.95,
      "rationale": "Explication de la pertinence ET justification de criticality + effort",
      "requirement_ids": ["req_id_1"],

      "reused": true,
      "existing_code": "PC-XXX",
      "deduplication_rationale": "Explication détaillée"
    }}
  ],
  "mappings": [
    {{"requirement_id": "req_id_1", "cp_ref": "CP-DOMAINE.X.Y"}}
  ]
}}

⚠️ RAPPEL : Si tu oublies criticality_level ou estimated_effort_hours, ton JSON sera REJETÉ !

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🎯 INSTRUCTIONS CRITIQUES POUR "criticality_level" ET "estimated_effort_hours" :

🚨 RÈGLE ABSOLUE OBLIGATOIRE 🚨

❌ INTERDIT : Mettre "MEDIUM" et "8" pour toutes les exigences
❌ INTERDIT : Utiliser toujours les mêmes valeurs par défaut
❌ INTERDIT : Ne pas analyser la criticité et l'effort réels

✅ OBLIGATOIRE : Tu DOIS varier les valeurs pour chaque exigence
✅ OBLIGATOIRE : Analyser l'impact et la complexité de CHAQUE contrôle
✅ OBLIGATOIRE : Justifier tes choix dans le champ "rationale"

⚠️ Si tu mets "MEDIUM" et "8", tu DOIS expliquer POURQUOI dans "rationale"
⚠️ Une base de PCs réaliste a une DISTRIBUTION variée des criticités et efforts

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 CRITICALITY_LEVEL (Niveau de criticité) :

🎯 DISTRIBUTION CIBLE ATTENDUE (pour un ensemble de PCs réaliste) :
- 15% CRITICAL (contrôles critiques)
- 30% HIGH (contrôles importants)
- 40% MEDIUM (contrôles standards)
- 15% LOW (contrôles complémentaires)

⚠️ VARIE les niveaux ! Ne mets PAS tout en MEDIUM !

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Analyse l'IMPACT et la SENSIBILITÉ de l'exigence :

🔴 CRITICAL (Critique) - Exemples :
- Contrôle d'accès aux données sensibles (RGPD, secrets)
- Chiffrement des données critiques
- Authentification multifacteur pour admins
- Sauvegarde des données critiques
- Plan de continuité d'activité
→ Impact sécurité MAJEUR, conformité OBLIGATOIRE

🟠 HIGH (Élevé) - Exemples :
- Gestion des droits d'accès
- Journalisation des événements de sécurité
- Mise à jour des correctifs de sécurité
- Contrôle des accès physiques
- Formation à la sécurité
→ Impact sécurité IMPORTANT, risque significatif

🟡 MEDIUM (Moyen) - Exemples :
- Politique de mots de passe standard
- Antivirus et anti-malware
- Classification des actifs
- Contrôle des supports amovibles
- Documentation des procédures
→ Impact sécurité MODÉRÉ, bonne pratique standard

🟢 LOW (Faible) - Exemples :
- Affichage des bannières de connexion
- Organisation des espaces de travail
- Étiquetage des câbles réseau
- Inventaire du matériel non-critique
- Sensibilisation générale
→ Impact sécurité LIMITÉ, mesure complémentaire

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⏱️ ESTIMATED_EFFORT_HOURS (Charge de travail estimée) :

🎯 DISTRIBUTION CIBLE ATTENDUE (pour un ensemble de PCs réaliste) :
- 20% → 2-4 heures (contrôles simples)
- 40% → 6-12 heures (contrôles standards)
- 30% → 16-24 heures (contrôles complexes)
- 10% → 40-80 heures (projets majeurs)

⚠️ VARIE les charges ! Ne mets PAS tout à "8" !

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Estime le TEMPS RÉEL nécessaire pour implémenter le contrôle :

🕐 2-4 heures - Contrôles simples :
- Activation d'une fonctionnalité existante
- Configuration d'un paramètre
- Création d'un document simple
- Affichage d'une bannière

🕑 6-12 heures - Contrôles standards :
- Rédaction d'une politique complète
- Configuration d'un outil de sécurité
- Mise en place d'une procédure
- Formation d'une équipe

🕓 16-24 heures - Contrôles complexes :
- Déploiement d'une solution technique
- Audit complet d'un domaine
- Mise en place d'un processus métier
- Intégration avec systèmes existants

🕗 40-80 heures - Projets majeurs :
- Implémentation d'un système de chiffrement complet
- Mise en place d'un SOC
- Refonte de l'architecture de sécurité
- Programme de formation complet

⚠️ Prends en compte :
- Complexité technique
- Nombre de systèmes impactés
- Besoin de compétences spécialisées
- Dépendances organisationnelles
- Phase de test et validation

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

💡 EXEMPLES CONCRETS DE CROSS-RÉFÉRENTIEL :

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📌 EXEMPLE 1 : Réutilisation CROSS-RÉFÉRENTIEL (✅ EXCELLENT)

Contexte : Tu traites une exigence ISO 27002
Exigence ISO 27002 : "Les mots de passe doivent respecter une complexité minimale"

Tu analyses la liste des PCs existants et tu trouves :
PC-A.5.1.1 "Politique de mots de passe sécurisés" (créé pour ISO 27001)

→ **ANALYSE** : L'objectif est identique (sécuriser les mots de passe)
→ **DÉCISION** : RÉUTILISE PC-A.5.1.1 (même s'il vient d'un autre référentiel !)
→ **RÉSULTAT** : 1 PC couvre maintenant ISO 27001 + ISO 27002 (CROSS-RÉFÉRENTIEL)

Réponse JSON :
{{
  "reused": true,
  "existing_code": "PC-A.5.1.1",
  "criticality_level": "HIGH",
  "estimated_effort_hours": 8,
  "deduplication_rationale": "Ce PC couvre déjà la complexité des mots de passe. Réutilisation cross-référentiel entre ISO 27001 et ISO 27002.",
  "rationale": "Criticité HIGH car impact important sur la sécurité des accès. Effort 8h pour documenter et déployer la politique."
}}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📌 EXEMPLE 2 : Réutilisation avec formulation différente (✅ EXCELLENT)

Contexte : Tu traites une exigence NIST
Exigence NIST CSF : "Implement multi-factor authentication for privileged accounts"

Tu analyses la liste et tu trouves :
PC-IAM.3.2 "Authentification multifacteur pour comptes à privilèges" (créé pour RGPD)

→ **ANALYSE** : Même objectif malgré la formulation différente (anglais vs français)
→ **DÉCISION** : RÉUTILISE PC-IAM.3.2
→ **RÉSULTAT** : 1 PC couvre maintenant RGPD + NIST (CROSS-RÉFÉRENTIEL international)

Réponse JSON :
{{
  "reused": true,
  "existing_code": "PC-IAM.3.2",
  "criticality_level": "CRITICAL",
  "estimated_effort_hours": 16,
  "deduplication_rationale": "Même objectif de sécurité : authentification multifacteur pour comptes privilégiés. Cross-référentiel RGPD-NIST.",
  "rationale": "Criticité CRITICAL car protège les comptes à privilèges (accès admin). Effort 16h pour déployer MFA sur tous les comptes privilégiés et former les utilisateurs."
}}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📌 EXEMPLE 3 : Création justifiée (✅ BON)

Contexte : Tu traites une exigence ISO 27001
Exigence ISO 27001 : "Mettre en place un système de détection d'intrusion"

Tu analyses TOUTE la liste des PCs existants :
- PC-A.5.1.1 "Mots de passe" → Non, domaine différent
- PC-A.8.2.1 "Sauvegarde" → Non, domaine différent
- PC-A.9.1.1 "Contrôle d'accès" → Non, objectif différent
... (tu continues jusqu'à la fin de la liste)

→ **ANALYSE** : Aucun PC existant ne couvre la détection d'intrusion
→ **DÉCISION** : CRÉE un nouveau PC
→ **RÉSULTAT** : Nouveau PC nécessaire

Réponse JSON :
{{
  "reused": false,
  "existing_code": null,
  "cp_ref": "PC-A.12.4.1",
  "title": "Système de détection d'intrusion (IDS/IPS)",
  "criticality_level": "HIGH",
  "estimated_effort_hours": 40,
  "deduplication_rationale": "Nouveau contrôle nécessaire. Analyse complète de la base : aucun PC existant ne couvre la détection d'intrusion.",
  "rationale": "Criticité HIGH car détection proactive des menaces. Effort 40h pour sélectionner, installer, configurer l'IDS et définir les règles de détection."
}}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

❌ EXEMPLE 4 : Duplication INTERDITE (MAUVAIS !)

Contexte : Tu traites une exigence RGPD
Exigence RGPD : "Appliquer des règles de mots de passe forts"

Tu analyses et tu trouves :
PC-A.5.1.1 "Politique de mots de passe sécurisés" (créé pour ISO 27001)

→ ❌ **ERREUR** : Créer PC-RGPD.32.1 "Politique de mots de passe RGPD"
→ ✅ **CORRECT** : RÉUTILISER PC-A.5.1.1

**Pourquoi c'est une erreur ?**
- Duplication inutile (même objectif)
- Perte du bénéfice cross-référentiel
- Maintenance compliquée (2 PCs au lieu d'1)
- Coût d'audit multiplié

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📌 EXEMPLE 5 : Contrôle simple (✅ VARIE LES VALEURS)

Contexte : Tu traites une exigence ISO 27001
Exigence ISO 27001 : "Afficher une bannière de connexion informant les utilisateurs"

Tu analyses TOUTE la liste → Aucun PC existant sur les bannières
→ **DÉCISION** : CRÉE un nouveau PC simple

Réponse JSON :
{{
  "reused": false,
  "existing_code": null,
  "cp_ref": "PC-A.7.2.8",
  "title": "Bannière d'information à la connexion",
  "criticality_level": "LOW",
  "estimated_effort_hours": 3,
  "deduplication_rationale": "Nouveau contrôle. Aucun PC existant sur l'affichage de bannières.",
  "rationale": "Criticité LOW car mesure informative sans impact direct sur la sécurité. Effort 3h pour créer la bannière, la configurer sur les systèmes et valider l'affichage."
}}

⚠️ NOTE : LOW + 3h car c'est un contrôle simple et rapide !

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🎯 RAPPEL FINAL :

⚠️ AVANT de créer un nouveau PC, demande-toi TOUJOURS :
"Est-ce que je peux réutiliser un PC existant ?"

✅ Ton objectif : MAXIMISER les liens cross-référentiels
✅ Ta mission : MINIMISER la création de nouveaux PCs
✅ Ton rôle : Créer une base de PCs MUTUALISÉE et EFFICACE

⚠️ VARIE criticality_level et estimated_effort_hours selon la RÉALITÉ de chaque contrôle !

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{system_prompt if system_prompt else ""}
"""

        msgs = list(messages)
        msgs.insert(0, {"role": "system", "content": enhanced_system_prompt})

        payload = {
            "model": self.model,
            "messages": msgs,
            "stream": False,
            "options": {
                "num_ctx": self.num_ctx,
                "num_predict": self.num_predict,
                "temperature": self.temperature,
                "top_p": self.top_p,
                "top_k": self.top_k,
                "repeat_penalty": self.repeat_penalty,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(f"{self.ollama_url}/api/chat", json=payload)
                resp.raise_for_status()
                data = resp.json()
                
                # Log de debug
                raw_content = data.get("message", {}).get("content", "")
                logger.debug(f"[PCGen] 📦 Réponse brute Ollama ({len(raw_content)} chars):")
                logger.debug(f"[PCGen] {raw_content[:500]}...")
                
                return data

        except httpx.TimeoutException:
            logger.warning(f"[PCGen] ⏱️ timeout batch retry {retry_count+1}/{self.max_retries}")
            await asyncio.sleep(2)
            return await self._call_ollama_chat(messages, system_prompt, retry_count + 1)
        except Exception as e:
            logger.error(f"[PCGen] ❌ Ollama error: {e}")
            raise
        
    def _parse_json_blocks(self, content: str) -> List[Dict[str, Any]]:
        """
        Extrait tous les blocs JSON de la réponse LLM.
        Version ultra-robuste pour DeepSeek.
        """
        import re
        
        blocks = []
        
        # 1️⃣ Nettoyer le contenu
        content = content.strip()
        
        # Supprimer les balises markdown
        # Patterns: ```json ... ``` ou ``` ... ```
        markdown_pattern = r'```(?:json)?\s*(.*?)\s*```'
        markdown_matches = re.findall(markdown_pattern, content, re.DOTALL)
        
        if markdown_matches:
            logger.debug(f"[PCGen] 📋 {len(markdown_matches)} bloc(s) markdown trouvé(s)")
            content = markdown_matches[0]  # Prendre le premier bloc
        
        content = content.strip()
        
        logger.debug(f"[PCGen] 🧹 Contenu nettoyé: {content[:200]}...")
        
        # 2️⃣ Essayer de parser directement
        try:
            data = json.loads(content)
            logger.debug(f"[PCGen] ✅ JSON parsé: {list(data.keys())}")
            blocks.append(data)
            return blocks
        except json.JSONDecodeError as e:
            logger.debug(f"[PCGen] ⚠️ Parsing direct échoué: {e}")
        
        # 3️⃣ Chercher tous les objets JSON { ... }
        json_pattern = r'\{(?:[^{}]|(?:\{[^{}]*\}))*\}'
        json_matches = re.finditer(json_pattern, content, re.DOTALL)
        
        for match in json_matches:
            json_str = match.group(0)
            try:
                data = json.loads(json_str)
                logger.debug(f"[PCGen] ✅ Bloc trouvé: {list(data.keys())}")
                blocks.append(data)
            except json.JSONDecodeError:
                continue
        
        logger.debug(f"[PCGen] 📦 Total: {len(blocks)} bloc(s) extraits")
        
        return blocks

    def _parse_batch_response(
        self, 
        raw_content: str, 
        req_batch: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Parse la réponse du LLM pour un batch.
        Retourne (control_points, mappings).
        """
        logger.debug(f"[PCGen] 🔍 Parsing réponse batch ({len(raw_content)} chars)")
        
        blocks = self._parse_json_blocks(raw_content)
        
        if not blocks:
            logger.warning(f"[PCGen] ⚠️ Aucun bloc JSON trouvé dans la réponse")
            logger.debug(f"[PCGen] Réponse brute: {raw_content[:500]}...")
            return [], []
        
        logger.info(f"[PCGen] 📦 {len(blocks)} blocs JSON trouvés")
        
        all_cps = []
        all_mappings = []
        
        for i, block in enumerate(blocks):
            logger.debug(f"[PCGen] 📋 Traitement bloc {i+1}/{len(blocks)}")
            
            # Cas 1: Bloc avec "points_de_controle"
            if "points_de_controle" in block:
                cps = block["points_de_controle"]
                logger.info(f"[PCGen] ✅ Trouvé {len(cps)} PC dans bloc {i+1}")

                for cp in cps:
                    # 🔍 LOG AVANT NETTOYAGE pour voir ce que l'AI a retourné
                    logger.debug(f"[PCGen] 🔍 PC brut de l'AI: criticality_level={cp.get('criticality_level')}, estimated_effort_hours={cp.get('estimated_effort_hours')}")

                    # Nettoyer le PC
                    cleaned = self._clean_control_point(cp)

                    # 🔍 LOG APRÈS NETTOYAGE pour voir si les champs sont préservés
                    logger.debug(f"[PCGen] ✅ PC nettoyé: code={cleaned.get('code')}, criticality={cleaned.get('criticality')}, effort={cleaned.get('estimated_effort_hours')}")

                    all_cps.append(cleaned)

                    # Créer les mappings
                    req_codes = cp.get("exigences_liees", [])
                    if isinstance(req_codes, str):
                        req_codes = [req_codes]

                    logger.debug(f"[PCGen]   PC '{cleaned.get('code')}' lié à {len(req_codes)} exigences")

                    for req_code in req_codes:
                        all_mappings.append({
                            "control_point_code": cleaned.get("code"),
                            "requirement_code": req_code
                        })
            
            # Cas 2: Bloc direct de PC
            elif "code" in block and "titre" in block:
                logger.info(f"[PCGen] ✅ Trouvé 1 PC direct dans bloc {i+1}")
                cleaned = self._clean_control_point(block)
                all_cps.append(cleaned)
                
                req_codes = block.get("exigences_liees", [])
                if isinstance(req_codes, str):
                    req_codes = [req_codes]
                
                for req_code in req_codes:
                    all_mappings.append({
                        "control_point_code": cleaned.get("code"),
                        "requirement_code": req_code
                    })
            
            else:
                logger.warning(f"[PCGen] ⚠️ Bloc {i+1} non reconnu: {list(block.keys())}")
        
        logger.info(f"[PCGen] 📊 Total extrait: {len(all_cps)} PC, {len(all_mappings)} mappings")
        
        return all_cps, all_mappings

    async def generate_from_framework(
        self,
        framework: Optional[Dict[str, Any]],
        requirements: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Point d'entrée depuis l'API: enveloppe un petit contexte framework.
        """
        if not self.ai_enabled:
            raise RuntimeError("IA désactivée — génération impossible.")
        ctx = {
            "framework": {
                "id": (framework or {}).get("id"),
                "code": (framework or {}).get("code"),
                "name": (framework or {}).get("name"),
                "locale": (framework or {}).get("locale", "fr"),
            }
        }
        return await self.generate(requirements=requirements, context=ctx)

    async def generate(
        self,
        requirements: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None,
        db: Optional[Session] = None,
        progress_callback: Optional[Any] = None,  # Callback pour progression SSE
    ) -> Dict[str, Any]:
        """
        Génère les PC par lots, répare/sanétise les sorties IA,
        applique les fallbacks (lot + global), puis nettoie et retourne le résultat.

        Args:
            progress_callback: Fonction async(batch_idx, total_batches, status, data) pour SSE
        """
        if not requirements:
            return {
                "control_points": [],
                "mappings": [],
                "true_uncovered_requirement_ids": [],
                "uncovered_after_fallback": [],
            }
        if not self.ollama_url or not self.ai_enabled:
            raise RuntimeError("IA non disponible ou désactivée – génération impossible.")

        logger.info(f"[PCGen] lancement sur {len(requirements)} exigences (batch={self.batch_size})")

        # remise à zéro du cumul
        self._result = {
            "control_points": [],
            "mappings": [],
            "true_uncovered_requirement_ids": [],
        }

        # découpes en lots
        batches = list(self._chunks(requirements, self.batch_size))
        total_batches = len(batches)

        # Callback initial
        if progress_callback:
            await progress_callback(0, total_batches, "started", {
                "total_requirements": len(requirements),
                "total_batches": total_batches,
                "batch_size": self.batch_size
            })

        # boucle des lots
        for idx, batch in enumerate(batches, start=1):
            prompt = self._build_prompt_for_batch(batch, context or {})
            logger.info(f"[PCGen] ▶️ lot {idx}/{total_batches} size={len(batch)} prompt_chars={len(prompt)}")

            # Callback avant traitement du lot
            if progress_callback:
                await progress_callback(idx, total_batches, "processing", {
                    "batch_index": idx,
                    "batch_size": len(batch),
                    "current_cps": len(self._result["control_points"])
                })

            raw = await self._call_deepseek_with_retry(prompt, self.num_predict)

            local = await self._parse_normalize_and_check(
                raw_content=raw,
                lot_requirements=batch,
                lot_idx=idx,
                lot_count=total_batches,
            )
            self._result["control_points"].extend(local["control_points"])
            self._result["mappings"].extend(local["mappings"])

            # Callback après traitement du lot
            if progress_callback:
                await progress_callback(idx, total_batches, "batch_complete", {
                    "batch_index": idx,
                    "new_cps": len(local["control_points"]),
                    "total_cps": len(self._result["control_points"]),
                    "progress_percent": int((idx / total_batches) * 100)
                })

        # dédup globale des PC
        cps_final, ref_alias = self._dedup_control_points(self._result["control_points"])

        # ✅ LOG pour voir ce qui est dans cps_final
        logger.debug(f"[PCGen] Nombre de PC distincts après déduplication: {len(cps_final)}")
        logger.debug(f"[PCGen] Premiers cp_ref: {[cp.get('cp_ref') for cp in cps_final[:10]]}")

        # Propagation alias sur mappings
        mappings_final: List[Dict[str, str]] = []
        for m in self._result["mappings"]:
            rid = str(m.get("requirement_id"))
            cp_ref = m.get("cp_ref")
            if not rid or not cp_ref:
                continue
            cp_ref = ref_alias.get(cp_ref, cp_ref)
            mappings_final.append({"requirement_id": rid, "cp_ref": cp_ref})

        # couverture globale + deuxième passe IA si nécessaire
        required_ids = {str(r.get("id")) for r in requirements if r.get("id")}
        mapped_ids = {m["requirement_id"] for m in mappings_final}
        missing_global = list(required_ids - mapped_ids)

        if missing_global:
            logger.warning(
                f"[PCGen] Couverture partielle après agrégation – {len(missing_global)} exigence(s) non mappée(s) "
                f"(ex: {missing_global[:5]}...)"
            )
            # on consigne les orphelines 'avant deuxième passe' pour l'UI (preview)
            self._result.setdefault("true_uncovered_requirement_ids", [])
            self._result["true_uncovered_requirement_ids"].extend(missing_global)

            # ✅ DEUXIÈME PASSE IA POUR LES EXIGENCES MANQUANTES
            logger.info(f"[PCGen] 🔄 Lancement de la deuxième passe IA pour {len(missing_global)} exigences manquantes...")

            # Callback pour informer du démarrage de la deuxième passe
            if progress_callback:
                await progress_callback(total_batches, total_batches, "second_pass_started", {
                    "missing_count": len(missing_global),
                    "message": f"Deuxième passe IA pour {len(missing_global)} exigences non couvertes..."
                })

            # Récupérer les exigences manquantes
            missing_requirements = [r for r in requirements if str(r.get("id")) in missing_global]

            if missing_requirements:
                try:
                    # Générer les PCs pour les exigences manquantes
                    second_pass_result = await self._generate_second_pass(missing_requirements, context)

                    if second_pass_result:
                        second_pass_cps = second_pass_result.get("control_points", [])
                        second_pass_mappings = second_pass_result.get("mappings", [])

                        logger.info(f"[PCGen] ✅ Deuxième passe: {len(second_pass_cps)} PC générés")

                        # Ajouter les nouveaux PCs
                        for cp in second_pass_cps:
                            # Éviter les doublons de code
                            new_ref = cp.get("cp_ref", "")
                            if new_ref and new_ref not in {c.get("cp_ref") for c in cps_final}:
                                cps_final.append(cp)

                        # Ajouter les nouveaux mappings
                        for m in second_pass_mappings:
                            rid = m.get("requirement_id")
                            cp_ref = m.get("cp_ref")
                            if rid and cp_ref:
                                mappings_final.append({"requirement_id": str(rid), "cp_ref": cp_ref})

                        # Callback pour informer de la fin de la deuxième passe
                        if progress_callback:
                            await progress_callback(total_batches, total_batches, "second_pass_complete", {
                                "new_cps": len(second_pass_cps),
                                "total_cps": len(cps_final),
                                "message": f"Deuxième passe terminée: {len(second_pass_cps)} PC supplémentaires générés"
                            })

                except Exception as e:
                    logger.error(f"[PCGen] ❌ Erreur deuxième passe IA: {e}")
                    # Ne pas générer de fallback automatique - laisser les exigences non couvertes
                    logger.warning(f"[PCGen] ⚠️ {len(missing_global)} exigences resteront non couvertes")

                    # Callback pour informer de l'erreur
                    if progress_callback:
                        await progress_callback(total_batches, total_batches, "second_pass_error", {
                            "error": str(e),
                            "message": f"Erreur deuxième passe: {len(missing_global)} exigences non couvertes"
                        })

        # recalcul après deuxième passe
        mapped_ids = {m["requirement_id"] for m in mappings_final}
        uncovered_after_fallback = list(required_ids - mapped_ids)

        if uncovered_after_fallback:
            logger.warning(
                f"[PCGen] ⚠️ ATTENTION: {len(uncovered_after_fallback)} exigences restent non couvertes après 2 passes IA. "
                f"Codes: {[reqs_index.get(rid, {}).get('official_code', rid) for rid in uncovered_after_fallback[:10]]}"
            )

        # reconstruire les exigences par CP pour l'UI
        reqs_index = {str(r.get("id")): r for r in requirements if r.get("id")}
        reqs_by_cp: Dict[str, list] = {}
        for m in mappings_final:
            ref = m["cp_ref"]
            rid = m["requirement_id"]
            reqs_by_cp.setdefault(ref, []).append(rid)

        # nettoyage qualité pour l'UI
        cleaned_cps: List[Dict[str, Any]] = []
        for cp in cps_final:
            ref = cp.get("cp_ref")
            if not ref:
                continue

            mapped_rids = reqs_by_cp.get(ref, [])
            if not mapped_rids:
                continue

            title = (cp.get("title") or "").strip()
            desc = (cp.get("description") or "").strip()
            dom = (cp.get("domain") or cp.get("category") or "").strip()

            # Si titre est générique/vide → reconstruire depuis l'exigence
            if (not title) or (title.lower() == "domaine") or self._is_uuidish(title) or self._looks_gibberish(title):
                # Prendre la première exigence mappée
                first_rid = mapped_rids[0]
                req = reqs_index.get(first_rid)
                if req:
                    title = self._make_specific_title_from_requirement(req)
                    logger.info(f"[PCGen] 🔧 Titre reconstruit pour {ref}: '{title}'")
                else:
                    title = f"Contrôle {ref}"

            # Normaliser domaine
            if not dom or self._is_uuidish(dom) or self._looks_gibberish(dom) or dom == "—":
                # Tenter de récupérer depuis la première exigence
                first_rid = mapped_rids[0]
                req = reqs_index.get(first_rid)
                if req:
                    dom = req.get("domain") or req.get("domain_name") or "—"

            # Bornes et espaces
            title = re.sub(r"\s+", " ", title)[:180]
            desc = re.sub(r"\s+", " ", desc)[:800] if desc else ""
            dom = re.sub(r"\s+", " ", str(dom))[:80] if dom else "—"

            # AI confidence
            conf = cp.get("ai_confidence", 0.0)
            try:
                conf = float(conf)
            except Exception:
                conf = 0.0
            conf = min(max(conf, 0.0), 1.0)

            cleaned_cps.append({
                **cp,
                "title": title,
                "description": desc,
                "domain": dom,
                "ai_confidence": conf,
            })

        cps_final = cleaned_cps

        # ✅ LOG final pour voir le résultat
        logger.info(
            f"[PCGen] ✅ terminé: batches={total_batches}, cps={len(cps_final)}, mappings={len(mappings_final)}, "
            f"orphelines_avant={len(set(self._result['true_uncovered_requirement_ids']))}, "
            f"orphelines_apres={len(uncovered_after_fallback)}"
        )
        
        logger.debug(f"[PCGen] ✅ {len(cps_final)} PC finaux prêts pour insertion en BDD")
        logger.debug(f"[PCGen] Premiers PC finaux: {[cp.get('cp_ref') for cp in cps_final[:5]]}")

        # ✅✅✅ FUSION DES MAPPINGS DANS LES PC ✅✅✅
        # ========== AJOUTER CES LIGNES ICI ==========
        # Regrouper les requirement_ids par cp_ref
        mappings_by_cp_ref = {}
        for m in mappings_final:
            cp_ref = m.get("cp_ref")
            req_id = m.get("requirement_id")
            if cp_ref and req_id:
                if cp_ref not in mappings_by_cp_ref:
                    mappings_by_cp_ref[cp_ref] = []
                mappings_by_cp_ref[cp_ref].append(req_id)
        
        # Ajouter mapped_requirements à chaque PC
        for cp in cps_final:
            cp_ref = cp.get("cp_ref")
            if cp_ref:
                cp["mapped_requirements"] = mappings_by_cp_ref.get(cp_ref, [])
            else:
                cp["mapped_requirements"] = []
        
        logger.info(
            f"[PCGen] 📊 Mappings fusionnés dans les PC: "
            f"{sum(len(mappings_by_cp_ref.get(cp.get('cp_ref'), [])) for cp in cps_final)} liaisons"
        )
        # ========== FIN FUSION ==========

        return {
            "control_points": cps_final,
            "mappings": mappings_final,
            "true_uncovered_requirement_ids": list(set(self._result.get("true_uncovered_requirement_ids", []))),
            "uncovered_after_fallback": uncovered_after_fallback,
        }
    # ---------------------------
    #       IA / PROMPTS
    # ---------------------------

    def _build_prompt_for_batch(self, requirements_batch: List[Dict[str, Any]], context: Dict[str, Any]) -> str:
        """
        Construit le prompt pour un batch d'exigences.
        Version optimisée pour DeepSeek avec couverture 100% obligatoire.
        """
        # Construire la liste des exigences
        reqs_text = ""
        req_ids_list = []
        for i, req in enumerate(requirements_batch, 1):
            code = req.get("official_code") or req.get("code", f"REQ-{i}")
            text = req.get("text") or req.get("description", "")
            req_id = req.get("id", f"req-{i}")
            req_ids_list.append(req_id)
            reqs_text += f"{i}. **{code}** (ID: {req_id})\n   {text}\n\n"

        prompt = f"""Tu es un expert en cybersécurité et conformité ISO 27001/27002.

🎯 **MISSION CRITIQUE : COUVERTURE 100% OBLIGATOIRE**

Tu dois générer des points de contrôle pour les {len(requirements_batch)} exigences ci-dessous.

⚠️ **RÈGLE ABSOLUE** : CHAQUE exigence DOIT avoir AU MOINS UN point de contrôle.
- Exigences SMSI (clauses 4.x, 5.x, 6.x, 7.x, 8.x, 9.x, 10.x) = exigences organisationnelles du système de management
- Exigences Annexe A (A.x.x) = contrôles de sécurité techniques et opérationnels

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📋 EXIGENCES À TRAITER ({len(requirements_batch)} au total) :

{reqs_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 FORMAT JSON OBLIGATOIRE :

```json
{{
  "control_points": [
    {{
      "cp_ref": "CP-<CODE_EXIGENCE>-001",
      "title": "Titre actionnable du contrôle (verbe + objet)",
      "description": "Description détaillée de ce qui doit être vérifié/audité (100-200 caractères)",
      "domain": "Catégorie du contrôle",
      "criticality_level": "LOW|MEDIUM|HIGH|CRITICAL",
      "estimated_effort_hours": 4,
      "ai_confidence": 0.85,
      "rationale": "Justification de la pertinence du contrôle",
      "requirement_ids": ["<UUID_EXIGENCE>"]
    }}
  ],
  "mappings": [
    {{"requirement_id": "<UUID_EXIGENCE>", "cp_ref": "CP-<CODE>-001"}}
  ]
}}
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔥 **RÈGLES STRICTES** :

1. **COUVERTURE 100%** : Chaque ID d'exigence ({', '.join(req_ids_list[:3])}...) DOIT apparaître dans au moins un mapping
2. **NOMMAGE** : cp_ref doit refléter le code de l'exigence (ex: CP-4.1-001 pour exigence 4.1, CP-A.5.15-001 pour A.5.15)
3. **TITRE ACTIONNABLE** : Commencer par un verbe (Vérifier, Contrôler, Auditer, S'assurer, Documenter, etc.)
4. **CRITICITÉ VARIÉE** : Adapter selon l'impact (CRITICAL pour données sensibles, HIGH pour sécurité, MEDIUM pour organisation, LOW pour documentation)
5. **EFFORT RÉALISTE** : 2-4h (simple), 6-12h (standard), 16-24h (complexe), 40-80h (projet)
6. **CONFIANCE IA** : 0.7-0.95 selon la clarté de l'exigence
7. **1-2 PC MAX** par exigence (éviter la sur-génération)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🏷️ **CATÉGORIES DE DOMAINES** :

Pour les clauses SMSI (4-10) :
- "Contexte et périmètre" (clause 4)
- "Leadership et engagement" (clause 5)
- "Planification et risques" (clause 6)
- "Support et ressources" (clause 7)
- "Fonctionnement opérationnel" (clause 8)
- "Évaluation des performances" (clause 9)
- "Amélioration continue" (clause 10)

Pour l'Annexe A :
- "Politiques de sécurité"
- "Organisation de la sécurité"
- "Sécurité des ressources humaines"
- "Gestion des actifs"
- "Contrôle d'accès"
- "Cryptographie"
- "Sécurité physique"
- "Sécurité des opérations"
- "Sécurité des communications"
- "Acquisition et développement"
- "Relations fournisseurs"
- "Gestion des incidents"
- "Continuité d'activité"
- "Conformité"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️ **VALIDATION FINALE** :

Avant de répondre, vérifie que :
✅ Chaque exigence a au moins un PC assigné
✅ Tous les IDs d'exigences apparaissent dans les mappings
✅ Le JSON est valide et complet
✅ Les criticités sont variées (pas tout en MEDIUM)
✅ Les efforts sont réalistes et variés

❌ **INTERDIT** :
- Ignorer une exigence
- Créer des PC génériques sans lien avec l'exigence
- Mettre la même criticité/effort pour tout
- Répondre autre chose que du JSON valide

Réponds UNIQUEMENT avec le JSON valide et complet.
"""

        return prompt

    def _clean_control_point(self, cp: Dict[str, Any]) -> Dict[str, Any]:
        """
        Nettoie et normalise un point de contrôle.
        """
        # Mapper les anciens noms vers les nouveaux
        field_mapping = {
            "cp_ref": "code",
            "title": "titre",
            "domain": "domaine",
            "ai_confidence": None  # Ignorer
        }

        cleaned = {}

        for old_key, new_key in field_mapping.items():
            if new_key and old_key in cp:
                cleaned[new_key] = cp[old_key]

        # Copier les champs déjà au bon format
        for key in ["code", "titre", "description", "domaine", "criticality", "criticality_level", "estimated_effort_hours", "exigences_liees"]:
            if key in cp and key not in cleaned:
                cleaned[key] = cp[key]

        # ⚠️ Mapper criticality_level → criticality si nécessaire (pour compatibilité avec DB)
        if "criticality_level" in cp and "criticality" not in cleaned:
            cleaned["criticality"] = cp["criticality_level"]

        # ⚠️ Préserver estimated_effort_hours depuis la réponse AI
        if "estimated_effort_hours" in cp:
            cleaned["estimated_effort_hours"] = cp["estimated_effort_hours"]

        # Valeurs par défaut
        if "code" not in cleaned:
            cleaned["code"] = cp.get("cp_ref", f"PC-{uuid4().hex[:8]}")

        if "titre" not in cleaned:
            cleaned["titre"] = cp.get("title", "Point de contrôle")

        if "description" not in cleaned:
            cleaned["description"] = cp.get("description", "")

        if "domaine" not in cleaned:
            cleaned["domaine"] = cp.get("domain", "Général")

        # ⚠️ SEULEMENT appliquer les defaults si VRAIMENT absents de la réponse AI
        if "criticality" not in cleaned and "criticality_level" not in cp:
            cleaned["criticality"] = "MEDIUM"

        # ⚠️ Default pour estimated_effort_hours si absent
        if "estimated_effort_hours" not in cleaned:
            cleaned["estimated_effort_hours"] = 4
        
        if "exigences_liees" not in cleaned:
            # Essayer d'extraire depuis le code
            code = cleaned.get("code", "")
            if code.startswith("PC-") and "-" in code:
                parts = code.split("-")
                if len(parts) >= 2:
                    req_code = "-".join(parts[1:-1])  # Ex: PC-A.13.1.3-001 → A.13.1.3
                    cleaned["exigences_liees"] = [req_code]
                else:
                    cleaned["exigences_liees"] = []
            else:
                cleaned["exigences_liees"] = []
        
        return cleaned

    # ---------------------------
    #      CALL DEEPSEEK
    # ---------------------------

        # ---------------------------
    #      CALL DEEPSEEK
    # ---------------------------

    async def _call_deepseek_with_retry(
        self,
        prompt: str,
        max_tokens: int = 4000,
        retry_count: int = 0
    ) -> str:
        """
        Appelle DeepSeek via Ollama avec retry automatique.
        """
        if retry_count >= self.max_retries:
            # ❌ ANCIEN CODE
            # raise HTTPException(
            #     status_code=503,
            #     detail=f"Échec DeepSeek après {self.max_retries} tentatives"
            # )
            
            # ✅ NOUVEAU CODE
            raise RuntimeError(
                f"Échec DeepSeek après {self.max_retries} tentatives"
            )
        
        try:
            messages = [{"role": "user", "content": prompt}]
            
            response = await self._call_ollama_chat(
                messages=messages,
                system_prompt=None,
                retry_count=0
            )
            
            content = response.get("message", {}).get("content", "")
            
            if not content:
                logger.warning(f"[PCGen] Réponse vide, retry {retry_count + 1}/{self.max_retries}")
                await asyncio.sleep(2)
                return await self._call_deepseek_with_retry(prompt, max_tokens, retry_count + 1)
            
            return content
            
        except Exception as e:
            logger.error(f"[PCGen] Erreur appel DeepSeek: {e}")
            
            if retry_count < self.max_retries - 1:
                logger.warning(f"[PCGen] Retry {retry_count + 1}/{self.max_retries}")
                await asyncio.sleep(2)
                return await self._call_deepseek_with_retry(prompt, max_tokens, retry_count + 1)
            else:
                # ✅ RuntimeError au lieu de HTTPException
                raise RuntimeError(f"Échec DeepSeek: {str(e)}")


    # ---------------------------
    #    JSON: CLEAN & REPAIR
    # ---------------------------

    def _clean_json_response(self, s: str) -> str:
        if not s:
            return ""
        s = s.strip()
        s = re.sub(r"<think>.*?</think>", "", s, flags=re.DOTALL)
        s = re.sub(r"^```(?:json)?", "", s, flags=re.IGNORECASE).strip("` \n\r")
        first, last = s.find("{"), s.rfind("}")
        if first != -1 and last != -1 and last > first:
            s = s[first : last + 1]
        s = s.replace("\n", " ").replace("\r", " ")
        s = s.replace("“", '"').replace("”", '"').replace("’", "'")
        return s

    async def _repair_json_via_model(self, broken: str) -> str:
        """
        Demande au modèle de reformater en JSON minifié STRICTEMENT VALIDE selon le schéma.
        """
        system = (
            "Tu es un validateur JSON. "
            "Reformate UNIQUEMENT la donnée ci-dessous en UN SEUL objet JSON MINIFIÉ, STRICTEMENT VALIDE "
            "et CONFORME au schéma: "
            '{"control_points":[{"cp_ref":"CP-001","title":"...","description":"...","domain":"..."}],'
            '"mappings":[{"requirement_id":"<RID>","cp_ref":"CP-001"}]} '
            "Aucun texte hors JSON."
        )
        user = "Donnée à réparer (ne pas inventer, corriger seulement la syntaxe et les clés): " + broken[:4000]
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "format": "json",
            "options": {
                "num_ctx": int(self.num_ctx),
                "num_predict": 128,
                "temperature": 0,
                "stop": ["<think>", "</think>", "```"],
            },
        }
        timeout = httpx.Timeout(connect=30.0, read=self.timeout, write=30.0, pool=30.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{self.ollama_url}/api/chat", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return (data.get("message") or {}).get("content", "") or ""

    async def _safe_json_extract(self, content: str) -> dict:
        """
        Extrait et parse le JSON de manière robuste, même si incomplet/tronqué.
        """
        import json
        from json_repair import repair_json
        
        # 1. Nettoyer le contenu
        cleaned = self._clean_json_response(content)
        
        # 2. Tenter le parsing direct
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass
        
        # 3. Tenter la réparation avec json-repair
        try:
            repaired = repair_json(cleaned)
            return json.loads(repaired)
        except Exception as e:
            logger.error(f"[PCGen] Impossible de parser/réparer le JSON: {e}")
            return {}

    def _desperate_sanitize_json(self, s: str) -> str:
        """
        Dernier filet de sécurité :
        - isole le plus grand bloc {...}
        - corrige identifiants non quotés fréquents
        - supprime virgules finales avant } ou ]
        - remplace quotes typographiques
        - si absent des clés attendues, renvoie squelette minimal
        """
        if not s:
            return '{"control_points":[],"mappings":[]}'

        s = s.replace("\r", " ").replace("\n", " ")
        s = s.replace("“", '"').replace("”", '"').replace("’", "'")

        first, last = s.find("{"), s.rfind("}")
        if first == -1 or last == -1 or last <= first:
            return '{"control_points":[],"mappings":[]}'

        s = s[first : last + 1]

        # identifiants non quotés -> quotes
        s = re.sub(r':\s*([A-Za-z_][A-Za-z0-9_\-]*)\s*([,}])', r':"\1"\2', s)

        # supprimer virgules traînantes
        s = re.sub(r",\s*([}\]])", r"\1", s)

        # supprimer éventuels code fences résiduels
        s = re.sub(r"^```(?:json)?", "", s, flags=re.IGNORECASE).strip("` ")

        if '"control_points"' not in s and '"mappings"' not in s and '"points"' not in s:
            return '{"control_points":[],"mappings":[]}'

        return s

    # ---------------------------
    #   SCHEMA & NORMALISATION
    # ---------------------------

    def _coalesce(self, d: Dict[str, Any], keys: List[str]) -> Any:
        for k in keys:
            if k in d and d[k] is not None:
                return d[k]
        return None

    def _coerce_schema(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Accepte des variantes (points, items, pcs, controls...) et (mappings, links...).
        Remet au schéma {"control_points": [...], "mappings": [...]}.
        """
        if not isinstance(data, dict):
            return {"control_points": [], "mappings": []}

        cp_keys = ["control_points", "points", "items", "pcs", "controls", "controlPoints"]
        map_keys = ["mappings", "links", "associations", "relations", "map"]

        cps = None
        for k in cp_keys:
            v = data.get(k)
            if isinstance(v, list):
                cps = v
                break
            if isinstance(v, dict):
                cps = list(v.values())
                break

        maps = None
        for k in map_keys:
            v = data.get(k)
            if isinstance(v, list):
                maps = v
                break
            if isinstance(v, dict):
                maps = list(v.values())
                break

        if cps is None:
            cps = []
        if maps is None:
            maps = []

        out_cps: List[Dict[str, Any]] = []
        out_maps: List[Dict[str, Any]] = []

        # Certains modèles mettent requirement_id directement dans le CP
        for cp in cps:
            if not isinstance(cp, dict):
                continue
            rid = self._coalesce(cp, ["requirement_id", "rid", "requirement", "req", "requirementId"])
            cref = self._coalesce(cp, ["cp_ref", "ref", "id", "code", "control", "control_ref"])
            if rid and cref:
                out_maps.append({"requirement_id": str(rid), "cp_ref": str(cref)})
                for k in ["requirement_id", "rid", "requirement", "req", "requirementId"]:
                    cp.pop(k, None)
            out_cps.append(cp)

        for m in maps:
            if not isinstance(m, dict):
                continue
            mrid = self._coalesce(m, ["requirement_id", "rid", "requirement", "req", "requirementId"])
            mref = self._coalesce(m, ["cp_ref", "ref", "id", "code", "control", "control_ref"])
            if mrid and mref:
                out_maps.append({"requirement_id": str(mrid), "cp_ref": str(mref)})

        return {"control_points": out_cps, "mappings": out_maps}

    def _make_ref_from_title(self, title: str) -> str:
        base = re.sub(r"[^A-Za-z0-9]+", "-", title.strip().upper()).strip("-")
        base = base[:12] if base else f"GEN-{uuid4().hex[:6].upper()}"
        if not base.startswith("CP-"):
            base = f"CP-{base}"
        return base

    def _normalize_control_points(
        self, cps: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
        """
        Normalise les champs d'un PC, fabrique une ref si absente, borne les longueurs,
        et renvoie aussi une table d'alias (ancien_ref -> ref_normalisée).
        """
        out: List[Dict[str, Any]] = []
        alias_map: Dict[str, str] = {}

        def _desc_to_str(v: Any) -> str:
            if isinstance(v, str):
                return v
            if isinstance(v, dict):
                for val in v.values():
                    if isinstance(val, str) and val.strip():
                        return val
                    if isinstance(val, list):
                        for x in val:
                            if isinstance(x, str) and x.strip():
                                return x
            if isinstance(v, list):
                parts = [x.strip() for x in v if isinstance(x, str) and x.strip()]
                if parts:
                    return " ".join(parts)
            if v is None:
                return ""
            return str(v)

        for cp in cps:
            if not isinstance(cp, dict):
                continue

            # 🔍 LOG AVANT NORMALISATION pour voir ce que l'AI a retourné
            logger.debug(f"[PCGen] 🔍 PC brut de l'AI: criticality_level={cp.get('criticality_level')}, estimated_effort_hours={cp.get('estimated_effort_hours')}")

            raw_title = self._coalesce(cp, ["title", "name", "label"])
            if isinstance(raw_title, dict):  # parfois multi-lang
                raw_title = next((v for v in raw_title.values() if isinstance(v, str) and v.strip()), "")
            raw_desc = self._coalesce(cp, ["description", "details", "desc"])
            raw_domain = self._coalesce(cp, ["domain", "category"])
            raw_ref = self._coalesce(cp, ["cp_ref", "ref", "id", "code"])

            title = (raw_title or "").strip()
            desc = _desc_to_str(raw_desc).strip()
            dom = (raw_domain or "").strip()
            cp_ref = (str(raw_ref) if raw_ref is not None else "").strip()

            if not cp_ref and title:
                cp_ref = self._make_ref_from_title(title)

            norm_ref = cp_ref.upper().replace(" ", "-")
            norm_ref = re.sub(r"[^A-Z0-9\-]", "", norm_ref)
            if norm_ref and not norm_ref.startswith("CP-"):
                if norm_ref.startswith("CP") and not norm_ref.startswith("CP-"):
                    norm_ref = "CP-" + norm_ref[2:]
                else:
                    norm_ref = f"CP-{norm_ref}"
            if not norm_ref:
                if title:
                    norm_ref = self._make_ref_from_title(title)
                else:
                    continue

            if not title and desc:
                dot = desc.find(".")
                title = desc[:dot].strip()[:80] if dot != -1 else desc[:80].strip()
            if not title:
                title = f"Contrôle {norm_ref}"

            title = re.sub(r"\s+", " ", title)[:180]
            desc = re.sub(r"\s+", " ", desc)[:800] if desc else ""
            dom = re.sub(r"\s+", " ", dom)[:80] if dom else ""

            # ⚠️ IMPORTANT: Préserver TOUS les champs du PC original, pas seulement les 4 de base
            normalized_cp = dict(cp)  # Copier tous les champs originaux
            normalized_cp.update({
                "cp_ref": norm_ref,
                "title": title,
                "description": desc,
                "domain": dom
            })

            # 🔍 LOG APRÈS NORMALISATION pour voir si les champs sont préservés
            logger.debug(f"[PCGen] ✅ PC normalisé: cp_ref={norm_ref}, criticality_level={normalized_cp.get('criticality_level')}, effort={normalized_cp.get('estimated_effort_hours')}")

            out.append(normalized_cp)

            if cp_ref and cp_ref != norm_ref:
                alias_map[cp_ref] = norm_ref

        # ne pas lever si vide : l’étape AUTO rattrapera
        return out, alias_map

    def _dedup_control_points(
        self, cps: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
        """
        Déduplique par cp_ref. Conserve les champs les plus “riches”.
        """
        seen: Dict[str, Dict[str, Any]] = {}
        alias: Dict[str, str] = {}
        for cp in cps:
            ref = cp.get("cp_ref")
            if not ref:
                continue
            if ref not in seen:
                seen[ref] = dict(cp)
            else:
                s = seen[ref]
                if len(cp.get("title", "")) > len(s.get("title", "")):
                    s["title"] = cp.get("title", s.get("title", ""))
                if len(cp.get("description", "")) > len(s.get("description", "")):
                    s["description"] = cp.get("description", s.get("description", ""))
                if len(cp.get("domain", "")) > len(s.get("domain", "")):
                    s["domain"] = cp.get("domain", s.get("domain", ""))
        return list(seen.values()), alias

    # ---------------------------
    #      PARSE & CONTROLES
    # ---------------------------

    def extract_json_from_markdown(raw_response: str) -> dict:
        """
        Extrait le premier bloc JSON d'une réponse markdown (```json ... ``` ou ``` ... ```).
        Si aucun bloc markdown, tente de parser tout le texte.
        Retourne un dict ou {} si échec.
        """
        import re
        import json

        # Cherche le bloc ```json ... ```
        match = re.search(r"```json\s*({.*?})\s*```", raw_response, re.DOTALL)
        if not match:
            # Cherche le bloc ``` ... ```
            match = re.search(r"```\s*({.*?})\s*```", raw_response, re.DOTALL)
        if match:
            json_str = match.group(1)
            try:
                return json.loads(json_str)
            except Exception:
                pass
        # Fallback : tente de parser tout le texte
        try:
            return json.loads(raw_response)
        except Exception:
            return {}

    async def _parse_normalize_and_check(
        self,
        raw_content: str,
        lot_requirements: List[Dict[str, Any]],
        lot_idx: int,
        lot_count: int,
    ) -> Dict[str, Any]:
        """
        Parse la réponse IA du lot, normalise, et mesure la couverture du lot.
        """
        try:
            data = await self._safe_json_extract(raw_content)
        except Exception:
            logger.error("[PCGen] JSON brut non parsable (2000 premiers chars): %s", (raw_content or "")[:2000])
            return {"control_points": [], "mappings": []}

        points = self._coerce_points_list(data)
        norm_cps, alias = self._normalize_control_points(points)

        # EXTRACTION DES MAPPINGS
        mappings: List[Dict[str, str]] = []
        
        # ✅ Utiliser 'code' comme ID (car 'id' est None)
        req_by_code = {}
        for req in lot_requirements:
            req_code = str(req.get("code", ""))
            if req_code:
                req_by_code[req_code] = req_code
                # Aussi avec les 8 premiers caractères
                req_by_code[req_code[:8]] = req_code
        
        logger.debug(f"[PCGen] req_by_code créé: {list(req_by_code.keys())[:10]}")
        
        # 1) Récupérer depuis data["mappings"]
        raw_mappings = data.get("mappings") or data.get("links") or data.get("map") or []
        if isinstance(raw_mappings, list):
            for m in raw_mappings:
                if not isinstance(m, dict):
                    continue
                rid_partial = str(m.get("requirement_id") or m.get("rid") or m.get("req") or "").strip()
                cp_ref = str(m.get("cp_ref") or m.get("ref") or m.get("control") or "").strip()
                
                if rid_partial and cp_ref:
                    rid_full = req_by_code.get(rid_partial, rid_partial)
                    cp_ref = alias.get(cp_ref, cp_ref)
                    mappings.append({"requirement_id": rid_full, "cp_ref": cp_ref})
        
        # 2) Fallback: depuis requirement_ids dans les PC
        for cp in points or []:
            cp_ref = (cp.get("cp_ref") or cp.get("ref") or cp.get("id") or cp.get("code") or "").strip()
            if not cp_ref:
                continue
            cp_ref = alias.get(cp_ref, cp_ref)

            rids = cp.get("requirement_ids") or cp.get("requirements") or cp.get("requirement_id") or []
            if not isinstance(rids, list):
                if rids:
                    rids = [rids]
                else:
                    rids = []
            
            for rid_partial in rids:
                rid_partial_s = str(rid_partial).strip()
                if rid_partial_s:
                    rid_full = req_by_code.get(rid_partial_s, rid_partial_s)
                    
                    if not any(m["requirement_id"] == rid_full and m["cp_ref"] == cp_ref for m in mappings):
                        mappings.append({"requirement_id": rid_full, "cp_ref": cp_ref})

        if mappings:
            logger.debug(f"[PCGen] Lot {lot_idx}: {len(mappings)} mappings extraits")
        else:
            logger.warning(f"[PCGen] ⚠️ Lot {lot_idx}: AUCUN mapping extrait de la réponse IA!")

        # ✅ Couverture basée sur 'code'
        batch_codes = {str(r["code"]) for r in lot_requirements if r.get("code")}
        mapped = {m["requirement_id"] for m in mappings if m.get("requirement_id") in batch_codes}
        missing = list(batch_codes - mapped)
        
        if missing:
            logger.warning(
                f"[PCGen] ⚠️ Lot {lot_idx}/{lot_count}: couverture partielle — "
                f"{len(missing)}/{len(batch_codes)} exigence(s) non mappée(s): {missing[:5]}"
            )
        else:
            logger.info(f"[PCGen] ✅ Lot {lot_idx}/{lot_count}: 100% couvert ({len(batch_codes)} exigences)")

        return {"control_points": norm_cps, "mappings": mappings}

    def _coerce_points_list(self, data: Any) -> List[Dict[str, Any]]:
        if not isinstance(data, dict):
            return []
        # Si le dict ne contient qu'une seule clé et que la valeur est un dict, retourne [valeur]
        if len(data) == 1:
            v = list(data.values())[0]
            if isinstance(v, dict):
                return [v]
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
        # Sinon, parcours les clés candidates
        candidates = (
            "points", "control_points", "items", "controls", "data", "result", "controle_iso_27002"
        )
        for key in candidates:
            if key not in data:
                continue
            v = data.get(key)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
            if isinstance(v, dict):
                return [v]
            if isinstance(v, str):
                s = v.strip()
                if s and s[0] in "[{":
                    try:
                        obj = json.loads(s)
                        if isinstance(obj, list):
                            return [x for x in obj if isinstance(x, dict)]
                        if isinstance(obj, dict):
                            for kk in candidates:
                                vv = obj.get(kk)
                                if isinstance(vv, list):
                                    return [x for x in vv if isinstance(x, dict)]
                                if isinstance(vv, dict):
                                    return [vv]
                    except Exception:
                        pass
        return []

    async def _generate_second_pass(
        self,
        missing_requirements: List[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Deuxième passe IA pour les exigences non couvertes.
        Utilise un prompt spécifique pour garantir la couverture.
        """
        if not missing_requirements:
            return {"control_points": [], "mappings": []}

        logger.info(f"[PCGen] 🔄 Deuxième passe: génération pour {len(missing_requirements)} exigences manquantes")

        # Construire un prompt spécifique pour les exigences manquantes
        reqs_text = ""
        req_ids_list = []
        for i, req in enumerate(missing_requirements, 1):
            code = req.get("official_code") or req.get("code", f"REQ-{i}")
            text = req.get("text") or req.get("requirement_text") or req.get("description", "")
            req_id = req.get("id", f"req-{i}")
            req_ids_list.append(str(req_id))
            reqs_text += f"{i}. **{code}** (ID: {req_id})\n   {text}\n\n"

        second_pass_prompt = f"""Tu es un expert en cybersécurité et conformité ISO 27001/27002.

⚠️ **MISSION CRITIQUE : COUVERTURE OBLIGATOIRE POUR EXIGENCES MANQUANTES**

Ces {len(missing_requirements)} exigences N'ONT PAS ÉTÉ COUVERTES lors de la première passe.
Tu DOIS ABSOLUMENT générer un point de contrôle pour CHACUNE d'entre elles.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📋 EXIGENCES NON COUVERTES :

{reqs_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🎯 **OBJECTIF** : Générer 1 point de contrôle pertinent pour CHAQUE exigence ci-dessus.

📊 FORMAT JSON OBLIGATOIRE :

```json
{{
  "control_points": [
    {{
      "cp_ref": "CP-<CODE_EXIGENCE>-001",
      "title": "Titre actionnable (verbe + objet)",
      "description": "Description de ce qui doit être vérifié (100-200 caractères)",
      "domain": "Catégorie du contrôle",
      "criticality_level": "LOW|MEDIUM|HIGH|CRITICAL",
      "estimated_effort_hours": 4,
      "ai_confidence": 0.80,
      "rationale": "Justification du contrôle",
      "requirement_ids": ["<UUID>"]
    }}
  ],
  "mappings": [
    {{"requirement_id": "<UUID>", "cp_ref": "CP-<CODE>-001"}}
  ]
}}
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️ **VÉRIFICATION OBLIGATOIRE** :

IDs des exigences à couvrir : {', '.join(req_ids_list)}

✅ CHAQUE ID ci-dessus DOIT apparaître dans les mappings
✅ Le cp_ref doit refléter le code de l'exigence (ex: CP-4.1-001, CP-5.2.a-001)
✅ Le titre doit être actionnable (verbe: Vérifier, Contrôler, Auditer, Documenter, etc.)

Réponds UNIQUEMENT avec le JSON valide et complet.
"""

        try:
            # Appeler l'IA
            response = await self._call_ollama_chat(
                messages=[{"role": "user", "content": second_pass_prompt}],
                retry_count=0
            )

            # Parser la réponse
            json_str = response.get("message", {}).get("content", "")
            if not json_str:
                logger.error("[PCGen] ❌ Deuxième passe: réponse vide de l'IA")
                return {"control_points": [], "mappings": []}

            # Nettoyer et parser le JSON
            json_str = json_str.strip()
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0].strip()
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0].strip()

            data = json.loads(json_str)

            # Extraire les PCs et mappings
            control_points = data.get("control_points", [])
            mappings = data.get("mappings", [])

            # Normaliser les PCs
            normalized_cps = []
            for cp in control_points:
                cp_ref = cp.get("cp_ref", "")
                if not cp_ref:
                    continue

                normalized_cps.append({
                    "cp_ref": cp_ref,
                    "title": cp.get("title", ""),
                    "description": cp.get("description", ""),
                    "domain": cp.get("domain", ""),
                    "criticality_level": cp.get("criticality_level", "MEDIUM"),
                    "estimated_effort_hours": cp.get("estimated_effort_hours", 8),
                    "ai_confidence": float(cp.get("ai_confidence", 0.8)),
                    "rationale": cp.get("rationale", ""),
                    "requirement_ids": cp.get("requirement_ids", []),
                })

            logger.info(f"[PCGen] ✅ Deuxième passe: {len(normalized_cps)} PC générés, {len(mappings)} mappings")

            # Vérifier la couverture
            mapped_ids = {str(m.get("requirement_id")) for m in mappings}
            still_missing = set(req_ids_list) - mapped_ids
            if still_missing:
                logger.warning(f"[PCGen] ⚠️ Deuxième passe: {len(still_missing)} exigences toujours non couvertes")

            return {"control_points": normalized_cps, "mappings": mappings}

        except json.JSONDecodeError as e:
            logger.error(f"[PCGen] ❌ Deuxième passe: erreur parsing JSON: {e}")
            return {"control_points": [], "mappings": []}
        except Exception as e:
            logger.error(f"[PCGen] ❌ Deuxième passe: erreur inattendue: {e}")
            return {"control_points": [], "mappings": []}

    def _build_fallback_cps(
        self,
        requirements: List[Dict[str, Any]],
        missing_ids: List[str],
        seed: int = 1,
    ) -> List[Dict[str, Any]]:
        """
        Construit des PC de secours spécifiques (1 PC par exigence orpheline).
        ⚠️ DÉPRÉCIÉ: Utiliser _generate_second_pass à la place pour de vrais PCs générés par IA.
        """
        req_by_id = {str(r.get("id")): r for r in requirements if r.get("id")}
        out: List[Dict[str, Any]] = []
        
        for idx, rid in enumerate(missing_ids, start=seed):
            r = req_by_id.get(str(rid))
            if not r:
                continue
            
            dom = r.get("domain") or r.get("domain_name") or r.get("domain_label") or "Général"
            subdom = r.get("subdomain") or r.get("sub_domain") or ""
            req_title = r.get("title") or "Sans titre"
            req_code = r.get("official_code") or r.get("code") or ""
            
            # Créer un titre explicite basé sur l'exigence
            title = f"Contrôle {req_code} - {req_title[:80]}" if req_code else f"Contrôle {dom} - {req_title[:80]}"
            
            out.append({
                "id": str(uuid4()),
                "cp_ref": f"AUTO.{dom[:3].upper()}.{idx:03d}",
                "code": f"AUTO-{dom[:3].upper()}-{idx:03d}",
                "title": title,
                "description": (
                    f"Point de contrôle automatique pour l'exigence '{req_title}'. "
                    f"Domaine : {dom}{(' > ' + subdom) if subdom else ''}. "
                    f"Ce contrôle nécessite une revue et un enrichissement manuel."
                ),
                "implementation_guidance": "Définir les modalités de vérification et d'audit spécifiques à cette exigence.",
                "criticality": "MEDIUM",
                "ai_confidence": 0.5,
                "ai_explanation": (
                    "PC de secours créé automatiquement car l'IA n'a pas pu générer un contrôle spécifique. "
                    "Une validation métier est requise."
                ),
                "mapped_requirements": [str(rid)],
                "mapped_requirements_details": [r],
                "status": "pending",
                "category": dom,
                "subcategory": subdom,
                "control_family": dom,
                "estimated_effort_hours": 4,
            })
        
        return out


    # ---------------------------
    #          UTIL
    # ---------------------------

    @staticmethod
    def _chunks(lst: List[Any], n: int) -> List[List[Any]]:
        n = max(1, int(n or 1))
        return [lst[i : i + n] for i in range(0, len(lst), n)]

    def _is_uuidish(self, s: str) -> bool:
        if not s:
            return False
        # ✅ Correction ici
        return bool(type(self).UUIDISH.match(s.strip()))

    def _looks_gibberish(self, s: str) -> bool:
        """
        Heuristique pour filtrer un "titre/domaine" inutilisable.
        """
        if not s:
            return True
        t = s.strip()
        if len(t) < 5:
            return True
        if self._is_uuidish(t):
            return True
        
        # Rejeter les titres génériques interdits
        generics = [
            "point de contrôle",
            "point de controle",
            "contrôle automatique",
            "controle automatique",
            "pc automatique",
            "mesures organisationnelles",
            "mesures physiques",
            "gestion de",
            "domaine",
            "sans titre",
        ]
        t_lower = t.lower()
        for g in generics:
            if t_lower == g or t_lower.startswith(g + " "):
                return True
        
        letters = sum(c.isalpha() for c in t)
        return (letters / max(len(t), 1)) < 0.4
    
    def _make_specific_title_from_requirement(self, req: Dict[str, Any]) -> str:
        """
        Construit un titre spécifique à partir de l'exigence.
        """
        req_title = (req.get("title") or "").strip()
        req_code = (req.get("official_code") or req.get("code") or "").strip()
        domain = (req.get("domain") or req.get("domain_name") or "").strip()
        subdomain = (req.get("subdomain") or req.get("subdomain_name") or "").strip()
        
        # Extraire les verbes d'action de l'exigence
        action_verbs = [
            "vérifier", "contrôler", "auditer", "s'assurer", "valider", 
            "surveiller", "documenter", "identifier", "évaluer", "tester",
            "mettre en place", "implémenter", "maintenir", "réviser"
        ]
        
        title_lower = req_title.lower()
        verb = "Contrôler"
        for v in action_verbs:
            if v in title_lower:
                verb = v.capitalize()
                break
        
        # Construire un titre actionnable
        if len(req_title) > 80:
            # Trouver une coupure naturelle
            short = req_title[:77]
            last_space = short.rfind(" ")
            if last_space > 40:
                short = short[:last_space]
            title = f"{verb} {short}..."
        else:
            # Reformuler pour commencer par un verbe
            if req_title.lower().startswith(("la ", "le ", "les ", "l'")):
                # "La gestion des..." → "Contrôler la gestion des..."
                title = f"{verb} {req_title.lower()}"
            else:
                title = f"{verb} : {req_title}"
        
        # Ajouter le code si disponible
        if req_code:
            title = f"[{req_code}] {title}"
        
        return title[:180]

