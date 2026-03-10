import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import icalendar
import recurring_ical_events
from google.oauth2 import service_account
from googleapiclient.discovery import build
import datetime
import os
import sys
import hashlib
import re
import json
import logging
import argparse
import email
import ssl
from email.header import decode_header
from imapclient import IMAPClient
from zoneinfo import ZoneInfo

__version__ = "5.0.0"

# --- Optionnel : charger .env en local ---
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # En Docker, les vars sont injectées via --env-file

# --- CONFIGURATION LOGGING ---
PARIS_TZ = ZoneInfo('Europe/Paris')
UTC_TZ = ZoneInfo('UTC')

class ParisFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        ct = datetime.datetime.fromtimestamp(record.created, tz=PARIS_TZ)
        if datefmt:
            return ct.strftime(datefmt)
        return ct.strftime("%Y-%m-%d %H:%M:%S")

logger = logging.getLogger('unicaen-sync')
logger.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(ParisFormatter('[%(asctime)s] %(message)s'))
logger.addHandler(handler)

# --- CONFIGURATION ---
ICS_URL = os.getenv("ICS_URL")
USERNAME = os.getenv("ENT_USER")
PASSWORD = os.getenv("ENT_PASS")
CALENDAR_ID = os.getenv("CALENDAR_ID")
SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_PKEY_PATH", 'credentials.json')
MAPPING_FILE = 'mapping.json'
MISSING_LOG_FILE = 'missing_subjects.txt'
OVERRIDES_FILE = '.overrides.json'
MAIL_SYNC_STATE_FILE = '.mail_sync_state'

IMAP_SERVER = os.getenv("IMAP_SERVER")
IMAP_USER = os.getenv("IMAP_USER")
IMAP_PASS = os.getenv("IMAP_PASS")

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

# Gestion Hack Ecampus
show_hack_env = os.getenv("SHOW_HACK_CAMPUS", "true").lower()
SHOW_HACK_CAMPUS = show_hack_env in ["true", "1", "yes", "on"]

SPECIAL_KEYWORDS = [
    "HACK", "SORTIE", "VISITE", "CONFÉRENCE", "ATELIER",
    "FORUM", "RENCONTRE", "JPO", "SALON", "DÉFI", "CHALLENGE",
    "RÉUNION DE RENTRÉE", "PETIT DÉJEUNER", "SHOOTING", "OUVERTURE"
]

# Couleurs Google Calendar par type
COLOR_EXAMEN = "11"    # Tomate (rouge)
COLOR_SPECIAL = "8"    # Graphite (gris)
COLOR_DEFAULT = "9"    # Myrtille (bleu)


# =============================================================================
#  FONCTIONS UTILITAIRES
# =============================================================================

def normalize_str(s):
    """Normalise une chaîne pour comparaison stable (retours chariot, espaces)."""
    return s.replace('\r\n', '\n').strip() if s else ""


def _imap_connect():
    """Crée une connexion IMAP avec SSL désactivé (certificat auto-signé Unicaen)."""
    # NOTE: La vérification SSL est désactivée volontairement car le serveur
    # Zimbra/ZCS d'Unicaen utilise un certificat auto-signé.
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return IMAPClient(IMAP_SERVER, use_uid=True, ssl=True, ssl_context=ctx)


def _read_last_uid():
    """Lit le dernier UID et UIDVALIDITY IMAP traités depuis le fichier d'état."""
    if os.path.exists(MAIL_SYNC_STATE_FILE):
        try:
            with open(MAIL_SYNC_STATE_FILE, 'r') as f:
                data = json.load(f)
                return data.get("uid_validity", 0), data.get("last_uid", 0)
        except (ValueError, IOError):
            return 0, 0
    return 0, 0

def validate_config(check_imap=False):
    """Vérifie que toutes les variables d'environnement et fichiers requis sont présents."""
    if not all([ICS_URL, USERNAME, PASSWORD, CALENDAR_ID]):
        logger.critical("❌ CRITIQUE : Variables d'environnement manquantes (.env)")
        sys.exit(1)
    if check_imap and not all([IMAP_SERVER, IMAP_USER, IMAP_PASS]):
        logger.critical("❌ CRITIQUE : Variables IMAP manquantes pour l'usage du scraping mail.")
        sys.exit(1)
    if not os.path.exists(MAPPING_FILE):
        logger.critical(f"❌ CRITIQUE : Fichier '{MAPPING_FILE}' introuvable.")
        sys.exit(1)
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        logger.critical(f"❌ ERREUR : {SERVICE_ACCOUNT_FILE} introuvable.")
        sys.exit(1)

