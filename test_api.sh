# Test dans un fichier Python ou le shell
from src.config import settings

# Afficher la config IA
print(settings.display_ai_config())

# Récupérer config d'un modèle
mistral_config = settings.get_model_config("mistral:7b")
print(mistral_config)

# Vérifier les properties
print(f"Modèle par défaut: {settings.current_model}")
print(f"Modèle avancé: {settings.advanced_model}")
print(f"Multi-modèles: {settings.has_multi_models}")