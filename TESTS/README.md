# DATA_LOADER - Guide d'Exécution des Tests de Validation (Environnement Unix)

Ce dossier (`DATA_LOADER/TESTS`) contient la suite de tests automatisés conçue pour valider l'ensemble du pipeline d'ingestion ELT en environnement Unix :
**`BICC_INTAKE_CONTROLLER` (Feeder) $\rightarrow$ `DATA_INGESTION_ORCHESTRATOR` $\rightarrow$ `TPT_LOADER` (Teradata)**.

Les tests exploitent directement les fichiers de configuration de production/recette situés dans `DATA_LOADER/PROCESSING_TOOLS/*/config.json` et s'exécutent sur les répertoires natifs `DATA_LOADER/DATA` et `DATA_LOADER/LOGS`.

---

## 1. Prérequis & Ce qu'il faut configurer avant de lancer les tests

Avant d'exécuter les tests sur votre serveur Unix, vérifiez les points suivants :

### 1.1 Variables d'Environnement Unix
Votre session shell (ou votre script `.profile` / `.bash_profile`) doit exporter les variables d'environnement suivantes :

```bash
# Environnement Teradata
export TDENV="DEV0"                     # Préfixe de la base (DEV0, INT0, PPD0, PRD0)
export ENV="DEV"                        # Identifiant de l'environnement
export TDPID="tdadev"                   # Hostname ou TDPID Teradata
export SID_ADM_USER="SIDFINADM"         # Compte de service (sans préfixe TDENV)
export USER_CHAPEAU="DEVADM"            # Profil chapeau d'exécution
export TDADEV="2"
export LANG="C"                         # Impératif pour l'encodage TPT/BTEQ
```

### 1.2 Authentification Teradata
Le framework supporte 3 modes d'authentification. Assurez-vous qu'au moins l'un d'eux est actif :
1. **Teradata Wallet (Recommandé)** :
   ```bash
   tdwallet add "${TDENV}${SID_ADM_USER}"
   # Saisir le mot de passe quand demandé
   ```
2. **Fichiers de clés chiffrées (DBT Profile / TJEncryptPassword)** :
   Vérifiez la présence des fichiers dans `~/.dbt/` :
   - `~/.dbt/${TDENV}${SID_ADM_USER}_Key.properties`
   - `~/.dbt/${TDENV}${SID_ADM_USER}_Pass.properties`
3. **Variable directe de test** :
   ```bash
   export TD_PASSWORD="<votre_mot_de_passe>"
   ```

### 1.3 Tables Techniques d'Orchestration (`${TDENV}SIDFINTCH`)
Les tables techniques de suivi d'état doivent être créées avec l'index primaire non-unique composite `(BATCH_ID, SOURCE)` :
```bash
cd /sg/local/sid/home/Dsidadm/DATA_LOADER/PROCESSING_TOOLS/DATA_INGESTION_ORCHESTRATOR
bteq << EOF
.logon ${TDPID}/${TDENV}${SID_ADM_USER},\$tdwallet(${TDENV}${SID_ADM_USER})
.run file = ddl_technical_tables.sql;
.logoff
.quit
EOF
```

> [!NOTE]
> Si la table `BATCH_RUNS` existe déjà, assurez-vous que la colonne `PROCESS_PID` a été ajoutée :
> `ALTER TABLE ${TDENV}SIDFINTCH.BATCH_RUNS ADD PROCESS_PID INTEGER;`

