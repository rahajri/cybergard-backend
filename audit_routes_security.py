#!/usr/bin/env python3
"""
Script d'audit de sécurité des routes FastAPI
Vérifie quelles routes sont protégées par Keycloak
"""

import os
import re
from pathlib import Path
from typing import Dict, List, Tuple

def analyze_route_file(filepath: Path) -> Dict[str, List[Dict]]:
    """Analyse un fichier de routes et extrait les routes avec leur protection"""

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Trouver toutes les définitions de routes
    route_pattern = r'@router\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']'
    routes = re.findall(route_pattern, content, re.MULTILINE)

    protected_routes = []
    unprotected_routes = []
    public_routes = []

    for method, path in routes:
        # Trouver le contexte de la route (les 10 lignes suivantes)
        route_def = f'@router.{method}("{path}"'
        idx = content.find(route_def)
        if idx == -1:
            route_def = f"@router.{method}('{path}'"
            idx = content.find(route_def)

        if idx != -1:
            # Extraire les 500 caractères suivants
            context = content[idx:idx+800]

            # Vérifier la présence de get_current_user_keycloak
            has_keycloak = 'get_current_user_keycloak' in context

            # Vérifier la présence de Depends (any auth)
            has_depends = 'Depends(' in context

            # Vérifier si c'est marqué comme public
            is_public = 'public' in context.lower() or 'no auth' in context.lower()

            route_info = {
                'method': method.upper(),
                'path': path,
                'has_keycloak': has_keycloak,
                'has_depends': has_depends,
                'is_public': is_public
            }

            if has_keycloak:
                protected_routes.append(route_info)
            elif is_public:
                public_routes.append(route_info)
            else:
                unprotected_routes.append(route_info)

    return {
        'protected': protected_routes,
        'unprotected': unprotected_routes,
        'public': public_routes
    }

def main():
    api_dir = Path(__file__).parent / 'src' / 'api' / 'v1'

    all_protected = []
    all_unprotected = []
    all_public = []

    files_analyzed = 0

    print("=" * 80)
    print("AUDIT DE SECURITE DES ROUTES API")
    print("=" * 80)
    print()

    for py_file in sorted(api_dir.glob('*.py')):
        if py_file.name.startswith('__'):
            continue

        print(f"[FILE] Analyse de {py_file.name}...")
        files_analyzed += 1

        result = analyze_route_file(py_file)

        all_protected.extend([(py_file.name, r) for r in result['protected']])
        all_unprotected.extend([(py_file.name, r) for r in result['unprotected']])
        all_public.extend([(py_file.name, r) for r in result['public']])

    print()
    print("=" * 80)
    print("RESUME")
    print("=" * 80)
    print(f"Fichiers analyses : {files_analyzed}")
    print(f"[OK] Routes protegees (Keycloak) : {len(all_protected)}")
    print(f"[PUBLIC] Routes publiques (intentionnelles) : {len(all_public)}")
    print(f"[WARNING] Routes NON protegees : {len(all_unprotected)}")
    print()

    if all_unprotected:
        print("=" * 80)
        print("[WARNING] ROUTES NON PROTEGEES (RISQUE DE SECURITE)")
        print("=" * 80)
        print()

        for filename, route in all_unprotected[:50]:  # Limiter a 50
            print(f"[FILE] {filename}")
            print(f"   {route['method']:6} {route['path']}")
            if route['has_depends']:
                print(f"   [INFO] Utilise Depends() mais pas get_current_user_keycloak")
            else:
                print(f"   [WARNING] AUCUNE AUTHENTIFICATION")
            print()

    if all_public:
        print("=" * 80)
        print("[PUBLIC] ROUTES PUBLIQUES (INTENTIONNELLES)")
        print("=" * 80)
        print()

        for filename, route in all_public[:20]:
            print(f"[FILE] {filename}")
            print(f"   {route['method']:6} {route['path']}")
            print()

    # Statistiques par fichier
    print("=" * 80)
    print("STATISTIQUES PAR FICHIER")
    print("=" * 80)
    print()

    file_stats = {}
    for filename, route in all_protected:
        file_stats.setdefault(filename, {'protected': 0, 'unprotected': 0, 'public': 0})
        file_stats[filename]['protected'] += 1

    for filename, route in all_unprotected:
        file_stats.setdefault(filename, {'protected': 0, 'unprotected': 0, 'public': 0})
        file_stats[filename]['unprotected'] += 1

    for filename, route in all_public:
        file_stats.setdefault(filename, {'protected': 0, 'unprotected': 0, 'public': 0})
        file_stats[filename]['public'] += 1

    for filename in sorted(file_stats.keys()):
        stats = file_stats[filename]
        total = stats['protected'] + stats['unprotected'] + stats['public']
        protected_pct = (stats['protected'] / total * 100) if total > 0 else 0

        status = "[OK]" if stats['unprotected'] == 0 else "[WARN]"

        print(f"{status} {filename:40} | "
              f"Protegees: {stats['protected']:3} | "
              f"Non protegees: {stats['unprotected']:3} | "
              f"Publiques: {stats['public']:3} | "
              f"Securite: {protected_pct:5.1f}%")

if __name__ == '__main__':
    main()
