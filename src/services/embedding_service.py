# src/services/embedding_service.py
"""
Service d'embedding complet pour la plateforme d'audit multi-référentiels
Supporte XLM-RoBERTa multilingue (FR/EN) pour :
- Embeddings des exigences de référentiels
- Embeddings des réponses d'auditée 
- Embeddings des évaluations d'auditeurs
- Analyse de similarité et clustering
"""

import logging
from typing import List, Dict, Optional, Tuple, Any
from transformers import AutoTokenizer, AutoModel
import numpy as np
import torch
from sqlalchemy.orm import Session
from sqlalchemy import text
import os
from datetime import datetime


# Import seulement les modèles qui existent actuellement
from ..models.audit import Requirement, Framework
from ..models.audit import ControlPoint, ControlPointEmbedding
from ..database import get_db

logger = logging.getLogger(__name__)


# ✅ CLASSE MANQUANTE À AJOUTER EN DÉBUT DE FICHIER

class EmbeddingService:
    """Service de génération d'embeddings avec modèle local"""

    def __init__(self, model_path: Optional[str] = None):
        if model_path:
            self.model_path = model_path
        else:
            # Utiliser le chemin Hugging Face local
            from ..config import settings
            # Le modèle est dans le cache Hugging Face
            self.model_path = "xlm-roberta-base"
        
            self.tokenizer = None
            self.model = None
            self._load_model()

    def _load_model(self):
        """Charge le modèle XLM-RoBERTa depuis le cache Hugging Face local"""
        import torch
        from transformers import AutoTokenizer, AutoModel
        
        # Configurer HF_HOME pour utiliser le cache local
        from ..config import settings
        os.environ["HF_HOME"] = settings.hf_home

        try:
            logger.info(f"🔄 Chargement du modèle depuis le cache HF : {self.model_path}")
            
            # Charger depuis le cache Hugging Face (utilise automatiquement le cache local)
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.model_path, 
                cache_dir=settings.models_cache_dir,
                local_files_only=False  # Permet d'utiliser le cache local s'il existe
            )
            self.model = AutoModel.from_pretrained(
                self.model_path, 
                cache_dir=settings.models_cache_dir,
                local_files_only=False  # Permet d'utiliser le cache local s'il existe
            )

            # Force CPU si pas de GPU
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            self.model.to(device)
            self.model.eval()

            logger.info(f"✅ Modèle chargé avec succès sur {device} : {self.model_path}")

        except Exception as e:
            logger.error(f"❌ Erreur chargement modèle : {e}")
            raise RuntimeError(f"Échec chargement modèle ({self.model_path}): {e}")

    
    def generate_embedding(self, text: str) -> List[float]:
        """Génère un embedding à partir d'un texte"""
        try:
            if not text or not text.strip():
                raise ValueError("Texte vide")
            
            # Tokenization
            inputs = self.tokenizer(
                text,
                return_tensors="pt",
                truncation=True,
                max_length=512,
                padding=True
            )
            
            # Génération embedding
            with torch.no_grad():
                outputs = self.model(**inputs)
            
            # Mean pooling sur les tokens
            embeddings = outputs.last_hidden_state.mean(dim=1)
            
            # Conversion en liste Python
            embedding_vector = embeddings[0].cpu().numpy().tolist()
            
            return embedding_vector
            
        except Exception as e:
            logger.error(f"Erreur génération embedding : {e}")
            raise
    
    def compute_similarity(self, embedding1: List[float], embedding2: List[float]) -> float:
        """Calcule la similarité cosine entre deux embeddings"""
        try:
            vec1 = np.array(embedding1)
            vec2 = np.array(embedding2)
            
            # Produit scalaire
            dot_product = np.dot(vec1, vec2)
            
            # Normes
            norm1 = np.linalg.norm(vec1)
            norm2 = np.linalg.norm(vec2)
            
            if norm1 == 0 or norm2 == 0:
                return 0.0
            
            # Similarité cosine
            similarity = dot_product / (norm1 * norm2)
            
            return max(0.0, min(1.0, similarity))
            
        except Exception as e:
            logger.error(f"Erreur calcul similarité : {e}")
            return 0.0


# ✅ CLASSE EXISTANTE (ne pas toucher)

