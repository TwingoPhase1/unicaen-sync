import requests
from requests.auth import HTTPBasicAuth
from ics import Calendar
from google.oauth2 import service_account
from googleapiclient.discovery import build
import datetime
import os
import sys
import re

# --- FONCTION DE LOG PERSONNALISÉE ---
def log(msg):
    # Affiche l'heure actuelle précise [YYYY-MM-DD HH:MM:SS] devant chaque message
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {msg}")
    sys.stdout.flush() # Force l'affichage immédiat dans Docker

# --- CONFIGURATION ---
ICS_URL = os.getenv("ICS_URL")
USERNAME = os.getenv("ENT_USER")
PASSWORD = os.getenv("ENT_PASS")
CALENDAR_ID = os.getenv("CALENDAR_ID")
SERVICE_ACCOUNT_FILE = 'credentials.json'
ALARM_MINUTES = 60 

# --- DICTIONNAIRE BUT R&T ---
COURS_MAPPING = {
    # SEMESTRE 1
    "R101": "🌐 Init. Réseaux",
    "R102": "🔌 Archi. Réseaux",
    "R103": "🏢 Réseaux Locaux",
    "R104": "⚡ Syst. Élec.",
    "R105": "📡 Supports Trans.",
    "R106": "💾 Archi. Numérique",
    "R107": "🐍 Prog. C++",
    "R108": "🐧 Syst. Linux",
    "R109": "🌍 Tech. Web",
    "R110": "🇬🇧 Anglais",
    "R111": "🗣️ Com. Pro.",
    "R112": "🤝 PPP",
    "R113": "📐 Maths Signal",
    "R114": "📈 Maths Trans.",
    "R115": "📅 Gestion Projet",
    "SAE11": "🛡️ SAÉ Cyber",
    "SAE12": "🕸️ SAÉ Réseaux",
    "SAE13": "📡 SAÉ Trans.",
    "SAE14": "🌐 SAÉ Web",
    "SAE15": "📊 SAÉ Données",
    "SAE16": "📂 Portfolio",
    # SEMESTRE 2
    "R201": "☁️ Tech. Internet",
    "R202": "🛠️ Admin Sys & Virtu",
    "R203": "📨 Services Réseaux",
    "R204": "☎️ Téléphonie",
    "R205": "🌊 Signaux Trans.",
    "R206": "🔢 Numérisation",
    "R207": "🗄️ Sources Données",
    "R208": "📊 Traitement Données",
    "R209": "🖼️ Dev Web",
    "R210": "🇺🇸 Anglais",
    "R211": "📢 Com. Pro.",
    "R212": "🧭 PPP",
    "R213": "➗ Maths Num.",
    "R214": "📉 Analyse Signaux",
    "SAE21": "🏢 SAÉ Réseau PME",
    "SAE22": "📏 SAÉ Mesure",
    "SAE23": "🏢 SAÉ Info Ent.",
    "SAE24": "🚀 SAÉ Projet Intégratif",
    "SAE25": "📂 Portfolio"
}

if not all([ICS_URL, USERNAME, PASSWORD, CALENDAR_ID]):
    log("❌ CRITIQUE : Variables d'environnement manquantes (.env)")
    sys.exit(1)

# --- 1. TÉLÉCHARGEMENT ---
log(f"📥 Démarrage du script - Connexion à l'ENT...")
headers = {"User-Agent": "Mozilla/5.0"}

try:
    response = requests.get(ICS_URL, headers=headers, auth=HTTPBasicAuth(USERNAME, PASSWORD))
    response.raise_for_status()
    response.encoding = response.apparent_encoding if response.apparent_encoding else 'utf-8'
    log(f"✅ Fichier ICS téléchargé ({len(response.text)} octets).")
except Exception as e:
    log(f"❌ ERREUR TÉLÉCHARGEMENT : {e}")
    sys.exit(1)

# --- 2. TRAITEMENT ---
log("⚙️ Analyse du fichier et conversion R&T...")
try:
    c = Calendar(response.text)
except Exception as e:
    log(f"❌ ERREUR LECTURE ICS : {e}")
    sys.exit(1)

now_aware = datetime.datetime.now(datetime.timezone.utc)
temp_events = []

