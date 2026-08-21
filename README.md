# Getly

Plateforme d'extractions comptables pour le core banking ACEP. Chaque
extraction est un module indépendant (formulaire + requête + export
Excel) branché sur une interface commune, ce qui permet d'en ajouter de
nouvelles facilement.

**Extractions disponibles aujourd'hui :**

- 📋 **Balance Agée** — date d'arrêté obligatoire (liste déroulante,
  dernière disponible par défaut) ; genre, ressource affectée, matricule
  client, n° prêt, secteur d'activité, classe d'âge, et localisation
  hiérarchique facultatifs → détail des prêts en cours (un par ligne)
  avec échéancier, retards par tranche et garanties → export Excel.
- 📒 **Journal des écritures** — un ou plusieurs codes opération, date
  début, date fin obligatoires ; matricule client, n° compte, sens
  écriture, et localisation hiérarchique (mutuelle → agence → bureau)
  facultatifs → tableau du journal → export Excel.
- 🏦 **État des dépôts** — date d'arrêté obligatoire (dernier solde
  clôturé + mouvements jusqu'à cette date) ; matricule client, compte
  général, n° compte, code type compte, statut compte, exclusion des
  soldes nuls, et localisation hiérarchique facultatifs → tableau des
  soldes débiteurs/créditeurs par compte → export Excel.
- 📈 **Plus gros consommateurs** — date d'arrêté obligatoire (liste
  déroulante, dernière disponible par défaut) ; localisation hiérarchique
  facultative → top 50 des clients emprunteurs par encours cumulé, comptes
  sains (sans impayé) → export Excel.
- 📉 **Plus petits consommateurs** — mêmes critères, classement inversé,
  avec un plancher d'encours (≥ 1000) pour exclure les encours résiduels
  quasi nuls → export Excel.
- ⚠️ **Plus gros contentieux** — mêmes critères, mais sur les clients en
  impayé (PAR 90/180/360), avec les provisions associées → export Excel.
- 💰 **Plus gros déposants** — même logique de calcul que l'État des
  dépôts (dernière clôture + mouvements), mais agrégée par client ;
  date d'arrêté obligatoire (postérieure à la dernière clôture),
  localisation hiérarchique facultative → top 50 des clients par solde
  de dépôts cumulé, du plus élevé au plus faible → export Excel.
- 🪙 **Plus petits déposants** — mêmes critères, classement inversé, avec
  un plancher de solde (≥ 1000 en valeur absolue) pour exclure les
  soldes résiduels quasi nuls → export Excel.

## ⚠️ Important : réseau

