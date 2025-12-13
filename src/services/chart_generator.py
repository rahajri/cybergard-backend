"""
Service de génération de graphiques pour les rapports.

Génère des graphiques professionnels avec matplotlib/plotly
pour inclusion dans les PDFs.
"""

from typing import Dict, Any, List, Optional, Tuple
import logging
from io import BytesIO
import base64

try:
    # IMPORTANT: Configurer le backend AVANT d'importer pyplot
    # Cela évite les erreurs tkinter sur Windows avec FastAPI
    import matplotlib
    matplotlib.use('Agg')  # Backend non-interactif (sans GUI)

    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    from matplotlib.path import Path
    import numpy as np
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    logging.warning("Matplotlib not installed. Chart generation unavailable.")

logger = logging.getLogger(__name__)


class ChartGenerator:
    """Générateur de graphiques pour rapports."""

    def __init__(self, color_scheme: Optional[Dict[str, str]] = None):
        """
        Initialise le générateur de graphiques.

        Args:
            color_scheme: Palette de couleurs du template
        """
        if not MATPLOTLIB_AVAILABLE:
            raise RuntimeError("Matplotlib not installed. Install with: pip install matplotlib")

        self.color_scheme = color_scheme or {
            "primary": "#8B5CF6",
            "secondary": "#3B82F6",
            "accent": "#10B981",
            "danger": "#EF4444",
            "warning": "#F59E0B",
            "success": "#22C55E"
        }

        # Configuration matplotlib
        plt.style.use('seaborn-v0_8-darkgrid')
        plt.rcParams['font.family'] = 'sans-serif'
        plt.rcParams['font.sans-serif'] = ['DejaVu Sans', 'Arial']
        plt.rcParams['font.size'] = 10

    def generate_radar_chart(
        self,
        labels: List[str],
        datasets: Dict[str, List[float]],
        title: str = "Radar Chart",
        width: int = 800,
        height: int = 600
    ) -> bytes:
        """
        Génère un graphique radar (spider chart).

        Args:
            labels: Labels des axes (ex: domaines)
            datasets: Dict {serie_name: values}
            title: Titre du graphique
            width: Largeur en pixels
            height: Hauteur en pixels

        Returns:
            Bytes de l'image PNG
        """
        logger.info(f"Génération radar chart: {title}")

        num_vars = len(labels)
        angles = np.linspace(0, 2 * np.pi, num_vars, endpoint=False).tolist()

        # Fermer le cercle
        angles += angles[:1]

        # Créer la figure
        fig, ax = plt.subplots(
            figsize=(width/100, height/100),
            subplot_kw=dict(projection='polar')
        )

        # Couleurs pour chaque série
        colors = [
            self.color_scheme["primary"],
            self.color_scheme["secondary"],
            self.color_scheme["accent"]
        ]

        # Tracer chaque série
        for i, (name, values) in enumerate(datasets.items()):
            values_closed = values + values[:1]
            ax.plot(angles, values_closed, 'o-', linewidth=2,
                   label=name, color=colors[i % len(colors)])
            ax.fill(angles, values_closed, alpha=0.15, color=colors[i % len(colors)])

        # Configuration des axes
        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(labels, size=9)
        ax.set_ylim(0, 100)
        ax.set_yticks([20, 40, 60, 80, 100])
        ax.set_yticklabels(['20', '40', '60', '80', '100'], size=8, color='gray')
        ax.grid(True, linestyle='--', alpha=0.3)

        # Titre et légende
        ax.set_title(title, size=14, weight='bold', pad=20)
        ax.legend(loc='upper right', bbox_to_anchor=(1.3, 1.1))

        # Convertir en bytes
        buf = BytesIO()
        plt.tight_layout()
        plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        plt.close(fig)

        buf.seek(0)
        img_bytes = buf.read()

        logger.info(f"Radar chart généré ({len(img_bytes)} bytes)")
        return img_bytes

    def generate_bar_chart(
        self,
        categories: List[str],
        values: List[float],
        title: str = "Bar Chart",
        xlabel: str = "",
        ylabel: str = "Score",
        width: int = 800,
        height: int = 500
    ) -> bytes:
        """
        Génère un graphique à barres.

        Args:
            categories: Catégories (axe X)
            values: Valeurs (axe Y)
            title: Titre du graphique
            xlabel: Label axe X
            ylabel: Label axe Y
            width: Largeur
            height: Hauteur

        Returns:
            Bytes PNG
        """
        logger.info(f"Génération bar chart: {title}")

        fig, ax = plt.subplots(figsize=(width/100, height/100))

        # Couleurs selon les valeurs
        colors = []
        for val in values:
            if val >= 80:
                colors.append(self.color_scheme["success"])
            elif val >= 60:
                colors.append(self.color_scheme["warning"])
            else:
                colors.append(self.color_scheme["danger"])

        # Créer les barres
        bars = ax.bar(categories, values, color=colors, alpha=0.8, edgecolor='black', linewidth=0.5)

        # Ajouter les valeurs sur les barres
        for bar in bars:
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height,
                   f'{height:.1f}',
                   ha='center', va='bottom', fontsize=9, weight='bold')

        # Configuration
        ax.set_title(title, fontsize=14, weight='bold', pad=15)
        ax.set_xlabel(xlabel, fontsize=11)
        ax.set_ylabel(ylabel, fontsize=11)
        ax.set_ylim(0, 105)
        ax.grid(axis='y', linestyle='--', alpha=0.3)

        # Rotation labels si nécessaire
        if len(max(categories, key=len)) > 10:
            plt.xticks(rotation=45, ha='right')

        # Convertir en bytes
        buf = BytesIO()
        plt.tight_layout()
        plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        plt.close(fig)

        buf.seek(0)
        img_bytes = buf.read()

        logger.info(f"Bar chart généré ({len(img_bytes)} bytes)")
        return img_bytes

    def generate_pie_chart(
        self,
        labels: List[str],
        values: List[float],
        title: str = "Pie Chart",
        width: int = 700,
        height: int = 500
    ) -> bytes:
        """
        Génère un graphique en camembert.

        Args:
            labels: Labels des parts
            values: Valeurs
            title: Titre
            width: Largeur
            height: Hauteur

        Returns:
            Bytes PNG
        """
        logger.info(f"Génération pie chart: {title}")

        fig, ax = plt.subplots(figsize=(width/100, height/100))

        # Couleurs automatiques
        colors = [
            self.color_scheme["primary"],
            self.color_scheme["secondary"],
            self.color_scheme["accent"],
            self.color_scheme["success"],
            self.color_scheme["warning"],
            self.color_scheme["danger"]
        ]

        # Créer le camembert
        wedges, texts, autotexts = ax.pie(
            values,
            labels=labels,
            colors=colors[:len(labels)],
            autopct='%1.1f%%',
            startangle=90,
            pctdistance=0.85,
            textprops={'fontsize': 10}
        )

        # Style des pourcentages
        for autotext in autotexts:
            autotext.set_color('white')
            autotext.set_weight('bold')

        # Titre
        ax.set_title(title, fontsize=14, weight='bold', pad=15)

        # Convertir en bytes
        buf = BytesIO()
        plt.tight_layout()
        plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        plt.close(fig)

        buf.seek(0)
        img_bytes = buf.read()

        logger.info(f"Pie chart généré ({len(img_bytes)} bytes)")
        return img_bytes

    def generate_gauge(
        self,
        value: float,
        min_val: float = 0,
        max_val: float = 100,
        title: str = "Gauge",
        thresholds: Optional[List[Dict[str, Any]]] = None,
        width: int = 600,
        height: int = 400
    ) -> bytes:
        """
        Génère une jauge (gauge/speedometer).

        Args:
            value: Valeur actuelle
            min_val: Valeur minimale
            max_val: Valeur maximale
            title: Titre
            thresholds: Seuils [{value, color, label}]
            width: Largeur
            height: Hauteur

        Returns:
            Bytes PNG
        """
        logger.info(f"Génération gauge: {title} = {value}")

        fig, ax = plt.subplots(figsize=(width/100, height/100), subplot_kw={'projection': 'polar'})

        # Définir thresholds par défaut
        if not thresholds:
            thresholds = [
                {"value": 40, "color": self.color_scheme["danger"], "label": "Faible"},
                {"value": 70, "color": self.color_scheme["warning"], "label": "Moyen"},
                {"value": 100, "color": self.color_scheme["success"], "label": "Bon"}
            ]

        # Calculer l'angle (demi-cercle)
        angle_range = np.pi  # 180 degrés
        angle = (value - min_val) / (max_val - min_val) * angle_range

        # Dessiner les zones de seuils
        prev_val = min_val
        for threshold in sorted(thresholds, key=lambda t: t["value"]):
            theta = np.linspace(
                (prev_val - min_val) / (max_val - min_val) * angle_range + np.pi,
                (threshold["value"] - min_val) / (max_val - min_val) * angle_range + np.pi,
                100
            )
            ax.fill_between(theta, 0, 1, alpha=0.3, color=threshold["color"])
            prev_val = threshold["value"]

        # Aiguille
        ax.arrow(
            angle + np.pi, 0, 0, 0.8,
            width=0.02, head_width=0.1, head_length=0.1,
            fc='black', ec='black', linewidth=2
        )

        # Configuration
        ax.set_ylim(0, 1)
        ax.set_theta_offset(np.pi)
        ax.set_theta_direction(-1)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.spines['polar'].set_visible(False)
        ax.grid(False)

        # Titre et valeur
        ax.text(0, -0.3, title, ha='center', va='center', fontsize=12, weight='bold',
               transform=ax.transAxes)
        ax.text(0, -0.5, f'{value:.1f}', ha='center', va='center', fontsize=24, weight='bold',
               transform=ax.transAxes)

        # Convertir en bytes
        buf = BytesIO()
        plt.tight_layout()
        plt.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor='white')
        plt.close(fig)

        buf.seek(0)
        img_bytes = buf.read()

        logger.info(f"Gauge généré ({len(img_bytes)} bytes)")
        return img_bytes

    def generate_comparison_chart(
        self,
        categories: List[str],
        datasets: Dict[str, List[float]],
        title: str = "Comparison Chart",
        ylabel: str = "Score",
        width: int = 900,
        height: int = 500
    ) -> bytes:
        """
        Génère un graphique de comparaison (barres groupées).

        Args:
            categories: Catégories (axe X)
            datasets: {serie_name: values}
            title: Titre
            ylabel: Label Y
            width: Largeur
            height: Hauteur

        Returns:
            Bytes PNG
        """
        logger.info(f"Génération comparison chart: {title}")

        fig, ax = plt.subplots(figsize=(width/100, height/100))

        x = np.arange(len(categories))
        width_bar = 0.8 / len(datasets)

        colors = [
            self.color_scheme["primary"],
            self.color_scheme["secondary"],
            self.color_scheme["accent"]
        ]

        # Tracer chaque série
        for i, (name, values) in enumerate(datasets.items()):
            offset = (i - len(datasets)/2 + 0.5) * width_bar
            ax.bar(x + offset, values, width_bar, label=name,
                  color=colors[i % len(colors)], alpha=0.8)

        # Configuration
        ax.set_title(title, fontsize=14, weight='bold', pad=15)
        ax.set_ylabel(ylabel, fontsize=11)
        ax.set_xticks(x)
        ax.set_xticklabels(categories)
        ax.set_ylim(0, 105)
        ax.legend()
        ax.grid(axis='y', linestyle='--', alpha=0.3)

        if len(max(categories, key=len)) > 10:
            plt.xticks(rotation=45, ha='right')

        # Convertir en bytes
        buf = BytesIO()
        plt.tight_layout()
        plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        plt.close(fig)

        buf.seek(0)
        img_bytes = buf.read()

        logger.info(f"Comparison chart généré ({len(img_bytes)} bytes)")
        return img_bytes

    def chart_to_base64(self, img_bytes: bytes) -> str:
        """
        Convertit une image en base64 pour embedding HTML.

        Args:
            img_bytes: Bytes de l'image

        Returns:
            String base64 (data:image/png;base64,...)
        """
        b64 = base64.b64encode(img_bytes).decode('utf-8')
        return f"data:image/png;base64,{b64}"


