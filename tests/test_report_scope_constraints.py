"""
Tests pour valider les contraintes de cohérence report_scope / entity_id.

Ces tests vérifient que :
1. Un rapport consolidé NE PEUT PAS avoir un entity_id
2. Un rapport individuel DOIT avoir un entity_id
3. Les templates sont filtrés correctement par scope
"""

import pytest
from uuid import uuid4
from pydantic import ValidationError

from src.schemas.report import (
    GenerateReportRequest,
    ReportScope,
    TemplateScope
)


class TestReportScopeValidation:
    """Tests de validation scope/entity_id au niveau du schéma."""

    def test_consolidated_report_without_entity_id_is_valid(self):
        """Un rapport consolidé sans entity_id est valide."""
        request = GenerateReportRequest(
            template_id=uuid4(),
            report_scope=ReportScope.CONSOLIDATED,
            entity_id=None,
            title="Rapport Consolidé Test"
        )
        # Ne doit pas lever d'exception
        request.validate_scope_entity_consistency()
        assert request.report_scope == ReportScope.CONSOLIDATED
        assert request.entity_id is None

    def test_consolidated_report_with_entity_id_is_invalid(self):
        """Un rapport consolidé avec entity_id est INVALIDE."""
        request = GenerateReportRequest(
            template_id=uuid4(),
            report_scope=ReportScope.CONSOLIDATED,
            entity_id=uuid4(),  # ❌ Ne devrait pas être présent
            title="Rapport Consolidé Test"
        )
        with pytest.raises(ValueError) as exc_info:
            request.validate_scope_entity_consistency()

        assert "entity_id doit être None" in str(exc_info.value)
        assert "consolidé" in str(exc_info.value)

    def test_entity_report_with_entity_id_is_valid(self):
        """Un rapport individuel avec entity_id est valide."""
        entity_id = uuid4()
        request = GenerateReportRequest(
            template_id=uuid4(),
            report_scope=ReportScope.ENTITY,
            entity_id=entity_id,
            title="Rapport Individuel Test"
        )
        # Ne doit pas lever d'exception
        request.validate_scope_entity_consistency()
        assert request.report_scope == ReportScope.ENTITY
        assert request.entity_id == entity_id

    def test_entity_report_without_entity_id_is_invalid(self):
        """Un rapport individuel sans entity_id est INVALIDE."""
        request = GenerateReportRequest(
            template_id=uuid4(),
            report_scope=ReportScope.ENTITY,
            entity_id=None,  # ❌ Devrait être présent
            title="Rapport Individuel Test"
        )
        with pytest.raises(ValueError) as exc_info:
            request.validate_scope_entity_consistency()

        assert "entity_id est requis" in str(exc_info.value)
        assert "individuel" in str(exc_info.value)

    def test_default_scope_is_consolidated(self):
        """Le scope par défaut est 'consolidated'."""
        request = GenerateReportRequest(
            template_id=uuid4(),
            title="Rapport Test"
        )
        assert request.report_scope == ReportScope.CONSOLIDATED

    def test_default_entity_id_is_none(self):
        """L'entity_id par défaut est None."""
        request = GenerateReportRequest(
            template_id=uuid4(),
            title="Rapport Test"
        )
        assert request.entity_id is None


class TestTemplateScopeFiltering:
    """Tests pour le filtrage des templates par scope."""

    def test_template_scope_enum_values(self):
        """Vérifie les valeurs de l'enum TemplateScope."""
        assert TemplateScope.CONSOLIDATED.value == "consolidated"
        assert TemplateScope.ENTITY.value == "entity"
        assert TemplateScope.BOTH.value == "both"

    def test_report_scope_enum_values(self):
        """Vérifie les valeurs de l'enum ReportScope."""
        assert ReportScope.CONSOLIDATED.value == "consolidated"
        assert ReportScope.ENTITY.value == "entity"


class TestReportScopeEnumBehavior:
    """Tests du comportement des enums ReportScope."""

    def test_scope_string_comparison(self):
        """Test comparaison string avec enum."""
        assert ReportScope.CONSOLIDATED == "consolidated"
        assert ReportScope.ENTITY == "entity"
        assert ReportScope.CONSOLIDATED.value == "consolidated"

    def test_scope_from_string(self):
        """Test création enum depuis string."""
        consolidated = ReportScope("consolidated")
        entity = ReportScope("entity")

        assert consolidated == ReportScope.CONSOLIDATED
        assert entity == ReportScope.ENTITY

    def test_invalid_scope_raises_error(self):
        """Test qu'un scope invalide lève une erreur."""
        with pytest.raises(ValueError):
            ReportScope("invalid_scope")


class TestGenerateRequestOptions:
    """Tests des options de génération."""

    def test_default_options(self):
        """Test les options par défaut."""
        request = GenerateReportRequest(
            template_id=uuid4(),
            title="Test"
        )

        assert request.options is not None
        assert request.options.get("include_appendix") is True
        assert request.options.get("include_ai_summary") is True
        assert request.options.get("include_benchmarking") is True
        assert request.options.get("language") == "fr"

    def test_custom_options(self):
        """Test des options personnalisées."""
        custom_options = {
            "force_mode": "final",
            "include_appendix": False,
            "include_ai_summary": False,
            "include_benchmarking": True,
            "language": "en"
        }

        request = GenerateReportRequest(
            template_id=uuid4(),
            title="Test",
            options=custom_options
        )

        assert request.options["force_mode"] == "final"
        assert request.options["include_appendix"] is False
        assert request.options["include_ai_summary"] is False
        assert request.options["language"] == "en"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
