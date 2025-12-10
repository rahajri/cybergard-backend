-- Initialisation des extensions requises

\echo 'Creating database extensions...'

-- UUID
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- pgvector (nom d'extension = vector)
CREATE EXTENSION IF NOT EXISTS "vector";

-- trigrammes pour recherche full-text approx.
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

\echo 'Installed extensions:'
SELECT name, default_version, installed_version
FROM pg_available_extensions
WHERE installed_version IS NOT NULL
ORDER BY name;

\echo 'Database initialization completed successfully!'
