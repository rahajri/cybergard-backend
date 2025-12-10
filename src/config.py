# backend/src/config.py
"""
Configuration complète de l'application CyberGuard Pro
Support multi-modèles IA (Mistral + DeepSeek) + API INSEE
"""

from typing import Optional, List, Set
from pathlib import Path
from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic.functional_validators import field_validator

# Déterminer le chemin du fichier .env (backend/.env)
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"


class Settings(BaseSettings):
    """
    Configuration complète de l'application CyberGuard Pro
    Support multi-modèles IA (Mistral + DeepSeek) + API INSEE
    """

    # ==========================================
    # PYDANTIC CONFIGURATION
    # ==========================================
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ==========================================
    # DATABASE CONFIGURATION
    # ==========================================
    database_url: Optional[str] = Field(default=None, alias="DATABASE_URL")
    db_host: str = Field(default="db", alias="DB_HOST")
    db_port: int = Field(default=5432, alias="DB_PORT")
    db_name: str = Field(default="audit_platform", alias="DB_NAME")
    db_user: str = Field(default="postgres", alias="DB_USER")
    db_password: str = Field(default="postgres", alias="DB_PASSWORD")
    pg_db: Optional[str] = Field(default=None, alias="POSTGRES_DB")
    pg_user: Optional[str] = Field(default=None, alias="POSTGRES_USER")
    pg_password: Optional[str] = Field(default=None, alias="POSTGRES_PASSWORD")

    # ==========================================
    # API CONFIGURATION
    # ==========================================
    api_v1_str: str = Field(default="/api/v1", alias="API_V1_STR")
    project_name: str = Field(default="CyberGuard Pro API", alias="PROJECT_NAME")
    version: str = Field(default="1.0.0", alias="VERSION")

    # ==========================================
    # SECURITY
    # ==========================================
    secret_key: str = Field(default="your-secret-key-here", alias="SECRET_KEY")
    algorithm: str = Field(default="HS256", alias="ALGORITHM")
    access_token_expire_minutes: int = Field(default=30, alias="ACCESS_TOKEN_EXPIRE_MINUTES")

    # ==========================================
    # CORS CONFIGURATION
    # ==========================================
    backend_cors_origins: List[str] = Field(
        default=["http://localhost:3000", "http://localhost:8000"],
        alias="BACKEND_CORS_ORIGINS"
        )

    # ==========================================
    # ⭐ API INSEE CONFIGURATION (NOUVEAU)
    # ==========================================
    insee_api_key: Optional[str] = Field(
        default=None, 
        alias="INSEE_API_KEY",
        description="Clé d'API INSEE (X-INSEE-Api-Key-Integration)"
    )
    insee_enabled: bool = Field(
        default=True,
        alias="INSEE_ENABLED",
        description="Activer l'intégration API INSEE"
    )
    insee_timeout_seconds: int = Field(
        default=10,
        alias="INSEE_TIMEOUT_SECONDS",
        description="Timeout des requêtes INSEE en secondes"
    )

    # ==========================================
    # AI CONFIGURATION - OLLAMA
    # ==========================================
    ai_generation_enabled: bool = Field(default=True, alias="AI_GENERATION_ENABLED")
    ollama_url: str = Field(default="http://host.docker.internal:11434", alias="OLLAMA_URL")
    ollama_model: str = Field(default="deepseek-r1:1.5b", alias="OLLAMA_MODEL")
    ollama_model_advanced: str = Field(default="deepseek-r1:7b", alias="OLLAMA_MODEL_ADVANCED")

    # ==========================================
    # AI CONFIGURATION - MISTRAL (prioritaire)
    # ==========================================
    mistral_enabled: bool = Field(default=True, alias="MISTRAL_ENABLED")
    mistral_model: str = Field(default="mistral:7b-instruct-v0.3-q4_K_M", alias="MISTRAL_MODEL")
    mistral_temperature: float = Field(default=0.1, alias="MISTRAL_TEMPERATURE")
    mistral_max_tokens: int = Field(default=2048, alias="MISTRAL_MAX_TOKENS")
    mistral_num_ctx: int = Field(default=8192, alias="MISTRAL_NUM_CTX")

    # ==========================================
    # AI CONFIGURATION - DEEPSEEK (spécialisé questions)
    # ==========================================
    deepseek_enabled: bool = Field(default=True, alias="DEEPSEEK_ENABLED")
    deepseek_model: str = Field(default="deepseek-r1:1.5b", alias="DEEPSEEK_MODEL")
    deepseek_num_ctx: int = Field(default=16384, alias="DEEPSEEK_NUM_CTX")
    deepseek_max_tokens: int = Field(default=4096, alias="DEEPSEEK_MAX_TOKENS")
    deepseek_temperature: float = Field(default=0.05, alias="DEEPSEEK_TEMPERATURE")
    deepseek_batch_size: int = Field(default=10, alias="DEEPSEEK_BATCH_SIZE")
    
    ai_top_p: float = Field(default=0.9, alias="AI_TOP_P")
    ai_repeat_penalty: float = Field(default=1.1, alias="AI_REPEAT_PENALTY")
    ai_timeout_seconds: int = Field(default=600, alias="AI_TIMEOUT_SECONDS")
    ai_max_retries: int = Field(default=3, alias="AI_MAX_RETRIES")
    
    max_requirements_per_request: int = Field(default=100, alias="MAX_REQUIREMENTS_PER_REQUEST")
    max_control_points_per_generation: int = Field(default=50, alias="MAX_CONTROL_POINTS_PER_GENERATION")

    # ==========================================
    # EMBEDDINGS CONFIGURATION
    # ==========================================
    auto_generate_embeddings: bool = Field(default=True, alias="AUTO_GENERATE_EMBEDDINGS")
    embedding_model: str = Field(default="xlm-roberta-base", alias="EMBEDDING_MODEL")
    embedding_dimension: int = Field(default=768, alias="EMBEDDING_DIMENSION")
    models_cache_dir: str = Field(default="./models", alias="MODELS_CACHE_DIR")

    # ==========================================
    # HUGGINGFACE CONFIGURATION
    # ==========================================
    hf_home: str = Field(default="./models", alias="HF_HOME")
    hf_hub_disable_symlinks_warning: bool = Field(default=True, alias="HF_HUB_DISABLE_SYMLINKS_WARNING")

    # ==========================================
    # REDIS CONFIGURATION
    # ==========================================
    redis_host: str = Field(default="localhost", alias="REDIS_HOST")
    redis_port: int = Field(default=6379, alias="REDIS_PORT")
    redis_db: int = Field(default=0, alias="REDIS_DB")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    redis_max_memory: str = Field(default="512mb", alias="REDIS_MAX_MEMORY")
    redis_max_connections: int = Field(default=100, alias="REDIS_MAX_CONNECTIONS")
    redis_socket_timeout: int = Field(default=5, alias="REDIS_SOCKET_TIMEOUT")
    redis_socket_connect_timeout: int = Field(default=5, alias="REDIS_SOCKET_CONNECT_TIMEOUT")
    redis_cache_ttl: int = Field(default=3600, alias="REDIS_CACHE_TTL")
    redis_session_ttl: int = Field(default=86400, alias="REDIS_SESSION_TTL")

    # ==========================================
    # CACHE CONFIGURATION
    # ==========================================
    cache_ttl_seconds: int = Field(default=3600, alias="CACHE_TTL_SECONDS")

    # ==========================================
    # LOGGING & ENVIRONMENT
    # ==========================================
    debug: bool = Field(default=True, alias="DEBUG")
    environment: str = Field(default="development", alias="ENVIRONMENT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # ==========================================
    # LEGACY SETTINGS (DEPRECATED - conservés pour compatibilité)
    # ==========================================
    ollama_base_url: str = Field(default="http://host.docker.internal:11434", alias="OLLAMA_BASE_URL")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4", alias="OPENAI_MODEL")
    openai_temperature: float = Field(default=0.3, alias="OPENAI_TEMPERATURE")
    openai_max_tokens: int = Field(default=4000, alias="OPENAI_MAX_TOKENS")
    ai_temperature: float = Field(default=0.1, alias="AI_TEMPERATURE")
    ai_max_tokens: int = Field(default=2048, alias="AI_MAX_TOKENS")
    ai_num_ctx: int = Field(default=8192, alias="AI_NUM_CTX")

    # ==========================================
    # VALIDATORS
    # ==========================================
    @field_validator("backend_cors_origins", mode="before")
    @classmethod
    def parse_cors(cls, v):
        """Parse CORS origins from JSON list or comma-separated string"""
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("["):
                try:
                    import json
                    return json.loads(v)
                except Exception:
                    pass
            return [s.strip() for s in v.split(",") if s.strip()]
        return []

    # ==========================================
    # COMPUTED PROPERTIES
    # ==========================================
    
    @property
    def sqlalchemy_url(self) -> str:
        """Génère l'URL SQLAlchemy complète"""
        if self.database_url:
            if self.database_url.startswith("postgresql://"):
                return self.database_url.replace("postgresql://", "postgresql+psycopg2://", 1)
            return self.database_url

        name = self.db_name or self.pg_db or "audit_platform"
        user = self.db_user or self.pg_user or "postgres"
        pwd = self.db_password or self.pg_password or "postgres"
        host = self.db_host or "db"
        port = self.db_port or 5432

        return f"postgresql+psycopg2://{user}:{pwd}@{host}:{port}/{name}"

    @property
    def is_deepseek_configured(self) -> bool:
        """Vérifie si DeepSeek/Ollama est configuré"""
        return bool(self.ollama_url and self.ai_generation_enabled)
    
    @property 
    def is_openai_configured(self) -> bool:
        """Vérifie si OpenAI est configuré (deprecated)"""
        return bool(self.openai_api_key)
    
            
    @property
    def is_insee_configured(self) -> bool:
        """Vérifie si l'API INSEE est configurée avec authentification"""
        return bool(
            self.insee_enabled and 
            self.insee_api_key
        )
    
    @property
    def ai_provider(self) -> str:
        """Retourne le fournisseur IA actif"""
        if self.is_deepseek_configured:
            return "deepseek"
        elif self.is_openai_configured:
            return "openai"
        else:
            return "algorithmic"
    
    @property
    def current_model(self) -> str:
        """Retourne le modèle par défaut actuel"""
        return self.ollama_model
    
    @property
    def advanced_model(self) -> str:
        """Retourne le modèle avancé"""
        return self.ollama_model_advanced
    
    @property
    def has_multi_models(self) -> bool:
        """Vérifie si plusieurs modèles sont disponibles"""
        return self.ollama_model != self.ollama_model_advanced

    # ==========================================
    # BACKWARD COMPATIBILITY PROPERTIES
    # ==========================================
    
    @property
    def PROJECT_NAME(self) -> str:
        return self.project_name

    @property
    def API_V1_STR(self) -> str:
        return self.api_v1_str

    @property
    def VERSION(self) -> str:
        return self.version

    @property
    def SECRET_KEY(self) -> str:
        return self.secret_key

    @property
    def ALGORITHM(self) -> str:
        return self.algorithm

    @property
    def ACCESS_TOKEN_EXPIRE_MINUTES(self) -> int:
        return self.access_token_expire_minutes

    @property
    def BACKEND_CORS_ORIGINS(self) -> List[str]:
        return self.backend_cors_origins

    @property
    def DATABASE_URL(self) -> str:
        return self.sqlalchemy_url
    
    @property
    def OLLAMA_URL(self) -> str:
        return self.ollama_url

    @property
    def OLLAMA_MODEL(self) -> str:
        return self.ollama_model

    # ==========================================
    # KEYCLOAK CONFIGURATION
    # ==========================================
    keycloak_enabled: bool = Field(
        default=False,
        alias="KEYCLOAK_ENABLED",
        description="Activer l'authentification Keycloak"
    )
    keycloak_server_url: str = Field(
        default="http://localhost:8080",
        alias="KEYCLOAK_SERVER_URL",
        description="URL du serveur Keycloak"
    )
    keycloak_realm_name: str = Field(
        default="cyberguard",
        alias="KEYCLOAK_REALM_NAME",
        description="Nom du realm Keycloak"
    )
    keycloak_client_id: str = Field(
        default="cybergard-backend",
        alias="KEYCLOAK_CLIENT_ID",
        description="Client ID pour le backend"
    )
    keycloak_client_secret: Optional[str] = Field(
        default=None,
        alias="KEYCLOAK_CLIENT_SECRET",
        description="Client secret pour le backend"
    )
    keycloak_admin_client_id: str = Field(
        default="admin-cli",
        alias="KEYCLOAK_ADMIN_CLIENT_ID",
        description="Client ID pour l'administration"
    )
    keycloak_admin_client_secret: Optional[str] = Field(
        default=None,
        alias="KEYCLOAK_ADMIN_CLIENT_SECRET",
        description="Client secret pour l'administration"
    )
    keycloak_admin_username: Optional[str] = Field(
        default=None,
        alias="KEYCLOAK_ADMIN_USERNAME",
        description="Username admin pour l'administration Keycloak"
    )
    keycloak_admin_password: Optional[str] = Field(
        default=None,
        alias="KEYCLOAK_ADMIN_PASSWORD",
        description="Password admin pour l'administration Keycloak"
    )

    @property
    def is_keycloak_configured(self) -> bool:
        """Vérifie si Keycloak est configuré et activé"""
        return bool(
            self.keycloak_enabled and
            self.keycloak_server_url and
            self.keycloak_realm_name and
            self.keycloak_client_id
        )


# Instance singleton
settings = Settings()