def check_new_imap_messages():
    """Vérifie s'il y a de nouveaux mails sans télécharger le calendrier entier."""
    uid_validity, last_uid = _read_last_uid()

    try:
        with _imap_connect() as server:
            server.login(IMAP_USER, IMAP_PASS)
            folder_info = server.select_folder('INBOX')
            current_validity = folder_info.get(b'UIDVALIDITY', 0)
            
            # Reset si changement de serveur/dossier
            if current_validity != uid_validity:
                uid_validity = current_validity
                last_uid = 0
            
            messages = server.search(['UID', f'{last_uid+1}:*']) if last_uid > 0 else server.search('ALL')
            messages = [uid for uid in messages if uid > last_uid]
            
            # Maj de l'état même si on s'arrête là
            if messages:
                with open(MAIL_SYNC_STATE_FILE, 'w') as f:
                    json.dump({"uid_validity": uid_validity, "last_uid": max(messages)}, f)
                return True
            return False
    except Exception as e:
        logger.error(f"❌ Erreur IMAP (fast check) : {e}")
        return False


def load_mapping():
    """Charge le dictionnaire de correspondance des matières (format riche)."""
    try:
        with open(MAPPING_FILE, 'r', encoding='utf-8') as f:
            mapping = json.load(f)
        logger.info(f"✅ Dictionnaire chargé : {len(mapping)} matières.")
        return mapping
    except json.JSONDecodeError as e:
        logger.critical(f"❌ CRITIQUE : Erreur de syntaxe JSON dans {MAPPING_FILE} : {e}")
        sys.exit(1)


def load_overrides():
    """Charge les dérogations locales issues des mails (nouveaux horaires, lieux)."""
    if not os.path.exists(OVERRIDES_FILE):
        return {}
    try:
        with open(OVERRIDES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"⚠️ Erreur de lecture de {OVERRIDES_FILE}: {e}")
        return {}


def save_overrides(overrides):
    """Sauvegarde les dérogations locales."""
    try:
        with open(OVERRIDES_FILE, 'w', encoding='utf-8') as f:
            json.dump(overrides, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logger.error(f"❌ Erreur de sauvegarde de {OVERRIDES_FILE}: {e}")


def send_discord_notification(title, description, color=16711680):
    """Envoie une notification Discord via Webhook si configuré."""
    if not DISCORD_WEBHOOK_URL:
        return

    payload = {
        "embeds": [{
            "title": title,
            "description": description,
            "color": color,
            "timestamp": datetime.datetime.now(UTC_TZ).isoformat()
        }]
    }

    try:
        requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=5)
    except Exception as e:
        logger.warning(f"⚠️ Échec de l'envoi de la notification Discord : {e}")

def download_ics():
    """Télécharge le fichier ICS depuis l'ENT avec retry automatique."""
    logger.info("📥 Connexion à l'ENT...")

    session = requests.Session()
    retries = Retry(total=3, backoff_factor=2, status_forcelist=[500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retries))

    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = session.get(
            ICS_URL, headers=headers,
            auth=requests.auth.HTTPBasicAuth(USERNAME, PASSWORD),
            timeout=30
        )
        response.raise_for_status()
        response.encoding = response.apparent_encoding if response.apparent_encoding else 'utf-8'
        logger.info(f"✅ Fichier ICS téléchargé ({len(response.text)} octets).")
        return response.text
    except Exception as e:
        logger.critical(f"❌ ERREUR TÉLÉCHARGEMENT : {e}")
        sys.exit(1)


def format_coefs(coefs):
    """Formate les coefficients en texte lisible avec emojis."""
    if not coefs:
        return ""
    
    lines = []
    total = 0
    for ue, val in coefs.items():
        lines.append(f"  📌 {ue} → coef {val}")
        total += val
    
    coef_text = "\n".join(lines)
    return f"\n\n📊 Coefficients :\n{coef_text}\n  ━━━━━━━━━━━━━━━\n  🏆 Total : {total}"


def enrich_description(raw_desc, cours_data, matched_code, is_first_of_day):
    """
    Transforme la description brute ICS en description enrichie avec emojis.
    
    Extrait : enseignant, groupe d'étudiants.
    Ajoute : ressource (code matière), coefficients.
    Ignore : salle (déjà dans location), groupe par activité.
    """
    desc = (raw_desc or "").strip()
    
    # Extraire les infos depuis la description brute (sets pour dédoublonner)
    enseignants_list = []
    groupes_list = []
    
    # Split sur vrais retours à la ligne ET sur \n littéraux
    lines = re.split(r'\n|\\n', desc)
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        line_lower = line.lower()
        
        # Lignes à IGNORER
        if line_lower.startswith("salle") or "groupe par activité" in line_lower or "groupes par activité" in line_lower:
            continue
        
        # Lignes à EXTRAIRE
        if line_lower.startswith("enseignant"):
            val = line.split(":", 1)[1].strip() if ":" in line else line
            if val and val not in enseignants_list:
                enseignants_list.append(val)
        elif "groupe d'étudiants" in line_lower or "groupes d'étudiants" in line_lower:
            val = line.split(":", 1)[1].strip() if ":" in line else line
            if val and val not in groupes_list:
                groupes_list.append(val)
    
    # Construction de la description enrichie
    parts = []
    
    if is_first_of_day:
        parts.append("🔔 Premier cours de la journée")
        parts.append("")
    
    if matched_code and cours_data:
        parts.append(f"📚 Ressource : {matched_code} — {cours_data.get('name', '')}")
    
    if enseignants_list:
        label = "Enseignants" if len(enseignants_list) > 1 else "Enseignant"
        parts.append(f"👨‍🏫 {label} : {', '.join(enseignants_list)}")
    
    if groupes_list:
        label = "Groupes" if len(groupes_list) > 1 else "Groupe"
        parts.append(f"👥 {label} : {', '.join(groupes_list)}")
    
    # Ajouter les coefficients si on a trouvé la matière
    if cours_data:
        coefs = cours_data.get("coefs", {})
        coef_text = format_coefs(coefs)
        if coef_text:
            parts.append(coef_text)
    
    return "\n".join(parts)


