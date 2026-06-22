"""Rendu des résultats Exa (Contact / Entreprise) en messages Telegram + boutons."""


def _esc(t):
    return (str(t or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def render_contact(index, c):
    """(texte, boutons) pour un Contact. `index` = position globale 1-based."""
    lignes = [f"<b>{index}. 👤 {_esc(c.nom) or '—'}</b>"]
    if c.libelle():
        lignes.append(_esc(c.libelle()))
    if c.lieu:
        lignes.append(f"📍 {_esc(c.lieu)}")
    if c.resume:
        lignes.append(f"<i>{_esc(c.resume)}</i>")
    ligne_b = []
    if c.linkedin:
        ligne_b.append({"text": "🔗 LinkedIn", "url": c.linkedin})
    ligne_b.append({"text": "💾 Airtable", "callback_data": f"sav:{index}"})
    return "\n".join(lignes), [ligne_b]


def render_entreprise(index, e):
    """(texte, boutons) pour une Entreprise."""
    lignes = [f"<b>{index}. 🏢 {_esc(e.nom) or '—'}</b>"]
    if e.libelle():
        lignes.append(_esc(e.libelle()))
    if e.ca_annuel or e.financement_total:
        bits = []
        if e.ca_annuel:
            bits.append(f"CA ~{int(e.ca_annuel):,}".replace(",", " ") + " €")
        if e.financement_total:
            bits.append(f"levé ~{int(e.financement_total):,}".replace(",", " ") + " €")
        lignes.append("💶 " + " · ".join(bits))
    if e.resume:
        lignes.append(f"<i>{_esc(e.resume)}</i>")
    ligne_b = []
    if e.site:
        ligne_b.append({"text": "🔗 Site", "url": e.site})
    ligne_b.append({"text": "💾 Airtable", "callback_data": f"sav:{index}"})
    return "\n".join(lignes), [ligne_b]


def render(index, item):
    """Dispatch selon le type de l'objet (Contact ou Entreprise)."""
    from source import Contact
    if isinstance(item, Contact):
        return render_contact(index, item)
    return render_entreprise(index, item)


def entete_recherche(titre, total, page, pages, cout):
    """En-tête d'une page de résultats, avec le coût de la requête."""
    deb = (page - 1) * 5 + 1
    fin = min(deb + 4, total)
    ligne_cout = f" · 💰 ${cout:.4f}" if cout else ""
    return (f"🔎 <b>{total} résultat(s)</b> — {_esc(titre)}\n"
            f"<i>{deb}–{fin} · page {page}/{pages}{ligne_cout}</i>")
