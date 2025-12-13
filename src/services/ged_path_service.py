"""
Service de gestion des chemins de la GED (Gestion Électronique des Documents)

Structure organisée par campagne:
/tenant-{TENANT_ID}/
    campaigns/
        {CAMPAIGN_ID}/
            evidence/          # Pièces jointes des réponses aux questions
                file1.pdf
                screenshot.png
                export.csv
            reports/           # Rapports générés au fil du temps
                preliminary.pdf
                final.pdf
                synthesis.json
                corrections/   # Rapports de correction après actions
                    v1_2024-11-21.pdf
                    v2_2024-12-01.pdf
            metadata.json     # Métadonnées de la campagne
"""
from uuid import UUID
from typing import Literal, Optional
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

DocumentType = Literal["evidence", "report", "report_correction", "metadata"]


class GEDPathService:
    """
    Service de construction de chemins structurés pour la GED
    """

    @staticmethod
    def build_campaign_base_path(tenant_id: UUID, campaign_id: UUID) -> str:
        """
        Construit le chemin de base d'une campagne

        Format: tenant-{TENANT_ID}/campaigns/{CAMPAIGN_ID}/

        Args:
            tenant_id: ID du tenant
            campaign_id: ID de la campagne

        Returns:
            Chemin de base de la campagne
        """
        return f"tenant-{tenant_id}/campaigns/{campaign_id}"

    @staticmethod
    def build_evidence_path(
        tenant_id: UUID,
        campaign_id: UUID,
        filename: str,
        question_id: Optional[UUID] = None,
        entity_id: Optional[UUID] = None
    ) -> str:
        """
        Construit le chemin d'une pièce justificative (evidence)

        Format: tenant-{TENANT_ID}/campaigns/{CAMPAIGN_ID}/evidence/{filename}
        ou avec sous-dossiers:
        Format: tenant-{TENANT_ID}/campaigns/{CAMPAIGN_ID}/evidence/{entity_id}/{question_id}/{filename}

        Args:
            tenant_id: ID du tenant
            campaign_id: ID de la campagne
            filename: Nom du fichier
            question_id: ID de la question (optionnel, pour organisation)
            entity_id: ID de l'entité auditée (optionnel, pour organisation)

        Returns:
            Chemin complet de la pièce justificative
        """
        base = f"tenant-{tenant_id}/campaigns/{campaign_id}/evidence"

        # Structure optionnelle avec sous-dossiers pour meilleure organisation
        if entity_id and question_id:
            return f"{base}/{entity_id}/{question_id}/{filename}"
        elif entity_id:
            return f"{base}/{entity_id}/{filename}"
        else:
            return f"{base}/{filename}"

    @staticmethod
    def build_report_path(
        tenant_id: UUID,
        campaign_id: UUID,
        report_type: str,
        filename: str,
        version: Optional[str] = None
    ) -> str:
        """
        Construit le chemin d'un rapport

        Format standard: tenant-{TENANT_ID}/campaigns/{CAMPAIGN_ID}/reports/{filename}
        Format correction: tenant-{TENANT_ID}/campaigns/{CAMPAIGN_ID}/reports/corrections/{version}_{filename}

        Args:
            tenant_id: ID du tenant
            campaign_id: ID de la campagne
            report_type: Type de rapport ("preliminary", "final", "synthesis", "correction")
            filename: Nom du fichier
            version: Version du rapport (pour les corrections)

        Returns:
            Chemin complet du rapport
        """
        base = f"tenant-{tenant_id}/campaigns/{campaign_id}/reports"

        if report_type == "correction" and version:
            return f"{base}/corrections/{version}_{filename}"
        else:
            return f"{base}/{filename}"

    @staticmethod
    def build_metadata_path(tenant_id: UUID, campaign_id: UUID) -> str:
        """
        Construit le chemin du fichier de métadonnées de la campagne

        Format: tenant-{TENANT_ID}/campaigns/{CAMPAIGN_ID}/metadata.json

        Args:
            tenant_id: ID du tenant
            campaign_id: ID de la campagne

        Returns:
            Chemin complet du fichier de métadonnées
        """
        return f"tenant-{tenant_id}/campaigns/{campaign_id}/metadata.json"

    @staticmethod
    def parse_path(object_path: str) -> dict:
        """
        Parse un chemin GED pour extraire les informations

        Args:
            object_path: Chemin complet de l'objet

        Returns:
            Dictionnaire avec les composants du chemin
            {
                "tenant_id": "uuid",
                "campaign_id": "uuid",
                "document_type": "evidence|report|metadata",
                "filename": "file.pdf",
                "entity_id": "uuid" (optionnel),
                "question_id": "uuid" (optionnel),
                "report_type": "correction|standard" (optionnel),
                "version": "v1" (optionnel)
            }
        """
        parts = object_path.split("/")
        result = {}

        try:
            # Parser tenant-{UUID}/campaigns/{CAMPAIGN_ID}/...
            if parts[0].startswith("tenant-"):
                result["tenant_id"] = parts[0].replace("tenant-", "")

            if len(parts) > 2 and parts[1] == "campaigns":
                result["campaign_id"] = parts[2]

            if len(parts) > 3:
                result["document_type"] = parts[3]

                # Evidence
                if parts[3] == "evidence":
                    if len(parts) == 5:
                        # Format: evidence/{filename}
                        result["filename"] = parts[4]
                    elif len(parts) == 6:
                        # Format: evidence/{entity_id}/{filename}
                        result["entity_id"] = parts[4]
                        result["filename"] = parts[5]
                    elif len(parts) == 7:
                        # Format: evidence/{entity_id}/{question_id}/{filename}
                        result["entity_id"] = parts[4]
                        result["question_id"] = parts[5]
                        result["filename"] = parts[6]

                # Reports
                elif parts[3] == "reports":
                    if len(parts) == 5:
                        # Format: reports/{filename}
                        result["report_type"] = "standard"
                        result["filename"] = parts[4]
                    elif len(parts) == 6 and parts[4] == "corrections":
                        # Format: reports/corrections/{version}_{filename}
                        result["report_type"] = "correction"
                        filename_with_version = parts[5]
                        if "_" in filename_with_version:
                            result["version"], result["filename"] = filename_with_version.split("_", 1)
                        else:
                            result["filename"] = filename_with_version

                # Metadata
                elif parts[3] == "metadata.json":
                    result["filename"] = "metadata.json"

        except Exception as e:
            logger.error(f"Erreur parsing path '{object_path}': {e}")

        return result

    @staticmethod
    def get_campaign_from_path(object_path: str) -> Optional[str]:
        """
        Extrait l'ID de campagne d'un chemin

        Args:
            object_path: Chemin complet de l'objet

        Returns:
            ID de la campagne ou None
        """
        parsed = GEDPathService.parse_path(object_path)
        return parsed.get("campaign_id")

    @staticmethod
    def get_tenant_from_path(object_path: str) -> Optional[str]:
        """
        Extrait l'ID du tenant d'un chemin

        Args:
            object_path: Chemin complet de l'objet

        Returns:
            ID du tenant ou None
        """
        parsed = GEDPathService.parse_path(object_path)
        return parsed.get("tenant_id")

    @staticmethod
    def list_campaign_structure() -> dict:
        """
        Retourne la structure complète d'une campagne (pour documentation)

        Returns:
            Dictionnaire représentant la structure
        """
        return {
            "root": "tenant-{TENANT_ID}/",
            "campaigns": {
                "path": "campaigns/{CAMPAIGN_ID}/",
                "subdirectories": {
                    "evidence": {
                        "description": "Pièces justificatives des réponses",
                        "structure": "{entity_id}/{question_id}/{filename}",
                        "examples": [
                            "file1.pdf",
                            "screenshot.png",
                            "export.csv"
                        ]
                    },
                    "reports": {
                        "description": "Rapports générés au fil du temps",
                        "structure": "{filename} ou corrections/{version}_{filename}",
                        "examples": [
                            "preliminary.pdf",
                            "final.pdf",
                            "synthesis.json",
                            "corrections/v1_2024-11-21.pdf",
                            "corrections/v2_2024-12-01.pdf"
                        ]
                    },
                    "metadata.json": {
                        "description": "Métadonnées de la campagne",
                        "content": {
                            "campaign_id": "uuid",
                            "title": "string",
                            "created_at": "timestamp",
                            "updated_at": "timestamp",
                            "report_versions": []
                        }
                    }
                }
            }
        }
