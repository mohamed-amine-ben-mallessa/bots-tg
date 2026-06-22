"""Menu hub + fil d'Ariane : navigation reliée et pro pour EXO.

Un écran d'accueil /menu relie toutes les fonctions par boutons (Recherche, CRM,
Campagnes, Marques, Stats). Chaque écran propose l'« étape suivante » logique
(fil d'Ariane) pour guider l'utilisateur dans le parcours de prospection :

  Marque → ICP → Recherche → Enrichir → CRM → Campagne → Relance

Callbacks : menu:<section>  (search/crm/camp/marque/stats/home/guide).
"""


def _esc(t):
    return (str(t or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def hub(marque="", crm_ok=False, resume_stats=""):
    """Écran d'accueil : sections + marque active + mini-stats."""
    bandeau = f"🏷️ <b>{_esc(marque)}</b>\n" if marque else ""
    txt = (
        "🚀 <b>EXO — Menu</b>\n"
        + bandeau +
        "\nTa plateforme de prospection. Choisis une section :"
    )
    if resume_stats:
        txt += f"\n\n{resume_stats}"
    boutons = [
        [{"text": "🔎 Recherche", "callback_data": "menu:search"},
         {"text": "📇 CRM", "callback_data": "menu:crm"}],
        [{"text": "📣 Campagnes", "callback_data": "menu:camp"},
         {"text": "🏷️ Marques", "callback_data": "menu:marque"}],
        [{"text": "📊 Stats", "callback_data": "menu:stats"},
         {"text": "🧭 Guide", "callback_data": "menu:guide"}],
        [{"text": "⚙️ Configuration", "callback_data": "menu:config"}],
    ]
    return txt, boutons


def section_search():
    txt = ("🔎 <b>Recherche</b>\n\n"
           "Trouve des prospects (personnes) ou des entreprises, puis "
           "sauvegarde-les dans ton CRM.\n\n"
           "<i>Astuce : choisis une marque + un ICP pour des requêtes "
           "pré-générées.</i>")
    boutons = [
        [{"text": "👤 Personnes", "callback_data": "menu:people"},
         {"text": "🏢 Entreprises", "callback_data": "menu:company"}],
        [{"text": "🎯 Lancer un ICP", "callback_data": "menu:icps"}],
        [{"text": "⬅️ Menu", "callback_data": "menu:home"}],
    ]
    return txt, boutons


def section_crm(stats_line=""):
    txt = ("📇 <b>CRM</b>\n\n" + (stats_line + "\n\n" if stats_line else "") +
           "Gère tes contacts et entreprises, enrichis les emails, exporte.")
    boutons = [
        [{"text": "📤 Export Contacts", "callback_data": "menu:exp:Contacts"},
         {"text": "📤 Export Entreprises", "callback_data": "menu:exp:Entreprises"}],
        [{"text": "🎯 ICP", "callback_data": "menu:icps"}],
        [{"text": "⬅️ Menu", "callback_data": "menu:home"}],
    ]
    return txt, boutons


def section_camp():
    txt = ("📣 <b>Campagnes</b>\n\n"
           "Crée et envoie des emails de prospection (variables, images), "
           "puis relance les non-répondants.\n\n"
           "<i>Étapes : choisir cibles → brouillon → envoyer → relancer.</i>")
    boutons = [
        [{"text": "📋 Mes campagnes", "callback_data": "menu:camplist"}],
        [{"text": "⬅️ Menu", "callback_data": "menu:home"}],
    ]
    return txt, boutons


def section_marque(marque=""):
    txt = ("🏷️ <b>Marques</b>\n\n"
           f"Marque active : <b>{_esc(marque) or 'aucune'}</b>\n\n"
           "Travaille pour plusieurs marques : chaque recherche, ICP et contact "
           "est rattaché à la marque active.")
    boutons = [
        [{"text": "📋 Choisir une marque", "callback_data": "menu:marquelist"}],
        [{"text": "⬅️ Menu", "callback_data": "menu:home"}],
    ]
    return txt, boutons


def section_config(statut):
    """Écran Configuration : clés API + email. `statut` = dict de bool/str.

    Clés attendues : exa, serper, zeruh (bool/masqué), airtable (bool),
    smtp (bool), imap (bool), dry_run (bool), smtp_from (str).
    """
    def ic(ok):
        return "✅" if ok else "❌"

    exa = statut.get("exa")
    serper = statut.get("serper")
    txt = (
        "⚙️ <b>Configuration</b>\n\n"
        "<b>🔑 Clés API</b>\n"
        f"{ic(bool(exa))} Exa : <code>{_esc(exa) if exa else 'non définie'}</code>\n"
        f"{ic(bool(serper))} Serper : <code>{_esc(serper) if serper else 'non définie'}</code>\n"
        f"{ic(statut.get('zeruh'))} Zeruh (vérif. email) : "
        f"{'configurée' if statut.get('zeruh') else 'non configurée'}\n\n"
        "<b>📇 Airtable (CRM)</b>\n"
        f"{ic(statut.get('airtable'))} "
        f"{'connecté (7 tables)' if statut.get('airtable') else 'non configuré'}\n\n"
        "<b>✉️ Email</b>\n"
        f"{ic(statut.get('smtp'))} SMTP : "
        f"{_esc(statut.get('smtp_from')) if statut.get('smtp') else 'non configuré'}\n"
        f"{ic(statut.get('imap'))} IMAP (détection réponses) : "
        f"{'OK' if statut.get('imap') else 'non configuré'}\n"
        f"{'🟡 DRY-RUN actif (aucun envoi réel)' if statut.get('dry_run') else '🔴 ENVOI RÉEL activé'}"
    )
    boutons = [
        [{"text": "🔑 Définir clé Exa", "callback_data": "menu:cfg:exa"},
         {"text": "🔑 Clé Serper", "callback_data": "menu:cfg:serper"}],
        [{"text": "🗑️ Effacer mes clés", "callback_data": "menu:cfg:clearkeys"}],
        [{"text": "✉️ Tester l'email (SMTP)", "callback_data": "menu:cfg:testmail"}],
    ]
    if statut.get("imap"):
        boutons.append([{"text": "📥 Tester IMAP (réponses)",
                         "callback_data": "menu:cfg:testimap"}])
    boutons.append([{"text": "⬅️ Menu", "callback_data": "menu:home"}])
    return txt, boutons


def guide(etape="start"):
    """Parcours guidé pas-à-pas (pour les débutants)."""
    txt = (
        "🧭 <b>Guide express — 5 étapes</b>\n\n"
        "1️⃣ <b>Marque</b> — active ta marque (/marques)\n"
        "2️⃣ <b>ICP</b> — choisis un profil cible (/icps)\n"
        "3️⃣ <b>Recherche</b> — lance-le → contacts dans le CRM\n"
        "4️⃣ <b>Enrichir</b> — trouve les emails (bouton ✉️)\n"
        "5️⃣ <b>Campagne</b> — rédige &amp; envoie (/campagnes)\n\n"
        "<i>Chaque écran te propose l'étape suivante. Suis le fil 🧵</i>")
    boutons = [
        [{"text": "🚀 Commencer (marque)", "callback_data": "menu:marquelist"}],
        [{"text": "⬅️ Menu", "callback_data": "menu:home"}],
    ]
    return txt, boutons


def suite(apres, **kw):
    """Fil d'Ariane : boutons « étape suivante » après une action.

    `apres` ∈ {recherche, save, enrich, icp, campagne}. Renvoie une liste de
    boutons à attacher au message de résultat pour proposer la suite logique.
    """
    if apres == "recherche":
        return [[{"text": "💾 Tout sauvegarder", "callback_data": "act:saveall"},
                 {"text": "🔁 Affiner", "callback_data": "menu:people"}]]
    if apres == "save":
        return [[{"text": "✉️ Enrichir l'email", "callback_data": kw.get("enr", "menu:home")}],
                [{"text": "🔎 Continuer la recherche", "callback_data": "menu:search"}]]
    if apres == "enrich":
        return [[{"text": "📣 Créer une campagne", "callback_data": "menu:camp"}],
                [{"text": "🔎 Recherche", "callback_data": "menu:search"}]]
    if apres == "icp":
        return [[{"text": "✉️ Enrichir les emails", "callback_data": "menu:crm"},
                 {"text": "📊 Stats", "callback_data": "menu:stats"}]]
    if apres == "campagne":
        return [[{"text": "🔁 Relancer", "callback_data": "menu:camp"},
                 {"text": "📊 Stats", "callback_data": "menu:stats"}]]
    return None
