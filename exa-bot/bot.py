"""EXO — plateforme de prospection Telegram (Exa + Airtable CRM + mailing).

Recherche people/company (Exa, clé par user) → CRM Airtable (6 tables) →
enrichissement email (Serper → Zeruh) → campagnes mailing (SMTP OVH, 3 modes :
batch / brouillon éditable / individuel) avec garde-fous (dry-run, quota,
confirmation) → export CSV. Construit sur botkit.
"""

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import datetime as _dt
import logging
import os
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from botkit.app import BotApp                      # noqa: E402
from botkit import pagination                      # noqa: E402

import crm as crm_mod                              # noqa: E402
import enrich                                      # noqa: E402
import exports                                     # noqa: E402
import icp as icp_mod                              # noqa: E402
import mailing                                     # noqa: E402
import menu as menu_mod                            # noqa: E402
import render                                      # noqa: E402
import search_panel as sp_mod                      # noqa: E402
import source                                      # noqa: E402
from keystore import KeyStore                      # noqa: E402
from stats import Stats                            # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger("exo")

EXA_KEYS_URL = "https://dashboard.exa.ai/api-keys"
SERPER_KEYS_URL = "https://serper.dev/api-key"


def _now_iso():
    return _dt.datetime.now().replace(microsecond=0).isoformat()


def _load_dotenv():
    env = Path(__file__).resolve().parent / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def aide(crm_ok=False, marque=""):
    """Aide dynamique : masque /setup si le CRM est déjà prêt, montre la marque active."""
    bandeau_marque = (f"🏷️ Marque active : <b>{render._esc(marque)}</b>\n\n"
                      if marque else "")
    crm_ligne = ("/export &lt;table&gt; — CSV" if crm_ok
                 else "/setup — crée les tables Airtable · /export &lt;table&gt; — CSV")
    return (
        "🚀 <b>EXO — Prospection multi-marques</b>\n\n"
        + bandeau_marque +
        "<b>🔑 Clés (les tiennes)</b>\n"
        "/setkey &lt;clé exa&gt; · /setserper &lt;clé&gt; · /mykeys · /cout\n\n"
        "<b>🏷️ Marques</b>\n"
        "/marques — liste · /marque &lt;nom&gt; — activer · "
        "/marque_add &lt;nom&gt; | site | produits\n"
        "/icp_import &lt;url&gt; — génère des ICP depuis le site d'une marque\n\n"
        "<b>🔎 Recherche → CRM</b>\n"
        "/people &lt;requête&gt; · /company &lt;requête&gt;\n"
        "(sous chaque résultat : 🔗 lien · 💾 Airtable · ✉️ enrichir email)\n\n"
        "<b>🎯 ICP &amp; requêtes</b>\n"
        "/icps — liste (filtrée par marque) · /icp_add &lt;nom&gt; | postes | secteurs | lieux\n"
        "/icp_run &lt;nom&gt; — lance les requêtes générées · /run &lt;libellé&gt; — rejoue\n\n"
        "<b>📣 Campagnes</b>\n"
        "/campagnes · /envoyer &lt;campagne&gt; (batch · individuel)\n"
        "/brouillon &lt;campagne&gt; — éditer un email · /relancer &lt;campagne&gt; (IMAP)\n\n"
        "<b>📇 CRM</b>\n"
        f"{crm_ligne}\n\n"
        "<i>Mailing : dry-run par défaut, confirmation + quota/jour avant envoi réel.</i>")


class State:
    def __init__(self):
        self.items = []          # dernier lot (Contact|Entreprise)
        self.titre = ""
        self.cout = 0.0
        self.kind = "person"     # 'person' | 'company'
        self.marque = ""         # marque active (filtre/tag des données)
        self.panel = None        # panneau de recherche en cours (sp_mod.Panel)


