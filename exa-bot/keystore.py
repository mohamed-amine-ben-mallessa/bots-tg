"""Clés API par utilisateur (Exa, Serper) + suivi du coût Exa cumulé.

Chaque utilisateur Telegram fournit SES propres clés (CRUD). Persistées sur
disque (JsonStore atomique). Jamais affichées en clair (masquées).

⚠️ Stockage local en clair : protéger par permissions fichier + volume privé.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from botkit.store import JsonStore        # noqa: E402


def masquer(cle):
    c = (cle or "").strip()
    if len(c) <= 8:
        return "•" * len(c)
    return f"{c[:4]}…{c[-4:]}"


class KeyStore:
    """Clés (exa, serper) + coûts, indexés par user_id Telegram (str)."""

    def __init__(self, path="keys.json"):
        self._store = JsonStore(path)
        # { "<uid>": {"exa": "...", "serper": "...", "cost": 0.0, "calls": 0} }

    def _u(self, uid):
        return self._store.data.setdefault(str(uid), {})

    # ── CRUD générique par service ────────────────────────────────────────────

    def a_cle(self, uid, service="exa"):
        return bool(self._u(uid).get(service))

    def get(self, uid, service="exa"):
        return self._u(uid).get(service, "")

    def set(self, uid, cle, service="exa"):
        self._u(uid)[service] = (cle or "").strip()
        self._store.save()

    def supprimer(self, uid, service="exa"):
        existait = bool(self._u(uid).pop(service, None))
        self._store.save()
        return existait

    def masquee(self, uid, service="exa"):
        return masquer(self.get(uid, service))

    # ── compat Exa (anciens appels) ───────────────────────────────────────────

    def a_cle_exa(self, uid):
        return self.a_cle(uid, "exa")

    def get_exa(self, uid):
        return self.get(uid, "exa")

    def get_serper(self, uid):
        return self.get(uid, "serper")

    # ── suivi du coût Exa ─────────────────────────────────────────────────────

    def ajouter_cout(self, uid, montant):
        u = self._u(uid)
        u["cost"] = round(float(u.get("cost", 0.0)) + float(montant or 0), 6)
        u["calls"] = int(u.get("calls", 0)) + 1
        self._store.save()

    def cout_total(self, uid):
        return float(self._u(uid).get("cost", 0.0))

    def nb_appels(self, uid):
        return int(self._u(uid).get("calls", 0))
