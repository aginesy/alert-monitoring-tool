# Projet Alerting - Mattermost & Suivi Confluence

Ce projet permet de collecter les alertes et messages Mattermost postés sur un canal spécifique sur une période donnée (en nombre d'heures), de synchroniser un registre d'actions sur **Confluence** pour le point de suivi, et de générer un rapport synthétique au format HTML comprenant :
- Un **suivi des actions par catégorie d'alerte** synchronisé avec Confluence (statuts, actions décidées en réunion, porteur).
- Une **synthèse par catégorie d'alerte** indiquant le nombre d'occurrences sur la plage sélectionnée et l'évolution globale.
- Une **frise chronologique continue** et dépliable par catégorie d'alerte.
- Le **détail chronologique complet** de l'ensemble des alertes collectées.

---

## 📋 Suivi d'actions sur Confluence (Point de suivi)

Le projet intègre un registre de suivi interactif stocké sur une page Confluence dédiée :
- **Consignation des décisions** : Lors du point de suivi, l'équipe renseigne directement sur la page Confluence les colonnes *Statut*, *Porteur*, *Échéance* et *Actions décidées*.
- **Colonnes du tableau Confluence** :
  1. **Statut** (`NOUVELLE`, `PTPNEL`, `EN COURS`, `RÉSOLUE`, `RÉCURRENTE`, `BRUIT`)
  2. **Catégorie d'alerte** (avec ancre de navigation)
  3. **Occurrences** (nombre de la semaine)
  4. **Date de la dernière apparition de l'alerte dans Mattermost** (pastille date native Confluence + heure)
  5. **Porteur** (responsable de l'action)
  6. **Échéance** (date cible de résolution, renseignée au besoin)
  7. **Actions décidées (Point de suivi)** (décisions et historique d'équipe)
- **To-Do Point de Suivi** : Un encart synthétique placé directement au-dessus de la palette rappelle les 4 actions réflexes à mener en réunion hebdomadaire (Récurrentes ➔ Nouvelles ➔ Arbitrage PTPNEL ➔ Clôture En cours).
- **Palette de statuts rapide** : Un encart en tête de page permet de copier/coller en un clic (`Ctrl+C` / `Ctrl+V`) les pastilles de couleur officielles (`EN COURS`, `RÉSOLUE`, `NOUVELLE`, `PTPNEL`, `RÉCURRENTE`, `BRUIT`) sans aucune saisie texte.
- **Tableau dédié aux alertes de bruit** : Situé directement sous le tableau principal, ce second tableau regroupe et isole les alertes dont le statut a été positionné manuellement sur `BRUIT` (anomalies récurrentes connues qu'on ne peut pas désactiver, comme une épine dans le pied), évitant de polluer le tableau de suivi nominal.
- **Réconciliation automatique** : À chaque nouveau rapport (le lundi suivant), le script relit la page Confluence, préserve fidèlement les actions, porteurs et échéances déjà saisis, et enrichit le tableau avec les nouvelles occurrences.
- **Normalisation intelligente** : Évite les doublons de catégories causés par les métriques variables (ex : `(current : 91)`) ou les identifiants éphémères de pods Kubernetes (ex : suffixes de réplicas `-8578c8c7ff-wld7g`).

---

### 🔄 Cycle de vie et Workflows des alertes

```text
             ┌─────────────────── Détection initiale (Semaine S) ───────────────────┐
             │                                                                      │
             ▼                                                                      ▼
    [ 🔹 NOUVELLE ]                                                       [ 🔺 RÉCURRENTE ]
             │                                                                      ▲
   ┌─────────┴───────────────────────┐                                              │
   │ Aucune action prise             │ Action définie / Porteur                     │
   ▼                                 ▼                                              │
[ ⚪ PTPNEL ] ────────────► [ 🔸 EN COURS ] ──(Fix validé)──► [ ✅ RÉSOLUE ]        │
   │                                 │                              │               │
   │  Au bout de 4 sem.              │ (Positionné manuellement)    │ > 1 mois      │
   ├─► ⚠️ Avertissement (J-X)        ▼                              ▼               │
   │                           [ 🟤 BRUIT ] (Tableau dédié)   [ 📦 ARCHIVE ] ───────┘
   │  Plus de 1 mois                                                (Rechute si retour)
   ▼
[ 🗑️ Purge définitive ]
```

| Statut | Rôle | Action de l'équipe en réunion |
| :--- | :--- | :--- |
| 🔹 **`NOUVELLE`** | Alerte identifiée pour la 1ère fois cette semaine | Qualifier l'anomalie, désigner un porteur et définir l'action ➔ passer en **`EN COURS`**. |
| ⚪ **`PTPNEL`** | Pas traitée, pas nouvelle, encore là | Traiter en réunion : définir l'action et le porteur ➔ passer en **`EN COURS`**. *Au bout de 4 semaines sans prise en charge, un avertissement avec décompte s'affiche sous le statut. Au-delà de 1 mois sans changement de statut, la ligne est automatiquement purgée du tableau Confluence.* |
| 🔸 **`EN COURS`** | Plan d'action en cours d'exécution | Suivre l'avancement. Si le correctif est déployé/validé ➔ passer en **`RÉSOLUE`**. |
| ✅ **`RÉSOLUE`** | Problème corrigé et validé | Aucune action requise. Déplacée dans la page d'archive après 1 mois sans réapparition. |
| 🔺 **`RÉCURRENTE`** | **Rechute automatique !** | Analyser la régression en priorité, définir un correctif ➔ repasser en **`EN COURS`**. |
| 🟤 **`BRUIT`** | Alerte connue incompressible (épine dans le pied) | Positionné manuellement dans Confluence (pastille marron). Déplacée automatiquement par le script dans le tableau des alertes de bruit sous le tableau principal. |

#### Les 5 Workflows types :
1. **Cycle nominal (Nouveau problème)** :
   `NOUVELLE` (détection script) ➔ Saisie action & porteur ➔ `EN COURS` ➔ Déploiement correctif ➔ `RÉSOLUE`.
2. **Cycle de régression (Rechute post-résolution)** :
   `RÉSOLUE` ➔ Nouvelles alertes collectées ➔ **Bascule automatique en `RÉCURRENTE` par le script** ➔ Réanalyse en réunion ➔ `EN COURS`.
3. **Cycle d'observation (0 alerte sur la semaine écoulée)** :
   Si une alerte `EN COURS` n'a eu aucune occurrence (`0 cette semaine`), sa fiche est **intégralement conservée**. L'équipe décide de la passer en `RÉSOLUE` si le fix est validé, ou de la laisser en `EN COURS` pour observation.
4. **Alertes de bruit incompressible** :
   Positionnement manuel sur `BRUIT` ➔ Le script place l'alerte dans le tableau secondaire dédié sous le tableau principal.
5. **Fausse alerte ou anomalie sans suite** :
   Passage direct en `RÉSOLUE` avec mention du motif dans la colonne actions (*Faux positif - seuil ajusté* ou *Maintenance planifiée*).

---

### 🌐 Architecture des 3 Pages Confluence Interconnectées

Le dispositif s'articule autour de 3 pages Confluence complémentaires et interconnectées :

| Page Confluence | Rôle principal | Variable d'environnement | Identifiant par défaut |
| :--- | :--- | :--- | :--- |
| **1. Page Principale (Point de suivi)** | Tableau actif de qualification des alertes, tableau secondaire des alertes de bruit, consignes, palette et indicateurs. | `CONFLUENCE_PAGE_ID` | `123456789` |
| **2. Page d'Archive (Résolues > 1 mois)** | Historique pérenne des décisions sur les alertes résolues de longue date (6 colonnes sans statut). | `CONFLUENCE_ARCHIVE_PAGE_ID` | `123456780` |
| **3. Page de Statistiques (Évolution)** | Journal de bord hebdomadaire consignant l'évolution des métriques semaine par semaine (12 colonnes dont PTPNEL supprimées &gt; 1 mois et rapport HTML en PJ). | `CONFLUENCE_STATS_PAGE_ID` | `123456781` |

- **Navigation croisée automatique** :
  - La page principale propose des liens directs vers l'archive, les statistiques et le rapport visuel GitLab.
  - La page d'archive et la page de statistiques disposent d'un lien de retour immédiat vers le tableau de bord actif.
- **Automatisme du cycle de vie** :
  - **Archivage pérenne** : Les alertes `RÉSOLUE` depuis plus de 1 mois sans réapparition sont déplacées sur la page d'archive (et reviennent en `RÉCURRENTE` sur la page active si l'anomalie se reproduit).
  - **Avertissement et purge PTPNEL** : Les alertes `PTPNEL` sans prise en charge affichent un avertissement à 4 semaines avec compte à rebours, et sont supprimées du tableau actif après 1 mois.
  - **Isolation du Bruit** : Les alertes au statut `BRUIT` sont automatiquement regroupées dans le tableau secondaire situé sous le tableau principal.

---

## 📁 Arborescence du projet

```text
alerting/
├── .gitlab-ci.yml              # Pipeline GitLab CI/CD (automatisation hebdomadaire)
├── main.py                     # Point d'entrée de l'application
├── requirements.txt            # Dépendances requises (requests, Jinja2, python-dotenv, beautifulsoup4)
├── .env.example                # Exemple de configuration d'environnement
├── README.md                   # Documentation du projet
├── config/
│   ├── config.py               # Chemins des templates, valeurs par défaut et fichiers de sortie
│   ├── config_mattermost.py    # Chargement des identifiants et configuration Mattermost
│   └── config_confluence.py    # Chargement des identifiants et configuration Confluence
├── clients/
│   ├── mattermost_client.py    # Client de connexion à l'API Mattermost
│   └── confluence_client.py    # Client REST Confluence Server / Data Center
├── services/
│   ├── alert_service.py        # Catégorisation, décompte et graphe temporel des alertes
│   ├── tracking_service.py     # Réconciliation, normalisation, machine à états et rendu Confluence
│   ├── demo_service.py         # Mocks Mattermost/Confluence et exportateur web pour le mode démo
│   └── template_renderer.py    # Moteur de rendu Jinja2
├── templates/
│   └── alerting_template.html  # Modèle HTML du rapport avec badges Confluence et liens d'action
├── tests/
│   ├── test_alert_service.py       # Tests unitaires de catégorisation et de timeline
│   ├── test_confluence_client.py   # Tests unitaires du client Confluence
│   ├── test_demo_mode.py           # Tests unitaires du mode démo et de l'export des écrans Confluence
│   ├── test_main_args.py           # Tests unitaires des arguments CLI et variables d'environnement
│   └── test_tracking_service.py    # Tests unitaires de normalisation et réconciliation
├── utils/
│   └── logger.py               # Logger console avec coloration ANSI
└── output/                     # Répertoire où est sauvegardé le rapport généré
    └── alertes.html
```

---

## ⚙️ Installation

1. Accédez au répertoire du projet :
   ```bash
   cd alerting
   ```

2. Créez et activez un environnement virtuel (optionnel mais conseillé) :
   ```bash
   python -m venv venv
   source venv/bin/activate  # Sur Linux/macOS
   # ou
   .\venv\Scripts\activate   # Sur Windows
   ```

3. Installez les dépendances :
   ```bash
   pip install -r requirements.txt
   ```

---

## 🔑 Configuration

Créez un fichier `.env` à la racine du projet `alerting` (ou copiez `.env.example`) :

```env
# Mattermost
MATTERMOST_URL=https://mattermost.votredomaine.com
MATTERMOST_TOKEN=votre_token_personnel_ou_bot
MATTERMOST_CHANNEL_ID=id_du_canal_a_surveiller
MATTERMOST_TEAM=nom_equipe

# Confluence (Suivi d'actions)
CONFLUENCE_URL=https://confluence.votredomaine.com
CONFLUENCE_TOKEN=votre_token_personnel_confluence
CONFLUENCE_PAGE_ID=123456789
CONFLUENCE_ARCHIVE_PAGE_ID=123456780
CONFLUENCE_STATS_PAGE_ID=123456781
CONFLUENCE_DISABLED=false
SUIVI_CONFLUENCE=false

# Options générales
EXCLUDED_ALERT_TITLES=Batche(s)
APP_TIMEZONE=Europe/Paris
MAX_DETAILED_ALERTS=200
```

---

## 🚫 Filtrage des alertes

Par défaut, les alertes de statut de traitement de lots ayant pour titre `"Batche(s)"` (par exemple `Batche(s) OK`, `Batche(s) KO`, etc.) sont automatiquement filtrées et ne remontent pas dans le rapport final.

---

## 🚀 Utilisation

### 🌟 Mode Démonstration Autonome (Tester immédiatement sans configuration)

Vous pouvez lancer le projet instantanément **sans avoir besoin d'accès à un serveur Mattermost ni Confluence**. Un jeu d'alertes réaliste sur une architecture microservices et un registre Confluence simulé en mémoire illustrent l'ensemble des fonctionnalités (transitions de statuts automatiques, détection des récidives, alertes en cours avec porteurs, tri du bruit, archivage automatique) :

```bash
python main.py --demo
```

Pour générer et ouvrir directement le rapport HTML dans votre navigateur :
```bash
python main.py --demo --open
```

En mode démo, le script génère **4 livrables HTML 100 % interconnectés** dans le dossier `output/` :
1. `output/alertes.html` : Rapport visuel principal d'alerting (frise temporelle, badges, indicateurs et liens vers Confluence).
2. `output/confluence_suivi.html` : Simulation web fidèle de la **page active Confluence** (pastilles de statut Atlassian AUI, tableau principal, palette de copier/coller et tableau secondaire de Bruit).
3. `output/confluence_archive.html` : Simulation web de la **page d'archive Confluence** (alertes résolues de plus de 1 mois déplacées automatiquement).
4. `output/confluence_stats.html` : Simulation web de la **page de statistiques Confluence** (journal de bord hebdomadaire avec rapport HTML en pièce jointe).

*💡 Cliquez sur **« Consulter ou éditer cette alerte sur Confluence »** depuis le rapport d'alertes pour basculer directement sur la page Confluence simulée correspondante avec surlignage automatique de la ligne !*

---

### Exécution standard (comportement d'origine, sans Confluence)

Par défaut, le script analyse les alertes sans interagir avec Confluence :
```bash
python main.py
```

### Exécution avec suivi Confluence activé (Point de suivi)

Active la synchronisation avec Confluence pour la semaine écoulée (168 heures) :
```bash
python main.py --hours 168 --suivi-confluence
# ou explicitement avec une valeur booléenne (true / false) :
python main.py --hours 168 --suivi-confluence=true
python main.py --hours 168 --suivi-confluence=false
```

*Note : vous pouvez également activer ce mode via la variable d'environnement `SUIVI_CONFLUENCE=true`.*

### 📋 Récapitulatif des options de la ligne de commande (CLI)

| Option | Type / Valeurs | Valeur par défaut | Description |
| :--- | :--- | :--- | :--- |
| **`--demo`** | Flag | `false` | Lance le mode démo autonome avec simulation Mattermost et Confluence (aucun serveur externe requis). |
| **`--open`** | Flag | `false` | Ouvre automatiquement le rapport HTML dans votre navigateur par défaut après génération. |
| **`--hours`** | Entier strictement positif | `24` *(ou `168` en `--demo`)* | Nombre d'heures d'historique à analyser (ex : `168` pour 7 jours). |
| **`--output`** | Chemin de fichier | `output/alertes.html` | Chemin personnalisé vers le fichier HTML du rapport généré. |
| **`--suivi-confluence`** | Booléen (`true`/`false`) ou Flag | Variable `SUIVI_CONFLUENCE` *(ou `true` en `--demo`)* | Active ou désactive la réconciliation et la synchronisation Confluence. |

---

### Spécifier une plage horaire personnalisée

```bash
python main.py --hours 48
```

### Spécifier un chemin de sortie pour le rapport

```bash
python main.py --output /chemin/vers/mon_rapport.html
```

### Lancer les tests unitaires

```bash
python -m pytest -v
```

---

## 🔄 Automatisation GitLab CI/CD

Le fichier `.gitlab-ci.yml` permet d'automatiser l'exécution hebdomadaire du rapport :

1. **Variables de projet** : Dans GitLab (**Settings > CI/CD > Variables**), configurez :
   - `MATTERMOST_URL`
   - `MATTERMOST_TOKEN` (variable masquée / masked)
   - `MATTERMOST_CHANNEL_ID`
   - `CONFLUENCE_URL`
   - `CONFLUENCE_TOKEN` (variable masquée / masked)
   - `CONFLUENCE_PAGE_ID` (défaut : `123456789`)
   - `CONFLUENCE_ARCHIVE_PAGE_ID` (optionnel, défaut : `123456780`)
   - `CONFLUENCE_STATS_PAGE_ID` (optionnel, défaut : `123456781`)

2. **Programmation (Schedule)** : Dans GitLab (**Build > Pipeline schedules**) :
   - Interval Pattern : `30 10 * * 1` (tous les lundis à 10h30 heure locale Paris).
   - Variables : `WEEKLY_HOURS="--hours=168"` (analyse des 7 derniers jours).

3. **Artefacts** : Le rapport `output/alertes.html` est conservé automatiquement dans les artefacts GitLab.
