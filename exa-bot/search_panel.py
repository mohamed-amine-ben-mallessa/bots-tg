"""Panneau de recherche interactif (people/company) : état + claviers.

Tout par boutons : l'utilisateur choisit une marque, un ICP, sélectionne les
requêtes générées, règle les paramètres (nb résultats, profondeur, filtre lieu),
puis lance. L'état du panneau est gardé en mémoire côté bot (un panneau actif).

Callbacks (préfixes courts pour tenir dans la limite Telegram de 64 octets) :
  sp:nav:<vue>     — naviguer vers une vue (home/marque/icp/req/params)
  sp:mk:<page>     — page du sélecteur de marque
  sp:mkp:<idx>     — choisir la marque #idx (de la page courante)
  sp:ic:<page>     — page du sélecteur d'ICP
  sp:icp:<idx>     — choisir l'ICP #idx
  sp:rq:<idx>      — toggle la requête #idx
  sp:rqall / sp:rqnone — tout (dé)sélectionner
  sp:n:<10|25|50>  — nb résultats
  sp:t:<auto|fast|deep> — profondeur
  sp:go            — lancer la recherche
  sp:cancel        — fermer le panneau
"""

PAGE = 6                          # éléments par page dans les sélecteurs
NB_CHOICES = [10, 25, 50]
TYPE_CHOICES = ["auto", "fast", "deep"]


class Panel:
    """État d'un panneau de recherche (people ou company)."""

    def __init__(self, kind, marques, icps):
        self.kind = kind                 # "person" | "company"
        self.marques = marques           # [nom, …]
        self.icps = icps                 # [{nom, produit, fields}, …]
        self.marque = ""                 # marque active
        self.icp = None                  # ICP choisi (dict) ou None (requête libre)
        self.requetes = []               # [(libellé, texte), …] générées par l'ICP
        self.selection = set()           # indices de requêtes cochées
        self.libre = ""                  # requête libre saisie au clavier
        self.nb = 10
        self.type = "auto"
        self.lieu = ""                   # filtre lieu post-recherche
        self.vue = "home"

    # ── filtres dérivés ───────────────────────────────────────────────────────

    def icps_marque(self):
        """ICP filtrés par la marque active (ou tous si aucune marque)."""
        if not self.marque:
            return self.icps
        return [i for i in self.icps if i.get("marque") == self.marque]

    def requetes_choisies(self):
        if self.libre:
            return [("Requête libre", self.libre)]
        return [self.requetes[i] for i in sorted(self.selection)
                if i < len(self.requetes)]

    def pret(self):
        return bool(self.requetes_choisies())


# ── Rendu du panneau (texte + clavier principal) ──────────────────────────────

