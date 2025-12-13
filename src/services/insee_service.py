# backend/src/services/insee_service.py
"""
Service d'intégration avec l'API INSEE Sirene
Récupération automatique des informations d'entreprise via SIRET
"""

import httpx
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import logging
import os
from fastapi import HTTPException

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class INSEEService:
    def __init__(self):
        self.mode = os.getenv("INSEE_AUTH_MODE", "api_key").lower()
        self.api_base = os.getenv("INSEE_API_BASE", "https://api.insee.fr/api-sirene/3.11").rstrip("/")
        self.timeout = float(os.getenv("INSEE_TIMEOUT_SECONDS", "15"))

        # api_key mode
        self.integration_key = os.getenv("INSEE_INTEGRATION_KEY")

        # oauth2 mode
        self.token_url = os.getenv("INSEE_TOKEN_URL", "https://api.insee.fr/token").rstrip("/")
        self.client_id = os.getenv("INSEE_CLIENT_ID")
        self.client_secret = os.getenv("INSEE_CLIENT_SECRET")
        self._token = None
        self._token_exp = 0

    async def _get_oauth_token(self) -> str:
        import base64, time
        auth = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(
                self.token_url,
                data={"grant_type": "client_credentials"},
                headers={
                    "Authorization": f"Basic {auth}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
        if r.status_code != 200:
            raise HTTPException(status_code=502, detail=f"INSEE auth error {r.status_code}")
        data = r.json()
        self._token = data["access_token"]
        self._token_exp = time.time() + int(data.get("expires_in", 900)) - 30
        return self._token

    async def _auth_headers(self) -> dict:
        if self.mode == "api_key":
            if not self.integration_key:
                raise HTTPException(status_code=500, detail="INSEE integration key manquante")
            return {
                "X-INSEE-Api-Key-Integration": self.integration_key,
                "Accept": "application/json",
            }
        # oauth2
        import time
        if not self._token or time.time() >= self._token_exp:
            await self._get_oauth_token()
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }

    async def get_establishment_by_siret(self, siret: str) -> dict | None:
        # ✅ REDIS CACHE: Vérifier le cache d'abord
        from src.utils.redis_manager import redis_manager

        cache_key = f"insee:siret:{siret}"
        cached = redis_manager.get(cache_key)
        if cached:
            logger.info(f"✅ Cache HIT pour SIRET {siret}")
            return cached

        logger.info(f"⚠️ Cache MISS pour SIRET {siret} - Appel API INSEE")

        # Appel API INSEE
        url = f"{self.api_base}/siret/{siret}"
        headers = await self._auth_headers()

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.get(url, headers=headers)

        # Mapping d'erreurs clair
        if r.status_code == 404:
            return None
        if r.status_code in (401, 403):
            # Auth/clé invalide → 502 côté notre API
            raise HTTPException(status_code=502, detail=f"INSEE Unauthorized/Forbidden ({r.status_code})")
        if r.status_code != 200:
            raise HTTPException(status_code=502, detail=f"INSEE error {r.status_code}")

        # Réponse (mode API KEY) => {"header": {...}, "etablissement": {...}}
        data = r.json()

        # ✅ REDIS CACHE: Mettre en cache pour 24h (les données entreprise changent rarement)
        if data:
            redis_manager.set(cache_key, data, ttl=86400)
            logger.info(f"💾 Résultat INSEE mis en cache pour SIRET {siret}")

        return data
    
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
        
        return " ".join(parts).strip() or None
    
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

    def parse_establishment_data(self, data: dict) -> dict:
        """
        Retourne UNIQUEMENT des informations présentes dans la réponse INSEE
        + le payload brut (pour debug). Aucun calcul local.
        """
        import logging
        logger = logging.getLogger(__name__)

        etab = data.get("etablissement") or {}
        ul = etab.get("uniteLegale") or {}
        adr = etab.get("adresseEtablissement") or {}
        periodes = etab.get("periodesEtablissement") or [{}]
        p0 = periodes[0] or {}

        # Logs utiles
        logger.info("[INSEE] parse: siret=%s siren=%s cat=%s",
                    etab.get("siret"), etab.get("siren"), ul.get("categorieEntreprise"))

        return {
            # Identifiants bruts
            "siret": etab.get("siret"),
            "siren": etab.get("siren"),

            # Dénominations brutes
            "legal_name": ul.get("denominationUniteLegale") or ul.get("nomUniteLegale"),
            "trade_name": p0.get("denominationUsuelleEtablissement"),

            # Activité brute
            "ape_code": p0.get("activitePrincipaleEtablissement"),

            # Adresse brute (assemblée via helper existant)
            "address_line1": self._build_address_line1(adr),
            "postal_code": adr.get("codePostalEtablissement"),
            "city": adr.get("libelleCommuneEtablissement"),

            # Tranches effectifs brutes
            "trancheEffectifsEtablissement": etab.get("trancheEffectifsEtablissement"),
            "trancheEffectifsUniteLegale": ul.get("trancheEffectifsUniteLegale"),

            # Catégorie INSEE brute
            "enterprise_category": ul.get("categorieEntreprise"),

            # Date brute
            "creation_date": etab.get("dateCreationEtablissement"),

            # Payload brut pour debug/affichage
            "raw_insee_data": data,
        }


    async def enrich_entity_with_insee(
        self,
        entity_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Enrichit les données d'une entité avec les informations INSEE.
        - Aucune valeur calculée : on ne fait que relayer ce que renvoie l'INSEE via parse_establishment_data.
        - Si l'INSEE ne renvoie rien ou si la réponse est incomplète, on renvoie un message d'erreur explicite.
        - Ajout de logs détaillés pour le suivi complet de la requête.
        """
        siret = entity_data.get("siret")

        if not siret:
            logger.error("[INSEE] Enrichissement annulé : SIRET manquant dans entity_data.")
            raise HTTPException(status_code=400, detail="SIRET manquant pour l'enrichissement INSEE")

        logger.info(f"[INSEE] ➤ DÉBUT enrichissement pour le SIRET : {siret}")

        # Étape 1 : Appel INSEE
        try:
            logger.debug(f"[INSEE] Appel API INSEE pour le SIRET {siret}...")
            insee_data = await self.get_establishment_by_siret(siret)
        except Exception as e:
            logger.exception(f"[INSEE] ❌ Erreur lors de l'appel INSEE pour le SIRET {siret}: {e}")
            raise HTTPException(status_code=500, detail=f"Erreur de communication avec l'API INSEE : {str(e)}")

        if not insee_data:
            logger.warning(f"[INSEE] ⚠️ Aucune donnée INSEE trouvée pour le SIRET {siret}")
            raise HTTPException(status_code=404, detail=f"Aucune donnée INSEE trouvée pour le SIRET {siret}")

        logger.debug(f"[INSEE] ✅ Données brutes INSEE récupérées pour {siret} ({len(str(insee_data))} caractères)")

        # Étape 2 : Parsing strict
        try:
            parsed = self.parse_establishment_data(insee_data)
        except HTTPException as e:
            logger.error(f"[INSEE] ❌ Erreur de parsing INSEE ({siret}) : {e.detail}")
            raise
        except Exception as e:
            logger.exception(f"[INSEE] ❌ Exception inattendue lors du parsing INSEE pour {siret}: {e}")
            raise HTTPException(status_code=500, detail="Erreur interne lors du parsing des données INSEE")

        # Étape 3 : Vérification des données clés
        if not parsed.get("siret") or not parsed.get("siren"):
            logger.error(f"[INSEE] ❌ Réponse INSEE incomplète : SIRET ou SIREN manquant pour {siret}")
            raise HTTPException(status_code=502, detail="Réponse INSEE incomplète : SIRET ou SIREN manquant")

        logger.info(
            f"[INSEE] ✅ Parsing terminé pour {siret} | "
            f"SIREN={parsed.get('siren')} | Catégorie={parsed.get('enterprise_category') or 'N/A'}"
        )

        # Étape 4 : Fusion avec les données métier
        enriched = {**parsed, **entity_data}
        enriched["insee_data"] = parsed.get("raw_insee_data")
        enriched["insee_last_sync"] = datetime.utcnow()

        # Étape 5 : Logs de synthèse
        logger.info(f"[INSEE] ✔️ Enrichissement terminé pour le SIRET {siret}")
        logger.debug(
            "[INSEE] Champs disponibles : " +
            ", ".join([k for k in enriched.keys() if k not in ('insee_data', 'raw_insee_data')])
        )
        logger.debug(f"[INSEE] Taille du JSON brut INSEE : {len(str(parsed.get('raw_insee_data') or {}))} caractères")

        return enriched



# Instance singleton
_insee_service: Optional[INSEEService] = None


def get_insee_service() -> INSEEService:
    """Retourne l'instance singleton du service INSEE"""
    global _insee_service
    if _insee_service is None:
        _insee_service = INSEEService()
    return _insee_service