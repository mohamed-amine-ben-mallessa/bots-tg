<h1 align="center">🧰 bots-tg — a Telegram bot factory</h1>

<p align="center">
  <b>Stop copy-pasting the same 400 lines of Telegram plumbing into every new bot.</b><br>
  One shared kit, one folder per bot. Fix a bug in the kit, every bot gets the fix.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Telegram-Bot%20API-229ED9?logo=telegram&logoColor=white" alt="Telegram">
  <img src="https://img.shields.io/badge/dependencies-httpx%20only-brightgreen" alt="httpx only">
  <img src="https://img.shields.io/badge/tests-~47-1f9d55" alt="Tests">
  <img src="https://img.shields.io/badge/deploy-docker-2496ED?logo=docker&logoColor=white" alt="Docker">
  <img src="https://img.shields.io/badge/license-MIT-yellow" alt="MIT">
</p>

```python
from botkit.app import BotApp
app = BotApp(token, chat_id, nom="mon-bot")

@app.command("/hello")
def hello(ctx):
    ctx.reply("👋")

app.run()          # robust long-polling, dispatch, error capture — all handled
```

---

## Why this exists

Every Telegram bot starts the same way: long-polling with retries, message chunking at
4096 characters, a pagination scheme for lists, atomic JSON persistence, a callback
dispatcher. Everyone writes it once per bot, badly, and then the five copies drift apart.

**`botkit` is that code, written once.** A bot folder contains only what makes it that bot:
where the data comes from, how it renders, which commands exist.

```
bots-tg/
├── botkit/          🧰 the shared kit (Telegram, pagination, store, app, sinks)
├── exa-bot/         🔎 EXO — a full B2B prospecting platform built on it
└── <your-bot>/      same shape: source + render + bot + .env
```

Not the PyPI `telebot` package — this is hand-rolled, dependency-light (just `httpx`), and
small enough to read in one sitting.

## The kit

| Module | Role |
|---|---|
| `telegram_api.py` | Robust Telegram client: long-polling with network retry, `send_message` (HTML, chunking, text fallback), `send_document`, best-effort `answer_callback`, `set_my_commands` |
| `app.py` | The `BotApp` runner: lifecycle loop, `@app.command` / `@app.callback` dispatch, startup update purge, per-update error capture |
| `pagination.py` | Generic list pagination (◀️ Page X/N ▶️) preserving the global index |
| `store.py` | Atomic persistence: `JsonStore` (dict) and `SeenStore` (dedup), with a fallback when the file is bind-mounted (Errno 16) |
| `sinks/airtable.py` | Write records to Airtable (`pyairtable`) |

That Errno 16 fallback, the 4096-char chunking, the startup purge that stops a restarted
bot from replaying yesterday's messages — those are the bugs you'd otherwise find in
production. They're already fixed here.

## Build a new bot in 5 steps

1. `mkdir bots-tg/my-bot`, copy the shape of `exa-bot` (`source.py`, `render.py`, `bot.py`,
   `requirements.txt`, `Dockerfile`, `docker-compose.yml`, `.env.example`).
2. **`source.py`** — wrap your SDK/API into a list of normalized objects.
3. **`render.py`** — object → `(HTML text, buttons)`.
4. **`bot.py`** — declare commands and callbacks via `BotApp`. The kit handles the rest.
5. `cp .env.example .env`, fill it, then `python bot.py` (or `docker compose up`).

```python
@app.command("/x")
def handler(ctx):
    ctx.reply("…")            # ctx.reply / ctx.document / ctx.args / ctx.reste

@app.callback("pg")           # every "pg:…" callback
def page(ctx):
    ...                       # ctx.data = callback_data
```

⚠️ **One bot = one token = one container.** Two instances sharing a token means Telegram
409 — only one can poll.

## 🔎 exa-bot (EXO) — the reference bot

A complete B2B prospecting platform, and proof the kit carries real weight: people/company
search via **Exa**, an **Airtable** CRM (multi-brand), email enrichment (**Serper** →
**Zeruh**), **email campaigns** over SMTP/IMAP with guardrails, and a gamified UX.

