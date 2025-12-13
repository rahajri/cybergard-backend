"""
Dependencies FastAPI pour injection de dépendances
Évite les imports circulaires entre main.py et les routers
"""
from typing import Generator, Optional
from sqlalchemy.orm import Session
from fastapi import Depends, HTTPException, status, Request, Cookie
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
import logging

# Import conditionnel pour le type checking (évite les imports circulaires)
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.services.deepseek_pc_generator import DeepSeekControlPointGenerator

logger = logging.getLogger(__name__)

# Security scheme pour JWT
security = HTTPBearer(auto_error=False)  # auto_error=False pour gérer manuellement les cookies

# ============================================================================
# GÉNÉRATEUR DEEPSEEK
# ============================================================================

# Instance globale du générateur (sera initialisée par main.py au démarrage)
_deepseek_generator: Optional["DeepSeekControlPointGenerator"] = None


def set_deepseek_generator(generator: "DeepSeekControlPointGenerator") -> None:
    """
    Définit l'instance globale du générateur DeepSeek.
    
    Cette fonction est appelée au démarrage de l'application dans main.py
    pour enregistrer le générateur initialisé.
    
    Args:
        generator: Instance de DeepSeekControlPointGenerator
    """
    global _deepseek_generator
    _deepseek_generator = generator
    print(f"✅ Générateur DeepSeek enregistré dans dependencies.py")


def get_deepseek_generator() -> "DeepSeekControlPointGenerator":
    """
    Dependency FastAPI pour obtenir le générateur DeepSeek.
    
    Cette fonction est utilisée comme dépendance dans les endpoints FastAPI :
    
    Example:
        @router.post("/generate")
        async def generate(gen: DeepSeekControlPointGenerator = Depends(get_deepseek_generator)):
            result = await gen.generate_control_points(...)
    
    Returns:
        Instance du générateur DeepSeek
        
    Raises:
        RuntimeError: Si le générateur n'est pas initialisé (app non démarrée)
    """
    if _deepseek_generator is None:
        raise RuntimeError(
            "❌ DeepSeekPCGenerator non initialisé.\n"
            "Vérifier que :\n"
            "1. L'application a démarré correctement\n"
            "2. AI_GENERATION_ENABLED=true dans .env\n"
            "3. init_deepseek_generator() a été appelé dans main.py\n"
            "4. set_deepseek_generator() a été appelé avec succès"
        )
    return _deepseek_generator


# ============================================================================
# BASE DE DONNÉES
# ============================================================================

def get_db() -> Generator[Session, None, None]:
    """
    Dependency FastAPI pour obtenir une session de base de données.
    
    Cette fonction crée une session SQLAlchemy, l'injecte dans l'endpoint,
    puis la ferme automatiquement après traitement.
    
    Example:
        @router.get("/frameworks")
        def get_frameworks(db: Session = Depends(get_db)):
            return db.query(Framework).all()
    
    Yields:
        Session SQLAlchemy active
    """
    from src.database import SessionLocal
    
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================================================
# STATUT DU SYSTÈME
# ============================================================================

def get_system_status() -> dict:
    """
    Retourne le statut des dépendances système.
    
    Returns:
        Dictionnaire avec l'état de chaque composant
    """
    status = {
        "deepseek_generator": _deepseek_generator is not None,
        "database": True  # Assume DB is available if app started
    }
    
    if _deepseek_generator:
        status["deepseek_config"] = {
            "model": _deepseek_generator.model,
            "ollama_url": _deepseek_generator.ollama_url,
            "batch_size": _deepseek_generator.batch_size
        }
    
    return status


# ============================================================================
# AUTHENTIFICATION JWT
# ============================================================================

async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db)
):
    """
    Dependency FastAPI pour obtenir l'utilisateur actuellement connecté.
    
    Supporte deux méthodes d'authentification :
    1. Header Authorization: Bearer <token>
    2. Cookie: access_token=<token>
    
    Args:
        request: Requête FastAPI
        credentials: Credentials du header Authorization (optionnel)
        access_token: Token depuis le cookie (optionnel)
        db: Session de base de données
    
    Returns:
        Instance de User authentifié
    
    Raises:
        HTTPException 401: Si le token est invalide ou l'utilisateur non trouvé
        HTTPException 403: Si l'utilisateur est inactif
    
    Example:
        @router.get("/me")
        def get_me(current_user: User = Depends(get_current_user)):
            return current_user
    """
    from src.models import User
    from sqlalchemy import select
    
    # Récupérer le token depuis le header OU depuis le cookie
    token = None
    if credentials:
        token = credentials.credentials
        logger.debug("✅ Token récupéré depuis Authorization header")
    elif access_token:
        token = access_token
        logger.debug("✅ Token récupéré depuis cookie")
    
    if not token:
        logger.warning("❌ Aucun token trouvé (ni header ni cookie)")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Non authentifié. Token manquant.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Décoder le JWT
    try:
        # Importer les settings pour récupérer la clé secrète
        from src.config import settings
        
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
        
        user_id: str = payload.get("sub")
        if user_id is None:
            logger.error("❌ Token invalide: 'sub' manquant dans le payload")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token invalide: identifiant utilisateur manquant"
            )
        
        logger.debug(f"✅ Token décodé: user_id={user_id}")
        
    except JWTError as e:
        logger.error(f"❌ Erreur décodage JWT: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide ou expiré",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Récupérer l'utilisateur depuis la base de données
    user = db.execute(
        select(User).where(User.id == user_id)
    ).scalar_one_or_none()
    
    if user is None:
        logger.error(f"❌ Utilisateur {user_id} non trouvé en base")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Utilisateur non trouvé"
        )
    
    # Vérifier que l'utilisateur est actif
    if not user.is_active:
        logger.warning(f"❌ Utilisateur {user_id} est inactif")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Compte utilisateur inactif"
        )
    
    logger.debug(f"✅ Utilisateur authentifié: {user.email}")
    return user