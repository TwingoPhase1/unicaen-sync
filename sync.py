import requests
from requests.auth import HTTPBasicAuth
from ics import Calendar
from google.oauth2 import service_account
from googleapiclient.discovery import build
import datetime
import os
import sys
import re

# --- CONFIGURATION (Via variables d'environnement) ---
ICS_URL = os.getenv("ICS_URL")
USERNAME = os.getenv("ENT_USER")
PASSWORD = os.getenv("ENT_PASS")
CALENDAR_ID = os.getenv("CALENDAR_ID")
SERVICE_ACCOUNT_FILE = 'credentials.json'

# Petite sécurité
if not all([ICS_URL, USERNAME, PASSWORD, CALENDAR_ID]):
    print("❌ Erreur : Variables d'environnement manquantes dans le fichier .env")
    sys.exit(1)

# --- 1. TÉLÉCHARGEMENT ---
print(f"📥 Connexion à l'ENT...")

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

try:
    response = requests.get(ICS_URL, headers=headers, auth=HTTPBasicAuth(USERNAME, PASSWORD))
    response.raise_for_status()
    # Gestion encodage
    response.encoding = response.apparent_encoding if response.apparent_encoding else 'utf-8'
    print("✅ Fichier téléchargé !")
except Exception as e:
    print(f"❌ Erreur de téléchargement : {e}")
    sys.exit(1)

# --- 2. ANALYSE ET EMBELLISSEMENT ---
print("⚙️ Analyse et ajout des émojis...")
try:
    c = Calendar(response.text)
except Exception as e:
    print(f"❌ Erreur lecture ICS : {e}")
    sys.exit(1)

now_aware = datetime.datetime.now(datetime.timezone.utc)
events_to_add = []

for event in c.events:
    if not event.name or "hack ecampus" in event.name.lower():
        continue
    
    # --- LOGIQUE D'EMBELLISSEMENT AVANCÉE ---
    titre = event.name
    
    # 1. Nettoyage du préfixe administratif (GRP_...)
    # On cherche le motif " - " pour couper ce qu'il y a avant
    if " - " in titre:
        parts = titre.split(" - ", 1)
        if len(parts) > 1:
            titre = parts[1].strip() 
    
    # 2. Attribution des Emojis contextuels (BUT R&T)
    emoji = "📅" # Défaut
    
    titre_upper = titre.upper()
    desc_upper = (event.description or "").upper()

    # Logique de priorité : Examen > SAÉ > Types de cours > Matières
    if "EXAM" in titre_upper or "DS" in titre_upper or "EVALUATION" in titre_upper:
        emoji = "🚨" # Alerte pour examens
    elif "SAE" in titre_upper or "SAÉ" in titre_upper or "PROJET" in titre_upper:
        emoji = "🚀" # Fusée pour les SAÉ/Projets
    elif "TP" in titre_upper or "TP" in desc_upper:
        emoji = "💻" # Ordi pour les TP
    elif "TD" in titre_upper or "TD" in desc_upper:
        emoji = "✏️" # Crayon pour les TD
    elif "CM" in titre_upper or "CM" in desc_upper or "AMPHI" in titre_upper:
        emoji = "🎤" # Micro pour les Amphis
    elif "ANGLAIS" in titre_upper:
        emoji = "🇬🇧" # Drapeau
    elif "COMMUNICATION" in titre_upper or "EXPRESSION" in titre_upper:
        emoji = "🗣️" 
    elif "SOUTIEN" in titre_upper:
        emoji = "🆘" 
    elif "REUNION" in titre_upper or "ACCUEIL" in titre_upper:
        emoji = "ℹ️"

    # Titre final : Emojie + Titre nettoyé
    titre_final = f"{emoji} {titre}"

    # --- FIN LOGIQUE ---

    # Sécurisation date
    event_start = event.begin.datetime if hasattr(event.begin, 'datetime') else event.begin
    
    if event_start > now_aware:
        events_to_add.append({
            'summary': titre_final,
            'location': event.location,
            'description': event.description,
            'start': {'dateTime': event.begin.isoformat()}, 
            'end': {'dateTime': event.end.isoformat()},
        })

print(f"✅ {len(events_to_add)} cours futurs traités.")

# --- 3. GOOGLE SYNC ---
if not os.path.exists(SERVICE_ACCOUNT_FILE):
    print(f"❌ Erreur : {SERVICE_ACCOUNT_FILE} introuvable.")
    sys.exit(1)

creds = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=['https://www.googleapis.com/auth/calendar']
)
service = build('calendar', 'v3', credentials=creds)
now_str = now_aware.isoformat().replace("+00:00", "Z")

# SUPPRESSION
print("🧹 Nettoyage agenda...")
events_result = service.events().list(calendarId=CALENDAR_ID, timeMin=now_str, singleEvents=True, maxResults=2500).execute()
items_to_delete = events_result.get('items', [])

if items_to_delete:
    batch = service.new_batch_http_request()
    count_del = 0
    for e in items_to_delete:
        batch.add(service.events().delete(calendarId=CALENDAR_ID, eventId=e['id']))
        count_del += 1
        if count_del % 50 == 0:
            batch.execute()
            batch = service.new_batch_http_request()
    if count_del % 50 != 0: batch.execute()
    print(f"🗑️  {count_del} supprimés.")

# AJOUT
print(f"🚀 Envoi des {len(events_to_add)} cours...")
if events_to_add:
    batch = service.new_batch_http_request()
    count_add = 0
    for body in events_to_add:
        batch.add(service.events().insert(calendarId=CALENDAR_ID, body=body))
        count_add += 1
        if count_add % 50 == 0:
            batch.execute()
            batch = service.new_batch_http_request()
    if count_add % 50 != 0: batch.execute()

print("🎉 Terminé !")