"""
Script pour supprimer toutes les relations SQLAlchemy
"""
import re
import os
from pathlib import Path

def clean_relationships(filepath):
    """Supprime toutes les lignes relationship() d'un fichier"""
    if not os.path.exists(filepath):
        print(f"❌ Fichier non trouvé: {filepath}")
        return False
    
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    new_lines = []
    in_relationship = False
    skip_line = False
    
    for i, line in enumerate(lines):
        # Détecter les lignes relationship sur une seule ligne
        if 'relationship(' in line and ')' in line and '=' in line:
            # Ligne complète de relationship
            indent = len(line) - len(line.lstrip())
            new_lines.append(' ' * indent + f"# {line.strip()} - DÉSACTIVÉ\n")
            continue
        
        # Détecter le début d'une relationship multi-lignes
        if 'relationship(' in line and '=' in line:
            in_relationship = True
            indent = len(line) - len(line.lstrip())
            new_lines.append(' ' * indent + f"# {line.strip()}\n")
            continue
        
        # Si on est dans une relationship multi-lignes
        if in_relationship:
            indent = len(line) - len(line.lstrip())
            new_lines.append(' ' * indent + f"# {line.strip()}\n")
            if ')' in line:
                in_relationship = False
            continue
        
        # Garder la ligne normale
        new_lines.append(line)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)
    
    print(f"✅ Nettoyé: {filepath}")
    return True

# Fichiers à nettoyer
files_to_clean = [
    'src/models/tenant.py',
    'src/models/audit.py',
    'src/models/ecosystem.py',
]

print("🧹 Nettoyage des relations SQLAlchemy...\n")

for filepath in files_to_clean:
    full_path = Path(__file__).parent / filepath
    clean_relationships(str(full_path))

print("\n✅ Toutes les relations ont été désactivées")
print("🚀 Redémarrez le backend : uvicorn src.main:app --reload")