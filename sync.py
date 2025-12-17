import requests
from requests.auth import HTTPBasicAuth
from ics import Calendar
from google.oauth2 import service_account
from googleapiclient.discovery import build
import datetime
import os
import sys
import hashlib
import re
import json
import pytz

# --- CONFIGURATION LOGS ---
def log(msg):
    paris_tz = pytz.timezone('Europe/Paris')
    now = datetime.datetime.now(paris_tz).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {msg}")
    sys.stdout.flush()

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

# --- VÉRIFICATIONS ---
if not all([ICS_URL, USERNAME, PASSWORD, CALENDAR_ID]):
    log("❌ CRITIQUE : Variables d'environnement manquantes (.env)")
    sys.exit(1)

if not os.path.exists(MAPPING_FILE):
    log(f"❌ CRITIQUE : Fichier '{MAPPING_FILE}' introuvable.")
    sys.exit(1)

# --- CHARGEMENT DICTIONNAIRE ---
try:
    with open(MAPPING_FILE, 'r', encoding='utf-8') as f:
        COURS_MAPPING = json.load(f)
    log(f"✅ Dictionnaire chargé : {len(COURS_MAPPING)} matières.")
except json.JSONDecodeError as e:
    log(f"❌ CRITIQUE : Erreur de syntaxe JSON dans {MAPPING_FILE} : {e}")
    sys.exit(1)

SPECIAL_KEYWORDS = [
    "HACK", "SORTIE", "VISITE", "CONFÉRENCE", "ATELIER", 
    "FORUM", "RENCONTRE", "JPO", "SALON", "DÉFI", "CHALLENGE",
    "RÉUNION DE RENTRÉE", "PETIT DÉJEUNER", "SHOOTING", "OUVERTURE"
]

# --- HELPER BATCH ---
def execute_batch(service, requests_list):
    if not requests_list: return
    def batch_callback(request_id, response, exception):
        if exception: log(f"⚠️ Erreur Batch sur {request_id}: {exception}")

    batch = service.new_batch_http_request(callback=batch_callback)
    count = 0
    for req in requests_list:
        batch.add(req)
        count += 1
        if count >= 50:
            batch.execute()
            batch = service.new_batch_http_request(callback=batch_callback)
            count = 0
    if count > 0: batch.execute()

# --- 2. TÉLÉCHARGEMENT ---
log(f"📥 Connexion à l'ENT...")
headers = {"User-Agent": "Mozilla/5.0"}
try:
    response = requests.get(ICS_URL, headers=headers, auth=HTTPBasicAuth(USERNAME, PASSWORD))
    response.raise_for_status()
    response.encoding = response.apparent_encoding if response.apparent_encoding else 'utf-8'
    log(f"✅ Fichier ICS téléchargé ({len(response.text)} octets).")
except Exception as e:
    log(f"❌ ERREUR TÉLÉCHARGEMENT : {e}")
    sys.exit(1)

# --- 3. TRAITEMENT INTELLIGENT ---
log("⚙️ Analyse V1.0 Stable...")
try:
    c = Calendar(response.text)
except Exception as e:
    log(f"❌ ERREUR LECTURE ICS : {e}")
    sys.exit(1)

paris_tz = pytz.timezone('Europe/Paris')
utc_tz = datetime.timezone.utc
now_aware = datetime.datetime.now(utc_tz)

events_payload_map = {} 
seen_days = set()
missing_codes = set()

sorted_events = sorted(c.events, key=lambda x: x.begin)

