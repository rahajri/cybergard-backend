# Referentiels EBIOS RM ANSSI - Seeds

Ce repertoire contient les donnees de reference extraites des guides officiels ANSSI pour la methode EBIOS Risk Manager.

## Structure des fichiers

```
backend/seeds/
├── ebios/
│   ├── ref_ebios_sr.json      # Sources de risque types (11 entrees)
│   ├── ref_ebios_bs.json      # Biens supports types (18 entrees)
│   ├── ref_ebios_vm.json      # Valeurs metier types (15 entrees)
│   ├── ref_ebios_er.json      # Evenements redoutes types (18 entrees)
│   ├── ref_ebios_ov.json      # Objectifs vises types (8 entrees)
│   └── ref_ebios_guides.json  # Extraits guides ANSSI (13 entrees)
├── load_ebios_seeds.py        # Script de chargement
└── README.md                  # Cette documentation
```

## Contenu des referentiels

### ref_ebios_sr - Sources de risque (11 entrees)

| ID | Categorie | Description |
|----|-----------|-------------|
| SR_ETATIQUE | ETATIQUE | Etats, agences de renseignement |
| SR_CRIME_ORGANISE | CYBERCRIMINELS | Crime organise, mafias |
| SR_TERRORISTE | TERRORISTE | Cyberterroristes, milices |
| SR_ACTIVISTE | ACTIVISTE | Hacktivistes, ideologues |
| SR_CONCURRENT | CONCURRENT | Espionnage industriel |
| SR_OFFICINE | OFFICINE | Cybermercenaires |
| SR_AMATEUR | AMATEUR | Script-kiddies |
| SR_VENGEUR | VENGEUR | Employes mecontents |
| SR_MALVEILLANT_PATHO | MALVEILLANT | Opportunistes, fraudeurs |
| SR_FOURNISSEUR | FOURNISSEUR | Prestataires negligents |
| SR_EMPLOYE_INTERNE | INTERNE | Menace interne |

### ref_ebios_bs - Biens supports (18 entrees)

Categories : MATERIEL, LOGICIEL, RESEAU, APPLICATION, DONNEES, INFRASTRUCTURE, ORGANISATION, HUMAIN, LOCAUX

### ref_ebios_vm - Valeurs metier (15 entrees)

Natures : PROCESSUS, INFORMATION, SAVOIR_FAIRE

### ref_ebios_er - Evenements redoutes (18 entrees)

Echelle de gravite :
- **G1** : Mineure (aucun impact operationnel)
- **G2** : Significative (mode degrade)
- **G3** : Grave (mode tres degrade)
- **G4** : Critique (survie menacee)

### ref_ebios_ov - Objectifs vises (8 entrees)

- Espionnage, Prepositionnement, Influence, Entrave/Sabotage, Lucratif, Defi, Vengeance, Ideologique

### ref_ebios_guides - Extraits ANSSI (13 entrees)

Guides par atelier : AT1, AT2, AT3, AT4, AT5, COMMUN

## Installation

### 1. Appliquer les migrations

```bash
cd backend
python -m alembic upgrade head
```

Les migrations suivantes seront appliquees :
- `o1p2q3r4s5t6_add_ebios_anssi_reference_tables.py` : Cree les 7 tables referentielles
- `p1q2r3s4t5u6_add_analysis_version_to_risk_project.py` : Ajoute la colonne `analysis_version`

### 2. Charger les donnees

```bash
# Chargement standard (mode upsert - idempotent)
python seeds/load_ebios_seeds.py

# Avec suppression des donnees existantes
python seeds/load_ebios_seeds.py --drop-existing

# Verification du contenu
python seeds/load_ebios_seeds.py --check
```

### Configuration

Definir la variable d'environnement `DATABASE_URL` :

```bash
# Linux/Mac
export DATABASE_URL="postgresql://user:password@localhost:5432/audit_platform"

# Windows PowerShell
$env:DATABASE_URL="postgresql://user:password@localhost:5432/audit_platform"
```

Ou modifier directement dans `load_ebios_seeds.py` la valeur par defaut.