def _esc(t):
    return (str(t or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def vue_home(p: Panel):
    """Écran principal : récap des choix + boutons de navigation + Lancer."""
    titre = "👤 Recherche de personnes" if p.kind == "person" else "🏢 Recherche d'entreprises"
    nb_req = len(p.requetes_choisies())
    lignes = [
        f"<b>{titre}</b>\n",
        f"🏷️ Marque : <b>{_esc(p.marque) or 'toutes'}</b>",
        f"🎯 ICP : <b>{_esc(p.icp['nom']) if p.icp else ('requête libre' if p.libre else '—')}</b>",
        f"📑 Requêtes : <b>{nb_req}</b> sélectionnée(s)"
        + (f" · libre : « {_esc(p.libre)[:30]} »" if p.libre else ""),
        f"⚙️ {p.nb} résultats · profondeur {p.type}"
        + (f" · 📍 {_esc(p.lieu)}" if p.lieu else ""),
    ]
    boutons = [
        [{"text": "🏷️ Marque", "callback_data": "sp:nav:marque"},
         {"text": "🎯 ICP", "callback_data": "sp:nav:icp"}],
        [{"text": "⚙️ Paramètres", "callback_data": "sp:nav:params"}],
    ]
    if p.requetes:
        boutons.insert(1, [{"text": f"📑 Requêtes ({nb_req}/{len(p.requetes)})",
                            "callback_data": "sp:nav:req"}])
    lance = [{"text": "🚀 Lancer", "callback_data": "sp:go"}] if p.pret() else \
        [{"text": "✍️ Tape une requête ou choisis un ICP", "callback_data": "sp:nav:home"}]
    boutons.append(lance + [{"text": "✖️", "callback_data": "sp:cancel"}])
    return "\n".join(lignes), boutons


def _pagination_row(prefixe, page, total):
    pages = max(1, (total + PAGE - 1) // PAGE)
    if pages <= 1:
        return None
    row = []
    if page > 0:
        row.append({"text": "◀️", "callback_data": f"{prefixe}:{page - 1}"})
    row.append({"text": f"{page + 1}/{pages}", "callback_data": "sp:noop"})
    if page < pages - 1:
        row.append({"text": "▶️", "callback_data": f"{prefixe}:{page + 1}"})
    return row


def vue_marque(p: Panel, page=0):
    """Sélecteur de marque paginé."""
    items = ["(toutes)"] + p.marques
    debut = page * PAGE
    lot = items[debut:debut + PAGE]
    boutons = []
    for i, nom in enumerate(lot):
        actif = "✅ " if (nom == p.marque or (nom == "(toutes)" and not p.marque)) else ""
        boutons.append([{"text": f"{actif}{nom}",
                         "callback_data": f"sp:mkp:{debut + i}"}])
    nav = _pagination_row("sp:mk", page, len(items))
    if nav:
        boutons.append(nav)
    boutons.append([{"text": "⬅️ Retour", "callback_data": "sp:nav:home"}])
    return "🏷️ <b>Choisis une marque</b>", boutons


def marque_at(p: Panel, idx):
    """Renvoie le nom de marque à l'indice global idx (0 = toutes)."""
    items = ["(toutes)"] + p.marques
    if 0 <= idx < len(items):
        return "" if items[idx] == "(toutes)" else items[idx]
    return p.marque


def vue_icp(p: Panel, page=0):
    """Sélecteur d'ICP paginé (filtré par la marque active)."""
    items = p.icps_marque()
    debut = page * PAGE
    lot = items[debut:debut + PAGE]
    boutons = []
    for i, ic in enumerate(lot):
        actif = "✅ " if (p.icp and ic["nom"] == p.icp["nom"]) else ""
        boutons.append([{"text": f"{actif}{ic['nom']}"[:60],
                         "callback_data": f"sp:icp:{debut + i}"}])
    nav = _pagination_row("sp:ic", page, len(items))
    if nav:
        boutons.append(nav)
    boutons.append([{"text": "⬅️ Retour", "callback_data": "sp:nav:home"}])
    txt = ("🎯 <b>Choisis un ICP</b>" if items
           else "🎯 Aucun ICP pour cette marque. /icp_add pour en créer.")
    return txt, boutons


def icp_at(p: Panel, idx):
    items = p.icps_marque()
    return items[idx] if 0 <= idx < len(items) else None


def vue_req(p: Panel):
    """Sélection des requêtes générées par l'ICP (toggles)."""
    if not p.requetes:
        return ("📑 Choisis d'abord un ICP pour générer des requêtes.",
                [[{"text": "⬅️ Retour", "callback_data": "sp:nav:home"}]])
    boutons = []
    for i, (lib, _txt) in enumerate(p.requetes):
        coche = "☑️" if i in p.selection else "⬜"
        boutons.append([{"text": f"{coche} {lib}"[:60],
                         "callback_data": f"sp:rq:{i}"}])
    boutons.append([{"text": "✅ Tout", "callback_data": "sp:rqall"},
                    {"text": "⬜ Aucun", "callback_data": "sp:rqnone"}])
    boutons.append([{"text": "⬅️ Retour", "callback_data": "sp:nav:home"}])
    return (f"📑 <b>Requêtes de l'ICP</b> ({len(p.selection)} cochée(s))\n"
            "<i>Coche celles à lancer.</i>"), boutons


def vue_params(p: Panel):
    """Réglages : nb résultats, profondeur, filtre lieu."""
    nb_row = [{"text": ("● " if n == p.nb else "") + str(n),
               "callback_data": f"sp:n:{n}"} for n in NB_CHOICES]
    type_row = [{"text": ("● " if t == p.type else "") + t,
                 "callback_data": f"sp:t:{t}"} for t in TYPE_CHOICES]
    boutons = [nb_row, type_row,
               [{"text": "📍 Filtre lieu : tape /lieu <ville> ou /lieu pour effacer",
                 "callback_data": "sp:noop"}],
               [{"text": "⬅️ Retour", "callback_data": "sp:nav:home"}]]
    lignes = ["⚙️ <b>Paramètres</b>",
              f"• Résultats : <b>{p.nb}</b> (au-delà de 10, coût Exa par résultat)",
              f"• Profondeur : <b>{p.type}</b> (fast=rapide, deep=meilleur ~2x coût)",
              f"• Filtre lieu : <b>{_esc(p.lieu) or 'aucun'}</b>"]
    return "\n".join(lignes), boutons


def filtrer_lieu(items, lieu):
    """Filtre une liste de résultats sur le champ lieu (post-recherche)."""
    if not lieu:
        return items
    bas = lieu.lower()
    return [it for it in items if bas in (getattr(it, "lieu", "") or "").lower()]
