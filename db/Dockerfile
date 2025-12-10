# ---------- STAGE 1: build ----------
FROM postgres:15 AS builder

ARG PG_MAJOR=15
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    gcc \
    make \
    git \
    postgresql-server-dev-${PG_MAJOR} \
  && rm -rf /var/lib/apt/lists/*

# Compiler pgvector v0.8.0
RUN git clone --branch v0.8.0 --depth 1 https://github.com/pgvector/pgvector.git /tmp/pgvector \
 && make -C /tmp/pgvector \
 && make -C /tmp/pgvector install

# ---------- STAGE 2: final ----------
FROM postgres:15

# Copier les artefacts installés par "make install" depuis l’image builder
# (bibliothèque .so + fichiers .sql + control)
COPY --from=builder /usr/lib/postgresql/ /usr/lib/postgresql/
COPY --from=builder /usr/share/postgresql/ /usr/share/postgresql/

# Scripts d'init (exécutés au premier démarrage, quand le datadir est vide)
# - si tu montes déjà ./db/init.sql via docker-compose, tu peux COMMENTER la ligne COPY
COPY init.sql /docker-entrypoint-initdb.d/
