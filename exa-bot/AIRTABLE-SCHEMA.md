# Schéma Airtable — CRM de prospection EXO

> À valider avant le code. Ce schéma est le **contrat** dont dépendent tout le
> reste (recherche, ICP, campagnes, mailing). Crée ces 6 tables dans une base
> Airtable, avec un token (scopes `data.records:read`, `data.records:write`,
> `schema.bases:read`). Les noms de colonnes ci-dessous doivent matcher
> exactement (le bot écrit dessus).

## Vue d'ensemble (6 tables liées)

```
ICP ───┐
       ├──< Requêtes >──< Contacts >──┐
       │                              ├──< Emails envoyés
       └──< Entreprises >─────────────┘
                                  Campagnes >──< Emails envoyés
```

Une **Requête** appartient à un **ICP** ; elle produit des **Contacts** et des
**Entreprises** (résultats Exa). Une **Campagne** vise des Contacts et génère
des **Emails envoyés** (suivi des relances).

---

## 1. `Contacts` (people search)

Champs issus de l'API Exa people (`entities.properties`) :

| Colonne | Type Airtable | Source Exa |
|---|---|---|
| Nom | Single line text | `name` |
| Prénom | Single line text | `firstName` |
| Poste actuel | Single line text | `workHistory[0].title` |
| Entreprise actuelle | Single line text | `workHistory[0].company.name` |
| Lieu | Single line text | `location` |
| LinkedIn | URL | `url` |
| Parcours | Long text | `workHistory` formaté (postes + dates) |
| Formation | Long text | `educationHistory` formaté |
| Email | Email | enrichissement Exa ($0.02) / manuel |
| Téléphone | Phone | enrichissement Exa ($0.07) / manuel |
| Résumé | Long text | highlight / summary |
| Notes | Long text | libre |
| Tags | Multiple select | libre (à chaud) |
| Requête source | Link → Requêtes | requête qui l'a trouvé |
| Entreprise (lien) | Link → Entreprises | si matchée |
| Statut | Single select | Nouveau · Contacté · Relancé · Répondu · Gagné · Perdu |
| Score ICP | Number | calculé vs l'ICP |
| Coût$ | Number (decimal) | `costDollars.total` de la requête |
| Ajouté le | Created time | auto |

## 2. `Entreprises` (company search)

Champs issus de l'API Exa company :

| Colonne | Type | Source Exa |
|---|---|---|
| Nom | Single line text | `name` |
| Site | URL | `website` / `url` |
| Description | Long text | `description` |
| Secteur | Single line text | `industry` / `category` |
| Année création | Number | `foundedYear` |
| Effectif | Number | `workforce.total` |
| Ville | Single line text | `headquarters.city` |
| Pays | Single line text | `headquarters.country` |
| CA annuel | Number | `financials.revenueAnnual` |
| Financement total | Number | `financials.fundingTotal` |
| Dernière levée | Single line text | `financials.fundingLatestRound` (name + amount) |
| Visites/mois | Number | `webTraffic.visitsMonthly` |
| Requête source | Link → Requêtes | |
| Contacts | Link → Contacts | (rollup) |
| Coût$ | Number | |
| Ajouté le | Created time | |

## 3. `ICP` (profils de client idéal)

| Colonne | Type | Rôle |
|---|---|---|
| Nom | Single line text | ex. « SaaS Series A France » |
| Description | Long text | définition libre |
| Postes cibles | Long text | titres recherchés (séparés par virgule) |
| Secteurs | Long text | industries cibles |
| Lieux | Long text | zones géo |
| Taille entreprise | Single line text | ex. « 11-50 », « 50-200 » |
| Mots-clés requête | Long text | base des requêtes Exa générées |
| Requêtes | Link → Requêtes | |
| Actif | Checkbox | |

## 4. `Requêtes` (requêtes prédéfinies + suivi)

| Colonne | Type | Rôle |
|---|---|---|
| Libellé | Single line text | nom court |
| Texte requête | Long text | la requête Exa réelle |
| Type | Single select | people · company · answer |
| ICP | Link → ICP | |
| Dernière exécution | Date | suivi |
| Nb résultats | Number | dernier run |
| Coût cumulé$ | Number | somme des runs |
| Contacts | Link → Contacts | |
| Entreprises | Link → Entreprises | |
| Planifiée | Checkbox | à relancer périodiquement |

## 5. `Campagnes` (mailing + relances)