class ControlPointEmbeddingService:
    """Service spécialisé pour similarité et embeddings des points de contrôle."""

    def __init__(self, db: Session):
        self.db = db
        self.embedding_service = EmbeddingService()

    # ✅ CORRIGER LA SIGNATURE (chercher la ligne actuelle)
    def search_similar(
        self,
        query_text: str,
        min_similarity: float = 0.7,  # ✅ AJOUTER CE PARAMÈTRE
        limit: int = 10                # ✅ RENOMMER top_k en limit
    ) -> List[Dict[str, Any]]:
        """
        Retourne les PC les plus proches sémantiquement.
        
        Args:
            query_text: Texte de recherche
            min_similarity: Seuil de similarité minimum (0.0 à 1.0)
            limit: Nombre max de résultats
        """
        from sqlalchemy import text as sql_text

        # 1) Tenter le calcul d'embedding de la requête
        try:
            q_vec = self.embedding_service.generate_embedding(query_text or "")
            if not q_vec or (isinstance(q_vec, list) and len(q_vec) == 0):
                raise RuntimeError("Vectorisation de la requête vide.")
        except Exception as e:
            logger.warning(f"⚠️ Erreur génération embedding requête: {e}")
            # Fallback ILIKE
            like = f"%{(query_text or '').strip()}%"
            sql_fb = sql_text("""
                SELECT cp.id AS control_point_id, cp.code, cp.name, cp.description,
                       0.0 AS similarity_score
                FROM control_point cp
                WHERE cp.is_active = true
                  AND (cp.code ILIKE :q OR cp.name ILIKE :q OR cp.description ILIKE :q)
                ORDER BY cp.updated_at DESC NULLS LAST, cp.created_at DESC NULLS LAST
                LIMIT :k
            """)
            rows = self.db.execute(sql_fb, {"q": like, "k": limit}).mappings().all()
            return [dict(r) for r in rows]

        # 2) Recherche pgvector avec filtrage par min_similarity
        try:
            vec_lit = self._to_pgvector_literal(q_vec)

            # ✅ AJOUT : Filtrage par min_similarity
            sql = sql_text("""
                SELECT 
                    cp.id AS control_point_id,
                    cp.code,
                    cp.name,
                    cp.description,
                    (1 - (cpe.embedding_vector <-> CAST(:qv AS vector))) AS similarity_score
                FROM control_point_embeddings cpe
                JOIN control_point cp ON cp.id = cpe.control_point_id
                WHERE cp.is_active = true
                  AND (1 - (cpe.embedding_vector <-> CAST(:qv AS vector))) >= :min_sim
                ORDER BY cpe.embedding_vector <-> CAST(:qv AS vector)
                LIMIT :k
            """)

            rows = self.db.execute(sql, {
                "qv": vec_lit, 
                "min_sim": min_similarity,  # ✅ UTILISÉ
                "k": limit
            }).mappings().all()

            # Si pas de résultat, fallback ILIKE
            if not rows:
                logger.info("⚠️ Aucun PC trouvé avec pgvector, fallback ILIKE")
                like = f"%{(query_text or '').strip()}%"
                sql_fb = sql_text("""
                    SELECT cp.id AS control_point_id, cp.code, cp.name, cp.description,
                           0.0 AS similarity_score
                    FROM control_point cp
                    WHERE cp.is_active = true
                      AND (cp.code ILIKE :q OR cp.name ILIKE :q OR cp.description ILIKE :q)
                    ORDER BY cp.updated_at DESC NULLS LAST, cp.created_at DESC NULLS LAST
                    LIMIT :k
                """)
                rows = self.db.execute(sql_fb, {"q": like, "k": limit}).mappings().all()

            # Normalisation
            out = []
            for r in rows:
                out.append({
                    "id": str(r["control_point_id"]),  # ✅ Clé 'id' pour cohérence
                    "code": r.get("code"),
                    "name": r.get("name"),
                    "description": r.get("description"),
                    "similarity_score": round(float(r.get("similarity_score") or 0.0), 4),
                })
            return out

        except Exception as e:
            logger.error(f"❌ Erreur recherche pgvector: {e}")
            # Rollback transaction
            try:
                self.db.rollback()
            except Exception:
                pass

            # Fallback ILIKE après erreur
            like = f"%{(query_text or '').strip()}%"
            sql_fb = sql_text("""
                SELECT cp.id AS control_point_id, cp.code, cp.name, cp.description,
                       0.0 AS similarity_score
                FROM control_point cp
                WHERE cp.is_active = true
                  AND (cp.code ILIKE :q OR cp.name ILIKE :q OR cp.description ILIKE :q)
                ORDER BY cp.updated_at DESC NULLS LAST, cp.created_at DESC NULLS LAST
                LIMIT :k
            """)
            rows = self.db.execute(sql_fb, {"q": like, "k": limit}).mappings().all()
            return [dict(r) for r in rows]

    
    def generate_embedding(self, text: str, language: str = "auto") -> List[float]:
        """Générer un embedding pour un texte donné (multilingue)"""
        
        if self.model_type == "xlm-roberta":
            return self._generate_xlm_roberta_embedding(text)
        elif self.model_type == "openai":
            return self._generate_openai_embedding(text)
        else:
            raise ValueError(f"Model type {self.model_type} not supported")
    
    def _generate_xlm_roberta_embedding(self, text: str) -> List[float]:
        """Générer embedding avec XLM-RoBERTa multilingue"""
        try:
            import torch
            
            processed_text = self._preprocess_audit_text(text)
            
            inputs = self.tokenizer(
                processed_text, 
                return_tensors="pt", 
                truncation=True, 
                padding=True, 
                max_length=512
            )
            
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
            
            with torch.no_grad():
                outputs = self.model(**inputs)
                
                embeddings = outputs.last_hidden_state
                attention_mask = inputs['attention_mask']
                
                masked_embeddings = embeddings * attention_mask.unsqueeze(-1)
                
                summed = torch.sum(masked_embeddings, dim=1)
                counts = torch.clamp(attention_mask.sum(dim=1, keepdim=True), min=1e-9)
                mean_embeddings = summed / counts
                
                normalized = torch.nn.functional.normalize(mean_embeddings, p=2, dim=1)
                
                return normalized.cpu().numpy().tolist()[0]
                
        except Exception as e:
            logger.error(f"XLM-RoBERTa embedding error: {str(e)}")
            return self._generate_fallback_embedding(text)
    
    def _preprocess_audit_text(self, text: str) -> str:
        """Preprocessing spécialisé pour les textes d'audit multilingues"""
        processed = text.strip()
        
        replacements = {
            " ssi ": " système de sécurité de l'information ",
            " rgpd ": " règlement général sur la protection des données ",
            " cnil ": " commission nationale informatique et libertés ",
            " anssi ": " agence nationale sécurité systèmes information ",
            " dpo ": " délégué à la protection des données ",
            " ciso ": " responsable de la sécurité des systèmes d'information ",
            " isms ": " information security management system ",
            " gdpr ": " general data protection regulation ",
            " soc ": " security operations center ",
            " iam ": " identity and access management ",
            " pki ": " public key infrastructure ",
            " siem ": " security information event management ",
            " mfa ": " multi-factor authentication ",
            " rbac ": " role-based access control ",
        }
        
        text_lower = processed.lower()
        for abbr, full in replacements.items():
            text_lower = text_lower.replace(abbr, full)
        
        if text_lower != processed.lower():
            processed = text_lower
        
        return processed
    
    def _detect_language(self, text: str) -> str:
        """Détecter la langue du texte (FR/EN)"""
        french_keywords = [
            "sécurité", "conformité", "exigence", "politique", "procédure",
            "risque", "contrôle", "audit", "réglementation", "protection",
            "données", "information", "système", "mesure", "gestion"
        ]
        
        english_keywords = [
            "security", "compliance", "requirement", "policy", "procedure",
            "risk", "control", "audit", "regulation", "protection",
            "data", "information", "system", "measure", "management"
        ]
        
        text_lower = text.lower()
        
        french_score = sum(1 for keyword in french_keywords if keyword in text_lower)
        english_score = sum(1 for keyword in english_keywords if keyword in text_lower)
        
        return "fr" if french_score > english_score else "en"
    
    def _generate_openai_embedding(self, text: str) -> List[float]:
        """Générer embedding avec OpenAI"""
        try:
            import openai
            
            response = openai.Embedding.create(
                model="text-embedding-ada-002",
                input=text
            )
            return response['data'][0]['embedding']
        except Exception as e:
            logger.error(f"OpenAI embedding error: {str(e)}")
            return self._generate_fallback_embedding(text)
    
    def _generate_fallback_embedding(self, text: str) -> List[float]:
        """Embedding de secours basique (hash + padding)"""
        import hashlib
        
        hash_obj = hashlib.md5(text.encode())
        hash_hex = hash_obj.hexdigest()
        
        embedding = []
        for i in range(0, len(hash_hex), 2):
            val = int(hash_hex[i:i+2], 16) / 255.0
            embedding.append(val)
        
        while len(embedding) < 768:
            embedding.append(0.0)
        
        return embedding[:768]
    
    def compute_similarity(self, embedding1: List[float], embedding2: List[float]) -> float:
        """Calculer la similarité cosinus entre deux embeddings"""
        try:
            vec1 = np.array(embedding1)
            vec2 = np.array(embedding2)
            
            dot_product = np.dot(vec1, vec2)
            norm1 = np.linalg.norm(vec1)
            norm2 = np.linalg.norm(vec2)
            
            if norm1 == 0 or norm2 == 0:
                return 0.0
            
            similarity = dot_product / (norm1 * norm2)
            return float(similarity)
        except Exception as e:
            logger.error(f"Similarity computation error: {str(e)}")
            return 0.0
    
    def batch_generate_embeddings(self, texts: List[str], batch_size: int = 8) -> List[List[float]]:
        """Générer des embeddings par batch pour de meilleures performances"""
        embeddings = []
        
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            batch_embeddings = []
            
            for text in batch:
                embedding = self.generate_embedding(text)
                batch_embeddings.append(embedding)
            
            embeddings.extend(batch_embeddings)
            
            if len(embeddings) % 50 == 0:
                logger.info(f"Generated embeddings: {len(embeddings)}/{len(texts)}")
        
        return embeddings