def generate_chart_from_config(
    chart_type: str,
    data: Dict[str, Any],
    config: Dict[str, Any],
    color_scheme: Optional[Dict[str, str]] = None
) -> bytes:
    """
    Génère un graphique à partir d'une configuration.

    Args:
        chart_type: Type de graphique (radar, bar, pie, gauge)
        data: Données du graphique
        config: Configuration du widget
        color_scheme: Palette de couleurs

    Returns:
        Bytes de l'image PNG
    """
    generator = ChartGenerator(color_scheme)

    if chart_type == "radar_domains":
        return generator.generate_radar_chart(
            labels=data.get("labels", []),
            datasets=data.get("datasets", {}),
            title=config.get("title", "Radar Chart")
        )

    elif chart_type == "bar_chart":
        return generator.generate_bar_chart(
            categories=data.get("categories", []),
            values=data.get("values", []),
            title=config.get("title", "Bar Chart"),
            ylabel=config.get("ylabel", "Score")
        )

    elif chart_type == "pie_chart":
        return generator.generate_pie_chart(
            labels=data.get("labels", []),
            values=data.get("values", []),
            title=config.get("title", "Pie Chart")
        )

    elif chart_type == "gauge":
        return generator.generate_gauge(
            value=data.get("value", 0),
            title=config.get("title", "Gauge"),
            thresholds=config.get("thresholds")
        )

    elif chart_type == "comparison_chart":
        return generator.generate_comparison_chart(
            categories=data.get("categories", []),
            datasets=data.get("datasets", {}),
            title=config.get("title", "Comparison")
        )

    else:
        raise ValueError(f"Chart type not supported: {chart_type}")
