"""Enrichissement email : Serper (Google dorks) -> regex -> Zeruh (vérification).

Pipeline déclenché par bouton sur un lead :
  1. construit plusieurs requêtes Google dork ciblées (nom + entreprise),
  2. les lance via l'API Serper (clé fournie par l'utilisateur),
  3. extrait les emails des résultats (regex), filtre le bruit (images, faux),
  4. vérifie chaque email via Zeruh (clé .env), garde les meilleurs,
  5. renvoie le meilleur email + son statut, pour MAJ Airtable.
"""

import os
import re

import httpx

SERPER_URL = "https://google.serper.dev/search"
ZERUH_URL = "https://api.zeruh.com/v1/verify"

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_SKIP = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", "example.com",
         "sentry.io", "@2x", "wixpress.com", "domain.com", "email.com")


class EnrichError(RuntimeError):
    pass


def _domaine(entreprise):
    """Devine un domaine probable depuis le nom d'entreprise."""
    return re.sub(r"[^a-z0-9]", "", (entreprise or "").lower())


def construire_requetes(prenom, nom, entreprise):
    """Plusieurs Google dorks complémentaires pour maximiser les emails trouvés."""
    full = " ".join(x for x in (prenom, nom) if x).strip()
    dom = _domaine(entreprise)
    reqs = [
        f'"{full}" "{entreprise}" (email OR contact OR "@") -linkedin -facebook -instagram',
        f'"{full}" "{entreprise}" "@{dom}"' if dom else "",
        f'"{full}" "{entreprise}" "email address"',
        f'"{full}" "{entreprise}" contact',
    ]
    return [r for r in reqs if r]


def _serper(api_key, query, n=10):
    try:
        r = httpx.post(SERPER_URL,
                       headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                       json={"q": query, "num": n}, timeout=25)
    except httpx.HTTPError as e:
        raise EnrichError(f"Serper réseau : {e}") from e
    if r.status_code != 200:
        raise EnrichError(f"Serper {r.status_code} : {r.text[:150]}")
    return r.json()


def _emails_depuis(data, dom=""):
    """Extrait les emails plausibles d'une réponse Serper. Priorise le domaine."""
    import json as _json
    bruts = set(EMAIL_RE.findall(_json.dumps(data)))
    propres = []
    for e in bruts:
        low = e.lower()
        if any(s in low for s in _SKIP):
            continue
        propres.append(e)
    # Les emails au domaine de l'entreprise d'abord.
    propres.sort(key=lambda e: (0 if dom and dom in e.lower() else 1, len(e)))
    return propres


def chercher_emails(serper_key, prenom, nom, entreprise, max_req=3):
    """Lance les dorks et renvoie la liste dédupliquée d'emails candidats (+ crédits)."""
    if not serper_key:
        raise EnrichError("Clé Serper manquante.")
    dom = _domaine(entreprise)
    vus, candidats, credits = set(), [], 0
    for q in construire_requetes(prenom, nom, entreprise)[:max_req]:
        data = _serper(serper_key, q)
        credits += int(data.get("credits", 0) or 0)
        for e in _emails_depuis(data, dom):
            if e.lower() not in vus:
                vus.add(e.lower())
                candidats.append(e)
    return candidats, credits


def verifier(email, zeruh_key=None):
    """Vérifie un email via Zeruh. Renvoie {email, status, score, smtp, raison}."""
    zeruh_key = zeruh_key or os.environ.get("ZERUH_API_KEY", "").strip()
    if not zeruh_key:
        raise EnrichError("ZERUH_API_KEY manquant (.env).")
    try:
        r = httpx.get(ZERUH_URL, params={"api_key": zeruh_key,
                                         "email_address": email}, timeout=25)
        d = r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise EnrichError(f"Zeruh : {e}") from e
    res = d.get("result", {}) if d.get("success") else {}
    vd = res.get("validation_details", {})
    return {
        "email": email,
        "status": res.get("status", "unknown"),     # deliverable/risky/undeliverable
        "score": res.get("score", 0),
        "smtp": bool(vd.get("smtp_check")),
        "role": bool(vd.get("role")),
        "disposable": bool(vd.get("disposable")),
        "raison": res.get("reason", ""),
    }


def enrichir_contact(serper_key, prenom, nom, entreprise, zeruh_key=None,
                     seuil_score=60):
    """Pipeline complet : trouve et vérifie. Renvoie le MEILLEUR email exploitable.

    Renvoie un dict : {email, status, score, …, credits, candidats} ou
    {email: None, candidats, credits} si rien d'exploitable.
    """
    candidats, credits = chercher_emails(serper_key, prenom, nom, entreprise)
    meilleur = None
    verifs = []
    for e in candidats[:5]:                          # plafonne les vérifs (coût)
        v = verifier(e, zeruh_key)
        verifs.append(v)
        # On retient le 1er deliverable, sinon le meilleur score >= seuil.
        if v["status"] == "deliverable":
            meilleur = v
            break
        if (meilleur is None or v["score"] > meilleur["score"]) \
                and v["score"] >= seuil_score and not v["disposable"]:
            meilleur = v
    return {"meilleur": meilleur, "candidats": candidats,
            "verifs": verifs, "credits": credits}


def valider_cle_serper(serper_key):
    try:
        _serper(serper_key, "test", n=1)
        return True
    except Exception:
        return False