def classify_event(event, cours_mapping, compiled_codes):
    """
    Classifie un événement ICS et retourne le titre formaté + données matière.

    Returns:
        tuple: (final_summary, color_id, matched_code_or_None, cours_data_or_None, missing_code_or_None)
    """
    original_title = event.name.strip()
    title_upper = original_title.upper()

    # --- Événements spéciaux ---
    is_special = any(keyword in title_upper for keyword in SPECIAL_KEYWORDS)
    if is_special:
        emoji = "✨"
        if "HACK" in title_upper: emoji = "🛠️"
        elif "SORTIE" in title_upper or "VISITE" in title_upper: emoji = "🚌"
        elif "EXAM" in title_upper: emoji = "🚨"
        return f"{emoji} {original_title}", COLOR_SPECIAL, None, None, None

    # --- Événements normaux : chercher la matière ---
    search_zone = (event.name + " " + (event.description or "")).upper()

    subj_emoji = ""
    subj_name = ""
    found_code = False
    missing_code = None
    matched_code = None
    cours_data = None
    color_id = COLOR_DEFAULT

    # Tri par longueur décroissante pour éviter que R11 match avant R110
    for code, regex in compiled_codes.items():
        if regex.search(search_zone):
            data = cours_mapping[code]
            subj_emoji = data.get("emoji", "")
            subj_name = data.get("name", code)
            color_id = data.get("color", COLOR_DEFAULT)
            cours_data = data
            matched_code = code
            found_code = True
            break

    if not found_code:
        potential_code = re.search(r'\b(R\d{3}|SAE\d{2,3})\b', search_zone)
        if potential_code:
            missing_code = potential_code.group(0)

    if not subj_name:
        subj_name = original_title
        if " - " in subj_name:
            parts = subj_name.split(" - ", 1)
            if len(parts) > 1 and len(parts[1]) > 2:
                subj_name = parts[1].strip()

    # --- Détection du type (CM/TD/TP/Examen) avec regex word-boundary ---
    emoji_type = "📅"
    type_label = ""

    if re.search(r'\bEXAM\b|\bEVALUATION\b|\bPARTIEL\b|\bDS\b|\bEXAMENS?\b', search_zone):
        emoji_type = "🚨"
        type_label = "Examen"
        color_id = COLOR_EXAMEN  # Rouge pour les examens, prioritaire
    elif re.search(r'\b(SA[EÉ]|PROJET)\b', title_upper):
        emoji_type = "🚀"
        type_label = "SAÉ"
        color_id = "1"  # Lavande
    else:
        # Optimisation : Chercher TD, TP, CM en priorisant le titre, puis la description
        match_title = re.search(r'\b(TP|TD|CM|AMPHI|SOUTIEN)\b', title_upper)
        if match_title:
            typ = match_title.group(1)
            if typ == "TP": emoji_type, type_label = "💻", "TP"
            elif typ == "TD": emoji_type, type_label = "✏️", "TD"
            elif typ in ["CM", "AMPHI"]: emoji_type, type_label = "🎤", "CM"
            elif typ == "SOUTIEN": emoji_type, type_label = "🆘", "Soutien"
        else:
            match_desc = re.search(r'\b(TP|TD|CM)\b', search_zone)
            if match_desc:
                typ = match_desc.group(1)
                if typ == "TP": emoji_type, type_label = "💻", "TP"
                elif typ == "TD": emoji_type, type_label = "✏️", "TD"
                elif typ == "CM": emoji_type, type_label = "🎤", "CM"

    # --- Construction du titre final ---
    if type_label == "Examen":
        final_summary = f"{emoji_type} {type_label} {subj_emoji} {subj_name}"
    else:
        final_summary = f"{emoji_type}{subj_emoji} {type_label} {subj_name}"

    final_summary = re.sub(r'\s+', ' ', final_summary).strip()
    return final_summary, color_id, matched_code, cours_data, missing_code


def generate_stable_id(event_uid):
    """
    Génère un ID stable basé sur l'UID ICS original.
    Les IDs Google Calendar doivent être [a-v0-9]{5,1024}.
    """
    raw_hash = hashlib.md5(event_uid.encode('utf-8')).hexdigest()
    return "cal" + raw_hash