### 1.4 Droits Teradata sur les Bases Staging & Work
Le compte `${TDENV}${SID_ADM_USER}` doit disposer des privilèges suivants :
- **`${TDENV}SIDFINSTG`** : `SELECT`, `INSERT`, `UPDATE`, `DELETE`, `CREATE TABLE`, `DROP TABLE` (requis pour l'Auto-DDL Schema Guard).
- **`${TDENV}SIDFINWRK`** : `ALL` (nécessaire pour les tables de travail, log et d'erreur TPT/FastLoad).
- **`DBC.ColumnsV`** : `SELECT` (utilisé par Schema Guard pour dériver la structure et vérifier les colonnes).

### 1.5 Mapping des Entités (`DATA_LOADER/CONFIG/entity_mapping.csv`)
Le fichier [`entity_mapping.csv`](file:///C:/Users/P992860/data_loader/DATA_LOADER/CONFIG/entity_mapping.csv) associe les signatures de fichiers aux tables cibles.
Pour les tests, les entrées suivantes doivent être présentes (déjà pré-configurées) :
```csv
SOURCE,TARGET_TABLE,FILE_SIGNATURE,EXTENSION,INNER_EXTENSION
ORACLE_FUSION,ERP_MSH_USER,userpvo,".csv,.zip,.gz,.csv.gz",.csv
CRM,CRM_MSH_CUSTOMER,customerpvo,".csv,.zip,.gz,.csv.gz",.csv
```

---

## 2. Structure du Dossier TESTS

```
DATA_LOADER/TESTS/
├── README.md                      # Ce guide d'exploitation
├── clean_data_and_logs.sh         # Script de réinitialisation de DATA et LOGS
├── archive_outputs.sh             # Collecteur automatique des artefacts post-test
├── run_all_tests.sh               # Lanceur principal en Bash (avec packaging tar.gz)
├── run_all_tests.py               # Lanceur alternatif en Python 3
├── verify_database_and_storage.py # Auditeur approfondi Teradata DB & Storage Tiers
├── DATASETS/                      # Jeux de données immuables pour chaque cas de test
│   ├── BATCH_NOMINAL/             # Lot BATCH 9001 nominal (ORACLE_FUSION)
│   ├── BATCH_CONCURRENT_1/        # Lot BATCH 9002 pour test de concurrence
│   ├── BATCH_CONCURRENT_2/        # Lot BATCH 9003 pour test de concurrence
│   ├── BATCH_CRASH/               # Lot BATCH 9004 pour simulation crash & reprise
│   ├── BATCH_CRM/                 # Lot BATCH 9005 source CRM pour test multi-sources
│   ├── BATCH_POST_TASKS/          # Lot BATCH 9006 pour validation post-tasks Intake Controller
│   ├── BATCH_POST_TASKS_SKIP/     # Lot BATCH 9008 pour validation du bypass --skip-post-tasks
│   ├── BATCH_DB_AUDIT/            # Lot BATCH 9007 pour audit approfondi DB & Storage
│   └── BATCH_SPECIAL_COLS/        # Lot BATCH 9009 pour parité de nettoyage des colonnes CSV
├── scenarios/                     # Scripts de scénarios autonomes
│   ├── 01_test_nominal_pipeline.sh              # Scénario 1 : Pipeline complet nominal
│   ├── 02_test_skip_post_tasks.sh               # Scénario 2 : Découplage (--skip-post-tasks)
│   ├── 03_test_concurrency_lock.sh              # Scénario 3 : Concurrence & attente active
│   ├── 04_test_crash_stale_pid.sh               # Scénario 4 : Reprise crash & PID mort
│   ├── 05_test_multisource_partition.sh         # Scénario 5 : Cloisonnement multi-sources
│   ├── 06_test_intake_controller_post_tasks.sh  # Scénario 6 : Post-tasks source & bypass
│   ├── 07_test_database_and_storage_audit.sh    # Scénario 7 : Audit Teradata DB, Storage & PID
│   ├── 08_test_lock_recovery_and_schema_flags.sh # Scénario 8 : Lock recovery & Schema Guard flags
│   ├── 09_test_unit_and_core_sdk.sh             # Scénario 9 : Tests unitaires Core SDK & Pool DB
│   ├── 10_test_decoupled_multi_batch_queue.sh   # Scénario 10 : File multi-lots découplée FIFO
│   └── 11_test_multisource_plugin_and_slot_governor.sh # Scénario 11 : Plugins multi-sources & gouverneur de slots
├── unit/                          # Suite de tests unitaires (dataloader_core & services)
├── test_phase01_units.py          # Suite de tests unitaires Phase 01
└── OUTPUTS/                       # Répertoire créé automatiquement contenant tous les artefacts
    ├── scenario_01_nominal_pipeline/
    ├── scenario_02_skip_post_tasks/
    ├── scenario_03_concurrency_lock/
    ├── scenario_04_crash_recovery/
    ├── scenario_05_multisource_partition/
    ├── scenario_06_intake_post_tasks/
    ├── scenario_07_database_and_storage_audit/
    ├── scenario_08_lock_recovery_and_schema_flags/
    ├── scenario_09_unit_and_core_sdk/
    ├── scenario_10_decoupled_multi_batch_queue/
    ├── scenario_11_multisource_plugin_and_slot_governor/
    └── all_test_outputs_latest.tar.gz  # Archive tarball consolidée prête à être partagée
```

---

## 3. Comment Lancer les Tests

### 3.1 Rendre les scripts exécutables
À la première utilisation, donnez les droits d'exécution :
```bash
cd /sg/local/sid/home/Dsidadm/DATA_LOADER/TESTS
chmod +x clean_data_and_logs.sh run_all_tests.sh run_all_tests.py scenarios/*.sh
```

### 3.2 Exécuter l'ensemble des scénarios (Recommandé)
Pour exécuter les 11 scénarios séquentiellement avec rapport final :
```bash
./run_all_tests.sh
# ou en python :
python3 run_all_tests.py
```

### 3.3 Exécuter un scénario spécifique
Vous pouvez cibler un scénario unique (les dossiers `DATA` et `LOGS` sont automatiquement nettoyés et approvisionnés) :
```bash
# Via le master runner :
./run_all_tests.sh --scenario 1
./run_all_tests.sh --scenario 8
./run_all_tests.sh --scenario 9
./run_all_tests.sh --scenario 10
./run_all_tests.sh --scenario 11

# Ou en appel direct :
./scenarios/01_test_nominal_pipeline.sh
./scenarios/08_test_lock_recovery_and_schema_flags.sh
./scenarios/09_test_unit_and_core_sdk.sh
./scenarios/10_test_decoupled_multi_batch_queue.sh
./scenarios/11_test_multisource_plugin_and_slot_governor.sh
```

### 3.4 Réinitialiser manuellement les sas `DATA` et `LOGS`
Pour vider l'ensemble des répertoires de données (`DROP_ZONE`, `LANDING_ZONE`, `LOADING_ZONE`, `ARCHIVE_ZONE`) et de logs sans lancer de test :
```bash
./clean_data_and_logs.sh
# ou :
./run_all_tests.sh --clean
```

---

## 4. Archivage Automatique des Artefacts dans `OUTPUTS/` pour Analyse

Après l'exécution de chaque scénario (qu'il soit en **SUCCÈS** ou en **ÉCHEC**), un gestionnaire d'interruption automatique (`trap EXIT`) déclenche [`archive_outputs.sh`](file:///C:/Users/P992860/data_loader/DATA_LOADER/TESTS/archive_outputs.sh) et sauvegarde l'intégralité des traces et artefacts dans le sous-dossier dédié [`DATA_LOADER/TESTS/OUTPUTS/`](file:///C:/Users/P992860/data_loader/DATA_LOADER/TESTS/OUTPUTS) :

### 4.1 Contenu archivé par scénario (`OUTPUTS/<scenario_name>/`)
Chaque sous-répertoire de scénario contient :
1. **`LOGS/`** : L'ensemble exhaustif des logs générés pendant le run :
   - Logs Feeder (`LOG_FEEDER_<SOURCE>_<EXEC_TS>.log`)
   - Logs Orchestrateur (`LOG_ORCHESTRATOR_<SOURCE>_<EXTRACT_TS>_<BATCH_ID>_<EXEC_TS>.log`)
   - Logs TPT & BTEQ (`TPT/`)
2. **`ARCHIVE_ZONE/`** : Copie exacte des Batch Capsules archivées à l'issue de l'ingestion réussie (`BATCH_<ID>_<TS>/`).
3. **`RAW_RECEIPTS/`** : Reçus canoniques (`RECEIPT_*.json`) et manifests bruts archivés dans le coffre-fort `RAW/`.
4. **`REMAINING_IN_TRANSIT/`** : État des sas de transit (`DROP_ZONE`, `LANDING_ZONE`, `LOADING_ZONE`). En cas d'échec ou d'interruption, les fichiers résiduels ou marqueurs de reprise y sont immédiatement préservés pour diagnostic.
5. **`execution_summary.txt`** : Fiche de synthèse automatique incluant le code retour, le statut (PASS/FAIL), les variables d'environnement actives, l'inventaire des fichiers produits et les 40 dernières lignes des logs.

### 4.2 Récupération du Pack Consolidé (`all_test_outputs_latest.tar.gz`)
À la fin du run, une archive tarball compressée regroupant tous les scénarios est automatiquement générée à la racine de `OUTPUTS/` :
- Fichier horodaté : `OUTPUTS/all_test_outputs_YYYYMMDD_HHMMSS.tar.gz`
- Raccourci / copie courante : `OUTPUTS/all_test_outputs_latest.tar.gz`

---

## 5. Description Détaillée des Scénarios de Test

### 5.1 Synthèse d'Exécution & Métriques Officielles (100% PASS)

Les 11 scénarios d'intégration système ont été validés avec un taux de réussite de **100%** sur l'environnement Teradata Vantage cible :

| N° | Script de Scénario | Statut | Code Retour | Durée d'Exécution | Validation Clé |
|:---|:---|:---:|:---:|:---:|:---|
| **01** | `01_test_nominal_pipeline.sh` | **PASS** | `RC=0` | 20.2s | Pipeline nominal de bout en bout, création Auto-DDL, FastLoad, coffre-fort `RAW/`. |
| **02** | `02_test_skip_post_tasks.sh` | **PASS** | `RC=0` | 19.4s | Découplage hybride via `--skip-post-tasks`, bypass strict des hooks aval. |
| **03** | `03_test_concurrency_lock.sh` | **PASS** | `RC=0` | 40.1s | Attente active sur PID concurrent, évitement de collision et exécution ordonnée. |
| **04** | `04_test_crash_stale_pid.sh` | **PASS** | `RC=0` | 16.6s | Détection de PID mort (`999999`), nettoyage de verrou et reprise en vol d'un lot interrompu. |
| **05** | `05_test_multisource_partition.sh` | **PASS** | `RC=0` | 71.3s | Cloisonnement multi-sources strict (`ORACLE_FUSION` vs `CRM`) et exécutions isolées. |
| **06** | `06_test_intake_controller_post_tasks.sh` | **PASS** | `RC=0` | 38.2s | Exécution combinée des post-tasks source et globales, et validation du bypass. |
| **07** | `07_test_database_and_storage_audit.sh` | **PASS** | `RC=0` | 19.8s | Audit profond Teradata (`BATCH_RUNS`, `BATCH_TASKS`, `ERP_MSH_USER`) et intégrité stockage. |
| **08** | `08_test_lock_recovery_and_schema_flags.sh` | **PASS** | `RC=0` | 38.7s | Blocage de dérive sous `auto_migrate_ddl: false`, parité d'assainissement, reprise unlock. |
| **09** | `09_test_unit_and_core_sdk.sh` | **PASS** | `RC=0` | 22.1s | 35 tests unitaires du Core SDK (`TESTS/unit/`), respect des limites de lignes (<80), pool DB. |
| **10** | `10_test_decoupled_multi_batch_queue.sh` | **PASS** | `RC=0` | 38.6s | Découplage `--enqueue-only`, publication Batch Capsule, consommation FIFO multi-lots. |
| **11** | `11_test_multisource_plugin_and_slot_governor.sh` | **PASS** | `RC=0` | 38.2s | Plugins d'intake (`SourceIntakePlugin`), mapping 9 colonnes, régulation `UtilitySlotGovernor`. |
| **TOTAL** | **Suite Complète (11/11)** | **100% PASS** | `RC=0` | **363.2s (~6 min)** | **Tous les critères d'acceptation validés avec succès sur Teradata Vantage.** |

### 5.2 Détail des Scénarios et Assertions Vérifiées

| N° | Scénario | Ce que le test fait automatiquement | Validation & Critère de Succès |
|:---|:---|:---|:---|
| **01** | **Nominal Pipeline** | Nettoie `DATA/LOGS`, copie le lot `BATCH 9001` dans `DROP_ZONE/ORACLE_FUSION`, lance le Feeder nominalement. | - Code retour 0.<br>- Capsule complète archivée dans `ARCHIVE_ZONE/ORACLE_FUSION/<YYYY-MM>/BATCH_<ID>_<TS>/` avec son `batch_descriptor.json`, manifest canonique, et sous-dossier `RAW/`.<br>- Table Teradata créée / alimentée.<br>- Fichiers archivés dans sa capsule `ARCHIVE_ZONE`. |
| **02** | **Hybrid Decoupling** | Copie `BATCH 9001` dans `DROP_ZONE/ORACLE_FUSION`, lance `feeder.py --skip-post-tasks`. | - Code retour 0.<br>- Trace `Post-tasks execution skipped via --skip-post-tasks flag` présente dans les logs.<br>- Ingestion complète 100% sans exécution des post-traitements. |
| **03** | **Concurrency Lock** | Injecte `BATCH 9002` dans `DROP_ZONE/ORACLE_FUSION` et lance Feeder 1 en tâche de fond (`&`). Attends 0.5s, injecte `BATCH 9003` et lance Feeder 2 en parallèle. | - Feeder 2 détecte le PID actif de Feeder 1 et entre en boucle d'attente active (`poll_interval`).<br>- À la libération du verrou, Feeder 2 s'exécute à son tour.<br>- Les 2 lots sont archivés sans corruption ni collision. |
| **04** | **Crash & Stale PID** | Simule une interruption en injectant `BATCH 9004` directement dans `LOADING_ZONE/ORACLE_FUSION` avec un verrou `.orchestrator.pid` contenant un PID mort (`999999`). Lance le Feeder. | - Le Feeder constate que le PID `999999` n'existe plus dans le système d'exploitation.<br>- Nettoie le verrou orphelin.<br>- Déclenche la reprise en vol de l'Orchestrateur.<br>- Lot complété et archivé dans sa capsule `ARCHIVE_ZONE`. |
| **05** | **Multi-Source Isolation** | Crée les sas partitionnés `DROP_ZONE/ORACLE_FUSION` et `DROP_ZONE/CRM`. Dépose simultanément les 2 lots. Lance `feeder.py --source CRM`. Puis lance `feeder.py --source ORACLE_FUSION`. | - Le run CRM traite uniquement son sas sans toucher au sas `ORACLE_FUSION`.<br>- Le run ORACLE_FUSION traite son sas sans interférer.<br>- Fichiers archivés dans leurs zones respectives (`ARCHIVE_ZONE/CRM` et `ARCHIVE_ZONE/ORACLE_FUSION`). |
| **06** | **Intake Post-Tasks & Skip** | **Part A** : Injecte le lot `BATCH 9006` dans `DROP_ZONE/ORACLE_FUSION`, lance le Feeder nominalement.<br>**Part B** : Injecte le lot `BATCH 9008` dans `DROP_ZONE/ORACLE_FUSION`, lance avec `--skip-post-tasks`. | - **Part A** : Vérifie l'exécution effective de la post-task spécifique de l'Intake Controller ET de la post-task globale de l'Orchestrateur.<br>- **Part B** : Vérifie le contournement strict des deux tâches avec présence du log de bypass.<br>- Les 2 lots sont archivés avec succès. |
| **07** | **Deep DB, Storage & PID Audit** | Injecte le lot `BATCH 9007` (3 enregistrements) dans `DROP_ZONE/ORACLE_FUSION`, lance le Feeder, puis exécute `verify_database_and_storage.py`. | - **Teradata Technical Tables** : `BATCH_RUNS` a `STATUS='SUCCESS'`, `END_TIME IS NOT NULL`, et `PROCESS_PID` est **NON NUL** (conservé pour auditabilité). `BATCH_TASKS` toutes au statut `SUCCESS`.<br>- **Teradata Staging** : `ERP_MSH_USER` contient exactement 3 lignes avec `INFA_BATCH_ID='9007'` et `INFA_LAST_REPLICATED` valorisé.<br>- **Stockage** : `LANDING_ZONE` vide, `LOADING_ZONE` vide, coffre-fort `RAW/` vérifié.<br>- Génère `db_and_storage_audit_report.txt` dans `OUTPUTS/`. |
| **08** | **Lock Recovery & Schema Flags** | Exécute `test_phase01_units.py`, injecte `BATCH 9009` (`BATCH_SPECIAL_COLS`), teste `auto_migrate_ddl: false` sur dérive de schéma, teste `unlock_tpt_table.sh -m replace -B 9009 -T 20261016_100800`, puis exécute `verify_database_and_storage.py`. | - Tests unitaires Phase 01 à 100% PASS.<br>- En-têtes CSV avec caractères spéciaux nettoyés à l'identique entre Python et Bash.<br>- Blocage de `DROP TABLE` quand `auto_migrate_ddl=false`.<br>- `unlock_tpt_table.sh` peuple `INFA_BATCH_ID` et `INFA_LAST_REPLICATED` à 100% après reprise FastLoad. |
| **09** | **Core SDK Unit Tests & Connection Pool Validation** | Exécute l'ensemble des 10 modules de tests unitaires (`TESTS/unit/test_*.py`) couvrant le SDK Core et les services, contrôle la taille des points d'entrée (`< 80` lignes) et l'absence de duplication de code, ingère `BATCH 9001` de bout en bout via `dataloader_core` et `TeradataConnectionManager`, puis exécute `verify_database_and_storage.py`. | - 100% PASS sur la suite `unittest discover` de `TESTS/unit/` (10 modules de test).<br>- `feeder.py` et `orchestrator.py` strictement inférieurs à 80 lignes.<br>- Zéro duplication résiduelle.<br>- Ingestion Teradata complète via pool de connexions `TeradataConnectionManager`. |
| **10** | **Decoupled Multi-Batch Queue Ingestion** | **Part A** : Dépose `BATCH 9002` (`BATCH_CONCURRENT_1`) et `BATCH 9003` (`BATCH_CONCURRENT_2`) dans `DROP_ZONE/ORACLE_FUSION`, lance `feeder.py --enqueue-only`.<br>**Part B** : Vérifie la présence des 2 Batch Capsules autonomes dans `LANDING_ZONE/ORACLE_FUSION`, puis lance `orchestrator.py --source ORACLE_FUSION` pour consommer et vider la file.<br>**Part C** : Exécute `verify_database_and_storage.py` sur le lot 9002 (avec `--skip-staging-check` car écrasé en mode replace par le lot 9003) puis sur le lot 9003 (`--expected-count 1`). | - **Part A** : Feeder s'exécute en mode producteur pur sans connexion Teradata ; publie 2 Batch Capsules autonomes dans `LANDING_ZONE` contenant `batch_descriptor.json`, manifest canonique, données et `RAW/`.<br>- **Part B** : Orchestrateur consomme la file en ordre chronologique FIFO strict, applique le fast-path $O(1)$, synchronise le schéma via JIT Schema Guard, charge via TPT `-C -M 2`, exécute les post-tasks, et archive les capsules.<br>- **Part C** : Audit Teradata complet (statuts `SUCCESS`, conservation de `PROCESS_PID`, intégrité `BATCH_TASKS`, données et métadonnées d'audit de la table `ERP_MSH_USER`) à 100% PASS. |
| **11** | **Multi-Source Plugin & Slot Governor** | **Part A** : Valide l'architecture enfichable d'intake (`SourceIntakePlugin`) et la détection multi-source (`--all-sources`).<br>**Part B** : Teste le traitement d'entités avec attributs de mapping étendus (séparateur point-virgule `;`, `skip_rows: 2`, `header_mode: every_file`).<br>**Part C** : Valide le `UtilitySlotGovernor` sous charge concurrente (saturation de créneaux TPT) garantissant l'absence de saturation Teradata (Erreur 2633). | - Découverte et traitement sans friction de sources alternatives via plugins d'intake dédiés.<br>- Respect strict des options de parsing per-entity transmises à TPT (`-s`, `-S`, `-Y`).<br>- Gouvernance stricte des slots TPT inter-processus sans deadlocks ni dépassement de quota.<br>- Audit complet stockage et tables techniques à 100% PASS. |

---

## 6. Outil d'Audit Approfondi : `verify_database_and_storage.py`

Le script [`verify_database_and_storage.py`](verify_database_and_storage.py) est l'auditeur automatisé de référence utilisé dans les scénarios 07, 08, 09 et 10. Il réalise une inspection complète à trois niveaux (Stockage, Tables Techniques Teradata, Table Staging Teradata).

### 6.1 Syntaxe & Options en Ligne de Commande

```bash
python3 verify_database_and_storage.py \
    --batch-id <ID> \
    [--source <SOURCE>] \
    [--target-table <TABLE>] \
    [--expected-count <N>] \
    [--skip-staging-check] \
    [--output-file <FICHIER_RAPPORT>]
```

| Option | Type | Valeur par défaut | Description |
|:---|:---|:---|:---|
| `--batch-id` | `str` | *(Requis)* | Identifiant du lot à auditer (ex: `9001`, `9002`, `9003`, `9007`). |
| `--source` | `str` | `ORACLE_FUSION` | Partition source correspondante dans `DATA/` et `LOGS/`. |
| `--target-table` | `str` | `ERP_MSH_USER` | Nom de la table staging Teradata cible à inspecter. |
| `--expected-count` | `int` | `2` | Nombre de lignes attendu dans la table staging pour le lot audité. |
| `--skip-staging-check` | flag | `False` | **Contournement du contrôle des lignes en staging**. Indispensable pour auditer un lot intermédiaire dans une file multi-lots lorsque des lots successifs ciblent la même table en mode `replace` (le second lot écrasant les données du premier via FastLoad `DELETE ALL`), tout en vérifiant rigoureusement le stockage et les tables techniques. |
| `--output-file` | `str` | `None` | Chemin du fichier texte dans lequel sauvegarder le rapport d'audit exhaustif. |

### 6.2 Les 3 Niveaux de Contrôle Réalisés

```
┌────────────────────────────────────────────────────────────────────────┐
│ NIVEAU 1 : CYCLE DE VIE DU STOCKAGE (Storage Lifecycles)               │
│ - LANDING_ZONE/<SOURCE> : Doit être totalement propre et vide (0 orphelin)│
│ - LOADING_ZONE/<SOURCE> : Doit être totalement propre et vide (0 sas)  │
│ - ARCHIVE_ZONE/<SOURCE>/<YYYY-MM>/BATCH_<ID>_<TS>/ : Doit contenir     │
│   la Batch Capsule complète (*.csv, MANIFEST_*.MF, batch_descriptor.json│
│   et sous-dossier RAW/ avec RECEIPT_<SOURCE>_<TS>_<ID>.json).          │
│ - Absence de fichiers résiduels obsolètes post_tasks_*.json dans LOGS. │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │ PASS
┌──────────────────────────────────▼─────────────────────────────────────┐
│ NIVEAU 2 : TABLES TECHNIQUES D'ORCHESTRATION (Teradata Vantage)        │
│ - BATCH_RUNS : Enregistrement unique (BATCH_ID, SOURCE).               │
│   * STATUS = 'SUCCESS'                                                 │
│   * END_TIME IS NOT NULL                                               │
│   * PROCESS_PID IS NOT NULL (Audit preservation : PID conservé !)      │
│ - BATCH_TASKS : Toutes les entités sont au STATUS = 'SUCCESS'.         │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │ PASS (ou contourné si --skip-staging-check)
┌──────────────────────────────────▼─────────────────────────────────────┐
│ NIVEAU 3 : TABLE STAGING CIBLE & MÉTADONNÉES D'AUDIT                   │
│ - Nombre de lignes : SELECT COUNT(*) WHERE INFA_BATCH_ID = <batch_id>  │
│   doit correspondre exactement à --expected-count.                     │
│ - INFA_BATCH_ID : 100% valorisé avec la valeur du batch.              │
│ - INFA_LAST_REPLICATED : 100% valorisé avec les horodatages valides.   │
│ - Extraction d'un échantillon représentatif de 5 lignes pour log.     │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 7. Inventaire des Tests Unitaires (`DATA_LOADER/TESTS/unit/`)

En complément des 11 scénarios d'intégration système, le dossier `TESTS/unit/` héberge une suite de 14 modules de tests unitaires automatisés validant les composants internes du SDK partagé `dataloader_core` et des services d'application :

| Module de Test | Composant Validé | Fonctionnalités & Assertions Clés |
|:---|:---|:---|
| `test_batch_descriptor_capsule.py` | `capsule.py` (`BatchDescriptor`, `CapsulePathResolver`) | - Sérialisation et désérialisation JSON round-trip de `BatchDescriptor`.<br>- Publication atomique de capsules dans `LANDING_ZONE`.<br>- Exclusion des répertoires temporaires `.staging_*` lors des scans. |
| `test_core_config.py` | `config.py` (`ConfigLoader`) | - Résolution récursive des variables d'environnement (`${VAR}`).<br>- Résolution sécurisée des chemins de sas (`resolve_zone_path`) avec protection contre les faux positifs de sous-chaînes.<br>- Chargement et validation des configurations JSON avec valeurs par défaut. |
| `test_core_db_pool.py` | `db.py` (`TeradataConnectionManager`) | - Validation stricte des identifiants SQL contre les injections (`validate_sql_identifier`).<br>- Ordre de priorité des identifiants Teradata (Wallet $\rightarrow$ clés DBT $\rightarrow$ direct).<br>- Construction des variables d'environnement TPT.<br>- Réutilisation thread-safe des connexions au sein du pool persistant. |
| `test_core_locking.py` | `locking.py` (`ProcessLock`) | - Détection de l'existence et vivacité d'un PID système (`is_pid_alive`).<br>- Verrouillage POSIX exclusif non-bloquant (`fcntl.flock`).<br>- Détection et nettoyage automatique des verrous orphelins (PID mort / crash).<br>- Boucle d'attente active avec timeout pour les processus concurrents vivants. |
| `test_core_manifest_and_capsule.py` | `manifest.py` / `capsule.py` | - Reconnaissance et parsing des 4 motifs syntaxiques de fichiers manifests BICC.<br>- Lecture et écriture d'entrées de manifest avec calcul d'empreinte MD5.<br>- Résolution des sous-dossiers temporels et capsules d'archivage. |
| `test_core_mapping.py` | `mapping.py` (`EntityMapper`) | - Résolution des règles de routage pour fichiers simples (`.csv`, `.pecsv`, `.gz`).<br>- Inspection interne à double passe des archives d'entités `.zip`.<br>- Cloisonnement strict des règles par source et gestion des jokers (`*`). |
| `test_intake_plugin_framework.py` | `dataloader_core.intake` (`SourceIntakePlugin`, `PluginRegistry`) | - Enregistrement dynamique via `@PluginRegistry.register` et résolution de plugin par nom.<br>- Découverte et validation des candidats de lots (`BICCIntakePlugin`, `StandardManifestIntakePlugin`, `ManifestlessDropIntakePlugin`).<br>- Isolation 100% flat-file sans dépendance de base de données Teradata. |
| `test_intake_service.py` | `intake_service.py` (`IntakeControllerService`) | - Invariant architectural : `feeder.py` strictement $< 80$ lignes.<br>- Cycle de vie du service d'intake hérité de `BaseIntakeController` sur sas vide et sur lot unitaire nominal. |
| `test_jit_schema_guard_order.py` | `orchestrator_service.py` / `schema_guard.py` | - Vérification de l'ordre d'appel du Just-In-Time Schema Guard.<br>- Schema Guard invoqué pour chaque lot immédiatement avant le lancement TPT dans le respect de la file FIFO. |
| `test_multi_batch_queue_sensor.py` | `sensor.py` (`scan_landing_queue`) | - Détection et inventaire de 1..N Batch Capsules dans `LANDING_ZONE`.<br>- Tri chronologique strict ascendant FIFO.<br>- Rétro-compatibilité avec les manifests plats historiques.<br>- Détection et blocage sur fichiers orphelins non déclarés (contrat OPS-02). |
| `test_orchestrator_service.py` | `orchestrator_service.py` (`OrchestratorService`) | - Invariant architectural : `orchestrator.py` strictement $< 80$ lignes.<br>- Cycle de vie complet de l'orchestrateur (consommation de file, archivage).<br>- Exécution des post-tasks dans un environnement isolé (`context_env`) sans mutation de `os.environ`. |
| `test_per_entity_mapping_options.py` | `mapping.py` (`EntityRule`, `EntityMapper`) | - Rétro-compatibilité 100% avec les tables de correspondance à 5 colonnes.<br>- Prise en charge des 9 colonnes (`DELIMITER`, `LOAD_MODE`, `SKIP_ROWS`, `HEADER_MODE`).<br>- Parsing des variantes d'en-tête (`first_chunk_only`, `every_file`, `none`) et séparateurs personnalisés. |
| `test_phase01_units.py` | Utilitaires transverses | - Nettoyage et assainissement des noms de colonnes CSV (`clean_column_name`) avec parité exacte entre regex Python et filtres Bash.<br>- Validation des types SQL autorisés.<br>- Résolution de la table cible et gestion des PID stale. |
| `test_utility_slot_governor.py` | `locking.py` (`UtilitySlotGovernor`) | - Régulation cross-processus des créneaux de chargement Teradata via slots bornés `fcntl.flock`.<br>- Respect strict du plafond de concurrence (max slots) avec mise en file ordonnée.<br>- Libération instantanée au niveau du noyau Linux en cas de crash/terminaison. |

---

## 8. Dépannage & Diagnostic

### En cas d'erreur de connexion Teradata (`Cannot connect to tdadev`) :
- Vérifiez la connectivité réseau avec le serveur Vantage : `ping tdadev` ou `traceroute tdadev`.
- Vérifiez les variables : `echo $TDPID`, `echo $TDENV`, `echo $SID_ADM_USER`.
- Testez la connexion manuelle BTEQ :
  ```bash
  bteq << EOF
  .logon ${TDPID}/${TDENV}${SID_ADM_USER},\$tdwallet(${TDENV}${SID_ADM_USER})
  SELECT CURRENT_TIMESTAMP;
  .quit
  EOF
  ```

### En cas de table verrouillée par TPT (Erreur Teradata 2652) :
Si un test précédent a été interrompu violemment pendant un chargement TPT :
```bash
cd /sg/local/sid/home/Dsidadm/DATA_LOADER/PROCESSING_TOOLS/TPT_LOADER
./unlock_tpt_table.sh -t ERP_MSH_USER -d ${TDENV}SIDFINSTG -w ${TDENV}SIDFINWRK -m replace
```

### Consultation des logs :
Tous les fichiers de logs générés sont conservés dans `DATA_LOADER/LOGS/<SOURCE>/` :
- Logs du Feeder : `DATA_LOADER/LOGS/<SOURCE>/LOG_FEEDER_<SOURCE>_<EXEC_TS>.log`
- Logs de l'Orchestrateur : `DATA_LOADER/LOGS/<SOURCE>/<YYYY-MM>/BATCH_<ID>_<TS>/LOG_ORCHESTRATOR_*.log`
- Logs TPT : `DATA_LOADER/LOGS/<SOURCE>/<YYYY-MM>/BATCH_<ID>_<TS>/TPT/`

Pour afficher le dernier log du Feeder en continu :
```bash
tail -f $(ls -t /sg/local/sid/home/Dsidadm/DATA_LOADER/LOGS/*/*.log | head -1)
```
