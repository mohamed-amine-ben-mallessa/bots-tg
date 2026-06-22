"""Tests UX : menu hub, panneau de recherche, gamification."""

import sys
from pathlib import Path

BOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BOT.parent))
sys.path.insert(0, str(BOT))

import menu                              # noqa: E402
import search_panel as sp                # noqa: E402
import stats as stats_mod                # noqa: E402


# ── Menu hub ──────────────────────────────────────────────────────────────────

def test_hub_boutons():
    txt, btns = menu.hub("Sollea AI", crm_ok=True, resume_stats="mini")
    assert "Sollea AI" in txt and "mini" in txt
    cbs = [b["callback_data"] for row in btns for b in row]
    assert "menu:search" in cbs and "menu:stats" in cbs


def test_fil_ariane():
    assert menu.suite("recherche")[0][0]["callback_data"] == "act:saveall"
    assert menu.suite("enrich") is not None
    assert menu.suite("inconnu") is None


def test_hub_a_bouton_config():
    _, btns = menu.hub("", crm_ok=True)
    cbs = [b["callback_data"] for row in btns for b in row]
    assert "menu:config" in cbs


def test_section_config():
    statut = {"exa": "ab…yz", "serper": "", "zeruh": True, "airtable": True,
              "smtp": True, "imap": True, "dry_run": True,
              "smtp_from": "X <x@y.fr>"}
    txt, btns = menu.section_config(statut)
    assert "Configuration" in txt and "ab…yz" in txt
    assert "non définie" in txt          # serper vide
    assert "DRY-RUN" in txt
    cbs = [b["callback_data"] for row in btns for b in row]
    assert "menu:cfg:exa" in cbs and "menu:cfg:testmail" in cbs
    assert "menu:cfg:testimap" in cbs    # imap actif -> bouton présent


def test_section_config_imap_off():
    statut = {"smtp": True, "imap": False, "dry_run": False}
    txt, btns = menu.section_config(statut)
    cbs = [b["callback_data"] for row in btns for b in row]
    assert "menu:cfg:testimap" not in cbs    # imap off -> pas de bouton
    assert "ENVOI RÉEL" in txt


# ── Panneau de recherche ──────────────────────────────────────────────────────

ICPS = [
    {"nom": "Sollea · LeadFlow", "marque": "Sollea AI",
     "fields": {"Postes cibles": "CTO, VP", "Lieux": "Paris", "Secteurs": "SaaS"}},
    {"nom": "Autre · X", "marque": "Autre", "fields": {"Postes cibles": "DG"}},
]


def test_panel_filtre_icp_par_marque():
    p = sp.Panel("person", ["Sollea AI", "Autre"], ICPS)
    p.marque = "Sollea AI"
    assert len(p.icps_marque()) == 1
    assert p.icps_marque()[0]["nom"] == "Sollea · LeadFlow"


def test_panel_selection_requetes():
    p = sp.Panel("person", ["Sollea AI"], ICPS)
    p.requetes = [("a", "qa"), ("b", "qb"), ("c", "qc")]
    p.selection = {0, 2}
    choisies = p.requetes_choisies()
    assert [t for _, t in choisies] == ["qa", "qc"]


def test_panel_requete_libre_prioritaire():
    p = sp.Panel("person", [], [])
    p.libre = "CTO fintech"
    assert p.requetes_choisies() == [("Requête libre", "CTO fintech")]
    assert p.pret()


def test_panel_marque_at():
    p = sp.Panel("person", ["A", "B"], [])
    assert sp.marque_at(p, 0) == ""       # (toutes)
    assert sp.marque_at(p, 1) == "A"
    assert sp.marque_at(p, 2) == "B"


def test_panel_params_par_defaut():
    p = sp.Panel("company", [], [])
    assert p.nb == 10 and p.type == "auto"
    txt, btns = sp.vue_params(p)
    cbs = [b["callback_data"] for row in btns for b in row]
    assert "sp:n:25" in cbs and "sp:t:deep" in cbs


def test_filtrer_lieu():
    class O:
        def __init__(self, lieu):
            self.lieu = lieu
    items = [O("Paris"), O("Lyon"), O("Paris 11")]
    out = sp.filtrer_lieu(items, "paris")
    assert len(out) == 2


# ── Gamification ──────────────────────────────────────────────────────────────

def test_stats_compteurs_et_score(tmp_path):
    st = stats_mod.Stats(str(tmp_path / "s.json"))
    st.ajouter("u", "contacts", 5)
    st.ajouter("u", "emails", 2)
    u = st._u("u")
    assert u["contacts"] == 5 and u["emails"] == 2
    # score = contacts*1 + emails*3 = 5 + 6 = 11
    assert u["score"] == 11


def test_stats_badge_debloque(tmp_path):
    st = stats_mod.Stats(str(tmp_path / "s.json"))
    nouveaux = st.ajouter("u", "contacts", 10)
    assert any("Chasseur" in b for b in nouveaux)
    # Pas de re-débloquage.
    assert st.ajouter("u", "contacts", 1) == []


def test_stats_niveau_progression(tmp_path):
    st = stats_mod.Stats(str(tmp_path / "s.json"))
    assert st.niveau("u")[0] == "🥉 Bronze"
    st.ajouter("u", "reponses", 11)        # 11 * 10 = 110 pts -> Argent
    assert "Argent" in st.niveau("u")[0]


def test_stats_objectif_et_barre(tmp_path):
    st = stats_mod.Stats(str(tmp_path / "s.json"))
    st.set_objectif("u", 20)
    st.ajouter("u", "contacts", 10)
    fait, obj = st.objectif_semaine("u")
    assert fait == 10 and obj == 20
    assert "%" in st.resume("u")


def test_stats_resume_html(tmp_path):
    st = stats_mod.Stats(str(tmp_path / "s.json"))
    st.ajouter("u", "contacts", 3)
    r = st.resume("u")
    assert "Niveau" in r and "Streak" in r and "Objectif" in r
