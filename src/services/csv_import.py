# src/services/csv_import.py
from sqlalchemy.orm import Session
from sqlalchemy import text
import pandas as pd
import logging
from datetime import datetime
from typing import Dict, List, Optional

from ..models.audit import Framework, Domain, Requirement
from ..database import SessionLocal

logger = logging.getLogger(__name__)

class CSVImportService:
    def __init__(self, db: Session):
        self.db = db
    
    def import_referentiel(
        self,
        df: pd.DataFrame,
        code_referentiel: str,
        nom_referentiel: str,
        version: str = "1.0",
        editeur: str = "",
        langue: str = "fr"
    ) -> Dict:
        """Importer un référentiel CSV en base de données"""
        
        try:
            # 1. Créer le Framework
            framework = self._create_framework(
                code_referentiel, nom_referentiel, version, editeur, langue
            )
            
            # 2. Extraire et créer les sections (chapitres)
            sections_map = self._create_sections(df, framework.id)
            
            # 3. Créer les requirements
            requirements = self._create_requirements(df, framework.id, sections_map)
            
            # 4. Commit de toutes les données
            self.db.commit()
            
            stats = {
                "framework_id": str(framework.id),
                "sections_created": len(sections_map),
                "requirements_created": len(requirements),
                "total_rows_processed": len(df)
            }
            
            logger.info(f"Import réussi pour {code_referentiel}: {stats}")
            return stats
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Erreur import référentiel {code_referentiel}: {str(e)}")
            raise
    
    def _create_framework(self, code: str, name: str, version: str, publisher: str, language: str) -> Framework:
        """Créer le framework principal"""
        
        # Vérifier si le framework existe déjà
        existing = self.db.query(Framework).filter_by(code=code).first()
        if existing:
            logger.warning(f"Framework {code} existe déjà, suppression de l'ancien")
            self.db.delete(existing)
            self.db.flush()
        
        framework = Framework(
            code=code,
            name=name,
            version=version,
            publisher=publisher,
            language=language,
            import_date=datetime.now(),
            is_active=True
        )
        
        self.db.add(framework)
        self.db.flush()  # Pour obtenir l'ID
        
        logger.info(f"Framework créé: {code} - {name}")
        return framework
    
    def _create_sections(self, df: pd.DataFrame, framework_id: str) -> Dict[str, str]:
        """Créer les sections (chapitres) uniques"""
        
        # Extraire tous les chapitres uniques
        chapitres_uniques = df['chapitre'].dropna().unique()
        sections_map = {}
        
        for chapitre in chapitres_uniques:
            # Parser le chapitre pour extraire code et titre
            section_code, title = self._parse_chapitre(chapitre)
            
            section = Section(
                framework_id=framework_id,
                section_code=section_code,
                title=title,
                description=chapitre,
                section_type="chapitre",
                hierarchy_level=1
            )
            
            self.db.add(section)
            self.db.flush()  # Pour obtenir l'ID
            
            sections_map[chapitre] = str(section.id)
            logger.debug(f"Section créée: {section_code} - {title}")
        
        return sections_map
    
    def _parse_chapitre(self, chapitre: str) -> tuple[str, str]:
        """Parser un chapitre pour extraire code et titre"""
        if " - " in chapitre:
            parts = chapitre.split(" - ", 1)
            return parts[0].strip(), parts[1].strip()
        else:
            return chapitre[:20], chapitre  # Fallback
    
    def _create_requirements(self, df: pd.DataFrame, framework_id: str, sections_map: Dict[str, str]) -> List[Requirement]:
        """Créer toutes les exigences"""
        
        requirements = []
        
        for index, row in df.iterrows():
            try:
                # Récupérer l'ID de la section
                section_id = sections_map.get(row.get('chapitre'))
                if not section_id:
                    logger.warning(f"Section non trouvée pour la ligne {index}: {row.get('chapitre')}")
                    continue
                
                # Parser les tags
                tags = []
                if pd.notna(row.get('tags')):
                    tags = [tag.strip() for tag in str(row['tags']).split(',')]
                
                requirement = Requirement(
                    framework_id=framework_id,
                    section_id=section_id,
                    official_code=str(row.get('code_officiel', '')),
                    title=str(row.get('titre', '')),
                    requirement_text=str(row.get('description', '')),
                    chapter_path=str(row.get('chapitre', '')),
                    domain=str(row.get('domaine', '')) if pd.notna(row.get('domaine')) else None,
                    subdomain=str(row.get('sous_domaine', '')) if pd.notna(row.get('sous_domaine')) else None,
                    tags=tags,
                    risk_level=str(row.get('niveau_risque', 'medium')).lower() if pd.notna(row.get('niveau_risque')) else 'medium',
                    compliance_obligation=str(row.get('obligation_conformite', 'mandatory')).lower() if pd.notna(row.get('obligation_conformite')) else 'mandatory'
                )
                
                self.db.add(requirement)
                requirements.append(requirement)
                
            except Exception as e:
                logger.error(f"Erreur création requirement ligne {index}: {str(e)}")
                continue
        
        logger.info(f"Requirements créés: {len(requirements)}")
        return requirements

def import_csv_to_database(
    df: pd.DataFrame,
    code_referentiel: str,
    nom_referentiel: str,
    version: str = "1.0",
    editeur: str = "",
    langue: str = "fr"
) -> Dict:
    """Fonction helper pour importer un CSV"""
    
    db = SessionLocal()
    try:
        service = CSVImportService(db)
        return service.import_referentiel(
            df, code_referentiel, nom_referentiel, version, editeur, langue
        )
    finally:
        db.close()