#!/usr/bin/env python3
"""
Script pour sécuriser automatiquement les routes FastAPI
Ajoute current_user: User = Depends(get_current_user_keycloak) à toutes les routes
"""
import re
from pathlib import Path

def secure_route_function(content: str, file_path: Path) -> tuple[str, int]:
    """
    Ajoute current_user à toutes les fonctions de route qui n'en ont pas
    Retourne (nouveau_contenu, nombre_de_modifications)
    """
    modifications = 0

    # Pattern pour détecter les définitions de routes
    # Cherche @router.METHOD suivi de def/async def
    route_pattern = r'(@router\.(get|post|put|patch|delete)\([^\)]+\)[^\n]*\n(?:async )?def ([a-zA-Z_][a-zA-Z0-9_]*)\([^)]*)'

    def add_current_user(match):
        nonlocal modifications
        full_match = match.group(0)
        decorator = match.group(1)
        method = match.group(2)
        func_name = match.group(3)

        # Vérifier si current_user est déjà présent
        if 'current_user' in full_match:
            return full_match

        # Trouver la position avant db: Session = Depends(get_db)
        # ou avant la fermeture de parenthèse
        if 'db: Session = Depends(get_db)' in full_match:
            # Ajouter avant db
            new_match = full_match.replace(
                'db: Session = Depends(get_db)',
                'current_user: User = Depends(get_current_user_keycloak),\n    db: Session = Depends(get_db)'
            )
            modifications += 1
            return new_match
        else:
            # Chercher la dernière ligne avec paramètres
            lines = full_match.split('\n')
            # Insérer avant la dernière ligne (qui contient généralement la fermeture)
            if len(lines) > 1:
                # Trouver l'indentation
                indent = len(lines[-1]) - len(lines[-1].lstrip())
                # Ajouter current_user comme dernier paramètre
                lines.insert(-1, ' ' * indent + 'current_user: User = Depends(get_current_user_keycloak),')
                modifications += 1
                return '\n'.join(lines)

        return full_match

    new_content = re.sub(route_pattern, add_current_user, content, flags=re.MULTILINE)

    return new_content, modifications

def main():
    api_dir = Path(__file__).parent / 'src' / 'api' / 'v1'

    # Fichiers à sécuriser
    files_to_secure = [
        'control_points.py',
        'frameworks.py',
        'questionnaires.py',
        'questions.py',
        'options.py',
        'naf_codes.py',
        'campaign_scopes.py',
        'cross_referentials.py',
        'cross_referentials_export.py',
        'file_upload.py',
        'redis_monitoring.py',
        'questionnaires_duplicate.py',
    ]

    total_modifications = 0

    for filename in files_to_secure:
        filepath = api_dir / filename

        if not filepath.exists():
            print(f"[SKIP] {filename} - fichier introuvable")
            continue

        print(f"\n[PROCESS] {filename}")

        # Lire le contenu
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        # Vérifier si l'import est présent
        has_keycloak_import = 'get_current_user_keycloak' in content
        has_user_import = 'from ...models.audit import User' in content or 'from src.models.audit import User' in content

        if not has_keycloak_import:
            print(f"  [INFO] Ajout import get_current_user_keycloak")
            # Ajouter l'import après les autres imports de dependencies
            if 'from src.dependencies import' in content:
                content = content.replace(
                    'from src.dependencies import',
                    'from src.dependencies_keycloak import get_current_user_keycloak\nfrom src.dependencies import'
                )
            elif 'from ...dependencies import' in content:
                content = content.replace(
                    'from ...dependencies import',
                    'from ...dependencies_keycloak import get_current_user_keycloak\nfrom ...dependencies import'
                )
            else:
                # Ajouter après les imports de database
                if 'from ...database import' in content:
                    content = content.replace(
                        'from ...database import',
                        'from ...dependencies_keycloak import get_current_user_keycloak\nfrom ...database import'
                    )

        if not has_user_import:
            print(f"  [INFO] Ajout import User")
            # Ajouter User aux imports de models.audit
            if 'from ...models.audit import' in content:
                content = re.sub(
                    r'(from \.\.\.models\.audit import [^\n]+)',
                    r'\1, User',
                    content
                )
            elif 'from src.models.audit import' in content:
                content = re.sub(
                    r'(from src\.models\.audit import [^\n]+)',
                    r'\1, User',
                    content
                )

        # Sécuriser les routes
        new_content, mods = secure_route_function(content, filepath)

        if mods > 0:
            print(f"  [OK] {mods} routes sécurisées")

            # Écrire le fichier
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(new_content)

            total_modifications += mods
        else:
            print(f"  [INFO] Aucune modification nécessaire")

    print(f"\n" + "="*80)
    print(f"TOTAL: {total_modifications} routes sécurisées")
    print("="*80)

if __name__ == '__main__':
    main()
