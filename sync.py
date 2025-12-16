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

# --- FONCTION DE LOG ---
def log(msg):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {msg}")
    sys.stdout.flush()

# --- CONFIGURATION ---
ICS_URL = os.getenv("ICS_URL")
USERNAME = os.getenv("ENT_USER")
PASSWORD = os.getenv("ENT_PASS")
CALENDAR_ID = os.getenv("CALENDAR_ID")
SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_PKEY_PATH", 'credentials.json')
ALARM_MINUTES = 60 

# Gestion Hack Ecampus
show_hack_env = os.getenv("SHOW_HACK_CAMPUS", "true").lower()
SHOW_HACK_CAMPUS = show_hack_env in ["true", "1", "yes", "on"]

if not all([ICS_URL, USERNAME, PASSWORD, CALENDAR_ID]):
    log("❌ CRITIQUE : .env incomplet")
    sys.exit(1)

# --- 1. DICTIONNAIRE ---
SPECIAL_KEYWORDS = [
    "HACK", "SORTIE", "VISITE", "CONFÉRENCE", "ATELIER", 
    "FORUM", "RENCONTRE", "JPO", "SALON", "DÉFI", "CHALLENGE",
    "RÉUNION DE RENTRÉE", "PETIT DÉJEUNER", "SHOOTING", "OUVERTURE"
]

COURS_MAPPING = {
    # SEMESTRE 1
    "R101": "🌐 Init. Réseaux", "R102": "🔌 Archi. Réseaux", "R103": "🏢 Réseaux Locaux",
    "R104": "⚡ Syst. Élec.", "R105": "📡 Supports Trans.", "R106": "💾 Archi. Numérique",
    "R107": "🐍 Prog. Fondamentaux", "R108": "🐧 Syst. Exploitation", "R109": "🌍 Tech. Web",
    "R110": "🇬🇧 Anglais Tech.", "R111": "🗣️ Com. Pro.", "R112": "🤝 PPP",
    "R113": "📐 Maths Signal", "R114": "📈 Maths Trans.", "R115": "📅 Gestion Projet",
    # SAE S1
    "SAE101": "🛡️ SAÉ Cyber", "SAE102": "🕸️ SAÉ Réseaux", "SAE103": "📡 SAÉ Trans.",
    "SAE104": "🌐 SAÉ Web", "SAE105": "📊 SAÉ Données", "SAE106": "📂 Portfolio",
    "SAE11": "🛡️ SAÉ Cyber", "SAE12": "🕸️ SAÉ Réseaux", "SAE13": "📡 SAÉ Trans.",
    "SAE14": "🌐 SAÉ Web", "SAE15": "📊 SAÉ Données", "SAE16": "📂 Portfolio",
    # SEMESTRE 2
    "R201": "☁️ Tech. Internet", "R202": "🛠️ Admin Sys", "R203": "📨 Services Réseaux",
    "R204": "☎️ Téléphonie", "R205": "🌊 Signaux Trans.", "R206": "🔢 Numérisation",
    "R207": "🗄️ Sources Données", "R208": "📊 Traitement Données", "R209": "🖼️ Dev Web",
    "R210": "🇺🇸 Anglais Tech.", "R211": "📢 Com. Pro.", "R212": "🧭 PPP",
    "R213": "➗ Maths Num.", "R214": "📉 Analyse Signaux",
    # SAE S2
    "SAE201": "🏢 SAÉ Réseau PME", "SAE202": "📏 SAÉ Mesure", "SAE203": "🏢 SAÉ Info Ent.",
    "SAE204": "🚀 SAÉ Projet", "SAE205": "📂 Portfolio",
    "SAE21": "🏢 SAÉ Réseau PME", "SAE22": "📏 SAÉ Mesure", "SAE23": "🏢 SAÉ Info Ent.",
    "SAE24": "🚀 SAÉ Projet", "SAE25": "📂 Portfolio"
}

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
log("⚙️ Analyse et calcul des IDs (Format V15)...")
try:
    c = Calendar(response.text)
except Exception as e:
    log(f"❌ ERREUR LECTURE ICS : {e}")
    sys.exit(1)

now_aware = datetime.datetime.now(datetime.timezone.utc)
events_payload_map = {} 
seen_days = set()

sorted_events = sorted(c.events, key=lambda x: x.begin)