def parse_events(ics_text, cours_mapping, full_sync=False):
    """Parse le fichier ICS et retourne les événements transformés."""
    logger.info("⚙️ Analyse V5.0...")
    try:
        cal = icalendar.Calendar.from_ical(ics_text)
    except Exception as e:
        logger.critical(f"❌ ERREUR LECTURE ICS : {e}")
        sys.exit(1)

    now_aware = datetime.datetime.now(UTC_TZ)

    # Pré-trier les codes par longueur décroissante et compiler pour des perfs x10
    sorted_codes = sorted(cours_mapping.keys(), key=len, reverse=True)
    compiled_codes = {code: re.compile(rf'\b{re.escape(code)}\b', re.IGNORECASE) for code in sorted_codes}

    events_payload_map = {}
    seen_days = set()
    missing_codes = set()
    
    # Dérouler les RRULE sur une période de 1 an dans le passé et 3 ans dans le futur
    events = recurring_ical_events.of(cal).between(
        now_aware - datetime.timedelta(days=365),
        now_aware + datetime.timedelta(days=365 * 3)
    )

    # Sort events by start date
    events.sort(key=lambda x: x.get('dtstart').dt)

    class _EventAdapter:
        """Adaptateur léger pour passer les données icalendar à classify_event."""
        __slots__ = ('name', 'description', 'location')
        def __init__(self, name, description, location):
            self.name = name
            self.description = description
            self.location = location

    for event in events:
        event_name = str(event.get('SUMMARY', ''))
        event_desc = str(event.get('DESCRIPTION', ''))
        event_location = str(event.get('LOCATION', ''))
        
        dummy_event = _EventAdapter(event_name, event_desc, event_location)

        if not dummy_event.name:
            continue

        if not SHOW_HACK_CAMPUS and "hack ecampus" in dummy_event.name.lower():
            continue

        try:
            # Handle datetime or date objects from icalendar
            start_dt = event.get('DTSTART').dt
            end_dt = event.get('DTEND').dt
            
            if isinstance(start_dt, datetime.date) and not isinstance(start_dt, datetime.datetime):
                # All day event, convert to datetime with UTC
                start_dt = datetime.datetime.combine(start_dt, datetime.time.min).replace(tzinfo=UTC_TZ)
                end_dt = datetime.datetime.combine(end_dt, datetime.time.min).replace(tzinfo=UTC_TZ)
            elif start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=UTC_TZ)
                end_dt = end_dt.replace(tzinfo=UTC_TZ)
            else:
                start_dt = start_dt.astimezone(UTC_TZ)
                end_dt = end_dt.astimezone(UTC_TZ)
                
            event_start = start_dt
            event_end = end_dt
        except Exception as e:
            logger.warning(f"⚠️ Erreur de date sur un événement : {e}")
            continue

        # Calculer le jour pour pouvoir attribuer le flag 'premier cours' avant filtrage
        event_start_paris = event_start.replace(tzinfo=UTC_TZ).astimezone(PARIS_TZ)
        day_key = event_start_paris.strftime('%Y-%m-%d')

        is_first_of_day = day_key not in seen_days
        if is_first_of_day:
            seen_days.add(day_key)

        # On garde si la FIN est dans le futur (sauf en mode --full)
        if not full_sync and event_end <= now_aware:
            continue

        # Classification
        final_summary, color_id, matched_code, cours_data, missing_code = classify_event(
            dummy_event, cours_mapping, compiled_codes
        )
        if missing_code:
            missing_codes.add(missing_code)

        # --- ID STABLE basé sur l'UID ICS + RECURRENCE-ID s'il y en a un ---
        try:
            uid_str = str(event.get('UID', ''))
        except Exception:
            uid_str = f"{dummy_event.name}_{event_start.isoformat()}"
            
        recurrence_id = event.get('RECURRENCE-ID')
        if recurrence_id:
            uid_str += f"_{recurrence_id.dt.isoformat()}"
            
        # On ajoute quand même l'event_start dans le subistut UID pour éviter les collisions
        event_uid = uid_str or f"{dummy_event.name}_{event_start.isoformat()}"
        unique_id = generate_stable_id(event_uid + event_start.isoformat())

        # --- ALARME & DESCRIPTION ENRICHIE ---
        desc = enrich_description(dummy_event.description, cours_data, matched_code, is_first_of_day)

        # Build original data payload
        event_body = {
            'id': unique_id,
            'summary': final_summary,
            'location': dummy_event.location or "",
            'description': desc,
            'colorId': color_id,
            'start': {'dateTime': event_start.isoformat(), 'timeZone': 'UTC'},
            'end': {'dateTime': event_end.isoformat(), 'timeZone': 'UTC'},
            'reminders': {'useDefault': False, 'overrides': []},
            'extendedProperties': {
                'private': {
                    'createdBy': 'unicaen-sync-bot',
                    'version': '5.0',
                    'matchedCode': matched_code or ''
                }
            }
        }
        
        events_payload_map[unique_id] = event_body

    return events_payload_map, missing_codes


