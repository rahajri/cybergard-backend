# backend/src/services/domain_import_service.py
"""
Service d'import Excel avec hiérarchie domain (0-4 niveaux)
Gère la création récursive des domaines et l'import des exigences
"""

import re
import uuid
import json
import logging
from typing import Dict, List, Optional, Tuple
import unicodedata
import math
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import text
from psycopg2.extras import Json

# Si ces imports existent chez toi, on les laisse pour ne pas casser d'autres parties
try:
    from ..models.audit import Framework, Requirement  # noqa: F401
except Exception:
    pass

logger = logging.getLogger(__name__)

def _s(v): 
    return "" if v is None else str(v)

def _cell(v) -> str:
    """Nettoie une cellule Excel en chaîne 'propre' (évite 'nan')."""
    if v is None:
        return ""
    # float('nan') -> True ; str 'nan'/'NaN' -> traiter aussi
    if isinstance(v, float) and math.isnan(v):
        return ""
    s = str(v).strip()
    if s.lower() in {"nan", "none", "nul", "null"}:
        return ""
    return s

def _slugify(text_: str) -> str:
    if not text_:
        return ""
    t = unicodedata.normalize("NFD", text_).encode("ascii", "ignore").decode("ascii")
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()
    return t[:120]  # un peu plus long pour encodage du chemin



def _normalize_risk(v: str) -> str:
    v = (v or "").strip().lower()
    return {
        "faible": "low", "bas": "low", "low": "low",
        "moyen": "medium", "moyenne": "medium", "medium": "medium",
        "eleve": "high", "élevé": "high", "haut": "high", "high": "high",
    }.get(v, "medium")

def _normalize_obligation(v: str) -> str:
    v = (v or "").strip().lower()
    return {
        "obligatoire": "mandatory", "mandatory": "mandatory",
        "recommande": "recommended", "recommandé": "recommended", "recommended": "recommended",
        "optionnel": "optional", "facultatif": "optional", "optional": "optional",
    }.get(v, "mandatory")

