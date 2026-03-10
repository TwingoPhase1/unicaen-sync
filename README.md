# 📅 Unicaen EDT Sync v5.0

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
| ⚡ Sync Rapide API | Utilisation de `SyncTokens` Google pour des requêtes delta extrêmement véloces. |
| 🛡️ Safe Delete | Métadonnées privées (`extendedProperties`) : le bot ne supprime jamais vos événements personnels. |
| 🔄 Support RRULE | Rendu complet et aplatissement des événements récurrents (`icalendar`). |
| 📝 Auto-Discovery | Codes matières inconnus loggés dans `missing_subjects.txt`. |
| 🔁 Mode Full | `--full` pour resync tous les événements, passés inclus (ignore le jeton de sync rapide). |
| 📧 Mail Sync Bypass | `--mail` Scrappe les modifications urgentes envoyées par la scolarité avec protection `UIDVALIDITY`. |
| 🔔 Alerte Discord | Reçois un ping sur Discord (avec mention de rôle personnalisée via regex) lors d'un ajout de salle, changement d'horaire, ou d'annulation (détecte "Annulé" dans le `.ics` ET dans l'objet de l'e-mail). |
| 🧪 Mode Dry-Run | `--dry-run` pour tester le script et voir les diffs sans rien modifier sur Google Calendar ni localement. |

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

# (Optionnel) Pour synchroniser les changements via mail
IMAP_SERVER=zcs.unicaen.fr
IMAP_USER=prenom.nom@etu.unicaen.fr
IMAP_PASS=votre_mot_de_passe

# (Optionnel) Pour recevoir une notification Discord lors d'un changement de cours
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
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

### 5. Pings Discord (discord_roles.json)

Pour que la notification Discord mentionne des rôles spécifiques selon les cours (pratique pour notifier uniquement le groupe TD ou TP concerné), créez un fichier `discord_roles.json` à la racine :

```json
{
  "TD\\s*1": "123456789012345678",
  "TP\\s*[12]": "987654321098765432",
  "CM": "555555555555555555"
}
```

- La clé est une **Expression Régulière** (Regex) qui sera cherchée dans le titre et la description du cours modifié.
- La valeur est l'**ID du rôle Discord** à ping.
- S'il n'y a pas de fichier ou pas de correspondance, le message est quand même envoyé sans ping.

## 🐳 Usage Docker

```bash
# Build
docker build -t unicaen-sync .

# Run (événements futurs uniquement, avec SyncTokens rapides)
docker run --rm --env-file .env unicaen-sync

# Run (TOUS les événements, passés inclus)
docker run --rm --env-file .env unicaen-sync python sync.py --full

# Run (Test sans rien modifier - Dry-Run)
docker run --rm --env-file .env unicaen-sync python sync.py --dry-run

# Run (Vérification et réconciliation via Mail UNIQUEMENT)
docker run --rm --env-file .env unicaen-sync python sync.py --mail

# Run (Spécial: Tester le Webhook Discord)
# Envoie 3 fausses alertes sur votre serveur Discord pour valider le webhook et les pings de rôles du discord_roles.json
docker run --rm --env-file .env unicaen-sync python sync.py --test-discord
```

### Automatisation (Crontab optimisé)

Il est recommandé de lancer le script de base (`--mail`) fréquemment pour les mises à jour de salles, et un `--full` une fois par jour au cas où Zimbra se met à jour silencieusement dans le passé :

```bash
# Vérification des nouveaux mails uniquement (extrêmement rapide) - Toutes les 15 mins (de 7h à 20h)
*/15 07-20 * * * docker run --rm --env-file /chemin/vers/.env unicaen-sync python sync.py --mail >> /chemin/vers/unicaen-mail.log 2>&1

# Synchro complète avec l'ADE Zimbra - Tous les jours à 02h00
0 2 * * * docker run --rm --env-file /chemin/vers/.env unicaen-sync python sync.py --full >> /chemin/vers/unicaen-full.log 2>&1
```

## 📁 Structure

| Fichier | Rôle |
|---------|------|
| `sync.py` | Script principal V5.0 |
| `mapping.json` | Matières : emoji + couleur + coefficients |
| `discord_roles.json` | (Optionnel) Mapping Regex → Discord Role ID |
| `Dockerfile` | Image Docker (Python 3.11, TZ Paris) |
| `requirements.txt` | Dépendances Python |
| `credentials.json` | Clé Google (**non incluse**, à créer) |
| `.env` | Configuration (**non incluse**, à créer) |
| `.gitignore` | Exclut secrets et fichiers générés |

## ⚡ Crédits

Vibe coding assisted by Gemini 2.5 Pro 🤖✨