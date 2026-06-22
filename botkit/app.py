"""Runner de bot Telegram : boucle de vie + dispatch générique.

Le bot déclare ses commandes (« /people », …) et ses handlers de callbacks via
un BotApp ; botkit s'occupe de tout le reste :
  • long-polling robuste (erreurs réseau -> retry, jamais de crash),
  • purge des updates en attente au démarrage (pas de vieux clics rejoués),
  • restriction à un chat autorisé (bot privé),
  • dispatch des messages (commandes) et des callbacks (par préfixe),
  • capture des exceptions par update (un handler qui plante n'arrête pas le bot).

Exemple minimal :

    from botkit.app import BotApp
    app = BotApp(token, chat_id)

    @app.command("/start")
    def start(ctx):
        ctx.reply("Salut !")

    @app.callback("pg")          # tous les callbacks « pg:... »
    def page(ctx):
        ...

    app.run()
"""

import logging
import time

from .telegram_api import Telegram, TelegramError

log = logging.getLogger("botkit")


class Context:
    """Passé à chaque handler : accès au bot, au chat, et aux données de l'update."""

    def __init__(self, app, chat_id, *, text="", args="", reste="", data="",
                 callback_id="", update=None):
        self.app = app
        self.tg = app.tg
        self.chat_id = chat_id
        self.text = text          # message complet
        self.args = args          # 1er argument après la commande
        self.reste = reste        # tout ce qui suit la commande
        self.data = data          # callback_data (pour les clics)
        self.callback_id = callback_id
        self.update = update

    def reply(self, texte, buttons=None):
        return self.tg.send_message(self.chat_id, texte, buttons=buttons)

    def document(self, path, caption=""):
        return self.tg.send_document(self.chat_id, path, caption=caption)


class BotApp:
    def __init__(self, token, chat_id, *, nom="bot"):
        self.tg = Telegram(token)
        self.chat_id = str(chat_id)
        self.nom = nom
        self._commandes = {}      # "/x" -> handler(ctx)
        self._callbacks = {}      # préfixe -> handler(ctx)
        self._defaut = None       # handler des commandes inconnues
        self._au_demarrage = None

    # ── enregistrement (décorateurs) ──────────────────────────────────────────

    def command(self, *noms):
        def deco(fn):
            for n in noms:
                self._commandes[n.lower()] = fn
            return fn
        return deco

    def callback(self, prefixe):
        """Enregistre un handler pour tous les callbacks « <prefixe>:... »."""
        def deco(fn):
            self._callbacks[prefixe] = fn
            return fn
        return deco

    def defaut(self, fn):
        """Handler appelé pour une commande inconnue."""
        self._defaut = fn
        return fn

    def au_demarrage(self, fn):
        """Callable exécuté une fois le bot prêt (ex. message d'accueil)."""
        self._au_demarrage = fn
        return fn

    # ── autorisation ──────────────────────────────────────────────────────────

    def autorise(self, cid):
        return str(cid) == self.chat_id

    # ── dispatch ──────────────────────────────────────────────────────────────

    def _handle_message(self, msg):
        chat = (msg.get("chat") or {}).get("id")
        if not self.autorise(chat):
            return
        texte = (msg.get("text") or "").strip()
        if not texte:
            return
        parts = texte.split()
        cmd = parts[0].lower().split("@")[0]
        arg = parts[1] if len(parts) > 1 else ""
        reste = texte[len(parts[0]):].strip()
        ctx = Context(self, self.chat_id, text=texte, args=arg, reste=reste,
                      update=msg)
        handler = self._commandes.get(cmd, self._defaut)
        if handler:
            handler(ctx)

    def _handle_callback(self, cb):
        chat = ((cb.get("message") or {}).get("chat") or {}).get("id")
        if not self.autorise(chat):
            return
        self.tg.answer_callback(cb.get("id", ""))
        data = cb.get("data", "")
        prefixe = data.split(":", 1)[0]
        handler = self._callbacks.get(prefixe)
        if handler:
            ctx = Context(self, self.chat_id, data=data,
                          callback_id=cb.get("id", ""), update=cb)
            handler(ctx)

    def _handle_update(self, update):
        try:
            if update.get("message"):
                self._handle_message(update["message"])
            elif update.get("callback_query"):
                self._handle_callback(update["callback_query"])
        except Exception:
            log.exception("Erreur de traitement d'une update")
            try:
                self.tg.send_message(self.chat_id, "❌ Une erreur est survenue.")
            except TelegramError:
                pass

    # ── boucle de vie ─────────────────────────────────────────────────────────

    def _purger(self):
        """Avance l'offset au-delà des updates accumulés hors-ligne."""
        offset = None
        try:
            while True:
                ups = self.tg.get_updates(offset, timeout=0)
                if not ups:
                    break
                offset = ups[-1]["update_id"] + 1
        except TelegramError as e:
            log.warning("Purge updates: %s", e)
        return offset

    def run(self):
        log.info("Bot « %s » démarré.", self.nom)
        if self._au_demarrage:
            try:
                self._au_demarrage(Context(self, self.chat_id))
            except Exception:
                log.exception("au_demarrage a échoué")
        offset = self._purger()
        while True:
            try:
                updates = self.tg.get_updates(offset)
            except TelegramError as e:
                log.warning("getUpdates: %s", e)
                time.sleep(3)
                continue
            except Exception:
                log.exception("getUpdates: erreur inattendue")
                time.sleep(3)
                continue
            for up in updates:
                offset = up["update_id"] + 1
                self._handle_update(up)
