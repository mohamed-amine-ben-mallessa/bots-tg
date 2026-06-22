"""CRM Airtable : définition des 6 tables, /setup (création via API), CRUD.

Le schéma (TABLES) est la source de vérité ; `setup()` crée les tables
manquantes dans la base via l'API Meta d'Airtable (scope schema.bases:write).
Le CRUD (upsert avec dédoublonnage) écrit les Contacts/Entreprises issus d'Exa
et gère ICP/Requêtes/Campagnes/Emails.

Config via .env : AIRTABLE_TOKEN, AIRTABLE_BASE_ID.
"""

import os

import httpx

API = "https://api.airtable.com/v0"
META = "https://api.airtable.com/v0/meta/bases"


class CRMError(RuntimeError):
    pass


# ── Définition des tables (format API Meta Airtable) ──────────────────────────
# Chaque table : nom + champs (name, type, options). Les liens (Link to another
# record) sont créés en 2 passes car ils référencent d'autres tables.

def _select(options):
    return {"choices": [{"name": o} for o in options]}


TABLES = {
    "Marques": [
        {"name": "Nom", "type": "singleLineText"},
        {"name": "Site", "type": "url"},
        {"name": "Produits", "type": "multilineText"},
        {"name": "Signature", "type": "multilineText"},
        {"name": "Logo URL", "type": "url"},
        {"name": "SMTP from", "type": "singleLineText"},
        {"name": "SMTP host", "type": "singleLineText"},
        {"name": "SMTP user", "type": "singleLineText"},
        {"name": "Active", "type": "checkbox", "options": {
            "icon": "check", "color": "greenBright"}},
    ],
    "Contacts": [
        {"name": "Marque", "type": "singleLineText"},
        {"name": "Nom", "type": "singleLineText"},
        {"name": "Prénom", "type": "singleLineText"},
        {"name": "Poste actuel", "type": "singleLineText"},
        {"name": "Entreprise actuelle", "type": "singleLineText"},
        {"name": "Lieu", "type": "singleLineText"},
        {"name": "LinkedIn", "type": "url"},
        {"name": "Parcours", "type": "multilineText"},
        {"name": "Formation", "type": "multilineText"},
        {"name": "Email", "type": "email"},
        {"name": "Téléphone", "type": "phoneNumber"},
        {"name": "Résumé", "type": "multilineText"},
        {"name": "Notes", "type": "multilineText"},
        {"name": "Tags", "type": "multipleSelects", "options": _select(
            ["Prioritaire", "À recontacter", "VIP", "Concurrent"])},
        {"name": "Statut", "type": "singleSelect", "options": _select(
            ["Nouveau", "Contacté", "Relancé", "Répondu", "Gagné", "Perdu"])},
        {"name": "Score ICP", "type": "number", "options": {"precision": 0}},
        {"name": "Coût$", "type": "number", "options": {"precision": 4}},
    ],
    "Entreprises": [
        {"name": "Marque", "type": "singleLineText"},
        {"name": "Nom", "type": "singleLineText"},
        {"name": "Site", "type": "url"},
        {"name": "Description", "type": "multilineText"},
        {"name": "Secteur", "type": "singleLineText"},
        {"name": "Année création", "type": "number", "options": {"precision": 0}},
        {"name": "Effectif", "type": "number", "options": {"precision": 0}},
        {"name": "Ville", "type": "singleLineText"},
        {"name": "Pays", "type": "singleLineText"},
        {"name": "CA annuel", "type": "number", "options": {"precision": 0}},
        {"name": "Financement total", "type": "number", "options": {"precision": 0}},
        {"name": "Dernière levée", "type": "singleLineText"},
        {"name": "Visites/mois", "type": "number", "options": {"precision": 0}},
        {"name": "Résumé", "type": "multilineText"},
        {"name": "Notes", "type": "multilineText"},
        {"name": "Tags", "type": "multipleSelects", "options": _select(
            ["Cible", "Client", "Concurrent", "Partenaire"])},
        {"name": "Coût$", "type": "number", "options": {"precision": 4}},
    ],
    "ICP": [
        {"name": "Marque", "type": "singleLineText"},
        {"name": "Produit", "type": "singleLineText"},
        {"name": "Nom", "type": "singleLineText"},
        {"name": "Description", "type": "multilineText"},
        {"name": "Postes cibles", "type": "multilineText"},
        {"name": "Secteurs", "type": "multilineText"},
        {"name": "Lieux", "type": "multilineText"},
        {"name": "Taille entreprise", "type": "singleLineText"},
        {"name": "Mots-clés requête", "type": "multilineText"},
        {"name": "Actif", "type": "checkbox", "options": {
            "icon": "check", "color": "greenBright"}},
    ],
    "Requêtes": [
        {"name": "Libellé", "type": "singleLineText"},
        {"name": "Texte requête", "type": "multilineText"},
        {"name": "Type", "type": "singleSelect", "options": _select(
            ["people", "company", "answer"])},
        {"name": "Dernière exécution", "type": "dateTime", "options": {
            "dateFormat": {"name": "iso"}, "timeFormat": {"name": "24hour"},
            "timeZone": "Europe/Paris"}},
        {"name": "Nb résultats", "type": "number", "options": {"precision": 0}},
        {"name": "Coût cumulé$", "type": "number", "options": {"precision": 4}},
        {"name": "Planifiée", "type": "checkbox", "options": {
            "icon": "check", "color": "blueBright"}},
    ],
    "Campagnes": [
        {"name": "Marque", "type": "singleLineText"},
        {"name": "Nom", "type": "singleLineText"},
        {"name": "Objet email", "type": "singleLineText"},
        {"name": "Corps email", "type": "multilineText"},
        {"name": "Signature", "type": "multilineText"},
        {"name": "URL produit", "type": "url"},
        {"name": "Image bannière", "type": "url"},
        {"name": "Logo URL", "type": "url"},
        {"name": "Format", "type": "singleSelect", "options": _select(
            ["Texte", "HTML"])},
        {"name": "Approche", "type": "singleSelect", "options": _select(
            ["Cold", "Relance", "Promotion", "Nurture"])},
        {"name": "Statut", "type": "singleSelect", "options": _select(
            ["Brouillon", "Active", "Pausée", "Terminée"])},
        {"name": "Délai relance (jours)", "type": "number", "options": {"precision": 0}},
        {"name": "Nb relances max", "type": "number", "options": {"precision": 0}},
    ],
    "Emails envoyés": [
        {"name": "Objet", "type": "singleLineText"},
        {"name": "Corps", "type": "multilineText"},
        {"name": "Type", "type": "singleSelect", "options": _select(
            ["Initial", "Relance 1", "Relance 2"])},
        {"name": "Statut", "type": "singleSelect", "options": _select(
            ["Brouillon", "Envoyé", "Échec", "Ouvert", "Répondu"])},
        {"name": "Envoyé le", "type": "dateTime", "options": {
            "dateFormat": {"name": "iso"}, "timeFormat": {"name": "24hour"},
            "timeZone": "Europe/Paris"}},
        {"name": "Erreur", "type": "multilineText"},
    ],
}

