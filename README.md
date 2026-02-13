# 📅 Unicaen EDT Sync v3.0

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://www.docker.com/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

> Synchronise automatiquement votre emploi du temps universitaire (Zimbra/ADE) vers Google Agenda, avec des titres enrichis, des couleurs par matière et des coefficients intégrés.

## ✨ Fonctionnalités

| Fonctionnalité | Description |
|----------------|-------------|
| 🔓 Auth ENT | HTTPBasicAuth sur `ent.unicaen.fr` — pas besoin de lien ICS public qui expire. |
| 🏷️ Smart Renaming | Transforme `R107 - COURS` en `💻🐍 TP Prog. Fondamentaux`. |
| 🎨 Double Emojis | Type (🎤 CM, ✏️ TD, 💻 TP) + Matière (🐍 Prog, 📡 Trans, 🇬🇧 Anglais). |
| 🌈 Couleurs | Chaque domaine a sa couleur Google Calendar (cyan=Réseaux, rose=Télécoms, bleu=Prog, etc.). |
| 📊 Coefficients | Affichés dans la description avec le détail par UE et le total. |
| 🚨 Détection Examens | Préfixe `🚨 Examen` + couleur rouge automatique (DS, Partiels, Évaluations). |
| ⏰ Smart Alarms | Tag `🔔 Premier cours de la journée` pour les applications de réveil. |
| ⚡ Sync Différentielle | Hash MD5 stable par événement — ne touche que ce qui a changé. |
| 🛡️ Safe Delete | Métadonnées privées (`extendedProperties`) : le bot ne supprime jamais vos événements personnels. |
| 📝 Auto-Discovery | Codes matières inconnus loggés dans `missing_subjects.txt`. |
| 🔁 Mode Full | `--full` pour resync tous les événements, passés inclus. |

## 🚀 Installation

### 1. Google Cloud Platform

1. [Google Cloud Console](https://console.cloud.google.com/) → Créer un projet
2. Activer **Google Calendar API**
3. Créer un **Compte de service** → Télécharger la clé JSON → Renommer en `credentials.json`

### 2. Google Agenda

1. Créer un nouvel agenda dédié
2. **Paramètres et partage** → Partager avec l'email du compte de service (`@...iam.gserviceaccount.com`)
3. Permission : **Apporter des modifications aux événements**
4. Récupérer l'**ID de l'agenda** (section "Intégrer l'agenda", en bas)

### 3. Configuration (.env)

```env
ICS_URL=https://ent.unicaen.fr/zimbra/user/prenom.nom@etu.unicaen.fr/Calendar.ics
ENT_USER=22xxxxx
ENT_PASS=votre_mot_de_passe
CALENDAR_ID=xxxxxxxx@group.calendar.google.com
SHOW_HACK_CAMPUS=true
```

### 4. Dictionnaire (mapping.json)

Format riche avec emoji, couleur Google et coefficients par UE :

```json
{
  "R107": {
    "name": "Prog. Fondamentaux",
    "emoji": "🐍",
    "color": "9",
    "coefs": {"UE1.3": 19}
  }
}
```

<details>
<summary>Couleurs disponibles (colorId)</summary>

| colorId | Couleur | Usage |
|---------|---------|-------|
| `1` | Lavande | SAÉ |
| `2` | Sauge | Maths |
| `3` | Raisin | Systèmes |
| `4` | Flamant | Télécoms |
| `5` | Banane | Anglais |
| `6` | Mandarine | Com/PPP |
| `7` | Paon | Réseaux |
| `8` | Graphite | Spéciaux |
| `9` | Myrtille | Prog/Web |
| `10` | Basilic | Gestion Projet |
| `11` | Tomate | Examens |

</details>

## 🐳 Usage Docker

```bash
# Build
docker build -t unicaen-sync .

# Run (événements futurs uniquement)
docker run --rm --env-file .env unicaen-sync

# Run (TOUS les événements, passés inclus)
docker run --rm --env-file .env unicaen-sync python sync.py --full
```

### Automatisation (Crontab)

Sync à 00h, 06h, 12h et 15h :
```bash
0 0,6,12,15 * * * docker run --rm --env-file /chemin/vers/.env unicaen-sync >> /chemin/vers/unicaen.log 2>&1
```

## 📁 Structure

| Fichier | Rôle |
|---------|------|
| `sync.py` | Script principal V3.0 |
| `mapping.json` | Matières : emoji + couleur + coefficients |
| `Dockerfile` | Image Docker (Python 3.11, TZ Paris) |
| `requirements.txt` | Dépendances Python |
| `credentials.json` | Clé Google (**non incluse**, à créer) |
| `.env` | Configuration (**non incluse**, à créer) |
| `.gitignore` | Exclut secrets et fichiers générés |

## ⚡ Crédits

Vibe coding assisted by Gemini 2.5 Pro 🤖✨