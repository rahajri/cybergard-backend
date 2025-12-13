# backend/src/services/deepseek_question_generator.py
"""
Service de génération de Questions d'audit via DeepSeek
Responsabilité unique : Génération de questions
L'assignation aux PC est déléguée au ControlPointMatcher
"""
import asyncio
import json
import logging
import re
from typing import List, Dict, Any, Optional, Tuple
import httpx

from uuid import uuid4
import httpx
from sqlalchemy.orm import Session
from sqlalchemy.sql import text
import os
from dotenv import load_dotenv

# ✅ Forcer le chargement du .env au démarrage
load_dotenv(override=True)

# Import json-repair for robust JSON parsing
try:
    from json_repair import repair_json
except ImportError:
    repair_json = None

try:
    from ..config import settings
except ImportError:
    from ..config import settings

try:
    from ..models.audit import Framework, Requirement, ControlPoint
except ImportError:
    from ..models.audit import Framework, Requirement, ControlPoint

try:
    from ..schemas.questionnaire import GeneratedQuestion, QuestionGenerationRequest
except ImportError:
    # Définition locale si schema non disponible
    from pydantic import BaseModel
    from typing import Literal
    
    class QuestionGenerationRequest(BaseModel):
        mode: str  # 'framework' ou 'control_points'
        framework_id: Optional[str] = None
        control_point_ids: Optional[List[str]] = None
        language: str = "fr"
        ai_params: Dict[str, Any] = {}
    
    class GeneratedQuestion(BaseModel):
        id: Optional[str] = None                    # si tu en génères un
        text: str                                   # énoncé de la question
        type: Literal["single_choice","multiple_choice","open","rating","boolean","number","date"] = "open"
        options: Optional[List[str]] = None         # pour choix
        control_point_id: Optional[str] = None
        requirement_ids: List[str] = []
        difficulty: Optional[str] = None            # ex: "easy" | "medium" | "hard"
        ai_confidence: Optional[float] = None
        rationale: Optional[str] = None
        tags: List[str] = []
        is_mandatory: bool = False                  # Question obligatoire
        upload_conditions: Optional[Dict[str, Any]] = None  # Conditions d'upload
        question_code: Optional[str] = None         # Code standardisé (ex: "ISO27001-A5.1-Q1")
        chapter: Optional[str] = None               # Chapitre/section (ex: "A.5", "A.6")
        evidence_types: List[str] = []              # Types de preuves suggérés
        estimated_time_minutes: Optional[int] = None  # Temps estimé (1-120 min)

logger = logging.getLogger(__name__)


