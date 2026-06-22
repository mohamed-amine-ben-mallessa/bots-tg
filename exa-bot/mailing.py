"""Mailing : rendu de templates (variables + images) et envoi SMTP avec garde-fous.

Rendu : remplace {prenom}, {poste}, {entreprise}, {url_produit}, {image_url},
{logo_url}, {signature}, {expediteur}… dans l'objet et le corps. Le corps peut
être en Texte ou en HTML (les images hébergées s'affichent via <img src=...>).

Garde-fous d'envoi :
  • MAIL_DRY_RUN=true (défaut) : ne PAS envoyer, renvoie le brouillon.
  • MAIL_QUOTA_JOUR : plafond d'envois par jour (compteur persistant).
  • OVH SSL port 465 -> SMTP_SSL (connexion chiffrée d'emblée).
"""

import email as _email
import imaplib
import os
import re as _re
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


class MailError(RuntimeError):
    pass


class _Tol(dict):
    """format_map tolérant : une variable inconnue est laissée telle quelle."""
    def __missing__(self, k):
        return "{" + k + "}"


def variables(contact_fields, campagne_fields, expediteur=""):
    """Construit le dict de variables depuis un Contact et une Campagne (fields)."""
    c, k = contact_fields or {}, campagne_fields or {}
    return {
        "prenom": c.get("Prénom") or (c.get("Nom") or "").split(" ")[0],
        "nom": c.get("Nom", ""),
        "poste": c.get("Poste actuel", ""),
        "entreprise": c.get("Entreprise actuelle", ""),
        "lieu": c.get("Lieu", ""),
        "email": c.get("Email", ""),
        "url_produit": k.get("URL produit", ""),
        "image_url": k.get("Image bannière", ""),
        "logo_url": k.get("Logo URL", ""),
        "signature": k.get("Signature", ""),
        "expediteur": expediteur,
    }


def rendre(template, vars_):
    return (template or "").format_map(_Tol(vars_)).strip()


def corps_html(corps_rendu, vars_):
    """Enveloppe le corps en HTML, avec bannière/logo si fournis.

    `corps_rendu` peut déjà contenir du HTML ; sinon les sauts de ligne sont
    convertis en <br>. La bannière s'affiche en haut, le logo près de la
    signature.
    """
    img = vars_.get("image_url", "")
    logo = vars_.get("logo_url", "")
    banniere = (f'<img src="{img}" alt="" style="max-width:100%;height:auto;'
                f'margin-bottom:16px;">' if img else "")
    logo_html = (f'<br><img src="{logo}" alt="" style="max-height:48px;'
                 f'margin-top:12px;">' if logo else "")
    if "<" not in corps_rendu:                       # texte brut -> <br>
        corps_rendu = corps_rendu.replace("\n", "<br>")
    return (
        '<div style="font-family:Arial,sans-serif;font-size:14px;'
        'color:#222;line-height:1.5;max-width:600px;">'
        f"{banniere}{corps_rendu}{logo_html}</div>")


def composer(contact_fields, campagne_fields, expediteur):
    """Renvoie (objet_rendu, corps_rendu, html_ou_none).

    Si la campagne est en Format=HTML, le 3e élément est le corps HTML ; sinon None.
    """
    v = variables(contact_fields, campagne_fields, expediteur)
    objet = rendre(campagne_fields.get("Objet email", ""), v)
    corps = rendre(campagne_fields.get("Corps email", ""), v)
    sig = v.get("signature", "")
    if sig:
        corps = f"{corps}\n\n{rendre(sig, v)}"
    html = None
    if (campagne_fields.get("Format") or "").lower() == "html":
        html = corps_html(corps, v)
    return objet, corps, html


# ── Configuration SMTP ────────────────────────────────────────────────────────

def config_smtp():
    return {
        "host": os.environ.get("SMTP_HOST", "").strip(),
        "port": int(os.environ.get("SMTP_PORT", "465") or 465),
        "user": os.environ.get("SMTP_USER", "").strip(),
        "passwd": os.environ.get("SMTP_PASS", "").strip(),
        "from": os.environ.get("SMTP_FROM", "").strip()
                or os.environ.get("SMTP_USER", "").strip(),
    }


