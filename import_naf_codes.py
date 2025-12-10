import re
import os
import sys
import pandas as pd
from sqlalchemy import create_engine, text

# --- Connexion Postgres (adapte host/port si besoin)
engine = create_engine("postgresql://postgres:postgres@localhost:5432/audit_platform")

# --- Fichier Excel (argument ou auto-détection)
excel_path = sys.argv[1] if len(sys.argv) > 1 else "int_courts_naf_rev_2.xls"
if not os.path.isfile(excel_path):
    raise FileNotFoundError(f"Fichier introuvable: {excel_path}")

# --- Choix moteur selon extension
ext = os.path.splitext(excel_path)[1].lower()
engine_name = "xlrd" if ext == ".xls" else "openpyxl"

# --- Lecture
try:
    df = pd.read_excel(excel_path, engine=engine_name)
except Exception:
    df = pd.read_excel(excel_path)  # fallback

print("Colonnes détectées :", list(df.columns))

# --- Normalisation noms colonnes (on garde 'Code' et un libellé)
# On cherche une colonne qui contient 'Code' (exact ou proche)
code_col = None
for c in df.columns:
    if str(c).strip().lower() == "code":
        code_col = c
        break
if code_col is None:
    # essaie de trouver un équivalent
    for c in df.columns:
        if "code" in str(c).lower():
            code_col = c
            break
if code_col is None:
    raise ValueError("Colonne 'Code' non trouvée dans le fichier Excel.")

# Choix du libellé : on préfère la colonne 'Intitulés … 65 caractères' si présente
label_candidates = [c for c in df.columns if "65 caractères" in str(c)]
if label_candidates:
    label_col = label_candidates[0]
else:
    # sinon, on prend la colonne avec 'Intitulé' la plus longue
    intitule_cols = [c for c in df.columns if "Intitul" in str(c)]
    label_col = intitule_cols[0] if intitule_cols else df.columns[-1]  # fallback

# --- Sélection colonnes utiles
df = df[[code_col, label_col]].copy()
df.columns = ["code", "label"]

# --- Nettoyage
for c in ["code", "label"]:
    df[c] = df[c].astype(str).str.strip()

# --- Filtre: garder uniquement les codes NAF valides
# Formats acceptés:
#  - '62' (division)
#  - '62.0' / '62.01' (groupe/classe)
#  - '62.01Z' (sous-classe)
naf_regex = re.compile(r"^\d{2}(\.\d{1,2}([A-Z])?)?$")
df = df[df["code"].apply(lambda x: bool(naf_regex.match(x)))].copy()

# --- Dérive division (2 premiers chiffres) et group_code (ex: '62.01' si présent)
def derive_division(code: str) -> str:
    return code[:2]

def derive_group(code: str) -> str | None:
    # '62.01Z' -> '62.01' ; '62.01' -> '62.01' ; '62' -> None
    if "." in code:
        parts = code.split(".")
        if len(parts) >= 2:
            # garde seulement les deux chiffres après le point s'ils existent
            post = parts[1]
            # cas '62.0' ou '62.01' ou '62.01Z'
            digits = "".join(ch for ch in post if ch.isdigit())
            if len(digits) >= 1:
                # group_code = '62.' + 2 digits si possibles, sinon 1 digit
                if len(digits) >= 2:
                    return f"{parts[0]}.{digits[:2]}"
                else:
                    return f"{parts[0]}.{digits[:1]}"
    return None

df["division"] = df["code"].apply(derive_division)
df["group_code"] = df["code"].apply(derive_group)

# --- Tronque pour coller aux longueurs SQL de ta table (sécurité)
df["code"] = df["code"].str[:10]
df["label"] = df["label"].str[:255]
if "division" in df:
    df["division"] = df["division"].str[:5]
if "group_code" in df:
    df["group_code"] = df["group_code"].fillna("").astype(str).str[:5]

# --- Option: éviter les doublons avant insert
df = df.drop_duplicates(subset=["code"])

# --- Insert "upsert" (remplace to_sql pour mieux gérer conflits)
with engine.begin() as conn:
    # Crée la table si elle n'existe pas (minimale, si tu n'as pas déjà exécuté le CREATE TABLE)
    conn.execute(text("""
    CREATE TABLE IF NOT EXISTS public.naf_codes (
        code        VARCHAR(10) PRIMARY KEY,
        label       VARCHAR(255) NOT NULL,
        section     CHAR(1),
        section_name VARCHAR(255),
        division    VARCHAR(5),
        group_code  VARCHAR(5),
        domain      VARCHAR(255),
        sector_slug VARCHAR(64),
        created_at  TIMESTAMP DEFAULT NOW(),
        updated_at  TIMESTAMP DEFAULT NOW()
    );
    """))
    # upsert ligne à ligne (simple et sûr)
    ins = text("""
        INSERT INTO public.naf_codes (code, label, division, group_code)
        VALUES (:code, :label, :division, :group_code)
        ON CONFLICT (code) DO UPDATE
        SET label = EXCLUDED.label,
            division = EXCLUDED.division,
            group_code = EXCLUDED.group_code,
            updated_at = NOW();
    """)
    conn.execute(ins, df.to_dict(orient="records"))

print(f"✅ {len(df)} lignes NAF valides importées/à jour dans naf_codes")
