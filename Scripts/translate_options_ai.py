"""
Script de traduction des options via DeepSeek AI

Utilisation:
    # Traduire toutes les options système en anglais
    python backend/scripts/translate_options_ai.py --language en --system-only

    # Traduire toutes les options en anglais (avec confirmation)
    python backend/scripts/translate_options_ai.py --language en

    # Traduire toutes les options en anglais (sans confirmation)
    python backend/scripts/translate_options_ai.py --language en --auto-save

    # Traduire une option spécifique
    python backend/scripts/translate_options_ai.py --option-id <uuid> --language en

    # Preview (affiche sans sauvegarder)
    python backend/scripts/translate_options_ai.py --language en --preview
"""
import sys
import os
import argparse
import httpx
import json
from pathlib import Path

# Ajouter le répertoire parent au PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.orm import Session
from src.database import SessionLocal
from src.models.option import Option, OptionI18n


class OptionAITranslator:
    """Traducteur d'options via DeepSeek AI"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.api_url = "https://api.deepseek.com/v1/chat/completions"

    def translate_option(
        self,
        option_value: str,
        target_language: str = "en",
        context: str = "cybersecurity audit"
    ) -> str:
        """
        Traduit une option via DeepSeek AI

        Args:
            option_value: Valeur de l'option en français
            target_language: Code langue cible (en, es, de, it, pt)
            context: Contexte métier pour la traduction

        Returns:
            str: Valeur traduite
        """
        language_names = {
            "en": "English",
            "es": "Spanish",
            "de": "German",
            "it": "Italian",
            "pt": "Portuguese"
        }

        target_lang_name = language_names.get(target_language, target_language)

        prompt = f"""You are a professional translator specialized in {context} terminology.

Translate the following French option value into {target_lang_name}:

FRENCH VALUE: "{option_value}"

INSTRUCTIONS:
- Translate accurately while preserving the meaning
- Keep it concise (this is a form option)
- Maintain any technical terms
- Return ONLY the translated text, no quotes, no explanation

TRANSLATION:"""

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": "deepseek-chat",
            "messages": [
                {
                    "role": "system",
                    "content": "You are a professional translator. Always respond with ONLY the translation, no extra text."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": 0.3,
            "max_tokens": 100
        }

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(self.api_url, headers=headers, json=payload)
                response.raise_for_status()

            result = response.json()
            translation = result["choices"][0]["message"]["content"].strip()

            # Nettoyer les guillemets si présents
            translation = translation.strip('"').strip("'")

            return translation

        except Exception as e:
            print(f"❌ Erreur API DeepSeek: {e}")
            return None


def save_translation(
    db: Session,
    option_id: str,
    language_code: str,
    translated_value: str
) -> bool:
    """
    Sauvegarde une traduction d'option

    Args:
        db: Session SQLAlchemy
        option_id: UUID de l'option
        language_code: Code langue (en, es, de, it, pt)
        translated_value: Valeur traduite

    Returns:
        bool: True si sauvegardé, False si existait déjà
    """
    # Vérifier si traduction existe déjà
    existing = db.query(OptionI18n).filter(
        OptionI18n.option_id == option_id,
        OptionI18n.language_code == language_code
    ).first()

    if existing:
        # Mettre à jour
        existing.translated_value = translated_value
        db.commit()
        return False  # Existait déjà

    # Créer nouvelle traduction
    translation = OptionI18n(
        option_id=option_id,
        language_code=language_code,
        translated_value=translated_value
    )
    db.add(translation)
    db.commit()
    return True  # Nouvelle traduction


def main():
    parser = argparse.ArgumentParser(description="Traduction des options via DeepSeek AI")
    parser.add_argument("--option-id", help="UUID de l'option à traduire (si spécifique)")
    parser.add_argument("--language", required=True, help="Code langue cible (en, es, de, it, pt)")
    parser.add_argument("--system-only", action="store_true", help="Traduire uniquement les options système")
    parser.add_argument("--auto-save", action="store_true", help="Sauvegarder automatiquement sans confirmation")
    parser.add_argument("--preview", action="store_true", help="Afficher les traductions sans sauvegarder")

    args = parser.parse_args()

    # Vérifier la clé API
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        print("❌ DEEPSEEK_API_KEY non configurée dans .env")
        sys.exit(1)

    translator = OptionAITranslator(api_key)
    db = SessionLocal()

    try:
        # Récupérer les options à traduire
        query = db.query(Option)

        if args.option_id:
            # Option spécifique
            query = query.filter(Option.id == args.option_id)
        elif args.system_only:
            # Uniquement les options système
            query = query.filter(Option.is_system == True)

        options = query.all()

        if not options:
            print("❌ Aucune option trouvée")
            sys.exit(1)

        print(f"🔍 {len(options)} option(s) à traduire en {args.language.upper()}\n")

        stats = {"total": 0, "saved": 0, "skipped": 0, "errors": 0}

        for idx, option in enumerate(options):
            stats["total"] += 1

            # Vérifier si traduction existe déjà
            existing = db.query(OptionI18n).filter(
                OptionI18n.option_id == option.id,
                OptionI18n.language_code == args.language
            ).first()

            if existing and not args.preview:
                print(f"[{idx+1}/{len(options)}] ⏭️  '{option.default_value}' → Déjà traduite")
                stats["skipped"] += 1
                continue

            # Afficher l'option
            marker = "🔧" if option.is_system else "🤖"
            print(f"[{idx+1}/{len(options)}] {marker} '{option.default_value}'")

            # Traduire
            translation = translator.translate_option(
                option.default_value,
                target_language=args.language
            )

            if not translation:
                print(f"   ❌ Échec traduction")
                stats["errors"] += 1
                continue

            print(f"   → {translation}")

            # Sauvegarder ou demander confirmation
            if args.preview:
                print(f"   📋 Preview mode (non sauvegardé)")
            elif args.auto_save:
                is_new = save_translation(db, option.id, args.language, translation)
                print(f"   ✅ Sauvegardée {'(nouvelle)' if is_new else '(mise à jour)'}")
                stats["saved"] += 1
            else:
                # Demander confirmation
                choice = input(f"   💾 Sauvegarder ? (y/n/a=all): ").lower().strip()

                if choice == "a":
                    args.auto_save = True
                    is_new = save_translation(db, option.id, args.language, translation)
                    print(f"   ✅ Sauvegardée {'(nouvelle)' if is_new else '(mise à jour)'}")
                    stats["saved"] += 1
                elif choice == "y":
                    is_new = save_translation(db, option.id, args.language, translation)
                    print(f"   ✅ Sauvegardée {'(nouvelle)' if is_new else '(mise à jour)'}")
                    stats["saved"] += 1
                else:
                    print(f"   ⏭️  Ignorée")
                    stats["skipped"] += 1

            print()

        # Résumé
        print("=" * 70)
        print(f"✅ RÉSUMÉ")
        print(f"   Total: {stats['total']}")
        print(f"   Sauvegardées: {stats['saved']}")
        print(f"   Ignorées: {stats['skipped']}")
        print(f"   Erreurs: {stats['errors']}")
        print("=" * 70)

    finally:
        db.close()


if __name__ == "__main__":
    main()
