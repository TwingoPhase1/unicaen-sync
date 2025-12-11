# 📅 Unicaen EDT Sync -\> Google Calendar

Ce projet est un outil d'automatisation (conçu pour tourner sur un Homelab/VPS) qui synchronise l'emploi du temps de l'Université de Caen (Zimbra/ADE) vers un Google Agenda dédié.

## ✨ Fonctionnalités

  * **Contournement de l'authentification :** Utilise `HTTPBasicAuth` pour télécharger le fichier `.ics` directement depuis l'ENT (plus besoin de liens publics qui expirent).
  * **Nettoyage des titres :** Transforme les titres illisibles (`GRP_RTRTA...`) en titres propres avec des émojis (🎓 CM, 📝 TD, 💻 TP, ⚠️ Examen).
  * **Synchronisation unidirectionnelle :** Met à jour Google Agenda toutes les X heures (via Cron) en supprimant les doublons.
  * **Dockerisé :** Prêt à être déployé n'importe où.

-----

## 🚀 Installation & Configuration (La partie importante)

Ce code ne fonctionne pas "tout seul", il a besoin de vos identifiants et d'un accès à l'API Google.

### 1\. Création du "Robot" Google (Service Account)

C'est l'étape la plus complexe, suivez bien les instructions :

1.  Allez sur la **[Google Cloud Console](https://console.cloud.google.com/)**.
2.  Créez un **Nouveau Projet** (ex: `Unicaen-Sync`).
3.  Allez dans **"API et services" \> "Bibliothèque"**, cherchez **"Google Calendar API"** et cliquez sur **ACTIVER**.
4.  Allez dans **"IAM et administration" \> "Comptes de service"**.
5.  Cliquez sur **"Créer un compte de service"**, donnez-lui un nom (ex: `bot-agenda`).
6.  Une fois créé, cliquez sur l'adresse email du robot (`bot-agenda@...iam.gserviceaccount.com`).
7.  Allez dans l'onglet **"CLÉS"** \> **Ajouter une clé** \> **Créer une nouvelle clé** \> **JSON**.
8.  Un fichier va se télécharger. **Renommez-le `credentials.json`** et placez-le à la racine du projet.

### 2\. Configuration de Google Agenda

Votre robot a besoin de la permission de modifier votre agenda.

1.  Créez un **nouvel agenda** (secondaire) sur Google Agenda (ne mélangez pas avec votre perso \!).
2.  Dans les **Paramètres et partage** de cet agenda, allez dans "Partager avec des personnes spécifiques".
3.  Ajoutez l'**adresse email du robot** (celle trouvée à l'étape 1).
4.  ⚠️ **Important :** Donnez-lui l'autorisation **"Apporter des modifications aux événements"**.
5.  Toujours dans les paramètres, descendez jusqu'à "Intégrer l'agenda" et copiez l'**ID de l'agenda** (ex: `c_xxxxxxxx@group.calendar.google.com`).

### 3\. Le fichier `.env`

Créez un fichier nommé `.env` à la racine du projet et remplissez-le avec vos informations :

```ini
# Le lien direct vers le fichier .ics de l'ENT (celui qui demande un mot de passe)
# Format habituel : https://ent.unicaen.fr/zimbra/user/votre.nom@unicaen.fr/Calendar.ics
ICS_URL=https://ent.unicaen.fr/zimbra/...../Calendar.ics

# Vos identifiants ENT (Numéro étudiant & Mot de passe)
ENT_USER=22xxxxx
ENT_PASS=votre_mot_de_passe_secret

# L'ID de l'agenda Google récupéré à l'étape 2
CALENDAR_ID=xxxxxxxx@group.calendar.google.com
```

> **⚠️ ATTENTION :** Ne committez JAMAIS le fichier `.env` ou `credentials.json` sur GitHub \! Ajoutez-les à votre `.gitignore`.

-----

## 🐳 Utilisation avec Docker

Une fois les fichiers `credentials.json` et `.env` présents :

### 1\. Construire l'image

```bash
docker build -t unicaen-sync .
```

### 2\. Lancer manuellement (pour tester)

```bash
docker run --rm --env-file .env unicaen-sync
```

### 3\. Automatisation (Cron)

Pour lancer la synchro tous les jours à midi et minuit, ajoutez ceci à votre crontab (`crontab -e`) :

```bash
0 0,12 * * * docker run --rm --env-file /chemin/absolu/vers/.env unicaen-sync >> /var/log/unicaen.log 2>&1
```

-----

## 🛠️ Structure du projet

  * `sync.py` : Le script principal Python.
  * `requirements.txt` : Les dépendances Python.
  * `Dockerfile` : La configuration pour construire le conteneur.
  * `.env` : Vos secrets (NON INCLUS).
  * `credentials.json` : La clé Google (NON INCLUSE).

-----

### ⚡ Credits

  * **Author:** [Ton Pseudo GitHub]
  * **Vibe coding assisted by Gemini 3 Pro** 🤖✨