# Image d'exa-bot. À builder depuis le dossier PARENT (bots-tg/) pour inclure
# botkit :  docker build -f exa-bot/Dockerfile -t exa-bot .
FROM python:3.12-slim

WORKDIR /app

# Dépendances du bot.
COPY exa-bot/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Le socle partagé + le code du bot.
COPY botkit/ ./botkit/
COPY exa-bot/*.py ./

CMD ["python", "bot.py"]
