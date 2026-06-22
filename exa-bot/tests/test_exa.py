"""Tests d'exa-bot : extraction Exa (mock), rendu, mailing, keystore."""

import sys
from pathlib import Path

BOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BOT.parent))     # bots-tg/ (botkit)
sys.path.insert(0, str(BOT))            # exa-bot/

import enrich                            # noqa: E402
import icp as icp_mod                     # noqa: E402
import mailing                           # noqa: E402
import render                            # noqa: E402
import source                            # noqa: E402
from keystore import KeyStore, masquer   # noqa: E402


# ── Faux SDK Exa ──────────────────────────────────────────────────────────────

class _Ent:
    def __init__(self, props):
        self.properties = props


class _Res:
    def __init__(self, props=None, title="", url="", highlights=None):
        self.entities = [_Ent(props)] if props else []
        self.title = title
        self.url = url
        self.highlights = highlights or []
        self.text = ""


class _SR:
    def __init__(self, results, cost=0.005):
        self.results = results
        self.cost_dollars = {"total": cost}


class _FakeExa:
    def __init__(self, results, cost=0.005):
        self._results, self._cost = results, cost

    def search(self, query, **kw):
        return _SR(self._results, self._cost)


def _patch(monkeypatch, results, cost=0.005):
    monkeypatch.setattr(source, "_client", lambda key: _FakeExa(results, cost))


# ── People : extraction complète ──────────────────────────────────────────────

def test_people_extraction_complete(monkeypatch):
    props = {
        "name": "Jane Doe", "firstName": "Jane", "location": "Paris",
        "url": "https://linkedin.com/in/jane",
        "workHistory": [
            {"title": "VP Eng", "company": {"name": "Acme"},
             "dates": {"from": "2020", "to": "2024"}},
            {"title": "Lead", "company": {"name": "Beta"},
             "dates": {"from": "2018", "to": "2020"}},
        ],
        "educationHistory": [{"degree": "MSc CS", "institution": {"name": "MIT"}}],
    }
    _patch(monkeypatch, [_Res(props=props, highlights=["résumé"])], cost=0.007)
    contacts, cout = source.rechercher_personnes("KEY", "q")
    assert cout == 0.007
    c = contacts[0]
    assert c.nom == "Jane Doe" and c.poste == "VP Eng" and c.entreprise == "Acme"
    assert "VP Eng — Acme (2020–2024)" in c.parcours
    assert "Lead — Beta" in c.parcours
    assert c.formation == "MSc CS — MIT"
    rec = c.airtable(cout=cout)
    assert rec["Poste actuel"] == "VP Eng" and rec["Coût$"] == 0.007


def test_company_extraction_complete(monkeypatch):
    props = {
        "name": "Acme AI", "website": "https://acme.ai", "industry": "AgTech",
        "foundedYear": 2019, "description": "AI for farms",
        "workforce": {"total": 42},
        "headquarters": {"city": "Boston", "country": "USA"},
        "financials": {"revenueAnnual": 5000000, "fundingTotal": 12000000,
                       "fundingLatestRound": {"name": "Series A", "amount": 8000000}},
        "webTraffic": {"visitsMonthly": 150000},
    }
    _patch(monkeypatch, [_Res(props=props)], cost=0.006)
    ents, cout = source.rechercher_entreprises("KEY", "agtech")
    e = ents[0]
    assert e.nom == "Acme AI" and e.secteur == "AgTech" and e.annee_creation == 2019
    assert e.effectif == 42 and e.ville == "Boston" and e.pays == "USA"
    assert e.ca_annuel == 5000000 and e.financement_total == 12000000
    assert "Series A" in e.derniere_levee
    assert e.visites_mois == 150000
    rec = e.airtable(cout=cout)
    assert rec["Effectif"] == 42 and rec["CA annuel"] == 5000000


def test_cle_manquante_leve():
    try:
        source.rechercher_personnes("", "q")
        assert False
    except source.ExaError:
        pass


def test_cout_objet_total(monkeypatch):
    class _R:
        results = []
        cost_dollars = type("C", (), {"total": 0.9})()
    monkeypatch.setattr(source, "_client", lambda key: type(
        "E", (), {"search": lambda self, q, **k: _R()})())
    _, cout = source.rechercher_personnes("KEY", "q")
    assert cout == 0.9


# ── Rendu ─────────────────────────────────────────────────────────────────────

def test_render_contact():
    c = source.Contact(nom="Jane Doe", poste="VP Eng", entreprise="Acme",
                       linkedin="https://lnkd.in/jane")
    txt, btns = render.render(3, c)
    assert "3." in txt and "Jane Doe" in txt and "VP Eng @ Acme" in txt
    plats = [b for row in btns for b in row]
    assert any(b.get("url") == "https://lnkd.in/jane" for b in plats)
    assert any(b.get("callback_data") == "sav:3" for b in plats)


def test_render_entreprise():
    e = source.Entreprise(nom="Acme AI", secteur="AgTech", effectif=42,
                          site="https://acme.ai", ca_annuel=5000000)
    txt, btns = render.render(1, e)
    assert "Acme AI" in txt and "AgTech" in txt
    assert any(b.get("url") == "https://acme.ai" for row in btns for b in row)


def test_entete_cout():
    txt = render.entete_recherche("people · q", 12, 2, 3, 0.0345)
    assert "12 résultat" in txt and "page 2/3" in txt and "$0.0345" in txt