# --- dans src/services/embedding_service.py ---

class RequirementEmbeddingService:
    """Service spécialisé pour les embeddings des exigences de référentiels"""
    
    def __init__(self, db: Session):
        self.db = db
        self.embedding_service = EmbeddingService()
    
    def _fetch_domain_path(self, requirement_id: str) -> str:
        """Récupérer le chemin hiérarchique complet du domaine"""
        sql = text("""
            WITH RECURSIVE path AS (
              SELECT d.id, d.parent_id, d.level,
                     COALESCE((
                         SELECT dt.title
                         FROM domain_title dt
                         WHERE dt.domain_id = d.id AND dt.is_primary = true AND dt.language = 'fr'
                         LIMIT 1
                     ), d.code) AS label
              FROM domain d
              JOIN requirement r ON r.domain_id = d.id
              WHERE r.id = :rid
              UNION ALL
              SELECT d2.id, d2.parent_id, d2.level,
                     COALESCE((
                         SELECT dt2.title
                         FROM domain_title dt2
                         WHERE dt2.domain_id = d2.id AND dt2.is_primary = true AND dt2.language = 'fr'
                         LIMIT 1
                     ), d2.code) AS label
              FROM domain d2
              JOIN path p ON p.parent_id = d2.id
            )
            SELECT string_agg(label, ' > ' ORDER BY level) AS domain_path
            FROM path
        """)
        row = self.db.execute(sql, {"rid": requirement_id}).mappings().first()
        return row["domain_path"] if row else ""

    def _create_embedding_text(self, req, domain_path=None) -> str:
        """
        Construit un texte riche et stable pour l'embedding.
        - domain_path est optionnel (chaîne style "Parent > Enfant"), sinon on retombe sur chapter_path si dispo.
        - Tolérant aux champs manquants / None.
        """
        parts = []

        # Identifiants / métadonnées utiles
        off = getattr(req, "official_code", None)
        if off:
            parts.append(f"[{off}]")

        if domain_path:
            parts.append(f"Chemin: {domain_path}")
        else:
            chap = getattr(req, "chapter_path", None)
            if chap:
                parts.append(f"Chapitre: {chap}")

        # Titre + texte d'exigence
        title = getattr(req, "title", None)
        if title:
            parts.append(str(title))

        body = getattr(req, "requirement_text", None)
        if body:
            parts.append(str(body))

        # Libellés simples (colonnes texte, pas relations)
        dom = getattr(req, "domain", None)
        if dom:
            parts.append(f"Domaine: {dom}")

        sub = getattr(req, "subdomain", None)
        if sub:
            parts.append(f"Sous-domaine: {sub}")

        # Tags (liste/ARRAY) -> chaîne
        tags = getattr(req, "tags", None)
        if tags:
            try:
                tag_str = ", ".join([t for t in tags if t]) if isinstance(tags, (list, tuple)) else str(tags)
                if tag_str:
                    parts.append(f"Tags: {tag_str}")
            except Exception:
                pass

        risk = getattr(req, "risk_level", None)
        if risk:
            parts.append(f"Niveau de risque: {risk}")

        obl = getattr(req, "compliance_obligation", None)
        if obl:
            parts.append(f"Obligation: {obl}")

        return "\n".join(parts)

    
    def generate_requirement_embeddings(self, framework_id: str) -> dict:
        """
        Génère les embeddings pour toutes les exigences d'un framework.
        - Ne charge que les colonnes existantes en BDD (tolérant aux champs legacy)
        - Pas de SQL récursif pour le chemin de domaine (on s'en passe ici)
        - SAVEPOINT par exigence pour éviter d'aborter toute la transaction
        - Commit par batch pour fiabiliser
        """
        from sqlalchemy.orm import load_only

        BATCH_SIZE = 50  # commit toutes les 50 insertions
        embeddings_generated = 0
        errors = 0

        try:
            # Colonnes "sûres" selon le nouveau modèle
            base_cols = [
                Requirement.id,
                Requirement.framework_id,
                Requirement.domain_id,
                Requirement.official_code,
                Requirement.title,
                Requirement.requirement_text,
                Requirement.chapter_path,
                Requirement.tags,
                Requirement.risk_level,
                Requirement.compliance_obligation,
                Requirement.created_at,
            ]

            # Colonnes legacy éventuelles (si ton modèle les expose encore)
            opt_cols = []
            for name in ("domain", "subdomain"):
                if hasattr(Requirement, name):
                    opt_cols.append(getattr(Requirement, name))

            # 1) Charger les requirements sans colonnes “fantômes”
            requirements = (
                self.db.query(Requirement)
                .options(load_only(*base_cols, *opt_cols))
                .filter(Requirement.framework_id == framework_id)
                .all()
            )

            if not requirements:
                logger.info("Aucune exigence trouvée pour ce référentiel")
                return {
                    "status": "ok",
                    "message": "Aucune exigence trouvée pour ce référentiel",
                    "total_requirements": 0,
                    "embeddings_generated": 0,
                    "errors": 0,
                }

            logger.info(f"🚀 Génération embeddings: {len(requirements)} exigences à traiter")

            for i, req in enumerate(requirements, start=1):
                tx = self.db.begin_nested()  # SAVEPOINT (rollback local si échec)
                try:
                    # 2) Construire un texte sans dépendre d'un chemin de domaine calculé
                    text_for_embedding = self._create_embedding_text(req, domain_path=None)

                    # 3) Générer l'embedding (utilise la config actuelle du service)
                    vec = self.embedding_service.generate_embedding(text_for_embedding)

                    # 4) Stocker (UPSERT) l'embedding
                    self._store_requirement_embedding(str(req.id), vec, text_for_embedding)

                    tx.commit()
                    embeddings_generated += 1

                    if (i % 10) == 0:
                        logger.info(f"… {i}/{len(requirements)} traitées ({embeddings_generated} embeddings ok)")

                    if (embeddings_generated % BATCH_SIZE) == 0:
                        # sécuriser régulièrement : évite un gros rollback global
                        self.db.commit()

                except Exception as e:
                    tx.rollback()
                    errors += 1
                    logger.error(f"Erreur embedding pour requirement {getattr(req, 'id', 'N/A')}: {e}")

            # 5) Commit final
            self.db.commit()

            logger.info(
                f"✅ Embeddings terminés: ok={embeddings_generated}, erreurs={errors}, "
                f"total={len(requirements)}"
            )

            return {
                "status": "completed",
                "total_requirements": len(requirements),
                "embeddings_generated": embeddings_generated,
                "errors": errors,
                "model_used": getattr(self.embedding_service, "model_name", "default"),
            }

        except Exception as e:
            self.db.rollback()
            logger.error(f"❌ Erreur globale génération embeddings: {e}", exc_info=True)
            return {
                "status": "failed",
                "error": str(e),
                "embeddings_generated": embeddings_generated,
                "errors": errors,
            }


    
    def _store_requirement_embedding(self, requirement_id: str, embedding: list[float], source_text: str):
        """
        UPSERT robuste dans requirement_embeddings :
        - Détecte les colonnes présentes et s'y adapte (embedding_vector / embedding / vector, source_text|text|content|raw_text, model, created_at, updated_at).
        - Utilise des named binds SQLAlchemy (:rid, :vec, :txt, :model).
        - Convertit l'embedding en liste de float.
        - Conflit géré sur requirement_id (doit être PK ou unique).
        """
        from sqlalchemy import text

        # 1) Découverte du schéma réel
        cols_rows = self.db.execute(
            text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                AND table_name = 'requirement_embeddings'
            """)
        ).fetchall()
        cols = {r[0] for r in cols_rows}

        # Colonnes obligatoires
        if "requirement_id" not in cols:
            raise RuntimeError("La table requirement_embeddings doit au minimum contenir la colonne 'requirement_id'.")

        # 2) Choix des colonnes dynamiques
        # embedding
        emb_col = next((c for c in ("embedding_vector", "embedding", "vector") if c in cols), None)
        if not emb_col:
            raise RuntimeError(
                "Aucune colonne d'embedding trouvée dans requirement_embeddings "
                "(cherché: embedding_vector, embedding, vector)."
            )
        # texte source
        source_col = next((c for c in ("source_text", "text", "content", "raw_text") if c in cols), None)
        # modèle (optionnel)
        model_col = "model" if "model" in cols else None
        # timestamps (optionnels)
        created_at_col = "created_at" if "created_at" in cols else None
        updated_at_col = "updated_at" if "updated_at" in cols else None

        # 3) Construction dynamique de l'UPSERT
        insert_cols = ["requirement_id", emb_col]
        insert_vals = [":rid", ":vec"]
        update_sets = [f'{emb_col} = EXCLUDED.{emb_col}']

        # source text
        if source_col:
            insert_cols.append(source_col)
            insert_vals.append(":txt")
            update_sets.append(f'{source_col} = EXCLUDED.{source_col}')

        # model
        if model_col:
            insert_cols.append(model_col)
            insert_vals.append(":model")
            update_sets.append(f'{model_col} = EXCLUDED.{model_col}')

        # timestamps
        if created_at_col:
            insert_cols.append(created_at_col)
            insert_vals.append("NOW()")
        if updated_at_col:
            insert_cols.append(updated_at_col)
            insert_vals.append("NOW()")
            update_sets.append(f'{updated_at_col} = NOW()')

        # Assembler le SQL
        insert_cols_sql = ", ".join(insert_cols)
        insert_vals_sql = ", ".join(insert_vals)
        update_sets_sql = ", ".join(update_sets)

        sql = text(f"""
            INSERT INTO requirement_embeddings
                ({insert_cols_sql})
            VALUES
                ({insert_vals_sql})
            ON CONFLICT (requirement_id) DO UPDATE SET
                {update_sets_sql};
        """)

        # 4) Normaliser le vecteur (liste de float)
        vec = [float(x) for x in (embedding or [])]

        # 5) Exécuter
        params = {"rid": requirement_id, "vec": vec}
        if source_col:
            params["txt"] = source_text
        if model_col:
            params["model"] = "xlm-roberta-base"

        try:
            self.db.execute(sql, params)
        except Exception as e:
            # Log explicite puis relance (pour rollback via SAVEPOINT dans l'appelant)
            logger.error(f"Erreur stockage embedding {requirement_id}: {e}")
            raise

class ControlPointEmbeddingService:
    """Service spécialisé pour similarité et embeddings des points de contrôle."""

    def __init__(self, db: Session):
        self.db = db
        self.embedding_service = EmbeddingService()

    # --------- Construction du texte d'embedding PC ---------

    def generate_embedding_for_control_point(self, control_point_id: str):
        """
        Wrapper: génère et stocke l'embedding pour un seul PC, puis retourne un dict.
        """
        res = self.generate_and_store_embedding(control_point_id)
        if not res:
            raise ValueError(f"Point de contrôle introuvable: {control_point_id}")
        return res

    def _create_embedding_text(self, cp) -> str:
        """
        Construit un texte riche et stable pour un point de contrôle.
        Tolérant aux champs manquants.
        """
        parts = []
        code = getattr(cp, "code", None)
        name = getattr(cp, "name", None)
        desc = getattr(cp, "description", None)
        guide = getattr(cp, "implementation_guidance", None)
        cat = getattr(cp, "category", None)
        sub = getattr(cp, "subcategory", None)
        fam = getattr(cp, "control_family", None)
        risk = getattr(cp, "risk_domains", None)
        level = getattr(cp, "implementation_level", None)

        if code:
            parts.append(f"[{code}]")
        if name:
            parts.append(str(name))
        if desc:
            parts.append(str(desc))
        if guide:
            parts.append(f"Guidance: {guide}")
        if cat:
            parts.append(f"Catégorie: {cat}")
        if sub:
            parts.append(f"Sous-catégorie: {sub}")
        if fam:
            parts.append(f"Famille: {fam}")
        if risk:
            parts.append(f"Risques: {risk}")
        if level:
            parts.append(f"Niveau: {level}")

        return " | ".join(parts) if parts else ""

    # --------- Format pgvector ---------
    def _to_pgvector_literal(self, vec: list[float]) -> str:
        """Convertit une liste de floats en littéral pgvector '[v1,v2,...]'."""
        if not vec:
            return "[]"
        return "[" + ",".join(f"{float(v):.6f}" for v in vec) + "]"

    # --------- Recherche sémantique (pgvector + fallback ILIKE) ---------
    def search_similar(
    self,
    query_text: str,
    min_similarity: float = 0.7,
    limit: int = 10
) -> List[Dict[str, Any]]:
        """
        Retourne les PC les plus proches sémantiquement (basé sur pgvector).
        Requiert une table control_point_embeddings(control_point_id uuid, embedding_vector vector)
        et control_point(id, code, name, description, is_active).
        """
        from sqlalchemy import text as sql_text

        # 1) Tenter le calcul d’embedding de la requête
        try:
            q_vec = self.embedding_service.generate_embedding(query_text or "")
            if not q_vec or (isinstance(q_vec, list) and len(q_vec) == 0):
                raise RuntimeError("Vectorisation de la requête vide.")
        except Exception as e:
            # Fallback direct ILIKE si l’embedding échoue
            like = f"%{(query_text or '').strip()}%"
            sql_fb = sql_text("""
                SELECT cp.id AS control_point_id, cp.code, cp.name, cp.description,
                       0.0 AS similarity_score
                FROM control_point cp
                WHERE cp.is_active = true
                  AND (cp.code ILIKE :q OR cp.name ILIKE :q OR cp.description ILIKE :q)
                ORDER BY cp.updated_at DESC NULLS LAST, cp.created_at DESC NULLS LAST
                LIMIT :k
            """)
            rows = self.db.execute(sql, {"qv": vec_lit, "k": limit}).mappings().all()
            return [dict(r) for r in rows]

        # 2) Recherche pgvector
        try:
            vec_lit = self._to_pgvector_literal(q_vec)

            # Opérateur L2 '<->' (compatible partout). Si pgvector>=0.5, on peut utiliser '<=>'
            sql = sql_text("""
                SELECT 
                    cp.id AS control_point_id,
                    cp.code,
                    cp.name,
                    cp.description,
                    (1 - (cpe.embedding_vector <-> :qv::vector)) AS similarity_score
                FROM control_point_embeddings cpe
                JOIN control_point cp ON cp.id = cpe.control_point_id
                WHERE cp.is_active = true
                ORDER BY cpe.embedding_vector <-> :qv::vector
                LIMIT :k
            """)

            rows = self.db.execute(sql, {"qv": vec_lit, "k": limit}).mappings().all()

            # Si pas de résultat (pas encore d’embeddings PC ?), fallback ILIKE
            if not rows:
                like = f"%{(query_text or '').strip()}%"
                sql_fb = sql_text("""
                    SELECT cp.id AS control_point_id, cp.code, cp.name, cp.description,
                           0.0 AS similarity_score
                    FROM control_point cp
                    WHERE cp.is_active = true
                      AND (cp.code ILIKE :q OR cp.name ILIKE :q OR cp.description ILIKE :q)
                    ORDER BY cp.updated_at DESC NULLS LAST, cp.created_at DESC NULLS LAST
                    LIMIT :k
                """)
                rows = self.db.execute(sql_fb, {"q": like, "k": limit}).mappings().all()

            # Normalisation
            out = []
            for r in rows:
                out.append({
                    "control_point_id": str(r["control_point_id"]),
                    "code": r.get("code"),
                    "name": r.get("name"),
                    "description": r.get("description"),
                    "similarity_score": float(r.get("similarity_score") or 0.0),
                })
            return out

        except Exception:
            # Si la requête pgvector a levé une DatabaseError, la transaction est 'aborted'
            try:
                self.db.rollback()
            except Exception:
                pass

            # Fallback ILIKE après rollback
            like = f"%{(query_text or '').strip()}%"
            sql_fb = sql_text("""
                SELECT cp.id AS control_point_id, cp.code, cp.name, cp.description,
                       0.0 AS similarity_score
                FROM control_point cp
                WHERE cp.is_active = true
                  AND (cp.code ILIKE :q OR cp.name ILIKE :q OR cp.description ILIKE :q)
                ORDER BY cp.updated_at DESC NULLS LAST, cp.created_at DESC NULLS LAST
                LIMIT :k
            """)
            rows = self.db.execute(sql_fb, {"q": like, "k": limit}).mappings().all()
            return [dict(r) for r in rows]

    # --------- Génération + stockage d’un embedding PC ---------
    def generate_and_store_embedding(self, cp_or_id: Any) -> Optional[Dict[str, Any]]:
        """
        Génère l'embedding d'un PC et upsert dans control_point_embeddings.
        Accepte soit un objet ControlPoint, soit un id (str/UUID).
        """
        from ..models.audit import ControlPoint
        from sqlalchemy import text as sql_text

        # 1) Normaliser l'entrée -> (objet cp, id str)
        if isinstance(cp_or_id, ControlPoint):
            cp_obj = cp_or_id
            cp_id_str = str(cp_obj.id)
        else:
            cp_id_str = str(cp_or_id)
            cp_obj = self.db.query(ControlPoint).filter_by(id=cp_id_str).first()
            if not cp_obj:
                return None

        # 2) Texte source pour l'embedding
        src_text = self._create_embedding_text(cp_obj)

        # 3) Générer vecteur
        vector = self.embedding_service.generate_embedding(src_text)
        
        if not vector or len(vector) == 0:
            raise ValueError(f"Embedding vide généré pour PC {cp_id_str}")
        
        # 4) Convertir en format PostgreSQL vector: [v1,v2,v3,...]
        vec_lit = self._to_pgvector_literal(vector)

        # 5) ✅ CORRECTION: Utiliser uniquement le style :param de SQLAlchemy text

        upsert = sql_text("""
            INSERT INTO control_point_embeddings
                (id, control_point_id, embedding_vector, source_text, created_at, updated_at)
            VALUES
                (gen_random_uuid(), :cp_id, CAST(:vec AS vector), :src, NOW(), NOW())
            ON CONFLICT (control_point_id) DO UPDATE
            SET embedding_vector = EXCLUDED.embedding_vector,
                source_text      = EXCLUDED.source_text,
                updated_at       = NOW()
        """)

        
        try:
            # ✅ Exécuter avec le bon format de paramètres
            self.db.execute(
                upsert,
                {
                    "cp_id": cp_id_str,
                    "vec": vec_lit,             # format "[v1,v2,...]"
                    "src": src_text[:1000],
                }
            )
            self.db.commit()
            
            logger.info(f"✅ Embedding créé pour PC {cp_obj.code}")
            return {"control_point_id": cp_id_str, "status": "ok"}
            
        except Exception as e:
            logger.error(f"❌ Erreur stockage embedding pour PC {cp_obj.code}: {e}")
            raise

    # --------- Batch embeddings (global ou par framework) ---------
    def generate_all_embeddings(
        self,
        framework_id: Optional[str] = None,
        force_regenerate: bool = False
    ) -> Dict[str, Any]:
        """
        Génére les embeddings pour:
          - tous les PC actifs (par défaut), ou
          - uniquement les PC liés à un framework (si framework_id).
        Si force_regenerate=False, on skippe les PC déjà vectorisés.
        """
        from ..models.audit import ControlPoint, RequirementControlPoint, Requirement
        from sqlalchemy import text as sql_text

        # Sélection des PC selon le scope
        if framework_id:
            q = (
                self.db.query(ControlPoint)
                .join(RequirementControlPoint, RequirementControlPoint.control_point_id == ControlPoint.id)
                .join(Requirement, Requirement.id == RequirementControlPoint.requirement_id)
                .filter(Requirement.framework_id == framework_id, ControlPoint.is_active == True)
                .distinct()
            )
            scope_label = f"framework={framework_id}"
        else:
            q = self.db.query(ControlPoint).filter_by(is_active=True)
            scope_label = "global"

        cps = q.all()
        if not cps:
            return {
                "status": "ok",
                "scope": scope_label,
                "total_control_points": 0,
                "processed": 0,
                "skipped": 0,
                "errors": 0,
            }

        processed = 0
        skipped = 0
        errors = 0

        for cp in cps:
            try:
                if not force_regenerate:
                    # vérifier existence embedding
                    exists = self.db.execute(
                        sql_text("SELECT 1 FROM control_point_embeddings WHERE control_point_id = :id LIMIT 1"),
                        {"id": str(cp.id)}
                    ).first()
                    if exists:
                        skipped += 1
                        continue

                self.generate_and_store_embedding(cp)  # accepte objet ou id
                processed += 1

                if processed % 10 == 0:
                    try:
                        self.db.commit()
                    except Exception:
                        self.db.rollback()

            except Exception as e:
                errors += 1
                logger.warning(f"Erreur embedding pour PC {cp.id}: {e}")
                try:
                    self.db.rollback()
                except Exception:
                    pass

        try:
            self.db.commit()
        except Exception:
            self.db.rollback()

        return {
            "status": "completed",
            "scope": scope_label,
            "total_control_points": len(cps),
            "processed": processed,
            "skipped": skipped,
            "errors": errors,
        }


class AuditResponseEmbeddingService:
    """Service spécialisé pour les embeddings des réponses d'audit"""
    
    def __init__(self, db: Session):
        self.db = db
        self.embedding_service = EmbeddingService()
    
    def generate_audit_embeddings(self, audit_id: str) -> Dict:
        """Générer les embeddings pour toutes les réponses d'un audit"""
        
        logger.warning("AuditResponseEmbeddingService: Models not yet implemented")
        return {
            "audit_id": audit_id,
            "status": "pending",
            "message": "Question and QuestionAnswer models not yet implemented"
        }
    
    def _store_response_embedding(self, answer_id: str, embedding: List[float], 
                                source_text: str, question_id: str, audit_id: str):
        """Stocker l'embedding d'une réponse - Syntaxe corrigée"""
        
        try:
            embedding_str = "[" + ",".join(map(str, embedding)) + "]"
            
            sql = text("""
                INSERT INTO response_embeddings 
                (answer_id, question_id, audit_id, embedding_vector, source_text, created_at)
                VALUES (:answer_id, :question_id, :audit_id, :embedding_vector::vector, :source_text, NOW())
                ON CONFLICT (answer_id) 
                DO UPDATE SET 
                    embedding_vector = EXCLUDED.embedding_vector,
                    source_text = EXCLUDED.source_text,
                    updated_at = NOW()
            """)
            
            self.db.execute(sql, {
                "answer_id": answer_id,
                "question_id": question_id,
                "audit_id": audit_id,
                "embedding_vector": embedding_str,
                "source_text": source_text
            })
            
        except Exception as e:
            logger.error(f"Error storing response embedding for {answer_id}: {str(e)}")
            raise
    
    def _store_assessment_embedding(self, control_id: str, embedding: List[float], 
                                  source_text: str, audit_id: str):
        """Stocker l'embedding d'une évaluation - Syntaxe corrigée"""
        
        try:
            embedding_str = "[" + ",".join(map(str, embedding)) + "]"
            
            sql = text("""
                INSERT INTO assessment_embeddings 
                (control_id, audit_id, embedding_vector, source_text, created_at)
                VALUES (:control_id, :audit_id, :embedding_vector::vector, :source_text, NOW())
                ON CONFLICT (control_id) 
                DO UPDATE SET 
                    embedding_vector = EXCLUDED.embedding_vector,
                    source_text = EXCLUDED.source_text,
                    updated_at = NOW()
            """)
            
            self.db.execute(sql, {
                "control_id": control_id,
                "audit_id": audit_id,
                "embedding_vector": embedding_str,
                "source_text": source_text
            })
            
        except Exception as e:
            logger.error(f"Error storing assessment embedding for {control_id}: {str(e)}")
            raise

# Fonctions helper
def generate_embeddings_for_framework(framework_id: str) -> Dict:
    """Générer les embeddings d'un framework"""
    
    db = next(get_db())
    try:
        service = RequirementEmbeddingService(db)
        return service.generate_requirement_embeddings(framework_id)
    finally:
        db.close()

def generate_audit_response_embeddings(audit_id: str) -> Dict:
    """Générer les embeddings d'un audit"""
    
    db = next(get_db())
    try:
        service = AuditResponseEmbeddingService(db)
        return service.generate_audit_embeddings(audit_id)
    finally:
        db.close()

def generate_control_point_embeddings() -> Dict:
    """Générer les embeddings pour tous les points de contrôle"""
    from ..models.audit import ControlPoint

    db = next(get_db())
    try:
        service = ControlPointEmbeddingService(db)
        return service.generate_all_embeddings()
    finally:
        db.close()


def test_embedding_service():
    """Fonction de test pour valider le service d'embedding"""
    
    service = EmbeddingService()
    
    texts = [
        "Politique de sécurité de l'information",
        "Information security policy",
        "Gestion des accès et des identités",
        "Identity and access management"
    ]
    
    print("Test des embeddings multilingues:")
    for text in texts:
        embedding = service.generate_embedding(text)
        lang = service._detect_language(text)
        print(f"Text: {text}")
        print(f"Detected language: {lang}")
        print(f"Embedding dimension: {len(embedding)}")
        print(f"First 5 values: {embedding[:5]}")
        print("-" * 50)
    
    fr_embedding = service.generate_embedding("Politique de sécurité")
    en_embedding = service.generate_embedding("Security policy") 
    similarity = service.compute_similarity(fr_embedding, en_embedding)
    
    print(f"Cross-lingual similarity (FR-EN): {similarity:.3f}")

