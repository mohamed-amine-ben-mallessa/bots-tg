# bots-tg — fabrique de bots Telegram

Monorepo de bots Telegram bâtis sur un socle commun. **Convention : un dossier =
un bot.** Le code générique vit une seule fois dans [`botkit/`](botkit) ; chaque
bot ne contient que sa logique métier. Un fix dans `botkit` profite à tous les
bots — fini la divergence du copier-coller.

```
bots-tg/
├── botkit/          🧰 socle partagé (Telegram, pagination, store, app, sinks)
├── exa-bot/         🔎 EXO — plateforme de prospection (Exa + Airtable + mailing)
└── <futur-bot>/     même structure : source + render + bot + .env
```

---

## 🧰 botkit — le socle

Pas la lib PyPI `telebot` : c'est **du code maison factorisé**, sans dépendance
lourde (juste `httpx`).

| Module | Rôle |
|---|---|
| `telegram_api.py` | client Telegram robuste : long-polling (retry réseau), `send_message` (HTML, chunking, fallback texte), `send_document`, `answer_callback` best-effort, `set_my_commands` |
| `app.py` | runner `BotApp` : boucle de vie + dispatch des commandes (`@app.command`) et callbacks (`@app.callback`), purge des updates au démarrage, capture d'erreurs par update |
| `pagination.py` | pagination générique d'une liste (◀️ Page X/N ▶️), index global préservé |
| `store.py` | persistance atomique : `JsonStore` (dict) et `SeenStore` (dédup). Fallback si fichier bind-monté (Errno 16) |
| `sinks/airtable.py` | écriture de records dans Airtable (`pyairtable`) |

API minimale :

```python
from botkit.app import BotApp
app = BotApp(token, chat_id, nom="mon-bot")

@app.command("/x")
def handler(ctx):
    ctx.reply("…")            # ctx.reply / ctx.document / ctx.args / ctx.reste

@app.callback("pg")           # tous les callbacks « pg:… »
def page(ctx):
    ...                       # ctx.data = callback_data

app.run()                     # polling robuste + dispatch
```

### Créer un nouveau bot

1. `mkdir bots-tg/mon-bot`, copie la trame d'`exa-bot` (`source.py`, `render.py`,
   `bot.py`, `requirements.txt`, `Dockerfile`, `docker-compose.yml`, `.env.example`).
2. **source.py** : wrappe ton SDK/API → liste d'objets normalisés.
3. **render.py** : objet → `(texte HTML, boutons)`.
4. **bot.py** : déclare commandes/callbacks via `BotApp`. `botkit` gère le reste.
5. `cp .env.example .env`, remplis, puis `python bot.py` (ou `docker compose up`).

⚠️ **Un bot = un token = un conteneur.** Deux instances du même token →
conflit Telegram 409 (une seule peut poller).

---

## 🔎 exa-bot (EXO) — plateforme de prospection

Bot Telegram complet de prospection B2B : recherche de personnes/entreprises via
**Exa**, CRM **Airtable** (multi-marques), enrichissement d'email (**Serper** →
**Zeruh**), campagnes **email** (SMTP/IMAP) avec garde-fous, et UX gamifiée.

### Fonctions

| Domaine | Détail |
|---|---|
| **Recherche** | `/people` `/company` — panneau à boutons (marque, ICP, multi-requêtes, params) ou requête directe. Source : API Exa (people/company/answer). |
| **CRM** | 6 tables Airtable liées (Contacts, Entreprises, ICP, Requêtes, Campagnes, Emails) + table Marques. `/setup` les crée via l'API. Dédup à l'insertion. |
| **Multi-marques** | colonne `Marque` + table Marques (signature, logo, SMTP par marque). `/marques`, `/marque <nom>`. |
| **ICP** | profil de client idéal → génère des requêtes Exa + score les contacts. `/icps`, `/icp_add`, `/icp_run`. |
| **Enrichissement email** | bouton ✉️ : Serper (Google dorks) → regex → Zeruh (deliverable/risky/undeliverable) → MAJ Airtable. |
| **Campagnes** | templates à variables (`{prenom}`, `{url_produit}`, `{image_url}`…), HTML + images hébergées. Envoi batch / individuel / brouillon éditable. Relances via détection IMAP des réponses. |
| **Garde-fous mailing** | `MAIL_DRY_RUN=true` par défaut (aucun envoi), quota/jour, confirmation. |
| **Gamification** | `/stats` : niveau, streak, badges, objectif hebdo. Feedback + fil d'Ariane après chaque action. |
| **Config** | `/config` : statut des clés API + email, tests SMTP/IMAP. |
| **Export** | `/export <table>` → CSV. |

Schéma Airtable détaillé : [`exa-bot/AIRTABLE-SCHEMA.md`](exa-bot/AIRTABLE-SCHEMA.md).

### Clés API

| Service | Où | Comment |
|---|---|---|
| Telegram | `.env` | BotFather |
| Airtable | `.env` | token avec scopes data + schema |
| Zeruh | `.env` | zeruh.com (vérif. email) |
| SMTP/IMAP | `.env` | ton fournisseur (OVH : SSL 465/993) |
| **Exa** | **par l'utilisateur** | `/setkey` dans le chat (jamais en `.env`) |
| **Serper** | **par l'utilisateur** | `/setserper` dans le chat |

### Lancer

```bash
cd exa-bot
cp .env.example .env          # remplis Telegram, Airtable, Zeruh, SMTP
pip install -r requirements.txt
python bot.py                 # local
# ou en Docker (depuis exa-bot/) :
docker compose up -d --build  # monte ./data (clés + stats persistants)
```

Puis dans Telegram : `/setkey <clé Exa>`, `/setserper <clé>`, puis `/menu`.

---

## 🐳 Déploiement (VPS)

Chaque bot = un dossier `/opt/<bot>` + son `.env` + `docker compose up -d`.
Le `docker-compose.yml` monte un dossier `./data` (RW) pour les données
persistantes (clés, stats) — **un dossier, pas un fichier** (un bind-mount de
fichier casse l'écriture atomique avec « Errno 16 Device busy »).

```bash
# sur le VPS
cd /opt/exa-bot/exa-bot
docker compose up -d --build
docker compose logs -f
```

---

## 🧪 Tests

```bash
pytest exa-bot/tests/ botkit/tests/ -q      # ~47 tests, réseau mocké
```

---

## 🔐 Sécurité

`.env`, `keys.json`, `data/`, `stats.json`, exports CSV et données perso sont
**git-ignorés**. Ne commite jamais de clés. Si une clé a fuité (ex. collée dans
un chat), **régénère-la**.
