"""Persistance simple sur disque (écriture atomique) pour l'état des bots.

Deux primitives réutilisables :
  • JsonStore  : un dict persistant (état de questionnaire, config légère…).
  • SeenStore  : un ensemble d'identifiants déjà vus (dédoublonnage d'alertes).

Écriture atomique (tmp + os.replace) : jamais de fichier à moitié écrit, même
si le process meurt en plein write.
"""

import json
import os
from pathlib import Path


def _ecrire_atomique(path: Path, payload: str):
    """Écrit `payload` dans `path`, atomiquement quand c'est possible.

    Si `path` est un fichier bind-monté dans Docker, `os.replace` échoue avec
    « Errno 16 Device busy » (on ne peut pas remplacer le fichier monté). On
    retombe alors sur une écriture directe (non atomique mais fonctionnelle).
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    try:
        os.replace(tmp, path)
    except OSError:
        # Fallback (fichier monté / cross-device) : écriture directe.
        path.write_text(payload, encoding="utf-8")
        try:
            tmp.unlink()
        except OSError:
            pass


class JsonStore:
    """Dict persistant. `data` est chargé du disque, modifié, puis save()."""

    def __init__(self, path):
        self.path = Path(path)
        self.data = {}
        self._load()

    def _load(self):
        if not self.path.exists():
            return
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8")) or {}
        except (json.JSONDecodeError, OSError):
            self.data = {}

    def get(self, key, defaut=None):
        return self.data.get(key, defaut)

    def set(self, key, value):
        self.data[key] = value
        self.save()

    def clear(self):
        self.data = {}
        try:
            if self.path.exists():
                self.path.unlink()
        except OSError:
            pass

    def save(self):
        _ecrire_atomique(self.path, json.dumps(self.data, ensure_ascii=False))


class SeenStore:
    """Ensemble persistant d'identifiants déjà vus (FIFO borné)."""

    def __init__(self, path, max_ids=5000):
        self.path = Path(path)
        self._max = max_ids
        self._ids = []
        self._set = set()
        self._load()

    def _load(self):
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        ids = data.get("ids", []) if isinstance(data, dict) else []
        self._ids = [str(x) for x in ids if x]
        self._set = set(self._ids)

    def is_seen(self, oid):
        return str(oid) in self._set

    def add(self, oid):
        oid = str(oid or "").strip()
        if oid and oid not in self._set:
            self._ids.append(oid)
            self._set.add(oid)

    def add_many(self, ids):
        for oid in ids:
            self.add(oid)

    def filtrer_nouveaux(self, items, cle):
        """Renvoie les items dont `cle(item)` n'a jamais été vu (sans enregistrer)."""
        return [it for it in items if not cle(it) or not self.is_seen(cle(it))]

    def save(self):
        if len(self._ids) > self._max:
            self._ids = self._ids[-self._max:]
            self._set = set(self._ids)
        _ecrire_atomique(self.path, json.dumps({"ids": self._ids}, ensure_ascii=False))

    def __len__(self):
        return len(self._ids)
