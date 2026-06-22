"""Tests du socle botkit : pagination, store, dispatch."""

import sys
from pathlib import Path

# botkit importable depuis le dossier parent de tests/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from botkit import pagination, store        # noqa: E402
from botkit.app import BotApp, Context      # noqa: E402


# ── Pagination ────────────────────────────────────────────────────────────────

def test_nb_pages_et_borner():
    assert pagination.nb_pages(0) == 1
    assert pagination.nb_pages(12) == 3
    assert pagination.borner_page(99, 12) == 3
    assert pagination.borner_page(0, 12) == 1


def test_page_items_index_global():
    items = list(range(1, 13))
    p2 = pagination.page_items(items, 2)
    assert [idx for idx, _ in p2] == [6, 7, 8, 9, 10]


def test_barre_et_parse():
    assert pagination.barre(1, 3) is None
    bar = pagination.barre(2, 12)
    assert [b["callback_data"] for b in bar[0]] == ["pg:1", "pg:noop", "pg:3"]
    assert pagination.parse("pg:3") == 3
    assert pagination.parse("pg:noop") is None


def test_envoyer_page_attache_nav_au_dernier():
    envoyes = []

    class FakeTG:
        def send_message(self, cid, text, buttons=None):
            envoyes.append((text, buttons))

    items = list(range(1, 13))
    pagination.envoyer_page(FakeTG(), "1", items,
                            lambda i, it: (f"item {i}", [[{"text": "x", "callback_data": "y"}]]),
                            page=1, titre="t")
    # 1 en-tête + 5 items.
    assert len(envoyes) == 6
    # La barre de nav est sous le dernier item.
    derniers_btns = envoyes[-1][1]
    assert any("pg:" in b["callback_data"] for row in derniers_btns for b in row
               if "callback_data" in b)


# ── Store ─────────────────────────────────────────────────────────────────────

def test_jsonstore_persiste(tmp_path):
    p = tmp_path / "s.json"
    js = store.JsonStore(str(p))
    js.set("k", {"a": 1})
    assert store.JsonStore(str(p)).get("k") == {"a": 1}
    js.clear()
    assert not p.exists()


def test_seenstore_persiste_et_filtre(tmp_path):
    p = tmp_path / "seen.json"
    s = store.SeenStore(str(p))
    s.add_many(["a", "b"])
    s.save()
    s2 = store.SeenStore(str(p))
    assert s2.is_seen("a") and not s2.is_seen("c")
    items = [{"id": "a"}, {"id": "c"}]
    nouveaux = s2.filtrer_nouveaux(items, lambda it: it["id"])
    assert [it["id"] for it in nouveaux] == ["c"]


def test_seenstore_rognage(tmp_path):
    s = store.SeenStore(str(tmp_path / "seen.json"), max_ids=3)
    s.add_many([str(i) for i in range(10)])
    s.save()
    assert len(s) == 3 and s.is_seen("9") and not s.is_seen("0")


# ── Dispatch (BotApp) ─────────────────────────────────────────────────────────

class _TG:
    def __init__(self):
        self.sent = []

    def send_message(self, cid, text, buttons=None):
        self.sent.append(text)

    def answer_callback(self, cid, text=""):
        return True


def _app():
    app = BotApp.__new__(BotApp)         # sans token réel
    app.tg = _TG()
    app.chat_id = "123"
    app.nom = "test"
    app._commandes = {}
    app._callbacks = {}
    app._defaut = None
    app._au_demarrage = None
    return app


def test_dispatch_commande():
    app = _app()
    vus = []

    @app.command("/ping")
    def ping(ctx):
        vus.append(ctx.reste)
        ctx.reply("pong")

    app._handle_message({"chat": {"id": "123"}, "text": "/ping hello world"})
    assert vus == ["hello world"]
    assert app.tg.sent == ["pong"]


def test_dispatch_ignore_autre_chat():
    app = _app()

    @app.command("/x")
    def x(ctx):
        ctx.reply("ne devrait pas")

    app._handle_message({"chat": {"id": "999"}, "text": "/x"})
    assert app.tg.sent == []          # chat non autorisé -> ignoré


def test_dispatch_callback_par_prefixe():
    app = _app()
    recu = []

    @app.callback("pg")
    def pg(ctx):
        recu.append(ctx.data)

    app._handle_callback({"message": {"chat": {"id": "123"}}, "id": "c",
                          "data": "pg:2"})
    assert recu == ["pg:2"]


def test_handler_qui_plante_n_arrete_pas():
    app = _app()

    @app.command("/boom")
    def boom(ctx):
        raise ValueError("crash")

    # _handle_update capture l'exception et envoie un message d'erreur.
    app._handle_update({"message": {"chat": {"id": "123"}, "text": "/boom"}})
    assert any("erreur" in m.lower() for m in app.tg.sent)


def test_commande_inconnue_appelle_defaut():
    app = _app()

    @app.defaut
    def d(ctx):
        ctx.reply("inconnue")

    app._handle_message({"chat": {"id": "123"}, "text": "/zzz"})
    assert app.tg.sent == ["inconnue"]