def smtp_pret():
    c = config_smtp()
    return all((c["host"], c["user"], c["passwd"]))


def dry_run():
    return os.environ.get("MAIL_DRY_RUN", "true").lower() != "false"


def quota_jour():
    try:
        return int(os.environ.get("MAIL_QUOTA_JOUR", "50"))
    except ValueError:
        return 50


# ── Envoi ─────────────────────────────────────────────────────────────────────

def envoyer(destinataire, objet, corps_texte, corps_html=None, cfg=None):
    """Envoie un email via SMTP (OVH SSL 465). Lève MailError en cas d'échec.

    N'effectue AUCUN garde-fou ici (dry-run/quota) : c'est l'appelant (le bot)
    qui décide d'appeler ou non, après confirmation. Cette fonction envoie pour
    de vrai.
    """
    cfg = cfg or config_smtp()
    if not (cfg["host"] and cfg["user"] and cfg["passwd"]):
        raise MailError("Config SMTP incomplète (SMTP_HOST/USER/PASS).")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = objet
    msg["From"] = cfg["from"]
    msg["To"] = destinataire
    msg.attach(MIMEText(corps_texte, "plain", "utf-8"))
    if corps_html:
        msg.attach(MIMEText(corps_html, "html", "utf-8"))
    try:
        if cfg["port"] == 465:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(cfg["host"], cfg["port"], context=ctx,
                                  timeout=30) as s:
                s.login(cfg["user"], cfg["passwd"])
                s.sendmail(cfg["from"], [destinataire], msg.as_string())
        else:                                         # 587 -> STARTTLS
            with smtplib.SMTP(cfg["host"], cfg["port"], timeout=30) as s:
                s.starttls(context=ssl.create_default_context())
                s.login(cfg["user"], cfg["passwd"])
                s.sendmail(cfg["from"], [destinataire], msg.as_string())
    except Exception as e:
        raise MailError(f"Échec SMTP : {e}") from e
    return True


# ── IMAP : détection des réponses (pour les relances) ─────────────────────────

def config_imap():
    return {
        "host": os.environ.get("IMAP_HOST", "").strip()
                or os.environ.get("SMTP_HOST", "").strip(),
        "port": int(os.environ.get("IMAP_PORT", "993") or 993),
        "user": os.environ.get("SMTP_USER", "").strip(),
        "passwd": os.environ.get("SMTP_PASS", "").strip(),
    }


def imap_pret():
    c = config_imap()
    return all((c["host"], c["user"], c["passwd"]))


_ADDR_RE = _re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def expediteurs_recents(jours=30, dossier="INBOX", cfg=None):
    """Renvoie l'ensemble des adresses email ayant écrit dans la boîte récemment.

    Sert à détecter qui a « répondu » : si un contact d'une campagne est dans
    cet ensemble, on marque « Répondu » et on ne le relance pas.
    """
    import datetime as _d
    cfg = cfg or config_imap()
    if not (cfg["host"] and cfg["user"] and cfg["passwd"]):
        raise MailError("Config IMAP incomplète (IMAP_HOST/SMTP_USER/PASS).")
    depuis = (_d.date.today() - _d.timedelta(days=jours)).strftime("%d-%b-%Y")
    adresses = set()
    try:
        m = imaplib.IMAP4_SSL(cfg["host"], cfg["port"])
        m.login(cfg["user"], cfg["passwd"])
        m.select(dossier, readonly=True)
        typ, data = m.search(None, f'(SINCE {depuis})')
        if typ == "OK":
            ids = data[0].split()
            for num in ids[-500:]:                  # plafond raisonnable
                t, d = m.fetch(num, "(BODY[HEADER.FIELDS (FROM)])")
                if t != "OK" or not d or not d[0]:
                    continue
                brut = d[0][1].decode("utf-8", "replace")
                for a in _ADDR_RE.findall(brut):
                    adresses.add(a.lower())
        m.logout()
    except Exception as e:
        raise MailError(f"Échec IMAP : {e}") from e
    return adresses
