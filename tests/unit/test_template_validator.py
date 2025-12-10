"""
Tests unitaires pour TemplateValidator.

Tests de validation de la sécurité et structure des templates.
"""

import pytest
from uuid import uuid4

from src.services.template_validator import (
    TemplateValidator,
    TemplateValidationError,
    validate_template_before_generation
)


class TestTemplateValidator:
    """Tests pour TemplateValidator."""

    @pytest.fixture
    def validator(self):
        """Instance de TemplateValidator."""
        return TemplateValidator()

    @pytest.fixture
    def valid_template(self):
        """Template valide pour les tests."""
        return {
            "name": "Test Template",
            "code": "TEST_001",
            "template_type": "executive",
            "structure": [
                {
                    "widget_type": "cover",
                    "position": 0,
                    "config": {
                        "title": "Rapport d'Audit",
                        "subtitle": "%campaign.name%"
                    }
                },
                {
                    "widget_type": "title",
                    "position": 1,
                    "config": {
                        "text": "Introduction",
                        "level": 1
                    }
                },
                {
                    "widget_type": "metrics",
                    "position": 2,
                    "config": {
                        "metrics": [
                            {"label": "Score", "value_source": "stats.compliance_rate"}
                        ]
                    }
                }
            ],
            "color_scheme": {
                "primary": "#8B5CF6",
                "secondary": "#3B82F6"
            }
        }

    # ========================================================================
    # TESTS: Validation de la structure
    # ========================================================================

    def test_validate_valid_template(self, validator, valid_template):
        """Validation d'un template valide."""
        is_valid, errors = validator.validate_template(valid_template, strict=False)

        assert is_valid
        assert len(errors) == 0

    def test_validate_missing_required_field(self, validator, valid_template):
        """Erreur si champ requis manquant."""
        del valid_template['name']

        with pytest.raises(TemplateValidationError, match="Missing required field"):
            validator.validate_template(valid_template, strict=True)

    def test_validate_invalid_template_type(self, validator, valid_template):
        """Erreur si template_type invalide."""
        valid_template['template_type'] = 'invalid_type'

        with pytest.raises(TemplateValidationError, match="Invalid template_type"):
            validator.validate_template(valid_template, strict=True)

    def test_validate_empty_structure(self, validator, valid_template):
        """Erreur si structure vide."""
        valid_template['structure'] = []

        with pytest.raises(TemplateValidationError, match="structure' cannot be empty"):
            validator.validate_template(valid_template, strict=True)

    def test_validate_too_many_widgets(self, validator, valid_template):
        """Erreur si trop de widgets."""
        # Ajouter plus que MAX_WIDGETS (100)
        valid_template['structure'] = [
            {
                "widget_type": "title",
                "position": i,
                "config": {"text": f"Title {i}"}
            }
            for i in range(101)
        ]

        with pytest.raises(TemplateValidationError, match="Too many widgets"):
            validator.validate_template(valid_template, strict=True)

    # ========================================================================
    # TESTS: Validation de sécurité
    # ========================================================================

    def test_validate_detects_script_injection(self, validator, valid_template):
        """Détection d'injection de script."""
        valid_template['structure'][0]['config']['title'] = '<script>alert("XSS")</script>'

        with pytest.raises(TemplateValidationError, match="Potential security issue"):
            validator.validate_template(valid_template, strict=True)

    def test_validate_detects_javascript_protocol(self, validator, valid_template):
        """Détection de javascript: protocol."""
        valid_template['structure'][0]['config']['subtitle'] = 'javascript:void(0)'

        with pytest.raises(TemplateValidationError, match="Potential security issue"):
            validator.validate_template(valid_template, strict=True)

    def test_validate_detects_suspicious_paths(self, validator, valid_template):
        """Détection de chemins suspects."""
        valid_template['structure'][0]['config']['image'] = '../../../etc/passwd'

        with pytest.raises(TemplateValidationError, match="Suspicious file path"):
            validator.validate_template(valid_template, strict=True)

    def test_validate_template_size_limit(self, validator):
        """Erreur si template trop volumineux."""
        # Créer un template énorme
        huge_template = {
            "name": "Huge Template",
            "code": "HUGE",
            "template_type": "executive",
            "structure": [
                {
                    "widget_type": "paragraph",
                    "position": i,
                    "config": {
                        "text": "A" * 10000  # 10KB par widget
                    }
                }
                for i in range(300)  # 3MB total
            ]
        }

        with pytest.raises(TemplateValidationError, match="Template too large"):
            validator.validate_template(huge_template, strict=True)

    # ========================================================================
    # TESTS: Validation des widgets
    # ========================================================================

    def test_validate_widget_missing_type(self, validator, valid_template):
        """Erreur si widget sans widget_type."""
        valid_template['structure'][0] = {
            "position": 0,
            "config": {}
        }

        with pytest.raises(TemplateValidationError, match="missing 'widget_type'"):
            validator.validate_template(valid_template, strict=True)

    def test_validate_widget_invalid_type(self, validator, valid_template):
        """Erreur si widget_type invalide."""
        valid_template['structure'][0]['widget_type'] = 'invalid_widget'

        with pytest.raises(TemplateValidationError, match="invalid widget_type"):
            validator.validate_template(valid_template, strict=True)

    def test_validate_widget_missing_position(self, validator, valid_template):
        """Erreur si widget sans position."""
        del valid_template['structure'][0]['position']

        with pytest.raises(TemplateValidationError, match="missing 'position'"):
            validator.validate_template(valid_template, strict=True)

    def test_validate_widget_duplicate_position(self, validator, valid_template):
        """Erreur si positions dupliquées."""
        valid_template['structure'][1]['position'] = 0  # Même position que widget 0

        with pytest.raises(TemplateValidationError, match="Duplicate position"):
            validator.validate_template(valid_template, strict=True)

    def test_validate_widget_missing_config(self, validator, valid_template):
        """Erreur si widget sans config."""
        del valid_template['structure'][0]['config']

        with pytest.raises(TemplateValidationError, match="missing 'config'"):
            validator.validate_template(valid_template, strict=True)

    def test_validate_cover_missing_title(self, validator, valid_template):
        """Erreur si widget cover sans title."""
        valid_template['structure'][0]['config'] = {}  # Pas de title

        with pytest.raises(TemplateValidationError, match="cover.*missing 'title'"):
            validator.validate_template(valid_template, strict=True)

    def test_validate_title_too_long(self, validator, valid_template):
        """Erreur si texte de title trop long."""
        valid_template['structure'][1]['config']['text'] = "A" * 15000  # > MAX_STRING_LENGTH

        with pytest.raises(TemplateValidationError, match="text too long"):
            validator.validate_template(valid_template, strict=True)

    def test_validate_html_block_with_script(self, validator):
        """Erreur si html_block contient du JavaScript."""
        template = {
            "name": "Test",
            "code": "TEST",
            "template_type": "custom",
            "structure": [
                {
                    "widget_type": "html_block",
                    "position": 0,
                    "config": {
                        "html": '<div><script>alert("XSS")</script></div>'
                    }
                }
            ]
        }

        with pytest.raises(TemplateValidationError, match="JavaScript not allowed"):
            validator.validate_template(template, strict=True)

    # ========================================================================
    # TESTS: Validation des variables
    # ========================================================================

    def test_validate_allowed_variables(self, validator, valid_template):
        """Variables autorisées passent la validation."""
        valid_template['structure'][0]['config']['subtitle'] = (
            "%campaign.name% - %stats.compliance_rate%"
        )

        is_valid, errors = validator.validate_template(valid_template, strict=False)

        assert is_valid

    def test_validate_disallowed_variable(self, validator, valid_template):
        """Erreur si variable non autorisée."""
        valid_template['structure'][0]['config']['subtitle'] = "%user.password%"

        with pytest.raises(TemplateValidationError, match="Unknown or disallowed variable"):
            validator.validate_template(valid_template, strict=True)

    # ========================================================================
    # TESTS: Validation des couleurs
    # ========================================================================

    def test_validate_valid_colors(self, validator, valid_template):
        """Couleurs hex valides passent."""
        valid_template['color_scheme'] = {
            "primary": "#8B5CF6",
            "secondary": "#3B82F6",
            "danger": "#EF4444"
        }

        is_valid, errors = validator.validate_template(valid_template, strict=False)

        assert is_valid

    def test_validate_invalid_color_format(self, validator, valid_template):
        """Erreur si format de couleur invalide."""
        valid_template['color_scheme']['primary'] = 'purple'  # Pas hex

        with pytest.raises(TemplateValidationError, match="Invalid color format"):
            validator.validate_template(valid_template, strict=True)

    def test_validate_incomplete_hex_color(self, validator, valid_template):
        """Erreur si hex incomplet."""
        valid_template['color_scheme']['primary'] = '#FFF'  # 3 chars au lieu de 6

        with pytest.raises(TemplateValidationError, match="Invalid color format"):
            validator.validate_template(valid_template, strict=True)

    # ========================================================================
    # TESTS: Validation des données de génération
    # ========================================================================

    def test_validate_generation_data_valid(self, validator):
        """Données de génération valides."""
        campaign_id = uuid4()

        data = {
            'campaign': {
                'id': str(campaign_id),
                'name': 'Test Campaign'
            },
            'stats': {
                'total_questions': 100,
                'answered_questions': 80
            },
            'domains': [
                {'id': str(uuid4()), 'name': 'Domain A', 'score': 85.0}
            ]
        }

        is_valid, errors = validator.validate_generation_data(campaign_id, data)

        assert is_valid
        assert len(errors) == 0

    def test_validate_generation_data_missing_required_key(self, validator):
        """Erreur si clé requise manquante."""
        campaign_id = uuid4()

        data = {
            'campaign': {'id': str(campaign_id), 'name': 'Test'}
            # Manque 'stats' et 'domains'
        }

        is_valid, errors = validator.validate_generation_data(campaign_id, data)

        assert not is_valid
        assert any('stats' in err for err in errors)
        assert any('domains' in err for err in errors)

    def test_validate_generation_data_empty_campaign_name(self, validator):
        """Erreur si nom de campagne vide."""
        campaign_id = uuid4()

        data = {
            'campaign': {'id': str(campaign_id), 'name': ''},
            'stats': {'total_questions': 100},
            'domains': []
        }

        is_valid, errors = validator.validate_generation_data(campaign_id, data)

        assert not is_valid
        assert any("Campaign 'name' is empty" in err for err in errors)

    def test_validate_generation_data_no_questions(self, validator):
        """Erreur si pas de questions."""
        campaign_id = uuid4()

        data = {
            'campaign': {'id': str(campaign_id), 'name': 'Test'},
            'stats': {'total_questions': 0},
            'domains': []
        }

        is_valid, errors = validator.validate_generation_data(campaign_id, data)

        assert not is_valid
        assert any('no questions' in err.lower() for err in errors)

    def test_validate_generation_data_no_domains(self, validator):
        """Warning si pas de domaines."""
        campaign_id = uuid4()

        data = {
            'campaign': {'id': str(campaign_id), 'name': 'Test'},
            'stats': {'total_questions': 10},
            'domains': []
        }

        is_valid, errors = validator.validate_generation_data(campaign_id, data)

        assert not is_valid
        assert any('No domains' in err for err in errors)

    # ========================================================================
    # TESTS: Validation complète (template + données)
    # ========================================================================

    def test_validate_before_generation_success(self, valid_template):
        """Validation complète réussie."""
        campaign_id = uuid4()

        data = {
            'campaign': {'id': str(campaign_id), 'name': 'Test Campaign'},
            'stats': {'total_questions': 50},
            'domains': [{'id': str(uuid4()), 'name': 'Domain A'}]
        }

        # Ne doit pas lever d'exception
        validate_template_before_generation(
            template=valid_template,
            data=data,
            campaign_id=campaign_id,
            strict=True
        )

    def test_validate_before_generation_template_error(self, valid_template):
        """Erreur si template invalide."""
        campaign_id = uuid4()

        # Template invalide (script injection)
        valid_template['structure'][0]['config']['title'] = '<script>alert(1)</script>'

        data = {
            'campaign': {'id': str(campaign_id), 'name': 'Test'},
            'stats': {'total_questions': 50},
            'domains': [{'id': str(uuid4()), 'name': 'Domain A'}]
        }

        with pytest.raises(TemplateValidationError, match="security issue"):
            validate_template_before_generation(
                template=valid_template,
                data=data,
                campaign_id=campaign_id,
                strict=True
            )

    def test_validate_before_generation_data_error(self, valid_template):
        """Erreur si données invalides."""
        campaign_id = uuid4()

        # Données invalides (pas de questions)
        data = {
            'campaign': {'id': str(campaign_id), 'name': 'Test'},
            'stats': {'total_questions': 0},  # Problème
            'domains': []
        }

        with pytest.raises(TemplateValidationError, match="no questions"):
            validate_template_before_generation(
                template=valid_template,
                data=data,
                campaign_id=campaign_id,
                strict=True
            )

    def test_validate_non_strict_mode(self, valid_template):
        """Mode non-strict : warnings au lieu d'exceptions."""
        campaign_id = uuid4()

        # Template avec petit problème
        valid_template['structure'][0]['widget_type'] = 'invalid_type'

        data = {
            'campaign': {'id': str(campaign_id), 'name': 'Test'},
            'stats': {'total_questions': 50},
            'domains': [{'id': str(uuid4()), 'name': 'Domain A'}]
        }

        # Ne lève pas d'exception en mode non-strict
        try:
            validate_template_before_generation(
                template=valid_template,
                data=data,
                campaign_id=campaign_id,
                strict=False
            )
        except TemplateValidationError:
            pytest.fail("Should not raise in non-strict mode")