| Area | What it does |
|---|---|
| **Search** | `/people` `/company` — button panel (brand, ICP, multi-query, params) or a direct query. Source: Exa API (people/company/answer). |
| **CRM** | 6 linked Airtable tables (Contacts, Companies, ICP, Queries, Campaigns, Emails) + a Brands table. `/setup` creates them via the API. Dedup on insert. |
| **Multi-brand** | A `Marque` column + Brands table (signature, logo, per-brand SMTP). `/marques`, `/marque <name>`. |
| **ICP** | An ideal-customer profile generates Exa queries and scores contacts. `/icps`, `/icp_add`, `/icp_run`. |
| **Email enrichment** | ✉️ button: Serper (Google dorks) → regex → Zeruh (deliverable / risky / undeliverable) → update Airtable. |
| **Campaigns** | Variable templates (`{prenom}`, `{url_produit}`, `{image_url}`…), HTML + hosted images. Batch / individual / editable draft. Follow-ups via IMAP reply detection. |
| **Mailing guardrails** | `MAIL_DRY_RUN=true` **by default** (sends nothing), daily quota, confirmation step. |
| **Gamification** | `/stats`: level, streak, badges, weekly goal. Feedback + breadcrumb after every action. |
| **Config** | `/config`: API key + email status, SMTP/IMAP tests. |
| **Export** | `/export <table>` → CSV. |

Airtable schema: [`exa-bot/AIRTABLE-SCHEMA.md`](exa-bot/AIRTABLE-SCHEMA.md).

### Keys

| Service | Where | How |
|---|---|---|
| Telegram | `.env` | BotFather |
| Airtable | `.env` | Token with data + schema scopes |
| Zeruh | `.env` | zeruh.com (email verification) |
| SMTP/IMAP | `.env` | Your provider (OVH: SSL 465/993) |
| **Exa** | **by the user, in chat** | `/setkey` — never in `.env` |
| **Serper** | **by the user, in chat** | `/setserper` |

The two search keys are deliberately **never stored in the repo or the environment** — the
operator pastes them into the chat and they live in a gitignored keystore.

### Run it

```bash
cd exa-bot
cp .env.example .env          # Telegram, Airtable, Zeruh, SMTP
pip install -r requirements.txt
python bot.py                 # local
# or Docker, from exa-bot/:
docker compose up -d --build  # mounts ./data (keys + stats persist)
```

Then in Telegram: `/setkey <Exa key>`, `/setserper <key>`, then `/menu`.

## Deploy (VPS)

One bot = one `/opt/<bot>` folder + its `.env` + `docker compose up -d`. The compose file
mounts a `./data` **directory** (not a file) for persistent state — bind-mounting a single
file breaks atomic writes with "Errno 16 Device busy".

```bash
cd /opt/exa-bot/exa-bot
docker compose up -d --build
docker compose logs -f
```

## Tests

```bash
pytest exa-bot/tests/ botkit/tests/ -q      # ~47 tests, network mocked
```

## 🔐 Security

`.env`, `keys.json`, `data/`, `stats.json`, CSV exports and personal data are **gitignored**.
Never commit a key. If one leaked (pasted into a chat, say), **rotate it**.

Cold email is regulated — GDPR, CAN-SPAM and friends. `MAIL_DRY_RUN=true` is the default
for a reason; compliance is on you.

## Related

- 🤖 [**telegram_setter_bot**](https://github.com/mohamed-amine-ben-mallessa/telegram_setter_bot) — a 6-stage sales funnel for your Telegram DMs.
- 🦅 [**mysetterbot-claw**](https://github.com/mohamed-amine-ben-mallessa/mysetterbot-claw) — the same outreach idea for Instagram, as 42 MCP tools.

## License

MIT — see [LICENSE](LICENSE).

> Not affiliated with or endorsed by Telegram. "Telegram" is a trademark of its owner.

---

<p align="center">
  <sub>Built by <a href="https://github.com/mohamed-amine-ben-mallessa">Mohamed Amine Ben Mallessa</a> · ⭐ star it if you stopped copy-pasting bot plumbing</sub>
</p>
