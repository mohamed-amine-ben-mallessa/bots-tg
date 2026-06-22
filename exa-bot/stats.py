"""Gamification : compteurs de progression, objectifs, streak, badges, niveaux.

État par utilisateur, persistant (JsonStore). Chaque action du bot incrémente
des compteurs ; on en dérive un niveau, des badges débloqués et un streak de
jours actifs. Sert à rendre la prospection motivante et à montrer la progression.
"""

import datetime as _dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from botkit.store import JsonStore        # noqa: E402


# Paliers de niveau (score = somme pondérée des actions).
NIVEAUX = [
    (0, "🥉 Bronze"), (100, "🥈 Argent"), (300, "🥇 Or"),
    (700, "💎 Platine"), (1500, "👑 Légende"),
]

# Badges : (clé compteur, seuil, emoji, libellé).
BADGES = [
    ("contacts", 10, "🔍", "Chasseur (10 contacts)"),
    ("contacts", 100, "🎯", "Sniper (100 contacts)"),
    ("emails", 10, "✉️", "Vérificateur (10 emails)"),
    ("emails", 50, "📬", "Maître des emails (50)"),
    ("campagnes", 1, "📣", "Premier envoi"),
    ("envois", 50, "🚀", "Machine à outreach (50 envois)"),
    ("reponses", 1, "🎉", "Première réponse !"),
]

# Poids des actions dans le score.
POIDS = {"contacts": 1, "entreprises": 1, "emails": 3, "envois": 2,
         "campagnes": 5, "reponses": 10}

OBJECTIF_DEFAUT = 50          # leads/semaine


class Stats:
    def __init__(self, path="stats.json"):
        self._store = JsonStore(path)

    def _u(self, uid):
        return self._store.data.setdefault(str(uid), {
            "contacts": 0, "entreprises": 0, "emails": 0, "envois": 0,
            "campagnes": 0, "reponses": 0, "score": 0,
            "objectif": OBJECTIF_DEFAUT, "semaine": {}, "streak": 0,
            "dernier_jour": "", "badges": []})

    # ── incréments ────────────────────────────────────────────────────────────

    def ajouter(self, uid, compteur, n=1):
        """Incrémente un compteur, met à jour score/streak/semaine. Renvoie les
        nouveaux badges débloqués (liste de libellés)."""
        u = self._u(uid)
        u[compteur] = int(u.get(compteur, 0)) + n
        u["score"] = int(u.get("score", 0)) + POIDS.get(compteur, 1) * n
        self._maj_streak(u)
        self._maj_semaine(u, compteur, n)
        nouveaux = self._maj_badges(u)
        self._store.save()
        return nouveaux

    def _aujourdhui(self):
        return _dt.date.today().isoformat()

    def _maj_streak(self, u):
        auj = self._aujourdhui()
        dernier = u.get("dernier_jour", "")
        if dernier == auj:
            return
        hier = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()
        u["streak"] = (u.get("streak", 0) + 1) if dernier == hier else 1
        u["dernier_jour"] = auj

    def _semaine_courante(self):
        d = _dt.date.today()
        return f"{d.isocalendar()[0]}-S{d.isocalendar()[1]:02d}"

    def _maj_semaine(self, u, compteur, n):
        if compteur not in ("contacts", "entreprises"):
            return
        sem = u.setdefault("semaine", {})
        cle = self._semaine_courante()
        sem[cle] = int(sem.get(cle, 0)) + n
        # On ne garde que la semaine courante (pas d'historique infini).
        u["semaine"] = {cle: sem[cle]}

    def _maj_badges(self, u):
        debloques = set(u.get("badges", []))
        nouveaux = []
        for cle, seuil, emoji, libelle in BADGES:
            tag = f"{cle}:{seuil}"
            if tag not in debloques and u.get(cle, 0) >= seuil:
                debloques.add(tag)
                nouveaux.append(f"{emoji} {libelle}")
        u["badges"] = sorted(debloques)
        return nouveaux

    # ── lecture ───────────────────────────────────────────────────────────────

    def niveau(self, uid):
        score = self._u(uid).get("score", 0)
        nom = NIVEAUX[0][1]
        suivant = None
        for i, (seuil, label) in enumerate(NIVEAUX):
            if score >= seuil:
                nom = label
                suivant = NIVEAUX[i + 1] if i + 1 < len(NIVEAUX) else None
        return nom, score, suivant

    def objectif_semaine(self, uid):
        u = self._u(uid)
        fait = u.get("semaine", {}).get(self._semaine_courante(), 0)
        return fait, u.get("objectif", OBJECTIF_DEFAUT)

    def set_objectif(self, uid, n):
        self._u(uid)["objectif"] = max(1, int(n))
        self._store.save()

    def resume(self, uid):
        """Texte HTML de progression (pour /stats et le menu)."""
        u = self._u(uid)
        nom, score, suivant = self.niveau(uid)
        fait, obj = self.objectif_semaine(uid)
        barre = _barre(fait, obj)
        lignes = [
            f"📊 <b>Ta progression</b>\n",
            f"🏆 Niveau : <b>{nom}</b> · {score} pts"
            + (f" (→ {suivant[1]} à {suivant[0]})" if suivant else " · max !"),
            f"🔥 Streak : <b>{u.get('streak', 0)} jour(s)</b>",
            f"\n🎯 Objectif semaine : {fait}/{obj} leads\n{barre}",
            f"\n🔍 Contacts : {u.get('contacts', 0)} · 🏢 Entreprises : {u.get('entreprises', 0)}",
            f"✉️ Emails vérifiés : {u.get('emails', 0)} · 🚀 Envois : {u.get('envois', 0)}",
            f"📣 Campagnes : {u.get('campagnes', 0)} · 🎉 Réponses : {u.get('reponses', 0)}",
        ]
        badges = u.get("badges", [])
        if badges:
            noms = []
            for cle, seuil, emoji, libelle in BADGES:
                if f"{cle}:{seuil}" in badges:
                    noms.append(emoji)
            lignes.append(f"\n🏅 Badges : {' '.join(noms)} ({len(badges)})")
        return "\n".join(lignes)


def _barre(fait, total, taille=10):
    total = max(1, total)
    plein = min(taille, round(taille * fait / total))
    return "▰" * plein + "▱" * (taille - plein) + f"  {round(100 * fait / total)}%"
