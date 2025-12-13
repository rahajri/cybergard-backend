"""
Prompts EBIOS RM v2 - Atelier 5 : Matrice des Risques

Ce module gere la classification des risques selon la methodologie ANSSI.
AT5 ne genere PAS de contenu via IA - il consomme les donnees de AT3 et AT4
et calcule le niveau de risque selon les regles ANSSI.

Classification ANSSI :
- Score 1-3  : FAIBLE (vert)
- Score 4-7  : MODERE (jaune)
- Score 8-11 : IMPORTANT (orange)
- Score 12-16: CRITIQUE (rouge)

Score = Gravite × Vraisemblance (G et V entre 1 et 4)
"""

import logging
from typing import Dict, Any, List, Optional
from enum import Enum

logger = logging.getLogger(__name__)


# ==============================================================================
# ENUMS ET CONSTANTES ANSSI
# ==============================================================================

class RiskLevel(str, Enum):
    """Niveaux de risque ANSSI."""
    FAIBLE = "FAIBLE"
    MODERE = "MODERE"
    IMPORTANT = "IMPORTANT"
    CRITIQUE = "CRITIQUE"


# Seuils ANSSI (non configurables selon spec)
RISK_THRESHOLDS = {
    "FAIBLE": (1, 3),      # Score 1-3
    "MODERE": (4, 7),      # Score 4-7
    "IMPORTANT": (8, 11),  # Score 8-11
    "CRITIQUE": (12, 16)   # Score 12-16
}

# Couleurs pour le frontend
RISK_COLORS = {
    "FAIBLE": "#22c55e",      # Vert
    "MODERE": "#eab308",      # Jaune
    "IMPORTANT": "#f97316",   # Orange
    "CRITIQUE": "#ef4444"     # Rouge
}

# Couleurs de fond (plus claires)
RISK_BG_COLORS = {
    "FAIBLE": "#dcfce7",      # Vert clair
    "MODERE": "#fef9c3",      # Jaune clair
    "IMPORTANT": "#ffedd5",   # Orange clair
    "CRITIQUE": "#fee2e2"     # Rouge clair
}


# ==============================================================================
# SERVICE DE CLASSIFICATION DES RISQUES
# ==============================================================================

