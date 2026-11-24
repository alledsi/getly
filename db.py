"""
Accès générique à la base Oracle du core banking ACEP.

Ce module ne connaît rien du "métier" (journal des écritures ou toute
future extraction) : il fournit juste un pool de connexions et un
utilitaire pour exécuter une requête et récupérer un DataFrame. Chaque
module d'extraction (dans extractions/) construit ses propres requêtes
SQL et appelle fetch_df().
"""

from __future__ import annotations

from functools import lru_cache

import oracledb
import pandas as pd

import config


@lru_cache(maxsize=1)
def get_pool() -> oracledb.ConnectionPool:
    """
    Crée (une seule fois par process) un pool de connexions vers la base
    Oracle du core banking. oracledb en mode "thin" ne nécessite pas
    l'installation du client Oracle sur la machine.
    """
    dsn = oracledb.makedsn(config.DB_HOST, config.DB_PORT, sid=config.DB_SID)
    return oracledb.create_pool(
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        dsn=dsn,
        min=1,
        max=4,
        increment=1,
    )


def fetch_df(sql: str, params: dict | None = None) -> pd.DataFrame:
    """Exécute une requête SQL paramétrée et retourne un DataFrame pandas
    avec TOUTES les lignes du résultat (pas de plafond)."""
    pool = get_pool()
    with pool.acquire() as conn:
        with conn.cursor() as cur:
            cur.arraysize = 1000  # réduit le nombre d'allers-retours réseau
            cur.execute(sql, params or {})
            columns = [c[0] for c in cur.description]
            rows = cur.fetchall()
    return pd.DataFrame(rows, columns=columns)


def truncate_and_insert(table: str, columns: list[str], rows: list[dict]) -> int:
    """Vide entièrement `table` puis y insère `rows` (une clé par colonne
    de `columns`), dans une seule transaction — utilisé par les
    Intégrations (ex. TABLE_REGUL) qui remplacent tout le contenu d'une
    table à chaque import.

    Utilise volontairement `DELETE FROM` plutôt que `TRUNCATE TABLE` :
    sous Oracle, TRUNCATE est un DDL qui déclenche un commit implicite
    immédiat — si l'insertion qui suit échouait, la table resterait vide
    sans possibilité de retour en arrière. Avec DELETE, le vidage et
    l'insertion sont commis ensemble à la fin : si l'insertion échoue,
    tout est annulé (rollback automatique à la fermeture de la connexion
    sans commit) et la table garde son contenu d'origine.

    Retourne le nombre de lignes insérées (0 si `rows` est vide — la
    table est alors simplement vidée)."""
    pool = get_pool()
    colonnes_sql = ", ".join(columns)
    placeholders = ", ".join(f":{c}" for c in columns)
    insert_sql = f"INSERT INTO {table} ({colonnes_sql}) VALUES ({placeholders})"
    with pool.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {table}")
            if rows:
                cur.executemany(insert_sql, rows)
        conn.commit()
    return len(rows)
