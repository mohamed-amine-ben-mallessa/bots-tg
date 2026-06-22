"""Source de données Exa : people, company, answer (via exa-py).

La clé API est fournie PAR L'UTILISATEUR (passée en argument). Extraction
COMPLÈTE des champs Exa (workHistory, educationHistory, financials, webTraffic)
pour alimenter le CRM Airtable. Le coût (`costDollars.total`) est renvoyé avec
chaque appel.
"""

from dataclasses import dataclass, field
from typing import List, Tuple, Optional


class ExaError(RuntimeError):
    pass


# ── Modèles normalisés ────────────────────────────────────────────────────────

@dataclass
class Contact:
    nom: str = ""
    prenom: str = ""
    poste: str = ""               # poste actuel (workHistory[0].title)
    entreprise: str = ""          # société actuelle
    lieu: str = ""
    linkedin: str = ""
    parcours: str = ""            # workHistory formaté (multi-lignes)
    formation: str = ""           # educationHistory formaté
    email: str = ""
    telephone: str = ""
    resume: str = ""
    requete: str = ""
    brut: dict = field(default_factory=dict)

    def libelle(self):
        return " @ ".join(x for x in (self.poste, self.entreprise) if x)

    def airtable(self, cout=None):
        rec = {
            "Nom": self.nom, "Prénom": self.prenom, "Poste actuel": self.poste,
            "Entreprise actuelle": self.entreprise, "Lieu": self.lieu,
            "LinkedIn": self.linkedin, "Parcours": self.parcours,
            "Formation": self.formation, "Email": self.email,
            "Téléphone": self.telephone, "Résumé": self.resume,
        }
        if cout is not None:
            rec["Coût$"] = round(float(cout), 4)
        return {k: v for k, v in rec.items() if v not in ("", None)}


@dataclass
class Entreprise:
    nom: str = ""
    site: str = ""
    description: str = ""
    secteur: str = ""
    annee_creation: Optional[int] = None
    effectif: Optional[int] = None
    ville: str = ""
    pays: str = ""
    ca_annuel: Optional[float] = None
    financement_total: Optional[float] = None
    derniere_levee: str = ""
    visites_mois: Optional[int] = None
    resume: str = ""
    requete: str = ""
    brut: dict = field(default_factory=dict)

    def libelle(self):
        bits = [self.secteur]
        if self.effectif:
            bits.append(f"{self.effectif} pers.")
        if self.ville or self.pays:
            bits.append(" ".join(x for x in (self.ville, self.pays) if x))
        return " · ".join(b for b in bits if b)

    def airtable(self, cout=None):
        rec = {
            "Nom": self.nom, "Site": self.site, "Description": self.description,
            "Secteur": self.secteur, "Année création": self.annee_creation,
            "Effectif": self.effectif, "Ville": self.ville, "Pays": self.pays,
            "CA annuel": self.ca_annuel, "Financement total": self.financement_total,
            "Dernière levée": self.derniere_levee, "Visites/mois": self.visites_mois,
            "Résumé": self.resume,
        }
        if cout is not None:
            rec["Coût$"] = round(float(cout), 4)
        return {k: v for k, v in rec.items() if v not in ("", None)}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _client(api_key):
    if not api_key:
        raise ExaError("Clé Exa manquante.")
    try:
        from exa_py import Exa
    except ImportError as e:
        raise ExaError("exa-py manquant : `pip install exa-py`.") from e
    return Exa(api_key=api_key)


def _txt(v):
    return v.strip() if isinstance(v, str) else ""


def _num(v):
    return v if isinstance(v, (int, float)) else None


def _get(d, *path, defaut=None):
    """Accès tolérant à un chemin imbriqué dict (props Exa)."""
    cur = d
    for k in path:
        if not isinstance(cur, dict):
            return defaut
        cur = cur.get(k)
    return cur if cur is not None else defaut


def _cout(res) -> float:
    for attr in ("cost_dollars", "costDollars"):
        cd = getattr(res, attr, None)
        if cd is None:
            continue
        if isinstance(cd, (int, float)):
            return float(cd)
        total = getattr(cd, "total", None)
        if total is None and isinstance(cd, dict):
            total = cd.get("total")
        if isinstance(total, (int, float)):
            return float(total)
    return 0.0


def _props(r):
    ents = getattr(r, "entities", None) or []
    if ents and hasattr(ents[0], "properties"):
        return ents[0].properties or {}
    return {}


def _highlight(r):
    hl = getattr(r, "highlights", None) or []
    txt = _txt(hl[0]) if hl else _txt(getattr(r, "text", ""))
    return (txt[:300] + "…") if len(txt) > 300 else txt


