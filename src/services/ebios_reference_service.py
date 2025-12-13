"""
Service de gestion des referentiels EBIOS RM ANSSI

Ce service gere :
- Le chargement des referentiels depuis la base de donnees
- Le formatage des referentiels pour les prompts IA
- La validation des donnees selon les standards ANSSI

Tables referentielles :
- ref_ebios_sr : Sources de risque types (11 entrees)
- ref_ebios_bs : Biens supports types (18 entrees)
- ref_ebios_vm : Valeurs metier types (15 entrees)
- ref_ebios_er : Evenements redoutes types (18 entrees)
- ref_ebios_ov : Objectifs vises types (8 entrees)
- ref_ebios_guides : Extraits guides ANSSI
"""

import logging
from typing import Dict, Any, List, Optional
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class EbiosReferenceService:
    """
    Service de gestion des referentiels EBIOS RM ANSSI.

    Fournit des methodes pour :
    - Charger les referentiels depuis la base
    - Formater les donnees pour les prompts IA
    - Recuperer les guides par atelier
    """

    def __init__(self, db: Session):
        """
        Initialise le service avec une session de base de donnees.

        Args:
            db: Session SQLAlchemy
        """
        self.db = db

    # ==========================================================================
    # SOURCES DE RISQUE (ref_ebios_sr)
    # ==========================================================================

    def get_sources_risque(self, limit: int = 15) -> List[Dict[str, Any]]:
        """
        Recupere les sources de risque types depuis la base.

        Args:
            limit: Nombre maximum de sources a retourner

        Returns:
            Liste des sources de risque avec leurs attributs
        """
        query = text("""
            SELECT id, label, categorie, description, motivations,
                   ressources, sophistication, tags
            FROM ref_ebios_sr
            ORDER BY categorie, label
            LIMIT :limit
        """)

        result = self.db.execute(query, {"limit": limit})
        sources = []

        for row in result:
            sources.append({
                "id": row[0],
                "label": row[1],
                "categorie": row[2],
                "description": row[3],
                "motivations": row[4] or [],
                "ressources": row[5],
                "sophistication": row[6],
                "tags": row[7] or []
            })

        return sources

    def get_sources_risque_for_prompt(self, limit: int = 10) -> str:
        """
        Formate les sources de risque pour inclusion dans un prompt IA.

        Args:
            limit: Nombre maximum de sources a inclure

        Returns:
            Texte formate des sources de risque
        """
        sources = self.get_sources_risque(limit)

        if not sources:
            return "Aucun referentiel de sources de risque disponible."

        lines = []
        for sr in sources:
            motivations = ", ".join(sr["motivations"][:3]) if sr["motivations"] else "N/A"
            lines.append(
                f"- {sr['label']} ({sr['categorie']}): {sr['description'][:150]}... "
                f"Motivations: {motivations}"
            )

        return "\n".join(lines)

    # ==========================================================================
    # BIENS SUPPORTS (ref_ebios_bs)
    # ==========================================================================

    def get_biens_supports(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Recupere les biens supports types depuis la base.

        Args:
            limit: Nombre maximum de biens a retourner

        Returns:
            Liste des biens supports avec leurs attributs
        """
        query = text("""
            SELECT id, label, type, description, exemples, tags
            FROM ref_ebios_bs
            ORDER BY type, label
            LIMIT :limit
        """)

        result = self.db.execute(query, {"limit": limit})
        biens = []

        for row in result:
            biens.append({
                "id": row[0],
                "label": row[1],
                "type": row[2],
                "description": row[3],
                "exemples": row[4] or [],
                "tags": row[5] or []
            })

        return biens

    def get_biens_supports_for_prompt(self, limit: int = 12) -> str:
        """
        Formate les biens supports pour inclusion dans un prompt IA.

        Args:
            limit: Nombre maximum de biens a inclure

        Returns:
            Texte formate des biens supports
        """
        biens = self.get_biens_supports(limit)

        if not biens:
            return "Aucun referentiel de biens supports disponible."

        lines = []
        current_type = None

        for bs in biens:
            if bs["type"] != current_type:
                current_type = bs["type"]
                lines.append(f"\n[{current_type}]")

            exemples = ", ".join(bs["exemples"][:3]) if bs["exemples"] else ""
            lines.append(f"  - {bs['label']}: {bs['description'][:100]}... Ex: {exemples}")

        return "\n".join(lines)

    def get_biens_supports_types(self) -> List[str]:
        """
        Recupere la liste des types de biens supports disponibles.

        Returns:
            Liste des types uniques
        """
        query = text("""
            SELECT DISTINCT type FROM ref_ebios_bs ORDER BY type
        """)

        result = self.db.execute(query)
        return [row[0] for row in result]

    # ==========================================================================
    # VALEURS METIER (ref_ebios_vm)
    # ==========================================================================

    def get_valeurs_metier(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Recupere les valeurs metier types depuis la base.

        Args:
            limit: Nombre maximum de valeurs a retourner

        Returns:
            Liste des valeurs metier avec leurs attributs
        """
        query = text("""
            SELECT id, label, nature, description, exemples, besoins_securite, tags
            FROM ref_ebios_vm
            ORDER BY nature, label
            LIMIT :limit
        """)

        result = self.db.execute(query, {"limit": limit})
        valeurs = []

        for row in result:
            valeurs.append({
                "id": row[0],
                "label": row[1],
                "nature": row[2],
                "description": row[3],
                "exemples": row[4] or [],
                "besoins_securite": row[5] or [],
                "tags": row[6] or []
            })

        return valeurs

    def get_valeurs_metier_for_prompt(self, limit: int = 10) -> str:
        """
        Formate les valeurs metier pour inclusion dans un prompt IA.

        Args:
            limit: Nombre maximum de valeurs a inclure

        Returns:
            Texte formate des valeurs metier
        """
        valeurs = self.get_valeurs_metier(limit)

        if not valeurs:
            return "Aucun referentiel de valeurs metier disponible."

        lines = []
        for vm in valeurs:
            besoins = ", ".join(vm["besoins_securite"][:3]) if vm["besoins_securite"] else "N/A"
            lines.append(
                f"- {vm['label']} ({vm['nature']}): {vm['description'][:120]}... "
                f"Besoins: {besoins}"
            )

        return "\n".join(lines)

    # ==========================================================================
    # EVENEMENTS REDOUTES (ref_ebios_er)
    # ==========================================================================

    def get_evenements_redoutes(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Recupere les evenements redoutes types depuis la base.

        Args:
            limit: Nombre maximum d'evenements a retourner

        Returns:
            Liste des evenements redoutes avec leurs attributs
        """
        query = text("""
            SELECT id, label, description, critere_atteint,
                   gravite_default, impacts_types, tags
            FROM ref_ebios_er
            ORDER BY gravite_default DESC, label
            LIMIT :limit
        """)

        result = self.db.execute(query, {"limit": limit})
        evenements = []

        for row in result:
            evenements.append({
                "id": row[0],
                "label": row[1],
                "description": row[2],
                "critere_atteint": row[3],
                "gravite_default": row[4],
                "impacts_types": row[5] or [],
                "tags": row[6] or []
            })

        return evenements

    def get_evenements_redoutes_for_prompt(self, limit: int = 12) -> str:
        """
        Formate les evenements redoutes pour inclusion dans un prompt IA.

        Args:
            limit: Nombre maximum d'evenements a inclure

        Returns:
            Texte formate des evenements redoutes
        """
        evenements = self.get_evenements_redoutes(limit)

        if not evenements:
            return "Aucun referentiel d'evenements redoutes disponible."

        gravite_labels = {1: "G1-Mineure", 2: "G2-Significative", 3: "G3-Grave", 4: "G4-Critique"}

        lines = []
        for er in evenements:
            gravite = gravite_labels.get(er["gravite_default"], f"G{er['gravite_default']}")
            lines.append(
                f"- {er['label']} [{er['critere_atteint']}] ({gravite}): "
                f"{er['description'][:100]}..."
            )

        return "\n".join(lines)

    # ==========================================================================
    # OBJECTIFS VISES (ref_ebios_ov)
    # ==========================================================================

    def get_objectifs_vises(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Recupere les objectifs vises types depuis la base.

        Args:
            limit: Nombre maximum d'objectifs a retourner

        Returns:
            Liste des objectifs vises avec leurs attributs
        """
        query = text("""
            SELECT id, label, description, finalites,
                   secteurs_cibles, sources_typiques, tags
            FROM ref_ebios_ov
            ORDER BY label
            LIMIT :limit
        """)

        result = self.db.execute(query, {"limit": limit})
        objectifs = []

        for row in result:
            objectifs.append({
                "id": row[0],
                "label": row[1],
                "description": row[2],
                "finalites": row[3] or [],
                "secteurs_cibles": row[4] or [],
                "sources_typiques": row[5] or [],
                "tags": row[6] or []
            })

        return objectifs

    def get_objectifs_vises_for_prompt(self, limit: int = 8) -> str:
        """
        Formate les objectifs vises pour inclusion dans un prompt IA.

        Args:
            limit: Nombre maximum d'objectifs a inclure

        Returns:
            Texte formate des objectifs vises
        """
        objectifs = self.get_objectifs_vises(limit)

        if not objectifs:
            return "Aucun referentiel d'objectifs vises disponible."

        lines = []
        for ov in objectifs:
            finalites = ", ".join(ov["finalites"][:3]) if ov["finalites"] else "N/A"
            lines.append(
                f"- {ov['label']}: {ov['description'][:100]}... Finalites: {finalites}"
            )

        return "\n".join(lines)

    # ==========================================================================
    # GUIDES ANSSI (ref_ebios_guides)
    # ==========================================================================

    def get_guides_by_atelier(self, atelier: str) -> List[Dict[str, Any]]:
        """
        Recupere les extraits de guides pour un atelier specifique.

        Args:
            atelier: Code de l'atelier (AT1, AT2, AT3, AT4, AT5, COMMUN)

        Returns:
            Liste des guides avec leurs extraits
        """
        query = text("""
            SELECT id, atelier, titre, extrait, reference_pdf
            FROM ref_ebios_guides
            WHERE atelier = :atelier OR atelier = 'COMMUN'
            ORDER BY id
        """)

        result = self.db.execute(query, {"atelier": atelier})
        guides = []

        for row in result:
            guides.append({
                "id": row[0],
                "atelier": row[1],
                "titre": row[2],
                "extrait": row[3],
                "reference_pdf": row[4]
            })

        return guides

    def get_guides_for_prompt(self, atelier: str) -> str:
        """
        Formate les guides pour inclusion dans un prompt IA.

        Args:
            atelier: Code de l'atelier

        Returns:
            Texte formate des guides
        """
        guides = self.get_guides_by_atelier(atelier)

        if not guides:
            return ""

        lines = [f"\n--- Extraits methodologiques ANSSI pour {atelier} ---\n"]

        for guide in guides:
            lines.append(f"[{guide['titre']}]")
            lines.append(guide['extrait'])
            lines.append("")

        return "\n".join(lines)

    # ==========================================================================
    # METHODES COMBINÉES POUR PROMPTS IA
    # ==========================================================================

    def get_referentiels_for_at1(self) -> Dict[str, str]:
        """
        Recupere tous les referentiels necessaires pour l'AT1.

        Returns:
            Dict avec les referentiels formates pour le prompt
        """
        return {
            "valeurs_metier": self.get_valeurs_metier_for_prompt(10),
            "biens_supports": self.get_biens_supports_for_prompt(12),
            "evenements_redoutes": self.get_evenements_redoutes_for_prompt(12),
            "guides": self.get_guides_for_prompt("AT1")
        }

    def get_referentiels_for_at2(self) -> Dict[str, str]:
        """
        Recupere tous les referentiels necessaires pour l'AT2.

        Returns:
            Dict avec les referentiels formates pour le prompt
        """
        return {
            "sources_risque": self.get_sources_risque_for_prompt(10),
            "objectifs_vises": self.get_objectifs_vises_for_prompt(8),
            "guides": self.get_guides_for_prompt("AT2")
        }

    def get_referentiels_for_at3(self) -> Dict[str, str]:
        """
        Recupere tous les referentiels necessaires pour l'AT3.

        Returns:
            Dict avec les referentiels formates pour le prompt
        """
        return {
            "sources_risque": self.get_sources_risque_for_prompt(8),
            "biens_supports": self.get_biens_supports_for_prompt(10),
            "evenements_redoutes": self.get_evenements_redoutes_for_prompt(10),
            "guides": self.get_guides_for_prompt("AT3")
        }

    def get_referentiels_for_at4(self) -> Dict[str, str]:
        """
        Recupere les referentiels necessaires pour l'AT4.

        Returns:
            Dict avec les referentiels formates pour le prompt
        """
        return {
            "guides": self.get_guides_for_prompt("AT4")
        }

    def get_referentiels_for_at5(self) -> Dict[str, str]:
        """
        Recupere les referentiels necessaires pour l'AT5.

        Returns:
            Dict avec les referentiels formates pour le prompt
        """
        return {
            "guides": self.get_guides_for_prompt("AT5")
        }

    # ==========================================================================
    # UTILITAIRES
    # ==========================================================================

    def check_referentiels_loaded(self) -> Dict[str, int]:
        """
        Verifie que les referentiels sont charges en base.

        Returns:
            Dict avec le nombre d'entrees par table
        """
        tables = [
            "ref_ebios_sr",
            "ref_ebios_bs",
            "ref_ebios_vm",
            "ref_ebios_er",
            "ref_ebios_ov",
            "ref_ebios_guides"
        ]

        counts = {}

        for table in tables:
            try:
                query = text(f"SELECT COUNT(*) FROM {table}")
                result = self.db.execute(query)
                counts[table] = result.scalar() or 0
            except Exception as e:
                logger.warning(f"Table {table} not found or error: {e}")
                counts[table] = -1

        return counts

    def is_ebios_rm_v2_enabled(self, project_id: str) -> bool:
        """
        Verifie si un projet utilise le mode EBIOS RM v2.

        Args:
            project_id: UUID du projet

        Returns:
            True si le projet utilise ebios_rm_v2, False sinon
        """
        query = text("""
            SELECT analysis_version
            FROM risk_project
            WHERE id = CAST(:project_id AS uuid)
        """)

        try:
            result = self.db.execute(query, {"project_id": project_id})
            row = result.fetchone()

            if row and row[0] == "ebios_rm_v2":
                return True
        except Exception as e:
            logger.error(f"Error checking analysis_version: {e}")

        return False


# ==========================================================================
# FONCTION UTILITAIRE POUR INJECTION DE DEPENDANCE
# ==========================================================================

def get_ebios_reference_service(db: Session) -> EbiosReferenceService:
    """
    Factory pour creer une instance du service.

    Args:
        db: Session SQLAlchemy

    Returns:
        Instance de EbiosReferenceService
    """
    return EbiosReferenceService(db)
