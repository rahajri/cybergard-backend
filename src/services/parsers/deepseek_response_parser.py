"""
DeepSeek Response Parser

Parser robuste pour traiter les réponses JSON de DeepSeek/Ollama avec 6 stratégies
de récupération pour gérer les JSON malformés, tronqués ou avec balises markdown.

Version: 1.0
Date: 2025-01-08
"""

import json
import re
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# Importation conditionnelle de json-repair
try:
    from json_repair import repair_json
except ImportError:
    repair_json = None
    logger.warning("⚠️ json-repair non disponible, stratégie 0 désactivée")


class DeepSeekResponseParser:
    """
    Parser robuste avec 6 stratégies de récupération JSON.

    Stratégies:
    0. json-repair (si disponible) - La plus robuste
    1. Extraction markdown avec balises ```json```
    2. Extraction du premier objet/tableau JSON
    3. Parse direct après nettoyage basique
    4. Nettoyage agressif avec extraction entre { }
    5. Correction des erreurs courantes (quotes, virgules)
    6. Récupération partielle pour JSON tronqué
    """

    @staticmethod
    def parse(raw_response: str) -> List[Dict[str, Any]]:
        """
        Parse la réponse brute de l'IA en utilisant les 6 stratégies.

        Args:
            raw_response: Réponse brute de l'IA (peut contenir markdown, balises, etc.)

        Returns:
            Liste de questions parsées (format: [{"anchor_id": "...", "questions": [...]}])
            ou liste vide si échec complet
        """
        if not raw_response or not raw_response.strip():
            logger.warning("⚠️ Réponse IA vide")
            return []

        logger.debug(f"📥 Réponse brute IA ({len(raw_response)} chars): {raw_response[:500]}...")

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # ✅ STRATÉGIE 0 : json-repair (si disponible) - LA PLUS ROBUSTE
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        if repair_json:
            try:
                cleaned = raw_response.strip()

                # Nettoyer les balises markdown
                if cleaned.startswith('```'):
                    first_newline = cleaned.find('\n')
                    if first_newline > 0:
                        cleaned = cleaned[first_newline + 1:]
                if cleaned.endswith('```'):
                    cleaned = cleaned[:-3].strip()

                # Réparer et parser
                repaired = repair_json(cleaned)
                data = json.loads(repaired)
                logger.info("✅ JSON réparé avec json-repair (stratégie 0)")

                return DeepSeekResponseParser._normalize_structure(data)
            except Exception as e:
                logger.warning(f"⚠️ Stratégie 0 (json-repair) échouée: {e}")

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # ✅ STRATÉGIE 1 : Extraction JSON entre ```json et ```
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

        # 1a. Balises complètes
        json_match = re.search(r'```(?:json)?\s*(\{.*\}|\[.*\])\s*```', raw_response, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(1))
                logger.info("✅ JSON extrait des backticks (stratégie 1a)")
                return DeepSeekResponseParser._normalize_structure(data)
            except json.JSONDecodeError as e:
                logger.warning(f"⚠️ Stratégie 1a (backticks complets) échouée: {e}")

        # 1b. Balise ouvrante seulement (JSON tronqué)
        json_start = re.search(r'```(?:json)?\s*(\{.*)', raw_response, re.DOTALL)
        if json_start:
            try:
                json_content = json_start.group(1).strip()
                if json_content.endswith('```'):
                    json_content = json_content[:-3].strip()

                data = json.loads(json_content)
                logger.info("✅ JSON extrait des backticks partiels (stratégie 1b)")
                return DeepSeekResponseParser._normalize_structure(data)
            except json.JSONDecodeError as e:
                logger.warning(f"⚠️ Stratégie 1b (backticks partiels) échouée: {e}")

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # ✅ STRATÉGIE 2 : Extraction du premier objet/tableau JSON trouvé
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        json_object_match = re.search(r'(\{.*\}|\[.*\])', raw_response, re.DOTALL)
        if json_object_match:
            try:
                data = json.loads(json_object_match.group(1))
                logger.info("✅ JSON trouvé (stratégie 2)")
                return DeepSeekResponseParser._normalize_structure(data)
            except json.JSONDecodeError as e:
                logger.warning(f"⚠️ Stratégie 2 échouée: {e}")

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # ✅ STRATÉGIE 3 : Parse direct après nettoyage basique
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        try:
            cleaned = DeepSeekResponseParser._clean_json_response(raw_response)
            data = json.loads(cleaned)
            logger.info("✅ JSON parsé après nettoyage (stratégie 3)")
            return DeepSeekResponseParser._normalize_structure(data)
        except json.JSONDecodeError as e:
            logger.warning(f"⚠️ Stratégie 3 échouée: {e}")

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # ✅ STRATÉGIE 4 : Nettoyage agressif
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        cleaned = raw_response.strip()

        # Supprimer balises <think>
        cleaned = re.sub(r'<think>.*?</think>', '', cleaned, flags=re.DOTALL)

        # Extraire entre { et }
        if '{' in cleaned and '}' in cleaned:
            start_idx = cleaned.find('{')
            end_idx = cleaned.rfind('}') + 1
            cleaned = cleaned[start_idx:end_idx]

            try:
                data = json.loads(cleaned)
                logger.info("✅ JSON nettoyé parsé (stratégie 4)")
                return DeepSeekResponseParser._normalize_structure(data)
            except json.JSONDecodeError as e:
                logger.warning(f"⚠️ Stratégie 4 échouée: {e}")

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # ✅ STRATÉGIE 5 : Correction des erreurs courantes
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
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
            logger.info("✅ JSON corrigé parsé (stratégie 5)")
            return DeepSeekResponseParser._normalize_structure(data)
        except json.JSONDecodeError as e:
            logger.warning(f"⚠️ Stratégie 5 échouée: {e}")

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # ✅ STRATÉGIE 6 : Récupération partielle (JSON tronqué)
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        logger.warning("⚠️ Tentative de récupération partielle du JSON tronqué...")
        try:
            result = DeepSeekResponseParser._recover_truncated_json(raw_response)
            if result:
                return result
        except Exception as e:
            logger.error(f"❌ Stratégie 6 (récupération partielle) échouée: {e}")

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # ❌ ÉCHEC COMPLET
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        logger.error("❌ Toutes les stratégies ont échoué")
        logger.error(f"📄 Contenu brut (1000 premiers chars):\n{raw_response[:1000]}")
        return []

    @staticmethod
    def _normalize_structure(data: Any) -> List[Dict[str, Any]]:
        """
        Normalise la structure JSON retournée par l'IA.

        Supporte:
        - {"items": [...]}
        - {"questions": [...]}
        - [...]
        - {}

        Returns:
            Format standardisé: [{"anchor_id": "generated", "questions": [...]}]
        """
        if isinstance(data, dict) and "items" in data:
            return data["items"]
        elif isinstance(data, dict) and "questions" in data:
            return [{"anchor_id": "generated", "questions": data["questions"]}]
        elif isinstance(data, list):
            return data
        elif isinstance(data, dict):
            # Fallback : si dict contient directement des questions
            return [data]
        return []

    @staticmethod
    def _clean_json_response(s: str) -> str:
        """
        Nettoie la réponse IA en retirant tout ce qui entoure le JSON.

        Args:
            s: Réponse brute

        Returns:
            JSON nettoyé (string)
        """
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
            cleaned = match.group(0) if match else s

        return cleaned

    @staticmethod
    def _recover_truncated_json(raw: str) -> Optional[List[Dict[str, Any]]]:
        """
        Tente de récupérer un JSON tronqué en le complétant intelligemment.

        Stratégie:
        1. Retirer balises markdown
        2. Détecter si JSON incomplet (braces non fermées, chaîne tronquée)
        3. Trouver le dernier objet complet
        4. Compléter les fermetures manquantes

        Args:
            raw: Réponse brute potentiellement tronquée

        Returns:
            Liste de questions si récupération réussie, None sinon
        """
        truncated = raw.strip()

        # Retirer les balises markdown si présentes
        if truncated.startswith('```'):
            first_newline = truncated.find('\n')
            if first_newline > 0:
                truncated = truncated[first_newline + 1:]

        if truncated.endswith('```'):
            truncated = truncated[:-3].strip()

        logger.debug(f"🔍 Après nettoyage markdown, longueur: {len(truncated)}")

        # Chercher le début du tableau de questions
        if '"questions"' not in truncated and '"items"' not in truncated:
            logger.warning("⚠️ Aucune structure de questions trouvée")
            return None

        # Compter les accolades et crochets
        open_braces = truncated.count('{')
        close_braces = truncated.count('}')
        open_brackets = truncated.count('[')
        close_brackets = truncated.count(']')

        logger.debug(f"🔍 Comptage: {{ {close_braces}/{open_braces}, [ {close_brackets}/{open_brackets}")

        # Vérifier si le JSON se termine mal
        ends_properly = truncated.rstrip().endswith('}') or truncated.rstrip().endswith(']')
        is_incomplete_braces = close_braces < open_braces or close_brackets < open_brackets

        # Vérifier si tronqué au milieu d'une chaîne (nombre impair de guillemets)
        unescaped_quotes = len([c for i, c in enumerate(truncated)
                               if c == '"' and (i == 0 or truncated[i-1] != '\\')])
        is_incomplete_string = (unescaped_quotes % 2) != 0

        if is_incomplete_braces or not ends_properly or is_incomplete_string:
            logger.info(f"🔧 JSON incomplet détecté, tentative de complétion...")

            # Trouver le dernier objet complet
            last_complete = truncated.rfind('},')
            if last_complete == -1:
                last_complete = truncated.rfind('}')

            if last_complete > 0:
                # Couper après le dernier objet complet
                truncated = truncated[:last_complete + 1]

                # Vérifier les guillemets après la coupe
                unescaped_quotes_after_cut = len([c for i, c in enumerate(truncated)
                                                 if c == '"' and (i == 0 or truncated[i-1] != '\\')])
                if (unescaped_quotes_after_cut % 2) != 0:
                    truncated += '"'
                    logger.debug("🔧 Fermeture de chaîne ajoutée")

                # Fermer proprement le JSON
                missing_brackets = open_brackets - truncated.count(']')
                missing_braces = open_braces - truncated.count('}')

                completion = ']' * missing_brackets + '}' * missing_braces
                truncated += completion

                logger.debug(f"🔧 Ajout de fermetures: {completion}")

                try:
                    data = json.loads(truncated)
                    logger.info("✅ JSON tronqué récupéré avec succès (stratégie 6)")
                    return DeepSeekResponseParser._normalize_structure(data)
                except json.JSONDecodeError as e:
                    logger.error(f"❌ Récupération échouée après complétion: {e}")
                    return None

        return None

    @staticmethod
    def coerce_and_enrich_questions(items: List[Dict]) -> List[Dict]:
        """
        Normalise et enrichit les questions parsées.

        Gère:
        - Alias de champs (text → question_text, type → response_type)
        - Conversion champs stringifiés (upload_conditions, tags, evidence_types)
        - Valeurs par défaut
        - ✅ Génération automatique des métadonnées si manquantes

        Args:
            items: Liste de questions brutes

        Returns:
            Liste de questions normalisées
        """
        out: List[Dict] = []
        question_counter = 1  # Compteur pour question_code

        for q in items:
            if not isinstance(q, dict):
                continue

            # Alias éventuels renvoyés par le prompt
            if "text" in q and "question_text" not in q:
                q["question_text"] = q["text"]
            if "type" in q and "response_type" not in q:
                q["response_type"] = q["type"]

            # 🔧 upload_conditions peut arriver en STRING JSON → convertir en OBJET
            uc = q.get("upload_conditions")
            if isinstance(uc, str):
                try:
                    q["upload_conditions"] = json.loads(uc)
                except Exception:
                    logger.warning("[Parser] upload_conditions string non JSON → ignoré")
                    q["upload_conditions"] = None

            # "tags" peut être stringifié comme "[]"
            tags = q.get("tags")
            if isinstance(tags, str):
                try:
                    q["tags"] = json.loads(tags)
                except Exception:
                    q["tags"] = []

            # Evidence types stringifiés
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
            q = DeepSeekResponseParser._auto_generate_metadata(q, question_counter)
            question_counter += 1

            out.append(q)

        return out

    @staticmethod
    def _auto_generate_metadata(q: Dict[str, Any], counter: int) -> Dict[str, Any]:
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
            # Essayer d'extraire depuis requirement_code/official_code
            req_code = q.get("requirement_code") or q.get("official_code")

            if req_code:
                # Ex: "A.5.1.1" → chapter = "A.5"
                chapter = DeepSeekResponseParser._extract_chapter_from_code(req_code)
                q["question_code"] = f"ISO27001-{chapter}-Q{counter}" if chapter else f"CUSTOM-GEN-Q{counter}"
            else:
                q["question_code"] = f"CUSTOM-GEN-Q{counter}"

        # 2. Générer chapter si manquant
        if not q.get("chapter"):
            req_code = q.get("requirement_code") or q.get("official_code")
            if req_code:
                q["chapter"] = DeepSeekResponseParser._extract_chapter_from_code(req_code)

        # 3. Générer evidence_types si vide
        if not q.get("evidence_types") or (isinstance(q.get("evidence_types"), list) and len(q["evidence_types"]) == 0):
            q["evidence_types"] = DeepSeekResponseParser._generate_evidence_types(
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

        Args:
            official_code: Code officiel ISO/NIST

        Returns:
            Chapitre ou None
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
    def _generate_evidence_types(question_type: str, difficulty: str) -> List[str]:
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
