"""
Tests unitaires pour ReportService.

Tests de la logique métier de génération de rapports :
- Détermination du mode (DRAFT vs FINAL)
- Collecte des données
- Calcul des statistiques et scores
- Résolution des variables
- Cache des graphiques
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from uuid import uuid4
from datetime import datetime, timezone

from src.services.report_service import ReportService
from src.schemas.report import GenerationMode


class TestReportService:
    """Tests pour ReportService."""

    @pytest.fixture
    def mock_db(self):
        """Mock de session database."""
        db = Mock()
        db.execute = Mock()
        db.commit = Mock()
        db.rollback = Mock()
        return db

    @pytest.fixture
    def report_service(self, mock_db):
        """Instance de ReportService avec mock DB."""
        return ReportService(db=mock_db)

    # ========================================================================
    # TESTS: Détermination du mode de génération
    # ========================================================================

    def test_determine_mode_draft_when_campaign_in_progress(
        self, report_service, mock_db
    ):
        """Mode DRAFT si campagne status='in_progress'."""
        campaign_id = uuid4()

        # Mock campaign avec status in_progress
        mock_campaign = Mock()
        mock_campaign.id = campaign_id
        mock_campaign.status = 'in_progress'

        mock_result = Mock()
        mock_result.scalar_one_or_none = Mock(return_value=mock_campaign)
        mock_db.execute.return_value = mock_result

        mode = report_service.determine_generation_mode(campaign_id)

        assert mode == GenerationMode.DRAFT

    def test_determine_mode_draft_when_pending_answers(
        self, report_service, mock_db
    ):
        """Mode DRAFT si des réponses sont en attente."""
        campaign_id = uuid4()

        # Mock campaign completed
        mock_campaign = Mock()
        mock_campaign.id = campaign_id
        mock_campaign.status = 'completed'

        # Premier appel: campaign
        mock_result1 = Mock()
        mock_result1.scalar_one_or_none = Mock(return_value=mock_campaign)

        # Deuxième appel: pending count = 5
        mock_result2 = Mock()
        mock_result2.scalar = Mock(return_value=5)

        mock_db.execute.side_effect = [mock_result1, mock_result2]

        mode = report_service.determine_generation_mode(campaign_id)

        assert mode == GenerationMode.DRAFT

    def test_determine_mode_final_when_completed_and_validated(
        self, report_service, mock_db
    ):
        """Mode FINAL si campagne completed et toutes réponses validées."""
        campaign_id = uuid4()

        # Mock campaign frozen
        mock_campaign = Mock()
        mock_campaign.id = campaign_id
        mock_campaign.status = 'frozen'

        # Premier appel: campaign
        mock_result1 = Mock()
        mock_result1.scalar_one_or_none = Mock(return_value=mock_campaign)

        # Deuxième appel: pending count = 0
        mock_result2 = Mock()
        mock_result2.scalar = Mock(return_value=0)

        mock_db.execute.side_effect = [mock_result1, mock_result2]

        mode = report_service.determine_generation_mode(campaign_id)

        assert mode == GenerationMode.FINAL

    def test_determine_mode_draft_on_error(
        self, report_service, mock_db
    ):
        """Mode DRAFT par défaut si erreur."""
        campaign_id = uuid4()

        # Simuler erreur DB
        mock_db.execute.side_effect = Exception("DB connection failed")

        mode = report_service.determine_generation_mode(campaign_id)

        # En cas d'erreur, mode DRAFT (plus sûr)
        assert mode == GenerationMode.DRAFT

    # ========================================================================
    # TESTS: Collecte des données
    # ========================================================================

    def test_collect_campaign_data_success(
        self, report_service, mock_db
    ):
        """Collecte des données réussie."""
        campaign_id = uuid4()

        # Mock campaign
        mock_campaign = Mock()
        mock_campaign.id = campaign_id
        mock_campaign.title = "Test Campaign"
        mock_campaign.description = "Test description"
        mock_campaign.status = "in_progress"
        mock_campaign.launch_date = datetime(2024, 1, 1)
        mock_campaign.due_date = datetime(2024, 12, 31)

        mock_result = Mock()
        mock_result.scalar_one_or_none = Mock(return_value=mock_campaign)
        mock_db.execute.return_value = mock_result

        # Mock des méthodes internes
        with patch.object(report_service, '_calculate_statistics') as mock_stats, \
             patch.object(report_service, '_calculate_domain_scores') as mock_domains, \
             patch.object(report_service, '_get_non_conformities') as mock_nc, \
             patch.object(report_service, '_get_actions') as mock_actions:

            mock_stats.return_value = {
                'total_questions': 100,
                'answered_questions': 80,
                'compliance_rate': 75.0
            }

            mock_domains.return_value = [
                {'id': str(uuid4()), 'name': 'Domain 1', 'score': 80.0}
            ]

            mock_nc.return_value = ([], [])  # (major, minor)
            mock_actions.return_value = []

            data = report_service.collect_campaign_data(campaign_id)

        # Vérifications
        assert 'campaign' in data
        assert data['campaign']['title'] == "Test Campaign"
        assert 'stats' in data
        assert data['stats']['total_questions'] == 100
        assert 'domains' in data
        assert len(data['domains']) == 1
        assert 'nc_major' in data
        assert 'nc_minor' in data
        assert 'actions' in data

    def test_collect_campaign_data_campaign_not_found(
        self, report_service, mock_db
    ):
        """Erreur si campagne non trouvée."""
        campaign_id = uuid4()

        mock_result = Mock()
        mock_result.scalar_one_or_none = Mock(return_value=None)
        mock_db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="non trouvée"):
            report_service.collect_campaign_data(campaign_id)

    # ========================================================================
    # TESTS: Calcul des statistiques
    # ========================================================================

    def test_calculate_statistics_with_data(
        self, report_service, mock_db
    ):
        """Calcul des statistiques avec données."""
        campaign_id = uuid4()

        # Mock result
        mock_row = Mock()
        mock_row.total_questions = 100
        mock_row.answered_questions = 85
        mock_row.compliant = 60
        mock_row.nc_major = 10
        mock_row.nc_minor = 15
        mock_row.not_applicable = 0

        mock_result = Mock()
        mock_result.fetchone = Mock(return_value=mock_row)
        mock_db.execute.return_value = mock_result

        stats = report_service._calculate_statistics(campaign_id)

        assert stats['total_questions'] == 100
        assert stats['answered_questions'] == 85
        assert stats['pending_questions'] == 15
        assert stats['compliance_rate'] == 60.0  # 60/100
        assert stats['nc_major_count'] == 10
        assert stats['nc_minor_count'] == 15
        assert stats['compliant_count'] == 60
        assert stats['not_applicable_count'] == 0

    def test_calculate_statistics_empty_campaign(
        self, report_service, mock_db
    ):
        """Calcul avec campagne vide."""
        campaign_id = uuid4()

        # Mock result vide
        mock_row = Mock()
        mock_row.total_questions = 0
        mock_row.answered_questions = 0
        mock_row.compliant = 0
        mock_row.nc_major = 0
        mock_row.nc_minor = 0
        mock_row.not_applicable = 0

        mock_result = Mock()
        mock_result.fetchone = Mock(return_value=mock_row)
        mock_db.execute.return_value = mock_result

        stats = report_service._calculate_statistics(campaign_id)

        assert stats['total_questions'] == 0
        assert stats['compliance_rate'] == 0.0  # Pas de division par zéro

    # ========================================================================
    # TESTS: Scores par domaine
    # ========================================================================

    def test_calculate_domain_scores(
        self, report_service, mock_db
    ):
        """Calcul des scores par domaine."""
        campaign_id = uuid4()

        # Mock results
        mock_row1 = Mock()
        mock_row1.id = uuid4()
        mock_row1.name = "Domain A"
        mock_row1.code = "A"
        mock_row1.score = 85.5
        mock_row1.total_answered = 20
        mock_row1.compliant = 15
        mock_row1.nc_minor = 3
        mock_row1.nc_major = 2

        mock_row2 = Mock()
        mock_row2.id = uuid4()
        mock_row2.name = "Domain B"
        mock_row2.code = "B"
        mock_row2.score = 60.0
        mock_row2.total_answered = 10
        mock_row2.compliant = 5
        mock_row2.nc_minor = 3
        mock_row2.nc_major = 2

        mock_result = Mock()
        mock_result.fetchall = Mock(return_value=[mock_row1, mock_row2])
        mock_db.execute.return_value = mock_result

        domains = report_service._calculate_domain_scores(campaign_id)

        assert len(domains) == 2
        assert domains[0]['name'] == "Domain A"
        assert domains[0]['score'] == 85.5
        assert domains[1]['name'] == "Domain B"
        assert domains[1]['score'] == 60.0

    # ========================================================================
    # TESTS: Résolution des variables
    # ========================================================================

    def test_resolve_variables_campaign(
        self, report_service
    ):
        """Résolution des variables de campagne."""
        text = "Campagne: %campaign.name% - Status: %campaign.status%"

        data = {
            'campaign': {
                'name': 'Test Campaign',
                'status': 'in_progress'
            }
        }

        result = report_service.resolve_variables(text, data)

        assert result == "Campagne: Test Campaign - Status: in_progress"

    def test_resolve_variables_stats(
        self, report_service
    ):
        """Résolution des variables de stats."""
        text = "Total: %stats.total_questions% questions"

        data = {
            'stats': {
                'total_questions': 100
            }
        }

        result = report_service.resolve_variables(text, data)

        assert result == "Total: 100 questions"

    def test_resolve_variables_system(
        self, report_service
    ):
        """Résolution des variables système (date)."""
        text = "Généré le %report.date%"

        data = {}

        result = report_service.resolve_variables(text, data)

        # Vérifier que la date est présente (format DD/MM/YYYY)
        assert "Généré le" in result
        assert "/" in result

    def test_resolve_variables_missing_data(
        self, report_service
    ):
        """Variables non trouvées restent inchangées."""
        text = "Campagne: %campaign.name%"

        data = {}  # Pas de données campaign

        result = report_service.resolve_variables(text, data)

        # Variable non résolue reste telle quelle
        assert result == "Campagne: %campaign.name%"

    # ========================================================================
    # TESTS: Cache des graphiques
    # ========================================================================

    def test_get_cached_chart_hit(
        self, report_service, mock_db
    ):
        """Cache hit : graphique trouvé."""
        campaign_id = uuid4()
        chart_key = "radar_domains"
        chart_data = {"labels": ["A", "B"], "values": [80, 90]}

        # Mock cache entry
        mock_cache = Mock()
        mock_cache.image_data = b"fake_image_data"

        mock_result = Mock()
        mock_result.scalar_one_or_none = Mock(return_value=mock_cache)
        mock_db.execute.return_value = mock_result

        image_data = report_service.get_cached_chart(
            campaign_id, "radar", chart_key, chart_data
        )

        assert image_data == b"fake_image_data"

    def test_get_cached_chart_miss(
        self, report_service, mock_db
    ):
        """Cache miss : graphique non trouvé."""
        campaign_id = uuid4()
        chart_key = "radar_domains"
        chart_data = {"labels": ["A", "B"], "values": [80, 90]}

        # Pas de cache
        mock_result = Mock()
        mock_result.scalar_one_or_none = Mock(return_value=None)
        mock_db.execute.return_value = mock_result

        image_data = report_service.get_cached_chart(
            campaign_id, "radar", chart_key, chart_data
        )

        assert image_data is None

    def test_cache_chart_new_entry(
        self, report_service, mock_db
    ):
        """Création d'une nouvelle entrée de cache."""
        campaign_id = uuid4()
        chart_key = "radar_domains"
        chart_data = {"labels": ["A", "B"]}
        image_data = b"fake_image"

        # Pas d'entrée existante
        mock_result = Mock()
        mock_result.scalar_one_or_none = Mock(return_value=None)
        mock_db.execute.return_value = mock_result

        # Exécuter
        report_service.cache_chart(
            campaign_id=campaign_id,
            chart_type="radar",
            chart_key=chart_key,
            chart_data=chart_data,
            image_data=image_data,
            image_width=800,
            image_height=600
        )

        # Vérifier que add() et commit() ont été appelés
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    def test_cache_chart_update_existing(
        self, report_service, mock_db
    ):
        """Mise à jour d'une entrée de cache existante."""
        campaign_id = uuid4()
        chart_key = "radar_domains"
        chart_data = {"labels": ["A", "B"]}
        image_data = b"new_image"

        # Entrée existante
        mock_existing = Mock()
        mock_result = Mock()
        mock_result.scalar_one_or_none = Mock(return_value=mock_existing)
        mock_db.execute.return_value = mock_result

        # Exécuter
        report_service.cache_chart(
            campaign_id=campaign_id,
            chart_type="radar",
            chart_key=chart_key,
            chart_data=chart_data,
            image_data=image_data,
            image_width=800,
            image_height=600
        )

        # Vérifier que les champs ont été mis à jour
        assert mock_existing.image_data == image_data
        assert mock_existing.image_width == 800
        assert mock_existing.image_height == 600

        # Vérifier commit
        mock_db.commit.assert_called_once()


class TestReportServiceIntegration:
    """Tests d'intégration pour ReportService (avec vraie DB de test)."""

    @pytest.mark.integration
    def test_full_data_collection_flow(self, test_db_session):
        """
        Test du flow complet de collecte de données.

        Nécessite une DB de test avec données fixtures.
        """
        # TODO: Implémenter avec fixtures DB réelles
        pass
