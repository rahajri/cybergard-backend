"""
Service de rendu des widgets en HTML.

Transforme la configuration JSON des widgets en HTML formaté
prêt pour la conversion PDF via WeasyPrint.
"""

from typing import Dict, Any, List, Optional
from jinja2 import Environment, Template
from datetime import datetime
import logging
import re

logger = logging.getLogger(__name__)


class WidgetRenderer:
    """Renderer pour transformer widgets en HTML."""

    def __init__(self, color_scheme: Dict[str, str], fonts: Dict[str, Dict[str, Any]]):
        """
        Initialise le renderer avec le thème du template.

        Args:
            color_scheme: Palette de couleurs
            fonts: Configuration des polices
        """
        self.color_scheme = color_scheme
        self.fonts = fonts
        self.env = Environment()

    # ========================================================================
    # WIDGETS DE STRUCTURE
    # ========================================================================

    def render_cover(self, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """
        Rendu de la page de garde avec logo client.

        Args:
            config: Configuration du widget
            data: Données du rapport

        Returns:
            HTML de la page de garde
        """
        # Debug: Afficher les clés disponibles dans data pour le debug
        logger.info(f"🔍 render_cover: data keys={list(data.keys())}")
        if 'campaign' in data:
            logger.info(f"🔍 render_cover: campaign keys={list(data['campaign'].keys()) if isinstance(data['campaign'], dict) else 'NOT_DICT'}")
            logger.info(f"🔍 render_cover: campaign.name='{data['campaign'].get('name', 'MISSING')}'")

        title = self._resolve_variable(config.get("title", ""), data)
        subtitle = self._resolve_variable(config.get("subtitle", ""), data)

        logger.info(f"🔍 render_cover: config.title='{config.get('title', '')}' -> resolved='{title}'")

        # Résoudre la date - si %report.date% utilisé, le remplacer par la date actuelle
        date_config = config.get("date", "")
        if "%report.date%" in date_config:
            from datetime import datetime
            date = date_config.replace("%report.date%", datetime.now().strftime('%d/%m/%Y'))
        else:
            date = self._resolve_variable(date_config, data)

        confidentiality = config.get("confidentiality", "")

        # Récupérer le logo selon la configuration
        logo_source = config.get("logo_source", "tenant")  # tenant, organization, entity, none
        logos = data.get("logos", {})

        logger.info(f"🖼️ render_cover: logo_source='{logo_source}', logos keys={list(logos.keys())}")

        logo_url = None
        if logo_source == "tenant":
            logo_url = logos.get("tenant_logo_url")
        elif logo_source == "organization":
            logo_url = logos.get("organization_logo_url")
        elif logo_source == "entity":
            logo_url = logos.get("entity_logo_url")
        # Fallback: essayer custom_logo si le logo demandé n'existe pas
        if not logo_url:
            logo_url = logos.get("custom_logo") or logos.get("tenant_logo_url")
            logger.info(f"🖼️ render_cover: fallback logo_url={'présent' if logo_url else 'absent'}")

        if logo_url:
            logger.info(f"🖼️ render_cover: logo_url trouvé ({len(logo_url)} chars)")
        else:
            logger.warning(f"🖼️ render_cover: AUCUN logo trouvé!")

        # HTML du logo (supporte PNG/SVG avec transparence)
        if logo_url:
            # Déterminer si c'est un SVG pour adapter le style
            is_svg = logo_url.lower().endswith('.svg') or 'image/svg' in logo_url.lower()
            logo_html = f'''
                <img src="{logo_url}" alt="Logo"
                     style="
                         max-width: 200px;
                         max-height: 100px;
                         object-fit: contain;
                         background: transparent;
                     "/>
            '''
        else:
            # Placeholder si pas de logo (fond semi-transparent pour cover)
            # Compatible xhtml2pdf (pas de flexbox)
            logo_html = f'''
                <div style="
                    width: 200px;
                    height: 80px;
                    margin: 0 auto;
                    background-color: rgba(255,255,255,0.15);
                    text-align: center;
                    line-height: 80px;
                    font-size: 14px;
                    color: rgba(255,255,255,0.7);
                    border: 1px dashed rgba(255,255,255,0.3);
                ">Logo Client</div>
            '''

        # Récupérer la couleur du titre depuis color_scheme ou config (blanc par défaut)
        title_color = self.color_scheme.get('title_color') or config.get('title_color', '#FFFFFF')
        primary_color = self.color_scheme.get('primary', '#dc2626')

        # HTML compatible xhtml2pdf (pas de flexbox, pas de linear-gradient)
        # Utiliser des tables pour le centrage et background-color solide
        html = f"""
        <div class="cover-page" style="
            page-break-after: always;
            background-color: {primary_color};
            padding: 0;
            margin: 0;
        ">
            <table width="100%" height="500" cellpadding="0" cellspacing="0" border="0" style="
                background-color: {primary_color};
            ">
                <tr>
                    <td align="center" valign="middle" style="
                        padding: 40px 30px;
                        text-align: center;
                    ">
                        <!-- Logo -->
                        <div style="margin-bottom: 30px;">
                            {logo_html}
                        </div>

                        <!-- Titre principal -->
                        <h1 style="
                            font-family: {self.fonts['title']['family']};
                            font-size: {self.fonts['title']['size'] + 8}px;
                            font-weight: {self.fonts['title']['weight']};
                            color: {title_color};
                            margin: 20px 0;
                        ">{title}</h1>

                        <!-- Sous-titre -->
                        <h2 style="
                            font-family: {self.fonts['heading1']['family']};
                            font-size: {self.fonts['heading1']['size']}px;
                            font-weight: normal;
                            color: {title_color};
                            margin: 10px 0;
                        ">{subtitle}</h2>

                        <!-- Date -->
                        <p style="
                            font-family: {self.fonts['body']['family']};
                            font-size: {self.fonts['body']['size']}px;
                            color: {title_color};
                            margin: 30px 0 10px 0;
                        ">{date}</p>

                        <!-- Confidentialité -->
                        {f'<p style="font-size: {self.fonts["body"]["size"] - 1}px; margin-top: 20px; color: {title_color};">{confidentiality}</p>' if confidentiality else ''}
                    </td>
                </tr>
            </table>
        </div>
        """
        return html

    def render_header(self, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """
        Rendu de l'en-tête de page avec logo, titre et métadonnées.

        Structure: [LOGO] | TITRE DU RAPPORT | [Référentiel / Date / Page X/Y]
        """
        # Texte simple (ancien format) ou nouveau format structuré
        title = self._resolve_variable(config.get("title", config.get("text", "")), data)
        framework = self._resolve_variable(config.get("framework", ""), data)
        show_logo = config.get("show_logo", True)
        show_date = config.get("show_date", True)
        show_page_number = config.get("show_page_number", True)

        # Récupérer le logo
        logo_source = config.get("logo_source", "tenant")
        logos = data.get("logos", {})

        logo_url = None
        if show_logo:
            if logo_source == "tenant":
                logo_url = logos.get("tenant_logo_url")
            elif logo_source == "organization":
                logo_url = logos.get("organization_logo_url")
            elif logo_source == "entity":
                logo_url = logos.get("entity_logo_url")

        # HTML du logo (supporte PNG/SVG avec transparence)
        if logo_url:
            logo_html = f'''
                <img src="{logo_url}" alt="Logo"
                     style="
                         max-height: 40px;
                         max-width: 100px;
                         object-fit: contain;
                         background: transparent;
                     "/>
            '''
        elif show_logo:
            # Compatible xhtml2pdf (pas de flexbox)
            logo_html = f'''
                <div style="
                    width: 60px;
                    height: 40px;
                    background-color: {self.color_scheme['primary']}15;
                    text-align: center;
                    line-height: 40px;
                    font-size: 8px;
                    color: {self.color_scheme['primary']};
                    border: 1px dashed {self.color_scheme['primary']}40;
                ">LOGO</div>
            '''
        else:
            logo_html = ""

        # Date actuelle
        current_date = datetime.now().strftime('%d/%m/%Y')

        # Métadonnées (droite)
        meta_items = []
        if framework:
            meta_items.append(framework)
        if show_date:
            meta_items.append(current_date)
        if show_page_number:
            meta_items.append("Page <span class='page-number'></span>")

        meta_html = "<br>".join(meta_items)

        # HTML compatible xhtml2pdf (table au lieu de flexbox)
        html = f"""
        <div class="page-header" style="
            border-bottom: 2px solid {self.color_scheme['primary']};
            padding-bottom: 10px;
            margin-bottom: 20px;
        ">
            <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                    <!-- Logo à gauche -->
                    <td width="15%" valign="middle">
                        {logo_html}
                    </td>

                    <!-- Titre au centre -->
                    <td width="70%" valign="middle" style="text-align: center; padding: 0 15px;">
                        <p style="
                            font-family: {self.fonts['heading1']['family']};
                            font-size: {self.fonts['heading1']['size'] - 2}px;
                            font-weight: bold;
                            color: {self.color_scheme['text']};
                            margin: 0;
                        ">{title}</p>
                    </td>

                    <!-- Métadonnées à droite -->
                    <td width="15%" valign="middle" style="text-align: right;">
                        <p style="
                            font-family: {self.fonts['body']['family']};
                            font-size: {self.fonts['body']['size'] - 2}px;
                            color: #6B7280;
                            margin: 0;
                            line-height: 1.4;
                        ">{meta_html}</p>
                    </td>
                </tr>
            </table>
        </div>
        """
        return html

    def render_footer(self, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """Rendu du pied de page."""
        text = self._resolve_variable(config.get("text", ""), data)

        html = f"""
        <div class="page-footer" style="
            border-top: 1px solid {self.color_scheme['primary']};
            padding-top: 10px;
            margin-top: 20px;
            text-align: center;
        ">
            <p style="
                font-family: {self.fonts['body']['family']};
                font-size: {self.fonts['body']['size'] - 1}px;
                color: #6B7280;
                margin: 0;
            ">{text}</p>
        </div>
        """
        return html

    def render_toc(self, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """
        Rendu de la table des matières.

        Génère automatiquement la TOC à partir de la structure du template
        en extrayant les widgets de type 'section', 'title', et les widgets
        avec des titres configurés.
        """
        title = config.get("title", "Sommaire")
        depth = config.get("depth", 2)

        # Récupérer la structure du template passée dans data
        structure = data.get('_template_structure', [])

        # Extraire les sections pour la TOC
        toc_entries = []
        section_number = 0

        for widget in sorted(structure, key=lambda w: w.get('position', 0)):
            widget_type = widget.get('widget_type', '')
            widget_config = widget.get('config', {})

            # Ignorer les widgets de structure (cover, toc, page_break)
            if widget_type in ['cover', 'toc', 'page_break', 'footer', 'header']:
                continue

            # Extraire le titre selon le type de widget
            entry_title = None
            level = 1

            if widget_type == 'section':
                entry_title = widget_config.get('title', '')
                level = 1
                section_number += 1
            elif widget_type == 'title':
                entry_title = widget_config.get('text', '')
                level = widget_config.get('level', 1)
            elif widget_type in ['ai_summary', 'summary']:
                entry_title = widget_config.get('title', 'Synthèse')
                level = 1
                section_number += 1
            else:
                # Pour les autres widgets, utiliser le titre s'il existe
                entry_title = widget_config.get('title', '')
                if entry_title:
                    level = 2  # Sous-section

            # Résoudre les variables dans le titre
            if entry_title:
                entry_title = self._resolve_variable(entry_title, data)

                # Ne pas ajouter si le titre est vide après résolution
                if entry_title.strip():
                    # Limiter selon la profondeur configurée
                    if level <= depth:
                        toc_entries.append({
                            'title': entry_title,
                            'level': level,
                            'number': section_number if level == 1 else None
                        })

        # Générer le HTML de la TOC
        html = f"""
        <div class="toc" style="page-break-after: always;">
            <h1 style="
                font-family: {self.fonts['heading1']['family']};
                font-size: {self.fonts['heading1']['size']}px;
                color: {self.color_scheme['text']};
                margin-bottom: 30px;
                border-bottom: 3px solid {self.color_scheme['primary']};
                padding-bottom: 10px;
            ">{title}</h1>

            <div class="toc-entries" style="margin-top: 20px;">
        """

        if toc_entries:
            for entry in toc_entries:
                indent = (entry['level'] - 1) * 20
                font_size = self.fonts['body']['size'] + (2 if entry['level'] == 1 else 0)
                font_weight = 'bold' if entry['level'] == 1 else 'normal'
                number_prefix = f"{entry['number']}. " if entry['number'] else "• "

                html += f"""
                <div style="
                    margin-left: {indent}px;
                    padding: 8px 0;
                    border-bottom: 1px dotted #E5E7EB;
                    font-family: {self.fonts['body']['family']};
                    font-size: {font_size}px;
                    font-weight: {font_weight};
                    color: {self.color_scheme['text']};
                ">
                    <span style="color: {self.color_scheme['primary']};">{number_prefix}</span>
                    {entry['title']}
                </div>
                """
        else:
            # Fallback si aucune entrée trouvée
            html += f"""
                <p style="font-style: italic; color: #6B7280;">
                    Aucune section définie dans ce rapport.
                </p>
            """

        html += """
            </div>
        </div>
        """
        return html

    def render_page_break(self, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """Rendu d'un saut de page."""
        return '<div style="page-break-after: always;"></div>\n'

    # ========================================================================
    # WIDGETS DE TEXTE
    # ========================================================================

    def render_title(self, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """Rendu d'un titre."""
        text = self._resolve_variable(config.get("text", ""), data)
        level = config.get("level", 1)

        font_key = f"heading{level}" if level > 1 else "title"
        font = self.fonts.get(font_key, self.fonts["heading1"])

        html = f"""
        <h{level} style="
            font-family: {font['family']};
            font-size: {font['size']}px;
            font-weight: {font['weight']};
            color: {self.color_scheme['text']};
            margin: 25px 0 15px 0;
            border-bottom: 2px solid {self.color_scheme['primary']};
            padding-bottom: 8px;
        ">{text}</h{level}>
        """
        return html

    def render_paragraph(self, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """Rendu d'un paragraphe."""
        text = self._resolve_variable(config.get("text", ""), data)

        html = f"""
        <p style="
            font-family: {self.fonts['body']['family']};
            font-size: {self.fonts['body']['size']}px;
            color: {self.color_scheme['text']};
            line-height: 1.6;
            margin: 12px 0;
        ">{text}</p>
        """
        return html

    def render_description(self, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """Rendu d'une description (paragraphe formaté)."""
        text = self._resolve_variable(config.get("text", ""), data)

        html = f"""
        <div class="description" style="
            background-color: #F9FAFB;
            border-left: 4px solid {self.color_scheme['accent']};
            padding: 15px;
            margin: 15px 0;
            border-radius: 4px;
        ">
            <p style="
                font-family: {self.fonts['body']['family']};
                font-size: {self.fonts['body']['size']}px;
                color: {self.color_scheme['text']};
                margin: 0;
                line-height: 1.6;
            ">{text}</p>
        </div>
        """
        return html

    # ========================================================================
    # WIDGETS DE MÉTRIQUES
    # ========================================================================

    def render_metrics(self, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """Rendu des métriques clés."""
        metrics = config.get("metrics", [])

        # HTML compatible xhtml2pdf (inline-block au lieu de flex)
        html = '<div class="metrics" style="margin: 20px 0;">\n'

        for metric in metrics:
            label = metric.get("label", "")
            raw_value = self._resolve_variable(metric.get("value", ""), data)
            metric_type = metric.get("type", "count")
            suffix = metric.get("suffix", "")

            # Nettoyer la valeur si c'est un nombre
            try:
                if isinstance(raw_value, (int, float)):
                    value = raw_value
                else:
                    cleaned = str(raw_value).replace('%', '').replace(',', '.').strip()
                    value = float(cleaned) if cleaned and not cleaned.startswith('%') else raw_value
            except (ValueError, TypeError):
                value = raw_value

            # Formatter la valeur selon le type ou suffix
            if suffix:
                formatted_value = f"{value}{suffix}"
            elif metric_type == "percentage":
                formatted_value = f"{value}%"
            elif metric_type == "score":
                formatted_value = f"{value}/100"
            else:
                formatted_value = str(value)

            html += f"""
            <div class="metric-card" style="
                display: inline-block;
                width: 22%;
                margin-right: 2%;
                margin-bottom: 10px;
                background-color: {self.color_scheme['primary']};
                color: white;
                padding: 20px;
                text-align: center;
                vertical-align: top;
            ">
                <div style="
                    font-size: 32px;
                    font-weight: bold;
                    margin-bottom: 8px;
                ">{formatted_value}</div>
                <div style="
                    font-size: {self.fonts['body']['size']}px;
                ">{label}</div>
            </div>
            """

        html += '</div>\n'
        return html

    def render_gauge(self, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """Rendu d'une jauge de score."""
        title = config.get("title", "Score")

        # Résoudre et convertir la valeur en float avec gestion d'erreur
        try:
            resolved_value = self._resolve_variable(config.get("value", "0"), data)
            # Nettoyer la valeur (enlever %, espaces, etc.)
            cleaned = str(resolved_value).replace('%', '').replace(',', '.').strip()
            value = float(cleaned) if cleaned and cleaned.replace('.','').replace('-','').isdigit() else 0
        except (ValueError, TypeError):
            value = 0
            logger.warning(f"Gauge: impossible de convertir la valeur '{config.get('value')}'")

        min_val = config.get("min", 0)
        max_val = config.get("max", 100)
        thresholds = config.get("thresholds", [])

        # Déterminer la couleur selon les seuils
        color = self.color_scheme["success"]
        for threshold in sorted(thresholds, key=lambda t: t["value"]):
            if value < threshold["value"]:
                color = threshold.get("color", color)
                break

        percentage = ((value - min_val) / (max_val - min_val)) * 100

        # HTML compatible xhtml2pdf (tables au lieu de position absolute)
        # Note: xhtml2pdf ne supporte pas bien les SVG complexes, on utilise une barre simple
        html = f"""
        <div class="gauge" style="margin: 30px 0; text-align: center;">
            <h3 style="
                font-family: {self.fonts['heading2']['family']};
                font-size: {self.fonts['heading2']['size']}px;
                color: {self.color_scheme['text']};
                margin-bottom: 20px;
            ">{title}</h3>

            <table width="400" cellpadding="0" cellspacing="0" border="0" align="center">
                <tr>
                    <td align="center" style="padding-bottom: 15px;">
                        <div style="font-size: 48px; font-weight: bold; color: {color};">{value:.1f}%</div>
                    </td>
                </tr>
                <tr>
                    <td align="center">
                        <!-- Barre de progression -->
                        <table width="300" cellpadding="0" cellspacing="0" border="0" style="border: 1px solid #E5E7EB;">
                            <tr>
                                <td width="{percentage}%" style="background-color: {color}; height: 20px;"></td>
                                <td width="{100 - percentage}%" style="background-color: #E5E7EB; height: 20px;"></td>
                            </tr>
                        </table>
                    </td>
                </tr>
                <tr>
                    <td align="center" style="padding-top: 10px;">
                        <table width="300" cellpadding="0" cellspacing="0" border="0">
                            <tr>
                                <td align="left" style="font-size: 12px; color: #6B7280;">{min_val}</td>
                                <td align="right" style="font-size: 12px; color: #6B7280;">{max_val}</td>
                            </tr>
                        </table>
                    </td>
                </tr>
            </table>
        </div>
        """
        return html

    # ========================================================================
    # WIDGETS GRAPHIQUES (Placeholder - sera implémenté avec matplotlib)
    # ========================================================================

    def render_radar_domains(self, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """
        Rendu d'un radar par domaine avec graphique matplotlib.

        Args:
            config: Configuration du widget (title, max_domains, etc.)
            data: Données contenant 'domains' ou 'domain_scores'
        """
        from .chart_generator import ChartGenerator
        import base64

        title = config.get("title", "Scores par Domaine")
        max_domains = config.get("max_domains", 10)

        # Récupérer les données des domaines
        domains = data.get("domains", data.get("domain_scores", []))

        if not domains:
            return self._render_chart_placeholder("Radar Domaines", "📊 Aucune donnée disponible")

        # Limiter le nombre de domaines pour lisibilité
        domains = domains[:max_domains]

        # Préparer les données pour le radar
        labels = []
        scores = []

        for domain in domains:
            # Tronquer les noms longs
            name = domain.get("name", domain.get("code", "?"))
            if len(name) > 20:
                name = name[:17] + "..."
            labels.append(name)
            scores.append(domain.get("score", 0))

        if not labels:
            return self._render_chart_placeholder("Radar Domaines", "📊 Aucun domaine")

        try:
            # Générer le graphique
            chart_gen = ChartGenerator(self.color_scheme)
            datasets = {"Score": scores}

            img_bytes = chart_gen.generate_radar_chart(
                labels=labels,
                datasets=datasets,
                title="",  # Titre géré en HTML
                width=600,
                height=500
            )

            # Convertir en base64
            img_b64 = base64.b64encode(img_bytes).decode('utf-8')

            html = f"""
            <div class="chart-radar" style="margin: 30px 0; text-align: center;">
                <h3 style="
                    font-family: {self.fonts['heading2']['family']};
                    font-size: {self.fonts['heading2']['size']}px;
                    color: {self.color_scheme['text']};
                    margin-bottom: 20px;
                ">{title}</h3>

                <img src="data:image/png;base64,{img_b64}"
                     alt="{title}"
                     style="max-width: 100%; height: auto;"/>
            </div>
            """
            return html

        except Exception as e:
            logger.error(f"Erreur génération radar: {e}")
            return self._render_chart_placeholder("Radar Domaines", f"📊 Erreur: {str(e)[:50]}")

    def render_bar_chart(self, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """Rendu d'un graphique à barres."""
        return self._render_chart_placeholder("Graphique à Barres", "📊")

    def render_pie_chart(self, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """Rendu d'un camembert."""
        return self._render_chart_placeholder("Camembert", "🥧")

    # ========================================================================
    # WIDGETS TABLES
    # ========================================================================

    def render_actions_table(self, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """Rendu du tableau des actions."""
        actions = data.get("actions", [])
        limit = config.get("limit", None)
        priority_filter = config.get("priority_filter", None)
        columns = config.get("columns", ["title", "severity", "priority", "due_days"])

        # Filtrer et limiter
        if priority_filter:
            actions = [a for a in actions if a.get("priority") in priority_filter]

        if limit:
            actions = actions[:limit]

        html = """
        <div class="table-container" style="margin: 20px 0; overflow-x: auto;">
            <table style="
                width: 100%;
                border-collapse: collapse;
                font-family: {font};
                font-size: {size}px;
            ">
                <thead>
                    <tr style="background-color: {header_bg}; color: white;">
        """.format(
            font=self.fonts['body']['family'],
            size=self.fonts['body']['size'],
            header_bg=self.color_scheme['primary']
        )

        # En-têtes
        column_labels = {
            "title": "Action",
            "severity": "Sévérité",
            "priority": "Priorité",
            "due_days": "Délai (jours)",
            "suggested_role": "Rôle"
        }

        for col in columns:
            html += f'<th style="padding: 12px; text-align: left;">{column_labels.get(col, col)}</th>\n'

        html += """
                    </tr>
                </thead>
                <tbody>
        """

        # Lignes
        for i, action in enumerate(actions):
            bg_color = "#F9FAFB" if i % 2 == 0 else "white"
            html += f'<tr style="background-color: {bg_color};">\n'

            for col in columns:
                value = action.get(col, "-")

                # Formatage spécial pour sévérité et priorité
                if col == "severity":
                    severity_colors = {
                        "critical": self.color_scheme["danger"],
                        "major": self.color_scheme["warning"],
                        "minor": self.color_scheme["success"]
                    }
                    color = severity_colors.get(value, "#6B7280")
                    value = f'<span style="color: {color}; font-weight: bold;">●</span> {value.upper()}'
                elif col == "priority":
                    value = f'<strong>{value}</strong>'

                html += f'<td style="padding: 10px;">{value}</td>\n'

            html += '</tr>\n'

        html += """
                </tbody>
            </table>
        </div>
        """

        return html

    def render_nc_table(self, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """Rendu du tableau des non-conformités."""
        # Support des deux formats: nc_major/nc_minor OU nc_list
        nc_list = data.get("nc_list", [])
        nc_major = data.get("nc_major", [])
        nc_minor = data.get("nc_minor", [])
        severity = config.get("severity", "all")  # Par défaut: all
        limit = config.get("limit", None)

        # Si nc_list existe (format collect_entity_data), l'utiliser
        if nc_list:
            if severity == "major":
                ncs = [nc for nc in nc_list if nc.get('severity_class') == 'critical' or nc.get('severity') == 'CRITIQUE']
            elif severity == "minor":
                ncs = [nc for nc in nc_list if nc.get('severity_class') == 'minor' or nc.get('severity') == 'MINEURE']
            else:  # all
                ncs = nc_list
        else:
            # Sinon utiliser nc_major/nc_minor (format collect_campaign_data)
            if severity == "major":
                ncs = nc_major
            elif severity == "minor":
                ncs = nc_minor
            else:  # all
                ncs = nc_major + nc_minor

        if limit:
            ncs = ncs[:limit]

        # Si aucune NC, afficher un message
        if not ncs:
            return f"""
            <div class="no-nc-message" style="
                margin: 20px 0;
                padding: 20px;
                background-color: #F0FDF4;
                border: 1px solid #22C55E;
                border-radius: 8px;
                text-align: center;
                color: #166534;
            ">
                <p style="margin: 0; font-size: {self.fonts['body']['size']}px;">
                    <span style="color: #22C55E; font-weight: bold; font-size: 16px;">&#10003;</span>
                    Aucune non-conformité identifiée
                </p>
            </div>
            """

        html = f"""
        <div class="table-container" style="margin: 20px 0;">
            <table style="
                width: 100%;
                border-collapse: collapse;
                font-family: {self.fonts['body']['family']};
                font-size: {self.fonts['body']['size']}px;
            ">
                <thead>
                    <tr style="background-color: {self.color_scheme['danger']}; color: white;">
                        <th style="padding: 12px; text-align: left;">Domaine</th>
                        <th style="padding: 12px; text-align: left;">Question</th>
                        <th style="padding: 12px; text-align: left;">Risque</th>
                        <th style="padding: 12px; text-align: left;">Commentaire</th>
                    </tr>
                </thead>
                <tbody>
        """

        for i, nc in enumerate(ncs):
            bg_color = "#FEF2F2" if i % 2 == 0 else "white"

            # Support des deux formats de données
            domain_name = nc.get('domain_name', '-')
            question_text = nc.get('question_text', '-') or '-'
            question_text = question_text[:100] + '...' if len(question_text) > 100 else question_text

            # Risque: utiliser severity (nc_list) ou risk_level (nc_major/minor)
            risk = nc.get('severity') or nc.get('risk_level') or '-'
            risk = str(risk).upper() if risk and risk != '-' else '-'

            # Commentaire
            comment = nc.get('comment') or '-'
            comment = comment[:80] + '...' if len(comment) > 80 else comment

            html += f"""
                <tr style="background-color: {bg_color};">
                    <td style="padding: 10px;">{domain_name}</td>
                    <td style="padding: 10px;">{question_text}</td>
                    <td style="padding: 10px;"><span style="color: {self.color_scheme['danger']}; font-weight: bold;">●</span> {risk}</td>
                    <td style="padding: 10px;">{comment}</td>
                </tr>
            """

        html += """
                </tbody>
            </table>
        </div>
        """

        return html

    def render_questions_table(self, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """Rendu du tableau des questions."""
        return self._render_chart_placeholder("Tableau Questions", "📋")

    # ========================================================================
    # WIDGETS IA ET AVANCÉS
    # ========================================================================

    def render_ai_summary(self, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """
        Rendu du résumé exécutif généré par IA ou manuellement.

        Priorité du contenu:
        1. ai_contents[widget_id] - Contenu généré/manuel stocké par le job processor
        2. manual_content dans config - Contenu saisi manuellement dans le template
        3. ai_summary dans data - Contenu pré-généré (ancien format)
        4. Placeholder si rien n'est disponible

        Options:
        - show_title: Si False, ne pas afficher le titre (utile si section précède)
        """
        title = config.get("title", "Résumé Exécutif")
        show_title = config.get("show_title", True)  # Par défaut on affiche le titre
        tone = config.get("tone", "executive")
        report_scope = config.get("report_scope", "consolidated")
        widget_id = config.get("id", "")  # ID du widget si présent

        # Debug logging
        logger.info(f"🎨 render_ai_summary: widget_id='{widget_id[:25] if widget_id else 'VIDE'}', title='{title}'")
        ai_contents = data.get("ai_contents", {})
        ai_summary_global = data.get("ai_summary", {})
        logger.info(f"🎨 render_ai_summary: ai_contents keys={list(ai_contents.keys())}")
        logger.info(f"🎨 render_ai_summary: ai_summary global présent={bool(ai_summary_global)}, text len={len(ai_summary_global.get('text', ''))}")

        summary_text = ""

        # Priorité 1: Contenu stocké par le job processor (nouveau système)
        if widget_id and widget_id in ai_contents:
            content_data = ai_contents[widget_id]
            summary_text = content_data.get("text", "")
            logger.info(f"✅ render_ai_summary: Contenu trouvé via widget_id ({len(summary_text)} chars)")
            # Utiliser le tone stocké si disponible
            if content_data.get("tone"):
                tone = content_data["tone"]
        else:
            logger.warning(f"⚠️ render_ai_summary: widget_id '{widget_id[:25] if widget_id else 'VIDE'}' NON trouvé dans ai_contents")

        # Priorité 2: Contenu manuel dans la config du widget (template)
        if not summary_text:
            manual_content = config.get("manual_content", "").strip()
            if manual_content:
                summary_text = manual_content
                logger.info(f"✅ render_ai_summary: Contenu manuel utilisé ({len(summary_text)} chars)")

        # Priorité 3: Ancien format - ai_summary global
        if not summary_text:
            ai_content = data.get("ai_summary", {})
            summary_text = ai_content.get("text", "")
            if summary_text:
                logger.info(f"✅ render_ai_summary: Contenu ai_summary global utilisé ({len(summary_text)} chars)")
            else:
                logger.warning(f"⚠️ render_ai_summary: ai_summary global VIDE également")

        # Priorité 4: Placeholder
        is_placeholder = False
        if not summary_text:
            is_placeholder = True
            summary_text = f"Le résumé exécutif sera généré par l'IA lors de la génération du rapport. Paramètres: Ton {tone}, Scope {report_scope}"

        # Style selon le ton - couleurs EBIOS (rouge/orange)
        tone_styles = {
            "executive": {"border_color": "#DC2626", "bg": "#FEF2F2", "accent": "#B91C1C"},
            "technical": {"border_color": "#EA580C", "bg": "#FFF7ED", "accent": "#C2410C"},
            "detailed": {"border_color": "#D97706", "bg": "#FFFBEB", "accent": "#B45309"},
        }
        style = tone_styles.get(tone, tone_styles["executive"])

        # Formater le texte IA en paragraphes HTML propres
        def format_ai_text(text: str) -> str:
            """Convertit le texte IA en HTML formaté avec paragraphes."""
            if not text or is_placeholder:
                return f'<p style="color: #6B7280; font-style: italic; margin: 0;">{text}</p>'

            # Nettoyer le texte
            text = text.strip()

            # Séparer en paragraphes (double saut de ligne ou simple saut)
            paragraphs = []
            for para in text.split('\n\n'):
                para = para.strip()
                if para:
                    # Si c'est une liste à puces
                    if para.startswith('- ') or para.startswith('• '):
                        items = [line.strip().lstrip('-•').strip() for line in para.split('\n') if line.strip()]
                        list_html = '<ul style="margin: 10px 0; padding-left: 20px;">'
                        for item in items:
                            list_html += f'<li style="margin: 5px 0; color: #374151;">{item}</li>'
                        list_html += '</ul>'
                        paragraphs.append(list_html)
                    # Si c'est une liste numérotée (vérifier longueur avant d'accéder à para[1])
                    elif len(para) > 1 and para[0].isdigit() and para[1] in '.):':
                        items = [line.strip() for line in para.split('\n') if line.strip()]
                        list_html = '<ol style="margin: 10px 0; padding-left: 20px;">'
                        for item in items:
                            # Enlever le numéro au début
                            clean_item = re.sub(r'^\d+[\.\)\:]\s*', '', item)
                            list_html += f'<li style="margin: 5px 0; color: #374151;">{clean_item}</li>'
                        list_html += '</ol>'
                        paragraphs.append(list_html)
                    else:
                        # Paragraphe normal - gérer les sauts de ligne simples
                        para_text = para.replace('\n', '<br>')
                        paragraphs.append(f'<p style="margin: 0 0 12px 0; color: #374151; text-align: justify;">{para_text}</p>')

            return ''.join(paragraphs) if paragraphs else f'<p style="margin: 0;">{text}</p>'

        formatted_content = format_ai_text(summary_text)

        # Générer le HTML du titre seulement si show_title est True
        title_html = ""
        if show_title:
            title_html = f"""
            <h3 style="
                font-family: {self.fonts['heading1']['family']};
                font-size: {self.fonts['heading1']['size']}px;
                font-weight: bold;
                color: {style['border_color']};
                margin: 0 0 15px 0;
                padding-bottom: 10px;
                border-bottom: 2px solid {style['border_color']}20;
            ">{title}</h3>
            """

        # HTML compatible xhtml2pdf (pas de linear-gradient, pas de box-shadow)
        html = f"""
        <div class="ai-summary" style="
            margin: 25px 0;
            padding: 25px;
            background-color: {style['bg']};
            border-left: 5px solid {style['border_color']};
        ">
            {title_html}
            <div style="
                font-family: {self.fonts['body']['family']};
                font-size: 11px;
                line-height: 1.7;
            ">{formatted_content}</div>
        </div>
        """
        return html

    def render_kpi(self, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """Rendu des cartes KPI."""
        title = config.get("title", "Indicateurs Clés")
        layout = config.get("layout", "grid")

        # Récupérer les données - supporter les deux formats (entity et consolidated)
        scores = data.get("scores", {})
        stats = data.get("stats", {})
        domain_scores = data.get("domain_scores", data.get("domains", []))

        # Score global: chercher dans plusieurs endroits possibles
        global_score = scores.get("global", 0)
        if global_score == 0:
            # Fallback: utiliser compliance_rate des stats
            global_score = stats.get("compliance_rate", 0)
        if global_score == 0:
            # Fallback: calculer depuis benchmarking
            benchmarking = data.get("benchmarking", {})
            global_score = benchmarking.get("entity_score", 0)

        # Nombre de domaines: compter la liste ou utiliser stats
        domains_count = len(domain_scores) if domain_scores else stats.get("total_domains", 0)

        # Questions
        questions_count = stats.get("total_questions", 0)

        # NC: calculer depuis nc_major_count + nc_minor_count ou nc_count
        nc_count = stats.get("nc_count", 0)
        if nc_count == 0:
            nc_count = stats.get("nc_major_count", 0) + stats.get("nc_minor_count", 0)

        # Entités (pour rapports consolidés)
        entities_count = stats.get("entities_count", 0)
        if entities_count == 0:
            global_stats = data.get("global_stats", {})
            entities_count = global_stats.get("total_entities", 0)

        # Construire les KPIs
        kpis = []
        if config.get("show_global_score", True):
            kpis.append({"label": "Score Global", "value": f"{global_score}%", "icon": "🎯", "color": self._get_score_color(global_score)})
        if config.get("show_domains_count", True):
            kpis.append({"label": "Domaines", "value": str(domains_count), "icon": "📊", "color": "#6366F1"})
        if config.get("show_questions_count", True):
            kpis.append({"label": "Questions", "value": str(questions_count), "icon": "❓", "color": "#0891B2"})
        if config.get("show_nc_count", True):
            kpis.append({"label": "Non-Conformités", "value": str(nc_count), "icon": "⚠️", "color": "#DC2626"})
        if config.get("show_entities_count", False) and entities_count > 0:
            kpis.append({"label": "Entités", "value": str(entities_count), "icon": "🏢", "color": "#7C3AED"})

        # Générer HTML - Compatible xhtml2pdf (tables au lieu de flexbox)
        html = f"""
        <div class="kpi-section" style="margin: 20px 0;">
            <h3 style="
                font-family: {self.fonts['heading1']['family']};
                font-size: {self.fonts['heading1']['size']}px;
                margin: 0 0 15px 0;
            ">{title}</h3>
            <table width="100%" cellpadding="10" cellspacing="0" border="0">
                <tr>
        """

        for i, kpi in enumerate(kpis):
            html += f"""
                    <td width="{100 // len(kpis) if kpis else 25}%" align="center" style="
                        padding: 15px;
                        background: white;
                        border: 1px solid #E5E7EB;
                        text-align: center;
                    ">
                        <div style="font-size: 24px; margin-bottom: 5px;">{kpi['icon']}</div>
                        <div style="
                            font-size: 28px;
                            font-weight: bold;
                            color: {kpi['color']};
                        ">{kpi['value']}</div>
                        <div style="
                            font-size: 12px;
                            color: #6B7280;
                            margin-top: 5px;
                        ">{kpi['label']}</div>
                    </td>
            """

        html += """
                </tr>
            </table>
        </div>
        """
        return html

    def render_benchmark(self, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """Rendu du widget de benchmarking."""
        title = config.get("title", "Positionnement")

        benchmarking = data.get("benchmarking", {})
        entity_score = benchmarking.get("entity_score", 0)
        # Fallback: average_score OU campaign_avg
        average_score = benchmarking.get("average_score") or benchmarking.get("campaign_avg", 0)
        # Fallback: position OU rank
        position = benchmarking.get("position") or benchmarking.get("rank", 0)
        total = benchmarking.get("total_entities", 0)
        # Fallback: performance_vs_average OU difference_vs_avg
        delta = benchmarking.get("performance_vs_average") or benchmarking.get("difference_vs_avg", 0)

        logger.info(f"📊 render_benchmark: entity_score={entity_score}, average_score={average_score}, position={position}, delta={delta}")

        delta_color = "#22C55E" if delta >= 0 else "#DC2626"
        delta_icon = "↑" if delta >= 0 else "↓"

        # HTML compatible xhtml2pdf (tables au lieu de flexbox, pas de linear-gradient)
        html = f"""
        <div class="benchmark-widget" style="
            margin: 20px 0;
            padding: 20px;
            background-color: #F0F9FF;
            border: 1px solid #BAE6FD;
        ">
            <h3 style="
                font-family: {self.fonts['heading1']['family']};
                font-size: {self.fonts['heading1']['size']}px;
                margin: 0 0 15px 0;
                color: #0369A1;
            ">{title}</h3>

            <table width="100%" cellpadding="10" cellspacing="0" border="0">
                <tr>
                    <td width="25%" align="center" style="text-align: center;">
                        <div style="font-size: 14px; color: #6B7280;">Votre Score</div>
                        <div style="font-size: 36px; font-weight: bold; color: {self._get_score_color(entity_score)};">{entity_score}%</div>
                    </td>
                    <td width="25%" align="center" style="text-align: center;">
                        <div style="font-size: 14px; color: #6B7280;">Moyenne Secteur</div>
                        <div style="font-size: 36px; font-weight: bold; color: #6B7280;">{average_score}%</div>
                    </td>
                    <td width="25%" align="center" style="text-align: center;">
                        <div style="font-size: 14px; color: #6B7280;">Position</div>
                        <div style="font-size: 36px; font-weight: bold; color: #0369A1;">{position}/{total}</div>
                    </td>
                    <td width="25%" align="center" style="text-align: center;">
                        <div style="font-size: 14px; color: #6B7280;">vs Moyenne</div>
                        <div style="font-size: 36px; font-weight: bold; color: {delta_color};">{delta_icon} {abs(delta)}%</div>
                    </td>
                </tr>
            </table>
        </div>
        """
        return html

    def render_domain_scores(self, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """Rendu du tableau des scores par domaine."""
        title = config.get("title", "Scores par Domaine")
        show_progress = config.get("show_progress_bar", True)
        sort_by = config.get("sort_by", "score")
        order = config.get("order", "asc")

        domain_scores = data.get("domain_scores", [])

        # Tri
        if sort_by == "score":
            domain_scores = sorted(domain_scores, key=lambda x: x.get("score", 0), reverse=(order == "desc"))
        elif sort_by == "name":
            domain_scores = sorted(domain_scores, key=lambda x: x.get("name", ""), reverse=(order == "desc"))

        html = f"""
        <div class="domain-scores" style="margin: 20px 0;">
            <h3 style="
                font-family: {self.fonts['heading1']['family']};
                font-size: {self.fonts['heading1']['size']}px;
                margin: 0 0 15px 0;
            ">{title}</h3>
            <table style="
                width: 100%;
                border-collapse: collapse;
                font-family: {self.fonts['body']['family']};
                font-size: {self.fonts['body']['size']}px;
            ">
                <thead>
                    <tr style="background-color: {self.color_scheme['primary']}; color: white;">
                        <th style="padding: 12px; text-align: left;">Domaine</th>
                        <th style="padding: 12px; text-align: center; width: 100px;">Score</th>
                        {'<th style="padding: 12px; text-align: left; width: 200px;">Progression</th>' if show_progress else ''}
                    </tr>
                </thead>
                <tbody>
        """

        for i, domain in enumerate(domain_scores):
            bg_color = "#F9FAFB" if i % 2 == 0 else "white"
            score = domain.get("score", 0)
            name = domain.get("name", "N/A")
            score_color = self._get_score_color(score)

            progress_html = ""
            if show_progress:
                progress_html = f"""
                    <td style="padding: 12px;">
                        <div style="
                            width: 100%;
                            height: 20px;
                            background: #E5E7EB;
                            border-radius: 10px;
                            overflow: hidden;
                        ">
                            <div style="
                                width: {score}%;
                                height: 100%;
                                background: {score_color};
                                border-radius: 10px;
                            "></div>
                        </div>
                    </td>
                """

            html += f"""
                <tr style="background-color: {bg_color};">
                    <td style="padding: 12px;">{name}</td>
                    <td style="padding: 12px; text-align: center; font-weight: bold; color: {score_color};">{score}%</td>
                    {progress_html}
                </tr>
            """

        html += """
                </tbody>
            </table>
        </div>
        """
        return html

    def render_action_plan(self, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """Rendu du plan d'action."""
        title = config.get("title", "Plan d'Action")
        limit = config.get("limit", 10)
        show_priority = config.get("show_priority", True)
        show_deadline = config.get("show_deadline", False)
        show_budget = config.get("show_budget", False)

        # Chercher les actions dans plusieurs clés possibles
        actions = data.get("action_plan", []) or data.get("actions", [])
        if limit:
            actions = actions[:limit]

        if not actions:
            return f"""
            <div style="margin: 20px 0; padding: 20px; background: #F0FDF4; border: 1px solid #22C55E; border-radius: 8px; text-align: center;">
                <p style="color: #166534;">&#10003; Aucune action corrective requise</p>
            </div>
            """

        # HTML compatible xhtml2pdf (tables au lieu de flexbox)
        html = f"""
        <div class="action-plan" style="margin: 20px 0;">
            <h3 style="
                font-family: {self.fonts['heading1']['family']};
                font-size: {self.fonts['heading1']['size']}px;
                margin: 0 0 15px 0;
            ">{title}</h3>
        """

        priority_colors = {
            "high": {"bg": "#FEF2F2", "border": "#DC2626", "label": "Haute"},
            "medium": {"bg": "#FEF3C7", "border": "#F59E0B", "label": "Moyenne"},
            "low": {"bg": "#ECFDF5", "border": "#22C55E", "label": "Basse"},
        }

        for i, action in enumerate(actions):
            priority = action.get("priority", "medium")
            pstyle = priority_colors.get(priority, priority_colors["medium"])

            # Construire la ligne des métadonnées
            meta_items = []
            if show_priority:
                meta_items.append(f'<span style="color: {pstyle["border"]};">● Priorité: {pstyle["label"]}</span>')
            if show_deadline and action.get("deadline"):
                meta_items.append(f'<span>📅 {action.get("deadline", "N/A")}</span>')
            if show_budget and action.get("budget"):
                meta_items.append(f'<span>💰 {action.get("budget", "N/A")}</span>')
            meta_html = " &nbsp;&nbsp; ".join(meta_items) if meta_items else ""

            html += f"""
                <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom: 10px;">
                    <tr>
                        <td width="4" style="background-color: {pstyle['border']}; padding: 0;"></td>
                        <td style="background-color: {pstyle['bg']}; padding: 15px;">
                            <table width="100%" cellpadding="0" cellspacing="0" border="0">
                                <tr>
                                    <td width="30" valign="top" style="font-weight: bold; color: {pstyle['border']};">{i+1}.</td>
                                    <td>
                                        <div style="font-weight: 500;">{action.get('title', 'Action')}</div>
                                        <div style="font-size: 14px; color: #6B7280; margin-top: 5px;">
                                            {action.get('description', '')}
                                        </div>
                                        {f'<div style="margin-top: 8px; font-size: 12px;">{meta_html}</div>' if meta_html else ''}
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                </table>
            """

        html += """
        </div>
        """
        return html

    # ========================================================================
    # WIDGETS SCANNER (Rapports de scan de vulnérabilités)
    # ========================================================================

    def render_scan_summary(self, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """
        Rendu du résumé du scan.
        Affiche les informations clés: cible, entité, date, statut, durée.
        """
        scan = data.get("scan", {})
        entity = data.get("entity", {})
        target_data = data.get("target", {})
        summary = data.get("summary", {})

        # Récupérer la cible depuis target_data ou scan
        target = target_data.get("value", target_data.get("label", scan.get("target_value", "N/A")))
        entity_name = entity.get("name", scan.get("entity_name", "N/A"))
        scan_date = scan.get("finished_at", scan.get("created_at", "N/A"))
        status = scan.get("status", "N/A")
        # Durée depuis summary
        duration = summary.get("scan_duration_seconds", scan.get("duration_seconds", 0))

        # Formater la durée
        if isinstance(duration, (int, float)):
            if duration > 60:
                duration_str = f"{int(duration // 60)}h {int(duration % 60)}min"
            else:
                duration_str = f"{int(duration)}min"
        else:
            duration_str = str(duration)

        # Formater la date
        if scan_date and scan_date != "N/A":
            try:
                from datetime import datetime
                if isinstance(scan_date, str):
                    dt = datetime.fromisoformat(scan_date.replace('Z', '+00:00'))
                    scan_date = dt.strftime('%d/%m/%Y à %H:%M')
            except:
                pass

        # Couleur du statut
        status_colors = {
            "completed": "#22C55E",
            "running": "#3B82F6",
            "failed": "#EF4444",
            "pending": "#F59E0B"
        }
        status_color = status_colors.get(status.lower(), "#6B7280")

        # HTML compatible xhtml2pdf (tables au lieu de grid, pas de linear-gradient)
        html = f"""
        <div class="scan-summary" style="
            margin: 20px 0;
            padding: 20px;
            background-color: #ECFEFF;
            border: 1px solid #06B6D4;
        ">
            <table width="100%" cellpadding="10" cellspacing="0" border="0">
                <tr>
                    <td width="20%" align="center" style="text-align: center;">
                        <div style="font-size: 12px; color: #0E7490; margin-bottom: 5px;">🎯 Cible</div>
                        <div style="font-size: 14px; font-weight: bold; color: #164E63;">{target}</div>
                    </td>
                    <td width="20%" align="center" style="text-align: center;">
                        <div style="font-size: 12px; color: #0E7490; margin-bottom: 5px;">🏢 Entité</div>
                        <div style="font-size: 14px; font-weight: bold; color: #164E63;">{entity_name}</div>
                    </td>
                    <td width="20%" align="center" style="text-align: center;">
                        <div style="font-size: 12px; color: #0E7490; margin-bottom: 5px;">📅 Date du scan</div>
                        <div style="font-size: 14px; font-weight: bold; color: #164E63;">{scan_date}</div>
                    </td>
                    <td width="20%" align="center" style="text-align: center;">
                        <div style="font-size: 12px; color: #0E7490; margin-bottom: 5px;">⏱️ Durée</div>
                        <div style="font-size: 14px; font-weight: bold; color: #164E63;">{duration_str}</div>
                    </td>
                    <td width="20%" align="center" style="text-align: center;">
                        <div style="font-size: 12px; color: #0E7490; margin-bottom: 5px;">📊 Statut</div>
                        <div style="
                            font-size: 12px;
                            font-weight: bold;
                            color: white;
                            background-color: {status_color};
                            padding: 4px 12px;
                        ">{status.upper()}</div>
                    </td>
                </tr>
            </table>
        </div>
        """
        return html

    def render_scan_exposure_score(self, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """
        Rendu du score d'exposition du scan.
        Affiche une jauge avec le score et des métriques CVSS.
        """
        title = config.get("title", "Score d'Exposition")

        # Récupérer les données depuis summary (collecteur scanner) ou fallback
        summary = data.get("summary", {})
        vulnerabilities = data.get("vulnerabilities", {})

        exposure_score_raw = summary.get("exposure_score", 0)
        # Calculer métriques CVSS depuis les vulnérabilités
        all_vulns = vulnerabilities.get("all", [])
        cvss_scores = [v.get("cvss_score", 0) for v in all_vulns if v.get("cvss_score")]
        cvss_avg = sum(cvss_scores) / len(cvss_scores) if cvss_scores else 0
        cvss_max = max(cvss_scores) if cvss_scores else 0
        total_cves = sum(len(v.get("cve_ids", [])) for v in all_vulns)

        # Normaliser l'exposition sur une échelle de 10
        # exposure_score est sur 100, diviser par 10 pour obtenir l'échelle 0-10
        if exposure_score_raw > 10:
            exposure_score = exposure_score_raw / 10
        else:
            exposure_score = exposure_score_raw

        # Déterminer le niveau de risque (sur échelle 0-10)
        if exposure_score >= 8:
            risk_level = "CRITIQUE"
            risk_color = "#DC2626"
            risk_bg = "#FEF2F2"
        elif exposure_score >= 6:
            risk_level = "ÉLEVÉ"
            risk_color = "#F97316"
            risk_bg = "#FFF7ED"
        elif exposure_score >= 4:
            risk_level = "MOYEN"
            risk_color = "#EAB308"
            risk_bg = "#FEFCE8"
        else:
            risk_level = "FAIBLE"
            risk_color = "#22C55E"
            risk_bg = "#F0FDF4"

        # Calcul pour la barre de progression
        percentage = min(exposure_score / 10 * 100, 100)

        # HTML compatible xhtml2pdf (tables au lieu de flexbox, pas de SVG complexe)
        html = f"""
        <div class="exposure-score" style="margin: 30px 0;">
            <h3 style="
                font-family: {self.fonts['heading2']['family']};
                font-size: {self.fonts['heading2']['size']}px;
                color: {self.color_scheme['text']};
                margin-bottom: 20px;
                text-align: center;
            ">{title}</h3>

            <table width="100%" cellpadding="10" cellspacing="0" border="0">
                <tr>
                    <!-- Score d'exposition -->
                    <td width="50%" align="center" style="text-align: center; padding: 20px;">
                        <div style="font-size: 48px; font-weight: bold; color: {risk_color};">{exposure_score:.1f}/10</div>
                        <!-- Barre de progression -->
                        <table width="200" cellpadding="0" cellspacing="0" border="0" align="center" style="margin-top: 15px; border: 1px solid #E5E7EB;">
                            <tr>
                                <td width="{percentage}%" style="background-color: {risk_color}; height: 15px;"></td>
                                <td width="{100 - percentage}%" style="background-color: #E5E7EB; height: 15px;"></td>
                            </tr>
                        </table>
                    </td>
                    <!-- Niveau de risque -->
                    <td width="50%" align="center" style="text-align: center;">
                        <div style="
                            padding: 20px 30px;
                            background-color: {risk_bg};
                            border: 2px solid {risk_color};
                        ">
                            <div style="font-size: 12px; color: #6B7280; margin-bottom: 5px;">Niveau de Risque</div>
                            <div style="font-size: 24px; font-weight: bold; color: {risk_color};">{risk_level}</div>
                        </div>
                    </td>
                </tr>
            </table>

            <!-- Métriques CVSS -->
            <table width="100%" cellpadding="15" cellspacing="0" border="0" style="margin-top: 20px; background-color: #F9FAFB;">
                <tr>
                    <td width="33%" align="center" style="text-align: center;">
                        <div style="font-size: 11px; color: #6B7280;">Total CVEs</div>
                        <div style="font-size: 20px; font-weight: bold; color: #0891B2;">{total_cves}</div>
                    </td>
                    <td width="33%" align="center" style="text-align: center; border-left: 1px solid #E5E7EB;">
                        <div style="font-size: 11px; color: #6B7280;">CVSS Moyen</div>
                        <div style="font-size: 20px; font-weight: bold; color: #0891B2;">{cvss_avg:.1f}</div>
                    </td>
                    <td width="33%" align="center" style="text-align: center; border-left: 1px solid #E5E7EB;">
                        <div style="font-size: 11px; color: #6B7280;">CVSS Max</div>
                        <div style="font-size: 20px; font-weight: bold; color: {risk_color};">{cvss_max:.1f}</div>
                    </td>
                </tr>
            </table>
        </div>
        """
        return html

    def render_scan_cvss_distribution(self, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """
        Rendu de la distribution CVSS par sévérité.
        Affiche un graphique en barres horizontales.
        """
        title = config.get("title", "Distribution par Sévérité")

        # Récupérer les données depuis summary (collecteur scanner)
        summary = data.get("summary", {})
        vulnerabilities = data.get("vulnerabilities", {})

        # Compter depuis le summary ou les listes de vulnérabilités
        severity_data = [
            {"label": "Critique", "count": summary.get("vuln_critical", len(vulnerabilities.get("critical", []))), "color": "#DC2626"},
            {"label": "Haute", "count": summary.get("vuln_high", len(vulnerabilities.get("high", []))), "color": "#F97316"},
            {"label": "Moyenne", "count": summary.get("vuln_medium", len(vulnerabilities.get("medium", []))), "color": "#EAB308"},
            {"label": "Basse", "count": summary.get("vuln_low", len(vulnerabilities.get("low", []))), "color": "#22C55E"},
            {"label": "Info", "count": summary.get("vuln_info", len(vulnerabilities.get("info", []))), "color": "#0891B2"},
        ]

        total = sum(s["count"] for s in severity_data)
        max_count = max(s["count"] for s in severity_data) if total > 0 else 1

        # HTML compatible xhtml2pdf (tables au lieu de flexbox)
        html = f"""
        <div class="cvss-distribution" style="margin: 20px 0;">
            <h3 style="
                font-family: {self.fonts['heading2']['family']};
                font-size: {self.fonts['heading2']['size']}px;
                color: {self.color_scheme['text']};
                margin-bottom: 15px;
            ">{title}</h3>

            <div style="background-color: #F9FAFB; padding: 20px;">
        """

        for sev in severity_data:
            percentage = (sev["count"] / max_count * 100) if max_count > 0 else 0
            pct_total = (sev["count"] / total * 100) if total > 0 else 0

            html += f"""
                <div style="margin-bottom: 12px;">
                    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom: 4px;">
                        <tr>
                            <td align="left" style="font-size: 12px; font-weight: 500; color: #374151;">
                                <span style="color: {sev['color']}; font-size: 14px;">●</span> {sev['label']}
                            </td>
                            <td align="right" style="font-size: 12px; color: #6B7280;">
                                {sev['count']} ({pct_total:.0f}%)
                            </td>
                        </tr>
                    </table>
                    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #E5E7EB;">
                        <tr>
                            <td width="{percentage}%" style="background-color: {sev['color']}; height: 20px;"></td>
                            <td width="{100 - percentage}%" style="height: 20px;"></td>
                        </tr>
                    </table>
                </div>
            """

        html += f"""
                <div style="
                    margin-top: 15px;
                    padding-top: 15px;
                    border-top: 1px solid #E5E7EB;
                    text-align: center;
                    font-size: 14px;
                    color: #0891B2;
                    font-weight: bold;
                ">
                    Total: {total} vulnérabilités
                </div>
            </div>
        </div>
        """
        return html

    def render_scan_vulnerabilities_table(self, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """
        Rendu du tableau des vulnérabilités détectées.
        """
        title = config.get("title", "Vulnérabilités Détectées")
        limit = config.get("limit", 30)
        sort_by = config.get("sort_by", "cvss_score")
        order = config.get("order", "desc")

        # Récupérer les vulnérabilités (peut être un dict avec clés par sévérité ou une liste)
        vuln_data = data.get("vulnerabilities", {})
        if isinstance(vuln_data, dict):
            # Format collecteur scanner: dict avec clés critical, high, etc.
            vulnerabilities = vuln_data.get("all", [])
        else:
            # Format liste directe
            vulnerabilities = vuln_data

        # Trier
        reverse = order == "desc"
        vulnerabilities = sorted(vulnerabilities, key=lambda x: x.get(sort_by, 0) or 0, reverse=reverse)

        # Limiter
        if limit:
            vulnerabilities = vulnerabilities[:limit]

        if not vulnerabilities:
            return f"""
            <div style="margin: 20px 0; padding: 30px; background: #F0FDF4; border: 1px solid #22C55E; border-radius: 8px; text-align: center;">
                <span style="font-size: 24px;">✓</span>
                <p style="color: #166534; margin: 10px 0 0 0;">Aucune vulnérabilité détectée</p>
            </div>
            """

        html = f"""
        <div class="vulnerabilities-table" style="margin: 20px 0;">
            <h3 style="
                font-family: {self.fonts['heading2']['family']};
                font-size: {self.fonts['heading2']['size']}px;
                margin-bottom: 15px;
            ">{title}</h3>

            <table style="
                width: 100%;
                border-collapse: collapse;
                font-size: {self.fonts['body']['size']}px;
            ">
                <thead>
                    <tr style="background: #0E7490; color: white;">
                        <th style="padding: 10px; text-align: left;">CVE ID</th>
                        <th style="padding: 10px; text-align: center;">Sévérité</th>
                        <th style="padding: 10px; text-align: center;">CVSS</th>
                        <th style="padding: 10px; text-align: left;">Description</th>
                        <th style="padding: 10px; text-align: left;">Service</th>
                    </tr>
                </thead>
                <tbody>
        """

        for i, vuln in enumerate(vulnerabilities):
            bg_color = "#ECFEFF" if i % 2 == 0 else "white"

            # cve_ids est une liste dans le collecteur scanner
            cve_ids = vuln.get("cve_ids", [])
            cve_id = cve_ids[0] if cve_ids else vuln.get("cve_id", vuln.get("title", "N/A"))
            cvss = vuln.get("cvss_score", vuln.get("cvss", 0)) or 0
            severity = vuln.get("severity", "")
            description = (vuln.get("description", "") or vuln.get("title", ""))[:80]
            if len(vuln.get("description", "") or "") > 80:
                description += "..."
            # service dans le collecteur scanner
            service = vuln.get("service", vuln.get("affected_service", "N/A"))

            # Couleur selon sévérité
            if cvss >= 9:
                sev_color = "#DC2626"
                sev_label = "CRITIQUE"
            elif cvss >= 7:
                sev_color = "#F97316"
                sev_label = "HAUTE"
            elif cvss >= 4:
                sev_color = "#EAB308"
                sev_label = "MOYENNE"
            else:
                sev_color = "#22C55E"
                sev_label = "BASSE"

            html += f"""
                <tr style="background: {bg_color};">
                    <td style="padding: 10px; font-family: monospace; font-size: 11px;">{cve_id}</td>
                    <td style="padding: 10px; text-align: center;">
                        <span style="
                            background: {sev_color};
                            color: white;
                            padding: 2px 8px;
                            border-radius: 4px;
                            font-size: 10px;
                            font-weight: bold;
                        ">{sev_label}</span>
                    </td>
                    <td style="padding: 10px; text-align: center; font-weight: bold; color: {sev_color};">{cvss:.1f}</td>
                    <td style="padding: 10px; font-size: 11px;">{description}</td>
                    <td style="padding: 10px; font-size: 11px;">{service}</td>
                </tr>
            """

        html += """
                </tbody>
            </table>
        </div>
        """
        return html

    def render_scan_services_table(self, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """
        Rendu du tableau des services exposés.
        """
        title = config.get("title", "Services Exposés")

        services = data.get("services", data.get("open_ports", []))

        if not services:
            return f"""
            <div style="margin: 20px 0; padding: 30px; background: #ECFEFF; border: 1px solid #06B6D4; border-radius: 8px; text-align: center;">
                <p style="color: #0E7490; margin: 0;">Aucun service exposé détecté</p>
            </div>
            """

        html = f"""
        <div class="services-table" style="margin: 20px 0;">
            <h3 style="
                font-family: {self.fonts['heading2']['family']};
                font-size: {self.fonts['heading2']['size']}px;
                margin-bottom: 15px;
            ">{title}</h3>

            <table style="
                width: 100%;
                border-collapse: collapse;
                font-size: {self.fonts['body']['size']}px;
            ">
                <thead>
                    <tr style="background: #0E7490; color: white;">
                        <th style="padding: 10px; text-align: center;">Port</th>
                        <th style="padding: 10px; text-align: center;">Protocole</th>
                        <th style="padding: 10px; text-align: left;">Service</th>
                        <th style="padding: 10px; text-align: left;">Version</th>
                        <th style="padding: 10px; text-align: center;">État</th>
                    </tr>
                </thead>
                <tbody>
        """

        for i, service in enumerate(services):
            bg_color = "#ECFEFF" if i % 2 == 0 else "white"

            port = service.get("port", "N/A")
            protocol = service.get("protocol", "TCP").upper()
            service_name = service.get("service", service.get("name", "unknown"))
            version = service.get("version", "-")
            state = service.get("state", "open")

            state_color = "#22C55E" if state == "open" else "#6B7280"

            html += f"""
                <tr style="background: {bg_color};">
                    <td style="padding: 10px; text-align: center; font-weight: bold;">{port}</td>
                    <td style="padding: 10px; text-align: center;">{protocol}</td>
                    <td style="padding: 10px;">{service_name}</td>
                    <td style="padding: 10px; font-size: 11px; color: #6B7280;">{version}</td>
                    <td style="padding: 10px; text-align: center;">
                        <span style="color: {state_color};">●</span> {state}
                    </td>
                </tr>
            """

        html += """
                </tbody>
            </table>
        </div>
        """
        return html

    def render_scan_tls_analysis(self, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """
        Rendu de l'analyse TLS/SSL.
        """
        # Récupérer les données TLS depuis le collecteur scanner
        tls_data = data.get("tls", data.get("tls_analysis", data.get("ssl_info", {})))
        summary = data.get("summary", {})

        # Si pas de TLS data mais grade dans summary
        if not tls_data and summary.get("tls_grade"):
            tls_data = {"grade": summary.get("tls_grade")}

        if not tls_data:
            return f"""
            <div style="margin: 20px 0; padding: 30px; background-color: #F9FAFB; border: 1px solid #E5E7EB; text-align: center;">
                <p style="color: #6B7280; margin: 0;">Aucune information TLS/SSL disponible</p>
            </div>
            """

        grade = tls_data.get("grade", tls_data.get("ssl_grade", summary.get("tls_grade", "N/A")))
        protocols = tls_data.get("protocols", [])
        cert_info = tls_data.get("certificate", {})
        vulnerabilities = tls_data.get("vulnerabilities", [])

        # Couleur selon le grade
        grade_colors = {
            "A+": "#22C55E", "A": "#22C55E",
            "B": "#84CC16",
            "C": "#EAB308",
            "D": "#F97316",
            "E": "#EF4444", "F": "#DC2626"
        }
        grade_color = grade_colors.get(str(grade).upper(), "#6B7280")

        # HTML compatible xhtml2pdf (tables au lieu de flexbox)
        html = f"""
        <div class="tls-analysis" style="margin: 20px 0;">
            <table width="100%" cellpadding="10" cellspacing="0" border="0">
                <tr>
                    <!-- Grade TLS -->
                    <td width="120" align="center" valign="top" style="
                        padding: 20px;
                        background-color: #F0FDF4;
                        border: 2px solid {grade_color};
                        text-align: center;
                    ">
                        <div style="font-size: 11px; color: #6B7280; margin-bottom: 5px;">Grade TLS</div>
                        <div style="font-size: 48px; font-weight: bold; color: {grade_color};">{grade}</div>
                    </td>

                    <!-- Certificat -->
                    <td valign="top" style="padding: 15px;">
                        <h4 style="margin: 0 0 10px 0; color: #0E7490;">📜 Certificat</h4>
                        <div style="background-color: #F9FAFB; padding: 15px; font-size: 12px;">
                            <p style="margin: 5px 0;"><strong>Émetteur:</strong> {cert_info.get('issuer', 'N/A')}</p>
                            <p style="margin: 5px 0;"><strong>Validité:</strong> {cert_info.get('valid_from', 'N/A')} - {cert_info.get('valid_to', 'N/A')}</p>
                            <p style="margin: 5px 0;"><strong>Algorithme:</strong> {cert_info.get('algorithm', 'N/A')}</p>
                        </div>
                    </td>

                    <!-- Protocoles -->
                    <td valign="top" style="padding: 15px;">
                        <h4 style="margin: 0 0 10px 0; color: #0E7490;">🔒 Protocoles</h4>
        """

        for proto in protocols:
            proto_name = proto if isinstance(proto, str) else proto.get("name", str(proto))
            is_secure = "TLS 1.2" in proto_name or "TLS 1.3" in proto_name
            proto_color = "#22C55E" if is_secure else "#F97316"

            html += f"""
                        <span style="
                            background-color: #F0FDF4;
                            color: {proto_color};
                            padding: 4px 10px;
                            font-size: 11px;
                            font-weight: 500;
                        ">{proto_name}</span>&nbsp;
            """

        html += """
                    </td>
                </tr>
            </table>
        """

        # Vulnérabilités TLS si présentes
        if vulnerabilities:
            html += f"""
            <div style="margin-top: 15px; padding: 15px; background-color: #FEF2F2; border: 1px solid #FCA5A5;">
                <h4 style="margin: 0 0 10px 0; color: #DC2626;">⚠️ Vulnérabilités TLS</h4>
                <ul style="margin: 0; padding-left: 20px; font-size: 12px; color: #7F1D1D;">
            """
            for vuln in vulnerabilities[:5]:
                vuln_name = vuln if isinstance(vuln, str) else vuln.get("name", str(vuln))
                html += f"<li>{vuln_name}</li>"
            html += "</ul></div>"

        html += "</div>"
        return html

    def render_scan_ecosystem_scatter(self, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """
        Rendu du graphique de positionnement dans l'écosystème.
        Affiche un scatter plot avec les entités.
        """
        title = config.get("title", "Position dans l'Écosystème")
        highlight_current = config.get("highlight_current", True)

        # Récupérer les données - plusieurs sources possibles
        # 1. ecosystem_comparison (format direct)
        # 2. ecosystem (format direct)
        # 3. positioning_chart.data (format depuis _get_entity_positioning)
        ecosystem = data.get("ecosystem_comparison", data.get("ecosystem", []))

        # Si pas de données directes, chercher dans positioning_chart
        if not ecosystem:
            positioning_chart = data.get("positioning_chart", {})
            if isinstance(positioning_chart, dict):
                ecosystem = positioning_chart.get("data", [])

        current_entity_id = data.get("entity", {}).get("id") or data.get("scan", {}).get("entity_id")

        if not ecosystem:
            return f"""
            <div style="margin: 20px 0; padding: 30px; background: #F9FAFB; border: 1px solid #E5E7EB; border-radius: 8px; text-align: center;">
                <p style="color: #6B7280; margin: 0;">Données d'écosystème non disponibles</p>
            </div>
            """

        # Créer une représentation textuelle du scatter (pour PDF, un vrai graphique nécessiterait matplotlib)
        html = f"""
        <div class="ecosystem-scatter" style="margin: 20px 0;">
            <h3 style="
                font-family: {self.fonts['heading2']['family']};
                font-size: {self.fonts['heading2']['size']}px;
                margin-bottom: 15px;
            ">{title}</h3>

            <div style="background: #F9FAFB; border-radius: 8px; padding: 20px;">
                <table style="width: 100%; border-collapse: collapse; font-size: {self.fonts['body']['size']}px;">
                    <thead>
                        <tr style="background: #0E7490; color: white;">
                            <th style="padding: 10px; text-align: left;">Entité</th>
                            <th style="padding: 10px; text-align: center;">CVEs</th>
                            <th style="padding: 10px; text-align: center;">CVSS Moy.</th>
                            <th style="padding: 10px; text-align: center;">Exposition</th>
                            <th style="padding: 10px; text-align: center;">Risque</th>
                        </tr>
                    </thead>
                    <tbody>
        """

        for i, entity in enumerate(ecosystem[:15]):  # Limiter à 15 entités
            entity_id = entity.get("entity_id", entity.get("id"))
            is_current = str(entity_id) == str(current_entity_id) if current_entity_id else False
            # Vérifier aussi le flag 'highlighted' de _get_entity_positioning
            if not is_current and entity.get("highlighted"):
                is_current = True
            bg_color = "#CFFAFE" if is_current else ("#ECFEFF" if i % 2 == 0 else "white")
            font_weight = "bold" if is_current else "normal"

            name = entity.get("entity_name", entity.get("name", "N/A"))
            # Supporter les deux formats: direct (total_cves) et positioning_chart (x)
            cves = entity.get("total_cves", entity.get("cve_count", entity.get("x", 0)))
            cvss_avg = entity.get("cvss_avg", entity.get("y", 0))
            exposure_raw = entity.get("exposure_score", entity.get("size", 0))

            # Normaliser l'exposition sur une échelle de 10
            # exposure_score est sur 100 dans _get_entity_positioning, diviser par 10
            if exposure_raw > 10:
                exposure = exposure_raw / 10
            else:
                exposure = exposure_raw

            # Niveau de risque (sur échelle 0-10)
            if exposure >= 8:
                risk = "CRITIQUE"
                risk_color = "#DC2626"
            elif exposure >= 6:
                risk = "ÉLEVÉ"
                risk_color = "#F97316"
            elif exposure >= 4:
                risk = "MOYEN"
                risk_color = "#EAB308"
            else:
                risk = "FAIBLE"
                risk_color = "#22C55E"

            current_marker = " ◀" if is_current else ""

            html += f"""
                <tr style="background: {bg_color}; font-weight: {font_weight};">
                    <td style="padding: 10px;">{name}{current_marker}</td>
                    <td style="padding: 10px; text-align: center;">{cves}</td>
                    <td style="padding: 10px; text-align: center;">{cvss_avg:.1f}</td>
                    <td style="padding: 10px; text-align: center;">{exposure:.1f}/10</td>
                    <td style="padding: 10px; text-align: center;">
                        <span style="
                            background: {risk_color};
                            color: white;
                            padding: 2px 8px;
                            border-radius: 4px;
                            font-size: 10px;
                        ">{risk}</span>
                    </td>
                </tr>
            """

        html += """
                    </tbody>
                </table>
            </div>
        </div>
        """
        return html

    def render_scan_recommendations(self, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """
        Rendu des recommandations de remédiation.
        """
        title = config.get("title", "Recommandations")
        limit = config.get("limit", 15)
        group_by = config.get("group_by", "severity")

        recommendations = data.get("recommendations", data.get("remediation_actions", []))

        # S'assurer que recommendations est une liste
        if not isinstance(recommendations, list):
            recommendations = []

        if not recommendations:
            # Générer des recommandations basiques basées sur les vulnérabilités
            # Les vulnérabilités peuvent être sous forme de dict (avec 'all', 'critical', etc.) ou de liste
            vulnerabilities_raw = data.get("vulnerabilities", [])

            # Extraire la liste des vulnérabilités selon la structure
            if isinstance(vulnerabilities_raw, dict):
                # Structure: {"all": [...], "critical": [...], "high": [...], ...}
                vulnerabilities = vulnerabilities_raw.get("all", [])
                # Si 'all' est vide, combiner les autres catégories
                if not vulnerabilities:
                    for sev in ["critical", "high", "medium", "low", "info"]:
                        vulnerabilities.extend(vulnerabilities_raw.get(sev, []))
            elif isinstance(vulnerabilities_raw, list):
                vulnerabilities = vulnerabilities_raw
            else:
                vulnerabilities = []

            if vulnerabilities:
                recommendations = []
                for vuln in vulnerabilities[:limit]:
                    if isinstance(vuln, dict):
                        # Gérer cve_ids (liste) ou cve_id (string)
                        cve_ids = vuln.get('cve_ids', vuln.get('cve_id', []))
                        if isinstance(cve_ids, list):
                            cve_display = ', '.join(cve_ids[:3]) if cve_ids else 'vulnérabilité'
                        else:
                            cve_display = cve_ids or 'vulnérabilité'

                        # Construire la description depuis recommendation ou title/description
                        remediation = vuln.get("recommendation", vuln.get("remediation", ""))
                        if not remediation:
                            service = vuln.get('service', vuln.get('affected_service', vuln.get('service_name', 'N/A')))
                            version = vuln.get('version', vuln.get('service_version', ''))
                            remediation = f"Mettre à jour {service}"
                            if version:
                                remediation += f" (actuellement v{version})"
                            # Ajouter la description de la vuln si disponible
                            if vuln.get('description'):
                                remediation += f". {vuln.get('description')[:200]}"

                        cvss = vuln.get("cvss_score", 0) or 0
                        recommendations.append({
                            "title": f"Corriger {cve_display}",
                            "description": remediation[:500],
                            "priority": "high" if cvss >= 7 else ("medium" if cvss >= 4 else "low"),
                            "severity": vuln.get("severity", "medium")
                        })

        if not recommendations:
            return f"""
            <div style="margin: 20px 0; padding: 30px; background: #F0FDF4; border: 1px solid #22C55E; border-radius: 8px; text-align: center;">
                <span style="font-size: 24px;">✓</span>
                <p style="color: #166534; margin: 10px 0 0 0;">Aucune action de remédiation requise</p>
            </div>
            """

        if limit and isinstance(recommendations, list):
            recommendations = recommendations[:limit]

        html = f"""
        <div class="scan-recommendations" style="margin: 20px 0;">
            <h3 style="
                font-family: {self.fonts['heading2']['family']};
                font-size: {self.fonts['heading2']['size']}px;
                margin-bottom: 15px;
            ">{title}</h3>

            <div style="display: flex; flex-direction: column; gap: 10px;">
        """

        priority_styles = {
            "high": {"bg": "#FEF2F2", "border": "#DC2626", "icon": "🔴"},
            "critical": {"bg": "#FEF2F2", "border": "#DC2626", "icon": "🔴"},
            "medium": {"bg": "#FEF3C7", "border": "#F59E0B", "icon": "🟡"},
            "low": {"bg": "#ECFDF5", "border": "#22C55E", "icon": "🟢"},
        }

        for i, rec in enumerate(recommendations):
            priority = rec.get("priority", rec.get("severity", "medium")).lower()
            style = priority_styles.get(priority, priority_styles["medium"])

            html += f"""
                <div style="
                    padding: 15px;
                    background: {style['bg']};
                    border-left: 4px solid {style['border']};
                    border-radius: 0 8px 8px 0;
                ">
                    <div style="display: flex; gap: 10px;">
                        <span style="font-size: 14px;">{style['icon']}</span>
                        <div style="flex: 1;">
                            <div style="font-weight: 500; color: #1F2937;">
                                {i+1}. {rec.get('title', 'Recommandation')}
                            </div>
                            <div style="font-size: 12px; color: #6B7280; margin-top: 5px;">
                                {rec.get('description', '')}
                            </div>
                        </div>
                    </div>
                </div>
            """

        html += """
            </div>
        </div>
        """
        return html

    def render_scan_risk_gauge(self, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """
        Rendu de la jauge de risque global (pour rapports écosystème).
        Similaire à render_gauge mais avec styling scanner.
        """
        title = config.get("title", "Niveau de Risque")

        # Résoudre la valeur
        try:
            resolved_value = self._resolve_variable(config.get("value", "0"), data)
            value = float(str(resolved_value).replace('%', '').replace(',', '.').strip())
        except:
            value = 0

        max_val = config.get("max", 10)
        thresholds = config.get("thresholds", [])

        # Déterminer la couleur
        color = "#22C55E"
        label = "Faible"
        for threshold in sorted(thresholds, key=lambda t: t["value"]):
            if value < threshold["value"]:
                color = threshold.get("color", color)
                label = threshold.get("label", label)
                break

        percentage = (value / max_val) * 100

        html = f"""
        <div class="risk-gauge" style="margin: 30px 0; text-align: center;">
            <h3 style="
                font-family: {self.fonts['heading2']['family']};
                font-size: {self.fonts['heading2']['size']}px;
                color: #0E7490;
                margin-bottom: 20px;
            ">{title}</h3>

            <div style="
                width: 200px;
                height: 120px;
                margin: 0 auto;
                position: relative;
            ">
                <svg width="200" height="120" viewBox="0 0 200 120">
                    <path d="M 20 100 A 80 80 0 0 1 180 100"
                          fill="none"
                          stroke="#E5E7EB"
                          stroke-width="15"
                          stroke-linecap="round"/>
                    <path d="M 20 100 A 80 80 0 0 1 {20 + (160 * percentage / 100)} {100 - (80 * percentage / 100) * 0.8}"
                          fill="none"
                          stroke="{color}"
                          stroke-width="15"
                          stroke-linecap="round"/>
                </svg>

                <div style="
                    position: absolute;
                    bottom: 20px;
                    left: 50%;
                    transform: translateX(-50%);
                    text-align: center;
                ">
                    <div style="font-size: 28px; font-weight: bold; color: {color};">{value:.1f}/{max_val}</div>
                    <div style="font-size: 12px; color: #6B7280;">{label}</div>
                </div>
            </div>
        </div>
        """
        return html

    def render_scan_comparison_table(self, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """
        Rendu du tableau comparatif des entités (pour écosystème).
        """
        title = config.get("title", "Comparaison des Entités")

        entities = data.get("ecosystem_comparison", data.get("entities", []))

        if not entities:
            return f"""
            <div style="margin: 20px 0; padding: 30px; background: #F9FAFB; border-radius: 8px; text-align: center;">
                <p style="color: #6B7280;">Aucune donnée de comparaison disponible</p>
            </div>
            """

        html = f"""
        <div class="comparison-table" style="margin: 20px 0;">
            <h3 style="margin-bottom: 15px;">{title}</h3>

            <table style="width: 100%; border-collapse: collapse; font-size: {self.fonts['body']['size']}px;">
                <thead>
                    <tr style="background: #0E7490; color: white;">
                        <th style="padding: 10px; text-align: left;">Entité</th>
                        <th style="padding: 10px; text-align: left;">Cible</th>
                        <th style="padding: 10px; text-align: center;">Total</th>
                        <th style="padding: 10px; text-align: center;">Critique</th>
                        <th style="padding: 10px; text-align: center;">Haute</th>
                        <th style="padding: 10px; text-align: center;">Moyenne</th>
                        <th style="padding: 10px; text-align: center;">CVSS</th>
                        <th style="padding: 10px; text-align: center;">Dernier Scan</th>
                    </tr>
                </thead>
                <tbody>
        """

        for i, entity in enumerate(entities):
            bg_color = "#ECFEFF" if i % 2 == 0 else "white"

            html += f"""
                <tr style="background: {bg_color};">
                    <td style="padding: 10px;">{entity.get('entity_name', 'N/A')}</td>
                    <td style="padding: 10px; font-size: 11px;">{entity.get('target', 'N/A')}</td>
                    <td style="padding: 10px; text-align: center; font-weight: bold;">{entity.get('total_cves', 0)}</td>
                    <td style="padding: 10px; text-align: center; color: #DC2626;">{entity.get('critical', 0)}</td>
                    <td style="padding: 10px; text-align: center; color: #F97316;">{entity.get('high', 0)}</td>
                    <td style="padding: 10px; text-align: center; color: #EAB308;">{entity.get('medium', 0)}</td>
                    <td style="padding: 10px; text-align: center;">{entity.get('cvss_avg', 0):.1f}</td>
                    <td style="padding: 10px; text-align: center; font-size: 11px;">{entity.get('last_scan', 'N/A')}</td>
                </tr>
            """

        html += """
                </tbody>
            </table>
        </div>
        """
        return html

    def render_scan_top_vulnerabilities(self, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """
        Rendu des top vulnérabilités (pour rapport écosystème).
        """
        title = config.get("title", "Top Vulnérabilités")
        limit = config.get("limit", 15)

        vulnerabilities = data.get("top_vulnerabilities", data.get("vulnerabilities", []))

        if limit:
            vulnerabilities = vulnerabilities[:limit]

        if not vulnerabilities:
            return self.render_scan_vulnerabilities_table(config, data)

        return self.render_scan_vulnerabilities_table({**config, "title": title}, {"vulnerabilities": vulnerabilities})

    def render_scan_history_chart(self, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """
        Rendu du graphique d'historique des scans.
        """
        title = config.get("title", "Évolution Temporelle")

        history = data.get("scan_history", data.get("history", []))

        if not history:
            return f"""
            <div style="margin: 20px 0; padding: 30px; background: #F9FAFB; border-radius: 8px; text-align: center;">
                <p style="color: #6B7280;">Historique non disponible</p>
            </div>
            """

        html = f"""
        <div class="history-chart" style="margin: 20px 0;">
            <h3 style="margin-bottom: 15px;">{title}</h3>

            <table style="width: 100%; border-collapse: collapse; font-size: {self.fonts['body']['size']}px;">
                <thead>
                    <tr style="background: #0E7490; color: white;">
                        <th style="padding: 10px;">Date</th>
                        <th style="padding: 10px;">Total CVEs</th>
                        <th style="padding: 10px;">Critiques</th>
                        <th style="padding: 10px;">CVSS Moy.</th>
                        <th style="padding: 10px;">Tendance</th>
                    </tr>
                </thead>
                <tbody>
        """

        prev_total = None
        for i, entry in enumerate(history):
            bg_color = "#ECFEFF" if i % 2 == 0 else "white"
            total = entry.get("total_cves", 0)

            # Tendance
            if prev_total is not None:
                if total > prev_total:
                    trend = "↑"
                    trend_color = "#DC2626"
                elif total < prev_total:
                    trend = "↓"
                    trend_color = "#22C55E"
                else:
                    trend = "→"
                    trend_color = "#6B7280"
            else:
                trend = "-"
                trend_color = "#6B7280"

            prev_total = total

            html += f"""
                <tr style="background: {bg_color};">
                    <td style="padding: 10px;">{entry.get('date', 'N/A')}</td>
                    <td style="padding: 10px; text-align: center;">{total}</td>
                    <td style="padding: 10px; text-align: center; color: #DC2626;">{entry.get('critical', 0)}</td>
                    <td style="padding: 10px; text-align: center;">{entry.get('cvss_avg', 0):.1f}</td>
                    <td style="padding: 10px; text-align: center; color: {trend_color}; font-size: 18px;">{trend}</td>
                </tr>
            """

        html += """
                </tbody>
            </table>
        </div>
        """
        return html

    def render_budget_summary(self, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """Rendu du résumé budgétaire."""
        title = config.get("title", "Investissement Recommandé")

        budget = data.get("budget", {})

        html = f"""
        <div class="budget-summary" style="
            margin: 20px 0;
            padding: 20px;
            background: linear-gradient(135deg, #FEF3C7 0%, #FDE68A 100%);
            border-radius: 8px;
        ">
            <h3 style="margin: 0 0 15px 0; color: #92400E;">💰 {title}</h3>
            <div style="display: flex; flex-wrap: wrap; gap: 20px;">
                <div style="flex: 1; min-width: 120px; text-align: center;">
                    <div style="font-size: 12px; color: #6B7280;">Formation</div>
                    <div style="font-size: 20px; font-weight: bold;">{budget.get('formation', 'N/A')}€</div>
                </div>
                <div style="flex: 1; min-width: 120px; text-align: center;">
                    <div style="font-size: 12px; color: #6B7280;">Outils</div>
                    <div style="font-size: 20px; font-weight: bold;">{budget.get('tools', 'N/A')}€</div>
                </div>
                <div style="flex: 1; min-width: 120px; text-align: center;">
                    <div style="font-size: 12px; color: #6B7280;">Conseil</div>
                    <div style="font-size: 20px; font-weight: bold;">{budget.get('conseil', 'N/A')}€</div>
                </div>
                <div style="flex: 1; min-width: 120px; text-align: center; border-left: 2px solid #F59E0B; padding-left: 20px;">
                    <div style="font-size: 12px; color: #6B7280;">Total</div>
                    <div style="font-size: 24px; font-weight: bold; color: #92400E;">{budget.get('total', 'N/A')}€</div>
                </div>
            </div>
        </div>
        """
        return html

    def render_metrics_widget(self, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """Rendu du widget de métriques à suivre."""
        title = config.get("title", "Métriques de Suivi")
        metrics_list = config.get("metrics", [])

        html = f"""
        <div class="metrics-widget" style="margin: 20px 0;">
            <h3 style="
                font-family: {self.fonts['heading1']['family']};
                font-size: {self.fonts['heading1']['size']}px;
                margin: 0 0 15px 0;
            ">📊 {title}</h3>
            <div style="
                display: flex;
                flex-wrap: wrap;
                gap: 10px;
            ">
        """

        for metric in metrics_list:
            html += f"""
                <div style="
                    padding: 10px 15px;
                    background: #F3F4F6;
                    border-radius: 20px;
                    font-size: 14px;
                ">
                    • {metric}
                </div>
            """

        html += """
            </div>
        </div>
        """
        return html

    def _get_score_color(self, score: float) -> str:
        """Retourne la couleur selon le score."""
        if score >= 80:
            return "#22C55E"  # Vert
        elif score >= 60:
            return "#F59E0B"  # Orange
        elif score >= 40:
            return "#F97316"  # Orange foncé
        else:
            return "#DC2626"  # Rouge

    def render_properties_table(self, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """Rendu d'un tableau de propriétés."""
        properties = config.get("properties", [])

        html = f"""
        <div class="properties-table" style="margin: 20px 0;">
            <table style="
                width: 100%;
                border-collapse: collapse;
                font-family: {self.fonts['body']['family']};
                font-size: {self.fonts['body']['size']}px;
            ">
        """

        for prop in properties:
            label = prop.get("label", "")
            value = self._resolve_variable(prop.get("value", ""), data)

            html += f"""
                <tr>
                    <td style="
                        padding: 12px;
                        background-color: #F3F4F6;
                        font-weight: bold;
                        width: 30%;
                        border-bottom: 1px solid #E5E7EB;
                    ">{label}</td>
                    <td style="
                        padding: 12px;
                        border-bottom: 1px solid #E5E7EB;
                    ">{value}</td>
                </tr>
            """

        html += """
            </table>
        </div>
        """

        return html

    # ========================================================================
    # HELPERS
    # ========================================================================

    def _resolve_variable(self, text: str, data: Dict[str, Any]) -> str:
        """
        Résout les variables %xxx.yyy% dans le texte.

        Args:
            text: Texte contenant des variables
            data: Données du rapport

        Returns:
            Texte avec variables remplacées
        """
        import re

        # Pattern: %key.subkey%
        pattern = r'%([^%]+)%'

        def replacer(match):
            path = match.group(1).split('.')
            value = data

            for key in path:
                if isinstance(value, dict):
                    value = value.get(key, match.group(0))
                else:
                    return match.group(0)

            return str(value) if value is not None else match.group(0)

        return re.sub(pattern, replacer, str(text))

    def _render_chart_placeholder(self, title: str, icon: str) -> str:
        """Rendu d'un placeholder pour graphiques."""
        html = f"""
        <div class="chart-placeholder" style="margin: 30px 0; text-align: center;">
            <div style="
                width: 500px;
                height: 300px;
                margin: 0 auto;
                background: #F9FAFB;
                border: 2px dashed #D1D5DB;
                border-radius: 8px;
                display: flex;
                align-items: center;
                justify-content: center;
                color: #6B7280;
            ">
                <p>{icon} {title}<br/>(Implémentation à venir)</p>
            </div>
        </div>
        """
        return html

    # ========================================================================
    # WIDGETS EBIOS RM
    # ========================================================================

    def render_ebios_table(self, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """
        Rendu d'une table EBIOS RM générique.

        Args:
            config: Configuration avec columns et data_source
            data: Données du rapport

        Returns:
            HTML de la table
        """
        columns = config.get('columns', [])
        data_source = config.get('data_source', '')

        # Récupérer les données depuis le data_source (ex: "at1.business_values")
        parts = data_source.split('.')
        items = data
        for part in parts:
            if isinstance(items, dict):
                items = items.get(part, [])
            else:
                items = []
                break

        if not items:
            return '<p style="color: #6B7280; font-style: italic;">Aucune donnée disponible</p>'

        # Générer le header
        header_html = '<tr>'
        for col in columns:
            width = col.get('width', 'auto')
            header_html += f'<th style="width: {width}; padding: 10px; background: {self.color_scheme.get("primary", "#dc2626")}; color: white; text-align: left; border: 1px solid #e5e7eb;">{col.get("label", "")}</th>'
        header_html += '</tr>'

        # Générer les lignes
        rows_html = ''
        for item in items:
            rows_html += '<tr>'
            for col in columns:
                key = col.get('key', '')
                style = col.get('style', '')
                value = self._get_nested_value(item, key)

                # Appliquer le style si défini
                cell_style = "padding: 8px; border: 1px solid #e5e7eb;"
                if style == 'badge':
                    cell_style += self._get_badge_style(value)
                elif style == 'risk_level':
                    cell_style += self._get_risk_level_style(value)
                elif style == 'priority':
                    cell_style += self._get_priority_style(value)
                elif style == 'status':
                    cell_style += self._get_status_style(value)

                rows_html += f'<td style="{cell_style}">{value or "-"}</td>'
            rows_html += '</tr>'

        html = f"""
        <table style="width: 100%; border-collapse: collapse; margin: 15px 0;">
            <thead>{header_html}</thead>
            <tbody>{rows_html}</tbody>
        </table>
        """
        return html

    def render_ebios_risk_matrix(self, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """
        Rendu de la matrice des risques EBIOS RM.

        Args:
            config: Configuration avec title, levels, etc.
            data: Données du rapport avec at3 et at4

        Returns:
            HTML de la matrice
        """
        title = config.get('title', 'Matrice des Risques')
        levels = config.get('levels', [
            {"min": 16, "max": 25, "color": "#dc2626", "label": "Critique"},
            {"min": 9, "max": 15, "color": "#f97316", "label": "Important"},
            {"min": 4, "max": 8, "color": "#eab308", "label": "Modéré"},
            {"min": 1, "max": 3, "color": "#22c55e", "label": "Faible"}
        ])

        # Collecter tous les scénarios
        strategic = data.get('at3', {}).get('strategic_scenarios', [])
        operational = data.get('at4', {}).get('operational_scenarios', [])
        all_scenarios = strategic + operational

        # Créer la grille 5x5
        matrix_grid = {}
        for sev in range(1, 6):
            matrix_grid[sev] = {}
            for lik in range(1, 6):
                matrix_grid[sev][lik] = []

        for s in all_scenarios:
            sev = min(max(int(s.get('severity', 1)), 1), 5)
            lik = min(max(int(s.get('likelihood', 1)), 1), 5)
            matrix_grid[sev][lik].append(s.get('code', '?'))

        # Compter par niveau
        risk_counts = {'critical': 0, 'high': 0, 'medium': 0, 'low': 0}
        for s in all_scenarios:
            level = s.get('risk_level', 0) or (s.get('severity', 1) * s.get('likelihood', 1))
            if level >= 16:
                risk_counts['critical'] += 1
            elif level >= 9:
                risk_counts['high'] += 1
            elif level >= 4:
                risk_counts['medium'] += 1
            else:
                risk_counts['low'] += 1

        def get_cell_color(severity: int, likelihood: int) -> str:
            level = severity * likelihood
            for l in levels:
                if l['min'] <= level <= l['max']:
                    return l['color']
            return "#c8e6c9"

        # Générer la matrice HTML
        severity_labels = {5: "Critique", 4: "Grave", 3: "Significatif", 2: "Limité", 1: "Négligeable"}
        likelihood_labels = {1: "Minime", 2: "Significatif", 3: "Fort", 4: "Maximal", 5: "Certain"}

        html = f'<h3 style="color: {self.color_scheme.get("primary", "#dc2626")}; margin-bottom: 15px;">{title}</h3>'
        html += """
        <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
            <thead>
                <tr>
                    <th style="width: 100px; background: #f5f5f5; padding: 8px; border: 1px solid #ddd;">Gravité ↓<br/>Vraisemb. →</th>
        """
        for lik in range(1, 6):
            html += f'<th style="background: #f5f5f5; padding: 8px; border: 1px solid #ddd; text-align: center;">{lik}<br/><small>{likelihood_labels.get(lik, "")}</small></th>'
        html += '</tr></thead><tbody>'

        for sev in range(5, 0, -1):
            html += f"""
            <tr>
                <td style="background: #f5f5f5; padding: 8px; border: 1px solid #ddd; font-weight: bold; text-align: center;">
                    {sev}<br/><small>{severity_labels.get(sev, '')}</small>
                </td>
            """
            for lik in range(1, 6):
                cell_color = get_cell_color(sev, lik)
                scenarios_in_cell = matrix_grid.get(sev, {}).get(lik, [])
                cell_content = "<br/>".join(scenarios_in_cell) if scenarios_in_cell else "-"
                html += f"""
                <td style="background: {cell_color}20; padding: 8px; border: 1px solid #ddd; text-align: center; vertical-align: middle;">
                    <span style="font-weight: {'bold' if scenarios_in_cell else 'normal'};">{cell_content}</span>
                </td>
                """
            html += '</tr>'

        html += '</tbody></table>'

        # Légende
        html += """
        <table style="width: 100%; margin-top: 15px;">
            <tr>
        """
        for l in levels:
            count_key = 'critical' if l['min'] >= 16 else 'high' if l['min'] >= 9 else 'medium' if l['min'] >= 4 else 'low'
            html += f"""
                <td style="background: {l['color']}30; padding: 12px; text-align: center; border: 1px solid #ddd;">
                    <strong style="color: {l['color']};">{l['label']}</strong><br/>
                    <small>(niveau {l['min']}-{l['max']})</small><br/>
                    <strong style="font-size: 18pt; color: {l['color']};">{risk_counts.get(count_key, 0)}</strong>
                </td>
            """
        html += '</tr></table>'

        return html

    def render_ebios_action_cards(self, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """
        Rendu des cartes d'actions détaillées EBIOS RM.

        Args:
            config: Configuration avec fields et data_source
            data: Données du rapport

        Returns:
            HTML des cartes d'actions
        """
        fields = config.get('fields', [])
        data_source = config.get('data_source', 'at6.actions')

        # Récupérer les actions
        parts = data_source.split('.')
        actions = data
        for part in parts:
            if isinstance(actions, dict):
                actions = actions.get(part, [])
            else:
                actions = []
                break

        if not actions:
            return '<p style="color: #6B7280; font-style: italic;">Aucune action définie</p>'

        html = ''
        for i, action in enumerate(actions):
            html += f"""
            <div style="border: 1px solid #e5e7eb; border-radius: 8px; padding: 15px; margin: 15px 0; background: #fafafa; page-break-inside: avoid;">
                <h4 style="color: {self.color_scheme.get('primary', '#dc2626')}; margin: 0 0 10px 0; border-bottom: 2px solid {self.color_scheme.get('primary', '#dc2626')}; padding-bottom: 5px;">
                    {action.get('code_action', f'A{i+1}')} - {action.get('titre', 'Action')}
                </h4>
                <table style="width: 100%; border-collapse: collapse;">
            """
            for field in fields:
                key = field.get('key', '')
                label = field.get('label', key)
                value = action.get(key, '-')
                if value and isinstance(value, str) and len(value) > 0:
                    html += f"""
                    <tr>
                        <td style="padding: 5px 10px; width: 30%; font-weight: bold; color: #4B5563; vertical-align: top;">{label}</td>
                        <td style="padding: 5px 10px; color: #1F2937;">{value}</td>
                    </tr>
                    """
            html += '</table></div>'

        return html

    def render_section(self, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """
        Rendu d'une section/titre.

        Args:
            config: Configuration avec level, title, description
            data: Données du rapport

        Returns:
            HTML de la section
        """
        level = config.get('level', 1)
        title = config.get('title', '')
        description = config.get('description', '')

        tag = f'h{level}' if 1 <= level <= 6 else 'h2'
        color = self.color_scheme.get('primary', '#dc2626')

        html = f'<{tag} style="color: {color}; margin-top: 25px; margin-bottom: 10px;">{title}</{tag}>'
        if description:
            html += f'<p style="color: #6B7280; font-style: italic; margin-bottom: 15px;">{description}</p>'

        return html

    # ========================================================================
    # WIDGETS EBIOS RM - RAPPORTS INDIVIDUELS (Fiches Scénarios)
    # ========================================================================

    def render_scenario_header(self, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """
        Rendu de l'en-tête d'un scénario de risque.

        Args:
            config: Configuration avec fields (code, title, type, risk_level)
            data: Données du scénario

        Returns:
            HTML de l'en-tête du scénario
        """
        scenario = data.get('scenario', {})
        fields = config.get('fields', [])
        color = self.color_scheme.get('primary', '#dc2626')

        html = f'''
        <div style="background: linear-gradient(135deg, {color}10, {color}05); border: 1px solid {color}30; border-radius: 8px; padding: 20px; margin: 15px 0;">
            <table style="width: 100%; border-collapse: collapse;">
        '''

        for field in fields:
            key = field.get('key', '')
            label = field.get('label', key)
            values_map = field.get('values', {})
            style = field.get('style', '')

            value = self._get_nested_value(scenario, key) or '-'

            # Appliquer le mapping de valeurs si défini
            if values_map and value in values_map:
                value = values_map.get(value, value)

            # Appliquer le style si c'est un niveau de risque
            cell_style = ''
            if style == 'risk_level':
                cell_style = self._get_risk_level_style(value)
                value = f'<span style="padding: 4px 12px; border-radius: 4px; {cell_style}">{value}</span>'

            html += f'''
                <tr>
                    <td style="padding: 8px 12px; width: 30%; font-weight: bold; color: #4B5563; border-bottom: 1px solid #e5e7eb;">{label}</td>
                    <td style="padding: 8px 12px; color: #1F2937; border-bottom: 1px solid #e5e7eb;">{value}</td>
                </tr>
            '''

        html += '</table></div>'
        return html

    def render_scenario_description(self, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """
        Rendu de la description d'un scénario.

        Args:
            config: Configuration avec field, show_context
            data: Données du scénario

        Returns:
            HTML de la description
        """
        scenario = data.get('scenario', {})
        field = config.get('field', 'description')
        show_context = config.get('show_context', False)

        description = scenario.get(field, '') or 'Aucune description disponible.'

        html = f'''
        <div style="background-color: #f9fafb; border-left: 4px solid {self.color_scheme.get('primary', '#dc2626')}; padding: 15px 20px; margin: 15px 0; border-radius: 0 8px 8px 0;">
            <p style="color: #374151; line-height: 1.7; margin: 0;">{description}</p>
        </div>
        '''

        if show_context and scenario.get('context'):
            html += f'''
            <div style="margin-top: 10px; padding: 10px 15px; background-color: #eff6ff; border-radius: 6px;">
                <strong style="color: #1e40af;">Contexte :</strong>
                <p style="color: #1e3a8a; margin: 5px 0 0 0;">{scenario.get('context', '')}</p>
            </div>
            '''

        return html

    def render_risk_evaluation(self, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """
        Rendu de l'évaluation du risque avec visualisation.

        Args:
            config: Configuration avec fields, show_scale, show_visual
            data: Données du scénario

        Returns:
            HTML de l'évaluation
        """
        scenario = data.get('scenario', {})
        fields = config.get('fields', [])
        show_scale = config.get('show_scale', True)
        show_visual = config.get('show_visual', True)
        color = self.color_scheme.get('primary', '#dc2626')

        # Extraire les valeurs
        severity = int(scenario.get('severity', 1) or 1)
        likelihood = int(scenario.get('likelihood', 1) or 1)
        risk_level = severity * likelihood

        html = '<div style="margin: 15px 0;">'

        # Visualisation de la grille
        if show_visual:
            html += f'''
            <div style="display: flex; gap: 30px; margin-bottom: 20px; flex-wrap: wrap;">
                <div style="flex: 1; min-width: 200px;">
                    <h4 style="color: {color}; margin-bottom: 10px;">Évaluation</h4>
                    <table style="border-collapse: collapse; width: 100%;">
                        <tr>
                            <td style="padding: 10px; background: #f3f4f6; border: 1px solid #e5e7eb; font-weight: bold;">Gravité (G)</td>
                            <td style="padding: 10px; border: 1px solid #e5e7eb; text-align: center; font-size: 18px; font-weight: bold; {self._get_severity_style(severity)}">{severity}/4</td>
                        </tr>
                        <tr>
                            <td style="padding: 10px; background: #f3f4f6; border: 1px solid #e5e7eb; font-weight: bold;">Vraisemblance (V)</td>
                            <td style="padding: 10px; border: 1px solid #e5e7eb; text-align: center; font-size: 18px; font-weight: bold; {self._get_likelihood_style(likelihood)}">{likelihood}/4</td>
                        </tr>
                        <tr>
                            <td style="padding: 10px; background: #f3f4f6; border: 1px solid #e5e7eb; font-weight: bold;">Niveau de risque</td>
                            <td style="padding: 10px; border: 1px solid #e5e7eb; text-align: center; font-size: 20px; font-weight: bold; {self._get_risk_level_style(risk_level)}">{risk_level}/16</td>
                        </tr>
                    </table>
                </div>
            '''

            # Mini matrice visuelle
            html += f'''
                <div style="flex: 1; min-width: 200px;">
                    <h4 style="color: {color}; margin-bottom: 10px;">Position dans la matrice</h4>
                    <table style="border-collapse: collapse;">
            '''
            for sev in range(4, 0, -1):
                html += '<tr>'
                for lik in range(1, 5):
                    cell_level = sev * lik
                    is_current = (sev == severity and lik == likelihood)
                    bg_color = self._get_risk_matrix_color(cell_level)
                    border = '3px solid #1f2937' if is_current else '1px solid #d1d5db'
                    font_weight = 'bold' if is_current else 'normal'
                    html += f'<td style="width: 40px; height: 40px; background-color: {bg_color}; border: {border}; text-align: center; font-weight: {font_weight};">{cell_level}</td>'
                html += '</tr>'
            html += '</table></div></div>'

        # Échelle de référence
        if show_scale:
            html += '''
            <div style="margin-top: 15px; padding: 15px; background-color: #f9fafb; border-radius: 8px;">
                <strong style="color: #374151;">Légende des niveaux :</strong>
                <div style="display: flex; gap: 15px; margin-top: 10px; flex-wrap: wrap;">
                    <span style="padding: 4px 12px; background-color: #fecaca; color: #7f1d1d; border-radius: 4px;">16-25 : Critique</span>
                    <span style="padding: 4px 12px; background-color: #fed7aa; color: #9a3412; border-radius: 4px;">9-15 : Important</span>
                    <span style="padding: 4px 12px; background-color: #fef08a; color: #854d0e; border-radius: 4px;">4-8 : Modéré</span>
                    <span style="padding: 4px 12px; background-color: #bbf7d0; color: #166534; border-radius: 4px;">1-3 : Faible</span>
                </div>
            </div>
            '''

        html += '</div>'
        return html

    def render_risk_source_card(self, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """
        Rendu d'une carte de source de risque.

        Args:
            config: Configuration avec fields, data_source
            data: Données du rapport

        Returns:
            HTML de la carte
        """
        data_source = config.get('data_source', 'scenario.risk_source')
        risk_source = self._get_nested_value(data, data_source) or {}
        fields = config.get('fields', [])
        color = self.color_scheme.get('primary', '#dc2626')

        if not risk_source:
            return '<p style="color: #9ca3af; font-style: italic;">Aucune source de risque associée.</p>'

        html = f'''
        <div style="background: linear-gradient(135deg, #fef2f2, #fff7ed); border: 1px solid #fecaca; border-radius: 8px; padding: 20px; margin: 15px 0;">
            <div style="display: flex; align-items: center; margin-bottom: 15px;">
                <span style="font-size: 24px; margin-right: 10px;">⚠️</span>
                <h4 style="margin: 0; color: {color};">Source de Risque</h4>
            </div>
            <table style="width: 100%; border-collapse: collapse;">
        '''

        for field in fields:
            key = field.get('key', '')
            label = field.get('label', key)
            value = risk_source.get(key, '-') or '-'

            # Style spécial pour la pertinence
            if key == 'pertinence' or key == 'relevance':
                try:
                    pert_val = int(value) if value != '-' else 0
                    style = self._get_risk_level_style(pert_val * 4)  # Scale to 16
                    value = f'<span style="padding: 2px 8px; border-radius: 4px; {style}">{value}/4</span>'
                except (ValueError, TypeError):
                    pass

            html += f'''
                <tr>
                    <td style="padding: 8px 12px; width: 30%; font-weight: bold; color: #7f1d1d; border-bottom: 1px solid #fecaca;">{label}</td>
                    <td style="padding: 8px 12px; color: #1F2937; border-bottom: 1px solid #fecaca;">{value}</td>
                </tr>
            '''

        html += '</table></div>'
        return html

    def render_feared_event_card(self, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """
        Rendu d'une carte d'événement redouté.

        Args:
            config: Configuration avec fields, data_source
            data: Données du rapport

        Returns:
            HTML de la carte
        """
        data_source = config.get('data_source', 'scenario.feared_event')
        feared_event = self._get_nested_value(data, data_source) or {}
        fields = config.get('fields', [])
        color = self.color_scheme.get('secondary', '#991b1b')

        if not feared_event:
            return '<p style="color: #9ca3af; font-style: italic;">Aucun événement redouté associé.</p>'

        html = f'''
        <div style="background: linear-gradient(135deg, #fef3c7, #fef9c3); border: 1px solid #fcd34d; border-radius: 8px; padding: 20px; margin: 15px 0;">
            <div style="display: flex; align-items: center; margin-bottom: 15px;">
                <span style="font-size: 24px; margin-right: 10px;">🎯</span>
                <h4 style="margin: 0; color: #92400e;">Événement Redouté</h4>
            </div>
            <table style="width: 100%; border-collapse: collapse;">
        '''

        for field in fields:
            key = field.get('key', '')
            label = field.get('label', key)
            value = feared_event.get(key, '-') or '-'

            # Style spécial pour la gravité
            if key == 'severity' or key == 'gravité':
                try:
                    sev_val = int(value) if value != '-' else 0
                    style = self._get_severity_style(sev_val)
                    value = f'<span style="padding: 2px 8px; border-radius: 4px; {style}">{value}/4</span>'
                except (ValueError, TypeError):
                    pass

            # Style pour les impacts (liste)
            if key == 'impacts' and isinstance(value, list):
                value = ', '.join(str(v) for v in value) if value else '-'

            html += f'''
                <tr>
                    <td style="padding: 8px 12px; width: 30%; font-weight: bold; color: #92400e; border-bottom: 1px solid #fcd34d;">{label}</td>
                    <td style="padding: 8px 12px; color: #1F2937; border-bottom: 1px solid #fcd34d;">{value}</td>
                </tr>
            '''

        html += '</table></div>'
        return html

    def _get_severity_style(self, severity: int) -> str:
        """Retourne le style CSS pour une gravité (1-4)."""
        if severity >= 4:
            return "background-color: #fecaca; color: #7f1d1d;"
        elif severity >= 3:
            return "background-color: #fed7aa; color: #9a3412;"
        elif severity >= 2:
            return "background-color: #fef08a; color: #854d0e;"
        return "background-color: #bbf7d0; color: #166534;"

    def _get_likelihood_style(self, likelihood: int) -> str:
        """Retourne le style CSS pour une vraisemblance (1-4)."""
        if likelihood >= 4:
            return "background-color: #fecaca; color: #7f1d1d;"
        elif likelihood >= 3:
            return "background-color: #fed7aa; color: #9a3412;"
        elif likelihood >= 2:
            return "background-color: #fef08a; color: #854d0e;"
        return "background-color: #bbf7d0; color: #166534;"

    def _get_risk_matrix_color(self, level: int) -> str:
        """Retourne la couleur de fond pour un niveau de risque dans la matrice."""
        if level >= 16:
            return "#fecaca"  # Rouge clair
        elif level >= 9:
            return "#fed7aa"  # Orange clair
        elif level >= 4:
            return "#fef08a"  # Jaune clair
        return "#bbf7d0"  # Vert clair

    def _get_nested_value(self, obj: Dict, key: str) -> Any:
        """Récupère une valeur imbriquée avec notation point."""
        parts = key.split('.')
        value = obj
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return None
        return value

    def _get_badge_style(self, value: str) -> str:
        """Retourne le style CSS pour un badge."""
        if value in ['CRITICAL', 'Critique']:
            return "background-color: #fecaca; color: #7f1d1d; font-weight: bold;"
        elif value in ['HIGH', 'Élevé', 'Important']:
            return "background-color: #fed7aa; color: #9a3412; font-weight: bold;"
        elif value in ['MEDIUM', 'Moyen', 'Modéré']:
            return "background-color: #fef08a; color: #854d0e;"
        elif value in ['LOW', 'Faible']:
            return "background-color: #bbf7d0; color: #166534;"
        return ""

    def _get_risk_level_style(self, value) -> str:
        """Retourne le style CSS pour un niveau de risque."""
        try:
            level = int(value) if value else 0
        except (ValueError, TypeError):
            level = 0

        if level >= 16:
            return "background-color: #fecaca; color: #7f1d1d; font-weight: bold; text-align: center;"
        elif level >= 9:
            return "background-color: #fed7aa; color: #9a3412; font-weight: bold; text-align: center;"
        elif level >= 4:
            return "background-color: #fef08a; color: #854d0e; text-align: center;"
        else:
            return "background-color: #bbf7d0; color: #166534; text-align: center;"

    def _get_priority_style(self, value: str) -> str:
        """Retourne le style CSS pour une priorité."""
        if value in ['CRITICAL', 'P1', 'Critique']:
            return "background-color: #fecaca; color: #7f1d1d; font-weight: bold;"
        elif value in ['HIGH', 'P2', 'Haute']:
            return "background-color: #fed7aa; color: #9a3412;"
        elif value in ['MEDIUM', 'P3', 'Moyenne']:
            return "background-color: #fef08a; color: #854d0e;"
        return "background-color: #bbf7d0; color: #166534;"

    def _get_status_style(self, value: str) -> str:
        """Retourne le style CSS pour un statut."""
        if value in ['completed', 'Terminé', 'Done']:
            return "background-color: #bbf7d0; color: #166534;"
        elif value in ['in_progress', 'En cours']:
            return "background-color: #bfdbfe; color: #1e40af;"
        elif value in ['pending', 'En attente', 'À faire']:
            return "background-color: #fef08a; color: #854d0e;"
        return ""

    # ========================================================================
    # WIDGET DISPATCHER
    # ========================================================================

    def render_widget(self, widget_type: str, config: Dict[str, Any], data: Dict[str, Any]) -> str:
        """
        Dispatcher principal pour le rendu des widgets.

        Args:
            widget_type: Type du widget
            config: Configuration du widget
            data: Données du rapport

        Returns:
            HTML du widget rendu
        """
        renderer_map = {
            # Structure
            "cover": self.render_cover,
            "header": self.render_header,
            "footer": self.render_footer,
            "toc": self.render_toc,
            "page_break": self.render_page_break,
            # Texte
            "title": self.render_title,
            "paragraph": self.render_paragraph,
            "text": self.render_paragraph,  # Alias
            "description": self.render_description,
            # Métriques & KPIs
            "metrics": self.render_metrics,
            "kpi": self.render_kpi,
            "gauge": self.render_gauge,
            "benchmark": self.render_benchmark,
            # Graphiques
            "radar_domains": self.render_radar_domains,
            "radar_chart": self.render_radar_domains,  # Alias
            "bar_chart": self.render_bar_chart,
            "pie_chart": self.render_pie_chart,
            "chart": self.render_bar_chart,  # Generic chart
            # Tables
            "actions_table": self.render_actions_table,
            "action_plan": self.render_action_plan,
            "nc_table": self.render_nc_table,
            "questions_table": self.render_questions_table,
            "properties_table": self.render_properties_table,
            "domain_scores": self.render_domain_scores,
            # IA & Avancés
            "ai_summary": self.render_ai_summary,
            "summary": self.render_ai_summary,  # Alias
            "budget_summary": self.render_budget_summary,
            "metrics_widget": self.render_metrics_widget,
            # Scanner - Widgets spécifiques aux rapports de scan
            "scan_summary": self.render_scan_summary,
            "scan_exposure_score": self.render_scan_exposure_score,
            "scan_cvss_distribution": self.render_scan_cvss_distribution,
            "scan_vulnerabilities_table": self.render_scan_vulnerabilities_table,
            "scan_services_table": self.render_scan_services_table,
            "scan_tls_analysis": self.render_scan_tls_analysis,
            "scan_ecosystem_scatter": self.render_scan_ecosystem_scatter,
            "scan_recommendations": self.render_scan_recommendations,
            "scan_risk_gauge": self.render_scan_risk_gauge,
            "scan_comparison_table": self.render_scan_comparison_table,
            "scan_top_vulnerabilities": self.render_scan_top_vulnerabilities,
            "scan_history_chart": self.render_scan_history_chart,
            # EBIOS RM - Widgets spécifiques aux rapports EBIOS
            "ebios_table": self.render_ebios_table,
            "ebios_risk_matrix": self.render_ebios_risk_matrix,
            "ebios_action_cards": self.render_ebios_action_cards,
            "section": self.render_section,
            # EBIOS RM - Widgets pour rapports individuels (fiches scénarios)
            "scenario_header": self.render_scenario_header,
            "scenario_description": self.render_scenario_description,
            "risk_evaluation": self.render_risk_evaluation,
            "risk_source_card": self.render_risk_source_card,
            "feared_event_card": self.render_feared_event_card,
        }

        renderer = renderer_map.get(widget_type)

        if renderer:
            try:
                return renderer(config, data)
            except Exception as e:
                logger.error(f"Erreur lors du rendu du widget {widget_type}: {str(e)}")
                return f'<p style="color: red;">Erreur: {widget_type}</p>'
        else:
            logger.warning(f"Widget type non supporté: {widget_type}")
            return f'<p style="color: orange;">Widget non supporté: {widget_type}</p>'


def render_template_to_html(
    template: Dict[str, Any],
    data: Dict[str, Any]
) -> str:
    """
    Rendu complet d'un template en HTML.

    Args:
        template: Configuration du template
        data: Données du rapport

    Returns:
        HTML complet du rapport
    """
    color_scheme = template.get("color_scheme", {})
    fonts = template.get("fonts", {})

    renderer = WidgetRenderer(color_scheme, fonts)

    # En-tête HTML
    html = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{data.get('report', {}).get('title', 'Rapport')}</title>
        <style>
            @page {{
                size: {template.get('page_size', 'A4')} {template.get('orientation', 'portrait')};
                margin: {template.get('margins', {}).get('top', 20)}mm {template.get('margins', {}).get('right', 15)}mm {template.get('margins', {}).get('bottom', 20)}mm {template.get('margins', {}).get('left', 15)}mm;
            }}

            body {{
                font-family: {fonts.get('body', {}).get('family', 'Arial')};
                font-size: {fonts.get('body', {}).get('size', 10)}px;
                color: {color_scheme.get('text', '#000000')};
                line-height: 1.5;
            }}

            {template.get('custom_css', '')}
        </style>
    </head>
    <body>
    """

    # Rendu de chaque widget
    structure = template.get("structure", [])

    # Passer la structure du template dans data pour que render_toc puisse générer la TOC
    data['_template_structure'] = structure

    for widget in sorted(structure, key=lambda w: w.get("position", 0)):
        widget_type = widget.get("widget_type")
        config = widget.get("config", {}).copy()  # Copier pour ne pas modifier l'original

        # IMPORTANT: Inclure l'ID du widget dans la config pour le rendu
        # Cela permet aux widgets IA de récupérer leur contenu depuis ai_contents
        if widget.get("id"):
            config["id"] = widget.get("id")

        widget_html = renderer.render_widget(widget_type, config, data)
        html += widget_html + "\n"

    # Fermeture HTML
    html += """
    </body>
    </html>
    """

    return html
