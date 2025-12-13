#!/usr/bin/env python3
"""
Script de chargement des referentiels EBIOS RM ANSSI

Ce script charge les donnees des fichiers JSON dans les tables referentielles.
Mode upsert: met a jour les entrees existantes et ajoute les nouvelles.

Usage:
    python load_ebios_seeds.py                  # Chargement normal (upsert)
    python load_ebios_seeds.py --drop-existing  # Supprime les donnees existantes d'abord
    python load_ebios_seeds.py --check          # Verifie seulement le nombre d'entrees

Prerequis:
    - La migration o1p2q3r4s5t6_add_ebios_anssi_reference_tables.py doit etre appliquee
    - La variable DATABASE_URL doit etre definie
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Ajouter le repertoire parent pour importer les modules du backend
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Configuration
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/audit_platform"
)

# Repertoire des fichiers JSON
SEEDS_DIR = Path(__file__).parent / "ebios"


def load_json_file(filename: str) -> dict:
    """Charge un fichier JSON depuis le repertoire seeds/ebios/."""
    filepath = SEEDS_DIR / filename
    if not filepath.exists():
        print(f"[ERROR] Fichier non trouve: {filepath}")
        return {}

    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def load_sources_risque(session, data: dict, drop_existing: bool = False) -> int:
    """Charge les sources de risque dans ref_ebios_sr."""
    if drop_existing:
        session.execute(text("DELETE FROM ref_ebios_sr"))
        print("  [INFO] Table ref_ebios_sr videe")

    sources = data.get("sources_risque", [])
    count = 0

    for sr in sources:
        try:
            session.execute(text("""
                INSERT INTO ref_ebios_sr (id, label, categorie, description, motivations, ressources, sophistication, tags, created_at)
                VALUES (:id, :label, :categorie, :description, CAST(:motivations AS jsonb), :ressources, :sophistication, CAST(:tags AS jsonb), :created_at)
                ON CONFLICT (id) DO UPDATE SET
                    label = EXCLUDED.label,
                    categorie = EXCLUDED.categorie,
                    description = EXCLUDED.description,
                    motivations = EXCLUDED.motivations,
                    ressources = EXCLUDED.ressources,
                    sophistication = EXCLUDED.sophistication,
                    tags = EXCLUDED.tags,
                    updated_at = :updated_at
            """), {
                "id": sr["id"],
                "label": sr["label"],
                "categorie": sr["categorie"],
                "description": sr.get("description"),
                "motivations": json.dumps(sr.get("motivations", [])),
                "ressources": sr.get("ressources"),
                "sophistication": sr.get("sophistication"),
                "tags": json.dumps(sr.get("tags", [])),
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            })
            count += 1
        except Exception as e:
            print(f"  [ERROR] Source {sr['id']}: {e}")

    return count


def load_biens_supports(session, data: dict, drop_existing: bool = False) -> int:
    """Charge les biens supports dans ref_ebios_bs."""
    if drop_existing:
        session.execute(text("DELETE FROM ref_ebios_bs"))
        print("  [INFO] Table ref_ebios_bs videe")

    biens = data.get("biens_supports", [])
    count = 0

    for bs in biens:
        try:
            session.execute(text("""
                INSERT INTO ref_ebios_bs (id, label, type, description, exemples, tags, created_at)
                VALUES (:id, :label, :type, :description, CAST(:exemples AS jsonb), CAST(:tags AS jsonb), :created_at)
                ON CONFLICT (id) DO UPDATE SET
                    label = EXCLUDED.label,
                    type = EXCLUDED.type,
                    description = EXCLUDED.description,
                    exemples = EXCLUDED.exemples,
                    tags = EXCLUDED.tags,
                    updated_at = :updated_at
            """), {
                "id": bs["id"],
                "label": bs["label"],
                "type": bs["type"],
                "description": bs.get("description"),
                "exemples": json.dumps(bs.get("exemples", [])),
                "tags": json.dumps(bs.get("tags", [])),
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            })
            count += 1
        except Exception as e:
            print(f"  [ERROR] Bien {bs['id']}: {e}")

    return count


def load_valeurs_metier(session, data: dict, drop_existing: bool = False) -> int:
    """Charge les valeurs metier dans ref_ebios_vm."""
    if drop_existing:
        session.execute(text("DELETE FROM ref_ebios_vm"))
        print("  [INFO] Table ref_ebios_vm videe")

    valeurs = data.get("valeurs_metier", [])
    count = 0

    for vm in valeurs:
        try:
            session.execute(text("""
                INSERT INTO ref_ebios_vm (id, label, nature, description, exemples, besoins_securite, tags, created_at)
                VALUES (:id, :label, :nature, :description, CAST(:exemples AS jsonb), CAST(:besoins_securite AS jsonb), CAST(:tags AS jsonb), :created_at)
                ON CONFLICT (id) DO UPDATE SET
                    label = EXCLUDED.label,
                    nature = EXCLUDED.nature,
                    description = EXCLUDED.description,
                    exemples = EXCLUDED.exemples,
                    besoins_securite = EXCLUDED.besoins_securite,
                    tags = EXCLUDED.tags,
                    updated_at = :updated_at
            """), {
                "id": vm["id"],
                "label": vm["label"],
                "nature": vm.get("nature"),
                "description": vm.get("description"),
                "exemples": json.dumps(vm.get("exemples", [])),
                "besoins_securite": json.dumps(vm.get("besoins_securite", [])),
                "tags": json.dumps(vm.get("tags", [])),
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            })
            count += 1
        except Exception as e:
            print(f"  [ERROR] Valeur {vm['id']}: {e}")

    return count


def load_evenements_redoutes(session, data: dict, drop_existing: bool = False) -> int:
    """Charge les evenements redoutes dans ref_ebios_er."""
    if drop_existing:
        session.execute(text("DELETE FROM ref_ebios_er"))
        print("  [INFO] Table ref_ebios_er videe")

    evenements = data.get("evenements_redoutes", [])
    count = 0

    for er in evenements:
        try:
            session.execute(text("""
                INSERT INTO ref_ebios_er (id, label, description, critere_atteint, gravite_default, impacts_types, tags, created_at)
                VALUES (:id, :label, :description, :critere_atteint, :gravite_default, CAST(:impacts_types AS jsonb), CAST(:tags AS jsonb), :created_at)
                ON CONFLICT (id) DO UPDATE SET
                    label = EXCLUDED.label,
                    description = EXCLUDED.description,
                    critere_atteint = EXCLUDED.critere_atteint,
                    gravite_default = EXCLUDED.gravite_default,
                    impacts_types = EXCLUDED.impacts_types,
                    tags = EXCLUDED.tags,
                    updated_at = :updated_at
            """), {
                "id": er["id"],
                "label": er["label"],
                "description": er.get("description"),
                "critere_atteint": er.get("critere_atteint"),
                "gravite_default": er.get("gravite_default"),
                "impacts_types": json.dumps(er.get("impacts_types", [])),
                "tags": json.dumps(er.get("tags", [])),
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            })
            count += 1
        except Exception as e:
            print(f"  [ERROR] Evenement {er['id']}: {e}")

    return count


def load_objectifs_vises(session, data: dict, drop_existing: bool = False) -> int:
    """Charge les objectifs vises dans ref_ebios_ov."""
    if drop_existing:
        session.execute(text("DELETE FROM ref_ebios_ov"))
        print("  [INFO] Table ref_ebios_ov videe")

    objectifs = data.get("objectifs_vises", [])
    count = 0

    for ov in objectifs:
        try:
            session.execute(text("""
                INSERT INTO ref_ebios_ov (id, label, description, finalites, secteurs_cibles, sources_typiques, tags, created_at)
                VALUES (:id, :label, :description, CAST(:finalites AS jsonb), CAST(:secteurs_cibles AS jsonb), CAST(:sources_typiques AS jsonb), CAST(:tags AS jsonb), :created_at)
                ON CONFLICT (id) DO UPDATE SET
                    label = EXCLUDED.label,
                    description = EXCLUDED.description,
                    finalites = EXCLUDED.finalites,
                    secteurs_cibles = EXCLUDED.secteurs_cibles,
                    sources_typiques = EXCLUDED.sources_typiques,
                    tags = EXCLUDED.tags,
                    updated_at = :updated_at
            """), {
                "id": ov["id"],
                "label": ov["label"],
                "description": ov.get("description"),
                "finalites": json.dumps(ov.get("finalites", [])),
                "secteurs_cibles": json.dumps(ov.get("secteurs_cibles", [])),
                "sources_typiques": json.dumps(ov.get("sources_typiques", [])),
                "tags": json.dumps(ov.get("tags", [])),
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            })
            count += 1
        except Exception as e:
            print(f"  [ERROR] Objectif {ov['id']}: {e}")

    return count


def load_guides(session, data: dict, drop_existing: bool = False) -> int:
    """Charge les guides ANSSI dans ref_ebios_guides."""
    if drop_existing:
        session.execute(text("DELETE FROM ref_ebios_guides"))
        print("  [INFO] Table ref_ebios_guides videe")

    guides = data.get("guides", [])
    count = 0

    for guide in guides:
        try:
            session.execute(text("""
                INSERT INTO ref_ebios_guides (id, atelier, titre, extrait, reference_pdf, created_at)
                VALUES (:id, :atelier, :titre, :extrait, :reference_pdf, :created_at)
                ON CONFLICT (id) DO UPDATE SET
                    atelier = EXCLUDED.atelier,
                    titre = EXCLUDED.titre,
                    extrait = EXCLUDED.extrait,
                    reference_pdf = EXCLUDED.reference_pdf,
                    updated_at = :updated_at
            """), {
                "id": guide["id"],
                "atelier": guide["atelier"],
                "titre": guide.get("titre"),
                "extrait": guide["extrait"],
                "reference_pdf": guide.get("reference_pdf"),
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            })
            count += 1
        except Exception as e:
            print(f"  [ERROR] Guide {guide['id']}: {e}")

    return count


def check_counts(session) -> dict:
    """Verifie le nombre d'entrees dans chaque table."""
    tables = [
        "ref_ebios_sr",
        "ref_ebios_bs",
        "ref_ebios_vm",
        "ref_ebios_er",
        "ref_ebios_ov",
        "ref_ebios_guides"
    ]

    counts = {}
    for table in tables:
        try:
            result = session.execute(text(f"SELECT COUNT(*) FROM {table}"))
            counts[table] = result.scalar()
        except Exception as e:
            counts[table] = f"ERROR: {e}"

    return counts


