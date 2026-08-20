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


def test_connection() -> tuple[bool, str]:
    """Essaie d'ouvrir une connexion, pour un bouton 'Tester la connexion'."""
    try:
        pool = get_pool()
        with pool.acquire() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM DUAL")
                cur.fetchone()
        return True, "Connexion à la base ACEP réussie."
    except Exception as exc:  # noqa: BLE001
        return False, f"Échec de connexion : {exc}"


def fetch_df(sql: str, params: dict | None = None) -> pd.DataFrame:
    """Exécute une requête SQL paramétrée et retourne un DataFrame pandas."""
    pool = get_pool()
    with pool.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or {})
            columns = [c[0] for c in cur.description]
            rows = cur.fetchmany(config.MAX_ROWS)
    return pd.DataFrame(rows, columns=columns)
