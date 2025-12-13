"""
Application FastAPI principale
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
import time
import logging

from src.api.v1 import (
    frameworks,
    requirements,
    control_points,
    questionnaires,
    questionnaires_duplicate,  # ✅ NOUVEAU : Duplication avec question_i18n
    questions,
    question_types,  # ✅ AJOUTÉ
    options,  # ✅ NOUVEAU : Gestion des options réutilisables
    organizations,
    users,
    user_management,
    auth_keycloak,
    audite,
    audite_test,
    questionnaire_preview,
    attachments,
    hierarchy,
    category_relationships,  # ✅ NOUVEAU : Relations many-to-many entre catégories
    cross_referentials,
    cross_referentials_export,
    naf_codes,
    ecosystem,
    activation,
    admin,
    redis_monitoring,  # ✅ Monitoring Redis
    file_upload,  # ✅ Upload de fichiers pour pièces jointes
    questionnaire_activation,  # ✅ NOUVEAU : Activation questionnaires pour tenants
    campaigns,  # ✅ NOUVEAU : Gestion des campagnes d'audit
    campaign_scopes,  # ✅ NOUVEAU : Gestion des périmètres réutilisables
    magic_link_auth,  # ✅ NOUVEAU : Authentification sécurisée via Magic Link + Keycloak
    magic_link_admin,  # ✅ NOUVEAU : Administration des Magic Links (dev/tests)
    collaboration,  # ✅ NOUVEAU : Gestion de la collaboration et des @mentions
    action_plans,  # ✅ NOUVEAU : Génération automatique de plans d'action par IA
    action_plan_generate,  # ✅ NOUVEAU : Endpoint SSE pour génération de plan d'action (v2)
    actions,  # ✅ NOUVEAU : Actions publiées (module Actions client)
    reports,  # ✅ NOUVEAU : Gestion des templates et rapports
    roles,  # ✅ NOUVEAU : Gestion des rôles et permissions
    discussions,  # ✅ NOUVEAU : Module Discussions (conversations et messages)
    dashboard,  # ✅ NOUVEAU : Dashboard orienté Conformité & Audit
    external_scan,  # ✅ NOUVEAU : Module Scanner Externe (ASM)
    ebios,  # ✅ NOUVEAU : Module EBIOS RM (Analyse de risques ANSSI)
    client_questionnaires,  # ✅ NOUVEAU : Questionnaires côté client
)

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Création de l'application FastAPI
app = FastAPI(
    title="CYBERGARD AI API",
    version="2.0.0",
    description="API pour la gestion des audits de conformité ISO 27001"
)

# Middleware CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"]
)

# Middleware GZip
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Middleware Rate Limiting (optionnel - décommentez pour activer)
# from src.middleware.rate_limit import RateLimitMiddleware
# app.add_middleware(
#     RateLimitMiddleware,
#     max_requests=100,
#     window_seconds=60,
#     exclude_paths=["/health", "/docs", "/openapi.json", "/redoc", "/api/v1/redis/health"]
# )

# Middleware de timing
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    return response

# Routes de base
@app.get("/")
async def root():
    return {
        "message": "CYBERGARD AI API",
        "version": "2.0.0",
        "status": "running"
    }

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": time.time()
    }

# Enregistrement des routeurs API v1
app.include_router(frameworks.router, prefix="/api/v1/frameworks", tags=["Frameworks"])
app.include_router(requirements.router, prefix="/api/v1/requirements", tags=["Requirements"])
app.include_router(control_points.router, prefix="/api/v1/control-points", tags=["Control Points"])
app.include_router(questionnaires.router, prefix="/api/v1/questionnaires", tags=["Questionnaires"])
app.include_router(questionnaires_duplicate.router, prefix="/api/v1/questionnaires", tags=["Questionnaires Duplicate"])  # ✅ NOUVEAU : Duplication avec question_i18n
app.include_router(questions.router, prefix="/api/v1/questions", tags=["Questions"])
app.include_router(question_types.router, prefix="/api/v1", tags=["Question Types"])  # ✅ AJOUTÉ
app.include_router(options.router, prefix="/api/v1", tags=["Options"])  # ✅ NOUVEAU : Endpoints pour options réutilisables
app.include_router(organizations.router, prefix="/api/v1/organizations", tags=["Organizations"])
app.include_router(users.router, prefix="/api/v1/users", tags=["Users"])
app.include_router(user_management.router, prefix="/api/v1/user-management", tags=["User Management"])
app.include_router(auth_keycloak.router, prefix="/api/v1", tags=["Authentication"])
app.include_router(audite.router, prefix="/api/v1/audite", tags=["Audité"])
app.include_router(audite_test.router, prefix="/api/v1/audite-test", tags=["Audité Test"])
app.include_router(questionnaire_preview.router, prefix="/api/v1/questionnaires", tags=["Questionnaire Preview"])
app.include_router(attachments.router, prefix="/api/v1/attachments", tags=["Attachments"])
app.include_router(hierarchy.router, prefix="/api/v1/hierarchy", tags=["Hierarchy"])
app.include_router(category_relationships.router, prefix="/api/v1/hierarchy", tags=["Category Relationships"])  # ✅ NOUVEAU : Relations many-to-many
app.include_router(cross_referentials.router, prefix="/api/v1/cross-referentials", tags=["Cross Referentials"])
app.include_router(cross_referentials_export.router, prefix="/api/v1/cross-referentials", tags=["Cross Referentials Export"])
app.include_router(naf_codes.router, prefix="/api/v1/naf-codes", tags=["NAF Codes"])
app.include_router(ecosystem.router, prefix="/api/v1", tags=["Ecosystem"])  # Le prefix /ecosystem est déjà dans ecosystem.py
app.include_router(activation.router, prefix="/api/v1/activation", tags=["Activation"])
app.include_router(admin.router, prefix="/api/v1", tags=["Admin"])
app.include_router(redis_monitoring.router, prefix="/api/v1", tags=["Monitoring"])
app.include_router(file_upload.router, prefix="/api/v1", tags=["File Upload"])
app.include_router(questionnaire_activation.router, prefix="/api/v1", tags=["Questionnaire Activation"])
app.include_router(campaigns.router, prefix="/api/v1", tags=["Campaigns"])
app.include_router(campaign_scopes.router, prefix="/api/v1", tags=["Campaign Scopes"])
app.include_router(magic_link_auth.router, prefix="/api/v1/magic-link", tags=["Magic Link Auth"])
app.include_router(magic_link_admin.router, prefix="/api/v1/magic-link/admin", tags=["Magic Link Admin"])
app.include_router(collaboration.router, prefix="/api/v1", tags=["Collaboration"])
app.include_router(action_plans.router, prefix="/api/v1", tags=["Action Plans"])
app.include_router(action_plan_generate.router, prefix="/api/v1", tags=["Action Plan Generation"])
app.include_router(actions.router, prefix="/api/v1", tags=["Actions"])  # ✅ NOUVEAU : Actions publiées
app.include_router(reports.router, prefix="/api/v1", tags=["Reports"])
app.include_router(roles.router, prefix="/api/v1/roles", tags=["Roles & Permissions"])  # ✅ NOUVEAU : Gestion des rôles et permissions
app.include_router(discussions.router, prefix="/api/v1", tags=["Discussions"])  # ✅ NOUVEAU : Module Discussions
app.include_router(dashboard.router, prefix="/api/v1", tags=["Dashboard"])  # ✅ NOUVEAU : Dashboard Conformité & Audit
app.include_router(external_scan.router, prefix="/api/v1", tags=["External Scanner"])  # ✅ NOUVEAU : Module Scanner Externe (ASM)
app.include_router(ebios.router, prefix="/api/v1", tags=["EBIOS RM"])  # ✅ NOUVEAU : Module EBIOS RM (Analyse de risques ANSSI)
app.include_router(client_questionnaires.router, prefix="/api/v1", tags=["Client Questionnaires"])  # ✅ NOUVEAU : Questionnaires côté client

# Événement de démarrage
@app.on_event("startup")
async def startup_event():
    # Initialiser Redis
    from src.utils.redis_manager import redis_manager
    try:
        redis_manager.connect()
        if redis_manager.is_connected:
            logger.info("✅ Redis connecté et opérationnel")
        else:
            logger.warning("⚠️ Redis non disponible - Mode dégradé activé")
    except Exception as e:
        logger.warning(f"⚠️ Impossible de se connecter à Redis: {e} - Mode dégradé activé")

    # Initialiser le service Keycloak
    from src.services.keycloak_service import init_keycloak_service
    try:
        init_keycloak_service()
        logger.info("✅ KeycloakService initialisé")
    except Exception as e:
        logger.error(f"❌ Erreur lors de l'initialisation de KeycloakService: {e}")
        raise

    logger.info("🚀 CYBERGARD AI API démarrée")
    logger.info("📚 Documentation disponible sur /docs")

# Événement d'arrêt
@app.on_event("shutdown")
async def shutdown_event():
    # Déconnecter Redis
    from src.utils.redis_manager import redis_manager
    try:
        redis_manager.disconnect()
        logger.info("✅ Redis déconnecté proprement")
    except Exception as e:
        logger.warning(f"⚠️ Erreur lors de la déconnexion Redis: {e}")

    logger.info("🛑 Arrêt de CYBERGARD AI API")
