"""Export CSV des tables CRM (sélectif par table + filtre optionnel)."""

import csv
from pathlib import Path


def exporter_csv(crm, table, chemin=None, formula=None, max_records=1000):
    """Écrit les records d'une table CRM dans un CSV (UTF-8 BOM pour Excel).

    `formula` = filterByFormula Airtable optionnel (filtre sélectif).
    Renvoie (chemin, nb_lignes). Les colonnes = union des champs rencontrés.
    """
    records = crm.lister(table, formula=formula, max_records=max_records)
    chemin = chemin or f"export_{table.lower().replace(' ', '_')}.csv"
    # Colonnes : union ordonnée des clés (1re occurrence d'abord).
    colonnes = []
    for rec in records:
        for k in (rec.get("fields") or {}):
            if k not in colonnes:
                colonnes.append(k)
    with open(chemin, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=colonnes, extrasaction="ignore")
        w.writeheader()
        for rec in records:
            fields = rec.get("fields") or {}
            ligne = {}
            for k, v in fields.items():
                # Aplatissement : listes (liens, multi-select) -> texte joint.
                if isinstance(v, list):
                    ligne[k] = " | ".join(str(x) for x in v)
                else:
                    ligne[k] = v
            w.writerow(ligne)
    return chemin, len(records)