class RiskMatrixService:
    """
    Service de classification des risques selon la methodologie ANSSI.

    Ce service :
    1. Calcule le score de risque (G × V)
    2. Determine le niveau ANSSI (FAIBLE, MODERE, IMPORTANT, CRITIQUE)
    3. Prepare les donnees pour la matrice 4×4
    4. Genere les statistiques pour le dashboard
    """

    @staticmethod
    def clamp_value(value: Any, min_val: int = 1, max_val: int = 4) -> int:
        """
        Normalise une valeur entre min et max.

        Args:
            value: Valeur a normaliser
            min_val: Valeur minimale (defaut: 1)
            max_val: Valeur maximale (defaut: 4)

        Returns:
            Valeur normalisee entre min_val et max_val
        """
        if value is None:
            return min_val

        try:
            v = int(value)
            return max(min_val, min(max_val, v))
        except (ValueError, TypeError):
            logger.warning(f"Valeur invalide pour clamp: {value}, utilisation de {min_val}")
            return min_val

    @staticmethod
    def compute_score(gravity: int, likelihood: int) -> int:
        """
        Calcule le score de risque.

        Args:
            gravity: Gravite (1-4)
            likelihood: Vraisemblance (1-4)

        Returns:
            Score = gravity × likelihood (1-16)
        """
        g = RiskMatrixService.clamp_value(gravity)
        v = RiskMatrixService.clamp_value(likelihood)
        return g * v

    @staticmethod
    def compute_risk_level(score: int) -> str:
        """
        Determine le niveau de risque ANSSI selon le score.

        Args:
            score: Score de risque (1-16)

        Returns:
            Niveau ANSSI: FAIBLE, MODERE, IMPORTANT ou CRITIQUE
        """
        score = max(1, min(16, score))

        if score <= 3:
            return RiskLevel.FAIBLE.value
        elif score <= 7:
            return RiskLevel.MODERE.value
        elif score <= 11:
            return RiskLevel.IMPORTANT.value
        else:
            return RiskLevel.CRITIQUE.value

    @staticmethod
    def compute_risk_level_from_gv(gravity: int, likelihood: int) -> Dict[str, Any]:
        """
        Calcule le niveau de risque complet a partir de G et V.

        Args:
            gravity: Gravite (1-4)
            likelihood: Vraisemblance (1-4)

        Returns:
            Dict avec score, level, color, bg_color
        """
        g = RiskMatrixService.clamp_value(gravity)
        v = RiskMatrixService.clamp_value(likelihood)
        score = g * v
        level = RiskMatrixService.compute_risk_level(score)

        return {
            "gravity": g,
            "likelihood": v,
            "score": score,
            "level": level,
            "color": RISK_COLORS.get(level, "#6b7280"),
            "bg_color": RISK_BG_COLORS.get(level, "#f3f4f6")
        }

    @staticmethod
    def get_matrix_position(gravity: int, likelihood: int) -> Dict[str, int]:
        """
        Retourne la position dans la matrice 4×4.

        La matrice est indexee :
        - Axe X (colonnes) : Vraisemblance (1-4, gauche a droite)
        - Axe Y (lignes) : Gravite (4-1, haut en bas)

        Args:
            gravity: Gravite (1-4)
            likelihood: Vraisemblance (1-4)

        Returns:
            Dict avec row (0-3) et col (0-3)
        """
        g = RiskMatrixService.clamp_value(gravity)
        v = RiskMatrixService.clamp_value(likelihood)

        return {
            "row": 4 - g,  # G4 en haut (row=0), G1 en bas (row=3)
            "col": v - 1   # V1 a gauche (col=0), V4 a droite (col=3)
        }

    @staticmethod
    def process_scenario(scenario: Dict[str, Any], scenario_type: str = "SS") -> Dict[str, Any]:
        """
        Traite un scenario (strategique ou operationnel) pour AT5.

        Args:
            scenario: Donnees du scenario
            scenario_type: "SS" pour strategique, "SO" pour operationnel

        Returns:
            Scenario enrichi avec classification ANSSI
        """
        # Extraire G et V selon le type
        if scenario_type == "SS":
            gravity = scenario.get("severity", scenario.get("gravite", 0))
            likelihood = scenario.get("likelihood", scenario.get("vraisemblance", 0))
            reference = scenario.get("code", "SS??")
            title = scenario.get("title", scenario.get("titre", "Sans titre"))
        else:  # SO
            gravity = scenario.get("gravite", scenario.get("gravity", 0))
            likelihood = scenario.get("vraisemblance", scenario.get("likelihood", 0))
            reference = scenario.get("reference", "SO??")
            title = scenario.get("titre", scenario.get("title", "Sans titre"))

        # Calculer la classification
        risk_info = RiskMatrixService.compute_risk_level_from_gv(gravity, likelihood)
        position = RiskMatrixService.get_matrix_position(gravity, likelihood)

        return {
            "reference": reference,
            "title": title,
            "type": scenario_type,
            "gravity": risk_info["gravity"],
            "likelihood": risk_info["likelihood"],
            "score": risk_info["score"],
            "level": risk_info["level"],
            "color": risk_info["color"],
            "bg_color": risk_info["bg_color"],
            "matrix_row": position["row"],
            "matrix_col": position["col"],
            # Conserver les donnees originales
            "original_data": scenario
        }

    @staticmethod
    def build_risk_matrix(
        strategic_scenarios: List[Dict[str, Any]],
        operational_scenarios: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Construit la matrice des risques complete.

        Args:
            strategic_scenarios: Liste des scenarios strategiques (AT3)
            operational_scenarios: Liste des scenarios operationnels (AT4)

        Returns:
            Dict avec matrice, scenarios, statistiques
        """
        # Initialiser la matrice 4×4
        matrix = [[[] for _ in range(4)] for _ in range(4)]

        # Traiter les scenarios strategiques
        processed_ss = []
        for ss in strategic_scenarios:
            try:
                processed = RiskMatrixService.process_scenario(ss, "SS")
                processed_ss.append(processed)
                matrix[processed["matrix_row"]][processed["matrix_col"]].append(processed)
            except Exception as e:
                logger.warning(f"Erreur traitement scenario SS: {e}")

        # Traiter les scenarios operationnels
        processed_so = []
        for so in operational_scenarios:
            try:
                processed = RiskMatrixService.process_scenario(so, "SO")
                processed_so.append(processed)
                matrix[processed["matrix_row"]][processed["matrix_col"]].append(processed)
            except Exception as e:
                logger.warning(f"Erreur traitement scenario SO: {e}")

        # Calculer les statistiques
        all_scenarios = processed_ss + processed_so
        stats = RiskMatrixService.compute_statistics(all_scenarios)

        return {
            "matrix": matrix,
            "strategic_scenarios": processed_ss,
            "operational_scenarios": processed_so,
            "all_scenarios": all_scenarios,
            "statistics": stats,
            "thresholds": RISK_THRESHOLDS,
            "colors": RISK_COLORS
        }

    @staticmethod
    def compute_statistics(scenarios: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Calcule les statistiques de la matrice.

        Args:
            scenarios: Liste des scenarios traites

        Returns:
            Dict avec statistiques par niveau, moyennes, etc.
        """
        if not scenarios:
            return {
                "total": 0,
                "by_level": {
                    "FAIBLE": 0,
                    "MODERE": 0,
                    "IMPORTANT": 0,
                    "CRITIQUE": 0
                },
                "by_type": {
                    "SS": 0,
                    "SO": 0
                },
                "avg_score": 0,
                "max_score": 0,
                "critical_count": 0
            }

        # Compter par niveau
        by_level = {"FAIBLE": 0, "MODERE": 0, "IMPORTANT": 0, "CRITIQUE": 0}
        for s in scenarios:
            level = s.get("level", "FAIBLE")
            by_level[level] = by_level.get(level, 0) + 1

        # Compter par type
        by_type = {"SS": 0, "SO": 0}
        for s in scenarios:
            stype = s.get("type", "SS")
            by_type[stype] = by_type.get(stype, 0) + 1

        # Scores
        scores = [s.get("score", 0) for s in scenarios]

        return {
            "total": len(scenarios),
            "by_level": by_level,
            "by_type": by_type,
            "avg_score": round(sum(scores) / len(scores), 2) if scores else 0,
            "max_score": max(scores) if scores else 0,
            "critical_count": by_level.get("CRITIQUE", 0),
            "important_count": by_level.get("IMPORTANT", 0)
        }

    @staticmethod
    def get_matrix_cell_info(row: int, col: int) -> Dict[str, Any]:
        """
        Retourne les informations d'une cellule de la matrice.

        Args:
            row: Ligne (0-3, 0=haut)
            col: Colonne (0-3, 0=gauche)

        Returns:
            Dict avec gravity, likelihood, score_range, level
        """
        gravity = 4 - row  # row 0 = G4, row 3 = G1
        likelihood = col + 1  # col 0 = V1, col 3 = V4

        score = gravity * likelihood
        level = RiskMatrixService.compute_risk_level(score)

        return {
            "gravity": gravity,
            "likelihood": likelihood,
            "score": score,
            "level": level,
            "color": RISK_COLORS.get(level, "#6b7280"),
            "bg_color": RISK_BG_COLORS.get(level, "#f3f4f6")
        }

    @staticmethod
    def generate_empty_matrix_template() -> List[List[Dict[str, Any]]]:
        """
        Genere le template de la matrice vide avec les couleurs.

        Returns:
            Matrice 4×4 avec les informations de chaque cellule
        """
        matrix = []
        for row in range(4):
            matrix_row = []
            for col in range(4):
                cell_info = RiskMatrixService.get_matrix_cell_info(row, col)
                cell_info["scenarios"] = []
                matrix_row.append(cell_info)
            matrix.append(matrix_row)
        return matrix


# ==============================================================================
# VALIDATION DES DONNEES AT5
# ==============================================================================

def validate_at5_input(
    at3_data: Optional[Dict[str, Any]],
    at4_data: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Valide les donnees d'entree pour AT5.

    Args:
        at3_data: Donnees AT3 (scenarios strategiques)
        at4_data: Donnees AT4 (scenarios operationnels)

    Returns:
        Dict avec valid, errors, warnings, data
    """
    errors = []
    warnings = []

    strategic_scenarios = []
    operational_scenarios = []

    # Valider AT3
    if at3_data:
        ss_list = at3_data.get("scenarios_strategiques", [])
        for i, ss in enumerate(ss_list):
            gravity = ss.get("severity", ss.get("gravite"))
            likelihood = ss.get("likelihood", ss.get("vraisemblance"))

            if gravity is None:
                warnings.append(f"SS[{i}]: gravite manquante")
            if likelihood is None:
                warnings.append(f"SS[{i}]: vraisemblance manquante")

            if gravity is not None and likelihood is not None:
                strategic_scenarios.append(ss)
    else:
        warnings.append("Aucune donnee AT3 fournie")

    # Valider AT4
    if at4_data:
        so_list = at4_data.get("scenarios_operationnels", [])
        for i, so in enumerate(so_list):
            gravity = so.get("gravite", so.get("gravity"))
            likelihood = so.get("vraisemblance", so.get("likelihood"))

            if gravity is None:
                warnings.append(f"SO[{i}]: gravite manquante")
            if likelihood is None:
                warnings.append(f"SO[{i}]: vraisemblance manquante")

            if gravity is not None and likelihood is not None:
                operational_scenarios.append(so)
    else:
        warnings.append("Aucune donnee AT4 fournie")

    # Verifier qu'on a au moins un scenario
    if not strategic_scenarios and not operational_scenarios:
        errors.append("Aucun scenario valide pour construire la matrice")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "strategic_scenarios": strategic_scenarios,
        "operational_scenarios": operational_scenarios,
        "stats": {
            "strategic_count": len(strategic_scenarios),
            "operational_count": len(operational_scenarios),
            "total": len(strategic_scenarios) + len(operational_scenarios)
        }
    }


# ==============================================================================
# FONCTION DE GENERATION AT5 (pas d'IA, calcul direct)
# ==============================================================================

def generate_at5_matrix(
    at3_data: Optional[Dict[str, Any]],
    at4_data: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Genere la matrice des risques AT5.

    Cette fonction ne fait PAS appel a l'IA - elle consomme
    les donnees de AT3 et AT4 et applique les regles ANSSI.

    Args:
        at3_data: Donnees AT3 (scenarios strategiques)
        at4_data: Donnees AT4 (scenarios operationnels)

    Returns:
        Dict avec matrice, scenarios, statistiques
    """
    # Valider les entrees
    validation = validate_at5_input(at3_data, at4_data)

    if not validation["valid"]:
        return {
            "success": False,
            "data": None,
            "errors": validation["errors"],
            "warnings": validation["warnings"]
        }

    # Construire la matrice
    matrix_data = RiskMatrixService.build_risk_matrix(
        strategic_scenarios=validation["strategic_scenarios"],
        operational_scenarios=validation["operational_scenarios"]
    )

    return {
        "success": True,
        "data": matrix_data,
        "warnings": validation["warnings"],
        "stats": validation["stats"]
    }
