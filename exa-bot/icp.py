"""ICP (profil de client idéal) : génération de requêtes Exa + scoring.

Un ICP définit des postes cibles, secteurs et lieux. On en dérive
automatiquement des requêtes Exa en langage naturel, et on peut scorer un
contact/une entreprise selon son adéquation à l'ICP.
"""

import re
import unicodedata


def _norm(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _liste(champ):
    """Découpe un champ texte (postes/secteurs/lieux) en éléments."""
    return [x.strip() for x in re.split(r"[\n,;]+", champ or "") if x.strip()]


def requetes_people(icp_fields):
    """Génère des requêtes people Exa depuis un ICP.

    Croise postes × lieux (et ajoute un secteur si présent). Renvoie une liste
    de (libellé, texte_requête).
    """
    postes = _liste(icp_fields.get("Postes cibles"))
    secteurs = _liste(icp_fields.get("Secteurs"))
    lieux = _liste(icp_fields.get("Lieux")) or [""]
    base_mots = (icp_fields.get("Mots-clés requête") or "").strip()
    out = []
    for poste in (postes or [base_mots] or [""]):
        if not poste:
            continue
        for lieu in lieux:
            secteur = secteurs[0] if secteurs else ""
            bits = [poste]
            if secteur:
                bits.append(secteur)
            if lieu:
                bits.append(lieu)
            texte = " ".join(bits)
            lib = " · ".join(b for b in (poste, lieu) if b)
            out.append((lib[:60], texte))
    return out or ([(base_mots[:60], base_mots)] if base_mots else [])


def requetes_company(icp_fields):
    """Génère des requêtes company Exa depuis un ICP (secteurs × lieux + taille)."""
    secteurs = _liste(icp_fields.get("Secteurs"))
    lieux = _liste(icp_fields.get("Lieux")) or [""]
    taille = (icp_fields.get("Taille entreprise") or "").strip()
    out = []
    for secteur in (secteurs or [icp_fields.get("Mots-clés requête", "")]):
        if not secteur:
            continue
        for lieu in lieux:
            bits = [f"{secteur} companies"]
            if lieu:
                bits.append(lieu)
            if taille:
                bits.append(f"{taille} employees")
            texte = " ".join(bits)
            out.append((f"{secteur} · {lieu}".strip(" ·")[:60], texte))
    return out


def scorer_contact(contact_fields, icp_fields):
    """Score 0-100 d'adéquation d'un contact à l'ICP (poste, lieu, secteur)."""
    score = 0
    postes = [_norm(p) for p in _liste(icp_fields.get("Postes cibles"))]
    poste_c = _norm(contact_fields.get("Poste actuel"))
    if postes and any(p in poste_c or poste_c in p for p in postes if p):
        score += 50
    elif postes and any(mot in poste_c for p in postes for mot in p.split() if len(mot) > 3):
        score += 30
    lieux = [_norm(l) for l in _liste(icp_fields.get("Lieux"))]
    lieu_c = _norm(contact_fields.get("Lieu"))
    if not lieux or any(l in lieu_c for l in lieux if l):
        score += 25
    secteurs = [_norm(s) for s in _liste(icp_fields.get("Secteurs"))]
    ent_c = _norm(contact_fields.get("Entreprise actuelle"))
    if not secteurs or any(s in ent_c for s in secteurs if s):
        score += 25
    return min(100, score)
