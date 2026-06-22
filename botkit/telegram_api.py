"""Client Telegram bas niveau : long-polling et envois.

Couvre le sous-ensemble de l'API Bot nécessaire au bot : getUpdates (polling),
sendMessage (avec clavier inline), sendDocument, answerCallbackQuery. Aucune
dépendance lourde — juste httpx.
"""

import httpx

API = "https://api.telegram.org"
_MAX_LEN = 3800  # marge sous la limite Telegram (4096)


class TelegramError(RuntimeError):
    pass


class Telegram:
    """Petit wrapper autour de l'API Bot. `token` requis."""

    def __init__(self, token, timeout=35):
        if not token:
            raise TelegramError("TELEGRAM_BOT_TOKEN manquant.")
        self._base = f"{API}/bot{token}"
        self._client = httpx.Client(timeout=timeout)

    # ── Réception ────────────────────────────────────────────────────────────

    def get_updates(self, offset=None, timeout=30):
        """Long-polling : récupère les updates depuis `offset`. Renvoie la liste.

        Les erreurs réseau (connexion reset, timeout, protocole) sont converties
        en TelegramError pour que la boucle de polling les traite comme des aléas
        transitoires (retry) plutôt que de faire planter le bot.
        """
        params = {"timeout": timeout, "allowed_updates": '["message","callback_query"]'}
        if offset is not None:
            params["offset"] = offset
        try:
            r = self._client.get(f"{self._base}/getUpdates", params=params,
                                 timeout=timeout + 10)
            data = r.json()
        except httpx.HTTPError as e:
            raise TelegramError(f"getUpdates réseau : {type(e).__name__}: {e}")
        if not data.get("ok"):
            raise TelegramError(f"getUpdates a échoué : {data}")
        return data.get("result", [])

    # ── Envoi ────────────────────────────────────────────────────────────────

    def send_message(self, chat_id, text, buttons=None):
        """Envoie un message (HTML). `buttons` = inline keyboard optionnel.

        Découpe automatiquement les messages trop longs (les boutons ne sont
        attachés qu'au dernier morceau).
        """
        morceaux = _chunk(text)
        last = None
        for i, m in enumerate(morceaux):
            payload = {"chat_id": chat_id, "text": m, "parse_mode": "HTML",
                       "disable_web_page_preview": True}
            if buttons and i == len(morceaux) - 1:
                payload["reply_markup"] = {"inline_keyboard": buttons}
            try:
                last = self._post("sendMessage", payload)
            except TelegramError as e:
                # HTML mal formé (ex. un « <type> » non échappé) -> Telegram
                # rejette le parsing. On renvoie le même texte en clair plutôt
                # que de perdre le message.
                if "parse entities" not in str(e):
                    raise
                payload.pop("parse_mode", None)
                last = self._post("sendMessage", payload)
        return last

    def send_document(self, chat_id, path, caption=""):
        """Envoie un fichier (PDF). Renvoie False si le fichier est absent."""
        import os
        if not path or not os.path.exists(path):
            return False
        with open(path, "rb") as f:
            r = self._client.post(
                f"{self._base}/sendDocument",
                data={"chat_id": chat_id, "caption": caption[:1000]},
                files={"document": (os.path.basename(path), f, "application/pdf")},
            )
        data = r.json()
        if not data.get("ok"):
            raise TelegramError(f"sendDocument a échoué : {data}")
        return True

    def set_my_commands(self, commands):
        """Configure le menu natif Telegram. `commands` = [(cmd, description), …]."""
        payload = {"commands": [{"command": c, "description": d}
                                for c, d in commands]}
        try:
            self._post("setMyCommands", payload)
            return True
        except TelegramError:
            return False

    def answer_callback(self, callback_id, text=""):
        """Acquitte un clic de bouton (enlève le « sablier » côté client).

        Best-effort : l'acquittement est purement cosmétique. S'il échoue (clic
        trop vieux après un redémarrage, ID invalide…), on l'ignore — surtout
        pas de quoi bloquer le traitement réel du clic (génération de CV, etc.).
        Renvoie True si acquitté, False sinon.
        """
        try:
            self._post("answerCallbackQuery",
                       {"callback_query_id": callback_id, "text": text[:200]})
            return True
        except TelegramError:
            return False

    # ── interne ──────────────────────────────────────────────────────────────

    def _post(self, method, payload):
        r = self._client.post(f"{self._base}/{method}", json=payload)
        data = r.json()
        if not data.get("ok"):
            raise TelegramError(f"{method} a échoué : {data}")
        return data.get("result")

    def close(self):
        self._client.close()


def _chunk(text, maxlen=_MAX_LEN):
    """Découpe un texte en morceaux <= maxlen, en coupant sur des sauts de ligne."""
    if len(text) <= maxlen:
        return [text]
    morceaux, courant = [], ""
    for ligne in text.split("\n"):
        candidat = ligne if not courant else courant + "\n" + ligne
        if len(candidat) > maxlen and courant:
            morceaux.append(courant)
            courant = ligne
        else:
            courant = candidat
    if courant:
        morceaux.append(courant)
    return morceaux