def _format_parcours(work_history):
    """workHistory[] -> texte multi-lignes « Poste — Entreprise (from–to) »."""
    lignes = []
    for w in (work_history or [])[:6]:
        if not isinstance(w, dict):
            continue
        titre = _txt(w.get("title"))
        boite = _txt(_get(w, "company", "name"))
        dts = w.get("dates") or {}
        periode = "–".join(x for x in (_txt(dts.get("from")), _txt(dts.get("to"))) if x)
        ligne = " — ".join(x for x in (titre, boite) if x)
        if periode:
            ligne += f" ({periode})"
        if ligne:
            lignes.append(ligne)
    return "\n".join(lignes)


def _format_formation(edu_history):
    lignes = []
    for e in (edu_history or [])[:4]:
        if not isinstance(e, dict):
            continue
        deg = _txt(e.get("degree"))
        inst = _txt(_get(e, "institution", "name"))
        ligne = " — ".join(x for x in (deg, inst) if x)
        if ligne:
            lignes.append(ligne)
    return "\n".join(lignes)


# ── People ────────────────────────────────────────────────────────────────────

def rechercher_personnes(api_key, query, n=10) -> Tuple[List[Contact], float]:
    exa = _client(api_key)
    try:
        res = exa.search(query, category="people", type="auto", num_results=n)
    except Exception as e:
        raise ExaError(f"Exa people search a échoué : {e}") from e
    out = []
    for r in getattr(res, "results", []) or []:
        p = _props(r)
        wh = p.get("workHistory") or []
        poste = _txt(_get(wh[0], "title")) if wh else ""
        boite = _txt(_get(wh[0], "company", "name")) if wh else ""
        out.append(Contact(
            nom=_txt(p.get("name")) or _txt(getattr(r, "title", "")),
            prenom=_txt(p.get("firstName")),
            poste=poste, entreprise=boite,
            lieu=_txt(p.get("location")),
            linkedin=_txt(p.get("url")) or _txt(getattr(r, "url", "")),
            parcours=_format_parcours(wh),
            formation=_format_formation(p.get("educationHistory")),
            resume=_highlight(r), requete=query, brut=p,
        ))
    return out, _cout(res)


# ── Company ───────────────────────────────────────────────────────────────────

def rechercher_entreprises(api_key, query, n=10) -> Tuple[List[Entreprise], float]:
    exa = _client(api_key)
    try:
        res = exa.search(query, category="company", type="auto",
                         num_results=n, contents={"highlights": True})
    except Exception as e:
        raise ExaError(f"Exa company search a échoué : {e}") from e
    out = []
    for r in getattr(res, "results", []) or []:
        p = _props(r)
        hq = p.get("headquarters") or {}
        fin = p.get("financials") or {}
        levee = fin.get("fundingLatestRound") or {}
        levee_txt = " ".join(str(x) for x in (
            _txt(levee.get("name")), levee.get("amount")) if x)
        out.append(Entreprise(
            nom=_txt(p.get("name")) or _txt(getattr(r, "title", "")),
            site=_txt(p.get("website")) or _txt(getattr(r, "url", "")),
            description=_txt(p.get("description")),
            secteur=_txt(p.get("industry") or p.get("category")),
            annee_creation=_num(p.get("foundedYear")),
            effectif=_num(_get(p, "workforce", "total")),
            ville=_txt(hq.get("city")), pays=_txt(hq.get("country")),
            ca_annuel=_num(fin.get("revenueAnnual")),
            financement_total=_num(fin.get("fundingTotal")),
            derniere_levee=levee_txt.strip(),
            visites_mois=_num(_get(p, "webTraffic", "visitsMonthly")),
            resume=_highlight(r), requete=query, brut=p,
        ))
    return out, _cout(res)


# ── Answer (enrichissement) ───────────────────────────────────────────────────

def answer(api_key, query, output_schema=None, text=False) -> Tuple[dict, float]:
    """Exa Answer : réponse synthétisée + citations. Renvoie (dict, coût$).

    `output_schema` (JSON Schema Draft-7) force une réponse structurée. Utile
    pour enrichir un contact (ex. trouver email, accroche personnalisée).
    """
    exa = _client(api_key)
    kw = {"text": text}
    if output_schema:
        kw["output_schema"] = output_schema
    try:
        res = exa.answer(query, **kw)
    except Exception as e:
        raise ExaError(f"Exa answer a échoué : {e}") from e
    citations = []
    for c in getattr(res, "citations", []) or []:
        citations.append({
            "title": _txt(getattr(c, "title", "")),
            "url": _txt(getattr(c, "url", "")),
        })
    return {"answer": getattr(res, "answer", None), "citations": citations}, _cout(res)


def valider_cle(api_key) -> bool:
    try:
        _client(api_key).search("test", type="auto", num_results=1)
        return True
    except Exception:
        return False
