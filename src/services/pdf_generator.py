"""
Service de génération de PDF avec WeasyPrint.

Transforme le HTML généré par le widget renderer en PDF de haute qualité.
"""

from typing import Dict, Any, Optional
from pathlib import Path
import logging
from io import BytesIO
from datetime import datetime
import hashlib

try:
    from weasyprint import HTML, CSS
    from weasyprint.text.fonts import FontConfiguration
    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False
    logging.warning("WeasyPrint not installed. PDF generation will not work.")

from .widget_renderer import render_template_to_html

logger = logging.getLogger(__name__)


class PDFGenerator:
    """Générateur de PDF à partir de templates HTML."""

    def __init__(self, output_dir: Optional[Path] = None):
        """
        Initialise le générateur PDF.

        Args:
            output_dir: Répertoire de sortie pour les PDFs générés
        """
        if not WEASYPRINT_AVAILABLE:
            raise RuntimeError("WeasyPrint is not installed. Install with: pip install weasyprint")

        self.output_dir = output_dir or Path("storage/reports")
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Configuration des polices
        self.font_config = FontConfiguration()

    def generate_pdf(
        self,
        template: Dict[str, Any],
        data: Dict[str, Any],
        filename: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Génère un PDF à partir d'un template et de données.

        Args:
            template: Configuration du template
            data: Données du rapport
            filename: Nom du fichier de sortie (optionnel)

        Returns:
            Dict avec file_path, file_size_bytes, checksum, page_count
        """
        logger.info(f"Génération PDF pour template: {template.get('name', 'Unknown')}")

        start_time = datetime.now()

        # 1. Générer le HTML
        html_content = render_template_to_html(template, data)

        # 2. Générer le nom de fichier si non fourni
        if not filename:
            report_id = data.get("report", {}).get("id", "unknown")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"report_{report_id}_{timestamp}.pdf"

        file_path = self.output_dir / filename

        # 3. CSS additionnel pour WeasyPrint
        additional_css = CSS(string="""
            @page {
                margin: 0;
            }

            body {
                margin: 0;
                padding: 0;
            }

            /* Optimisations pour impression */
            @media print {
                .no-print {
                    display: none;
                }
            }

            /* Support des couleurs pour impression */
            * {
                -webkit-print-color-adjust: exact !important;
                print-color-adjust: exact !important;
                color-adjust: exact !important;
            }
        """)

        # 4. Conversion HTML → PDF
        try:
            html_doc = HTML(string=html_content)
            pdf_bytes = html_doc.write_pdf(
                stylesheets=[additional_css],
                font_config=self.font_config
            )

            # 5. Sauvegarder le PDF
            with open(file_path, 'wb') as f:
                f.write(pdf_bytes)

            # 6. Calculer les métadonnées
            file_size = len(pdf_bytes)
            checksum = hashlib.sha256(pdf_bytes).hexdigest()

            # Compter les pages (approximatif)
            page_count = self._count_pages(html_content)

            generation_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)

            logger.info(f"PDF généré: {file_path} ({file_size} bytes, {page_count} pages, {generation_time_ms}ms)")

            return {
                "file_path": str(file_path),
                "file_name": filename,
                "file_size_bytes": file_size,
                "file_checksum": checksum,
                "page_count": page_count,
                "generation_time_ms": generation_time_ms
            }

        except Exception as e:
            logger.error(f"Erreur lors de la génération PDF: {str(e)}", exc_info=True)
            raise

    def generate_pdf_bytes(
        self,
        template: Dict[str, Any],
        data: Dict[str, Any]
    ) -> bytes:
        """
        Génère un PDF en mémoire (bytes) sans le sauvegarder.

        Args:
            template: Configuration du template
            data: Données du rapport

        Returns:
            Bytes du PDF généré
        """
        logger.info(f"Génération PDF en mémoire pour template: {template.get('name', 'Unknown')}")

        # Générer le HTML
        html_content = render_template_to_html(template, data)

        # CSS additionnel
        additional_css = CSS(string="""
            @page { margin: 0; }
            body { margin: 0; padding: 0; }
            * { -webkit-print-color-adjust: exact !important; }
        """)

        # Conversion HTML → PDF
        try:
            html_doc = HTML(string=html_content)
            pdf_bytes = html_doc.write_pdf(
                stylesheets=[additional_css],
                font_config=self.font_config
            )

            logger.info(f"PDF généré en mémoire ({len(pdf_bytes)} bytes)")
            return pdf_bytes

        except Exception as e:
            logger.error(f"Erreur lors de la génération PDF: {str(e)}", exc_info=True)
            raise

    def _count_pages(self, html_content: str) -> int:
        """
        Compte approximativement le nombre de pages dans le HTML.

        Args:
            html_content: Contenu HTML

        Returns:
            Nombre estimé de pages
        """
        # Compter les page-break-after
        page_breaks = html_content.count('page-break-after')

        # Estimer les pages basées sur la longueur du contenu
        estimated_pages = max(1, (len(html_content) // 5000) + page_breaks)

        return estimated_pages

    def cleanup_old_reports(self, days: int = 30) -> int:
        """
        Nettoie les rapports générés depuis plus de X jours.

        Args:
            days: Nombre de jours de rétention

        Returns:
            Nombre de fichiers supprimés
        """
        import time

        now = time.time()
        cutoff = now - (days * 86400)
        deleted = 0

        for pdf_file in self.output_dir.glob("*.pdf"):
            if pdf_file.stat().st_mtime < cutoff:
                pdf_file.unlink()
                deleted += 1
                logger.info(f"Rapport supprimé: {pdf_file.name}")

        logger.info(f"{deleted} rapports supprimés (> {days} jours)")
        return deleted


class PDFPreviewGenerator:
    """Générateur de previews (thumbnails) pour les PDFs."""

    def __init__(self):
        """Initialise le générateur de previews."""
        try:
            from pdf2image import convert_from_bytes
            self.pdf2image_available = True
        except ImportError:
            self.pdf2image_available = False
            logger.warning("pdf2image not installed. Preview generation unavailable.")

    def generate_preview(
        self,
        pdf_bytes: bytes,
        page: int = 1,
        dpi: int = 150
    ) -> Optional[bytes]:
        """
        Génère une image preview de la première page du PDF.

        Args:
            pdf_bytes: Bytes du PDF
            page: Numéro de page (1-indexed)
            dpi: Résolution de l'image

        Returns:
            Bytes de l'image PNG ou None si impossible
        """
        if not self.pdf2image_available:
            logger.warning("pdf2image not available, cannot generate preview")
            return None

        try:
            from pdf2image import convert_from_bytes
            from io import BytesIO

            # Convertir la première page en image
            images = convert_from_bytes(
                pdf_bytes,
                first_page=page,
                last_page=page,
                dpi=dpi
            )

            if not images:
                return None

            # Convertir l'image en bytes
            img_buffer = BytesIO()
            images[0].save(img_buffer, format='PNG')
            img_bytes = img_buffer.getvalue()

            logger.info(f"Preview générée ({len(img_bytes)} bytes)")
            return img_bytes

        except Exception as e:
            logger.error(f"Erreur lors de la génération de preview: {str(e)}")
            return None


def validate_pdf(pdf_bytes: bytes) -> bool:
    """
    Valide qu'un fichier est bien un PDF valide.

    Args:
        pdf_bytes: Bytes du fichier

    Returns:
        True si PDF valide, False sinon
    """
    # Vérifier la signature PDF
    if not pdf_bytes.startswith(b'%PDF-'):
        return False

    # Vérifier la présence de EOF
    if b'%%EOF' not in pdf_bytes[-1024:]:
        return False

    return True


def merge_pdfs(pdf_files: list[bytes]) -> bytes:
    """
    Fusionne plusieurs PDFs en un seul.

    Args:
        pdf_files: Liste de bytes de PDFs

    Returns:
        Bytes du PDF fusionné
    """
    try:
        from PyPDF2 import PdfMerger

        merger = PdfMerger()

        for pdf_bytes in pdf_files:
            merger.append(BytesIO(pdf_bytes))

        output = BytesIO()
        merger.write(output)
        merged_bytes = output.getvalue()

        logger.info(f"{len(pdf_files)} PDFs fusionnés ({len(merged_bytes)} bytes)")
        return merged_bytes

    except ImportError:
        logger.error("PyPDF2 not installed. Cannot merge PDFs.")
        raise RuntimeError("PyPDF2 required for PDF merging")
    except Exception as e:
        logger.error(f"Erreur lors de la fusion PDF: {str(e)}")
        raise