for event in sorted_events:
    if not event.name: continue
    
    # Filtre Hack
    if not SHOW_HACK_CAMPUS and "hack ecampus" in event.name.lower():
        continue 
    
    event_start = event.begin.datetime if hasattr(event.begin, 'datetime') else event.begin
    event_end = event.end.datetime if hasattr(event.end, 'datetime') else event.end

    if event_start > now_aware:
        
        # --- LOGIQUE DE NOMMAGE ---
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
            
            nom_matiere = None
            for code, nom_propre in COURS_MAPPING.items():
                if code in search_zone_clean:
                    nom_matiere = nom_propre
                    break
            
            if not nom_matiere:
                nom_matiere = original_title
                if " - " in nom_matiere:
                    parts = nom_matiere.split(" - ", 1)
                    if len(parts) > 1 and len(parts[1]) > 2:
                        nom_matiere = parts[1].strip()

            # Emoji Type & Préfixe Texte
            emoji_type = "📅"
            prefix = ""
            
            desc_upper = (event.description or "").upper()
            
            if "EXAM" in search_zone or "EVALUATION" in search_zone or "PARTIEL" in search_zone or re.search(r'\bDS\b', search_zone): 
                emoji_type = "🚨"
                prefix = "Examen "
            elif "TP" in title_upper: 
                emoji_type = "💻"
            elif "TD" in title_upper: 
                emoji_type = "✏️"
            elif "CM" in title_upper or "AMPHI" in title_upper: 
                emoji_type = "🎤"
            elif "SOUTIEN" in title_upper: 
                emoji_type = "🆘"
            elif "ANGLAIS" in title_upper: 
                emoji_type = "🇬🇧"
            elif not any(x in title_upper for x in ["TP", "TD", "CM"]):
                if "TP" in desc_upper: emoji_type = "💻"
                elif "TD" in desc_upper: emoji_type = "✏️"
                elif "CM" in desc_upper: emoji_type = "🎤"

            final_summary = f"{emoji_type} {prefix}{nom_matiere}"

        # --- ID STABLE (V15 - "cal") ---
        # FIX: Pas d'underscore allowed par Google (0-9, a-v)
        id_str = f"cal_{final_summary}{event_start.isoformat()}"
        unique_id = "cal" + hashlib.md5(id_str.encode('utf-8')).hexdigest()

        # --- ALARME 1ER COURS ---
        day_key = event_start.strftime('%Y-%m-%d')
        reminders = {'useDefault': False, 'overrides': []}
        desc = (event.description or "").strip()

        if day_key not in seen_days:
            seen_days.add(day_key)
            reminders['overrides'].append({'method': 'popup', 'minutes': ALARM_MINUTES})
            desc = f"⏰ REVEIL ACTIVÉ\n\n{desc}"

        event_body = {
            'id': unique_id,
            'summary': final_summary,
            'location': event.location or "",
            'description': desc,
            'start': {'dateTime': event_start.isoformat()}, 
            'end': {'dateTime': event_end.isoformat()},
            'reminders': reminders
        }
        
        events_payload_map[unique_id] = event_body

# --- 4. GOOGLE SYNC (DIFFÉRENTIEL) ---
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

# Calcul des différences
ics_ids = set(events_payload_map.keys())
google_ids = set(google_events_map.keys())

def should_delete(ev_id):
    # Regex mise à jour pour inclure les IDs "cal" (V15) et "raw md5" (V13)
    if re.match(r'^(cal)?[a-f0-9]{32}$', ev_id):
        return True
    
    event = google_events_map.get(ev_id)
    if not event: return False
    
    desc = event.get('description', '') or ''
    summary = event.get('summary', '') or ''
    
    if "REVEIL" in desc or "PREMIER COURS" in desc:
        return True
    
    bot_emojis = ["🎤", "✏️", "💻", "📅", "🚨", "🚀", "🇬🇧", "🆘", "✨", "🛠️", "🚌"]
    if any(emoji in summary for emoji in bot_emojis):
        return True
        
    return False

ids_to_maybe_delete = google_ids - ics_ids
to_delete = {x for x in ids_to_maybe_delete if should_delete(x)}

ids_potential_update = google_ids & ics_ids
to_insert = ics_ids - google_ids

to_update = set()
skipped_updates = 0

for eid in ids_potential_update:
    new_data = events_payload_map[eid]
    old_data = google_events_map[eid]
    
    needs_update = False
    if new_data['summary'] != old_data.get('summary', ''): needs_update = True
    elif new_data['description'] != old_data.get('description', ''): needs_update = True
    elif new_data['location'] != old_data.get('location', ''): needs_update = True
    
    old_reminders = old_data.get('reminders', {})
    new_reminders = new_data['reminders']
    if old_reminders.get('useDefault') != new_reminders['useDefault']: needs_update = True

    if needs_update: to_update.add(eid)
    else: skipped_updates += 1

log(f"📊 Analyse : +{len(to_insert)} ajouts, -{len(to_delete)} suppressions, ~{len(to_update)} mises à jour.")

# --- 5. EXÉCUTION ---
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