for event in c.events:
    if not event.name or "hack ecampus" in event.name.lower():
        continue
    
    event_start = event.begin.datetime if hasattr(event.begin, 'datetime') else event.begin
    if event_start > now_aware:
        
        raw_title = event.name
        # Nettoyage
        if " - " in raw_title:
            parts = raw_title.split(" - ", 1)
            if len(parts) > 1:
                raw_title = parts[1].strip()

        # Identification Matière
        title_key = raw_title.upper().replace(" ", "").replace(".", "")
        nom_matiere = raw_title 
        for code, nom_propre in COURS_MAPPING.items():
            if code in title_key:
                nom_matiere = nom_propre
                break 

        # Identification Type
        emoji_type = "📅"
        full_info = (event.name + " " + (event.description or "")).upper()

        if "EXAM" in full_info or "DS" in full_info or "EVALUATION" in full_info:
            emoji_type = "🚨"
        elif "TP" in full_info:
            emoji_type = "💻"
        elif "TD" in full_info:
            emoji_type = "✏️"
        elif "CM" in full_info or "AMPHI" in full_info:
            emoji_type = "🎤"
        elif "SOUTIEN" in full_info:
            emoji_type = "🆘"
        elif "SAE" in title_key:
            emoji_type = "🚀"

        final_summary = f"{emoji_type} {nom_matiere}"

        temp_events.append({
            'original_start': event_start,
            'summary': final_summary,
            'location': event.location,
            'description': event.description,
            'start': {'dateTime': event.begin.isoformat()}, 
            'end': {'dateTime': event.end.isoformat()},
            'day_key': event_start.strftime('%Y-%m-%d')
        })

# --- TRI ET ALARME ---
temp_events.sort(key=lambda x: x['original_start'])
events_to_add = []
seen_days = set()

for evt in temp_events:
    day = evt['day_key']
    reminders = {'useDefault': False, 'overrides': []}
    
    if day not in seen_days:
        seen_days.add(day)
        reminders['overrides'].append({'method': 'popup', 'minutes': ALARM_MINUTES})
        evt['description'] = (evt['description'] or "") + "\n\n⏰ REVEIL 1H AVANT"
    
    events_to_add.append({
        'summary': evt['summary'],
        'location': evt['location'],
        'description': evt['description'],
        'start': evt['start'],
        'end': evt['end'],
        'reminders': reminders
    })

# --- STATISTIQUES LOG ---
if events_to_add:
    start_date = events_to_add[0]['start']['dateTime']
    end_date = events_to_add[-1]['start']['dateTime']
    log(f"📊 Analyse terminée : {len(events_to_add)} cours trouvés.")
    log(f"📅 Période couverte : Du {start_date} au {end_date}")
else:
    log("⚠️ Aucun cours trouvé pour le futur.")

# --- 3. GOOGLE SYNC ---
if not os.path.exists(SERVICE_ACCOUNT_FILE):
    log(f"❌ ERREUR : {SERVICE_ACCOUNT_FILE} introuvable.")
    sys.exit(1)

creds = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=['https://www.googleapis.com/auth/calendar']
)
service = build('calendar', 'v3', credentials=creds)
now_str = now_aware.isoformat().replace("+00:00", "Z")

# SUPPRESSION
log("🧹 Nettoyage de l'agenda Google...")
try:
    events_result = service.events().list(calendarId=CALENDAR_ID, timeMin=now_str, singleEvents=True, maxResults=2500).execute()
    items_to_delete = events_result.get('items', [])
except Exception as e:
    log(f"❌ ERREUR GOOGLE API (LIST): {e}")
    sys.exit(1)

count_del = 0
if items_to_delete:
    batch = service.new_batch_http_request()
    for e in items_to_delete:
        batch.add(service.events().delete(calendarId=CALENDAR_ID, eventId=e['id']))
        count_del += 1
        if count_del % 50 == 0:
            batch.execute()
            batch = service.new_batch_http_request()
    if count_del % 50 != 0: batch.execute()
    log(f"🗑️  {count_del} anciens événements supprimés.")
else:
    log("ℹ️  Aucun événement à supprimer.")

# AJOUT
log(f"🚀 Envoi des {len(events_to_add)} nouveaux cours...")
count_add = 0
if events_to_add:
    batch = service.new_batch_http_request()
    for body in events_to_add:
        batch.add(service.events().insert(calendarId=CALENDAR_ID, body=body))
        count_add += 1
        if count_add % 50 == 0:
            batch.execute()
            batch = service.new_batch_http_request()
    if count_add % 50 != 0: batch.execute()

log(f"🎉 SUCCÈS : Synchronisation terminée. (Ajoutés: {count_add} / Supprimés: {count_del})")