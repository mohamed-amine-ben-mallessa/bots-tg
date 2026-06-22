"""Pagination générique d'une liste d'items pour Telegram.

Affiche une page d'items (un message par item, pour ses boutons propres) avec une
barre de navigation « ◀️ Précédent · Page X/N · Suivant ▶️ ». L'index reste
GLOBAL (1-based) dans le lot complet, pour que les callbacks par item restent
corrects quelle que soit la page.

Le bot fournit une fonction `render(index, item) -> (texte, boutons)`. botkit ne
connaît rien du contenu — juste comment paginer.
"""

import re

PAGE_SIZE = 5            # items par page (surchargeable)


def nb_pages(total, page_size=PAGE_SIZE):
    return max(1, (total + page_size - 1) // page_size)


def borner_page(page, total, page_size=PAGE_SIZE):
    """Ramène `page` dans [1, nb_pages]."""
    return max(1, min(int(page or 1), nb_pages(total, page_size)))


def page_items(items, page, page_size=PAGE_SIZE):
    """Renvoie [(index_global_1based, item), …] pour la page demandée."""
    page = borner_page(page, len(items), page_size)
    debut = (page - 1) * page_size
    fin = min(debut + page_size, len(items))
    return [(i + 1, items[i]) for i in range(debut, fin)]


def barre(page, total, page_size=PAGE_SIZE, prefixe="pg"):
    """Clavier de navigation, ou None s'il n'y a qu'une page.

    Les callbacks sont « <prefixe>:<n> » ; le compteur central est inerte
    (« <prefixe>:noop »).
    """
    pages = nb_pages(total, page_size)
    if pages <= 1:
        return None
    page = borner_page(page, total, page_size)
    ligne = []
    if page > 1:
        ligne.append({"text": "◀️ Précédent", "callback_data": f"{prefixe}:{page - 1}"})
    ligne.append({"text": f"📄 {page}/{pages}", "callback_data": f"{prefixe}:noop"})
    if page < pages:
        ligne.append({"text": "Suivant ▶️", "callback_data": f"{prefixe}:{page + 1}"})
    return [ligne]


def entete(titre, page, total, page_size=PAGE_SIZE):
    """En-tête « N résultat(s) — titre · items a–b · page X/N »."""
    pages = nb_pages(total, page_size)
    p = borner_page(page, total, page_size)
    deb = (p - 1) * page_size + 1
    fin = min(deb + page_size - 1, total)
    return (f"<b>{total} résultat(s)</b> — {titre}\n"
            f"<i>{deb}–{fin} · page {p}/{pages}</i>")


def parse(data, prefixe="pg"):
    """« pg:3 » -> 3 ; « pg:noop » ou autre -> None."""
    m = re.fullmatch(rf"{re.escape(prefixe)}:(\d+)", data or "")
    return int(m.group(1)) if m else None


def envoyer_page(tg, chat_id, items, render, page=1, titre="", page_size=PAGE_SIZE,
                 prefixe="pg"):
    """Envoie une page complète : en-tête + items (un message chacun) + nav.

    `render(index, item) -> (texte, boutons|None)`. La barre de navigation est
    attachée sous le dernier item de la page.
    """
    total = len(items)
    if total == 0:
        tg.send_message(chat_id, "Aucun résultat à afficher.")
        return
    page = borner_page(page, total, page_size)
    tg.send_message(chat_id, entete(titre, page, total, page_size))
    paire = page_items(items, page, page_size)
    for pos, (index, item) in enumerate(paire):
        texte, boutons = render(index, item)
        nav = barre(page, total, page_size, prefixe) if pos == len(paire) - 1 else None
        if nav and boutons:
            boutons = list(boutons) + nav
        elif nav:
            boutons = nav
        tg.send_message(chat_id, texte, buttons=boutons)