def apply_overrides(events_payload_map):
    """
    Vérifie les dérogations :
    Si Zimbra est mis à jour -> on supprime la dérogation.
    Si Zimbra n'est pas encore à jour -> on applique la dérogation sur events_payload_map.
    """
    overrides = load_overrides()
    if not overrides:
        return events_payload_map

    overrides_to_remove = set()
    
    for zimbra_id, override_data in overrides.items():
        if zimbra_id not in events_payload_map:
            continue
            
        zimbra_event = events_payload_map[zimbra_id]
        
        # Extrait les infos pour vérification
        z_start = zimbra_event['start']['dateTime']
        z_end = zimbra_event['end']['dateTime']
        z_loc = zimbra_event.get('location', '')
        
        o_start = override_data['start']
        o_end = override_data['end']
        o_loc = override_data.get('location', '')
        
        # Si Zimbra a désormais les mêmes dates ET lieu que la dérogation -> Zimbra est à jour !
        if z_start == o_start and z_end == o_end and z_loc == o_loc:
            logger.info(f"👍 Zimbra a été mis à jour pour l'événement {zimbra_id}. Dérogation annulée.")
            overrides_to_remove.add(zimbra_id)
        else:
            # Zimbra pas à jour -> on applique la rustine
            logger.info(f"🔄 Application de la dérogation mail sur l'événement {zimbra_id}.")
            zimbra_event['start']['dateTime'] = o_start
            zimbra_event['end']['dateTime'] = o_end
            if o_loc:
                zimbra_event['location'] = o_loc
            
            # Tags visuels
            if not zimbra_event['summary'].startswith("🔄️"):
                zimbra_event['summary'] = f"🔄️ {zimbra_event['summary']}"
            
            mail_notice = "🔄️ Changement via mail de la scolarité 🔄️\n\n"
            if mail_notice not in zimbra_event['description']:
                zimbra_event['description'] = mail_notice + zimbra_event['description']
                
    # Nettoyage des dérogations devenues inutiles
    if overrides_to_remove:
        for z_id in overrides_to_remove:
            del overrides[z_id]
        save_overrides(overrides)

    return events_payload_map


def fetch_latest_ics_from_mail(cours_mapping, events_payload_map, dry_run=False):
    """
    Se connecte en IMAP, cherche les nouveaux mails avec fichiers .ics (ou .vcs).
    Enregistre les dérogations si pertinentes.
    """
    if dry_run:
        logger.info("🧪 [DRY RUN] Recherche de mails simulée.")
        
    if not IMAP_SERVER or not IMAP_USER or not IMAP_PASS:
        logger.info("ℹ️ Identifiants IMAP non configurés. Ignorance de la recherche de mails.")
        return
        
    uid_validity, last_uid = _read_last_uid()

    logger.info("📧 Connexion à la boîte mail...")
    try:
        with _imap_connect() as server:
            server.login(IMAP_USER, IMAP_PASS)
            folder_info = server.select_folder('INBOX')
            current_validity = folder_info.get(b'UIDVALIDITY', 0)
            
            # Reset si changement de serveur/dossier
            if current_validity != uid_validity:
                uid_validity = current_validity
                last_uid = 0

            messages = server.search(['UID', f'{last_uid+1}:*']) if last_uid > 0 else server.search('ALL')
            messages = [uid for uid in messages if uid > last_uid]
            
            if not messages:
                logger.info("💤 Aucun nouveau message à analyser.")
                return

            # Ne traiter que les plus récents (limite sécurité)
            new_msgs = messages[-50:]
            
            overrides = load_overrides()
            new_uid_state = last_uid
            
            # Trier les clés de codes matières par longueur et compiler
            sorted_codes = sorted(cours_mapping.keys(), key=len, reverse=True)
            compiled_codes = {code: re.compile(rf'\b{re.escape(code)}\b', re.IGNORECASE) for code in sorted_codes}
            
            # Créer un cache O(1) (date, code_matiere) -> list[(z_id, z_event)]
            events_by_date_code = {}
            for z_id, z_event in events_payload_map.items():
                z_start = datetime.datetime.fromisoformat(z_event['start']['dateTime']).date()
                matched_code = z_event.get('extendedProperties', {}).get('private', {}).get('matchedCode', '')
                if matched_code:
                    key = (z_start, matched_code)
                    if key not in events_by_date_code:
                        events_by_date_code[key] = []
                    events_by_date_code[key].append((z_id, z_event))
            
            for msg_uid in new_msgs:
                new_uid_state = max(new_uid_state, msg_uid)
                try:
                    res = server.fetch(msg_uid, ['RFC822'])
                    # res[msg_uid] contains the data, check for b'RFC822'
                    msg_data = res[msg_uid]
                    if b'RFC822' in msg_data:
                        raw_email = msg_data[b'RFC822']
                    else:
                        continue
                        
                    msg = email.message_from_bytes(raw_email)
                    
                    # Chercher la pièce jointe
                    process_mail_parts(msg, msg_uid, overrides, events_by_date_code, compiled_codes)
                except Exception as inner_e:
                    logger.warning(f"⚠️ Impossible de parser le mail UID {msg_uid}: {inner_e}")
                
            # Sauvegarder
            if not dry_run:
                save_overrides(overrides)
                with open(MAIL_SYNC_STATE_FILE, 'w') as f:
                    json.dump({"uid_validity": uid_validity, "last_uid": new_uid_state}, f)
            else:
                logger.info("🧪 [DRY RUN] Sauvegarde de l'état mail ignorée.")
            
            logger.info("✅ Vérification des mails terminée.")

    except Exception as e:
        logger.error(f"❌ Erreur IMAP : {e}")