class DeepSeekQuestionGenerator:
    """
    Génération de questions via IA ou fallback.
    Deux entrées distinctes :
      - generate_from_framework(framework: {...}, requirements: [...])
      - generate_from_control_points(control_points: [...])
    Les deux garantissent 1+ question par item (exigence/PC), avec relance ciblée si manquant.
    """
    
    # LIGNE 70-120 : REMPLACER SYSTEM_PROMPT

    SYSTEM_PROMPT = """Tu es un auditeur senior en cybersécurité avec 15 ans d'expérience terrain auprès de PME françaises.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 MISSION : GÉNÉRER DES QUESTIONS D'AUDIT RÉALISTES ET OPÉRATIONNELLES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️ RÈGLE ABSOLUE : Chaque question doit permettre de VÉRIFIER CONCRÈTEMENT une pratique/un dispositif
❌ INTERDIT : Questions théoriques, génériques ou qui ne demandent pas de PREUVES TANGIBLES

✅ PRINCIPES FONDAMENTAUX :

1️⃣ DEMANDER DES PREUVES CONCRÈTES
   ❌ "Avez-vous une politique de sauvegarde ?"
   ✅ "Quelle est la date de la dernière restauration de sauvegarde testée ?"
   ✅ "Combien de sauvegardes complètes ont été réalisées le mois dernier ?"

2️⃣ VÉRIFIER L'IMPLÉMENTATION RÉELLE
   ❌ "Existe-t-il une procédure de gestion des incidents ?"
   ✅ "Combien d'incidents de sécurité ont été enregistrés dans votre outil de ticketing en 2024 ?"
   ✅ "Quel est le délai moyen de traitement d'un incident de sécurité ?"

3️⃣ MESURER, PAS SUPPOSER
   ❌ "Les mots de passe sont-ils sécurisés ?"
   ✅ "Quelle est la longueur minimale imposée pour les mots de passe des comptes administrateurs ?"
   ✅ "Combien de comptes ont encore un mot de passe expiré depuis plus de 90 jours ?"

4️⃣ DEMANDER DES NOMS, DATES, VERSIONS
   ❌ "Utilisez-vous un antivirus ?"
   ✅ "Quel antivirus est déployé sur les postes de travail (nom et version) ?"
   ✅ "Quelle est la date de la dernière mise à jour des signatures antivirus ?"

5️⃣ CIBLER LES TRACES ET JOURNAUX
   ❌ "Surveillez-vous les accès ?"
   ✅ "Où sont stockés les journaux d'authentification (chemin du serveur/service) ?"
   ✅ "Quelle est la durée de rétention configurée pour les logs d'accès ?"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 DISTRIBUTION CIBLE DES TYPES DE QUESTIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️ VARIE LES TYPES ! Ne génère PAS que des yes_no !

🎯 DISTRIBUTION RECOMMANDÉE (pour un lot de 10 questions) :
- 20% boolean       → 2 questions binaires (existence de document/processus)
- 30% single_choice → 3 questions à choix unique (fréquence, niveau de maturité)
- 20% open          → 2 questions ouvertes (description de processus, liste d'outils)
- 15% number        → 1-2 questions numériques (délais, compteurs, pourcentages)
- 10% date          → 1 question de date (dernière revue, dernier test)
- 5%  rating        → 0-1 question d'échelle (niveau d'implémentation)

📌 TYPES DISPONIBLES : boolean | single_choice | multiple_choice | open | rating | number | date

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 TYPES DE QUESTIONS DÉTAILLÉS (7 types disponibles)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✅ boolean - Questions binaires Oui/Non (20%)
   Usage : Vérifier l'EXISTENCE d'un document/processus formel
   Options : Automatiques (Oui/Non)
   Exemples :
   • "Un registre des traitements RGPD est-il formellement tenu à jour ?"
   • "Les accès VPN sont-ils protégés par authentification multifacteur (MFA) ?"
   • "Des tests de restauration de sauvegarde sont-ils réalisés au moins annuellement ?"

✅ single_choice - Choix unique (30% - TYPE PRINCIPAL)
   Usage : Fréquence, niveau de maturité, méthode utilisée, outil déployé
   ⚠️ TOUJOURS fournir 3-5 options réalistes dans le champ "options" !
   Exemples :
   • "Quelle est la fréquence de mise à jour de l'antivirus ?"
     Options: ["Temps réel", "Quotidienne", "Hebdomadaire", "Mensuelle", "Jamais/Ne sait pas"]
   • "Quel outil est utilisé pour la gestion des vulnérabilités ?"
     Options: ["Nessus", "Qualys", "Rapid7", "OpenVAS", "Aucun outil", "Autre"]
   • "Quelle est la fréquence des sauvegardes complètes ?"
     Options: ["Quotidienne", "Hebdomadaire", "Mensuelle", "Aucune", "Ne sait pas"]

✅ multiple_choice - Choix multiples (5%)
   Usage : Sélectionner PLUSIEURS éléments dans une liste (rare en audit)
   ⚠️ Fournir 4-8 options réalistes dans le champ "options" !
   Exemples :
   • "Quels types de données sensibles sont traités par votre organisation ?"
     Options: ["Données personnelles", "Données de santé", "Données bancaires", "Secrets industriels", "Aucune donnée sensible"]
   • "Quelles mesures de sécurité sont appliquées aux postes de travail ?"
     Options: ["Antivirus", "Pare-feu local", "Chiffrement disque", "Authentification forte", "Aucune"]

✅ open - Texte libre (20%)
   Usage : Demander une liste, description de processus, justificatifs, explications
   Options : null
   Exemples :
   • "Listez les systèmes critiques sauvegardés quotidiennement (nom + emplacement)."
   • "Décrivez la procédure de désactivation d'un compte utilisateur lors d'un départ (étapes)."
   • "Quels sont les principaux actifs informatiques à protéger dans votre organisation ?"

✅ number - Valeur numérique (15%)
   Usage : Métriques, compteurs, délais mesurables, pourcentages
   Options : null
   Exemples :
   • "Combien de comptes privilégiés (admin) sont actuellement actifs ?"
   • "Quel est le délai maximum (en jours) avant expiration d'un mot de passe ?"
   • "Combien de correctifs de sécurité ont été appliqués le mois dernier ?"
   • "Quelle est la durée de rétention des logs d'authentification (en jours) ?"

✅ date - Date précise (10%)
   Usage : Dernière action, dernier test, prochaine échéance, date de mise en service
   Options : null
   Exemples :
   • "Quelle est la date du dernier test de restauration de sauvegarde ?"
   • "Quand a eu lieu la dernière revue de la politique de sécurité ?"
   • "Date de la dernière analyse de vulnérabilités sur le réseau ?"

✅ rating - Échelle 1-5 (5% - UTILISER AVEC PARCIMONIE)
   Usage : Auto-évaluation du niveau de maturité/implémentation
   Options : ["Non implémenté", "Incomplet", "Partiel", "Complet", "Optimisé"]
   Exemples :
   • "Quel est le niveau de maturité de votre processus de gestion des incidents ?"
   • "Évaluez le niveau d'implémentation de votre politique de contrôle d'accès."

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📎 QUESTIONS AVEC UPLOAD DE PREUVES (NOUVEAU)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️ RÈGLE IMPORTANTE : Certaines questions EXIGENT des preuves documentaires ou des liens

🎯 QUAND EXIGER UNE PREUVE ?
✅ Existence d'une politique formelle → Demander le document PDF
✅ Processus documenté → Demander la procédure ou capture d'écran du portail
✅ Certification ou conformité → Demander le certificat
✅ Logs ou rapports → Demander exports ou captures

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔧 CHAMPS ADDITIONNELS POUR QUESTIONS AVEC PREUVES :
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1️⃣ "is_mandatory" (boolean)
   → true : Question OBLIGATOIRE (l'auditeur DOIT répondre)
   → false : Question optionnelle

   ⚠️ Marquer comme OBLIGATOIRE (is_mandatory: true) :
   - Questions critiques pour la conformité (RGPD, ISO 27001, etc.)
   - Exigences réglementaires
   - Contrôles de sécurité essentiels

   Exemple :
   {
     "text": "Un registre des traitements RGPD est-il formellement tenu à jour ?",
     "type": "boolean",
     "is_mandatory": true,
     "tags": ["RGPD", "conformité", "obligatoire"]
   }

2️⃣ "upload_conditions" (object ou null)
   → Si une réponse EXIGE un justificatif, remplir cet objet
   → Si aucune preuve requise, mettre null

   Structure :
   {
     "required_for_values": ["Oui", "Partiellement"],  // Valeurs déclenchant l'upload
     "attachment_types": ["evidence", "policy"],       // Types de fichiers acceptés
     "min_files": 1,                                   // Nombre minimum (défaut: 1)
     "max_files": 3,                                   // Nombre maximum (null = illimité)
     "accepts_links": true,                            // Accepter liens URL (true/false)
     "help_text": "Veuillez joindre la politique signée ou un lien SharePoint vers le document",
     "is_mandatory": true                              // Upload OBLIGATOIRE si valeur correspond
   }

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📂 TYPES DE PIÈCES JOINTES (attachment_types) :
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

- "evidence"     → Preuves générales (.pdf, .jpg, .docx, .xlsx, .csv)
- "policy"       → Politiques/procédures (.pdf, .docx)
- "screenshot"   → Captures d'écran (.jpg, .png, .gif)
- "certificate"  → Certificats (.pdf, .cer, .pem)
- "report"       → Rapports d'audit/scan (.pdf, .xlsx, .html)
- "log"          → Fichiers de logs (.txt, .log, .json, .csv)
- "other"        → Autres types (.pdf, .jpg, .txt, .zip)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔍 EXEMPLES DE QUESTIONS AVEC UPLOAD :
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✅ EXEMPLE 1 : Politique de sécurité (UPLOAD OBLIGATOIRE)
{
  "text": "L'organisation dispose-t-elle d'une politique de sécurité de l'information formellement approuvée par la direction ?",
  "type": "single_choice",
  "options": ["Oui", "Partiellement", "Non", "En cours de rédaction"],
  "is_mandatory": true,
  "upload_conditions": {
    "required_for_values": ["Oui"],
    "attachment_types": ["policy", "evidence"],
    "min_files": 1,
    "max_files": 2,
    "accepts_links": true,
    "help_text": "Joindre la politique signée (PDF) OU fournir un lien SharePoint/intranet OU une capture d'écran du portail",
    "is_mandatory": true
  },
  "help_text": "Vérifier l'existence d'un document formel signé par la direction générale ou le RSSI.",
  "difficulty": "easy",
  "tags": ["politique", "gouvernance", "ISO 27001"]
}

✅ EXEMPLE 2 : Certificat ISO (UPLOAD OPTIONNEL)
{
  "text": "L'organisation est-elle certifiée ISO 27001 ?",
  "type": "boolean",
  "options": null,
  "is_mandatory": false,
  "upload_conditions": {
    "required_for_values": ["Oui"],
    "attachment_types": ["certificate", "evidence"],
    "min_files": 1,
    "max_files": 1,
    "accepts_links": true,
    "help_text": "Joindre le certificat ISO 27001 en cours de validité ou fournir un lien vers le registre des certificats",
    "is_mandatory": false
  },
  "help_text": "Demander le certificat délivré par l'organisme accrédité (AFNOR, BSI, etc.)",
  "difficulty": "easy",
  "tags": ["certification", "ISO 27001"]
}

✅ EXEMPLE 3 : Logs d'accès (UPLOAD OBLIGATOIRE pour conformité)
{
  "text": "Les journaux d'authentification sont-ils conservés et archivés ?",
  "type": "single_choice",
  "options": ["Oui, avec archivage", "Oui, sans archivage", "Non", "Ne sait pas"],
  "is_mandatory": true,
  "upload_conditions": {
    "required_for_values": ["Oui, avec archivage"],
    "attachment_types": ["log", "screenshot", "evidence"],
    "min_files": 1,
    "max_files": 5,
    "accepts_links": true,
    "help_text": "Joindre un export des logs d'authentification (CSV/TXT) OU une capture d'écran du SIEM montrant la rétention OU un lien vers l'outil de collecte",
    "is_mandatory": true
  },
  "help_text": "Consulter SIEM, serveur syslog, ou EventViewer Windows. Vérifier durée de rétention.",
  "difficulty": "medium",
  "tags": ["journalisation", "traçabilité", "RGPD"]
}

✅ EXEMPLE 4 : Sans upload requis
{
  "text": "Combien de comptes administrateurs actifs sont recensés dans l'Active Directory ?",
  "type": "number",
  "options": null,
  "is_mandatory": true,
  "upload_conditions": null,
  "help_text": "Commande : Get-ADUser -Filter {Enabled -eq $true -and AdminCount -eq 1} | Measure-Object",
  "difficulty": "medium",
  "tags": ["contrôle d'accès", "Active Directory"]
}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚙️ RÈGLES DE GÉNÉRATION POUR UPLOAD :
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1️⃣ 20-30% des questions doivent avoir upload_conditions (documents formels, preuves)
2️⃣ Toujours proposer accepts_links: true (liens SharePoint/intranet acceptés)
3️⃣ help_text DOIT lister les types de preuves acceptées avec emojis :
   📄 = Document PDF/Word
   📷 = Capture d'écran
   🔗 = Lien URL
   📅 = Document avec date
   📊 = Rapport/export
4️⃣ is_mandatory dans upload_conditions = true si conformité critique (RGPD, ISO, etc.)
5️⃣ min_files: 1 par défaut, max_files: null (illimité) SAUF si besoin précis
6️⃣ required_for_values : Généralement ["Oui"] ou ["Oui", "Partiellement"]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 EXEMPLES DE QUESTIONS RÉALISTES PAR DOMAINE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔐 CONTRÔLE D'ACCÈS :
✅ "Combien de comptes administrateurs actifs sont recensés dans l'Active Directory ?"
✅ "Quelle est la durée de verrouillage (en minutes) après 5 tentatives de connexion échouées ?"
✅ "Les sessions utilisateur sont-elles verrouillées après combien de minutes d'inactivité ?"

🛡️ SAUVEGARDES :
✅ "Quelle est la date de la dernière restauration de sauvegarde réalisée en environnement de test ?"
✅ "Où sont stockées les sauvegardes externalisées (nom du site/datacenter) ?"
✅ "Quel pourcentage des serveurs critiques a été sauvegardé avec succès la semaine dernière ?"

🔄 GESTION DES PATCHS :
✅ "Quel est le délai moyen (en jours) entre la publication et l'application d'un patch critique ?"
✅ "Combien de serveurs ont un système d'exploitation obsolète (non supporté par l'éditeur) ?"
✅ "Quel outil est utilisé pour déployer les correctifs de sécurité ?"
   Options: ["WSUS", "SCCM", "PDQ Deploy", "Script manuel", "Aucun"]

🚨 GESTION DES INCIDENTS :
✅ "Combien d'incidents de sécurité ont été enregistrés dans l'outil de ticketing en 2024 ?"
✅ "Quel est le délai moyen de qualification d'un incident de sécurité (en heures) ?"
✅ "Un plan de réponse aux incidents (PRI) documenté existe-t-il et a-t-il été testé ?"

📝 JOURNALISATION :
✅ "Quelle est la durée de rétention des journaux d'authentification (en jours) ?"
✅ "Les logs sont-ils centralisés dans un SIEM ou outil de collecte ?"
   Options: ["SIEM commercial", "ELK/Splunk", "Syslog centralisé", "Logs locaux uniquement", "Aucune centralisation"]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
💡 HELP_TEXT : OBLIGATOIRE POUR CHAQUE QUESTION !
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️ RÈGLE ABSOLUE : Chaque question DOIT avoir un help_text qui guide l'utilisateur !

🎯 LE HELP_TEXT DOIT CONTENIR :
✅ Où trouver l'information (outil, console, fichier, système)
✅ Commande/chemin/requête pour obtenir la donnée
✅ Contexte métier ou réglementaire (pourquoi c'est important)
✅ Exemples concrets de réponses acceptables

📋 EXEMPLES DE BON HELP_TEXT :

• Pour question boolean/single_choice :
  "help_text": "Vérifier dans la console d'administration. Si oui, la politique doit être datée et signée par le responsable sécurité ou la direction."

• Pour question number :
  "help_text": "Commande PowerShell : Get-ADUser -Filter {Enabled -eq $true -and AdminCount -eq 1} | Measure-Object. Les comptes de service doivent être exclus."

• Pour question date :
  "help_text": "Consulter le rapport du dernier test de restauration ou le journal de sauvegarde. La fréquence recommandée est au moins annuelle."

• Pour question open :
  "help_text": "Lister les actifs prioritaires : serveurs métier, bases de données, postes dirigeants. Inclure l'emplacement physique/virtuel."

• Pour question rating :
  "help_text": "Niveau 1 : Aucun processus. Niveau 3 : Processus défini mais non optimisé. Niveau 5 : Processus mature avec indicateurs."

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 OBJECTIF PRINCIPAL : COUVRIR COMPLÈTEMENT LE RÉFÉRENTIEL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️ RÈGLE FONDAMENTALE : Générer 3 à 8 questions par exigence/contrôle

Pourquoi plusieurs questions par exigence ?
→ Une exigence ISO 27001 couvre généralement PLUSIEURS aspects qu'il faut vérifier séparément
→ Exemple : Exigence "Contrôle d'accès" nécessite de vérifier :
  • Existence d'une politique (question boolean/single_choice)
  • Méthode d'authentification utilisée (question single_choice)
  • Nombre de comptes privilégiés (question number)
  • Date de dernière revue des droits (question date)
  • Liste des accès sensibles (question open)
  • Fréquence de revue (question single_choice)

Combien de questions générer ?
✅ Exigence SIMPLE (ex: "Politique de sécurité") = 3-4 questions
   → Existence, date d'approbation, accessibilité, revue
✅ Exigence MOYENNE (ex: "Gestion des incidents") = 4-6 questions
   → Processus, outils, métriques, formation, tests, documentation
✅ Exigence COMPLEXE (ex: "Contrôle d'accès logique") = 6-8 questions
   → Politique, authentification, autorisation, revue, journalisation, comptes privilégiés, comptes de service, MFA

⚠️ NE JAMAIS générer moins de 3 questions par exigence !

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 DIRECTIVES INTELLIGENTES DE GÉNÉRATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️ RÈGLES OBLIGATOIRES À APPLIQUER POUR CHAQUE QUESTION :

🎯 OBJECTIF UPLOAD : 20-30% des questions DOIVENT avoir upload_conditions défini
    → Particulièrement pour les questions sur :
      • Existence de politiques/procédures formelles
      • Conformité RGPD/ISO/réglementaire
      • Certifications ou audits
      • Processus documentés
      • Configurations système critiques

1️⃣ ADAPTER LE NIVEAU DE DIFFICULTÉ (difficulty) selon la criticité du contrôle
   📌 Utilise la criticité fournie dans les données d'entrée (criticality_level)

   Mapping criticité → difficulty :
   - criticality = "LOW"      → difficulty = "easy"
   - criticality = "MEDIUM"   → difficulty = "medium"
   - criticality = "HIGH"     → difficulty = "hard"
   - criticality = "CRITICAL" → difficulty = "hard"

   ⚠️ Si aucune criticité fournie → difficulty = "medium" par défaut

2️⃣ MARQUER LES QUESTIONS CRITIQUES COMME OBLIGATOIRES (is_mandatory)
   📌 Une question est OBLIGATOIRE si :
   - criticality_level = "HIGH" ou "CRITICAL"
   - OU si la question vérifie une exigence légale/réglementaire (RGPD, ISO 27001, etc.)

   ✅ is_mandatory = true  → Pour questions critiques (HIGH/CRITICAL)
   ⭕ is_mandatory = false → Pour questions informatives (LOW/MEDIUM)

3️⃣ GÉNÉRER UN CODE DE QUESTION STANDARDISÉ (question_code)
   📌 Format : {FRAMEWORK}-{CHAPTER}-Q{NUMBER}
   ⚠️ NOM DU CHAMP JSON : "question_code" (PAS "id" !)

   Exemples :
   - "question_code": "ISO27001-A5.1-Q1"  → 1ère question du chapitre A.5.1
   - "question_code": "ISO27001-A5.1-Q2"  → 2ème question du chapitre A.5.1
   - "question_code": "ISO27001-A6.2-Q1"  → 1ère question du chapitre A.6.2
   - "question_code": "CUSTOM-GEN-Q1"     → Si framework/chapter non disponible

   ⚠️ Extraire le chapter depuis requirement.official_code si disponible
   Exemple : official_code = "A.5.1.1" → chapter = "A.5.1"

4️⃣ DÉDUIRE LE CHAPITRE (chapter) depuis requirement.official_code
   📌 Extraire le préfixe alphanumérique du code officiel

   Exemples d'extraction :
   - official_code = "A.5.1.1" → chapter = "A.5"
   - official_code = "A.6.2.1" → chapter = "A.6"
   - official_code = "5.1"     → chapter = "5"
   - official_code = null      → chapter = null

5️⃣ SUGGÉRER DES TYPES DE PREUVES (evidence_types) selon le type de question
   📌 Définir les types de preuves attendues dans un tableau evidence_types

   Mapping type de question → evidence_types suggérés :

   • boolean (existence de politique/processus) :
     → ["policy", "evidence", "screenshot"]

   • single_choice / multiple_choice (configuration, fréquence) :
     → ["screenshot", "report", "evidence"]

   • open (description de processus) :
     → ["policy", "evidence", "screenshot"]

   • number (métriques, compteurs) :
     → ["report", "screenshot", "log"]

   • date (dernière action, test) :
     → ["report", "evidence", "screenshot"]

   • rating (auto-évaluation) :
     → ["evidence", "report"]

   Types disponibles : "evidence", "policy", "screenshot", "certificate", "report", "log", "other"

6️⃣ DÉFINIR upload_conditions POUR 20-30% DES QUESTIONS
   📌 OBLIGATOIRE : Au moins 1 question sur 5 DOIT avoir upload_conditions défini

   Quand définir upload_conditions :

   ✅ Questions sur existence de politiques/procédures :
      Exemple : "L'organisation dispose-t-elle d'une politique de sécurité ?"
      → upload_conditions avec required_for_values: ["Oui"]

   ✅ Questions sur conformité/certifications :
      Exemple : "L'organisation est-elle certifiée ISO 27001 ?"
      → upload_conditions avec required_for_values: ["Oui"]

   ✅ Questions sur tests/audits réalisés :
      Exemple : "Des tests de restauration ont-ils été réalisés ?"
      → upload_conditions avec required_for_values: ["Oui"]

   ✅ Questions nécessitant preuve documentaire :
      Exemple : "Quelle est la fréquence des sauvegardes ?"
      → upload_conditions avec required_for_values: ["Quotidienne", "Hebdomadaire"]

   ❌ NE PAS définir upload_conditions pour :
      • Questions purement quantitatives (nombre de comptes, pourcentage)
      • Questions de type "date" sans besoin de justificatif
      • Questions d'auto-évaluation (rating)

   Structure minimale obligatoire :
   {
     "required_for_values": ["Oui"],
     "attachment_types": ["policy", "evidence"],
     "min_files": 1,
     "max_files": null,
     "accepts_links": true,
     "help_text": "Joindre le document PDF/Word OU fournir un lien SharePoint/intranet vers le document",
     "is_mandatory": true
   }

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚙️ CONSIGNES TECHNIQUES JSON
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔴 CHAMPS OBLIGATOIRES POUR CHAQUE QUESTION :

Pour chaque question, tu DOIS inclure TOUS ces champs :

1️⃣ "text" (string, OBLIGATOIRE)
   → Texte clair et précis de la question

2️⃣ "type" (string, OBLIGATOIRE)
   → Type de question : boolean | single_choice | multiple_choice | open | number | date | rating

3️⃣ "help_text" (string, OBLIGATOIRE - JAMAIS VIDE !)
   → Aide contextuelle pour l'utilisateur final
   → Explique comment interpréter la question
   → Indique quelles preuves sont attendues
   → Donne des exemples concrets ou commandes techniques
   → Minimum 50 caractères, maximum 300 caractères

4️⃣ "options" (array ou null)
   → Liste d'options pour single_choice/multiple_choice
   → null pour les autres types

5️⃣ "is_mandatory" (boolean)
   → true pour questions obligatoires
   → false pour questions optionnelles

6️⃣ "upload_conditions" (object ou null)
   → Conditions pour joindre des preuves documentaires
   → null si aucune preuve requise

7️⃣ "difficulty" (string)
   → "easy" | "medium" | "hard"

8️⃣ "estimated_time_minutes" (number, OBLIGATOIRE)
   → Temps estimé pour répondre à la question (en minutes)
   → Fourchettes par type de question :
     • boolean/single_choice : 2-5 minutes
     • multiple_choice : 3-7 minutes
     • number/date : 3-8 minutes (selon complexité de recherche)
     • open (texte court) : 5-10 minutes
     • open (texte long/description) : 10-20 minutes
     • rating : 3-6 minutes
   → Questions avec upload : +3-5 minutes
   → Questions nécessitant une commande technique : +5-10 minutes

9️⃣ "tags" (array)
   → Liste de tags thématiques
   → Ex: ["RGPD", "sauvegarde", "contrôle d'accès"]

🔟 "question_code" (string, OBLIGATOIRE)
   → Code unique de la question au format {FRAMEWORK}-{CHAPTER}-Q{NUMBER}
   → Ex: "ISO27001-A5.1-Q1", "ISO27001-A6.2-Q3"
   → Si framework/chapter inconnu : "CUSTOM-GEN-Q1"

1️⃣1️⃣ "chapter" (string ou null)
   → Chapitre/section du référentiel (ex: "A.5", "A.6", "5.1")
   → Extraire depuis requirement.official_code si disponible
   → null si non déterminable

1️⃣2️⃣ "evidence_types" (array)
   → Types de preuves suggérés pour cette question
   → Ex: ["policy", "screenshot"], ["report", "log"]
   → Utiliser le mapping type de question → evidence_types (voir directive 5)
   → Liste complète: ["evidence", "policy", "screenshot", "certificate", "report", "log", "other"]

⚠️ VALIDATION STRICTE :
- help_text NE DOIT JAMAIS être vide ou null
- help_text DOIT contenir au moins 50 caractères
- help_text DOIT être contextuel et utile, pas générique
- estimated_time_minutes DOIT être un nombre réaliste (entre 2 et 30 minutes)

📋 SCHÉMA JSON ATTENDU :

⚠️ RAPPEL IMPORTANT :
   • Au moins 20-30% des questions DOIVENT avoir upload_conditions défini
   • Voir directive 6️⃣ ci-dessus pour savoir quand l'utiliser
   • Exemples ci-dessous montrent des questions AVEC et SANS upload_conditions

{
  "questions": [
    {
      "text": "L'organisation dispose-t-elle d'une politique de sécurité de l'information formellement approuvée ?",
      "type": "single_choice",
      "options": ["Oui", "Partiellement", "Non", "En cours de rédaction"],
      "is_mandatory": true,
      "upload_conditions": {
        "required_for_values": ["Oui"],
        "attachment_types": ["policy", "evidence"],
        "min_files": 1,
        "max_files": 2,
        "accepts_links": true,
        "help_text": "Joindre la politique signée (PDF) OU fournir un lien SharePoint/intranet OU une capture d'écran du portail documentaire",
        "is_mandatory": true
      },
      "help_text": "Vérifier dans le référentiel documentaire ou demander au RSSI. La politique doit être datée, signée par la direction et accessible aux collaborateurs.",
      "estimated_time_minutes": 5,
      "difficulty": "hard",
      "question_code": "ISO27001-A5.1-Q1",
      "chapter": "A.5",
      "evidence_types": ["policy", "evidence", "screenshot"],
      "tags": ["politique", "gouvernance", "ISO 27001"]
    },
    {
      "text": "Combien de comptes administrateurs actifs sont recensés dans l'Active Directory ?",
      "type": "number",
      "options": null,
      "is_mandatory": true,
      "upload_conditions": null,
      "help_text": "Utiliser PowerShell : Get-ADUser -Filter {Enabled -eq $true -and AdminCount -eq 1} | Measure-Object. Exclure les comptes de service et inclure uniquement les comptes humains.",
      "estimated_time_minutes": 8,
      "difficulty": "hard",
      "question_code": "ISO27001-A9.2-Q1",
      "chapter": "A.9",
      "evidence_types": ["report", "screenshot", "log"],
      "tags": ["contrôle d'accès", "comptes privilégiés"]
    },
    {
      "text": "Quelle est la fréquence des sauvegardes complètes des serveurs critiques ?",
      "type": "single_choice",
      "options": ["Quotidienne", "Hebdomadaire", "Mensuelle", "Aucune sauvegarde", "Ne sait pas"],
      "is_mandatory": true,
      "upload_conditions": {
        "required_for_values": ["Quotidienne", "Hebdomadaire"],
        "attachment_types": ["screenshot", "report", "evidence"],
        "min_files": 1,
        "max_files": null,
        "accepts_links": true,
        "help_text": "Joindre une capture d'écran du planning de sauvegarde OU un rapport de l'outil de backup",
        "is_mandatory": true
      },
      "help_text": "Consulter la planification dans l'outil de sauvegarde (Veeam, Acronis, Backup Exec). Vérifier le planning des tâches automatisées pour les serveurs identifiés comme critiques.",
      "estimated_time_minutes": 6,
      "difficulty": "medium",
      "question_code": "ISO27001-A12.3-Q1",
      "chapter": "A.12",
      "evidence_types": ["screenshot", "report", "evidence"],
      "tags": ["sauvegarde", "continuité"]
    },
    {
      "text": "Quelle est la date du dernier test de restauration de sauvegarde réalisé avec succès ?",
      "type": "date",
      "options": null,
      "is_mandatory": false,
      "upload_conditions": null,
      "help_text": "Consulter les comptes-rendus de test dans l'outil de sauvegarde ou les tickets d'intervention. Un test annuel minimum est recommandé par ISO 27001.",
      "estimated_time_minutes": 6,
      "difficulty": "medium",
      "question_code": "ISO27001-A12.3-Q2",
      "chapter": "A.12",
      "evidence_types": ["report", "evidence", "screenshot"],
      "tags": ["sauvegarde", "test"]
    }
  ]
}

⚠️ RÈGLES JSON STRICTES :
- Répondre UNIQUEMENT en JSON valide (UTF-8)
- AUCUN texte avant/après le JSON
- AUCUNE balise markdown (```json)
- AUCUNE balise <think>
- Tous les guillemets doubles (")
- Toutes les virgules correctes
- Tous les crochets/accolades fermés

✅ Champs OBLIGATOIRES (NOMS EXACTS À RESPECTER) :

⚠️ ATTENTION : Utiliser EXACTEMENT ces noms de champs (pas "id", pas "requirement_id") :

- "text" : Question claire et précise
- "type" : boolean|single_choice|multiple_choice|open|rating|number|date
- "options" : Array pour single_choice/multiple_choice, null sinon
- "is_mandatory" : true (question obligatoire) ou false (optionnelle)
- "upload_conditions" : Object (si preuve requise) ou null (si aucune preuve)
- "help_text" : Guidance technique (commande, chemin fichier, outil à consulter)
- "difficulty" : low|medium|high (selon criticality_level du contrôle)
- "question_code" : Code unique format {FRAMEWORK}-{CHAPTER}-Q{NUMBER} ⚠️ PAS "id"
- "chapter" : Chapitre/section (ex: "A.5", "A.6") ou null
- "evidence_types" : Array de types de preuves suggérés (ex: ["policy", "screenshot"])
- "estimated_time_minutes" : Temps estimé en minutes (2-30)
- "tags" : 1-3 tags pertinents

⚠️ NE PAS UTILISER : "id", "requirement_id" - Ces champs ne sont pas utilisés !

⚠️ IMPORTANT UPLOAD_CONDITIONS :
Si upload_conditions n'est pas null, il DOIT contenir :
- "required_for_values" : Array de valeurs déclenchant l'upload (ex: ["Oui"])
- "attachment_types" : Array de types acceptés (ex: ["policy", "evidence"])
- "min_files" : Number (défaut: 1)
- "max_files" : Number ou null (null = illimité)
- "accepts_links" : Boolean (true pour accepter liens URL)
- "help_text" : String expliquant les preuves acceptées (texte simple, SANS emojis)
- "is_mandatory" : Boolean (true si upload obligatoire pour conformité)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🎯 TON OBJECTIF : Générer des questions qu'un auditeur pourrait IMMÉDIATEMENT utiliser
pour collecter des PREUVES VÉRIFIABLES lors d'un audit terrain.

⚠️ Si une question ne permet pas de vérifier/mesurer/prouver quelque chose de concret,
elle n'a PAS sa place dans un questionnaire d'audit professionnel !"""

    # LIGNE 130-160 : REMPLACER __init__

    def __init__(self, db_session: Session):
        self.db = db_session

        # ✅ Lecture robuste avec fallback explicite
        self.ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
        self.model = os.getenv("OLLAMA_MODEL", "deepseek-v3.1:671b-cloud")
        
        # ✅ Conversion sécurisée des types
        try:
            self.temperature = float(os.getenv("DEEPSEEK_TEMPERATURE", "0.6"))
        except ValueError:
            self.temperature = 0.6
            logger.warning("⚠️ DEEPSEEK_TEMPERATURE invalide, utilisation de 0.6")
        
        try:
            self.max_tokens = int(os.getenv("DEEPSEEK_MAX_TOKENS", "8192"))
        except ValueError:
            self.max_tokens = 8192
            logger.warning("⚠️ DEEPSEEK_MAX_TOKENS invalide, utilisation de 8192")
        
        try:
            self.timeout = int(os.getenv("AI_TIMEOUT_SECONDS", "600"))
        except ValueError:
            self.timeout = 600
            logger.warning("⚠️ AI_TIMEOUT_SECONDS invalide, utilisation de 600")
        
        try:
            self.max_retries = int(os.getenv("AI_MAX_RETRIES", "3"))
        except ValueError:
            self.max_retries = 3
        
        try:
            self.batch_size = int(os.getenv("DEEPSEEK_BATCH_SIZE", "10"))
        except ValueError:
            self.batch_size = 10
        
        ai_enabled_str = os.getenv("AI_GENERATION_ENABLED", "true").lower()
        self.ai_enabled = ai_enabled_str in ("true", "1", "yes", "on")

        # ✅ Log de démarrage détaillé
        logger.info(
            f"🤖 [DeepSeek Init] "
            f"URL={self.ollama_url} | "
            f"Model={self.model} | "
            f"Enabled={self.ai_enabled} | "
            f"Timeout={self.timeout}s | "
            f"Retries={self.max_retries} | "
            f"Batch={self.batch_size} | "
            f"Temp={self.temperature} | "
            f"MaxTokens={self.max_tokens}"
        )

    # ======================== Public API ======================== #

    def _chunks(self, seq, n: int):
        """Découpe une séquence en lots de n éléments."""
        for i in range(0, len(seq), n):
            yield seq[i:i + n]

    def _build_prompt_for_batch(self, items_batch: list) -> str:
        """Construit un prompt concis pour un lot d'exigences d'un référentiel."""
        lines = [
            f"CONTEXTE : Génération de questions d'audit pour {len(items_batch)} exigences.",
            "Chaque exigence doit donner lieu à plusieurs questions couvrant son intention.",
            "\nEXIGENCES À COUVRIR :"
        ]
        for r in items_batch:
            code  = r.get("requirement_code") or r.get("official_code") or ""
            title = (r.get("title") or r.get("requirement_title") or "")[:120]
            desc  = (r.get("description") or r.get("requirement_text") or "")[:160]
            dom   = r.get("domain") or "N/A"
            crit  = r.get("criticality_level") or "MEDIUM"  # ✅ Récupérer la criticité

            lines.append(f"[{code}] {title}")
            if desc:
                lines.append(f"  Description : {desc}")
            lines.append(f"  Domaine : {dom}")
            lines.append(f"  Criticité : {crit}")  # ✅ Informer l'IA de la criticité

        lines.append(
            """
    INSTRUCTIONS DE SORTIE :
    - Réponds STRICTEMENT en JSON valide (UTF-8), sans texte avant/après, sans balises <think>.
    - Toutes les clés/chaînes entre doubles guillemets.
    - Génère 5 à 10 questions d'audit pratiques par exigence.
    - Types: yes_yes, single_choice, multiple_choice, textarea, number, date.
    - Inclure "help_text" si utile.

    ⚠️ CRITICITÉ ET DIFFICULTÉ :
    - Utilise la "Criticité" de chaque exigence pour définir "difficulty" :
      • LOW → difficulty: "low"
      • MEDIUM → difficulty: "medium"
      • HIGH → difficulty: "high"
      • CRITICAL → difficulty: "high"
    - Marque "is_mandatory": true pour les exigences CRITICAL et HIGH

    ⚠️ IMPORTANT : Suivre le schéma JSON détaillé dans SYSTEM_PROMPT ci-dessus.
    Ne PAS utiliser "id" ou "requirement_id" - utiliser "question_code" et "chapter" à la place.
    """.strip()
        )

        prompt = "\n".join(lines)
        return prompt[:8000]
    
    def _rank_cps_for_question(self, question_text: str, candidates: List[Dict[str, Any]]) -> tuple[Optional[Dict[str, Any]], float]:
        """
        Classe des CP candidats pour une question donnée.
        Stratégie rapide:
        - Score 1: correspondance lexicale (titre/description)
        - Score 2 (optionnel): similarité embeddings si EmbeddingService dispo
        Retourne (meilleur_cp, score)
        """
        if not candidates:
            return None, -1.0

        q = (question_text or "").lower()
        if not q:
            return candidates[0], 0.0

        # Heuristique lexicale simple
        def lexical_score(cp: Dict[str, Any]) -> float:
            s = f"{cp.get('name','')} {cp.get('description','')}".lower()
            score = 0
            # mini-features
            for term in ["auth", "mfa", "pwd", "backup", "sauvegarde", "journal", "log", "incident", "patch", "vpn", "firewall", "antivirus", "chiffrement", "encrypt"]:
                if term in q and term in s:
                    score += 1.0
            # bonus si mots exacts partagés (sim. Jaccard simplifiée)
            qw = set(q.split())
            sw = set(s.split())
            if qw and sw:
                score += len(qw & sw) / max(1, len(qw | sw))
            return score

        ranked = sorted(candidates, key=lexical_score, reverse=True)
        best = ranked[0]
        best_s = lexical_score(best)

        # Si tu veux activer un second étage plus “smart”, branche ton EmbeddingService ici
        # try:
        #     from src.services.embedding_service import EmbeddingService
        #     emb = EmbeddingService()
        #     qv = emb.generate_embedding(question_text)
        #     best_cp, best_score = None, -1.0
        #     for cp in candidates:
        #         sv = emb.generate_embedding(f"{cp.get('name','')} {cp.get('description','')}")
        #         sim = emb.compute_similarity(qv, sv)
        #         if sim > best_score:
        #             best_cp, best_score = cp, sim
        #     return best_cp, best_score
        # except Exception:
        #     pass

        return best, best_s


    def _fetch_control_points_for_requirements(self, requirement_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Retourne { requirement_id: [ {id, code, name, description, domain} , ... ] }
        en lisant requirement_control_point → control_point.
        """
        from sqlalchemy import text
        if not requirement_ids:
            return {}

        query = text("""
            SELECT
                rcp.requirement_id AS rid,
                cp.id               AS cp_id,
                cp.code             AS cp_code,
                cp.name             AS cp_name,
                cp.description      AS cp_desc,
                cp.category         AS cp_category,
                cp.subcategory      AS cp_subcategory,
                cp.criticality_level AS cp_criticality
            FROM requirement_control_point rcp
            JOIN control_point cp ON cp.id = rcp.control_point_id
            WHERE rcp.requirement_id::text = ANY(:rid_list)
            AND cp.is_active = true
        """)

        rows = self.db.execute(query, {"rid_list": requirement_ids}).mappings().all()
        result: Dict[str, List[Dict[str, Any]]] = {}
        for r in rows:
            rid = str(r["rid"])
            result.setdefault(rid, []).append({
                "id": str(r["cp_id"]),
                "code": r["cp_code"],
                "name": r["cp_name"],
                "description": r["cp_desc"],
                "category": r["cp_category"],
                "subcategory": r["cp_subcategory"],
                "criticality_level": r["cp_criticality"],
            })
        return result

    async def _assign_control_points(self, questions: List[Dict[str, Any]], request) -> List[Dict[str, Any]]:
        """
        Enrichit chaque question avec control_point_id en utilisant:
        1) requirement_control_point (mapping direct)
        2) S'il y a plusieurs PCs possibles pour une exigence: choix par similarité question↔PC
        3) Fallback: rien (on ne force pas un mauvais mapping)
        """
        if not questions:
            return questions

        # Collecte des exigences référencées par les questions
        req_ids: set[str] = set()
        for q in questions:
            for rid in q.get("requirement_ids", []) or []:
                rid_s = str(rid).strip()
                # Valider que c'est un UUID valide (format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)
                if rid_s and len(rid_s) == 36 and rid_s.count('-') == 4:
                    try:
                        # Tenter de valider comme UUID
                        import uuid as uuid_lib
                        uuid_lib.UUID(rid_s)
                        req_ids.add(rid_s)
                    except (ValueError, AttributeError):
                        # Ignorer les IDs invalides
                        pass

        if not req_ids:
            return questions

        # 1) Charger tous les PCs liés aux exigences (via requirement_control_point)
        cp_by_req: Dict[str, List[Dict[str, Any]]] = self._fetch_control_points_for_requirements(list(req_ids))

        # 2) Pour chaque question, attribuer le meilleur CP (si pas déjà présent)
        out: List[Dict[str, Any]] = []
        for q in questions:
            if q.get("control_point_id"):
                out.append(q)
                continue

            q_text = (q.get("text") or "").strip()
            best_cp = None
            best_score = -1.0

            # Chercher un CP dans l'union des CPs de ses exigences
            candidate_cps: List[Dict[str, Any]] = []
            for rid in q.get("requirement_ids", []) or []:
                rid_s = str(rid).strip()
                candidate_cps.extend(cp_by_req.get(rid_s, []))

            # Dédupliquer par id
            seen = set()
            uniq_candidates = []
            for cp in candidate_cps:
                cid = cp.get("id")
                if cid and cid not in seen:
                    seen.add(cid)
                    uniq_candidates.append(cp)

            if uniq_candidates:
                best_cp, best_score = self._rank_cps_for_question(q_text, uniq_candidates)

            if best_cp:
                q["control_point_id"] = str(best_cp["id"])

            out.append(q)

        return out

    async def _generate_via_deepseek(self, request: QuestionGenerationRequest) -> List[Dict[str, Any]]:
        """
        Génération via DeepSeek (questions brutes) AVEC batching et prompts courts.
        Autonome : ne dépend plus de _get_source_data().
        """
        all_questions: List[Dict[str, Any]] = []

        # 1) Récupération directe selon le mode
        if request.mode == "framework":
            framework, requirements = self._load_framework_and_requirements(request.framework_id)
            source_type = "framework"
            # Récupérer les criticités des control points liés aux requirements
            cp_map = self._fetch_control_points_for_requirements([str(r.id) for r in requirements])

            items = [
                {
                    "anchor_id": str(r.id),
                    "requirement_code": r.official_code,
                    "title": r.title,
                    "requirement_text": (r.requirement_text or "")[:600],
                    "domain": getattr(r, "domain", None),
                    "subdomain": getattr(r, "subdomain", None),
                    # Utiliser la criticité du premier control point lié, ou "MEDIUM" par défaut
                    "criticality_level": cp_map.get(str(r.id), [{}])[0].get("criticality_level", "MEDIUM") if cp_map.get(str(r.id)) else "MEDIUM",
                    "official_code": r.official_code,  # Pour extraction du chapter
                }
                for r in requirements
            ]
        elif request.mode == "control_points":
            control_points = self._load_control_points(request.control_point_ids)
            source_type = "control_points"
            items = [
                {
                    "anchor_id": str(cp.id),
                    "code": cp.code,
                    "title": cp.name,
                    "description": (cp.description or "")[:600],
                    "domain": getattr(cp, "category", None) or getattr(cp, "control_family", None),
                    "subdomain": getattr(cp, "subcategory", None),
                    "criticality_level": getattr(cp, "criticality_level", "MEDIUM"),  # Criticité du CP
                    "official_code": getattr(cp, "code", None),  # Code du CP
                }
                for cp in control_points
            ]
        else:
            raise ValueError("Mode inconnu pour _generate_via_deepseek")

        # 2) Taille de lot (config ou défaut 10)
        batch_size = int(getattr(self, "batch_size", 10))

        # 3) Boucle par lots
        for batch in self._chunks(items, batch_size):
            
            # APRÈS (un seul argument)
            prompt = self._build_prompt_for_batch(batch)

            logger.info(f"[QGen] lot={len(batch)} prompt_chars={len(prompt)}")
            try:
                response_content = await self._call_deepseek_with_retry(prompt)
            except Exception as e:
                logger.error(f"[QGen] Échec lot ({len(batch)} items) : {e}")
                continue

            # 4) Parsing JSON -> questions
            questions = self._parse_items(response_content)

            # 🔍 LOG : Afficher un échantillon de la première question parsée
            if questions:
                # Prendre la première question du batch pour inspection
                first_item = questions[0]
                if isinstance(first_item, dict) and "questions" in first_item:
                    # Format items avec anchor_id
                    sample_questions = first_item.get("questions", [])
                    if sample_questions:
                        sample = sample_questions[0]
                        logger.info(f"📋 [SAMPLE_PARSED] Première question du lot: {json.dumps(sample, ensure_ascii=False, indent=2)[:500]}...")
                elif isinstance(first_item, dict):
                    # Format direct (liste de questions)
                    logger.info(f"📋 [SAMPLE_PARSED] Première question du lot: {json.dumps(first_item, ensure_ascii=False, indent=2)[:500]}...")

                all_questions.extend(questions)

        return all_questions




    async def generate_questions(self, request: QuestionGenerationRequest) -> List[GeneratedQuestion]:
        """
        Point d'entrée unique appelé par l'API.
        Délègue vers la branche adéquate.
        """
        mode = request.mode
        logger.info(f"[QGen] Mode={mode}")

        if mode == "framework":
            return await self._generate_for_framework(request)
        elif mode == "control_points":
            return await self._generate_for_control_points(request)
        else:
            raise ValueError("mode must be 'framework' or 'control_points'")
        

    # ---------------------- MODE: FRAMEWORK --------------------- #
    def _parse_questions(self, response_content: str) -> List[Dict[str, Any]]:
        """
        Parse la réponse JSON DeepSeek et renvoie une liste de questions normalisées.
        Tolérante : accepte des strings/objets partiels et les convertit en dicts utilisables.
        """
        try:
            cleaned = self._clean_json_response(response_content)
        except Exception:
            cleaned = response_content  # dernier recours

        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.error(f"JSON invalide renvoyé par l'IA: {e}")
            return []

        # On accepte {"questions":[...]} ou directement [...]
        if isinstance(parsed, dict) and "questions" in parsed:
            questions_raw = parsed["questions"]
        elif isinstance(parsed, list):
            questions_raw = parsed
        else:
            logger.warning("Réponse IA sans clé 'questions' ni liste exploitable")
            return []

        def _normalize_ai_item(item: Any) -> Optional[Dict[str, Any]]:
            # 1) Si string brute → question texte
            if isinstance(item, str):
                txt = item.strip()
                if not txt:
                    return None
                return {
                    "id": str(uuid4()),
                    "text": txt,
                    "type": "text",
                    "options": [],
                    "help_text": "",
                    "difficulty": "medium",
                    "domain": None,
                    "requirement_ids": [],
                    "ai_confidence": 0.8,
                    "rationale": "",
                    "tags": [],
                }

            # 2) Si dict → harmoniser alias + défauts
            if isinstance(item, dict):
                out = dict(item)  # shallow copy

                # alias fréquents
                if "question" in out and "text" not in out:
                    out["text"] = out.pop("question")

                # valeurs par défaut (anciens champs)
                out.setdefault("id", str(uuid4()))
                out.setdefault("text", "")
                out.setdefault("type", "text")
                out.setdefault("options", [])
                out.setdefault("help_text", out.get("rationale", "") or "")
                # ✅ Ne PAS écraser difficulty s'il existe déjà - setdefault suffit
                out.setdefault("difficulty", "medium")
                out.setdefault("domain", out.get("domain"))
                out.setdefault("requirement_ids", out.get("requirement_ids", []))
                out.setdefault("ai_confidence", float(out.get("ai_confidence", 0.8)))
                out.setdefault("rationale", out.get("rationale", "") or "")
                out.setdefault("tags", out.get("tags", []))

                # ✅ PRÉSERVER les nouveaux champs si présents dans la réponse IA
                # Ces champs sont maintenant demandés dans le SYSTEM_PROMPT
                # Ne PAS les écraser avec des valeurs par défaut
                # out.setdefault("question_code", None)  # ← NE PAS faire ça, préserver si présent
                # out.setdefault("chapter", None)
                # out.setdefault("evidence_types", [])
                # out.setdefault("is_mandatory", False)
                # out.setdefault("upload_conditions", None)
                # out.setdefault("estimated_time_minutes", None)

                # types autorisés
                allowed_types = {
                    "yes_no", "single_choice", "multiple_choice",
                    "text", "textarea", "number", "date", "likert"
                }
                if out["type"] not in allowed_types:
                    out["type"] = "text"

                # options → liste de str
                if not isinstance(out.get("options", []), list):
                    out["options"] = []
                else:
                    out["options"] = [str(o) for o in out["options"] if str(o).strip()]

                # requirement_ids peut être str ou liste
                rids = out.get("requirement_ids", [])
                if isinstance(rids, str) and rids.strip():
                    out["requirement_ids"] = [rids.strip()]
                elif isinstance(rids, list):
                    out["requirement_ids"] = [str(x).strip() for x in rids if str(x).strip()]
                else:
                    out["requirement_ids"] = []

                # texte obligatoire
                if not out["text"].strip():
                    return None

                return out

            # 3) Autres types → stringify
            txt = str(item).strip()
            if not txt:
                return None
            return {
                "id": str(uuid4()),
                "text": txt,
                "type": "text",
                "options": [],
                "help_text": "",
                "difficulty": "medium",
                "domain": None,
                "requirement_ids": [],
                "ai_confidence": 0.8,
                "rationale": "",
                "tags": [],
            }

        normalized: List[Dict[str, Any]] = []
        for it in questions_raw if isinstance(questions_raw, list) else []:
            q = _normalize_ai_item(it)
            if isinstance(q, dict) and q.get("text", "").strip():
                normalized.append(q)

        # Appliquer l'enrichissement et la normalisation des champs JSON stringifiés
        enriched = self._coerce_and_enrich_questions(normalized)

        return enriched

    def _merge_unique_questions(self, q1: List[Dict[str, Any]], q2: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Fusionne deux listes de questions en supprimant les doublons (clé = texte normalisé).
        """
        def norm(s: str) -> str:
            return " ".join((s or "").strip().lower().split())

        seen = set()
        out = []
        for q in (q1 or []):
            t = norm(q.get("text", ""))
            if t and t not in seen:
                seen.add(t)
                out.append(q)
        for q in (q2 or []):
            t = norm(q.get("text", ""))
            if t and t not in seen:
                seen.add(t)
                out.append(q)
        return out

    def _ensure_min_questions(self, questions: List[Dict[str, Any]], reqs: List[Dict[str, Any]], min_count: int = 8) -> List[Dict[str, Any]]:
        """
        Si la génération IA retourne trop peu de questions, complète avec un set algorithmique léger
        dérivé des exigences (patterns standards). Rapide, zéro appel externe.
        """
        if questions is None:
            questions = []
        if len(questions) >= min_count:
            return questions

        needed = min_count - len(questions)
        # Prendre un petit échantillon des exigences pour générer des templates
        base = self._pick_requirement_sample(reqs, max_reqs=min(needed * 2, 12))

        templates = []
        for r in base:
            title = (r.get("title") or "").strip()
            domain = r.get("domain") or None
            rid = r.get("id")
            short = title[:60] if title else "exigence"
            # 5 templates variés (on en ajoutera autant que nécessaire)
            templates.extend([
                {
                    "id": str(uuid4()),
                    "text": f"Disposez-vous d'une procédure formalisée pour « {short} » ?",
                    "type": "yes_no",
                    "options": [],
                    "help_text": "Procédure documentée, validée et diffusée.",
                    "difficulty": "easy",
                    "domain": domain,
                    "requirement_ids": [rid] if rid else [],
                    "ai_confidence": 0.6,
                    "rationale": "",
                    "tags": []
                },
                {
                    "id": str(uuid4()),
                    "text": f"Quand la dernière revue liée à « {short} » a-t-elle été réalisée ?",
                    "type": "date",
                    "options": [],
                    "help_text": "Indiquez la date de la dernière revue ou audit interne.",
                    "difficulty": "medium",
                    "domain": domain,
                    "requirement_ids": [rid] if rid else [],
                    "ai_confidence": 0.6,
                    "rationale": "",
                    "tags": []
                },
                {
                    "id": str(uuid4()),
                    "text": f"Quels éléments de preuve pouvez-vous fournir concernant « {short} » ?",
                    "type": "textarea",
                    "options": [],
                    "help_text": "Ex: procédures, rapports, tickets, journaux.",
                    "difficulty": "medium",
                    "domain": domain,
                    "requirement_ids": [rid] if rid else [],
                    "ai_confidence": 0.6,
                    "rationale": "",
                    "tags": []
                },
                {
                    "id": str(uuid4()),
                    "text": f"Quel est le niveau de mise en œuvre actuel pour « {short} » ?",
                    "type": "single_choice",
                    "options": ["Non démarré", "En cours", "Partiellement en place", "Mis en œuvre", "Optimisé"],
                    "help_text": "",
                    "difficulty": "easy",
                    "domain": domain,
                    "requirement_ids": [rid] if rid else [],
                    "ai_confidence": 0.6,
                    "rationale": "",
                    "tags": []
                },
                {
                    "id": str(uuid4()),
                    "text": f"Indiquez le nombre d'incidents liés à « {short} » sur les 12 derniers mois.",
                    "type": "number",
                    "options": [],
                    "help_text": "Saisir une valeur entière (0 si aucun).",
                    "difficulty": "medium",
                    "domain": domain,
                    "requirement_ids": [rid] if rid else [],
                    "ai_confidence": 0.6,
                    "rationale": "",
                    "tags": []
                },
            ])

        # Déduplication par texte + tronquer au strict nécessaire
        completed = self._merge_unique_questions(questions, templates)
        return completed[:max(min_count, len(completed))]

    def _pick_requirement_sample(self, reqs: List[Dict[str, Any]], max_reqs: int = 16) -> List[Dict[str, Any]]:
        """
        Sélectionne un échantillon représentatif réparti sur toute la liste (déterministe, sans hasard).
        - Répartit sur toute la longueur (step calculé)
        - Complète par la fin si besoin
        """
        n = len(reqs)
        if n <= max_reqs:
            return list(reqs)

        step = max(1, n // max_reqs)
        sample = []
        idx = 0
        while len(sample) < max_reqs and idx < n:
            sample.append(reqs[idx])
            idx += step

        # Compléter si l’arrondi a laissé des “trous”
        i = n - 1
        while len(sample) < max_reqs and i >= 0:
            if reqs[i] not in sample:
                sample.append(reqs[i])
            i -= 1

        return sample[:max_reqs]

    def _build_prompt_from_requirements(self, reqs: List[Dict[str, Any]], language: str = "fr") -> str:
        """
        Prompt concis et déterministe pour DeepSeek à partir d'un échantillon d'exigences.
        Conçu pour stabilité JSON et rapidité. Demande explicitement 8 à 12 questions.
        """
        max_reqs = 16  # échantillon un peu plus large sans exploser les tokens
        sample = self._pick_requirement_sample(reqs, max_reqs=max_reqs)

        lines = []
        lines.append(f"LANGUE: {language}")
        lines.append("MISSION: Générer 8 à 12 questions d'audit pratiques, adaptées PME FR.")
        lines.append("FORMAT: Répondre STRICTEMENT en JSON valide, sans texte hors JSON.")
        lines.append("SCHEMA:")
        lines.append("""{
    "questions": [
        {
        "text": "...",
        "type": "yes_no|single_choice|multiple_choice|text|textarea|number|date|likert",
        "options": [],
        "help_text": "",
        "difficulty": "easy|medium|hard",
        "domain": "..."
        }
    ]
    }""")
        lines.append("CONSIGNES:")
        lines.append("- Questions claires et opérationnelles (éviter le blabla)")
        lines.append("- Varier les types (oui/non, choix, texte, date, nombre)")
        lines.append("- Fournir help_text si utile")
        lines.append("- AUCUN markdown, AUCUNE phrase hors JSON")
        lines.append("- Nombre de questions attendu: entre 8 et 12")

        lines.append(f"\nEXIGENCES À COUVRIR (aperçu, {len(sample)} sur {len(reqs)}) :")
        for r in sample:
            code = r.get("official_code") or r.get("id")
            title = r.get("title") or ""
            desc = (r.get("requirement_text") or "")[:110].replace("\n", " ")
            lines.append(f"- [{code}] {title} | {desc}")

        lines.append("\nRÉPONDS MAINTENANT AVEC UNIQUEMENT LE JSON DEMANDÉ :")
        return "\n".join(lines)

    async def _gather_with_concurrency(self, limit: int, coros_iterable):
        """
        Exécute des coroutines avec une limite de concurrence.
        """
        import asyncio
        sem = asyncio.Semaphore(max(1, int(limit)))
        results = []

        async def _run(coro):
            async with sem:
                return await coro

        tasks = [asyncio.create_task(_run(c)) for c in coros_iterable]
        for t in tasks:
            try:
                results.append(await t)
            except Exception as e:
                logger.error(f"Tâche concurrente échouée: {e}")
                results.append([])
        return results

    
    async def _generate_for_framework(self, request: QuestionGenerationRequest) -> List[GeneratedQuestion]:
        """
        Génère des questions à partir d'un framework.
        Utilise _generate_via_deepseek qui gère déjà le batching et la normalisation.
        """
        # Utiliser la méthode existante qui fonctionne déjà
        questions_raw = await self._generate_via_deepseek(request)

        # Aplatir la structure items -> questions
        flat_questions = []
        for item in questions_raw:
            if isinstance(item, dict) and "questions" in item:
                # Structure: {"anchor_id": "...", "questions": [...]}
                anchor_id = item.get("anchor_id", "unknown")
                for q in item.get("questions", []):
                    if q:  # Ignorer les None
                        # Ajouter l'anchor_id/requirement_ids si pas déjà présent
                        if "requirement_ids" not in q and anchor_id != "unknown":
                            q["requirement_ids"] = [anchor_id]
                        elif "requirement_ids" not in q:
                            q["requirement_ids"] = []
                        flat_questions.append(q)
            elif isinstance(item, dict):
                # Déjà une question plate
                flat_questions.append(item)

        # Assigner les control points si nécessaire
        questions_enriched = await self._assign_control_points(flat_questions, request)

        # Convertir en GeneratedQuestion
        out: List[GeneratedQuestion] = []
        for q in questions_enriched:
            # Extraire requirement_ids
            requirement_ids = q.get("requirement_ids", [])
            if not isinstance(requirement_ids, list):
                requirement_ids = [requirement_ids] if requirement_ids else []

            try:
                generated_q = self._to_generated_question(
                    q,
                    requirement_ids=requirement_ids,
                    control_point_id=q.get("control_point_id")
                )
                out.append(generated_q)
            except Exception as e:
                logger.error(f"Erreur conversion question: {e}")
                continue

        logger.info(f"🎉 Total : {len(out)} questions générées pour le framework")
        return out

    def _build_validation_rules(self, question_data: dict) -> dict:
        """Construit les règles de validation selon le type de réponse."""
        q_type = question_data.get("type", "text")
        difficulty = question_data.get("difficulty", "medium")
        
        rules = {}
        
        if q_type == "yes_no":
            rules = {
                "requires_comment_if_no": True,
                "requires_evidence_if_no": True
            }
        
        elif q_type == "single_choice":
            rules = {
                "requires_selection": True,
                "allow_other": False
            }
        
        elif q_type == "multiple_choice":
            rules = {
                "min_selections": 1,
                "max_selections": 10,
                "allow_other": True
            }
        
        elif q_type == "rating":
            rules = {
                "min": 1,
                "max": 5,
                "scale_labels": [
                    "Non implémenté",
                    "Incomplet", 
                    "Partiel",
                    "Complet",
                    "Optimisé"
                ],
                "requires_comment_if_low": True,
                "low_threshold": 3
            }
        
        elif q_type == "number":
            rules = {
                "min": 0,
                "max": 100,
                "type": "integer",
                "unit": "%"
            }
        
        elif q_type == "date":
            rules = {
                "format": "YYYY-MM-DD",
                "min_date": "2020-01-01",
                "allow_future": False
            }
        
        elif q_type == "open":
            rules = {
                "min_length": 10,
                "max_length": 500,
                "multiline": True
            }
        
        return rules

    def _build_evidence_types(self, question_data: dict) -> list:
        """Détermine les types de preuves selon la difficulté."""
        difficulty = question_data.get("difficulty", "medium")
        
        if difficulty in ["hard", "critical"]:
            return ["document", "screenshot", "policy", "procedure", "audit_report"]
        elif difficulty == "medium":
            return ["document", "screenshot", "policy"]
        elif difficulty in ["easy", "basic"]:  # Support both for backwards compatibility
            return ["document", "screenshot"]
        else:
            return ["document"]

    def _estimate_time(self, question_data: dict) -> int:
        """Estime le temps de réponse selon la difficulté."""
        difficulty = question_data.get("difficulty", "medium")
        
        time_map = {
            "easy": 3,
            "basic": 3,  # Backwards compatibility
            "medium": 5,
            "hard": 10,
            "critical": 15
        }
        
        return time_map.get(difficulty, 5)


    def _build_prompt_for_requirement(
        self,
        req: Dict[str, Any],
        language: str = "fr",
        target_count: int = 5,
        alt: bool = False,
    ) -> str:
            """
            Prompt IA compact pour UNE exigence (latence faible).
            alt=True → variante de formulation pour 2e tentative.
            """
            code = req.get("official_code") or req.get("id")
            title = (req.get("title") or "").strip()
            desc = (req.get("requirement_text") or "").strip().replace("\n", " ")
            desc = desc[:350]  # limite tokens

            lines = []
            lines.append(f"LANGUE: {language}")
            lines.append("MISSION: Générer des questions d'audit pour UNE exigence, adaptées PME FR.")
            lines.append(f"NOMBRE_ATTENDU: {max(1, min(10, int(target_count)))} (±1)")
            lines.append("FORMAT: Répondre STRICTEMENT en JSON valide, sans texte hors JSON.")
            lines.append("SCHEMA: { \"questions\": [ { \"text\":\"...\", \"type\":\"yes_no|single_choice|multiple_choice|text|textarea|number|date|likert\", \"options\":[], \"help_text\":\"\", \"difficulty\":\"easy|medium|hard\", \"domain\":null } ] }")
            lines.append("CONSIGNES:")
            if not alt:
                lines.append("- Questions claires, opérationnelles, sans jargon inutile")
                lines.append("- Varier les types (oui/non, choix, texte, date, nombre)")
            else:
                lines.append("- Préférer yes_no, single_choice, textarea")
                lines.append("- Limiter la longueur des énoncés")
            lines.append("- AUCUN markdown, AUCUNE phrase hors JSON")

            lines.append(f"\nEXIGENCE [{code}]: {title}")
            if desc:
                lines.append(f"DESCRIPTION: {desc}")

            lines.append("\nRÉPONDS AVEC UNIQUEMENT LE JSON DEMANDÉ :")
            return "\n".join(lines)


    async def _generate_for_requirement_questions(
        self,
        req: Dict[str, Any],
        language: str = "fr",
        target_count: int = 5,
        min_count: int = 1,
        max_count: int = 10,
    ) -> List[Dict[str, Any]]:
            """
            Génère des questions pour UNE exigence.
            - 1re tentative IA rapide.
            - Si < min_count: 2e tentative IA avec un prompt alternatif.
            - Si encore insuffisant: complétion algorithmique locale.
            - Tronque à max_count.
            - Ajoute requirement_ids=[rid] systématiquement.
            """
            rid = str(req.get("id"))
            prompt1 = self._build_prompt_for_requirement(req, language, target_count)
            questions: List[Dict[str, Any]] = []

            try:
                resp1 = await self._call_deepseek_with_retry(prompt1)
                q1 = self._parse_questions(resp1)
                # attacher le rid + official_code + écrémage
                for q in q1:
                    q.setdefault("requirement_ids", [])
                    if rid not in q["requirement_ids"]:
                        q["requirement_ids"].append(rid)
                    # ✅ Ajouter official_code pour extraction du chapter
                    if "official_code" not in q and req.get("official_code"):
                        q["official_code"] = req.get("official_code")
                questions = q1
            except Exception as e:
                logger.warning(f"[QGen][{rid}] tentative 1 IA échouée: {e}")
                questions = []

            # 2e tentative si pas assez
            if len(questions) < min_count:
                prompt2 = self._build_prompt_for_requirement(req, language, target_count, alt=True)
                try:
                    resp2 = await self._call_deepseek_with_retry(prompt2)
                    q2 = self._parse_questions(resp2)
                    for q in q2:
                        q.setdefault("requirement_ids", [])
                        if rid not in q["requirement_ids"]:
                            q["requirement_ids"].append(rid)
                        # ✅ Ajouter official_code pour extraction du chapter
                        if "official_code" not in q and req.get("official_code"):
                            q["official_code"] = req.get("official_code")
                    # dédoublonnage
                    questions = self._merge_unique_questions(questions, q2)
                except Exception as e2:
                    logger.warning(f"[QGen][{rid}] tentative 2 IA échouée: {e2}")

            # complétion algorithmique jusqu'au minimum
            if len(questions) < min_count:
                questions = self._ensure_min_questions(questions, [req], min_count=min_count)

            # plafonner à max_count
            if len(questions) > max_count:
                questions = questions[:max_count]

            return questions


    

    # ------------------- MODE: CONTROL POINTS ------------------- #

    async def _generate_for_control_points(self, request: QuestionGenerationRequest) -> List[GeneratedQuestion]:
        """
        Génération à partir d'une liste de PC.
        Garantit >= 1 question / PC.
        """
        control_points = self._load_control_points(request.control_point_ids)

        target_per_pc = int((request.ai_params or {}).get("target_per_control_point", 2))
        min_per_pc = 1

        anchors = [
            {
                "anchor_id": str(cp.id),
                "code": cp.code,
                "title": cp.name,
                "description": (cp.description or "")[:600],
                "domain": getattr(cp, "category", None) or getattr(cp, "control_family", None),
                "subdomain": getattr(cp, "subcategory", None),
            }
            for cp in control_points
        ]
        prompt = self._build_prompt(anchors, mode="control_points", language=request.language)

        items = await self._ask_or_fallback(anchors, prompt, min_per_anchor=min_per_pc, target_per_anchor=target_per_pc)

        out: List[GeneratedQuestion] = []
        for item in items:
            cpid = item["anchor_id"]
            for q in item["questions"]:
                out.append(self._to_generated_question(q, control_point_id=cpid))

        return out

    # ===================== IA + Fallback ======================== #

    async def _ask_or_fallback(
        self,
        anchors: List[Dict[str, Any]],
        prompt: str,
        min_per_anchor: int,
        target_per_anchor: int,
    ) -> List[Dict[str, Any]]:
        # IA non dispo -> on lève (pas de fallback)
        if not (self.ai_enabled and self.ollama_url):
            raise RuntimeError("IA non disponible ou non configurée – fallback interdit")

        # IA dispo -> on tente
        response = await self._call_deepseek_with_retry(prompt)
        items = self._parse_items(response)
        # IMPORTANT: pas d'ajout de questions génériques
        return self._enforce_minimums(anchors, items, min_per_anchor, target_per_anchor)



    # --- deepseek_question_generator.py ---




    # ===================== Normalisation JSON =================== #

    # LIGNE 280-350 : REMPLACER _parse_items PAR CETTE VERSION

    def _parse_items(self, raw: str) -> List[Dict[str, Any]]:
        """
        Parse robuste de la réponse IA avec 5 stratégies de récupération.
        """
        import json
        import re
        
        if not raw or not raw.strip():
            logger.warning("⚠️ Réponse IA vide")
            return []
        
        logger.debug(f"📥 Réponse brute IA ({len(raw)} chars): {raw[:500]}...")

        # ✅ STRATÉGIE 0 : json-repair (si disponible) - LA PLUS ROBUSTE
        if repair_json:
            try:
                # Nettoyer les balises markdown
                cleaned = raw.strip()
                if cleaned.startswith('```'):
                    first_newline = cleaned.find('\n')
                    if first_newline > 0:
                        cleaned = cleaned[first_newline + 1:]
                if cleaned.endswith('```'):
                    cleaned = cleaned[:-3].strip()

                # Réparer et parser
                repaired = repair_json(cleaned)
                data = json.loads(repaired)
                logger.info(f"✅ JSON réparé avec json-repair (stratégie 0)")

                # Normaliser la structure
                if isinstance(data, dict) and "items" in data:
                    return data["items"]
                elif isinstance(data, dict) and "questions" in data:
                    return [{"anchor_id": "generated", "questions": data["questions"]}]
                elif isinstance(data, list):
                    return data
                return []
            except Exception as e:
                logger.warning(f"⚠️ Stratégie 0 (json-repair) échouée: {e}")

        # ✅ STRATÉGIE 1 : Extraction JSON entre ```json et ``` (ou tronqué)
        # D'abord essayer avec balises complètes
        json_match = re.search(r'```(?:json)?\s*(\{.*\}|\[.*\])\s*```', raw, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(1))
                logger.info(f"✅ JSON extrait des backticks (stratégie 1)")

                # Normaliser la structure
                if isinstance(data, dict) and "items" in data:
                    return data["items"]
                elif isinstance(data, dict) and "questions" in data:
                    # Convertir en format items
                    return [{"anchor_id": "generated", "questions": data["questions"]}]
                elif isinstance(data, list):
                    return data
                return []
            except json.JSONDecodeError as e:
                logger.warning(f"⚠️ Stratégie 1a (backticks complets) échouée: {e}")

        # Si ça échoue, essayer avec juste l'ouverture ```json (JSON tronqué)
        json_start = re.search(r'```(?:json)?\s*(\{.*)', raw, re.DOTALL)
        if json_start:
            try:
                json_content = json_start.group(1).strip()
                # Enlever la balise fermante si elle existe
                if json_content.endswith('```'):
                    json_content = json_content[:-3].strip()

                data = json.loads(json_content)
                logger.info(f"✅ JSON extrait des backticks partiels (stratégie 1b)")

                if isinstance(data, dict) and "items" in data:
                    return data["items"]
                elif isinstance(data, dict) and "questions" in data:
                    return [{"anchor_id": "generated", "questions": data["questions"]}]
                elif isinstance(data, list):
                    return data
                return []
            except json.JSONDecodeError as e:
                logger.warning(f"⚠️ Stratégie 1b (backticks partiels) échouée: {e}")
                # Si le JSON est tronqué, passer à la stratégie de récupération partielle
                pass
        
        # ✅ STRATÉGIE 2 : Extraction du premier objet/tableau JSON trouvé
        json_object_match = re.search(r'(\{.*\}|\[.*\])', raw, re.DOTALL)
        if json_object_match:
            try:
                data = json.loads(json_object_match.group(1))
                logger.info(f"✅ JSON trouvé (stratégie 2)")
                
                if isinstance(data, dict) and "items" in data:
                    return data["items"]
                elif isinstance(data, dict) and "questions" in data:
                    return [{"anchor_id": "generated", "questions": data["questions"]}]
                elif isinstance(data, list):
                    return data
                return []
            except json.JSONDecodeError as e:
                logger.warning(f"⚠️ Stratégie 2 échouée: {e}")
        
        # ✅ STRATÉGIE 3 : Parse direct après nettoyage basique
        try:
            cleaned = self._clean_json_response(raw)
            data = json.loads(cleaned)
            logger.info(f"✅ JSON parsé après nettoyage (stratégie 3)")
            
            if isinstance(data, dict) and "items" in data:
                return data["items"]
            elif isinstance(data, dict) and "questions" in data:
                return [{"anchor_id": "generated", "questions": data["questions"]}]
            elif isinstance(data, list):
                return data
            return []
        except json.JSONDecodeError as e:
            logger.warning(f"⚠️ Stratégie 3 échouée: {e}")
        
        # ✅ STRATÉGIE 4 : Nettoyage agressif
        cleaned = raw.strip()
        
        # Supprimer balises <think>
        cleaned = re.sub(r'<think>.*?</think>', '', cleaned, flags=re.DOTALL)
        
        # Extraire entre { et }
        if '{' in cleaned and '}' in cleaned:
            start_idx = cleaned.find('{')
            end_idx = cleaned.rfind('}') + 1
            cleaned = cleaned[start_idx:end_idx]
            
            try:
                data = json.loads(cleaned)
                logger.info(f"✅ JSON nettoyé parsé (stratégie 4)")
                
                if isinstance(data, dict) and "items" in data:
                    return data["items"]
                elif isinstance(data, dict) and "questions" in data:
                    return [{"anchor_id": "generated", "questions": data["questions"]}]
                return []
            except json.JSONDecodeError as e:
                logger.warning(f"⚠️ Stratégie 4 échouée: {e}")
        
        # ✅ STRATÉGIE 5 : Correction des erreurs courantes
        try:
            # Corriger clés sans guillemets
            fixed = re.sub(r'([{,]\s*)([A-Za-z0-9_]+)(\s*:)', r'\1"\2"\3', cleaned)
            
            # Remplacer quotes simples
            fixed = fixed.replace("'", '"')
            
            # Fixer virgules doubles
            fixed = re.sub(r',\s*,', ',', fixed)
            
            # Fixer virgules avant ]
            fixed = re.sub(r',\s*\]', ']', fixed)
            
            # Fixer virgules avant }
            fixed = re.sub(r',\s*\}', '}', fixed)
            
            # Supprimer trailing commas
            fixed = re.sub(r',(\s*[}\]])', r'\1', fixed)
            
            data = json.loads(fixed)
            logger.info(f"✅ JSON corrigé parsé (stratégie 5)")
            
            if isinstance(data, dict) and "items" in data:
                return data["items"]
            elif isinstance(data, dict) and "questions" in data:
                return [{"anchor_id": "generated", "questions": data["questions"]}]
            elif isinstance(data, list):
                return data
            return []
        except json.JSONDecodeError as e:
            logger.error(f"❌ Toutes les stratégies ont échoué. Dernière erreur: {e}")
            logger.error(f"📄 Contenu brut (1000 premiers chars):\n{raw[:1000]}")

        # ✅ STRATÉGIE 6 : Récupération partielle (JSON tronqué)
        logger.warning("⚠️ Tentative de récupération partielle du JSON tronqué...")
        try:
            # Retirer les balises markdown si présentes
            truncated = raw.strip()
            if truncated.startswith('```'):
                # Trouver la fin de la première ligne (```json)
                first_newline = truncated.find('\n')
                if first_newline > 0:
                    truncated = truncated[first_newline + 1:]

            # Retirer balise fermante si présente
            if truncated.endswith('```'):
                truncated = truncated[:-3].strip()

            logger.debug(f"🔍 Après nettoyage markdown, longueur: {len(truncated)}, fin: ...{truncated[-100:]}")

            # Chercher le début du tableau de questions
            if '"questions"' in truncated or '"items"' in truncated:
                # Si le JSON se termine mal, essayer de le compléter
                original_ending = truncated[-50:] if len(truncated) > 50 else truncated
                logger.debug(f"🔍 Fin originale du JSON: {original_ending}")

                # Compter les accolades et crochets pour voir si le JSON est fermé
                open_braces = truncated.count('{')
                close_braces = truncated.count('}')
                open_brackets = truncated.count('[')
                close_brackets = truncated.count(']')

                logger.debug(f"🔍 Comptage: {{ {close_braces}/{open_braces}, [ {close_brackets}/{open_brackets}")

                # Vérifier si le JSON se termine mal (pas proprement fermé ou tronqué dans une chaîne)
                ends_properly = truncated.rstrip().endswith('}') or truncated.rstrip().endswith(']')
                is_incomplete_braces = close_braces < open_braces or close_brackets < open_brackets

                # Vérifier si tronqué au milieu d'une chaîne (nombre impair de guillemets)
                # Note: compter seulement les guillemets qui ne sont pas échappés
                unescaped_quotes = len([c for i, c in enumerate(truncated) if c == '"' and (i == 0 or truncated[i-1] != '\\')])
                is_incomplete_string = (unescaped_quotes % 2) != 0

                if is_incomplete_braces or not ends_properly or is_incomplete_string:
                    logger.info(f"🔧 JSON incomplet détecté (braces={is_incomplete_braces}, ends_properly={ends_properly}, incomplete_string={is_incomplete_string}), tentative de complétion...")

                    # Trouver le dernier objet complet de question
                    # Chercher la dernière occurrence de "},\n" ou juste "}"
                    last_complete = truncated.rfind('},')
                    if last_complete == -1:
                        last_complete = truncated.rfind('}')

                    logger.debug(f"🔍 Dernière accolade complète trouvée à position: {last_complete}")

                    if last_complete > 0:
                        # Couper après le dernier objet complet
                        truncated = truncated[:last_complete + 1]

                        # Vérifier si on a des guillemets non fermés après la coupe
                        unescaped_quotes_after_cut = len([c for i, c in enumerate(truncated) if c == '"' and (i == 0 or truncated[i-1] != '\\')])
                        if (unescaped_quotes_after_cut % 2) != 0:
                            # Fermer la chaîne de caractères ouverte
                            truncated += '"'
                            logger.debug("🔧 Fermeture de chaîne de caractères ajoutée")

                        # Fermer proprement le JSON selon la structure attendue
                        # Structure attendue: {"questions": [...]}
                        missing_brackets = open_brackets - truncated.count(']')
                        missing_braces = open_braces - truncated.count('}')

                        completion = ']' * missing_brackets + '}' * missing_braces
                        truncated += completion

                        logger.debug(f"🔧 Ajout de fermetures: {completion}")
                        logger.debug(f"🔍 JSON complété (200 derniers chars): ...{truncated[-200:]}")

                        try:
                            data = json.loads(truncated)
                            logger.warning(f"✅ JSON partiellement récupéré (stratégie 6)")

                            if isinstance(data, dict) and "items" in data:
                                logger.info(f"✅ Récupéré {len(data['items'])} items partiels")
                                return data["items"]
                            elif isinstance(data, dict) and "questions" in data:
                                logger.info(f"✅ Récupéré {len(data['questions'])} questions partielles")
                                return [{"anchor_id": "generated", "questions": data["questions"]}]
                        except json.JSONDecodeError as parse_err:
                            logger.warning(f"⚠️ Parse JSON échoué après complétion: {parse_err}")
                            logger.debug(f"🔍 Position erreur: {parse_err.pos if hasattr(parse_err, 'pos') else 'N/A'}")
                            pass
        except Exception as recovery_error:
            logger.warning(f"⚠️ Récupération partielle échouée: {recovery_error}")
            import traceback
            logger.debug(f"Stack trace: {traceback.format_exc()}")

        # ❌ Échec total
        raise ValueError(f"JSON totalement invalide après toutes corrections. Extrait: {raw[:400]}")


    def _normalize_question_dict(self, q: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Nettoie un dict de question et mappe les types vers notre schéma."""
        text = (q or {}).get("text", "") or ""
        text = text.strip()
        if not text:
            return None

        typ = (q or {}).get("type", "open").strip().lower()
        # Mapping vers nos types
        # - boolean
        # - single_choice
        # - multiple_choice
        # - open
        # - rating
        # - number
        # - date
        if typ in ["yes_no", "boolean", "bool"]:
            typ = "boolean"
        elif typ in ["single", "single_choice", "choice"]:
            typ = "single_choice"
        elif typ in ["multi", "multiple", "multiple_choice", "multi_choice"]:
            typ = "multiple_choice"
        elif typ in ["text", "textarea", "open"]:
            typ = "open"
        elif typ in ["likert", "rating", "scale"]:
            typ = "rating"
        elif typ in ["number", "numeric", "integer", "int"]:
            typ = "number"
        elif typ in ["date", "datetime"]:
            typ = "date"
        else:
            typ = "open"

        options = q.get("options")
        if typ in ["single_choice", "multiple_choice"]:
            if not options or not isinstance(options, list):
                # options minimales de secours
                options = ["Oui", "Partiel", "Non"]
            else:
                options = [str(o).strip() for o in options if str(o).strip()][:12]
                if not options:
                    options = ["Oui", "Partiel", "Non"]
            # For rating, add standard likert if empty
            if typ == "rating" and (not options or len(options) == 0):
                options = ["Non implémenté", "Incomplet", "Partiel", "Complet", "Optimisé"]
        else:
            options = None

        difficulty = (q.get("difficulty") or "medium").lower()
        if difficulty not in ["easy", "medium", "hard"]:
            difficulty = "medium"

        help_text = q.get("help_text")
        if help_text:
            help_text = str(help_text).strip()
            if len(help_text) > 600:
                help_text = help_text[:600] + "…"

        tags = q.get("tags") or []
        if isinstance(tags, list):
            tags = [str(t).strip() for t in tags if str(t).strip()]
        else:
            tags = []

        # Nouveaux champs pour upload conditions
        is_mandatory = q.get("is_mandatory", False)
        if not isinstance(is_mandatory, bool):
            is_mandatory = False

        upload_conditions = q.get("upload_conditions")
        if upload_conditions and isinstance(upload_conditions, dict):
            # Valider la structure minimale
            if "required_for_values" not in upload_conditions:
                upload_conditions = None
        else:
            upload_conditions = None

        return {
            "text": text,
            "type": typ,
            "options": options,
            "help_text": help_text,
            "difficulty": difficulty,
            "tags": tags,
            "is_mandatory": is_mandatory,
            "upload_conditions": upload_conditions,
        }

    def _enforce_minimums(
        self,
        anchors: List[Dict[str, Any]],
        items: List[Dict[str, Any]],
        min_per_anchor: int,
        target_per_anchor: int,
    ) -> List[Dict[str, Any]]:
        by_id: Dict[str, List[Dict[str, Any]]] = {str(a["anchor_id"]): [] for a in anchors}
        for it in items:
            aid = str(it["anchor_id"])
            if aid in by_id:
                by_id[aid].extend(it["questions"])

        out: List[Dict[str, Any]] = []
        for a in anchors:
            aid = str(a["anchor_id"])
            qs = by_id.get(aid, [])
            # on coupe si trop long, mais on NE complète PLUS JAMAIS
            if len(qs) > max(target_per_anchor, min_per_anchor):
                qs = qs[:max(target_per_anchor, min_per_anchor)]
            if qs:
                out.append({"anchor_id": aid, "questions": qs})
            # (option stricte) si tu préfères lever quand < min :
            # else:
            #     raise RuntimeError(f"IA a renvoyé 0 question pour {aid} – fallback interdit")
        return out


    # ===================== Fallback algorithmique ================= #

    def _fallback_generate(
        self,
        anchors: List[Dict[str, Any]],
        min_per_anchor: int,
        target_per_anchor: int,
    ) -> List[Dict[str, Any]]:
        """Génération simple et déterministe, mais utile et couvrante."""
        items: List[Dict[str, Any]] = []
        for a in anchors:
            qs = self._fallback_questions_for_anchor(a, max(min_per_anchor, target_per_anchor))
            items.append({"anchor_id": str(a["anchor_id"]), "questions": qs})
        return items

    def _fallback_questions_for_anchor(self, anchor: Dict[str, Any], n: int) -> List[Dict[str, Any]]:
        """
        Génère N questions « base » en se basant sur le titre/description exigence ou PC.
        On varie un peu les types pour éviter l’ennui.
        """
        title = anchor.get("title") or anchor.get("official_code") or anchor.get("code") or "Contrôle"
        desc = anchor.get("requirement_text") or anchor.get("description") or ""

        base = []
        # 1: binaire présence
        base.append({
            "text": f"Une politique/procédure formalisée existe-t-elle pour « {title} » ?",
            "type": "boolean",
            "options": None,
            "help_text": f"Décrivez brièvement le dispositif en place. {desc[:140]}".strip(),
            "difficulty": "easy",
            "tags": ["existence", "policy"]
        })
        # 2: maturité (rating)
        base.append({
            "text": f"Quel est le niveau de maturité actuel pour « {title} » ?",
            "type": "rating",
            "options": ["Non implémenté", "Incomplet", "Partiel", "Complet", "Optimisé"],
            "help_text": "Évaluez le niveau d'implémentation actuel.",
            "difficulty": "medium",
            "tags": ["maturity"]
        })
        # 3: preuve (open)
        base.append({
            "text": f"Quelles preuves pouvez-vous fournir pour démontrer « {title} » ?",
            "type": "open",
            "options": None,
            "help_text": "Exemples: procédure, captures d'écran, export de configuration, rapport",
            "difficulty": "medium",
            "tags": ["evidence"]
        })
        # 4: couverture (single_choice)
        base.append({
            "text": f"Quelle est l'étendue de couverture de « {title} » ?",
            "type": "single_choice",
            "options": ["Aucune", "Partielle", "Majorité des périmètres", "Généralisée"],
            "help_text": None,
            "difficulty": "medium",
            "tags": ["coverage"]
        })
        # 5: indicateurs (open)
        base.append({
            "text": f"Quels indicateurs ou métriques suivez-vous pour « {title} » ?",
            "type": "open",
            "options": None,
            "help_text": None,
            "difficulty": "hard",
            "tags": ["kpi"]
        })

        # Tronquer/dupliquer de façon simple pour atteindre n
        out: List[Dict[str, Any]] = []
        i = 0
        while len(out) < n:
            out.append(base[i % len(base)])
            i += 1
        return out

    # ===================== Utils de construction ================= #

    def _build_prompt(self, anchors: List[Dict[str, Any]], mode: str, language: str = "fr") -> str:
        """
        Construit le message utilisateur pour DeepSeek.
        On envoie une liste 'anchors', chacun représentant une exigence (mode framework)
        ou un PC (mode control_points).
        """
        # Exemple concret pour guider l'IA sur le format attendu
        example_question = {
            "text": "L'organisation dispose-t-elle d'une politique de sécurité approuvée ?",
            "type": "single_choice",
            "options": ["Oui", "Partiellement", "Non"],
            "is_mandatory": True,
            "difficulty": "hard",  # Adapté selon criticality_level (LOW=easy, MEDIUM=medium, HIGH/CRITICAL=hard)
            "question_code": "ISO27001-A5.1-Q1",  # Format: {FRAMEWORK}-{CHAPTER}-Q{NUM}
            "chapter": "A.5",  # Extrait de official_code (ex: "A.5.1.1" → "A.5")
            "evidence_types": ["policy", "evidence"],  # Types suggérés selon type de question
            "estimated_time_minutes": 5,
            "help_text": "Vérifier dans le référentiel documentaire",
            "upload_conditions": {
                "required_for_values": ["Oui"],
                "attachment_types": ["policy", "evidence"],
                "min_files": 1,
                "max_files": 2,
                "accepts_links": True,
                "help_text": "Joindre la politique signée",
                "is_mandatory": True
            },
            "tags": ["politique", "gouvernance"]
        }

        # ⚠️ PROMPT STRUCTURÉ pour forcer l'IA à générer tous les champs
        # On envoie les anchors avec leurs métadonnées critiques
        instruction = {
            "task": "Générer des questions d'audit en français",
            "format": "JSON strict",
            "required_fields": {
                "text": "Question claire et précise",
                "type": "boolean|single_choice|multiple_choice|open|number|date",
                "options": "Array si choice, null sinon",
                "difficulty": "OBLIGATOIRE - Utiliser anchor.criticality_level : LOW=easy, MEDIUM=medium, HIGH=hard, CRITICAL=hard",
                "question_code": "OBLIGATOIRE - Format ISO27001-{chapter}-Q{num} ex: ISO27001-A5.1-Q1",
                "chapter": "OBLIGATOIRE - Extraire de anchor.official_code ex: A.5.1.1→A.5",
                "evidence_types": "OBLIGATOIRE - Array ex: ['policy','evidence'] ou ['screenshot','report']",
                "tags": "OBLIGATOIRE - 2-3 mots-clés ex: ['politique','SMSI']",
                "is_mandatory": "true si anchor.criticality_level=HIGH|CRITICAL, false sinon",
                "estimated_time_minutes": "3-10 selon complexité",
                "help_text": "Guidance technique",
                "upload_conditions": "Objet ou null"
            },
            "example": example_question,
            "anchors": anchors[:200]
        }

        return json.dumps(instruction, ensure_ascii=False)

    @staticmethod
    def _clean_json_response(s: str) -> str:
        """Nettoie la réponse IA en retirant tout ce qui entoure le JSON."""
        if not s:
            return "{}"
        s = s.strip()

        # Enlever éventuels blocs <think>...</think> ou balises similaires
        s = re.sub(r"<think>.*?</think>", "", s, flags=re.DOTALL)

        # Enlever éventuels ```json ... ``` ou ``` ```
        s = re.sub(r"^```(?:json)?", "", s, flags=re.IGNORECASE).strip("` \n")

        # Chercher la première et la dernière accolade valide
        first = s.find("{")
        last = s.rfind("}")

        if first != -1 and last != -1 and last > first:
            cleaned = s[first:last + 1]
        else:
            # Fallback : essayer d'extraire un fragment JSON avec regex
            match = re.search(r"\{.*\}", s, re.DOTALL)
            cleaned = match.group(0) if match else "{}"

        # Supprimer les caractères parasites avant/après
        cleaned = cleaned.strip()

        # Corriger les retours de ligne ou quotes mal échappés
        cleaned = cleaned.replace("\n", " ").replace("\r", " ")

        return cleaned


    def _coerce_and_enrich_questions(self, items: list[dict]) -> list[dict]:
        """
        - Normalise les champs (ex: upload_conditions string -> objet)
        - Remplit les valeurs par défaut attendues par le backend
        - ✅ Génère automatiquement les métadonnées manquantes (question_code, chapter, evidence_types)
        - ✅ Valide et normalise response_type selon la table question_type
        """
        import json

        out: list[dict] = []
        question_counter = 1  # Compteur pour question_code

        for q in items:
            if not isinstance(q, dict):
                continue

            # ✅ NORMALISER LE TYPE AVANT TOUTE CHOSE (pour conformité FK)
            q = self._normalize_response_type(q)

            # alias éventuels renvoyés par le prompt
            if "text" in q and "question_text" not in q:
                q["question_text"] = q["text"]
            if "type" in q and "response_type" not in q:
                q["response_type"] = q["type"]
            if "is_mandatory" in q and "is_required" not in q:
                q["is_required"] = bool(q.get("is_mandatory"))

            # champs obligatoires côté DB (voir table public.question)
            q.setdefault("validation_rules", {})
            q.setdefault("help_text", "")
            q.setdefault("difficulty", q.get("difficulty_level", "medium"))
            q.setdefault("estimated_time_minutes", 5)
            q.setdefault("ai_generated", True)
            q.setdefault("created_by", "ai")
            q.setdefault("is_active", True)

            # 🔧 upload_conditions peut arriver en STRING JSON → convertir en OBJET
            uc = q.get("upload_conditions")
            if isinstance(uc, str):
                try:
                    q["upload_conditions"] = json.loads(uc)
                except Exception:
                    logger.warning("[QGen] upload_conditions string non JSON -> ignoré")
                    q["upload_conditions"] = None

            # "tags" peut être stringifié comme "[]"
            tags = q.get("tags")
            if isinstance(tags, str):
                try:
                    q["tags"] = json.loads(tags)
                except Exception:
                    q["tags"] = []

            # Evidence types stringifiés (rare)
            ev = q.get("evidence_types")
            if isinstance(ev, str):
                try:
                    q["evidence_types"] = json.loads(ev)
                except Exception:
                    q["evidence_types"] = []

            # Difficulté → normaliser pour l'API
            if "difficulty_level" in q and "difficulty" not in q:
                q["difficulty"] = q["difficulty_level"]

            # ✅ FALLBACK: Générer automatiquement les métadonnées si manquantes
            q = self._auto_generate_metadata(q, question_counter)
            question_counter += 1

            out.append(q)

        # 📊 LOG RÉSUMÉ : Statistiques de normalisation
        if out:
            type_counts = {}
            for q in out:
                rt = q.get("response_type", "unknown")
                type_counts[rt] = type_counts.get(rt, 0) + 1

            logger.info(f"✅ [COERCE] {len(out)} questions enrichies - Répartition types: {type_counts}")

        return out

    @staticmethod
    def _normalize_response_type(q: dict) -> dict:
        """
        Normalise le champ 'type' ou 'response_type' pour qu'il corresponde
        aux valeurs valides de la table question_type.

        Types valides (codes de question_type):
        - boolean
        - single_choice
        - multiple_choice
        - open
        - number
        - date
        - rating

        Args:
            q: Question dict avec champ 'type' ou 'response_type'

        Returns:
            Question avec type normalisé
        """
        # Récupérer le type depuis 'type' ou 'response_type'
        original_type = q.get("type") or q.get("response_type") or "open"
        typ = original_type.strip().lower()

        # Mapping des variantes vers les codes valides
        if typ in ["yes_no", "boolean", "bool", "yes/no", "oui/non"]:
            normalized = "boolean"
        elif typ in ["single", "single_choice", "choice", "radio"]:
            normalized = "single_choice"
        elif typ in ["multi", "multiple", "multiple_choice", "multi_choice", "checkbox"]:
            normalized = "multiple_choice"
        elif typ in ["text", "textarea", "open", "texte", "libre"]:
            normalized = "open"
        elif typ in ["likert", "rating", "scale", "échelle", "notation"]:
            normalized = "rating"
        elif typ in ["number", "numeric", "integer", "int", "nombre"]:
            normalized = "number"
        elif typ in ["date", "datetime", "calendar"]:
            normalized = "date"
        else:
            # Fallback : si type inconnu, on met "open" (texte libre)
            logger.warning(f"⚠️ [TYPE_NORMALIZATION] Type inconnu '{original_type}' → normalisé en 'open' (question: {q.get('text', 'N/A')[:50]}...)")
            normalized = "open"

        # 🔍 LOG : Afficher uniquement si normalisation effectuée
        if normalized != typ and typ in ["text", "single", "multi", "textarea", "yes_no", "checkbox", "radio"]:
            logger.info(f"✅ [TYPE_NORMALIZATION] '{original_type}' → '{normalized}' (question: {q.get('text', 'N/A')[:50]}...)")

        # Mettre à jour les deux champs pour cohérence
        q["type"] = normalized
        q["response_type"] = normalized

        return q

    def _auto_generate_metadata(self, q: dict, counter: int) -> dict:
        """
        Génère automatiquement les métadonnées manquantes (fallback).

        Args:
            q: Question dict
            counter: Numéro de question pour génération du code

        Returns:
            Question enrichie
        """
        # 1. Générer question_code si manquant
        if not q.get("question_code"):
            req_code = q.get("requirement_code") or q.get("official_code")
            if req_code:
                chapter = self._extract_chapter_from_code(req_code)
                q["question_code"] = f"ISO27001-{chapter}-Q{counter}" if chapter else f"CUSTOM-GEN-Q{counter}"
            else:
                q["question_code"] = f"CUSTOM-GEN-Q{counter}"

        # 2. Générer chapter si manquant
        if not q.get("chapter"):
            req_code = q.get("requirement_code") or q.get("official_code")
            if req_code:
                q["chapter"] = self._extract_chapter_from_code(req_code)

        # 3. Générer evidence_types si vide
        if not q.get("evidence_types") or (isinstance(q.get("evidence_types"), list) and len(q["evidence_types"]) == 0):
            q["evidence_types"] = self._generate_evidence_types(
                question_type=q.get("type") or q.get("response_type", "open"),
                difficulty=q.get("difficulty", "medium")
            )

        return q

    @staticmethod
    def _extract_chapter_from_code(official_code: str) -> Optional[str]:
        """
        Extrait le chapitre depuis un code officiel.

        Exemples:
        - "A.5.1.1" → "A.5"
        - "A.6.2.1" → "A.6"
        - "5.1.2" → "5.1"
        """
        if not official_code:
            return None

        code = str(official_code).strip()

        if "." in code:
            parts = code.split(".")
            if len(parts) >= 2:
                return f"{parts[0]}.{parts[1]}"

        return None

    @staticmethod
    def _generate_evidence_types(question_type: str, difficulty: str) -> list[str]:
        """
        Génère les types de preuves suggérés selon le type et la difficulté.

        Args:
            question_type: Type de question
            difficulty: Niveau de difficulté

        Returns:
            Liste des types de preuves
        """
        # Mapping type → evidence_types par défaut
        type_mapping = {
            "boolean": ["policy", "evidence", "screenshot"],
            "single_choice": ["screenshot", "report", "evidence"],
            "multiple_choice": ["screenshot", "report", "evidence"],
            "open": ["policy", "evidence", "screenshot"],
            "number": ["report", "screenshot", "log"],
            "date": ["report", "evidence", "screenshot"],
            "rating": ["evidence", "report"]
        }

        base_types = type_mapping.get(question_type.lower(), ["document", "evidence"])

        # Enrichir selon difficulté
        difficulty_lower = (difficulty or "medium").lower()

        if difficulty_lower in ["hard", "high", "critical"]:
            # Questions difficiles → plus de types de preuves
            additional = ["audit_report", "procedure"]
            for t in additional:
                if t not in base_types:
                    base_types.append(t)

        return base_types


    def _to_generated_question(
        self,
        q: Dict[str, Any],
        requirement_ids: Optional[List[str]] = None,
        control_point_id: Optional[str] = None,
    ) -> GeneratedQuestion:
        """Transforme un dict de question normalisé → GeneratedQuestion."""
        text = q.get("text", "")
        if not text:
            raise ValueError("Question text is required")

        typ = q.get("type", "open")
        # Map vers nos types (schemas.questionnaire)
        # - boolean
        # - single_choice
        # - multiple_choice
        # - open
        # - rating
        # - number
        # - date
        mapped_type = {
            "boolean": "boolean",
            "single_choice": "single_choice",
            "multiple_choice": "multiple_choice",
            "open": "open",
            "rating": "rating",
            "number": "number",
            "date": "date",
        }.get(typ, "open")

        return GeneratedQuestion(
            id=str(uuid4()),
            text=text,
            type=mapped_type,  # Literal accepté par notre schéma
            options=q.get("options"),
            control_point_id=control_point_id,
            requirement_ids=requirement_ids or [],
            difficulty=q.get("difficulty"),
            ai_confidence=q.get("ai_confidence"),
            rationale=q.get("rationale"),
            help_text=q.get("help_text"),  # ✅ Aide contextuelle pour l'audité (DISTINCT de rationale)
            tags=q.get("tags", []),
            is_mandatory=q.get("is_mandatory", False),
            upload_conditions=q.get("upload_conditions"),
        )

    # ===================== Chargements BDD ======================= #

    def _load_framework_and_requirements(self, framework_id: Optional[str]) -> Tuple[Framework, List[Requirement]]:
        if not framework_id:
            raise ValueError("framework_id is required for mode 'framework'")

        fw = self.db.query(Framework).filter_by(id=framework_id, is_active=True).first()
        if not fw:
            raise ValueError("Framework not found or inactive")

        # Récupérer toutes les exigences actives pour ce framework
        reqs = self.db.execute(
            text(
                """
                SELECT id, official_code, title, requirement_text, domain_id, -- modèle 'audit' utilise domain_id
                       NULL::text as domain, NULL::text as subdomain
                FROM requirement
                WHERE framework_id = :fid AND is_active = true
                ORDER BY official_code NULLS LAST, created_at
                """
            ),
            {"fid": str(fw.id)},
        ).mappings().all()

        # Si tu stockes 'domain' / 'subdomain' en colonnes texte dans ton autre modèle,
        # tu peux adapter la sélection. Ici on reste compatible avec le dump fourni.

        # Convertir en pseudo-objets Requirement via SQLAlchemy si besoin
        # mais ici on renvoie les Mapping rows (dict-like) – suffisant pour le prompt.
        # Pour la conformité des types attendus par _to_generated_question,
        # on a seulement besoin des IDs.

        # Par cohérence, on fabrique des "objets" légers avec attributs :
        class RWrap:
            def __init__(self, row):
                self.id = row["id"]
                self.official_code = row["official_code"]
                self.title = row["title"]
                self.requirement_text = row["requirement_text"]
                self.domain = row["domain"]
                self.subdomain = row["subdomain"]

        requirements = [RWrap(r) for r in reqs]
        return fw, requirements

    def _load_control_points(self, cp_ids: Optional[List[str]]) -> List[ControlPoint]:
        if not cp_ids:
            raise ValueError("control_point_ids is required for mode 'control_points'")

        rows = self.db.execute(
            text(
                """
                SELECT id, code, name, description, category, subcategory, control_family
                FROM control_point
                WHERE id::text = ANY(:ids)
                """
            ),
            {"ids": cp_ids},
        ).mappings().all()

        class CPWrap:
            def __init__(self, row):
                self.id = row["id"]
                self.code = row["code"]
                self.name = row["name"]
                self.description = row["description"]
                self.category = row["category"]
                self.subcategory = row["subcategory"]
                self.control_family = row["control_family"]

        return [CPWrap(r) for r in rows]
    
    def _fallback_generate(self, *args, **kwargs):
        raise RuntimeError("Fallback algorithmique désactivé")

    def _fallback_questions_for_anchor(self, *args, **kwargs):
        raise RuntimeError("Fallback algorithmique désactivé")
    

    # LIGNE 730-800 : AMÉLIORER _call_deepseek_with_retry

    # LIGNE 1080-1150 : AMÉLIORER _call_deepseek_with_retry

    async def _call_deepseek_with_retry(self, prompt: str) -> str:
        """
        Appel du modèle DeepSeek (via Ollama/OpenAI-compatible) avec:
        - messages = [system, user]
        - retries + backoff
        - timeouts progressifs
        - gestion 5xx/502 Bad Gateway
        - support multi-endpoints (Ollama + OpenAI-like)
        """
        if not self.ollama_url:
            raise RuntimeError("ollama_url non configurée")

        # Chemin d'API : supporte /api/chat (Ollama 0.1+) et /v1/chat/completions (OpenAI-like)
        # on tente d'abord /api/chat (Ollama), sinon fallback OpenAI-like.
        endpoints = [
            f"{self.ollama_url.rstrip('/')}/api/chat",
            f"{self.ollama_url.rstrip('/')}/v1/chat/completions",
        ]

        def build_payload(is_openai: bool) -> Dict[str, Any]:
            messages = [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
            if not is_openai:
                # Ollama chat endpoint
                return {
                    "model": self.model,
                    "messages": messages,
                    "format": "json",
                    "stream": False,
                    "keep_alive": "5m",
                    "options": {
                        "temperature": self.temperature,
                        "top_p": 0.9,
                        "num_predict": self.max_tokens,
                        "repeat_penalty": 1.1,
                    },
                }
            # OpenAI-like
            return {
                "model": self.model,
                "messages": messages,
                "temperature": self.temperature,
                "top_p": 0.9,
                "stream": False,
                "max_tokens": self.max_tokens,
                "response_format": {"type": "json_object"},
            }

        def extract_text(resp_json: Dict[str, Any], is_openai: bool) -> str:
            # Ollama /api/chat -> {"message": {"content": "..."}}
            if not is_openai:
                return resp_json.get("message", {}).get("content", "")
            # OpenAI-like -> {"choices":[{"message":{"content":"..."}}]}
            choices = resp_json.get("choices") or []
            if choices and "message" in choices[0]:
                return choices[0]["message"].get("content", "")
            # certains serveurs renvoient directement "content"
            return resp_json.get("content", "")

        last_error = None
        for attempt in range(1, self.max_retries + 1):
            for idx, ep in enumerate(endpoints):
                is_openai = ep.endswith("/v1/chat/completions")
                try:
                    base_timeout = 120  # base par tentative
                    timeout_seconds = base_timeout * attempt
                    timeout = httpx.Timeout(connect=30.0, read=float(timeout_seconds), write=30.0, pool=30.0)

                    payload = build_payload(is_openai)
                    logger.debug(f"➡️ POST {ep} (try {attempt}/{self.max_retries})")

                    async with httpx.AsyncClient(timeout=timeout, verify=True) as client:
                        r = await client.post(ep, json=payload)
                        if r.status_code >= 500:
                            raise RuntimeError(f"Upstream {r.status_code}: {r.text}")
                        if r.status_code == 404 and idx == 0:
                            # /api/chat absent -> tenter fallback OpenAI-like
                            logger.info("ℹ️ Endpoint /api/chat introuvable, essai OpenAI-like...")
                            continue
                        r.raise_for_status()

                        data = r.json()
                        content = extract_text(data, is_openai)
                        if not content:
                            # certains serveurs renvoient 'response' ou 'message'
                            content = data.get("response") or data.get("message") or ""

                        if not content.strip():
                            raise RuntimeError("Réponse DeepSeek vide")

                        logger.debug(f"✅ Réponse IA reçue ({len(content)} chars)")
                        return content

                except (httpx.ReadTimeout, httpx.ConnectTimeout) as e:
                    last_error = e
                    logger.warning(f"⏳ Timeout (tentative {attempt}) sur {ep}: {e}")
                except httpx.HTTPError as e:
                    last_error = e
                    code = getattr(e.response, "status_code", "N/A")
                    body = getattr(e.response, "text", "")
                    logger.error(f"❌ HTTPError {code} sur {ep}: {body[:500]}")
                    # 4xx: ne pas réessayer sur ce endpoint, passer au suivant ou prochaine tentative
                except Exception as e:
                    last_error = e
                    logger.error(f"❌ Exception appel IA ({type(e).__name__}): {e}")

            # Backoff exponentiel
            await asyncio.sleep(min(2 ** attempt, 10))

        raise RuntimeError(f"Échec appel DeepSeek après {self.max_retries} tentatives: {last_error}")


    async def _call_deepseek_generate(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "top_p": 0.9,
                "num_predict": self.max_tokens,
            },
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(self.timeout)) as client:
            url = f"{self.ollama_url.rstrip('/')}/api/generate"
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            if "response" in data:
                return data["response"]
            raise ValueError("Structure de réponse inconnue pour /api/generate")

    # --- Ajoutez ces 2 fonctions utilitaires dans la classe DeepSeekQuestionGenerator ---

def _normalize_ai_item(self, item: Any) -> Dict[str, Any]:
    """Tolérant: transforme str/objets 'bizarres' en dict question standard."""
    if isinstance(item, str):
        return {"text": item.strip(), "type": "text", "options": [], "help_text": "", "difficulty": "medium"}
    if isinstance(item, dict):
        # Harmoniser quelques alias fréquents
        if "question" in item and "text" not in item:
            item["text"] = item.pop("question")
        item.setdefault("text", "")
        item.setdefault("type", "text")
        item.setdefault("options", [])
        item.setdefault("help_text", item.get("rationale", ""))
        item.setdefault("difficulty", item.get("difficulty", "medium"))
        return item
    # Dernier recours
    return {"text": str(item).strip(), "type": "text", "options": [], "help_text": "", "difficulty": "medium"}

def _normalize_ai_questions(self, raw_list: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw_list, list):
        raw_list = [raw_list] if raw_list is not None else []
    return [self._normalize_ai_item(x) for x in raw_list]