def main():
    _load_dotenv()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        log.error("TELEGRAM_BOT_TOKEN et TELEGRAM_CHAT_ID requis.")
        return 1

    app = BotApp(token, chat_id, nom="exo-bot")
    keys = KeyStore(os.environ.get("KEYS_PATH", "keys.json"))
    stats = Stats(os.environ.get("STATS_PATH", "stats.json"))
    state = State()
    uid = chat_id

    def crm():
        return crm_mod.CRM()        # nouvelle connexion par usage (simple, robuste)

    def _charger_marques_icps():
        """Renvoie ([noms_marques], [{nom, produit, marque, fields}]) depuis Airtable."""
        if not has_airtable():
            return [], []
        try:
            c = crm()
            marques = [r["fields"].get("Nom") for r in c.lister("Marques")
                       if r["fields"].get("Nom")]
            icps = [{"nom": r["fields"].get("Nom", ""),
                     "produit": r["fields"].get("Produit", ""),
                     "marque": r["fields"].get("Marque", ""),
                     "fields": r["fields"]}
                    for r in c.lister("ICP", max_records=200)
                    if r["fields"].get("Nom")]
            c.close()
            return marques, icps
        except Exception:
            return [], []

    def _feedback_badges(ctx, nouveaux):
        """Annonce les badges débloqués (gamification)."""
        for b in nouveaux:
            ctx.reply(f"🏅 <b>Badge débloqué !</b> {b}")

    def has_airtable():
        return bool(os.environ.get("AIRTABLE_TOKEN") and os.environ.get("AIRTABLE_BASE_ID"))

    def crm_pret():
        """True si Airtable est configuré ET les 6 tables CRM existent."""
        if not has_airtable():
            return False
        try:
            c = crm()
            tables = set(c.lister_tables())
            c.close()
            return set(crm_mod.TABLES).issubset(tables)
        except Exception:
            return False

    def _aide(ctx):
        ctx.reply(aide(crm_ok=crm_pret(), marque=state.marque))

    # ── clés ──────────────────────────────────────────────────────────────────

    def _exiger_exa(ctx):
        if keys.a_cle(uid, "exa"):
            return keys.get(uid, "exa")
        ctx.reply("🔑 <b>Clé Exa requise</b> — /setkey &lt;clé&gt;",
                  buttons=[[{"text": "🔑 Créer une clé Exa", "url": EXA_KEYS_URL}]])
        return None

    @app.au_demarrage
    def accueil(ctx):
        # Menu natif Telegram (liste de commandes cliquable).
        app.tg.set_my_commands([
            ("menu", "🚀 Menu principal"),
            ("people", "👤 Chercher des personnes"),
            ("company", "🏢 Chercher des entreprises"),
            ("icps", "🎯 Lancer un ICP"),
            ("marques", "🏷️ Marques"),
            ("campagnes", "📣 Campagnes"),
            ("stats", "📊 Ma progression"),
            ("config", "⚙️ Configuration (API + email)"),
            ("help", "❓ Aide"),
        ])
        try:
            txt, btns = menu_mod.hub(state.marque, crm_pret())
            ctx.reply("🟢 <b>EXO en ligne.</b>\n\n" + txt, buttons=btns)
        except Exception:
            pass

    @app.command("/start", "/help")
    def start(ctx):
        _aide(ctx)

    @app.command("/setkey")
    def setkey(ctx):
        cle = ctx.reste.strip()
        if not cle:
            ctx.reply("Usage : /setkey &lt;clé exa&gt;",
                      buttons=[[{"text": "🔑 Créer une clé Exa", "url": EXA_KEYS_URL}]])
            return
        ctx.reply("⏳ Vérification…")
        if not source.valider_cle(cle):
            ctx.reply("❌ Clé Exa invalide.")
            return
        keys.set(uid, cle, "exa")
        ctx.reply(f"✅ Clé Exa enregistrée (<code>{keys.masquee(uid, 'exa')}</code>).")

    @app.command("/setserper")
    def setserper(ctx):
        cle = ctx.reste.strip()
        if not cle:
            ctx.reply("Usage : /setserper &lt;clé serper&gt;",
                      buttons=[[{"text": "🔑 Créer une clé Serper", "url": SERPER_KEYS_URL}]])
            return
        ctx.reply("⏳ Vérification…")
        if not enrich.valider_cle_serper(cle):
            ctx.reply("❌ Clé Serper invalide.")
            return
        keys.set(uid, cle, "serper")
        ctx.reply(f"✅ Clé Serper enregistrée (<code>{keys.masquee(uid, 'serper')}</code>).")

    @app.command("/mykeys")
    def mykeys(ctx):
        ex = keys.masquee(uid, "exa") if keys.a_cle(uid, "exa") else "—"
        sp = keys.masquee(uid, "serper") if keys.a_cle(uid, "serper") else "—"
        ctx.reply(f"🔑 Exa : <code>{ex}</code>\n🔑 Serper : <code>{sp}</code>\n"
                  f"💰 {keys.nb_appels(uid)} requêtes Exa · ${keys.cout_total(uid):.4f}")

    @app.command("/cout")
    def cout(ctx):
        ctx.reply(f"💰 <b>Coût Exa</b> : {keys.nb_appels(uid)} requêtes · "
                  f"<b>${keys.cout_total(uid):.4f}</b>")

    # ── gamification ──────────────────────────────────────────────────────────

    @app.command("/stats")
    def stats_cmd(ctx):
        ctx.reply(stats.resume(uid),
                  buttons=[[{"text": "🔎 Chercher", "callback_data": "menu:search"},
                            {"text": "🚀 Menu", "callback_data": "menu:home"}]])

    @app.command("/config")
    def config_cmd(ctx):
        _rep(ctx, menu_mod.section_config(_statut_config()))

    @app.command("/objectif")
    def objectif(ctx):
        arg = ctx.reste.strip()
        if not arg.isdigit():
            fait, obj = stats.objectif_semaine(uid)
            ctx.reply(f"🎯 Objectif : <b>{obj}</b> leads/semaine ({fait} atteints).\n"
                      "Change-le : /objectif &lt;nombre&gt;")
            return
        stats.set_objectif(uid, int(arg))
        ctx.reply(f"🎯 Objectif fixé à <b>{arg}</b> leads/semaine. 💪")

    # ── setup CRM ─────────────────────────────────────────────────────────────

    @app.command("/setup")
    def setup(ctx):
        if not has_airtable():
            ctx.reply("⚠️ AIRTABLE_TOKEN / AIRTABLE_BASE_ID manquants (.env).")
            return
        ctx.reply("🏗️ Création des tables CRM…")
        try:
            c = crm()
            rapport = c.setup()
            c.close()
        except crm_mod.CRMError as e:
            ctx.reply(f"⚠️ {e}")
            return
        lignes = [f"• {t} : {etat}" for t, etat in rapport.items()]
        ctx.reply("✅ <b>CRM prêt</b>\n" + "\n".join(lignes))

    # ── recherche ─────────────────────────────────────────────────────────────

    def _afficher(ctx, items, titre, cout, page=1):
        state.items, state.titre, state.cout = items, titre, cout
        if not items:
            ctx.reply(f"Aucun résultat. 💰 ${cout:.4f}")
            return
        total = len(items)
        pages = pagination.nb_pages(total)
        page = pagination.borner_page(page, total)
        ctx.reply(render.entete_recherche(titre, total, page, pages, cout))
        paire = pagination.page_items(items, page)
        for index, item in paire:
            texte, boutons = render.render(index, item)
            # bouton enrichir email pour les contacts (personnes)
            if isinstance(item, source.Contact):
                boutons[0].append({"text": "✉️ Email", "callback_data": f"enr:{index}"})
            nav = pagination.barre(page, total) if index == paire[-1][0] else None
            if nav:
                boutons = list(boutons) + nav
            ctx.reply(texte, buttons=boutons)

    def _ouvrir_panel(ctx, kind):
        """Ouvre le panneau de recherche à boutons (people ou company)."""
        if not _exiger_exa(ctx):
            return
        marques, icps = _charger_marques_icps()
        p = sp_mod.Panel(kind, marques, icps)
        p.marque = state.marque        # pré-remplit avec la marque active
        state.panel = p
        txt, btns = sp_mod.vue_home(p)
        ctx.reply(txt, buttons=btns)

    def _executer_recherche(ctx, kind, requetes, p=None):
        """Exécute 1..N requêtes Exa, fusionne (dédup), filtre lieu, affiche + gamifie."""
        cle = _exiger_exa(ctx)
        if not cle:
            return
        nb = p.nb if p else 10
        typ = p.type if p else "auto"
        lieu = p.lieu if p else ""
        ctx.reply(f"🔎 {len(requetes)} requête(s) · {nb} résultats · {typ}…")
        vus, fusion, cout_total = set(), [], 0.0
        for lib, texte in requetes:
            try:
                if kind == "person":
                    items, c = source.rechercher_personnes(cle, texte, n=nb)
                else:
                    items, c = source.rechercher_entreprises(cle, texte, n=nb)
            except source.ExaError as e:
                ctx.reply(f"⚠️ {render._esc(lib)} : {e}")
                continue
            keys.ajouter_cout(uid, c)
            cout_total += c
            if hasattr(source, "_client"):
                pass
            for it in items:
                clef = (getattr(it, "linkedin", "") or getattr(it, "site", "")
                        or getattr(it, "nom", "")).lower()
                if clef and clef in vus:
                    continue
                vus.add(clef)
                fusion.append(it)
        if lieu:
            fusion = sp_mod.filtrer_lieu(fusion, lieu)
        state.kind = kind
        titre = (requetes[0][0] if len(requetes) == 1
                 else f"{len(requetes)} requêtes fusionnées")
        # Gamification : compteur de résultats trouvés.
        compteur = "contacts" if kind == "person" else "entreprises"
        nouveaux = stats.ajouter(uid, compteur, len(fusion)) if fusion else []
        _afficher(ctx, fusion, titre, cout_total)
        if fusion:
            ctx.reply(f"🎉 <b>{len(fusion)} résultat(s)</b> trouvé(s) · "
                      f"💰 ${cout_total:.4f}",
                      buttons=menu_mod.suite("recherche"))
        _feedback_badges(ctx, nouveaux)

    @app.command("/people")
    def people(ctx):
        q = ctx.reste.strip()
        if not q:
            _ouvrir_panel(ctx, "person")     # pas de texte -> panneau à boutons
            return
        _executer_recherche(ctx, "person", [(f"people · {q}", q)])

    @app.command("/company")
    def company(ctx):
        q = ctx.reste.strip()
        if not q:
            _ouvrir_panel(ctx, "company")
            return
        _executer_recherche(ctx, "company", [(f"company · {q}", q)])

    @app.callback("pg")
    def page(ctx):
        if ctx.data == "pg:noop":
            return
        n = pagination.parse(ctx.data, "pg")
        if n is not None:
            _afficher(ctx, state.items, state.titre, state.cout, page=n)

    # ── Panneau de recherche (sp:*) ───────────────────────────────────────────

    @app.callback("sp")
    def panel_cb(ctx):
        p = state.panel
        data = ctx.data
        if data == "sp:noop":
            return
        if data == "sp:cancel":
            state.panel = None
            ctx.reply("✖️ Panneau fermé. /menu pour le hub.")
            return
        if p is None:
            ctx.reply("Panneau expiré. Relance /people ou /company.")
            return
        parts = data.split(":")
        action = parts[1] if len(parts) > 1 else ""
        arg = parts[2] if len(parts) > 2 else ""

        def _rendre(vue_fn, *a):
            txt, btns = vue_fn(*a)
            ctx.reply(txt, buttons=btns)

        if action == "nav":
            p.vue = arg
            if arg == "marque":
                _rendre(sp_mod.vue_marque, p, 0)
            elif arg == "icp":
                _rendre(sp_mod.vue_icp, p, 0)
            elif arg == "req":
                _rendre(sp_mod.vue_req, p)
            elif arg == "params":
                _rendre(sp_mod.vue_params, p)
            else:
                _rendre(sp_mod.vue_home, p)
        elif action == "mk":                       # page marque
            _rendre(sp_mod.vue_marque, p, int(arg or 0))
        elif action == "mkp":                      # choisir marque
            p.marque = sp_mod.marque_at(p, int(arg))
            state.marque = p.marque
            p.icp = None                           # reset ICP (filtré par marque)
            p.requetes, p.selection = [], set()
            _rendre(sp_mod.vue_home, p)
        elif action == "ic":                       # page ICP
            _rendre(sp_mod.vue_icp, p, int(arg or 0))
        elif action == "icp":                      # choisir ICP
            ic = sp_mod.icp_at(p, int(arg))
            if ic:
                p.icp = ic
                p.libre = ""
                reqs = (icp_mod.requetes_people(ic["fields"]) if p.kind == "person"
                        else icp_mod.requetes_company(ic["fields"]))
                p.requetes = reqs
                p.selection = set(range(len(reqs)))   # toutes cochées par défaut
            _rendre(sp_mod.vue_req, p)
        elif action == "rq":                       # toggle requête
            i = int(arg)
            if i in p.selection:
                p.selection.discard(i)
            else:
                p.selection.add(i)
            _rendre(sp_mod.vue_req, p)
        elif action == "rqall":
            p.selection = set(range(len(p.requetes)))
            _rendre(sp_mod.vue_req, p)
        elif action == "rqnone":
            p.selection = set()
            _rendre(sp_mod.vue_req, p)
        elif action == "n":                        # nb résultats
            p.nb = int(arg)
            _rendre(sp_mod.vue_params, p)
        elif action == "t":                        # profondeur
            p.type = arg
            _rendre(sp_mod.vue_params, p)
        elif action == "go":                       # lancer
            reqs = p.requetes_choisies()
            if not reqs:
                ctx.reply("Choisis au moins une requête (ICP) ou tape une "
                          "requête libre.")
                return
            kind = p.kind
            state.panel = None
            _executer_recherche(ctx, kind, reqs, p)

    # ── Menu hub (menu:*) ─────────────────────────────────────────────────────

    @app.command("/menu")
    def menu_cmd(ctx):
        mini = ""
        try:
            nom, score, _ = stats.niveau(uid)
            fait, obj = stats.objectif_semaine(uid)
            mini = f"🏆 {nom} · 🎯 {fait}/{obj} cette semaine"
        except Exception:
            pass
        txt, btns = menu_mod.hub(state.marque, crm_pret(), mini)
        ctx.reply(txt, buttons=btns)

    @app.callback("menu")
    def menu_cb(ctx):
        sec = ctx.data.split(":", 1)[1] if ":" in ctx.data else "home"
        if sec == "home":
            txt, btns = menu_mod.hub(state.marque, crm_pret())
            ctx.reply(txt, buttons=btns)
        elif sec == "search":
            _rep(ctx, menu_mod.section_search())
        elif sec == "people":
            _ouvrir_panel(ctx, "person")
        elif sec == "company":
            _ouvrir_panel(ctx, "company")
        elif sec == "crm":
            _rep(ctx, menu_mod.section_crm())
        elif sec == "camp":
            _rep(ctx, menu_mod.section_camp())
        elif sec == "marque":
            _rep(ctx, menu_mod.section_marque(state.marque))
        elif sec == "stats":
            ctx.reply(stats.resume(uid),
                      buttons=[[{"text": "⬅️ Menu", "callback_data": "menu:home"}]])
        elif sec == "guide":
            _rep(ctx, menu_mod.guide())
        elif sec == "config":
            _rep(ctx, menu_mod.section_config(_statut_config()))
        elif sec.startswith("cfg:"):
            _action_config(ctx, sec.split(":", 1)[1])
        elif sec == "icps":
            _menu_lister_icps(ctx)
        elif sec == "marquelist":
            _menu_lister_marques(ctx)
        elif sec == "camplist":
            _lister_campagnes(ctx)
        elif sec.startswith("exp:"):
            _exporter(ctx, sec.split(":", 1)[1])
        elif sec.startswith("runicp:"):
            _lancer_icp_par_id(ctx, sec.split(":", 1)[1])
        elif sec.startswith("pickmk:"):
            nom = sec.split(":", 1)[1]
            state.marque = nom
            ctx.reply(f"🏷️ Marque active : <b>{render._esc(nom)}</b>.",
                      buttons=menu_mod.suite("icp"))

    def _rep(ctx, paire):
        """Envoie une (texte, boutons) produite par menu_mod."""
        ctx.reply(paire[0], buttons=paire[1])

    # ── helpers du menu (listes cliquables) ───────────────────────────────────

    def _menu_lister_marques(ctx):
        marques, _ = _charger_marques_icps()
        if not marques:
            ctx.reply("Aucune marque. /marque_add &lt;nom&gt; | site | produits")
            return
        btns = [[{"text": ("✅ " if m == state.marque else "🏷️ ") + m,
                  "callback_data": f"menu:pickmk:{m}"}] for m in marques[:12]]
        btns.append([{"text": "⬅️ Menu", "callback_data": "menu:home"}])
        ctx.reply("🏷️ <b>Choisis une marque active</b>", buttons=btns)

    def _menu_lister_icps(ctx):
        _, icps = _charger_marques_icps()
        if state.marque:
            icps = [i for i in icps if i.get("marque") == state.marque]
        if not icps:
            ctx.reply("Aucun ICP. /icp_add pour en créer un.", buttons=None)
            return
        btns = [[{"text": f"🎯 {i['nom']}"[:60],
                  "callback_data": f"menu:runicp:{i['fields'].get('id', i['nom'])}"}]
                for i in icps[:12]]
        # On route par NOM (pas d'id stocké dans fields) : utilise le nom.
        btns = [[{"text": f"🎯 {i['nom']}"[:60],
                  "callback_data": "menu:runicp:" + i['nom'][:40]}] for i in icps[:12]]
        btns.append([{"text": "⬅️ Menu", "callback_data": "menu:home"}])
        ctx.reply(f"🎯 <b>ICP{' · ' + render._esc(state.marque) if state.marque else ''}</b> "
                  "— clique pour lancer :", buttons=btns)

    def _lancer_icp_par_id(ctx, nom_icp):
        """Lance un ICP depuis le menu (par nom)."""
        cle = _exiger_exa(ctx)
        if not cle:
            return
        c = crm()
        icp_rec = _icp_par_nom(c, nom_icp)
        if not icp_rec:
            c.close()
            ctx.reply(f"ICP introuvable.")
            return
        kind = "person"
        reqs = icp_mod.requetes_people(icp_rec["fields"])
        c.close()
        if not reqs:
            ctx.reply("Cet ICP ne génère aucune requête.")
            return
        _executer_recherche(ctx, kind, reqs)

    def _exporter(ctx, table):
        if not has_airtable():
            ctx.reply("⚠️ Airtable non configuré.")
            return
        ctx.reply(f"📤 Export de « {render._esc(table)} »…")
        try:
            c = crm()
            chemin, n = exports.exporter_csv(c, table)
            c.close()
        except crm_mod.CRMError as e:
            ctx.reply(f"⚠️ {e}")
            return
        if n == 0:
            ctx.reply("Table vide — rien à exporter.")
            return
        ctx.document(chemin, caption=f"📤 {n} ligne(s) — {table}")

    def _lister_campagnes(ctx):
        if not has_airtable():
            ctx.reply("⚠️ Airtable non configuré.")
            return
        c = crm()
        recs = c.lister("Campagnes", max_records=50)
        c.close()
        if not recs:
            ctx.reply("Aucune campagne. Crée-en une dans Airtable (table "
                      "Campagnes) puis /envoyer &lt;nom&gt;.")
            return
        lignes = ["📣 <b>Campagnes</b>\n"]
        for r in recs:
            f = r["fields"]
            lignes.append(f"• <b>{render._esc(f.get('Nom', '—'))}</b> "
                          f"— {f.get('Approche', '')} · {f.get('Statut', '')}")
        ctx.reply("\n".join(lignes),
                  buttons=[[{"text": "⬅️ Menu", "callback_data": "menu:home"}]])

    # ── section Configuration (API + email) ───────────────────────────────────

    def _statut_config():
        """Calcule l'état des clés et services pour l'écran Config."""
        return {
            "exa": keys.masquee(uid, "exa") if keys.a_cle(uid, "exa") else "",
            "serper": keys.masquee(uid, "serper") if keys.a_cle(uid, "serper") else "",
            "zeruh": bool(os.environ.get("ZERUH_API_KEY")),
            "airtable": crm_pret(),
            "smtp": mailing.smtp_pret(),
            "imap": mailing.imap_pret(),
            "dry_run": mailing.dry_run(),
            "smtp_from": mailing.config_smtp().get("from", ""),
        }

    def _action_config(ctx, action):
        if action == "exa":
            ctx.reply("🔑 Envoie ta clé Exa : <code>/setkey TA_CLE</code>",
                      buttons=[[{"text": "Créer une clé Exa", "url": EXA_KEYS_URL}]])
        elif action == "serper":
            ctx.reply("🔑 Envoie ta clé Serper : <code>/setserper TA_CLE</code>",
                      buttons=[[{"text": "Créer une clé Serper", "url": SERPER_KEYS_URL}]])
        elif action == "clearkeys":
            keys.supprimer(uid, "exa")
            keys.supprimer(uid, "serper")
            ctx.reply("🗑️ Tes clés Exa et Serper ont été effacées.")
        elif action == "testmail":
            if not mailing.smtp_pret():
                ctx.reply("❌ SMTP non configuré (SMTP_HOST/USER/PASS dans .env).")
                return
            dest = mailing.config_smtp().get("from", "").split("<")[-1].strip(">") \
                or mailing.config_smtp().get("user", "")
            ctx.reply(f"✉️ Envoi d'un email de test à {render._esc(dest)}…")
            try:
                mailing.envoyer(dest, "[EXO] Test de configuration",
                                "Si tu lis ceci, ta config SMTP fonctionne. 🎉")
                ctx.reply("✅ Email de test envoyé ! Vérifie ta boîte.")
            except mailing.MailError as e:
                ctx.reply(f"❌ {e}")
        elif action == "testimap":
            if not mailing.imap_pret():
                ctx.reply("❌ IMAP non configuré.")
                return
            ctx.reply("📥 Connexion IMAP…")
            try:
                addrs = mailing.expediteurs_recents(jours=7)
                ctx.reply(f"✅ IMAP OK — {len(addrs)} expéditeur(s) sur 7 jours.")
            except mailing.MailError as e:
                ctx.reply(f"❌ {e}")

    # ── sauvegarde Airtable ───────────────────────────────────────────────────

    @app.callback("sav")
    def save(ctx):
        m = re.fullmatch(r"sav:(\d+)", ctx.data or "")
        if not m:
            return
        idx = int(m.group(1))
        if idx < 1 or idx > len(state.items):
            ctx.reply("⚠️ Résultat expiré — relance la recherche.")
            return
        if not has_airtable():
            ctx.reply("⚠️ Airtable non configuré.")
            return
        item = state.items[idx - 1]
        try:
            c = crm()
            if isinstance(item, source.Contact):
                aj, ig = c.upsert_contacts([item], cout=state.cout, marque=state.marque)
            else:
                aj, ig = c.upsert_entreprises([item], cout=state.cout, marque=state.marque)
            c.close()
        except crm_mod.CRMError as e:
            ctx.reply(f"⚠️ {e}")
            return
        nom = getattr(item, "nom", "")
        if aj:
            ctx.reply(f"💾 « {render._esc(nom)} » enregistré dans Airtable.")
        else:
            ctx.reply(f"↩️ « {render._esc(nom)} » déjà présent (ignoré).")

    # ── enrichissement email (Serper → Zeruh → Airtable) ──────────────────────

    @app.callback("enr")
    def enrichir(ctx):
        m = re.fullmatch(r"enr:(\d+)", ctx.data or "")
        if not m:
            return
        idx = int(m.group(1))
        if idx < 1 or idx > len(state.items):
            ctx.reply("⚠️ Résultat expiré.")
            return
        item = state.items[idx - 1]
        if not isinstance(item, source.Contact):
            ctx.reply("L'enrichissement email ne vaut que pour les personnes.")
            return
        serper = keys.get(uid, "serper")
        if not serper:
            ctx.reply("🔑 Clé Serper requise — /setserper &lt;clé&gt;",
                      buttons=[[{"text": "🔑 Créer une clé Serper", "url": SERPER_KEYS_URL}]])
            return
        ctx.reply(f"✉️ Recherche d'email pour <b>{render._esc(item.nom)}</b>…")
        try:
            res = enrich.enrichir_contact(serper, item.prenom, item.nom,
                                          item.entreprise)
        except enrich.EnrichError as e:
            ctx.reply(f"⚠️ {e}")
            return
        m_ = res["meilleur"]
        if not m_:
            cands = ", ".join(res["candidats"][:4]) or "aucun"
            ctx.reply(f"🔍 Aucun email vérifié exploitable.\n"
                      f"Candidats bruts : {render._esc(cands)}")
            return
        item.email = m_["email"]
        msg = (f"✅ <b>{render._esc(m_['email'])}</b>\n"
               f"statut : {m_['status']} · score {m_['score']}/100 · "
               f"smtp {'✓' if m_['smtp'] else '✗'}")
        # MAJ Airtable si le contact y est.
        if has_airtable():
            try:
                c = crm()
                trouve = c.trouver_contact(item.nom)
                if trouve:
                    c.maj_email_contact(trouve[0], m_["email"], m_["status"],
                                        m_["score"], _now_iso())
                    msg += "\n💾 Email mis à jour dans Airtable."
                else:
                    msg += "\n<i>(contact pas encore dans Airtable — 💾 d'abord)</i>"
                c.close()
            except crm_mod.CRMError:
                pass
        # Gamification : compteur d'emails vérifiés + fil d'Ariane.
        nouveaux = stats.ajouter(uid, "emails", 1)
        ctx.reply(msg, buttons=menu_mod.suite("enrich"))
        _feedback_badges(ctx, nouveaux)

    # ── export CSV ────────────────────────────────────────────────────────────

    @app.command("/export")
    def export(ctx):
        table = ctx.reste.strip() or "Contacts"
        if not has_airtable():
            ctx.reply("⚠️ Airtable non configuré.")
            return
        ctx.reply(f"📤 Export de « {render._esc(table)} »…")
        try:
            c = crm()
            chemin, n = exports.exporter_csv(c, table)
            c.close()
        except crm_mod.CRMError as e:
            ctx.reply(f"⚠️ {e}")
            return
        if n == 0:
            ctx.reply("Table vide — rien à exporter.")
            return
        ctx.document(chemin, caption=f"📤 {n} ligne(s) — {table}")

    # ── campagnes & mailing ───────────────────────────────────────────────────

    @app.command("/campagnes")
    def campagnes(ctx):
        if not has_airtable():
            ctx.reply("⚠️ Airtable non configuré.")
            return
        c = crm()
        recs = c.lister("Campagnes", max_records=50)
        c.close()
        if not recs:
            ctx.reply("Aucune campagne. Crée-en une dans Airtable (table "
                      "Campagnes) puis /envoyer &lt;nom&gt;.")
            return
        lignes = ["📣 <b>Campagnes</b>\n"]
        for r in recs:
            f = r["fields"]
            lignes.append(f"• <b>{render._esc(f.get('Nom', '—'))}</b> "
                          f"— {f.get('Approche', '')} · {f.get('Statut', '')}")
        ctx.reply("\n".join(lignes))

    def _campagne_par_nom(c, nom):
        for r in c.lister("Campagnes", max_records=100):
            if (r["fields"].get("Nom") or "").lower() == (nom or "").lower():
                return r
        return None

    def _cibles_campagne(c, camp_rec):
        """Contacts liés à la campagne (champ Cibles) avec un email."""
        ids = camp_rec["fields"].get("Cibles") or []
        if not ids:
            return []
        contacts = []
        for rec in c.lister("Contacts", max_records=1000):
            if rec["id"] in ids and rec["fields"].get("Email"):
                contacts.append(rec)
        return contacts

    @app.command("/envoyer")
    def envoyer(ctx):
        nom = ctx.reste.strip()
        if not nom:
            ctx.reply("Usage : /envoyer &lt;nom de campagne&gt;")
            return
        if not has_airtable():
            ctx.reply("⚠️ Airtable non configuré.")
            return
        c = crm()
        camp = _campagne_par_nom(c, nom)
        if not camp:
            c.close()
            ctx.reply(f"Campagne « {render._esc(nom)} » introuvable. /campagnes")
            return
        cibles = _cibles_campagne(c, camp)
        c.close()
        if not cibles:
            ctx.reply("Aucune cible avec email. Lie des Contacts (champ Cibles) "
                      "et enrichis leurs emails d'abord.")
            return
        # Mémorise pour les actions (batch / individuel).
        state.titre = nom
        expediteur = mailing.config_smtp()["from"]
        # Aperçu du 1er brouillon + choix du mode.
        objet, corps, html = mailing.composer(cibles[0]["fields"],
                                               camp["fields"], expediteur)
        apercu = (f"📣 <b>{render._esc(nom)}</b> — {len(cibles)} cible(s) avec email\n"
                  f"Mode : <b>{'DRY-RUN' if mailing.dry_run() else 'ENVOI RÉEL'}</b> "
                  f"· quota {mailing.quota_jour()}/j\n\n"
                  f"<b>Aperçu</b> (à {render._esc(cibles[0]['fields'].get('Email',''))}) :\n"
                  f"<b>Objet</b> : {render._esc(objet)}\n"
                  f"<pre>{render._esc(corps[:500])}</pre>")
        boutons = [
            [{"text": "📨 Batch (tous)", "callback_data": f"snd:batch"}],
            [{"text": "👤 Un par un", "callback_data": f"snd:one"}],
            [{"text": "✖️ Annuler", "callback_data": "snd:cancel"}],
        ]
        # Stocke le contexte d'envoi.
        state.kind = "campagne"
        state.items = cibles
        state.cout = 0.0
        state._camp = camp                     # type: ignore[attr-defined]
        ctx.reply(apercu, buttons=boutons)

    def _envoyer_un(cible_fields, camp_fields):
        """Compose + envoie (ou dry-run) un email. Renvoie (ok, objet, erreur)."""
        expediteur = mailing.config_smtp()["from"]
        objet, corps, html = mailing.composer(cible_fields, camp_fields, expediteur)
        dest = cible_fields.get("Email", "")
        if not dest:
            return False, objet, "pas d'email"
        if mailing.dry_run():
            return True, objet, "dry-run (non envoyé)"
        try:
            mailing.envoyer(dest, objet, corps, html)
            return True, objet, ""
        except mailing.MailError as e:
            return False, objet, str(e)

    @app.callback("snd")
    def send_cb(ctx):
        action = ctx.data.split(":", 1)[1] if ":" in ctx.data else ""
        if action == "cancel":
            ctx.reply("✖️ Envoi annulé.")
            return
        camp = getattr(state, "_camp", None)
        if not camp or not state.items:
            ctx.reply("⚠️ Contexte d'envoi expiré — relance /envoyer.")
            return
        cibles = state.items
        if action == "batch":
            n_ok, n_ko, quota = 0, 0, mailing.quota_jour()
            for rec in cibles[:quota]:
                ok, objet, err = _envoyer_un(rec["fields"], camp["fields"])
                n_ok += 1 if ok else 0
                n_ko += 0 if ok else 1
            mode = "DRY-RUN (rien envoyé)" if mailing.dry_run() else "envoyés"
            ctx.reply(f"📨 Batch {mode} : {n_ok} ok · {n_ko} échec "
                      f"(plafonné à {quota}/j).")
        elif action == "one":
            # Envoie le 1er, propose le suivant.
            rec = cibles[0]
            ok, objet, err = _envoyer_un(rec["fields"], camp["fields"])
            reste = cibles[1:]
            state.items = reste
            statut = "✅" if ok else "❌"
            suite = (f"\nReste {len(reste)} cible(s).") if reste else "\nTerminé."
            boutons = [[{"text": "👤 Suivant", "callback_data": "snd:one"}]] if reste else None
            ctx.reply(f"{statut} {render._esc(rec['fields'].get('Email',''))} — "
                      f"{render._esc(err or 'ok')}{suite}", buttons=boutons)

    # ── ICP & requêtes prédéfinies ────────────────────────────────────────────

    @app.command("/icp_add")
    def icp_add(ctx):
        # Format : /icp_add nom | postes | secteurs | lieux [| taille]
        parts = [p.strip() for p in ctx.reste.split("|")]
        if len(parts) < 2 or not parts[0]:
            ctx.reply("Usage : /icp_add &lt;nom&gt; | postes | secteurs | lieux "
                      "[| taille]\nEx. /icp_add SaaS-FR | CTO, VP Eng | SaaS, "
                      "Fintech | Paris, Lyon | 11-50")
            return
        if not has_airtable():
            ctx.reply("⚠️ Airtable non configuré (/setup).")
            return
        fields = {"Nom": parts[0], "Actif": True}
        if state.marque:
            fields["Marque"] = state.marque
        for i, col in enumerate(["Postes cibles", "Secteurs", "Lieux",
                                 "Taille entreprise"], start=1):
            if i < len(parts) and parts[i]:
                fields[col] = parts[i]
        try:
            c = crm()
            c.creer("ICP", fields)
            c.close()
        except crm_mod.CRMError as e:
            ctx.reply(f"⚠️ {e}")
            return
        ctx.reply(f"🎯 ICP « {render._esc(parts[0])} » créé. "
                  f"/icp_run {render._esc(parts[0])} pour lancer ses requêtes.")

    @app.command("/icps")
    def icps(ctx):
        if not has_airtable():
            ctx.reply("⚠️ Airtable non configuré.")
            return
        c = crm()
        recs = c.lister("ICP", max_records=100)
        c.close()
        # Filtre par marque active si définie.
        if state.marque:
            recs = [r for r in recs
                    if (r["fields"].get("Marque") or "") == state.marque]
        if not recs:
            ctx.reply(f"Aucun ICP{' pour ' + state.marque if state.marque else ''}. "
                      "/icp_add pour en créer un.")
            return
        titre = f"🎯 <b>ICP{' · ' + render._esc(state.marque) if state.marque else ''}</b>\n"
        lignes = [titre]
        for r in recs:
            f = r["fields"]
            lignes.append(f"• <b>{render._esc(f.get('Nom', '—'))}</b> — "
                          f"{render._esc(f.get('Postes cibles', ''))[:40]}")
        ctx.reply("\n".join(lignes))

    def _icp_par_nom(c, nom):
        cible = (nom or "").strip().lower()
        recs = c.lister("ICP", max_records=100)
        # 1) match exact.
        for r in recs:
            if (r["fields"].get("Nom") or "").strip().lower() == cible:
                return r
        # 2) tolérant : le texte tapé COMMENCE par le nom de l'ICP (l'utilisateur
        #    a collé le nom + une partie de la description) ou inversement.
        for r in recs:
            n = (r["fields"].get("Nom") or "").strip().lower()
            if n and (cible.startswith(n) or n.startswith(cible)):
                return r
        return None

    @app.command("/icp_run")
    def icp_run(ctx):
        nom = ctx.reste.strip()
        cle = _exiger_exa(ctx)
        if not cle:
            return
        if not has_airtable():
            ctx.reply("⚠️ Airtable non configuré.")
            return
        c = crm()
        icp_rec = _icp_par_nom(c, nom)
        if not icp_rec:
            c.close()
            ctx.reply(f"ICP « {render._esc(nom)} » introuvable. /icps")
            return
        reqs = icp_mod.requetes_people(icp_rec["fields"])
        if not reqs:
            c.close()
            ctx.reply("Cet ICP ne génère aucune requête (postes/secteurs vides).")
            return
        ctx.reply(f"🎯 {len(reqs)} requête(s) générée(s) pour « {render._esc(nom)} ». "
                  "Lancement…")
        total_aj, total_cout = 0, 0.0
        for lib, texte in reqs[:6]:                 # plafond raisonnable
            try:
                contacts, cout = source.rechercher_personnes(cle, texte)
            except source.ExaError:
                continue
            keys.ajouter_cout(uid, cout)
            total_cout += cout
            # Score ICP de chaque contact.
            for ct in contacts:
                sc = icp_mod.scorer_contact(
                    {"Poste actuel": ct.poste, "Lieu": ct.lieu,
                     "Entreprise actuelle": ct.entreprise}, icp_rec["fields"])
                ct.brut["_score_icp"] = sc
            aj, ig = c.upsert_contacts(contacts, cout=cout, marque=state.marque)
            total_aj += aj
        c.close()
        ctx.reply(f"✅ ICP exécuté : <b>{total_aj}</b> contact(s) ajouté(s) "
                  f"au CRM · 💰 ${total_cout:.4f}")

    @app.command("/run")
    def run_requete(ctx):
        """Rejoue une requête sauvegardée (table Requêtes) + met à jour son suivi."""
        lib = ctx.reste.strip()
        cle = _exiger_exa(ctx)
        if not cle:
            return
        if not has_airtable():
            ctx.reply("⚠️ Airtable non configuré.")
            return
        c = crm()
        req = None
        for r in c.lister("Requêtes", max_records=100):
            if (r["fields"].get("Libellé") or "").lower() == lib.lower():
                req = r
                break
        if not req:
            c.close()
            ctx.reply(f"Requête « {render._esc(lib)} » introuvable. /requetes")
            return
        f = req["fields"]
        texte = f.get("Texte requête", "")
        typ = (f.get("Type") or "people").lower()
        ctx.reply(f"▶️ Rejoue « {render._esc(lib)} » ({typ})…")
        try:
            if typ == "company":
                items, cout = source.rechercher_entreprises(cle, texte)
                aj, ig = c.upsert_entreprises(items, cout=cout, marque=state.marque)
            else:
                items, cout = source.rechercher_personnes(cle, texte)
                aj, ig = c.upsert_contacts(items, cout=cout, marque=state.marque)
        except source.ExaError as e:
            c.close()
            ctx.reply(f"⚠️ {e}")
            return
        keys.ajouter_cout(uid, cout)
        # Suivi : MAJ dernière exécution / nb résultats / coût cumulé.
        cumul = float(f.get("Coût cumulé$", 0) or 0) + cout
        try:
            c.maj("Requêtes", req["id"], {
                "Dernière exécution": _now_iso(),
                "Nb résultats": len(items), "Coût cumulé$": round(cumul, 4)})
        except crm_mod.CRMError:
            pass
        c.close()
        ctx.reply(f"✅ {aj} ajouté(s) · {ig} doublon(s) · 💰 ${cout:.4f}")

    @app.command("/requetes")
    def requetes(ctx):
        if not has_airtable():
            ctx.reply("⚠️ Airtable non configuré.")
            return
        c = crm()
        recs = c.lister("Requêtes", max_records=50)
        c.close()
        if not recs:
            ctx.reply("Aucune requête sauvegardée. Crée-en dans Airtable (table "
                      "Requêtes) puis /run &lt;libellé&gt;.")
            return
        lignes = ["📑 <b>Requêtes</b>\n"]
        for r in recs:
            f = r["fields"]
            lignes.append(f"• <b>{render._esc(f.get('Libellé', '—'))}</b> "
                          f"({f.get('Type', 'people')}) — "
                          f"{f.get('Nb résultats', 0)} résultats")
        ctx.reply("\n".join(lignes))

    # ── Mode brouillon (générer → éditer → régénérer → envoyer) ───────────────

    @app.command("/brouillon")
    def brouillon(ctx):
        nom = ctx.reste.strip()
        if not nom or not has_airtable():
            ctx.reply("Usage : /brouillon &lt;campagne&gt;")
            return
        c = crm()
        camp = _campagne_par_nom(c, nom)
        if not camp:
            c.close()
            ctx.reply(f"Campagne introuvable. /campagnes")
            return
        cibles = _cibles_campagne(c, camp)
        c.close()
        if not cibles:
            ctx.reply("Aucune cible avec email.")
            return
        expediteur = mailing.config_smtp()["from"]
        objet, corps, html = mailing.composer(cibles[0]["fields"],
                                               camp["fields"], expediteur)
        # Stocke le brouillon courant (éditable).
        state.kind = "brouillon"
        state._camp = camp                          # type: ignore[attr-defined]
        state.items = cibles
        state._draft = {"objet": objet, "corps": corps,  # type: ignore[attr-defined]
                        "dest": cibles[0]["fields"].get("Email", "")}
        ctx.reply(
            f"📝 <b>Brouillon</b> (cible : {render._esc(state._draft['dest'])})\n\n"
            f"<b>Objet</b> : {render._esc(objet)}\n<pre>{render._esc(corps)}</pre>\n\n"
            "✏️ <b>Éditer</b> : /objet &lt;nouveau&gt; ou /corps &lt;nouveau&gt;\n"
            "🔄 /regen — régénère depuis le template · 📤 envoie :",
            buttons=[[{"text": "📤 Envoyer ce brouillon", "callback_data": "drf:send"},
                      {"text": "✖️ Annuler", "callback_data": "drf:cancel"}]])

    @app.command("/objet")
    def edit_objet(ctx):
        d = getattr(state, "_draft", None)
        if not d:
            ctx.reply("Aucun brouillon. /brouillon &lt;campagne&gt;")
            return
        d["objet"] = ctx.reste.strip()
        ctx.reply(f"✏️ Objet mis à jour : {render._esc(d['objet'])}")

    @app.command("/corps")
    def edit_corps(ctx):
        d = getattr(state, "_draft", None)
        if not d:
            ctx.reply("Aucun brouillon. /brouillon &lt;campagne&gt;")
            return
        d["corps"] = ctx.reste.strip()
        ctx.reply("✏️ Corps mis à jour.")

    @app.command("/regen")
    def regen(ctx):
        camp = getattr(state, "_camp", None)
        cibles = getattr(state, "items", [])
        if not camp or not cibles:
            ctx.reply("Aucun brouillon à régénérer.")
            return
        expediteur = mailing.config_smtp()["from"]
        objet, corps, _ = mailing.composer(cibles[0]["fields"], camp["fields"],
                                           expediteur)
        state._draft = {"objet": objet, "corps": corps,   # type: ignore[attr-defined]
                        "dest": cibles[0]["fields"].get("Email", "")}
        ctx.reply(f"🔄 Régénéré.\n<b>Objet</b> : {render._esc(objet)}\n"
                  f"<pre>{render._esc(corps)}</pre>")

    @app.callback("drf")
    def draft_cb(ctx):
        action = ctx.data.split(":", 1)[1] if ":" in ctx.data else ""
        d = getattr(state, "_draft", None)
        if action == "cancel" or not d:
            ctx.reply("✖️ Brouillon abandonné.")
            return
        if action == "send":
            if mailing.dry_run():
                ctx.reply("🟡 DRY-RUN actif : rien n'est envoyé. "
                          "Passe MAIL_DRY_RUN=false pour envoyer pour de vrai.")
                return
            try:
                mailing.envoyer(d["dest"], d["objet"], d["corps"])
                ctx.reply(f"📤 Envoyé à {render._esc(d['dest'])}.")
            except mailing.MailError as e:
                ctx.reply(f"❌ {e}")

    # ── Relances (détection IMAP des réponses) ────────────────────────────────

    @app.command("/relancer")
    def relancer(ctx):
        nom = ctx.reste.strip()
        if not nom or not has_airtable():
            ctx.reply("Usage : /relancer &lt;campagne&gt;")
            return
        ctx.reply("🔁 Détection des réponses (IMAP)…")
        repondus = set()
        if mailing.imap_pret():
            try:
                repondus = mailing.expediteurs_recents(jours=30)
            except mailing.MailError as e:
                ctx.reply(f"⚠️ IMAP : {e}")
        c = crm()
        camp = _campagne_par_nom(c, nom)
        if not camp:
            c.close()
            ctx.reply("Campagne introuvable. /campagnes")
            return
        cibles = _cibles_campagne(c, camp)
        # Met à jour le statut « Répondu » et filtre les non-répondants.
        a_relancer, repondu_n = [], 0
        for rec in cibles:
            mail = (rec["fields"].get("Email") or "").lower()
            if mail and mail in repondus:
                repondu_n += 1
                try:
                    c.maj("Contacts", rec["id"], {"Statut": "Répondu"})
                except crm_mod.CRMError:
                    pass
            else:
                a_relancer.append(rec)
        c.close()
        if not a_relancer:
            ctx.reply(f"Tous ont répondu ({repondu_n}) ou aucune cible. Rien à relancer.")
            return
        state.kind = "campagne"
        state._camp = camp                          # type: ignore[attr-defined]
        state.items = a_relancer
        ctx.reply(
            f"🔁 <b>{len(a_relancer)}</b> à relancer ({repondu_n} ont répondu, "
            f"exclus).\nMode : {'DRY-RUN' if mailing.dry_run() else 'ENVOI RÉEL'}",
            buttons=[[{"text": "📨 Relancer tous", "callback_data": "snd:batch"}],
                     [{"text": "👤 Un par un", "callback_data": "snd:one"}],
                     [{"text": "✖️ Annuler", "callback_data": "snd:cancel"}]])

    # ── Marques (multi-marques) ───────────────────────────────────────────────

    @app.command("/marques")
    def marques(ctx):
        if not has_airtable():
            ctx.reply("⚠️ Airtable non configuré.")
            return
        c = crm()
        recs = c.lister("Marques", max_records=50)
        c.close()
        if not recs:
            ctx.reply("Aucune marque. /marque_add &lt;nom&gt; | site | produits")
            return
        lignes = ["🏷️ <b>Marques</b>\n"]
        for r in recs:
            f = r["fields"]
            actif = "✅" if f.get("Nom") == state.marque else "▫️"
            lignes.append(f"{actif} <b>{render._esc(f.get('Nom', '—'))}</b> — "
                          f"{render._esc(f.get('Site', ''))}")
        lignes.append("\n💡 /marque &lt;nom&gt; pour activer une marque.")
        ctx.reply("\n".join(lignes))

    @app.command("/marque")
    def marque(ctx):
        nom = ctx.reste.strip()
        if not nom:
            ctx.reply(f"Marque active : <b>{render._esc(state.marque) or '—'}</b>\n"
                      "Usage : /marque &lt;nom&gt;")
            return
        if not has_airtable():
            ctx.reply("⚠️ Airtable non configuré.")
            return
        c = crm()
        existe = any((r["fields"].get("Nom") or "").lower() == nom.lower()
                     for r in c.lister("Marques", max_records=100))
        c.close()
        if not existe:
            ctx.reply(f"Marque « {render._esc(nom)} » inconnue. /marques")
            return
        state.marque = nom
        ctx.reply(f"🏷️ Marque active : <b>{render._esc(nom)}</b>. "
                  "Les recherches, ICP et sauvegardes seront taggés à cette marque.")

    @app.command("/marque_add")
    def marque_add(ctx):
        parts = [p.strip() for p in ctx.reste.split("|")]
        if not parts or not parts[0]:
            ctx.reply("Usage : /marque_add &lt;nom&gt; | site | produits "
                      "| signature | logo_url")
            return
        if not has_airtable():
            ctx.reply("⚠️ Airtable non configuré.")
            return
        f = {"Nom": parts[0], "Active": True}
        for i, col in enumerate(["Site", "Produits", "Signature", "Logo URL"],
                                start=1):
            if i < len(parts) and parts[i]:
                f[col] = parts[i]
        try:
            c = crm()
            c.creer("Marques", f)
            c.close()
        except crm_mod.CRMError as e:
            ctx.reply(f"⚠️ {e}")
            return
        state.marque = parts[0]
        ctx.reply(f"🏷️ Marque « {render._esc(parts[0])} » créée et activée.")

    @app.command("/icp_import")
    def icp_import(ctx):
        """Génère des ICP depuis le site d'une marque (analyse de la page produit)."""
        ctx.reply(
            "🔗 <b>Import d'ICP depuis un site</b>\n\n"
            "Cette commande nécessite l'analyse de la page produit du site — "
            "fournis-moi l'URL et la liste des produits avec leurs cibles, ou "
            "crée les ICP manuellement avec /icp_add (un par produit).\n\n"
            "<i>Astuce : /marque_add &lt;nom&gt; | site | produits, puis un "
            "/icp_add par produit en précisant postes/secteurs/lieux.</i>")

    @app.defaut
    def inconnu(ctx):
        ctx.reply("Commande inconnue. /help")

    log.info("EXO prêt.")
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
