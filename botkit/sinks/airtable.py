"""Stockage de résultats dans Airtable (via pyairtable).

Sink commun à tous les bots : chaque bot mappe ses items en dict {colonne: valeur}
et appelle `enregistrer(...)`. pyairtable gère la limite de 10 records/requête.

Config via variables d'environnement (ou passée explicitement) :
  AIRTABLE_TOKEN, AIRTABLE_BASE_ID, AIRTABLE_TABLE
"""

import os


class AirtableError(RuntimeError):
    pass


def _table(base_id=None, table=None):
    try:
        from pyairtable import Api
    except ImportError as e:
        raise AirtableError(
            "pyairtable manquant : `pip install pyairtable`.") from e
    token = os.environ.get("AIRTABLE_TOKEN", "").strip()
    base_id = base_id or os.environ.get("AIRTABLE_BASE_ID", "").strip()
    table = table or os.environ.get("AIRTABLE_TABLE", "").strip()
    if not (token and base_id and table):
        raise AirtableError(
            "Config Airtable incomplète : AIRTABLE_TOKEN / AIRTABLE_BASE_ID / "
            "AIRTABLE_TABLE requis.")
    return Api(token).table(base_id, table)


def disponible():
    """True si la config Airtable est présente (pour afficher/masquer le bouton)."""
    return all(os.environ.get(k) for k in
               ("AIRTABLE_TOKEN", "AIRTABLE_BASE_ID", "AIRTABLE_TABLE"))


def enregistrer(records, base_id=None, table=None):
    """Crée des enregistrements dans Airtable. `records` = liste de dicts.

    Renvoie le nombre d'enregistrements créés. Lève AirtableError si la config
    manque ou si l'API échoue.
    """
    if not records:
        return 0
    t = _table(base_id, table)
    try:
        crees = t.batch_create(records)   # gère le découpage par lots de 10
    except Exception as e:
        raise AirtableError(f"Échec d'écriture Airtable : {e}") from e
    return len(crees)
