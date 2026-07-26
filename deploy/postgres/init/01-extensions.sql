-- Extensions must exist before Alembic runs. Creating them inside a migration
-- requires superuser at migration time, which is not a privilege the application
-- role should hold in any environment that matters.

CREATE EXTENSION IF NOT EXISTS vector;      -- pgvector: embeddings + HNSW
CREATE EXTENSION IF NOT EXISTS pg_trgm;     -- trigram fuzzy matching
CREATE EXTENSION IF NOT EXISTS btree_gist;  -- required for the bitemporal
                                            -- EXCLUDE constraint on memory
CREATE EXTENSION IF NOT EXISTS citext;      -- case-insensitive email / slug
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- The NL2SQL flow queries a *separate* database with a read-only role, so a
-- generated SELECT can never reach the platform's own tables. Created here
-- because it needs superuser.
SELECT 'CREATE DATABASE mnemos_analytics OWNER mnemos'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'mnemos_analytics')\gexec
