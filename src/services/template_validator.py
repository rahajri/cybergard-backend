"""
Service de validation des templates de rapports.

Valide la structure, la configuration et la sécurité des templates
avant génération pour éviter les erreurs runtime et problèmes de sécurité.
"""

from typing import Dict, Any, List, Optional, Tuple
import logging
import json
from uuid import UUID
import re

logger = logging.getLogger(__name__)


class TemplateValidationError(Exception):
    """Exception levée lors de la validation d'un template."""
    pass


class TemplateValidator:
    """Validateur de templates de rapports."""

    # Widget types autorisés
    ALLOWED_WIDGET_TYPES = {
        # Structure
        "cover", "header", "footer", "toc", "page_break",
        # Text
        "title", "paragraph", "description",
        # Metrics
        "metrics", "gauge",
        # Charts
        "radar_domains", "bar_chart", "pie_chart", "comparison_chart",
        # Tables
        "actions_table", "nc_table", "questions_table", "properties_table",
        # Custom
        "html_block", "image"
    }

    # Variables autorisées (whitelist)
    ALLOWED_VARIABLES = {
        # Campaign
        "campaign.id", "campaign.name", "campaign.title", "campaign.description",
        "campaign.status", "campaign.start_date", "campaign.due_date",
        # Stats
        "stats.total_questions", "stats.answered_questions", "stats.pending_questions",
        "stats.compliance_rate", "stats.nc_major_count", "stats.nc_minor_count",
        "stats.compliant_count", "stats.not_applicable_count",
        # System
        "report.date", "report.time", "current_date", "current_time"
    }

    # Limites de sécurité
    MAX_WIDGETS = 100
    MAX_WIDGET_CONFIG_SIZE = 50000  # 50KB par widget config
    MAX_TEMPLATE_SIZE = 2000000  # 2MB total
    MAX_STRING_LENGTH = 10000  # Pour textes dans config

    def __init__(self):
        """Initialise le validateur."""
        pass

    def validate_template(
        self,
        template: Dict[str, Any],
        strict: bool = True
    ) -> Tuple[bool, List[str]]:
        """
        Valide un template complet.

        Args:
            template: Configuration du template
            strict: Si True, erreurs critiques bloquent. Si False, warnings uniquement.

        Returns:
            (is_valid, errors_list)

        Raises:
            TemplateValidationError: Si erreurs critiques en mode strict
        """
        errors = []

        try:
            # 1. Validation de la structure de base
            structure_errors = self._validate_structure(template)
            errors.extend(structure_errors)

            # 2. Validation de la sécurité
            security_errors = self._validate_security(template)
            errors.extend(security_errors)

            # 3. Validation des widgets
            widget_errors = self._validate_widgets(template.get('structure', []))
            errors.extend(widget_errors)

            # 4. Validation des variables
            variable_errors = self._validate_variables(template)
            errors.extend(variable_errors)

            # 5. Validation des couleurs
            color_errors = self._validate_colors(template.get('color_scheme', {}))
            errors.extend(color_errors)

            if errors:
                if strict:
                    error_msg = "\n".join([f"- {err}" for err in errors])
                    raise TemplateValidationError(
                        f"Template validation failed:\n{error_msg}"
                    )
                else:
                    logger.warning(f"Template validation warnings: {len(errors)} issues found")
                    for err in errors:
                        logger.warning(f"  - {err}")
                    return False, errors

            logger.info("Template validation succeeded")
            return True, []

        except TemplateValidationError:
            raise
        except Exception as e:
            logger.error(f"Unexpected error during validation: {str(e)}", exc_info=True)
            raise TemplateValidationError(f"Validation error: {str(e)}")

    def _validate_structure(self, template: Dict[str, Any]) -> List[str]:
        """Valide la structure de base du template."""
        errors = []

        # Champs requis
        required_fields = ['name', 'code', 'template_type', 'structure']
        for field in required_fields:
            if field not in template:
                errors.append(f"Missing required field: {field}")

        # Type de template valide
        if 'template_type' in template:
            valid_types = ['executive', 'technical', 'suppliers', 'custom']
            if template['template_type'] not in valid_types:
                errors.append(
                    f"Invalid template_type: {template['template_type']}. "
                    f"Must be one of {valid_types}"
                )

        # Structure doit être une liste
        if 'structure' in template:
            if not isinstance(template['structure'], list):
                errors.append("'structure' must be a list")
            elif len(template['structure']) == 0:
                errors.append("'structure' cannot be empty")
            elif len(template['structure']) > self.MAX_WIDGETS:
                errors.append(
                    f"Too many widgets: {len(template['structure'])} "
                    f"(max {self.MAX_WIDGETS})"
                )

        return errors

    def _validate_security(self, template: Dict[str, Any]) -> List[str]:
        """Valide la sécurité du template."""
        errors = []

        # 1. Vérifier la taille totale
        try:
            template_json = json.dumps(template)
            size = len(template_json.encode('utf-8'))
            if size > self.MAX_TEMPLATE_SIZE:
                errors.append(
                    f"Template too large: {size} bytes "
                    f"(max {self.MAX_TEMPLATE_SIZE})"
                )
        except Exception as e:
            errors.append(f"Cannot serialize template to JSON: {str(e)}")

        # 2. Vérifier les injections HTML/JS dans les configs
        dangerous_patterns = [
            r'<script[^>]*>',
            r'javascript:',
            r'onerror\s*=',
            r'onload\s*=',
            r'eval\s*\(',
            r'__import__',
            r'exec\s*\(',
        ]

        template_str = json.dumps(template)
        for pattern in dangerous_patterns:
            if re.search(pattern, template_str, re.IGNORECASE):
                errors.append(
                    f"Potential security issue: pattern '{pattern}' detected"
                )

        # 3. Vérifier les chemins de fichiers suspects
        suspicious_paths = [
            '../', '..\\', '/etc/', 'c:\\', '/bin/', '/usr/'
        ]
        for path in suspicious_paths:
            if path in template_str:
                errors.append(
                    f"Suspicious file path detected: '{path}'"
                )

        return errors

    def _validate_widgets(self, widgets: List[Dict[str, Any]]) -> List[str]:
        """Valide la liste des widgets."""
        errors = []

        positions_used = set()

        for idx, widget in enumerate(widgets):
            widget_errors = self._validate_single_widget(widget, idx)
            errors.extend(widget_errors)

            # Vérifier unicité des positions
            position = widget.get('position')
            if position is not None:
                if position in positions_used:
                    errors.append(
                        f"Duplicate position {position} in widget #{idx}"
                    )
                positions_used.add(position)

        return errors

    def _validate_single_widget(
        self,
        widget: Dict[str, Any],
        widget_idx: int
    ) -> List[str]:
        """Valide un widget individuel."""
        errors = []

        # Champs requis
        if 'widget_type' not in widget:
            errors.append(f"Widget #{widget_idx}: missing 'widget_type'")
            return errors

        widget_type = widget['widget_type']

        # Type autorisé
        if widget_type not in self.ALLOWED_WIDGET_TYPES:
            errors.append(
                f"Widget #{widget_idx}: invalid widget_type '{widget_type}'. "
                f"Allowed: {self.ALLOWED_WIDGET_TYPES}"
            )

        # Position
        if 'position' not in widget:
            errors.append(f"Widget #{widget_idx}: missing 'position'")
        elif not isinstance(widget['position'], int):
            errors.append(f"Widget #{widget_idx}: 'position' must be an integer")

        # Config
        if 'config' not in widget:
            errors.append(f"Widget #{widget_idx}: missing 'config'")
        else:
            config = widget['config']
            if not isinstance(config, dict):
                errors.append(f"Widget #{widget_idx}: 'config' must be a dict")
            else:
                # Vérifier taille du config
                try:
                    config_json = json.dumps(config)
                    config_size = len(config_json.encode('utf-8'))
                    if config_size > self.MAX_WIDGET_CONFIG_SIZE:
                        errors.append(
                            f"Widget #{widget_idx}: config too large "
                            f"({config_size} bytes, max {self.MAX_WIDGET_CONFIG_SIZE})"
                        )
                except Exception as e:
                    errors.append(
                        f"Widget #{widget_idx}: cannot serialize config: {str(e)}"
                    )

                # Validation spécifique par type de widget
                type_errors = self._validate_widget_config(widget_type, config, widget_idx)
                errors.extend(type_errors)

        return errors

    def _validate_widget_config(
        self,
        widget_type: str,
        config: Dict[str, Any],
        widget_idx: int
    ) -> List[str]:
        """Valide la configuration spécifique d'un type de widget."""
        errors = []

        # Validation selon le type
        if widget_type == "cover":
            if 'title' not in config:
                errors.append(f"Widget #{widget_idx} (cover): missing 'title'")

        elif widget_type in ["title", "paragraph"]:
            if 'text' not in config:
                errors.append(f"Widget #{widget_idx} ({widget_type}): missing 'text'")
            elif len(config['text']) > self.MAX_STRING_LENGTH:
                errors.append(
                    f"Widget #{widget_idx} ({widget_type}): text too long "
                    f"({len(config['text'])} chars, max {self.MAX_STRING_LENGTH})"
                )

        elif widget_type == "gauge":
            if 'value_source' not in config:
                errors.append(f"Widget #{widget_idx} (gauge): missing 'value_source'")

        elif widget_type in ["radar_domains", "bar_chart", "pie_chart"]:
            if 'data_source' not in config:
                errors.append(
                    f"Widget #{widget_idx} ({widget_type}): missing 'data_source'"
                )

        elif widget_type in ["actions_table", "nc_table", "questions_table"]:
            if 'columns' not in config:
                errors.append(
                    f"Widget #{widget_idx} ({widget_type}): missing 'columns'"
                )
            elif not isinstance(config['columns'], list):
                errors.append(
                    f"Widget #{widget_idx} ({widget_type}): 'columns' must be a list"
                )

        elif widget_type == "html_block":
            if 'html' not in config:
                errors.append(f"Widget #{widget_idx} (html_block): missing 'html'")
            # Vérifier que le HTML ne contient pas de scripts
            html = config.get('html', '')
            if '<script' in html.lower() or 'javascript:' in html.lower():
                errors.append(
                    f"Widget #{widget_idx} (html_block): JavaScript not allowed in HTML"
                )

        return errors

    def _validate_variables(self, template: Dict[str, Any]) -> List[str]:
        """Valide les variables utilisées dans le template."""
        errors = []

        # Extraire toutes les variables du template
        template_str = json.dumps(template)
        variable_pattern = r'%([^%]+)%'
        variables_found = re.findall(variable_pattern, template_str)

        # Vérifier que toutes les variables sont autorisées
        for var in variables_found:
            if var not in self.ALLOWED_VARIABLES:
                errors.append(
                    f"Unknown or disallowed variable: %{var}%. "
                    f"Allowed variables: {self.ALLOWED_VARIABLES}"
                )

        return errors

    def _validate_colors(self, color_scheme: Dict[str, str]) -> List[str]:
        """Valide le schéma de couleurs."""
        errors = []

        # Pattern hex valide
        hex_pattern = r'^#[0-9A-Fa-f]{6}$'

        for color_name, color_value in color_scheme.items():
            if not re.match(hex_pattern, color_value):
                errors.append(
                    f"Invalid color format for '{color_name}': '{color_value}'. "
                    f"Must be hex format like #RRGGBB"
                )

        return errors

    def validate_generation_data(
        self,
        campaign_id: UUID,
        data: Dict[str, Any]
    ) -> Tuple[bool, List[str]]:
        """
        Valide les données collectées avant génération.

        Args:
            campaign_id: ID de la campagne
            data: Données collectées par ReportService

        Returns:
            (is_valid, errors_list)
        """
        errors = []

        # Vérifier les champs requis
        required_keys = ['campaign', 'stats', 'domains']
        for key in required_keys:
            if key not in data:
                errors.append(f"Missing required data key: '{key}'")

        # Vérifier campaign
        if 'campaign' in data:
            campaign = data['campaign']
            if not campaign.get('name'):
                errors.append("Campaign 'name' is empty")
            if not campaign.get('id'):
                errors.append("Campaign 'id' is missing")

        # Vérifier stats
        if 'stats' in data:
            stats = data['stats']
            if 'total_questions' not in stats:
                errors.append("Stats missing 'total_questions'")
            if stats.get('total_questions', 0) == 0:
                errors.append("Campaign has no questions")

        # Vérifier domains
        if 'domains' in data:
            domains = data['domains']
            if not isinstance(domains, list):
                errors.append("'domains' must be a list")
            elif len(domains) == 0:
                errors.append("No domains found in campaign")

        if errors:
            logger.error(
                f"Generation data validation failed for campaign {campaign_id}: "
                f"{len(errors)} errors"
            )
            for err in errors:
                logger.error(f"  - {err}")
            return False, errors

        logger.info(f"Generation data validation succeeded for campaign {campaign_id}")
        return True, []


def validate_template_before_generation(
    template: Dict[str, Any],
    data: Dict[str, Any],
    campaign_id: UUID,
    strict: bool = True
) -> None:
    """
    Fonction helper pour valider template + données avant génération.

    Args:
        template: Configuration du template
        data: Données de la campagne
        campaign_id: ID de la campagne
        strict: Si True, lève exception si erreurs

    Raises:
        TemplateValidationError: Si validation échoue en mode strict
    """
    validator = TemplateValidator()

    # Valider le template
    template_valid, template_errors = validator.validate_template(template, strict=strict)

    # Valider les données
    data_valid, data_errors = validator.validate_generation_data(campaign_id, data)

    all_errors = template_errors + data_errors

    if all_errors:
        if strict:
            error_msg = "\n".join([f"- {err}" for err in all_errors])
            raise TemplateValidationError(
                f"Pre-generation validation failed:\n{error_msg}"
            )
        else:
            logger.warning(
                f"Pre-generation validation warnings: {len(all_errors)} issues"
            )

    logger.info("Pre-generation validation passed")