for event in sorted_events:
    if not event.name: continue
    
    if not SHOW_HACK_CAMPUS and "hack ecampus" in event.name.lower():
        continue 
    
    try:
        event_start = event.begin.to('utc').datetime
        event_end = event.end.to('utc').datetime
    except Exception as e:
        log(f"⚠️ Erreur de date sur un événement : {e}")
        continue

    # On garde si la FIN est dans le futur
    if event_end > now_aware:
        
        original_title = event.name.strip()
        final_summary = original_title
        title_upper = original_title.upper()
        
        is_special = any(keyword in title_upper for keyword in SPECIAL_KEYWORDS)
        
        if is_special:
            emoji = "✨"
            if "HACK" in title_upper: emoji = "🛠️"
            elif "SORTIE" in title_upper or "VISITE" in title_upper: emoji = "🚌"
            elif "EXAM" in title_upper: emoji = "🚨"
            final_summary = f"{emoji} {original_title}"
        else:
            search_zone = (event.name + " " + (event.description or "")).upper()
            search_zone_clean = search_zone.replace(".", "").replace(" ", "").replace("-", "").replace("É", "E")
            
            subj_emoji = ""
            subj_name = ""
            found_code = False
            
            for code, nom_propre in COURS_MAPPING.items():
                if code in search_zone_clean:
                    parts = nom_propre.split(" ", 1)
                    if len(parts) == 2:
                        subj_emoji, subj_name = parts[0], parts[1]
                    else:
                        subj_name = nom_propre
                    found_code = True
                    break
            
            if not found_code:
                potential_code = re.search(r'\b(R\d{3}|SAE\d{2,3})\b', search_zone_clean)
                if potential_code:
                    missing_codes.add(potential_code.group(0))

            if not subj_name:
                subj_name = original_title
                if " - " in subj_name:
                    parts = subj_name.split(" - ", 1)
                    if len(parts) > 1 and len(parts[1]) > 2:
                        subj_name = parts[1].strip()

            emoji_type = "📅"
            type_label = "" 
            desc_upper = (event.description or "").upper()
            
            if "EXAM" in search_zone or "EVALUATION" in search_zone or "PARTIEL" in search_zone or re.search(r'\bDS\b', search_zone): 
                emoji_type = "🚨"
                type_label = "Examen"
            elif "TP" in title_upper: 
                emoji_type = "💻"
                type_label = "TP"
            elif "TD" in title_upper: 
                emoji_type = "✏️"
                type_label = "TD"
            elif "CM" in title_upper or "AMPHI" in title_upper: 
                emoji_type = "🎤"
                type_label = "CM"
            elif "SOUTIEN" in title_upper: 
                emoji_type = "🆘"
                type_label = "Soutien"
            elif "ANGLAIS" in title_upper: 
                emoji_type = "🇬🇧"
                type_label = "Anglais"
            elif not any(x in title_upper for x in ["TP", "TD", "CM"]):
                if "TP" in desc_upper: emoji_type = "💻"; type_label = "TP"
                elif "TD" in desc_upper: emoji_type = "✏️"; type_label = "TD"
                elif "CM" in desc_upper: emoji_type = "🎤"; type_label = "CM"

            if type_label == "Examen":
                final_summary = f"{emoji_type} {type_label} {subj_emoji} {subj_name}"
            else:
                final_summary = f"{emoji_type}{subj_emoji} {type_label} {subj_name}"
            
            final_summary = re.sub(r'\s+', ' ', final_summary).strip()

        # --- ID STABLE ---
        id_str = f"cal_{final_summary}{event_start.isoformat()}"
        unique_id = "cal" + hashlib.md5(id_str.encode('utf-8')).hexdigest()

        # --- ALARME & DESCRIPTION ---
        day_key = event_start.strftime('%Y-%m-%d')
        reminders = {'useDefault': False, 'overrides': []}
        desc = (event.description or "").strip()

        if day_key not in seen_days:
            seen_days.add(day_key)
            desc = f"🔔 Premier cours de la journée\n\n{desc}"

        event_body = {
            'id': unique_id,
            'summary': final_summary,
            'location': event.location or "",
            'description': desc,
            'start': {'dateTime': event_start.isoformat()}, 
            'end': {'dateTime': event_end.isoformat()},
            'reminders': reminders,
            'extendedProperties': {
                'private': {
                    'createdBy': 'unicaen-sync-bot',
                    'version': '1.0'
                }
            }
        }
        events_payload_map[unique_id] = event_body

if missing_codes:
    log(f"⚠️ Codes matières inconnus détectés : {', '.join(missing_codes)}")
    try:
        with open(MISSING_LOG_FILE, 'w') as f:
            f.write(f"Dernière détection : {datetime.datetime.now()}\n")
            for code in missing_codes:
                f.write(f"{code}\n")
        log(f"📝 Liste enregistrée dans {MISSING_LOG_FILE}")
    except Exception as e:
        log(f"❌ Impossible d'écrire le log : {e}")

# --- 4. GOOGLE SYNC ---
if not os.path.exists(SERVICE_ACCOUNT_FILE):
    log(f"❌ ERREUR : {SERVICE_ACCOUNT_FILE} introuvable.")
    sys.exit(1)

creds = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=['https://www.googleapis.com/auth/calendar']
)
service = build('calendar', 'v3', credentials=creds)

log("🔄 Comparaison avec l'agenda Google existant...")

google_events_map = {}
page_token = None
now_str = now_aware.isoformat().replace("+00:00", "Z")

try:
    while True:
        events_result = service.events().list(
            calendarId=CALENDAR_ID, 
            timeMin=now_str, 
            singleEvents=True, 
            maxResults=2500,
            pageToken=page_token
        ).execute()
        
        for item in events_result.get('items', []):
            if 'id' in item:
                google_events_map[item['id']] = item
        
        page_token = events_result.get('nextPageToken')
        if not page_token: break
            
except Exception as e:
    log(f"❌ ERREUR API GOOGLE : {e}")
    sys.exit(1)

# Différentiel
ics_ids = set(events_payload_map.keys())
google_ids = set(google_events_map.keys())

def should_delete(ev_id):
    # 1. Signature V1.0+ (Métadonnées) - La preuve absolue
    event = google_events_map.get(ev_id)
    if not event: return False
    
    props = event.get('extendedProperties', {}).get('private', {})
    if props.get('createdBy') == 'unicaen-sync-bot':
        return True

    # 2. Signature Beta/Legacy (ID Pattern)
    # On supprime tout ce qui ressemble à un ID généré par nos versions précédentes
    if re.match(r'^(cal)?[a-f0-9]{32}$', ev_id): return True
    
    return False

ids_to_maybe_delete = google_ids - ics_ids
to_delete = {x for x in ids_to_maybe_delete if should_delete(x)}
to_insert = ics_ids - google_ids
to_update = set()

for eid in (google_ids & ics_ids):
    new_data = events_payload_map[eid]
    old_data = google_events_map[eid]
    
    needs_update = False
    if new_data['summary'] != old_data.get('summary', ''): needs_update = True
    elif new_data['description'] != old_data.get('description', ''): needs_update = True
    elif new_data['location'] != old_data.get('location', ''): needs_update = True
    
    old_props = old_data.get('extendedProperties', {}).get('private', {})
    if 'createdBy' not in old_props: needs_update = True

    if needs_update: to_update.add(eid)

log(f"📊 Analyse : +{len(to_insert)} ajouts, -{len(to_delete)} suppressions, ~{len(to_update)} mises à jour.")

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
    log(f"🚀 Envoi de {len(batch_requests)} opérations...")
    execute_batch(service, batch_requests)
else:
    log("💤 Tout est déjà à jour.")

log("🎉 Synchronisation terminée.")