def find_matching_zimbra_event(mail_event, events_by_date_code, compiled_codes):
    """
    Tente de lier l'événement mail à un événement Zimbra existant via la matière
    et la proximité calendaire (même jour).
    L'ordre d'analyse O(1) permet d'accélérer considérablement le processus.
    """
    event_name = str(mail_event.get('SUMMARY', ''))
    event_desc = str(mail_event.get('DESCRIPTION', ''))
    original_title = event_name.strip().upper()
    search_zone = (event_name + " " + event_desc).upper()
    
    matched_code = None
    for code, regex in compiled_codes.items():
        if regex.search(search_zone):
            matched_code = code
            break
            
    if not matched_code:
        return None
        
    try:
        start_dt = mail_event.get('DTSTART').dt
        if isinstance(start_dt, datetime.datetime):
            mail_start = start_dt.date()
        else:
            mail_start = start_dt
    except Exception:
        return None
        
    # Match via the date index O(1)
    key = (mail_start, matched_code)
    if key in events_by_date_code:
        return events_by_date_code[key][0][0]
                
    return None

def process_mail_parts(msg, msg_uid, overrides, events_by_date_code, compiled_codes):
    for part in msg.walk():
        if part.get_content_maintype() == 'multipart':
            continue
        if part.get('Content-Disposition') is None:
            continue
            
        filename = part.get_filename()
        if not filename:
            continue
            
        if filename.lower().endswith('.ics') or filename.lower().endswith('.vcs'):
            logger.info(f"📎 Trouvé fichier de calendrier : {filename}")
            try:
                content = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                cal = icalendar.Calendar.from_ical(content)
                
                # Fetching events resolving recurrences just in case mail is a recurring event
                events = recurring_ical_events.of(cal).between(
                    datetime.datetime.now(UTC_TZ) - datetime.timedelta(days=7),
                    datetime.datetime.now(UTC_TZ) + datetime.timedelta(days=365)
                )
                
                for mail_ev in events:
                    z_id = find_matching_zimbra_event(mail_ev, events_by_date_code, compiled_codes)
                    if z_id:
                        logger.info(f"🔗 Liaison réussie : Le mail corrige l'événement Zimbra {z_id}")
                        
                        start_dt = mail_ev.get('DTSTART').dt
                        end_dt = mail_ev.get('DTEND').dt
                        
                        if isinstance(start_dt, datetime.date) and not isinstance(start_dt, datetime.datetime):
                            start_dt = datetime.datetime.combine(start_dt, datetime.time.min).replace(tzinfo=UTC_TZ)
                            end_dt = datetime.datetime.combine(end_dt, datetime.time.min).replace(tzinfo=UTC_TZ)
                        elif start_dt.tzinfo is None:
                            start_dt = start_dt.replace(tzinfo=UTC_TZ)
                            end_dt = end_dt.replace(tzinfo=UTC_TZ)
                        else:
                            start_dt = start_dt.astimezone(UTC_TZ)
                            end_dt = end_dt.astimezone(UTC_TZ)
                            
                        o_start = start_dt.isoformat()
                        o_end = end_dt.isoformat()
                        o_loc = str(mail_ev.get('LOCATION', ''))
                        
                        overrides[z_id] = {
                            "start": o_start,
                            "end": o_end,
                            "location": o_loc,
                            "uid_source": msg_uid
                        }
                        
                        # Notification Discord
                        try:
                            z_summary = "[Inconnu]"
                            mail_start_date = start_dt.date()
                            
                            # Find the matching code to get the summary
                            event_name = str(mail_ev.get('SUMMARY', ''))
                            event_desc = str(mail_ev.get('DESCRIPTION', ''))
                            search_zone = (event_name + " " + event_desc).upper()
                            matched_code = None
                            for code, regex in compiled_codes.items():
                                if regex.search(search_zone):
                                    matched_code = code
                                    break
                                    
                            if matched_code and (mail_start_date, matched_code) in events_by_date_code:
                                for ev_id, stored_ev in events_by_date_code[(mail_start_date, matched_code)]:
                                    if ev_id == z_id:
                                        z_summary = stored_ev.get('summary', z_summary)
                                        break
                            
                            discord_msg = (
                                f"**Matière :** {z_summary}\n"
                                f"**Nouvelle date :** {start_dt.astimezone(PARIS_TZ).strftime('%d/%m/%Y %H:%M')} ➔ {end_dt.astimezone(PARIS_TZ).strftime('%H:%M')}\n"
                            )
                            if o_loc:
                                discord_msg += f"**Nouveau lieu :** {o_loc}"
                                
                            send_discord_notification("🚨 Modification d'Emploi du Temps", discord_msg, color=16753920) # Orange
                        except Exception as e:
                            logger.error(f"Erreur formattage discord : {e}")
                    else:
                        event_name = str(mail_ev.get('SUMMARY', ''))
                        logger.warning(f"⚠️ Impossible de lier l'événement mail '{event_name}' à Zimbra (Matière introuvable ou date trop éloignée).")
            except Exception as e:
                logger.error(f"❌ Erreur de parsing de l'ICS du mail : {e}")

