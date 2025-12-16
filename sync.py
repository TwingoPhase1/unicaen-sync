import requests
from requests.auth import HTTPBasicAuth
from ics import Calendar
from google.oauth2 import service_account
from googleapiclient.discovery import build
import datetime
import os
import sys
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
SERVICE_ACCOUNT_FILE = 'credentials.json'
ALARM_MINUTES = 60 

# Gestion de l'option Hack Ecampus (par défaut : affiché si pas précisé)
show_hack_env = os.getenv("SHOW_HACK_CAMPUS", "true").lower()
SHOW_HACK_CAMPUS = show_hack_env in ["true", "1", "yes", "on"]

if not SHOW_HACK_CAMPUS:
    log("ℹ️ Info : Les événements 'Hack Ecampus' seront masqués.")

# --- 1. MOTS-CLÉS SPÉCIAUX (On ne touche pas au titre) ---
SPECIAL_KEYWORDS = [
    "HACK", "SORTIE", "VISITE", "CONFÉRENCE", "ATELIER", 
    "FORUM", "RENCONTRE", "JPO", "SALON", "DÉFI", "CHALLENGE",
    "RÉUNION DE RENTRÉE", "PETIT DÉJEUNER", "SHOOTING", "OUVERTURE"
]

# --- 2. DICTIONNAIRE MATIÈRES AVEC EMOJIS ---
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

if not all([ICS_URL, USERNAME, PASSWORD, CALENDAR_ID]):
    log("❌ CRITIQUE : .env incomplet")
    sys.exit(1)

# --- TÉLÉCHARGEMENT ---
log(f"📥 Connexion à l'ENT...")
headers = {"User-Agent": "Mozilla/5.0"}
try:
    response = requests.get(ICS_URL, headers=headers, auth=HTTPBasicAuth(USERNAME, PASSWORD))
    response.raise_for_status()
    response.encoding = response.apparent_encoding if response.apparent_encoding else 'utf-8'
    log(f"✅ Fichier téléchargé.")
except Exception as e:
    log(f"❌ ERREUR TÉLÉCHARGEMENT : {e}")
    sys.exit(1)

# --- TRAITEMENT ---
log("⚙️ Analyse V12 (Filtres & Emojis)...")
try:
    c = Calendar(response.text)
except Exception as e:
    log(f"❌ ERREUR LECTURE ICS : {e}")
    sys.exit(1)

now_aware = datetime.datetime.now(datetime.timezone.utc)
temp_events = []

for event in c.events:
    if not event.name: continue
    
    # --- FILTRE HACK ECAMPUS ---
    if not SHOW_HACK_CAMPUS and "hack ecampus" in event.name.lower():
        continue # On saute cet événement, il ne sera pas ajouté
    
    event_start = event.begin.datetime if hasattr(event.begin, 'datetime') else event.begin
    if event_start > now_aware:
        
        original_title = event.name.strip()
        final_summary = original_title
        
        # --- ETAPE A : ÉVÉNEMENT SPÉCIAL ? ---
        title_upper = original_title.upper()
        is_special = any(keyword in title_upper for keyword in SPECIAL_KEYWORDS)
        
        if is_special:
            emoji = "✨"
            if "HACK" in title_upper: emoji = "🛠️"
            elif "SORTIE" in title_upper or "VISITE" in title_upper: emoji = "🚌"
            elif "EXAM" in title_upper: emoji = "🚨"
            final_summary = f"{emoji} {original_title}"
            
        else:
            # --- ETAPE B : COURS CLASSIQUE ---
            
            # 1. Identification de la Matière (Emoji #2)
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

            # 2. Identification du Type (Emoji #1)
            emoji_type = "📅"
            desc_upper = (event.description or "").upper()
            
            if "EXAM" in search_zone or "DS" in search_zone: emoji_type = "🚨"
            elif "TP" in title_upper: emoji_type = "💻"
            elif "TD" in title_upper: emoji_type = "✏️"
            elif "CM" in title_upper or "AMPHI" in title_upper: emoji_type = "🎤"
            elif "SOUTIEN" in title_upper: emoji_type = "🆘"
            elif "ANGLAIS" in title_upper: emoji_type = "🇬🇧"
            elif not any(x in title_upper for x in ["TP", "TD", "CM"]):
                if "TP" in desc_upper: emoji_type = "💻"
                elif "TD" in desc_upper: emoji_type = "✏️"
                elif "CM" in desc_upper: emoji_type = "🎤"

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

# --- GOOGLE SYNC ---
if not os.path.exists(SERVICE_ACCOUNT_FILE):
    log(f"❌ ERREUR : {SERVICE_ACCOUNT_FILE} introuvable.")
    sys.exit(1)

creds = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=['https://www.googleapis.com/auth/calendar']
)
service = build('calendar', 'v3', credentials=creds)
now_str = now_aware.isoformat().replace("+00:00", "Z")

# SUPPRESSION
log("🧹 Nettoyage agenda...")
try:
    events_result = service.events().list(calendarId=CALENDAR_ID, timeMin=now_str, singleEvents=True, maxResults=2500).execute()
    items_to_delete = events_result.get('items', [])
except Exception as e:
    log(f"❌ ERREUR API : {e}")
    sys.exit(1)

if items_to_delete:
    batch = service.new_batch_http_request()
    count = 0
    for e in items_to_delete:
        batch.add(service.events().delete(calendarId=CALENDAR_ID, eventId=e['id']))
        count += 1
        if count % 50 == 0:
            batch.execute()
            batch = service.new_batch_http_request()
    if count % 50 != 0: batch.execute()
    log(f"🗑️  {count} supprimés.")

# AJOUT
log(f"🚀 Envoi des {len(events_to_add)} nouveaux cours...")
if events_to_add:
    batch = service.new_batch_http_request()
    count = 0
    for body in events_to_add:
        batch.add(service.events().insert(calendarId=CALENDAR_ID, body=body))
        count += 1
        if count % 50 == 0:
            batch.execute()
            batch = service.new_batch_http_request()
    if count % 50 != 0: batch.execute()
    log(f"🎉 SUCCÈS : {count} ajoutés.")
else:
    log("🎉 Terminé (Rien à ajouter).")