def main():
    parser = argparse.ArgumentParser(
        description="Charge les referentiels EBIOS RM ANSSI dans la base de donnees"
    )
    parser.add_argument(
        "--drop-existing",
        action="store_true",
        help="Supprime les donnees existantes avant le chargement"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verifie seulement le nombre d'entrees sans charger"
    )
    parser.add_argument(
        "--database-url",
        type=str,
        default=DATABASE_URL,
        help="URL de connexion a la base de donnees"
    )

    args = parser.parse_args()

    print("=" * 60)
    print("Chargement des referentiels EBIOS RM ANSSI")
    print("=" * 60)
    print(f"Database: {args.database_url[:50]}...")
    print(f"Seeds directory: {SEEDS_DIR}")
    print()

    # Connexion a la base
    try:
        engine = create_engine(args.database_url)
        Session = sessionmaker(bind=engine)
        session = Session()
        print("[OK] Connexion a la base de donnees etablie")
    except Exception as e:
        print(f"[ERROR] Impossible de se connecter a la base: {e}")
        sys.exit(1)

    # Mode verification uniquement
    if args.check:
        print("\n[INFO] Mode verification - Comptage des entrees:\n")
        counts = check_counts(session)
        for table, count in counts.items():
            print(f"  {table}: {count}")
        session.close()
        return

    # Chargement des fichiers JSON
    print("\n[STEP 1] Chargement des fichiers JSON...")

    files_to_load = [
        ("ref_ebios_sr.json", load_sources_risque),
        ("ref_ebios_bs.json", load_biens_supports),
        ("ref_ebios_vm.json", load_valeurs_metier),
        ("ref_ebios_er.json", load_evenements_redoutes),
        ("ref_ebios_ov.json", load_objectifs_vises),
        ("ref_ebios_guides.json", load_guides),
    ]

    results = {}

    try:
        print("\n[STEP 2] Insertion des donnees en base...")

        for filename, loader_func in files_to_load:
            print(f"\n  Processing {filename}...")
            data = load_json_file(filename)

            if not data:
                print(f"  [WARN] Fichier vide ou non trouve: {filename}")
                results[filename] = 0
                continue

            count = loader_func(session, data, args.drop_existing)
            results[filename] = count
            print(f"  [OK] {count} entrees chargees depuis {filename}")

        # Commit final
        session.commit()
        print("\n[OK] Toutes les donnees ont ete commitees")

    except Exception as e:
        session.rollback()
        print(f"\n[ERROR] Erreur lors du chargement: {e}")
        sys.exit(1)

    finally:
        session.close()

    # Resume
    print("\n" + "=" * 60)
    print("RESUME DU CHARGEMENT")
    print("=" * 60)

    total = 0
    for filename, count in results.items():
        print(f"  {filename}: {count} entrees")
        total += count

    print(f"\n  TOTAL: {total} entrees chargees")
    print("\n[DONE] Chargement termine avec succes!")


if __name__ == "__main__":
    main()