L'application se connecte directement à la base Oracle du core banking
(`192.168.0.204:1539`, SID `ace`), qui est une adresse **réseau interne**.
Elle doit donc être lancée depuis un poste ou un serveur qui a accès à ce
réseau (agence, siège, VPN...) — pas depuis un serveur cloud public.

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows : .venv\Scripts\activate
pip install -r requirements.txt
```

## Configuration

Les paramètres de connexion sont dans le fichier `.env` (déjà pré-rempli
avec les identifiants transmis). Si tu dois les changer, modifie ce
fichier (ou repars de `.env.example`) :

```
DB_HOST=192.168.0.204
DB_PORT=1539
DB_SID=ace
DB_USER=ace
DB_PASSWORD=ace
```

## Lancement

```bash
streamlit run app.py
```

L'application s'ouvre dans le navigateur (par défaut http://localhost:8888).

## Authentification

L'application est protégée par un écran de connexion : il faut un compte
pour accéder aux rapports. Les comptes sont stockés dans une base SQLite
locale (`getly_users.db`, créée automatiquement au premier lancement,
**propre à chaque poste/serveur** — comme `.env`, elle n'est jamais
versionnée dans Git, donc chaque déploiement a ses propres comptes).

**Premier lancement :** un compte administrateur par défaut est créé
automatiquement :

```
Identifiant : admin
Mot de passe : admin123
```

Ce mot de passe provisoire doit être changé dès la première connexion —
l'application l'impose avant de donner accès au reste du menu.

**Rôles :**
- *Utilisateur* : accès aux rapports et à « Mon compte » (changer son
  propre mot de passe).
- *Administrateur* : accès en plus à « Administration », pour créer des
  comptes, changer un rôle, activer/désactiver un compte, réinitialiser
  le mot de passe d'un utilisateur (celui-ci devra alors le changer à sa
  prochaine connexion), ou supprimer un compte. Le dernier administrateur
  actif ne peut pas être rétrogradé, désactivé ou supprimé (pour éviter
  de se retrouver sans accès administrateur).

Tout utilisateur peut changer son propre mot de passe depuis « Mon
compte » (ancien mot de passe requis). Les mots de passe sont hachés
(PBKDF2-HMAC-SHA256, sel aléatoire par compte) — jamais stockés en clair.

Sur un nouveau déploiement (ex. premier `git pull` sur le serveur), pense
à te connecter avec `admin` / `admin123`, changer ce mot de passe, puis
créer les comptes de l'équipe depuis « Administration ».

**Erreur `sqlite3.OperationalError: unable to open database file` :**
ça signifie que l'utilisateur système qui exécute l'application n'a pas
le droit d'écrire `getly_users.db` dans le dossier du projet — fréquent
avec un service systemd durci (`ProtectHome`, `ProtectSystem`,
`ReadWritePaths`...). Deux façons de corriger :
- donner à cet utilisateur les droits d'écriture sur le dossier du
  projet (vérifie avec `systemctl cat getly` quel `User=` est utilisé,
  et avec `ls -ld` les permissions du dossier) ; ou
- définir `GETLY_USERS_DB=/chemin/vers/un/dossier/inscriptible/getly_users.db`
  dans `.env` (voir `.env.example`) pour stocker la base ailleurs.

## Utilisation

1. Dans la barre latérale, choisis le **type d'extraction**.
2. Renseigne les champs obligatoires du formulaire, et facultativement
   les filtres avancés (certains menus, comme Mutuelle/Agence/Bureau,
   sont en cascade : choisir une mutuelle restreint les agences et
   bureaux proposés ensuite).
3. Clique sur le bouton de génération : le tableau s'affiche avec les
   totaux utiles.
4. Clique sur **"Télécharger en Excel"** pour récupérer le fichier `.xlsx`
   (mise en forme : en-têtes colorés, montants au format numérique,
   ligne de total le cas échéant).

## Architecture (pour ajouter une nouvelle extraction)

```
getly/
├── app.py                       # Shell Streamlit générique : auth, menu, formulaire,
│                                 # tableau, export — pilote la classe Extraction active
├── auth.py                      # Authentification + administration des comptes (SQLite, hachage)
├── auth_ui.py                   # Écrans Streamlit : connexion, mon compte, administration
├── db.py                        # Connexion Oracle générique (pool + fetch_df, sans plafond)
├── export_excel.py              # Générateur Excel générique (en-têtes, formats, totaux)
├── config.py                    # Lecture des paramètres depuis .env
├── extractions/
│   ├── base.py                  # Interface Extraction (contrat commun)
│   ├── __init__.py              # Registre EXTRACTIONS = [...]
│   ├── reference_data.py        # Référentiel partagé Mutuelle→Agence→Bureau + menu en cascade
│   │                             # + dernière clôture SOLDE_ARRETE + dates d'arrêté ENC_BRUT
│   ├── balance_agee.py          # Module : Balance Agée
│   ├── journal_ecritures.py     # Module : Journal des écritures
│   ├── etat_depots.py           # Module : État des dépôts
│   ├── classement_encours.py    # Modules : Plus gros/petits consommateurs, Plus gros contentieux
│   └── classement_depots.py     # Modules : Plus gros/petits déposants
├── requirements.txt
├── .env / .env.example
├── getly_users.db               # Base des comptes (créée au 1er lancement, exclue de Git)
└── README.md
```

Pour ajouter un nouveau type d'extraction (ex. Balance comptable, Grand
livre, Liste des clients...) :

1. Crée `extractions/ma_nouvelle_extraction.py`.
2. Défini une dataclass de filtres avec une méthode `validate()`.
3. Écris une sous-classe de `Extraction` (voir `extractions/base.py` pour
   le détail du contrat) avec sa requête SQL, son formulaire Streamlit
   (`render_form`) et sa fonction d'exécution (`execute`). Si ton
   extraction a besoin d'un filtre Mutuelle/Agence/Bureau, réutilise
   `extractions/reference_data.py` (fonctions `referentiel_localisation_cached()`
   et `render_localisation_cascade()`) plutôt que de dupliquer la logique.
4. Ajoute une instance de ta classe à `EXTRACTIONS` dans
   `extractions/__init__.py`.

L'application (menu, tableau, export Excel) s'adapte automatiquement —
aucune autre modification n'est nécessaire.

## Colonnes de la Balance Agée

Code mutuelle, Mutuelle, Code agence, Agence, Code bureau, Bureau,
Matricule client, Nom client, Genre, Âge, Classe d'âge, Ancienneté, N°
prêt, Type de prêt, Taille du prêt, Cycle, Date mise en place, Durée
(jours), Durée (mois), Montant capital prêté, Frais d'actes, Montant
frais de dossier, Assurance agricole, Montant intérêt prêt, Intérêt
capitalisé, Taux d'intérêt, Montant échéance, Périodicité échéance,
Nombre d'échéances, Date première échéance, Date dernière échéance,
Encours capital, Impayé capital, Montant impayé, Durée impayé, Crédit
jour, Retard 29/30/60/90/180/360/720 jours, Cycle prêt, Code secteur,
Secteur d'activité, Sous-secteur d'activité, Ressource affectée,
Catégorie, Nombre d'hommes, Nombre de femmes, Garantie(s), Valeur
garantie.

Un prêt en cours par ligne (table `ENC_BRUT`, encours non nul, hors
pertes) à la date d'arrêté choisie (liste déroulante des dates
disponibles). Pas de plafond sur le nombre de résultats — filtrer par
localisation, secteur ou classe d'âge si le volume est trop important.

## Colonnes du journal des écritures

Le tableau reprend le format standard OHADA/comptable, enrichi des
informations client/bureau/agence/mutuelle (utiles puisque ce sont aussi
des filtres) :

Date écriture, Date valeur, N° pièce, Code journal, Code opération,
Libellé opération, N° compte, Intitulé compte, Libellé écriture, Débit,
Crédit, Solde, Matricule client, Raison sociale, Prénom client, Code
bureau, Bureau, Code agence, Agence, Code mutuelle, Mutuelle.

Le **Solde** est un solde cumulé calculé sur les écritures renvoyées par
l'extraction (par compte, dans l'ordre chronologique) — ce n'est **pas**
le solde comptable total du compte (qui dépend d'écritures antérieures
non incluses si la période sélectionnée ne remonte pas jusqu'à
l'ouverture du compte).

## Colonnes de l'état des dépôts

Code mutuelle, Mutuelle, Code agence, Agence, Code bureau, Bureau,
Compte général, N° compte, Code type compte, Matricule client, Solde
débiteur, Solde créditeur, Date arrêté, Statut compte.

Seuls les comptes de dépôts (compte général commençant par "25") sont
inclus. Le solde à la date d'arrêté = dernier solde clôturé connu dans
`SOLDE_ARRETE` (sa date d'arrêté la plus récente) + somme des mouvements
de `ECRITURE` entre le lendemain de cette clôture et la date d'arrêté
choisie (incluse). La date d'arrêté demandée doit donc toujours être
postérieure à la dernière clôture disponible — l'application l'indique
et bloque sinon.

## Colonnes des classements (Plus gros/petits consommateurs, Plus gros contentieux)

Matricule client, Nom client, Secteur, Encours capital cumulé,
Garantie(s), *Provisions (uniquement Plus gros contentieux)*, Code
bureau, Bureau, Code agence, Agence, Code mutuelle, Mutuelle, Rang.

Les 3 extractions partagent la même logique (table `ENC_BRUT` à la date
d'arrêté choisie, encours cumulé par client sur ses prêts non affectés
en ressources externes, hors pertes) et ne diffèrent que par le seuil
d'encours, la condition d'impayé et l'ordre du classement (voir le
docstring de `extractions/classement_encours.py`). Seuls les 50 premiers
sont retournés dans chaque cas.

## Colonnes des classements de dépôts (Plus gros/petits déposants)

Matricule client, Nom client, Solde cumulé, Code bureau, Bureau, Code
agence, Agence, Code mutuelle, Mutuelle, Rang.

Même calcul de solde que l'État des dépôts (dernier solde clôturé dans
`SOLDE_ARRETE` + mouvements de `ECRITURE` jusqu'à la date d'arrêté
choisie), mais agrégé par client (`MATRICULE_CLIENT`) sur l'ensemble de
ses comptes de dépôts, puis classé. La date d'arrêté doit être
postérieure à la dernière clôture disponible (même contrainte que
l'État des dépôts). Les plus petits déposants sont filtrés à partir
d'un solde cumulé ≥ 1000 (en valeur absolue), comme pour les classements
d'encours. Seuls les 50 premiers sont retournés dans chaque cas.

## ⚠️ Sécurité

- Le fichier `.env` contient un identifiant/mot de passe Oracle en clair.
  Il est exclu de Git via `.gitignore`, mais il reste **en clair sur le
  disque** : ne le partage pas, et évite de l'envoyer par email/chat.
- Il est fortement recommandé de :
  - créer un compte Oracle dédié, **en lecture seule (SELECT only)** sur
    les tables utilisées (`ECRITURE, COMPTE, CLIENT, BUREAU, REGION,
    REGION_OPERAT, MUTUELLE, OPERATION, SOLDE_ARRETE, ENC_BRUT, PRET,
    TYPE_PRET, GARANTIES, TYPE_GARANTIE, SOUS_SECTEUR, SECTEUR,
    CATEGORIE`, et celles des futures extractions), plutôt que d'utiliser
    un compte applicatif générique ;
  - changer le mot de passe communiqué dans la conversation d'origine,
    puisqu'il a transité en clair.
- Les extractions ne sont pas plafonnées en nombre de lignes : une
  recherche très large peut ramener beaucoup de données et ralentir
  l'application. Affiner les filtres (dates, mutuelle/agence/bureau...)
  reste la meilleure protection.
- L'application impose désormais une connexion (voir « Authentification »
  ci-dessus). Change le mot de passe de `admin` dès le premier lancement
  sur chaque nouveau déploiement (poste ou serveur). Le fichier
  `getly_users.db` contient les mots de passe **hachés** (jamais en
  clair) mais reste un fichier sensible : il est exclu de Git, ne le
  partage pas non plus.
- Cette authentification protège l'accès à l'application elle-même, mais
  ne restreint pas encore les données visibles selon l'utilisateur (tous
  les comptes voient les mêmes rapports). Si l'application est exposée
  au-delà du réseau interne, ajoute en complément un reverse proxy
  (nginx) ou une restriction par IP/VPN.

## Déploiement (GitHub + serveur)

Le dépôt Git est prêt (`.env` exclu, seul `.env.example` est versionné) :

```bash
# Sur ton poste, après avoir créé un dépôt PRIVÉ sur GitHub
git remote add origin git@github.com:TON-ORG/getly.git
git push -u origin main

# Sur le serveur (qui a accès au réseau 192.168.0.204)
git clone git@github.com:TON-ORG/getly.git
cd getly
cp .env.example .env
nano .env                     # renseigne les vraies infos de connexion
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py --server.address 0.0.0.0 --server.port 8888
```

Au tout premier lancement sur le serveur, `getly_users.db` est créé
automatiquement avec le compte `admin` / `admin123` par défaut —
connecte-toi et change ce mot de passe immédiatement (voir
« Authentification » ci-dessus), puis crée les comptes de l'équipe.

Mises à jour futures sur le serveur : `git pull` (le `.env` et le
`getly_users.db` locaux ne sont jamais touchés), puis redémarrer le
service (`sudo systemctl restart getly` si tu utilises le service
systemd décrit précédemment).

## Évolutions possibles

- Extractions visibles/filtrées selon le rôle ou la localisation de
  l'utilisateur (l'authentification de base est en place, cette
  granularité reste à ajouter si besoin).
- Nouvelles extractions (balance, grand livre, situation client...).
- Export PDF en plus de l'Excel.