class DomainImportService:
    def __init__(self, db):
        self.db = db
        # ✅ Stats utilisées par ta popup
        self.stats = {
            "framework_id": None,
            "framework_name": None,
            "domains_created": 0,
            "requirements_created": 0,
            "warnings": [],   # liste -> len(...) dans la popup
            "errors": []      # liste -> len(...) dans la popup
        }

    # ───────────────────────────── Utils ───────────────────────────── #

    @staticmethod
    def _slugify(value: str) -> str:
        """
        Convertit un libellé en code "slug".
        Ex: "Mesures organisationnelles" → "mesures_organisationnelles"
        """
        if not value:
            return "non_classe"
        v = str(value).strip().lower()
        # remplacements d'accents
        v = re.sub(r"[àâäáã]", "a", v)
        v = re.sub(r"[éèêëē]", "e", v)
        v = re.sub(r"[îïíī]", "i", v)
        v = re.sub(r"[ôöóõō]", "o", v)
        v = re.sub(r"[ùûüúū]", "u", v)
        v = re.sub(r"[ç]", "c", v)
        v = re.sub(r"[ñ]", "n", v)
        # non alphanum -> underscore
        v = re.sub(r"[^a-z0-9]+", "_", v)
        v = v.strip("_")
        return v or "non_classe"

    def _get_or_create_domain(
        self,
        framework_id: uuid.UUID,
        title: str,
        level: int,
        parent_id: Optional[uuid.UUID],
        language: str = "fr",
    ) -> uuid.UUID:
        """
        Créer ou récupérer un domain.
        Contrainte logique : (framework_id, code) unique.
        """
        code = self._slugify(title)
        cache_key = f"{framework_id}_{code}"
        if cache_key in self.domain_cache:
            return self.domain_cache[cache_key]

        # Existe déjà ?
        row = self.db.execute(
            text(
                """
                SELECT id
                FROM domain
                WHERE framework_id = :framework_id AND code = :code
                LIMIT 1
            """
            ),
            {"framework_id": str(framework_id), "code": code},
        ).fetchone()

        if row:
            domain_id = uuid.UUID(row[0]) if not isinstance(row[0], uuid.UUID) else row[0]
            self.domain_cache[cache_key] = domain_id
            return domain_id

        # Créer domain
        domain_id = uuid.uuid4()
        self.db.execute(
            text(
                """
                INSERT INTO domain (
                    id, framework_id, parent_id, code, level,
                    sort_index, is_active, created_at
                )
                VALUES (
                    :id, :framework_id, :parent_id, :code, :level,
                    0, true, NOW()
                )
            """
            ),
            {
                "id": str(domain_id),
                "framework_id": str(framework_id),
                "parent_id": str(parent_id) if parent_id else None,
                "code": code,
                "level": int(level),
            },
        )

        # Titre (si la table domain_title existe chez toi)
        try:
            self.db.execute(
                text(
                    """
                    INSERT INTO domain_title (
                        id, domain_id, language, title, is_primary, created_at
                    )
                    VALUES (
                        :id, :domain_id, :language, :title, true, NOW()
                    )
                """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "domain_id": str(domain_id),
                    "language": language,
                    "title": title,
                },
            )
        except Exception as e:
            # On ne bloque pas l'import si domain_title n'existe pas
            logger.debug(f"domain_title non créé (optionnel) : {e}")

        self.db.flush()
        self.domain_cache[cache_key] = domain_id
        self.stats["domains_created"] += 1
        logger.info(f"✅ Domain créé : {title} (level {level}, code: {code})")
        return domain_id

    def _process_hierarchy(
        self, row: pd.Series, framework_id: uuid.UUID, language: str = "fr"
    ) -> Tuple[Optional[uuid.UUID], List[str]]:
        """
        À partir d'une ligne Excel, crée/récupère la hiérarchie domaines et
        retourne le domain_id final (dernier niveau).
        """
        warnings: List[str] = []
        cols = ["domaine", "domaine_rang1", "domaine_rang2", "domaine_rang3", "domaine_rang4"]
        values: List[str] = []

        for c in cols:
            if c in row and pd.notna(row[c]) and str(row[c]).strip():
                values.append(str(row[c]).strip())

        if not values:
            warnings.append("Aucun domaine défini (colonne 'domaine' vide)")
            # Domaine par défaut
            return self._get_or_create_domain(framework_id, "Autre", 0, None, language), warnings

        parent_id: Optional[uuid.UUID] = None
        current_id: Optional[uuid.UUID] = None

        for lvl, label in enumerate(values):
            current_id = self._get_or_create_domain(framework_id, label, lvl, parent_id, language)
            parent_id = current_id

        return current_id, warnings

    @staticmethod
    def _parse_tags(tags_value: object) -> List[str]:
        """
        Accepte:
          - JSON array: '["A","B"]'
          - CSV: "A, B, C"
          - texte simple: "A.5 Politique ..."
        Retourne toujours une liste.
        """
        if tags_value is None:
            return []
        s = str(tags_value).strip()
        if not s:
            return []
        # JSON array
        if s.startswith("[") and s.endswith("]"):
            try:
                parsed = json.loads(s)
                return [str(x).strip() for x in parsed if str(x).strip()]
            except Exception:
                pass
        # CSV
        if "," in s or ";" in s:
            parts = re.split(r"[;,]", s)
            return [p.strip() for p in parts if p.strip()]
        # texte simple -> un seul tag
        return [s]

    # ─────────────────────────── Import principal ─────────────────────────── #

    def import_excel(self, df, metadata: Dict):
        """
        Import du référentiel Excel avec création :
        - Framework
        - Domaines et DomainTitles
        - Exigences
        Retourne un dict de stats + log formaté pour la console
        """
        try:
            import logging
            logger = logging.getLogger(__name__)

            # --- Métadonnées framework ---
            fw_id        = str(uuid.uuid4())
            fw_code      = _s(metadata.get("code")).strip()
            fw_name      = (_s(metadata.get("name")) or fw_code).strip()
            fw_version   = _s(metadata.get("version") or "1.0").strip()
            fw_publisher = _s(metadata.get("publisher")).strip()
            fw_language  = (_s(metadata.get("language")) or "fr").strip() or "fr"
            fw_desc      = _s(metadata.get("description")).strip() or None
            fw_formule   = _s(metadata.get("formule")).strip() or None  # si utilisé

            # --- Insert framework (SQL direct) ---
            self.db.execute(
                text("""
                    INSERT INTO framework (
                        id, code, name, version, publisher, language,
                        description, formule, is_active, created_at
                    ) VALUES (
                        :id, :code, :name, :version, :publisher, :language,
                        :description, :formule, true, NOW()
                    )
                """),
                {
                    "id": fw_id,
                    "code": fw_code,
                    "name": fw_name,
                    "version": fw_version,
                    "publisher": fw_publisher,
                    "language": fw_language,
                    "description": fw_desc,
                    "formule": fw_formule,
                }
            )

            # --- Initialisation des stats ---
            self.stats = {
                "framework_id": fw_id,
                "framework_name": fw_name,
                "domains_created": 0,
                "requirements_created": 0,
                "warnings": [],
                "errors": [],
            }

            # Helper simple - utilise _cell pour éviter "nan"
            # Supporte les variantes avec/sans underscore et avec/sans espace
            def val(row, key):
                # Essayer la clé exacte
                if key in row:
                    return _cell(row.get(key))
                # Essayer avec espace au lieu de underscore
                key_with_space = key.replace("_", " ")
                if key_with_space in row:
                    return _cell(row.get(key_with_space))
                # Essayer avec underscore au lieu d'espace
                key_with_underscore = key.replace(" ", "_")
                if key_with_underscore in row:
                    return _cell(row.get(key_with_underscore))
                # Recherche insensible à la casse
                for col in row.index:
                    if str(col).strip().lower().replace(" ", "_") == key.lower().replace(" ", "_"):
                        return _cell(row.get(col))
                return ""

            # --- Lecture Excel ---
            for _, row in df.iterrows():
                # --- Niveaux hiérarchiques nettoyés ---
                levels = [_cell(row.get(k)) for k in ["domaine","domaine_rang1","domaine_rang2","domaine_rang3","domaine_rang4"]]
                levels = [x for x in levels if x]  # enlève vides/nan
                if not levels:
                    self.stats["warnings"].append("Ligne ignorée: hiérarchie vide")
                    continue

                parent_id = None
                leaf_domain_id = None
                path_titles = []

                for idx, title in enumerate(levels):
                    # on construit un code UNIQUE par *chemin* : slug("lvl1 / lvl2 / ... / lvln")
                    path_titles.append(title)
                    path_str = " / ".join(path_titles)
                    code_slug = _slugify(path_str)
                    if not code_slug:
                        code_slug = f"node-{idx}-{uuid.uuid4().hex[:8]}"  # fallback unique

                    # la contrainte est (framework_id, code) => on cherche par code uniquement
                    existing = self.db.execute(
                        text("""
                            SELECT id FROM domain
                            WHERE framework_id = :fw_id
                            AND code = :code
                            LIMIT 1
                        """),
                        {"fw_id": fw_id, "code": code_slug}
                    ).fetchone()

                    if existing:
                        domain_id = existing[0]
                    else:
                        domain_id = str(uuid.uuid4())
                        path_titles.append(title)
                        path_str = " > ".join(path_titles)

                        self.db.execute(
                            text("""
                                INSERT INTO domain (
                                    id, framework_id, parent_id, code,
                                    title, description, path, section_type,
                                    level, hierarchy_level, sort_index, sort_order,
                                    is_active, created_at
                                ) VALUES (
                                    :id, :framework_id, :parent_id, :code,
                                    :title, :description, :path, :section_type,
                                    :level, :hierarchy_level, :sort_index, :sort_order,
                                    true, NOW()
                                )
                            """),
                            {
                                "id": domain_id,
                                "framework_id": fw_id,
                                "parent_id": parent_id,
                                "code": code_slug,
                                "title": title,                          # ✅
                                "description": title,                    # ✅ (ou une vraie desc si tu l’as)
                                "path": path_str,                        # ✅ "N1 > N2 > …"
                                "section_type": "chapitre",              # ✅ si cohérent avec ton modèle
                                "level": idx,
                                "hierarchy_level": idx + 1,              # ✅ ton JSON montre ce champ
                                "sort_index": idx,
                                "sort_order": idx
                            }
                        )

                        self.stats["domains_created"] += 1

                        # domain_title (non bloquant si la table n'existe pas)
                        try:
                            self.db.execute(
                                text("""
                                    INSERT INTO domain_title (
                                        id, domain_id, language, title, is_primary, created_at
                                    ) VALUES (
                                        :id, :domain_id, :language, :title, true, NOW()
                                    )
                                """),
                                {
                                    "id": str(uuid.uuid4()),
                                    "domain_id": domain_id,
                                    "language": fw_language,
                                    "title": title or f"Niveau {idx+1}",
                                }
                            )
                        except Exception:
                            pass

                    parent_id = domain_id
                    leaf_domain_id = domain_id


                # --- Requirement ---
                tags_raw = val(row, "tags")
                tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []
                chapter_path = " > ".join(levels) if levels else None

                self.db.execute(
                    text("""
                        INSERT INTO requirement (
                            id, framework_id, domain_id, official_code,
                            title, requirement_text, tags, risk_level,
                            compliance_obligation, chapter_path, ai_processed, created_at
                        ) VALUES (
                            :id, :framework_id, :domain_id, :official_code,
                            :title, :requirement_text, :tags, :risk_level,
                            :compliance_obligation, :chapter_path, false, NOW()
                        )
                    """),
                    {
                        "id": str(uuid.uuid4()),
                        "framework_id": fw_id,
                        "domain_id": leaf_domain_id,
                        "official_code": val(row, "code_officiel"),
                        "title": val(row, "titre"),
                        "requirement_text": val(row, "description"),
                        "tags": Json(tags),
                        "risk_level": _normalize_risk(val(row, "niveau_risque")),
                        "compliance_obligation": _normalize_obligation(val(row, "obligation_conformite")),
                        "chapter_path": chapter_path,
                    }
                )
                self.stats["requirements_created"] += 1

            # ✅ LOG final dans la console
            logger.info(
                f"""
        ✅ Import terminé avec succès !
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        📊 Statistiques :
        • Framework : {fw_name}
        • Domaines créés : {self.stats['domains_created']}
        • Exigences importées : {self.stats['requirements_created']}
        • Avertissements : {len(self.stats['warnings'])}
        • Erreurs : {len(self.stats['errors'])}
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                """
            )

            return self.stats

        except Exception as e:
            if not hasattr(self, "stats"):
                self.stats = {"errors": []}
            self.stats["errors"].append(str(e))
            import logging
            logging.getLogger(__name__).error(f"❌ Erreur import référentiel : {e}")
            return self.stats


# ─────────────────────────── Helper externe ─────────────────────────── #

def import_excel_to_database(db: Session, excel_file_path: str, framework_info: Dict) -> Dict:
    """
    Fonction helper pour importer un fichier Excel depuis un chemin.
    """
    df = pd.read_excel(excel_file_path)
    df.columns = [str(c).strip() for c in df.columns]
    service = DomainImportService(db)
    return service.import_excel(df, framework_info)
