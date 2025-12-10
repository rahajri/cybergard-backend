# Scripts Utilitaires Backend

Ce dossier contient les scripts utilitaires pour le backend de CyberGuard AI.

## 📁 Structure

```
scripts/
├── checks/          # Scripts de vérification et diagnostic
└── tests/           # Scripts de tests manuels et d'intégration
```

---

## 🔍 Scripts de Vérification (`/checks`)

### check_admin_user.py
**Usage** : Vérifier l'utilisateur admin et son organisation

```bash
python backend/scripts/checks/check_admin_user.py
```

**Informations affichées** :
- Détails de l'utilisateur admin@cyberguard.pro
- Organisation par défaut
- Tenant associé
- Statut actif

**Quand l'utiliser** :
- Debug de problèmes de connexion admin
- Vérification de la configuration initiale
- Diagnostic des permissions

---

### check_campaign_questionnaire.py
**Usage** : Vérifier les relations campagne-questionnaire

```bash
python backend/scripts/checks/check_campaign_questionnaire.py
```

**Informations affichées** :
- Liste des campagnes
- Questionnaires associés
- Statuts des campagnes
- Liens entre entités

**Quand l'utiliser** :
- Debug de problèmes de campagnes
- Vérification de l'intégrité des données
- Diagnostic de relations manquantes

---

### check_tenant_columns.py
**Usage** : Vérifier les colonnes tenant_id dans les tables

```bash
python backend/scripts/checks/check_tenant_columns.py
```

**Informations affichées** :
- Tables avec colonnes tenant_id
- Intégrité du schéma multi-tenant

**Quand l'utiliser** :
- Vérification de la migration multi-tenant
- Audit de sécurité SaaS
- Diagnostic de problèmes d'isolation

---

## 🧪 Scripts de Tests (`/tests`)

### test_magic_link.sh
**Usage** : Test manuel de l'intégration Magic Link + Keycloak

```bash
bash backend/scripts/tests/test_magic_link.sh
```

**Étapes du test** :
1. Génération d'un Magic Link
2. Échange du token Magic Link contre un token Keycloak
3. Test d'accès au questionnaire

**Données requises** :
- Email de l'audité
- Campaign ID (UUID)
- Questionnaire ID (UUID)
- Tenant ID (UUID)

**Quand l'utiliser** :
- Test de l'intégration Magic Link
- Vérification du flux d'authentification audité
- Debug de problèmes d'accès par Magic Link

---

### test_redis_integration.py
**Usage** : Test de l'intégration Redis

```bash
python backend/scripts/tests/test_redis_integration.py
```

**Tests effectués** :
- Connexion à Redis
- Opérations CRUD (Create, Read, Update, Delete)
- Expiration des clés
- Performance du cache

**Quand l'utiliser** :
- Vérification du fonctionnement de Redis
- Test des performances de cache
- Debug de problèmes de cache

---

### test_saas_controls.py ⚠️ CRITIQUE
**Usage** : Tests de sécurité SaaS et isolation multi-tenant

```bash
python backend/scripts/tests/test_saas_controls.py
```

**Tests de sécurité** :
- Isolation entre tenants
- Contrôles d'accès
- Fuites de données potentielles
- Validation des permissions

**Quand l'utiliser** :
- **Avant chaque déploiement en production**
- Audit de sécurité régulier
- Validation de nouvelles fonctionnalités multi-tenant
- Investigation de problèmes de sécurité

**⚠️ IMPORTANT** : Ce script doit passer sans erreur avant tout déploiement !

---

## 📝 Notes

### Variables d'environnement
Tous les scripts Python nécessitent les variables d'environnement du backend :
- `DATABASE_URL` : URL de connexion PostgreSQL
- `REDIS_URL` : URL de connexion Redis (pour test_redis_integration.py)
- Variables Keycloak (pour test_magic_link.sh)

### Chargement automatique
Les scripts chargent automatiquement le fichier `.env` du backend via `python-dotenv`.

### Prérequis
- Python 3.11+
- Backend installé (`pip install -r requirements.txt`)
- Base de données accessible
- Redis accessible (pour test Redis)
- Keycloak configuré (pour test Magic Link)

---

## 🔒 Sécurité

- ❌ Ne jamais commiter de données sensibles dans ces scripts
- ❌ Ne pas partager les sorties contenant des tokens ou credentials
- ✅ Toujours utiliser des données de test pour les démonstrations
- ✅ Exécuter test_saas_controls.py régulièrement

---

## 📚 Ressources

- [Documentation Backend](../../documentation/backend/)
- [Documentation Sécurité](../../documentation/SAAS_SECURITY_FIXES_SUMMARY.md)
- [Documentation Redis](../../documentation/infrastructure/redis_cache_guide.md)
- [Documentation Magic Link](../../documentation/keycloak/MAGIC_LINK_KEYCLOAK_IMPLEMENTATION.md)

---

*Dernière mise à jour : Novembre 2025*