class TestTemplateValidatorEdgeCases:
    """Tests des cas limites."""

    @pytest.fixture
    def validator(self):
        return TemplateValidator()

    def test_empty_template(self, validator):
        """Template vide."""
        template = {}

        with pytest.raises(TemplateValidationError):
            validator.validate_template(template, strict=True)

    def test_none_template(self, validator):
        """Template None."""
        with pytest.raises((TemplateValidationError, AttributeError)):
            validator.validate_template(None, strict=True)

    def test_widget_config_not_dict(self, validator):
        """Config n'est pas un dict."""
        template = {
            "name": "Test",
            "code": "TEST",
            "template_type": "executive",
            "structure": [
                {
                    "widget_type": "title",
                    "position": 0,
                    "config": "not a dict"  # Erreur
                }
            ]
        }

        with pytest.raises(TemplateValidationError, match="config' must be a dict"):
            validator.validate_template(template, strict=True)

    def test_position_not_integer(self, validator):
        """Position n'est pas un entier."""
        template = {
            "name": "Test",
            "code": "TEST",
            "template_type": "executive",
            "structure": [
                {
                    "widget_type": "title",
                    "position": "first",  # String au lieu d'int
                    "config": {"text": "Title"}
                }
            ]
        }

        with pytest.raises(TemplateValidationError, match="position' must be an integer"):
            validator.validate_template(template, strict=True)
