"""
Configuration de l'application Getly.

Toutes les informations sensibles (hôte, identifiants, etc.) sont lues
depuis un fichier .env situé à la racine du projet (voir .env.example).
Ne jamais mettre ces valeurs "en dur" dans le code source.
"""

import os

from dotenv import load_dotenv

load_dotenv()  # charge le fichier .env s'il existe


def _get_env(name: str, default: str | None = None, required: bool = False) -> str:
    value = os.getenv(name, default)
    if required and not value:
        raise RuntimeError(
            f"La variable d'environnement '{name}' est manquante. "
            f"Vérifie ton fichier .env (voir .env.example)."
        )
    return value


# --- Connexion Oracle (core banking ACEP) ---
DB_HOST = _get_env("DB_HOST", required=True)
DB_PORT = int(_get_env("DB_PORT", "1521"))
DB_SID = _get_env("DB_SID", required=True)
DB_USER = _get_env("DB_USER", required=True)
DB_PASSWORD = _get_env("DB_PASSWORD", required=True)
