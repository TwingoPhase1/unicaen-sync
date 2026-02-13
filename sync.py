import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from ics import Calendar
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
from zoneinfo import ZoneInfo

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

def validate_config():
    """Vérifie que toutes les variables d'environnement et fichiers requis sont présents."""
    if not all([ICS_URL, USERNAME, PASSWORD, CALENDAR_ID]):
        logger.critical("❌ CRITIQUE : Variables d'environnement manquantes (.env)")
        sys.exit(1)
    if not os.path.exists(MAPPING_FILE):
        logger.critical(f"❌ CRITIQUE : Fichier '{MAPPING_FILE}' introuvable.")
        sys.exit(1)
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        logger.critical(f"❌ ERREUR : {SERVICE_ACCOUNT_FILE} introuvable.")
        sys.exit(1)


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


def classify_event(event, cours_mapping, sorted_codes):
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
    for code in sorted_codes:
        if re.search(rf'\b{re.escape(code)}\b', search_zone, re.IGNORECASE):
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
    desc_upper = (event.description or "").upper()

    if re.search(r'\bEXAM\b|\bEVALUATION\b|\bPARTIEL\b|\bDS\b', search_zone):
        emoji_type = "🚨"
        type_label = "Examen"
        color_id = COLOR_EXAMEN  # Rouge pour les examens, prioritaire
    elif re.search(r'\bTP\b', title_upper):
        emoji_type = "💻"
        type_label = "TP"
    elif re.search(r'\bTD\b', title_upper):
        emoji_type = "✏️"
        type_label = "TD"
    elif re.search(r'\bCM\b|\bAMPHI\b', title_upper):
        emoji_type = "🎤"
        type_label = "CM"
    elif re.search(r'\bSOUTIEN\b', title_upper):
        emoji_type = "🆘"
        type_label = "Soutien"
    elif not re.search(r'\bTP\b|\bTD\b|\bCM\b', title_upper):
        # Fallback : chercher dans la description
        if re.search(r'\bTP\b', desc_upper):
            emoji_type = "💻"; type_label = "TP"
        elif re.search(r'\bTD\b', desc_upper):
            emoji_type = "✏️"; type_label = "TD"
        elif re.search(r'\bCM\b', desc_upper):
            emoji_type = "🎤"; type_label = "CM"

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
    logger.info("⚙️ Analyse V3.0...")
    try:
        cal = Calendar(ics_text)
    except Exception as e:
        logger.critical(f"❌ ERREUR LECTURE ICS : {e}")
        sys.exit(1)

    now_aware = datetime.datetime.now(UTC_TZ)

    # Pré-trier les codes par longueur décroissante (SAE101 avant SAE11, R110 avant R11)
    sorted_codes = sorted(cours_mapping.keys(), key=len, reverse=True)

    events_payload_map = {}
    seen_days = set()
    missing_codes = set()

    sorted_events = sorted(cal.events, key=lambda x: x.begin)

    for event in sorted_events:
        if not event.name:
            continue

        if not SHOW_HACK_CAMPUS and "hack ecampus" in event.name.lower():
            continue

        try:
            event_start = event.begin.to('utc').datetime
            event_end = event.end.to('utc').datetime
        except Exception as e:
            logger.warning(f"⚠️ Erreur de date sur un événement : {e}")
            continue

        # On garde si la FIN est dans le futur (sauf en mode --full)
        if not full_sync and event_end <= now_aware:
            continue

        # Classification
        final_summary, color_id, matched_code, cours_data, missing_code = classify_event(
            event, cours_mapping, sorted_codes
        )
        if missing_code:
            missing_codes.add(missing_code)

        # --- ID STABLE basé sur l'UID ICS ---
        event_uid = event.uid or f"{event.name}_{event_start.isoformat()}"
        unique_id = generate_stable_id(event_uid)

        # --- ALARME & DESCRIPTION ENRICHIE ---
        # Calculer le jour en timezone Paris (pas UTC)
        event_start_paris = event_start.replace(tzinfo=UTC_TZ).astimezone(PARIS_TZ)
        day_key = event_start_paris.strftime('%Y-%m-%d')

        is_first_of_day = day_key not in seen_days
        if is_first_of_day:
            seen_days.add(day_key)

        desc = enrich_description(event.description, cours_data, matched_code, is_first_of_day)

        event_body = {
            'id': unique_id,
            'summary': final_summary,
            'location': event.location or "",
            'description': desc,
            'colorId': color_id,
            'start': {'dateTime': event_start.isoformat(), 'timeZone': 'UTC'},
            'end': {'dateTime': event_end.isoformat(), 'timeZone': 'UTC'},
            'reminders': {'useDefault': False, 'overrides': []},
            'extendedProperties': {
                'private': {
                    'createdBy': 'unicaen-sync-bot',
                    'version': '3.0'
                }
            }
        }
        events_payload_map[unique_id] = event_body

    return events_payload_map, missing_codes


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


def sync_to_google(events_payload_map, full_sync=False):
    """Synchronise les événements transformés avec Google Calendar."""
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=['https://www.googleapis.com/auth/calendar']
    )
    service = build('calendar', 'v3', credentials=creds)

    logger.info("🔄 Comparaison avec l'agenda Google existant...")

    # Récupérer les événements Google existants
    google_events_map = {}
    page_token = None
    list_params = {
        'calendarId': CALENDAR_ID,
        'singleEvents': True,
        'maxResults': 2500,
    }
    if not full_sync:
        now_str = datetime.datetime.now(UTC_TZ).isoformat().replace("+00:00", "Z")
        list_params['timeMin'] = now_str

    try:
        while True:
            if page_token:
                list_params['pageToken'] = page_token
            events_result = service.events().list(**list_params).execute()

            for item in events_result.get('items', []):
                if 'id' in item:
                    google_events_map[item['id']] = item

            page_token = events_result.get('nextPageToken')
            if not page_token:
                break
    except Exception as e:
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
        if new_data['summary'] != old_data.get('summary', ''):
            needs_update = True
        elif new_data['description'] != old_data.get('description', ''):
            needs_update = True
        elif new_data['location'] != old_data.get('location', ''):
            needs_update = True
        elif new_data.get('colorId') != old_data.get('colorId', ''):
            needs_update = True
        # Vérifier les changements d'horaire (start/end)
        elif new_data['start'].get('dateTime') != old_data.get('start', {}).get('dateTime', ''):
            needs_update = True
        elif new_data['end'].get('dateTime') != old_data.get('end', {}).get('dateTime', ''):
            needs_update = True

        # S'assurer que les métadonnées V3.0 sont présentes
        old_props = old_data.get('extendedProperties', {}).get('private', {})
        if old_props.get('version') != '3.0':
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
        execute_batch(service, batch_requests)
    else:
        logger.info("💤 Tout est déjà à jour.")


# =============================================================================
#  MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description='Unicaen EDT → Google Calendar Sync')
    parser.add_argument('--full', action='store_true',
                        help='Synchronise TOUS les événements (passés + futurs)')
    args = parser.parse_args()

    if args.full:
        logger.info("🔁 Mode FULL : synchronisation de tous les événements (passés inclus)")

    validate_config()
    cours_mapping = load_mapping()
    ics_text = download_ics()
    events_payload_map, missing_codes = parse_events(ics_text, cours_mapping, full_sync=args.full)
    log_missing_codes(missing_codes)
    sync_to_google(events_payload_map, full_sync=args.full)
    logger.info("🎉 Synchronisation terminée.")


if __name__ == "__main__":
    main()
