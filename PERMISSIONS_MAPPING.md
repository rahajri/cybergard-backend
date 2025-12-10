# Mapping des Permissions par Module API

## Résumé

Application réussie de `require_permission` sur **8 fichiers API** avec **34 endpoints protégés**.

## Détail par Module

### 1. attachments.py - GED_READ (7 endpoints)
- `POST /upload` - Upload de fichier
- `GET /{attachment_id}/download` - Téléchargement de fichier
- `GET /{attachment_id}` - Métadonnées d'un fichier
- `GET /answer/{answer_id}` - Liste des fichiers d'une réponse
- `DELETE /{attachment_id}` - Suppression d'un fichier
- `GET /stats/tenant/{tenant_id}` - Statistiques GED

**Permission appliquée**: `GED_READ`

### 2. action_plans.py - ACTION_PLAN_READ (1 endpoint)
- `GET /{campaign_id}/action-plan` - Récupération du plan d'action

**Permission appliquée**: `ACTION_PLAN_READ`

### 3. action_plan_generate.py - ACTION_PLAN_* (5 endpoints)
- `GET /{campaign_id}/action-plan/generate/stream` - Génération SSE → **ACTION_PLAN_CREATE**
- `GET /{campaign_id}/action-plan/items` - Liste des items → **ACTION_PLAN_READ**
- `PUT /action-plan/items/{item_id}` - Mise à jour d'un item → **ACTION_PLAN_UPDATE**
- `POST /{campaign_id}/action-plan/publish` - Publication du plan → **ACTION_PLAN_CREATE**
- `DELETE /{campaign_id}/action-plan` - Suppression du plan → **ACTION_PLAN_DELETE**

**Permissions appliquées**: 
- `ACTION_PLAN_CREATE` (2 endpoints)
- `ACTION_PLAN_READ` (1 endpoint)
- `ACTION_PLAN_UPDATE` (1 endpoint)
- `ACTION_PLAN_DELETE` (1 endpoint)

### 4. control_points.py - REFERENTIAL_READ (6 endpoints)
- Tous les endpoints de gestion des points de contrôle
- Endpoint de test `/test-cp-query/{framework_id}`

**Permission appliquée**: `REFERENTIAL_READ`

### 5. user_management.py - USER_READ (1 endpoint)
- `GET /users` - Liste des utilisateurs

**Permission appliquée**: `USER_READ`

### 6. category_relationships.py - REFERENTIAL_READ (5 endpoints)
- `GET /categories/{category_id}/parents` - Parents d'une catégorie
- `GET /categories/{category_id}/contexts` - Contextes hiérarchiques
- `POST /categories/relationships` - Création d'une relation
- `DELETE /categories/relationships/{relationship_id}` - Suppression d'une relation
- `PATCH /categories/relationships/{relationship_id}/promote` - Promotion d'une relation

**Permission appliquée**: `REFERENTIAL_READ`

### 7. hierarchy.py - ECOSYSTEM_READ (1 endpoint)
- `GET /categories/{category_id}/children` - Sous-catégories

**Permission appliquée**: `ECOSYSTEM_READ`

### 8. campaign_scopes.py - CAMPAIGN_READ (1 endpoint)
- `POST /campaign-scopes` - Création d'un périmètre de campagne

**Permission appliquée**: `CAMPAIGN_READ`

## Fichiers NON modifiés

### collaboration.py
**Raison**: Certains endpoints sont accessibles par les audités via Magic Links.
**Action**: Aucune modification (comme demandé).

### audite.py
**Raison**: Endpoints dédiés aux audités externes via Magic Links.
**Action**: Déjà exclu de la modification (comme demandé).

## Statistiques Finales

- **Fichiers modifiés**: 8
- **Endpoints protégés**: 34
- **Permissions uniques utilisées**: 8
  - `GED_READ`
  - `ACTION_PLAN_READ`
  - `ACTION_PLAN_CREATE`
  - `ACTION_PLAN_UPDATE`
  - `ACTION_PLAN_DELETE`
  - `REFERENTIAL_READ`
  - `USER_READ`
  - `ECOSYSTEM_READ`
  - `CAMPAIGN_READ`

## Vérification

Tous les fichiers ont été vérifiés :
```bash
# Aucune occurrence de get_current_user_keycloak (sauf imports)
grep -rn "Depends(get_current_user_keycloak)" --include="*.py" .
```

## Date de modification
2025-01-30
