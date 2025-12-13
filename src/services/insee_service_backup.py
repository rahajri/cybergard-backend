# backend/src/services/insee_service.py
"""
Service d'intégration avec l'API INSEE Sirene
Récupération automatique des informations d'entreprise via SIRET
"""

import httpx
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class INSEEService:
    """
    Service pour interroger l'API INSEE Sirene
    Documentation: https://api.insee.fr/catalogue/
    """
    
            
    BASE_URL = "https://api.insee.fr/entreprises/sirene/V3"
    
    def __init__(
        self, 
        api_key: Optional[str] = None,
        timeout: int = 10
    ):
        """
        Initialise le service INSEE
        
        Args:
            api_key: Clé d'API INSEE (si None, utilise settings)
            timeout: Timeout des requêtes en secondes
        """
        # Import settings ici pour éviter les imports circulaires
        try:
            from src.config import settings
            self.api_key = api_key or getattr(settings, 'insee_api_key', None)
            self.timeout = timeout or getattr(settings, 'insee_timeout_seconds', 10)
        except ImportError:
            logger.warning("Settings non disponible, utilisation des valeurs par défaut")
                        self.api_key = api_key
            self.timeout = timeout
    
    def get_headers(self) -> dict:
        """
        Construit les headers pour les requêtes INSEE
        """
        headers = {
            "Accept": "application/json"
        }
        
        if self.api_key:
            headers["X-INSEE-Api-Key-Integration"] = self.api_key
            logger.debug("Utilisation de la clé API INSEE")
        else:
            logger.debug("Pas de clé API INSEE, accès anonyme")
        
        return headers
    
    async def get_establishment_by_siret(self, siret: str) -> Optional[Dict[str, Any]]:
        """
        Récupère les informations d'un établissement via son SIRET
        
        Args:
            siret: Numéro SIRET à 14 chiffres
            
        Returns:
            Dictionnaire contenant les données de l'établissement ou None
        """
        # Nettoyer le SIRET (enlever espaces/tirets)
        siret = siret.replace(" ", "").replace("-", "")
        
                        
        if not siret or len(siret) != 14:
            logger.error(f"SIRET invalide: {siret}")
            return None
        
        try:
            headers = self.get_headers()
            url = f"{self.BASE_URL}/siret/{siret}"
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, headers=headers)
                
                if response.status_code == 200:
                    data = response.json()
                    logger.info(f"✅ Données INSEE récupérées pour SIRET {siret}")
                    return data
                elif response.status_code == 404:
                    logger.warning(f"SIRET non trouvé dans INSEE: {siret}")
                    return None
                elif response.status_code == 429:
                    logger.error("Quota API INSEE dépassé")
                    return None
                else:
                    logger.error(f"Erreur API INSEE: {response.status_code} - {response.text}")
                    return None
                    
        except httpx.TimeoutException:
            logger.error(f"Timeout lors de la requête INSEE pour SIRET {siret}")
            return None
        except Exception as e:
            logger.error(f"Erreur lors de l'appel API INSEE: {e}")
            return None
    
    def parse_establishment_data(self, insee_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse les données brutes de l'API INSEE en format exploitable
        
        Args:
            insee_data: Données brutes de l'API INSEE
            
        Returns:
            Dictionnaire avec les champs normalisés
        """
        if not insee_data or "etablissement" not in insee_data:
            return {}
        
        etab = insee_data.get("etablissement", {})
        unite_legale = etab.get("uniteLegale", {})
        adresse = etab.get("adresseEtablissement", {})
        periode = etab.get("periodesEtablissement", [{}])[0] if etab.get("periodesEtablissement") else {}
        
        return {
            # Identifiants
            "siret": etab.get("siret"),
            "siren": etab.get("siren"),
            "nic": etab.get("nic"),
            
            # Noms
            "legal_name": unite_legale.get("denominationUniteLegale") or 
                         f"{unite_legale.get('prenom1UniteLegale', '')} {unite_legale.get('nomUniteLegale', '')}".strip(),
            "trade_name": etab.get("denominationUsuelleEtablissement") or 
                         periode.get("enseigne1Etablissement"),
            
            # Activité
            "ape_code": etab.get("activitePrincipaleEtablissement"),
            "ape_label": periode.get("activitePrincipaleEtablissement"),
            
            # Adresse
            "address_line1": self._build_address_line1(adresse),
            "address_line2": adresse.get("complementAdresseEtablissement"),
            "postal_code": adresse.get("codePostalEtablissement"),
            "city": adresse.get("libelleCommuneEtablissement"),
            "region": adresse.get("libelleRegionEtablissement"),
            "country_code": "FR",
            
            # Effectif
            "employee_count": self._parse_employee_count(
                periode.get("trancheEffectifsEtablissement")
            ),
            "employee_range": periode.get("trancheEffectifsEtablissement"),
            
            # Dates
            "creation_date": etab.get("dateCreationEtablissement"),
            "start_date": periode.get("dateDebut"),
            
            # Statut
            "is_siege": etab.get("etablissementSiege", False),
            "etat_administratif": etab.get("etatAdministratifEtablissement"),
            
            # Catégorie juridique
            "legal_category_code": unite_legale.get("categorieJuridiqueUniteLegale"),
            
            # Données brutes complètes
            "raw_insee_data": insee_data
        }
    
    def _build_address_line1(self, adresse: Dict[str, Any]) -> str:
        """Construit la ligne d'adresse 1"""
        parts = []
        
        if adresse.get("numeroVoieEtablissement"):
            parts.append(str(adresse["numeroVoieEtablissement"]))
        if adresse.get("indiceRepetitionEtablissement"):
            parts.append(adresse["indiceRepetitionEtablissement"])
        if adresse.get("typeVoieEtablissement"):
            parts.append(adresse["typeVoieEtablissement"])
        if adresse.get("libelleVoieEtablissement"):
            parts.append(adresse["libelleVoieEtablissement"])
        
        return " ".join(parts).strip()
    
    def _parse_employee_count(self, tranche: Optional[str]) -> Optional[int]:
        """
        Convertit une tranche d'effectifs en nombre approximatif
        
        Tranches INSEE:
        - NN: Non employeur
        - 00: 0 salarié
        - 01: 1 ou 2 salariés
        - 02: 3 à 5 salariés
        - 03: 6 à 9 salariés
        - 11: 10 à 19 salariés
        - 12: 20 à 49 salariés
        - 21: 50 à 99 salariés
        - 22: 100 à 199 salariés
        - 31: 200 à 249 salariés
        - 32: 250 à 499 salariés
        - 41: 500 à 999 salariés
        - 42: 1 000 à 1 999 salariés
        - 51: 2 000 à 4 999 salariés
        - 52: 5 000 à 9 999 salariés
        - 53: 10 000 salariés et plus
        """
        if not tranche:
            return None
        
        mapping = {
            "NN": 0, "00": 0,
            "01": 2, "02": 4, "03": 8,
            "11": 15, "12": 35,
            "21": 75, "22": 150,
            "31": 225, "32": 375,
            "41": 750, "42": 1500,
            "51": 3500, "52": 7500,
            "53": 15000
        }
        
        return mapping.get(tranche)
    
    async def enrich_entity_with_insee(
        self, 
        entity_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Enrichit les données d'une entité avec les informations INSEE
        
        Args:
            entity_data: Données de base de l'entité (doit contenir un SIRET)
            
        Returns:
            Données enrichies avec les infos INSEE
        """
        siret = entity_data.get("siret")
        if not siret:
            logger.warning("Pas de SIRET fourni, impossible d'enrichir avec INSEE")
            return entity_data
        
        # Récupérer les données INSEE
        insee_data = await self.get_establishment_by_siret(siret)
        if not insee_data:
            logger.warning(f"Aucune donnée INSEE trouvée pour SIRET {siret}")
            return entity_data
        
        # Parser les données
        parsed_data = self.parse_establishment_data(insee_data)
        
        # Fusionner avec les données existantes (les données manuelles ont priorité)
        enriched_data = {**parsed_data, **entity_data}
        enriched_data["insee_data"] = parsed_data.get("raw_insee_data")
        enriched_data["insee_last_sync"] = datetime.utcnow()
        
        logger.info(f"✅ Entité enrichie avec données INSEE pour SIRET {siret}")
        return enriched_data


# Instance singleton
_insee_service: Optional[INSEEService] = None


def get_insee_service() -> INSEEService:
    """Retourne l'instance singleton du service INSEE"""
    global _insee_service
    if _insee_service is None:
        _insee_service = INSEEService()
    return _insee_service