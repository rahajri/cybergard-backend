# Exemple basé sur tes logs (multi-stage)
FROM postgres:15 AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates gcc make git postgresql-server-dev-15 && \
    rm -rf /var/lib/apt/lists/*

RUN git clone --branch v0.8.0 --depth 1 https://github.com/pgvector/pgvector.git /tmp/pgvector \
    && make -C /tmp/pgvector install

FROM postgres:15

# Extensions compilées
COPY --from=builder /usr/lib/postgresql/ /usr/lib/postgresql/
COPY --from=builder /usr/share/postgresql/ /usr/share/postgresql/

# Script d'init
COPY init.sql /docker-entrypoint-initdb.d/init.sql
