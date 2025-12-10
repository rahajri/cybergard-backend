"""Télécharge un rapport depuis MinIO."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from minio import Minio

# Connexion MinIO
client = Minio(
    "localhost:9000",
    access_key="minioadmin",
    secret_key="minioadmin123",
    secure=False
)

# Chemin du rapport C2M SYSTEM
report_path = "tenant-e628c959-d81b-417d-bbb9-0e861053ec30/campaigns/dcdb2976-1b43-4fda-8816-f71058b63ae5/reports/rapport_ad67b846-59b5-4b4b-8786-3c73421992d2_20251128_173212.html"

try:
    # Télécharger
    response = client.get_object("audit-attachments", report_path)
    content = response.read().decode('utf-8')
    response.close()
    response.release_conn()

    # Extraire le contenu des widgets IA (résumé exécutif et synthèse)
    print("=" * 80)
    print("RAPPORT C2M SYSTEM - ISO 27001")
    print("=" * 80)

    # Afficher une partie du contenu HTML pour voir le texte IA
    # Chercher les sections ai_summary
    import re

    # Trouver les contenus des widgets
    matches = re.findall(r'<div class="ai-content"[^>]*>(.*?)</div>', content, re.DOTALL)

    if matches:
        for i, match in enumerate(matches):
            print(f"\n--- Widget IA {i+1} ---")
            # Nettoyer les tags HTML
            clean = re.sub(r'<[^>]+>', ' ', match)
            clean = re.sub(r'\s+', ' ', clean).strip()
            print(clean[:2000] if len(clean) > 2000 else clean)
    else:
        # Chercher autrement
        matches2 = re.findall(r'Résumé Exécutif.*?(?=<div class="widget"|$)', content, re.DOTALL)
        if matches2:
            clean = re.sub(r'<[^>]+>', ' ', matches2[0])
            clean = re.sub(r'\s+', ' ', clean).strip()
            print(clean[:3000])
        else:
            # Afficher juste le début du HTML
            print("Début du rapport:")
            print(content[:5000])

except Exception as e:
    print(f"Erreur: {e}")