# ── Mailing : rendu de templates ──────────────────────────────────────────────

def test_composer_variables():
    contact = {"Nom": "Jane Doe", "Prénom": "Jane", "Poste actuel": "VP Eng",
               "Entreprise actuelle": "Acme"}
    camp = {"Objet email": "{prenom}, une idée pour {entreprise}",
            "Corps email": "Bonjour {prenom}, {poste} chez {entreprise} ? {url_produit}",
            "Signature": "Cordialement,\n{expediteur}",
            "URL produit": "https://x.com", "Format": "Texte"}
    objet, corps, html = mailing.composer(contact, camp, "Amine")
    assert objet == "Jane, une idée pour Acme"
    assert "VP Eng chez Acme" in corps and "https://x.com" in corps
    assert "Amine" in corps
    assert html is None                     # Format Texte -> pas de HTML


def test_composer_html_avec_images():
    contact = {"Prénom": "Jane"}
    camp = {"Objet email": "Hi", "Corps email": "Bonjour {prenom}",
            "Image bannière": "https://cdn/b.png", "Logo URL": "https://cdn/l.png",
            "Format": "HTML"}
    _, _, html = mailing.composer(contact, camp, "")
    assert html is not None
    assert 'src="https://cdn/b.png"' in html and 'src="https://cdn/l.png"' in html


def test_variable_inconnue_preservee():
    out = mailing.rendre("Salut {prenom}, {inconnu}", {"prenom": "Jane"})
    assert out == "Salut Jane, {inconnu}"


def test_smtp_config_defaults(monkeypatch):
    monkeypatch.delenv("MAIL_DRY_RUN", raising=False)
    assert mailing.dry_run() is True        # dry-run par défaut
    monkeypatch.setenv("MAIL_DRY_RUN", "false")
    assert mailing.dry_run() is False


# ── KeyStore ──────────────────────────────────────────────────────────────────

def test_masquer():
    assert masquer("abcdefghijkl") == "abcd…ijkl"


# ── ICP : génération de requêtes + scoring ────────────────────────────────────

ICP = {"Nom": "SaaS-FR", "Postes cibles": "CTO, VP Engineering",
       "Secteurs": "SaaS, Fintech", "Lieux": "Paris, Lyon",
       "Taille entreprise": "11-50"}


def test_icp_requetes_people():
    reqs = icp_mod.requetes_people(ICP)
    textes = [t for _, t in reqs]
    assert "CTO SaaS Paris" in textes
    assert "VP Engineering SaaS Lyon" in textes
    assert len(reqs) == 4                            # 2 postes × 2 lieux


def test_icp_requetes_company():
    reqs = icp_mod.requetes_company(ICP)
    textes = [t for _, t in reqs]
    assert any("SaaS companies Paris" in t and "11-50" in t for t in textes)


def test_icp_scoring():
    assert icp_mod.scorer_contact(
        {"Poste actuel": "CTO", "Lieu": "Paris",
         "Entreprise actuelle": "SaaS Co"}, ICP) == 100
    assert icp_mod.scorer_contact(
        {"Poste actuel": "Cuisinier", "Lieu": "Tokyo"}, ICP) == 0


# ── Enrichissement (Serper dorks + extraction emails) ─────────────────────────

def test_construire_requetes():
    reqs = enrich.construire_requetes("Sam", "Altman", "OpenAI")
    assert any('"Sam Altman"' in r and "OpenAI" in r for r in reqs)
    assert any("-linkedin" in r for r in reqs)          # version OSINT
    assert any('"@openai"' in r for r in reqs)          # dork domaine


def test_emails_depuis_filtre_bruit():
    data = {"organic": [{"snippet": "contact sama@openai.com ou logo@2x.png"},
                        {"snippet": "image: a@b.jpg, vrai: jane@acme.io"}]}
    emails = enrich._emails_depuis(data, dom="openai")
    assert "sama@openai.com" in emails
    assert "jane@acme.io" in emails
    # Les images sont filtrées.
    assert not any(e.endswith((".png", ".jpg")) for e in emails)
    # L'email au domaine de l'entreprise passe en premier.
    assert emails[0] == "sama@openai.com"


def test_verifier_sans_cle(monkeypatch):
    monkeypatch.delenv("ZERUH_API_KEY", raising=False)
    try:
        enrich.verifier("a@b.com")
        assert False
    except enrich.EnrichError:
        pass


def test_keystore_2_cles_et_cout(tmp_path):
    ks = KeyStore(str(tmp_path / "k.json"))
    ks.set("u1", "exa-secret-1234", "exa")
    ks.set("u1", "serper-key-5678", "serper")
    assert ks.a_cle("u1", "exa") and ks.a_cle("u1", "serper")
    assert ks.masquee("u1", "exa") == "exa-…1234"
    assert ks.masquee("u1", "serper") == "serp…5678"
    ks.ajouter_cout("u1", 0.01)
    ks.ajouter_cout("u1", 0.005)
    assert round(ks.cout_total("u1"), 4) == 0.015 and ks.nb_appels("u1") == 2
    # Persistance + 2 clés indépendantes.
    ks2 = KeyStore(str(tmp_path / "k.json"))
    assert ks2.get("u1", "exa") == "exa-secret-1234"
    assert ks2.get("u1", "serper") == "serper-key-5678"
    assert ks2.supprimer("u1", "serper") is True
    assert not ks2.a_cle("u1", "serper") and ks2.a_cle("u1", "exa")
