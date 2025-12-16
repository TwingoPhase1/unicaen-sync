# 📅 Unicaen EDT Sync -> Google Calendar

![Python](https://img.shields.io/badge/Python-3.11-blue?style=for-the-badge&logo=python&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?style=for-the-badge&logo=docker&logoColor=white)
![Status](https://img.shields.io/badge/Status-Maintained-green?style=for-the-badge)

**Unicaen EDT Sync** est un outil d'automatisation puissant conçu pour synchroniser votre emploi du temps universitaire (Zimbra/ADE) vers un Google Agenda dédié. Il transforme un calendrier brut et illisible en un agenda clair, propre et notifié.

---

## ✨ Fonctionnalités

| Fonctionnalité | Description |
| :--- | :--- |
| 🔓 **Auth Bypass** | Utilise `HTTPBasicAuth` pour s'authentifier directement sur `ent.unicaen.fr`, rendant obsolètes les liens ICS publics qui expirent tous les ans. |
| 🏷️ **Smart Renaming** | **Exemple :** `COURS - R107 - GRP A` devient `🐍 Prog. Fondamentaux`. <br> Supporte les codes **R1xx** (S1), **R2xx** (S2) et **SAExx**. Ajoute des émojis contextuels (🇬🇧 Anglais, 🎤 CM, 💻 TP). |
| ⏰ **Smart Alarms** | Si activé, configure une notification *pop-up* **60 minutes** avant le début du **premier cours** de la journée uniquement. Idéal pour être réveillé sans spam. |
| ⚡ **Differential Sync** | Calcule le hash MD5 unique de chaque événement. Ne consomme du quota API Google que si l'événement a réellement changé (titre, salle, heure). |
| 🛠️ **Hack Filter** | Si `SHOW_HACK_CAMPUS=false`, supprime automatiquement les événements contenant "Hack Ecampus" pour garder l'agenda propre. |
| 🐳 **Docker Ready** | Image alpine ultra-légère (~50Mo). Timezone configurée sur `Europe/Paris` pour éviter les décalages horaires. |

---

## 🚀 Installation & Configuration

### 1. Prérequis

#### ☁️ Google Cloud Platform (GCP)
1.  Rendez-vous sur la [Google Cloud Console](https://console.cloud.google.com/).
2.  Créez un nouveau projet (ex: `Unicaen-Sync`).
3.  Allez dans **"API et services"** > **"Bibliothèque"**, cherchez **"Google Calendar API"** et cliquez sur **ACTIVER**.
4.  Dans **"IAM et administration"** > **"Comptes de service"**, créez un compte (ex: `bot-agenda`).
5.  Cliquez sur l'email du compte créé, onglet **"CLÉS"** > **Ajouter une clé** > **JSON**.
6.  Renommez le fichier téléchargé en `credentials.json` et placez-le dans le dossier du projet.

#### 📅 Configuration Agenda
1.  Créez un **nouvel agenda** (ne polluez pas votre agenda perso !).
2.  Dans **Paramètres et partage** > **Partager avec des personnes spécifiques**, ajoutez l'email du compte de service (celui en `@...iam.gserviceaccount.com`).
3.  ⚠️ **Important :** Sélectionnez l'autorisation **"Apporter des modifications aux événements"**.
4.  Récupérez l'**ID de l'agenda** en bas de la page (section "Intégrer l'agenda").

#### 💻 Système
*   **Docker** installé sur la machine.

### 2. Configuration (`.env`)
Créez un fichier `.env` à la racine :

```ini
# 🔗 URL de l'ICS (Zimbra)
ICS_URL=https://ent.unicaen.fr/zimbra/user/votre.nom@unicaen.fr/Calendar.ics

# 👤 Identifiants ENT (Pour le téléchargement auth)
ENT_USER=22xxxxx
ENT_PASS=votre_mot_de_passe

# 📅 ID de l'agenda cible (créez un agenda dédié !)
CALENDAR_ID=xxxxxxxx@group.calendar.google.com

# ⚙️ Options Avancées
# Chemin vers la clé Google (par défaut: credentials.json)
GOOGLE_PKEY_PATH=credentials.json
# Afficher ou masquer les événements "Hack Ecampus" (true/false)
SHOW_HACK_CAMPUS=false
```

### 3. Usage avec Docker

#### Build
```bash
docker build -t unicaen-sync .
```

#### Run (Test manuel)
Assurez-vous que `credentials.json` est présent dans le dossier.
```bash
docker run --rm --env-file .env -v $(pwd)/credentials.json:/app/credentials.json unicaen-sync
```

#### Automatisation (Crontab)
Pour lancer la synchronisation tous les jours à 6h00 et 18h00 :
```bash
0 6,18 * * * docker run --rm --env-file /abs/path/.env -v /abs/path/credentials.json:/app/credentials.json unicaen-sync >> /var/log/unicaen.log 2>&1
```

---

## 🛠️ Structure du Projet

*   `sync.py` : Script principal contenant toute la logique de parsing et de synchro.
*   `Dockerfile` : Configuration de l'image Docker (Timezone Paris configurée).
*   `requirements.txt` : Dépendances (`google-api-python-client`, `ics`, `requests`).
*   `credentials.json` : Clé secrète Google.

---
### ⚡ Credits
  * **Vibe coding assisted by Gemini 3 Pro** 🤖✨