| Colonne | Type | Rôle |
|---|---|---|
| Nom | Single line text | ex. « Promo produit X — janv. » |
| Objet email | Single line text | sujet (avec variables) |
| Corps email | Long text | template (variables `{prenom}` etc.) |
| Signature | Long text | bloc signature |
| URL produit | URL | lien promu |
| Image bannière | URL | image hébergée (haut de l'email HTML) |
| Logo URL | URL | logo hébergé (signature / en-tête) |
| Format | Single select | Texte · HTML (images visibles si HTML) |
| Approche | Single select | Cold · Relance · Promotion · Nurture |
| Statut | Single select | Brouillon · Active · Pausée · Terminée |
| Délai relance (jours) | Number | ex. 3 |
| Nb relances max | Number | ex. 2 |
| Cibles | Link → Contacts | |
| Emails envoyés | Link → Emails envoyés | |

## 6. `Emails envoyés` (journal des envois + relances)

| Colonne | Type | Rôle |
|---|---|---|
| Contact | Link → Contacts | destinataire |
| Campagne | Link → Campagnes | |
| Objet | Single line text | objet final (variables résolues) |
| Corps | Long text | corps final envoyé |
| Type | Single select | Initial · Relance 1 · Relance 2 |
| Statut | Single select | Brouillon · Envoyé · Échec · Ouvert · Répondu |
| Envoyé le | Date | |
| Erreur | Long text | si échec SMTP |

---

## Variables d'email configurables

Les templates (objet, corps, signature) acceptent ces variables, résolues par
contact + campagne :

| Variable | Source |
|---|---|
| `{prenom}` `{nom}` | Contact |
| `{poste}` `{entreprise}` | Contact |
| `{lieu}` | Contact |
| `{url_produit}` | Campagne |
| `{signature}` | Campagne |
| `{image_url}` | Campagne (image bannière hébergée) |
| `{logo_url}` | Campagne (logo hébergé) |
| `{expediteur}` | config SMTP (.env) |

> 🖼️ **Images dans les emails** : on n'attache pas les images, on **référence
> des URLs hébergées** (`<img src="{image_url}">`). En email HTML, le client du
> destinataire charge l'image depuis l'URL. Les variables `{image_url}` /
> `{logo_url}` viennent des colonnes Campagne (Image bannière / Logo URL).

Exemple de corps :
```
Bonjour {prenom},

Je vois que vous êtes {poste} chez {entreprise} — votre travail sur […] m'a
marqué. On a construit {url_produit} qui aide les équipes comme la vôtre à […].

Ouvert à un échange de 15 min cette semaine ?

{signature}
```

## SMTP / IMAP (.env) — avec garde-fous

OVH (SSL) — port 465 = SMTP_SSL (chiffré d'emblée) ; IMAP 993 pour détecter les
réponses (marquer « Répondu » et stopper les relances).

```
SMTP_HOST=ssl0.ovh.net
SMTP_PORT=465            # 465 = SSL implicite (SMTP_SSL)
SMTP_USER=toi@domaine.com
SMTP_PASS=mot-de-passe-application   # ⚠️ utiliser un mdp d'application dédié
SMTP_FROM=Ton Nom <toi@domaine.com>
IMAP_HOST=ssl0.ovh.net  # optionnel : détection des réponses
IMAP_PORT=993
MAIL_DRY_RUN=true        # true = ne PAS envoyer (brouillon), false = envoyer
MAIL_QUOTA_JOUR=50       # plafond d'envois / jour
```

Garde-fous prévus : **dry-run par défaut**, **confirmation explicite** avant un
envoi réel, **quota/jour**, et envoi à une **liste de test** d'abord.

---

## Flux complet visé

1. `/icp_add` → crée un ICP (postes, secteurs, lieux).
2. `/requete_add` → requête prédéfinie liée à un ICP (people/company/answer).
3. `/run <requête>` → exécute Exa, écrit Contacts/Entreprises dans Airtable
   (dédup), met à jour le suivi + coût.
4. `/enrich <contact>` → Exa **Answer** pour enrichir (ex. email, actualité,
   accroche personnalisée).
5. `/campagne_add` → template (objet/corps/signature/url produit/approche).
6. `/envoyer <campagne>` → résout les variables par contact, **dry-run** affiche
   les brouillons ; confirmation → envoi SMTP (quota), journalise dans Emails.
7. `/relancer <campagne>` → renvoie aux non-répondants après le délai.
8. `/export <table> [filtre]` → CSV sélectif téléchargeable.

> ⚠️ **À confirmer avant que je code** : les noms de tables/colonnes ci-dessus,
> et si tu veux que je crée ces tables **via l'API** (si ton token a
> `schema.bases:write`) ou si tu les crées à la main dans Airtable.
```