## Utilisation dans le code

### Importer le service

```python
from src.services.ebios_reference_service import EbiosReferenceService

# Dans un endpoint FastAPI
@router.get("/ebios/referentiels/check")
async def check_referentiels(db: Session = Depends(get_db)):
    service = EbiosReferenceService(db)
    counts = service.check_referentiels_loaded()
    return counts
```

### Recuperer les referentiels pour un prompt IA

```python
from src.services.ebios_reference_service import EbiosReferenceService

def get_at1_prompt_context(db: Session) -> dict:
    service = EbiosReferenceService(db)
    return service.get_referentiels_for_at1()

# Retourne:
# {
#   "valeurs_metier": "texte formate...",
#   "biens_supports": "texte formate...",
#   "evenements_redoutes": "texte formate...",
#   "guides": "extraits ANSSI..."
# }
```

### Verifier si un projet utilise le mode v2

```python
from src.services.ebios_reference_service import EbiosReferenceService

def generate_at1(project_id: str, db: Session):
    service = EbiosReferenceService(db)

    if service.is_ebios_rm_v2_enabled(project_id):
        # Utiliser le nouveau pipeline avec referentiels ANSSI
        refs = service.get_referentiels_for_at1()
        # ... nouveau prompt avec refs
    else:
        # Comportement legacy
        # ... ancien prompt
```

## Architecture

### Tables creees

```sql
-- Referentiels ANSSI
ref_ebios_sr       -- Sources de risque types
ref_ebios_bs       -- Biens supports types
ref_ebios_vm       -- Valeurs metier types
ref_ebios_er       -- Evenements redoutes types
ref_ebios_ov       -- Objectifs vises types
ref_ebios_guides   -- Extraits guides ANSSI

-- Journalisation IA
ai_generation_logs -- Logs des appels IA par atelier

-- Modification existante
risk_project.analysis_version  -- 'legacy' | 'ebios_rm_v2'
```

### Service EbiosReferenceService

Methodes principales :
- `get_sources_risque()` / `get_sources_risque_for_prompt()`
- `get_biens_supports()` / `get_biens_supports_for_prompt()`
- `get_valeurs_metier()` / `get_valeurs_metier_for_prompt()`
- `get_evenements_redoutes()` / `get_evenements_redoutes_for_prompt()`
- `get_objectifs_vises()` / `get_objectifs_vises_for_prompt()`
- `get_guides_by_atelier()` / `get_guides_for_prompt()`
- `get_referentiels_for_at1()` / `get_referentiels_for_at2()` / etc.
- `check_referentiels_loaded()`
- `is_ebios_rm_v2_enabled(project_id)`

## Mise a jour des referentiels

Pour mettre a jour les donnees :

1. Modifier les fichiers JSON dans `seeds/ebios/`
2. Relancer le script de chargement

```bash
python seeds/load_ebios_seeds.py
```

Le script est **idempotent** : il met a jour les entrees existantes (base sur l'ID) et ajoute les nouvelles.

## Volumetrie ANSSI recommandee

Selon les guides ANSSI :
- **Valeurs metier** : 5-10 par projet
- **Biens supports** : 1-3 par valeur metier (8-15 au total)
- **Evenements redoutes** : 5-10 par projet
- **Sources de risque** : 5-12 par projet
- **Couples SR/OV** : 3-6 par etude
- **Scenarios strategiques** : 1-3 par couple SR/OV

## Sources

- **Guide EBIOS Risk Manager** - ANSSI, Edition 2024
- **Fiches Methodes EBIOS RM** - ANSSI, Supplement v1.1

## Notes importantes

1. **Mode legacy preserve** : Les projets existants continuent de fonctionner avec `analysis_version='legacy'`

2. **Activation par projet** : Le mode `ebios_rm_v2` s'active projet par projet

3. **Referentiels = guides** : Ces donnees sont des guides pour l'IA, pas des contraintes strictes. L'IA doit s'en inspirer mais adapter au contexte specifique de chaque projet.

4. **Gravite 1-4** : Utiliser l'echelle 4 niveaux pour la plupart des cas