# Liens entre tables, créés en 2e passe (Link to another record).
LIENS = [
    ("Contacts", "Requête source", "Requêtes"),
    ("Contacts", "Entreprise (lien)", "Entreprises"),
    ("Entreprises", "Requête source", "Requêtes"),
    ("Requêtes", "ICP", "ICP"),
    ("Campagnes", "Cibles", "Contacts"),
    ("Emails envoyés", "Contact", "Contacts"),
    ("Emails envoyés", "Campagne", "Campagnes"),
]


# ── Client bas niveau ─────────────────────────────────────────────────────────

class CRM:
    def __init__(self, token=None, base_id=None):
        self.token = (token or os.environ.get("AIRTABLE_TOKEN", "")).strip()
        self.base = (base_id or os.environ.get("AIRTABLE_BASE_ID", "")).strip()
        if not self.token or not self.base:
            raise CRMError("AIRTABLE_TOKEN et AIRTABLE_BASE_ID requis.")
        self._h = {"Authorization": f"Bearer {self.token}",
                   "Content-Type": "application/json"}
        self._client = httpx.Client(timeout=30)
        self._ids = {}        # nom table -> tableId (cache)

    # ── meta / setup ──────────────────────────────────────────────────────────

    def lister_tables(self):
        """{nom: tableId} des tables existantes (scope schema.bases:read)."""
        r = self._client.get(f"{META}/{self.base}/tables", headers=self._h)
        if r.status_code != 200:
            raise CRMError(f"Lecture schéma échouée ({r.status_code}) : {r.text[:200]}")
        return {t["name"]: t["id"] for t in r.json().get("tables", [])}

    def _champs_par_table(self):
        """{nom_table: set(noms_de_champs)} pour détecter les colonnes manquantes."""
        r = self._client.get(f"{META}/{self.base}/tables", headers=self._h)
        if r.status_code != 200:
            raise CRMError(f"Lecture schéma échouée ({r.status_code}) : {r.text[:200]}")
        return {t["name"]: {f["name"] for f in t.get("fields", [])}
                for t in r.json().get("tables", [])}

    def _creer_table(self, nom, champs):
        payload = {"name": nom, "fields": champs}
        r = self._client.post(f"{META}/{self.base}/tables", headers=self._h,
                              json=payload)
        if r.status_code not in (200, 201):
            raise CRMError(f"Création table « {nom} » échouée "
                           f"({r.status_code}) : {r.text[:250]}")
        return r.json()["id"]

    def _ajouter_champ(self, table_id, champ):
        r = self._client.post(f"{META}/{self.base}/tables/{table_id}/fields",
                              headers=self._h, json=champ)
        # 422 = champ déjà existant : on ignore.
        if r.status_code not in (200, 201, 422):
            raise CRMError(f"Ajout champ « {champ['name']} » échoué "
                           f"({r.status_code}) : {r.text[:200]}")

    def setup(self):
        """Crée les tables manquantes + leurs liens. Idempotent.

        Renvoie un rapport {table: 'créée'|'existait'}.
        """
        rapport = {}
        champs_existants = self._champs_par_table()
        # Passe 1 : tables manquantes + champs manquants sur les tables existantes.
        for nom, champs in TABLES.items():
            if nom not in champs_existants:
                self._creer_table(nom, champs)
                rapport[nom] = "créée"
            else:
                # Ajoute les colonnes manquantes (ex. nouvelle colonne Marque).
                deja = champs_existants[nom]
                ajoutes = 0
                tid = self.lister_tables()[nom]
                for ch in champs:
                    if ch["name"] not in deja:
                        self._ajouter_champ(tid, ch)
                        ajoutes += 1
                rapport[nom] = f"+{ajoutes} champ(s)" if ajoutes else "à jour"
        # Rafraîchir les IDs (les nouvelles tables ont un id maintenant).
        self._ids = self.lister_tables()
        # Passe 2 : champs de liaison.
        for table, champ, cible in LIENS:
            tid = self._ids.get(table)
            cid = self._ids.get(cible)
            if not tid or not cid:
                continue
            self._ajouter_champ(tid, {
                "name": champ, "type": "multipleRecordLinks",
                "options": {"linkedTableId": cid},
            })
        return rapport

    # ── CRUD records ──────────────────────────────────────────────────────────

    def _table_id(self, nom):
        if not self._ids:
            self._ids = self.lister_tables()
        tid = self._ids.get(nom)
        if not tid:
            raise CRMError(f"Table « {nom} » absente. Lance /setup.")
        return tid

    def creer(self, table, fields):
        """Crée un record. Renvoie son id."""
        tid = self._table_id(table)
        r = self._client.post(f"{API}/{self.base}/{tid}", headers=self._h,
                              json={"fields": fields})
        if r.status_code not in (200, 201):
            raise CRMError(f"Création record ({table}) échouée "
                           f"({r.status_code}) : {r.text[:200]}")
        return r.json()["id"]

    def creer_lot(self, table, liste_fields):
        """Crée plusieurs records (par lots de 10, limite Airtable). Renvoie le nb."""
        tid = self._table_id(table)
        total = 0
        for i in range(0, len(liste_fields), 10):
            lot = [{"fields": f} for f in liste_fields[i:i + 10]]
            r = self._client.post(f"{API}/{self.base}/{tid}", headers=self._h,
                                  json={"records": lot})
            if r.status_code not in (200, 201):
                raise CRMError(f"Création lot ({table}) échouée "
                               f"({r.status_code}) : {r.text[:200]}")
            total += len(r.json().get("records", []))
        return total

    def lister(self, table, formula=None, max_records=100):
        """Liste des records {id, fields}. `formula` = filterByFormula optionnel."""
        tid = self._table_id(table)
        params = {"maxRecords": max_records, "pageSize": 100}
        if formula:
            params["filterByFormula"] = formula
        out, offset = [], None
        while True:
            if offset:
                params["offset"] = offset
            r = self._client.get(f"{API}/{self.base}/{tid}", headers=self._h,
                                 params=params)
            if r.status_code != 200:
                raise CRMError(f"Lecture ({table}) échouée "
                               f"({r.status_code}) : {r.text[:200]}")
            d = r.json()
            out.extend(d.get("records", []))
            offset = d.get("offset")
            if not offset or len(out) >= max_records:
                break
        return out

    def maj(self, table, record_id, fields):
        tid = self._table_id(table)
        r = self._client.patch(f"{API}/{self.base}/{tid}/{record_id}",
                              headers=self._h, json={"fields": fields})
        if r.status_code != 200:
            raise CRMError(f"MAJ record ({table}) échouée "
                           f"({r.status_code}) : {r.text[:200]}")
        return r.json()["id"]

    def upsert_contacts(self, contacts, cout=None, marque=""):
        """Insère des Contacts en évitant les doublons (par LinkedIn ou Nom).

        `marque` (optionnel) tague chaque contact ajouté. Renvoie (ajoutés, ignorés).
        """
        existants = self.lister("Contacts", max_records=1000)
        vus = set()
        for rec in existants:
            f = rec.get("fields", {})
            vus.add((f.get("LinkedIn") or "").lower())
            vus.add((f.get("Nom") or "").lower())
        a_creer, ignores = [], 0
        for c in contacts:
            cle = (c.linkedin or "").lower() or (c.nom or "").lower()
            if cle and cle in vus:
                ignores += 1
                continue
            vus.add(cle)
            rec = c.airtable(cout=cout)
            if marque:
                rec["Marque"] = marque
            a_creer.append(rec)
        ajoutes = self.creer_lot("Contacts", a_creer) if a_creer else 0
        return ajoutes, ignores

    def upsert_entreprises(self, entreprises, cout=None, marque=""):
        existants = self.lister("Entreprises", max_records=1000)
        vus = set()
        for rec in existants:
            f = rec.get("fields", {})
            vus.add((f.get("Site") or "").lower())
            vus.add((f.get("Nom") or "").lower())
        a_creer, ignores = [], 0
        for e in entreprises:
            cle = (e.site or "").lower() or (e.nom or "").lower()
            if cle and cle in vus:
                ignores += 1
                continue
            vus.add(cle)
            rec = e.airtable(cout=cout)
            if marque:
                rec["Marque"] = marque
            a_creer.append(rec)
        ajoutes = self.creer_lot("Entreprises", a_creer) if a_creer else 0
        return ajoutes, ignores

    def trouver_contact(self, nom):
        """Renvoie (record_id, fields) du 1er contact dont le Nom matche, ou None."""
        nom = (nom or "").strip().lower()
        for rec in self.lister("Contacts", max_records=1000):
            if (rec.get("fields", {}).get("Nom") or "").lower() == nom:
                return rec["id"], rec["fields"]
        return None

    def maj_email_contact(self, record_id, email, statut, score, date_iso):
        """Met à jour l'email vérifié d'un contact (après enrichissement)."""
        return self.maj("Contacts", record_id, {
            "Email": email, "Email statut": statut,
            "Email score": int(score or 0), "Email vérifié le": date_iso,
        })

    def close(self):
        self._client.close()