def log_missing_codes(missing_codes):
    """Enregistre les codes matières inconnus dans un fichier log."""
    if not missing_codes:
        return
    logger.warning(f"⚠️ Codes matières inconnus détectés : {', '.join(sorted(missing_codes))}")
    try:
        with open(MISSING_LOG_FILE, 'w') as f:
            f.write(f"Dernière détection : {datetime.datetime.now(PARIS_TZ)}\n")
            for code in sorted(missing_codes):
                f.write(f"{code}\n")
        logger.info(f"📝 Liste enregistrée dans {MISSING_LOG_FILE}")
    except Exception as e:
        logger.error(f"❌ Impossible d'écrire le log : {e}")


def execute_batch(service, requests_list):
    """Exécute une liste de requêtes Google par batch de 50."""
    if not requests_list:
        return

    def batch_callback(request_id, response, exception):
        if exception:
            logger.warning(f"⚠️ Erreur Batch sur {request_id}: {exception}")

    batch = service.new_batch_http_request(callback=batch_callback)
    count = 0
    for req in requests_list:
        batch.add(req)
        count += 1
        if count >= 50:
            batch.execute()
            batch = service.new_batch_http_request(callback=batch_callback)
            count = 0
    if count > 0:
        batch.execute()


def normalize_dt(dt_string):
    """Normalise une datetime string pour comparaison stable (Z ↔ +00:00)."""
    if not dt_string:
        return ""
    return dt_string.replace("Z", "+00:00")


def should_delete(ev_id, google_events_map):
    """Détermine si un événement Google doit être supprimé."""
    event = google_events_map.get(ev_id)
    if not event:
        return False

    # Signature V1.0+ / V2.x / V3.x (Métadonnées)
    props = event.get('extendedProperties', {}).get('private', {})
    if props.get('createdBy') == 'unicaen-sync-bot':
        return True

    # Signature Beta/Legacy (ID Pattern)
    if re.match(r'^(cal)?[a-f0-9]{32}$', ev_id):
        return True

    return False


