# 📅 Unicaen EDT Sync v1.0

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://www.docker.com/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

> Un outil d'automatisation puissant conçu pour synchroniser votre emploi du temps universitaire (Zimbra/ADE) vers un Google Agenda dédié. Il transforme un calendrier brut et illisible en un agenda clair, propre et notifié.

## 📋 Table des matières

- [✨ Fonctionnalités](#-fonctionnalités)
- [🚀 Installation & Configuration](#-installation--configuration)
- [🛠️ Structure du Projet](#️-structure-du-projet)
- [⚡ Crédits](#-crédits)

## ✨ Fonctionnalités

| Fonctionnalité | Description |
|----------------|-------------|
| 🔓 Auth Bypass | Utilise HTTPBasicAuth pour s'authentifier directement sur ent.unicaen.fr, rendant obsolètes les liens ICS publics qui expirent tous les ans. |
| 🏷️ Smart Renaming | Transforme COURS - R107 en titres hybrides clairs : 💻🐍 TP Prog. Fondamentaux. Supporte un formatage spécial pour les examens : 🚨 Examen 🐍 Prog. |
| 🎨 Double Emojis | Ajoute un émoji pour le Type (🎤 Amphi, ✏️ TD, 💻 TP) et un pour la Matière (🐍 Prog, 📡 Trans, 🇬🇧 Anglais). |
| 🚨 Détection Examens | Identifie les DS, Partiels et Évaluations, ajoute un préfixe "Examen" et une alerte visuelle. |
| ⏰ Smart Alarms | Ajoute le tag 🔔 Premier cours de la journée dans la description du premier cours pour déclencher vos applications de réveil (ex: AMdroid). |
| ⚡ Differential Sync | Calcule un hash MD5 unique (cal_...) pour chaque cours. Ne modifie l'agenda que si l'événement a réellement changé (salle, horaire). |
| 🛡️ Safe Delete | Utilise des métadonnées privées (extendedProperties) pour identifier et supprimer uniquement les événements créés par le bot, sans jamais toucher à vos rendez-vous personnels. |
| 📝 Auto-Discovery | Détecte les codes matières inconnus (ex: R3.04) et les loggue dans un fichier missing_subjects.txt pour vous aider à compléter la configuration. |

## 🚀 Installation & Configuration

### 1. Prérequis

#### ☁️ Google Cloud Platform (GCP)
- Rendez-vous sur la [Google Cloud Console](https://console.cloud.google.com/).
- Créez un nouveau projet (ex: Unicaen-Sync).
- Allez dans "API et services" > "Bibliothèque", cherchez "Google Calendar API" et cliquez sur **ACTIVER**.
- Dans "IAM et administration" > "Comptes de service", créez un compte (ex: bot-agenda).
- Cliquez sur l'email du compte créé, onglet "CLÉS" > Ajouter une clé > JSON.
- Renommez le fichier téléchargé en `credentials.json` et placez-le dans le dossier du projet.

#### 📅 Configuration Agenda
- Créez un nouvel agenda (ne polluez pas votre agenda perso !).
- Dans **Paramètres et partage** > **Partager avec des personnes spécifiques**, ajoutez l'email du compte de service (celui en @...iam.gserviceaccount.com).
- ⚠️ **Important** : Sélectionnez l'autorisation "Apporter des modifications aux événements".
- Récupérez l'ID de l'agenda en bas de la page (section "Intégrer l'agenda").

#### 💻 Système
- Docker installé sur la machine.

### 2. Configuration (.env)

Créez un fichier `.env` à la racine :

```env
# 🔗 URL de l'ICS (Zimbra)
ICS_URL=https://ent.unicaen.fr/zimbra/user/votre.nom@unicaen.fr/Calendar.ics

# 👤 Identifiants ENT (Pour le téléchargement auth)
ENT_USER=22xxxxx
ENT_PASS=votre_mot_de_passe

# 📅 ID de l'agenda cible (Celui créé à l'étape 1)
CALENDAR_ID=xxxxxxxx@group.calendar.google.com

# ⚙️ Options Avancées
GOOGLE_PKEY_PATH=credentials.json
# Masquer les événements "Hack Ecampus" (true/false)
SHOW_HACK_CAMPUS=false
```

### 3. Dictionnaire (mapping.json)

Le fichier `mapping.json` à la racine contient les correspondances entre les codes (R101) et les noms affichés (Init. Réseaux). Vous pouvez l'éditer pour personnaliser les émojis et les noms des matières.

```json
{
  "R101": "🌐 Init. Réseaux",
  "SAE101": "🛡️ SAÉ Cyber"
}
```

### 4. Usage avec Docker

#### Build
```bash
docker build -t unicaen-sync .
```

#### Run (Test manuel)
Assurez-vous que `credentials.json` et `mapping.json` sont présents.
```bash
docker run --rm --env-file .env unicaen-sync
```

#### Automatisation (Crontab)
Pour lancer la synchronisation tous les jours à 00h, 06h, 12h et 15h :
```bash
0 0,6,12,15 * * * docker run --rm --env-file /home/user/unicaen-sync/.env unicaen-sync >> /home/user/unicaen.log 2>&1
```

## 🛠️ Structure du Projet

- `sync.py` : Script principal contenant toute la logique (V1.0).
- `Dockerfile` : Configuration de l'image Docker (Timezone Paris & Python 3.11).
- `requirements.txt` : Dépendances (ics, arrow, google-api, pytz...).
- `mapping.json` : Base de données des matières (éditable).
- `credentials.json` : Clé secrète Google (NON INCLUSE).
- `missing_subjects.txt` : Fichier généré automatiquement listant les codes matières trouvés mais non configurés.

## ⚡ Crédits

Vibe coding assisted by Gemini 3 Pro 🤖✨