# Exa Bot

Bot Telegram de recherche de **personnes** et d'**entreprises** sur le web, via
l'API [Exa](https://exa.ai), avec sauvegarde dans **Airtable**. Construit sur le
socle [`botkit`](../botkit).

## Commandes

- `/people <requête>` — ex. `/people VP Engineering AI startups San Francisco`
- `/company <requête>` — ex. `/company agtech companies US série A`
- `/help`

Sous chaque résultat : **🔗 lien** (LinkedIn / site) · **💾 Airtable**.
Navigation : **◀️ Page X/N ▶️** (5 résultats/page).

## Démarrage

```bash
cp .env.example .env          # TELEGRAM_*, EXA_API_KEY, (AIRTABLE_* optionnel)
pip install -r requirements.txt
python bot.py
```

Ou en Docker (depuis ce dossier) :

```bash
docker compose up -d --build
docker compose logs -f
```

## Ce que le bot contient (et ce qu'il n'a pas à refaire)

| Fichier | Rôle |
|---|---|
| `source.py` | wrappe `exa-py` (people + company) → `Item` normalisés |
| `render.py` | `Item` → message HTML + boutons |
| `bot.py` | câblage des commandes sur `botkit` |

Tout le reste — polling robuste, pagination, dispatch, écriture Airtable — vient
de `botkit`. Adapter le mapping Airtable : voir `Item.airtable_record()` dans
`source.py` (les noms de colonnes doivent matcher ta table).