def sync_to_google(events_payload_map, full_sync=False, dry_run=False):
    """Synchronise les événements transformés avec Google Calendar."""
    if dry_run:
        logger.info("🧪 [DRY RUN] Synchronisation Google Calendar simulée.")
        
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=['https://www.googleapis.com/auth/calendar']
    )
    service = build('calendar', 'v3', credentials=creds)

    logger.info("🔄 Comparaison avec l'agenda Google existant...")

    STORE_FILE = '.google_sync_store.json'
    local_store = {"sync_token": None, "events": {}}
    
    if os.path.exists(STORE_FILE) and not full_sync:
        try:
            with open(STORE_FILE, 'r') as f:
                local_store = json.load(f)
        except Exception:
            pass

    google_events_map = local_store.get("events", {})
    sync_token = local_store.get("sync_token")
    
    list_params = {
        'calendarId': CALENDAR_ID,
        'maxResults': 2500,
    }
    
    # Mode Delta (Sync Token) ou Mode Initial/Full
    if sync_token and not full_sync:
        list_params['syncToken'] = sync_token
    else:
        list_params['singleEvents'] = True
        list_params['privateExtendedProperty'] = 'createdBy=unicaen-sync-bot'
        list_params['timeZone'] = 'UTC'
        if not full_sync:
            now_str = datetime.datetime.now(UTC_TZ).isoformat().replace("+00:00", "Z")
            list_params['timeMin'] = now_str
            
    def fetch_google_events(params):
        page_token = None
        while True:
            if page_token:
                params['pageToken'] = page_token
            result = service.events().list(**params).execute()

            for item in result.get('items', []):
                if item.get('status') == 'cancelled':
                    google_events_map.pop(item['id'], None)
                elif 'id' in item:
                    # Ignore events not created by us if we pull everything (syncToken doesn't filter by extendedProperty!)
                    props = item.get('extendedProperties', {}).get('private', {})
                    if props.get('createdBy') == 'unicaen-sync-bot' or re.match(r'^(cal)?[a-f0-9]{32}$', item['id']):
                        google_events_map[item['id']] = item

            page_token = result.get('nextPageToken')
            if not page_token:
                next_sync_token = result.get('nextSyncToken')
                if next_sync_token:
                    local_store['sync_token'] = next_sync_token
                break

    try:
        fetch_google_events(list_params)
    except Exception as e:
        if '410' in str(e):
            logger.warning("🔄 Sync token expiré. Re-synchronisation complète...")
            list_params.pop('syncToken', None)
            list_params['singleEvents'] = True
            list_params['privateExtendedProperty'] = 'createdBy=unicaen-sync-bot'
            list_params['timeZone'] = 'UTC'
            if not full_sync:
                now_str = datetime.datetime.now(UTC_TZ).isoformat().replace("+00:00", "Z")
                list_params['timeMin'] = now_str
            local_store['events'] = {}
            google_events_map = local_store['events']
            fetch_google_events(list_params)
        else:
            logger.critical(f"❌ ERREUR API GOOGLE : {e}")
            sys.exit(1)

    # --- Différentiel ---
    ics_ids = set(events_payload_map.keys())
    google_ids = set(google_events_map.keys())

    ids_to_maybe_delete = google_ids - ics_ids
    to_delete = {x for x in ids_to_maybe_delete if should_delete(x, google_events_map)}
    to_insert = ics_ids - google_ids
    to_update = set()

    for eid in (google_ids & ics_ids):
        new_data = events_payload_map[eid]
        old_data = google_events_map[eid]

        needs_update = False
        if normalize_str(new_data['summary']) != normalize_str(old_data.get('summary', '')):
            needs_update = True
        elif normalize_str(new_data['description']) != normalize_str(old_data.get('description', '')):
            needs_update = True
        elif normalize_str(new_data['location']) != normalize_str(old_data.get('location', '')):
            needs_update = True
        elif new_data.get('colorId') != old_data.get('colorId', ''):
            needs_update = True
        # Vérifier les changements d'horaire (start/end) — normaliser Z ↔ +00:00
        elif normalize_dt(new_data['start'].get('dateTime')) != normalize_dt(old_data.get('start', {}).get('dateTime', '')):
            needs_update = True
        elif normalize_dt(new_data['end'].get('dateTime')) != normalize_dt(old_data.get('end', {}).get('dateTime', '')):
            needs_update = True

        # S'assurer que les métadonnées V5.0 sont présentes
        # Si on n'a pas old_props mais qu'on a le event, par défaut on met update pour injecter la V5
        old_props = old_data.get('extendedProperties', {}).get('private', {})
        if old_props.get('version') != '5.0':
            needs_update = True

        if needs_update:
            to_update.add(eid)

    logger.info(f"📊 Analyse : +{len(to_insert)} ajouts, -{len(to_delete)} suppressions, ~{len(to_update)} mises à jour.")

    # --- Exécution batch ---
    batch_requests = []
    for ev_id in to_delete:
        batch_requests.append(service.events().delete(calendarId=CALENDAR_ID, eventId=ev_id))
    for ev_id in to_insert:
        body = events_payload_map[ev_id]
        batch_requests.append(service.events().insert(calendarId=CALENDAR_ID, body=body))
    for ev_id in to_update:
        body = events_payload_map[ev_id]
        batch_requests.append(service.events().update(calendarId=CALENDAR_ID, eventId=ev_id, body=body))

    if batch_requests:
        logger.info(f"🚀 Envoi de {len(batch_requests)} opérations...")
        if not dry_run:
            execute_batch(service, batch_requests)
        else:
            logger.info("🧪 [DRY RUN] Opérations API Google ignorées.")
    else:
        logger.info("💤 Tout est déjà à jour.")
        
    if dry_run:
        return
        
    # Mettre à jour les données dans google_events_map localement et sauvegarder
    for ev_id in to_delete:
        local_store['events'].pop(ev_id, None)
    for ev_id in to_insert | to_update:
        local_store['events'][ev_id] = events_payload_map[ev_id]
        
    try:
        with open(STORE_FILE, 'w') as f:
            json.dump(local_store, f)
    except Exception as e:
        logger.error(f"⚠️ Erreur lors de la sauvegarde du cache Google : {e}")


# =============================================================================
#  MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description='Unicaen EDT → Google Calendar Sync')
    parser.add_argument('--full', action='store_true',
                        help='Synchronise TOUS les événements (passés + futurs)')
    parser.add_argument('--mail', action='store_true',
                        help='Vérifie uniquement les nouveaux mails et annule si pas de mail (usage cron séparé)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Exécute le script sans modifier Google Calendar ni les fichiers d\'état')
    args = parser.parse_args()

    if args.full:
        logger.info("🔁 Mode FULL : synchronisation de tous les événements (passés inclus)")

    if args.mail:
        logger.info("📩 Mode --mail activé : Vérification rapide IMAP...")
        validate_config(check_imap=True)
        if not check_new_imap_messages():
            logger.info("💤 Aucun nouveau message IMAP. Synchronisation mail non-nécessaire.")
            return
    else:
        validate_config(check_imap=False)

    cours_mapping = load_mapping()
    ics_text = download_ics()
    
    # 1. Parsing normal Zimbra
    events_payload_map, missing_codes = parse_events(ics_text, cours_mapping, full_sync=args.full)
    log_missing_codes(missing_codes)
    
    # 2. Vérification IMAP des éventuels changements
    fetch_latest_ics_from_mail(cours_mapping, events_payload_map, dry_run=args.dry_run)
    
    # 3. Application des overrides trouvés
    events_payload_map = apply_overrides(events_payload_map)
    
    # 4. Synchro finale
    sync_to_google(events_payload_map, full_sync=args.full, dry_run=args.dry_run)
    logger.info("🎉 Synchronisation terminée.")


if __name__ == "__main__":
    main()
