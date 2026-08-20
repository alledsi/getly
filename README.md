# Getly

Plateforme d'extractions comptables pour le core banking ACEP. Chaque
extraction est un module indépendant (formulaire + requête + export
Excel) branché sur une interface commune, ce qui permet d'en ajouter de
nouvelles facilement.

**Extractions disponibles aujourd'hui :**

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

L'application s'ouvre dans le navigateur (par défaut http://localhost:8501).

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
├── app.py                       # Shell Streamlit générique : menu, formulaire,
│                                 # tableau, export — pilote la classe Extraction active
├── db.py                        # Connexion Oracle générique (pool + fetch_df, sans plafond)
├── export_excel.py              # Générateur Excel générique (en-têtes, formats, totaux)
├── config.py                    # Lecture des paramètres depuis .env
├── extractions/
│   ├── base.py                  # Interface Extraction (contrat commun)
│   ├── __init__.py              # Registre EXTRACTIONS = [...]
│   ├── reference_data.py        # Référentiel partagé Mutuelle→Agence→Bureau + menu en cascade
│   ├── journal_ecritures.py     # Module : Journal des écritures
│   ├── etat_depots.py           # Module : État des dépôts
│   └── classement_encours.py    # Modules : Plus gros/petits consommateurs, Plus gros contentieux
├── requirements.txt
├── .env / .env.example
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

## ⚠️ Sécurité

- Le fichier `.env` contient un identifiant/mot de passe Oracle en clair.
  Il est exclu de Git via `.gitignore`, mais il reste **en clair sur le
  disque** : ne le partage pas, et évite de l'envoyer par email/chat.
- Il est fortement recommandé de :
  - créer un compte Oracle dédié, **en lecture seule (SELECT only)** sur
    les tables utilisées (`ECRITURE, COMPTE, CLIENT, BUREAU, REGION,
    MUTUELLE, OPERATION, SOLDE_ARRETE, ENC_BRUT, PRET, TYPE_PRET,
    GARANTIES, TYPE_GARANTIE, SOUS_SECTEUR, SECTEUR`, et celles des
    futures extractions), plutôt que d'utiliser un compte applicatif
    générique ;
  - changer le mot de passe communiqué dans la conversation d'origine,
    puisqu'il a transité en clair.
- Les extractions ne sont pas plafonnées en nombre de lignes : une
  recherche très large peut ramener beaucoup de données et ralentir
  l'application. Affiner les filtres (dates, mutuelle/agence/bureau...)
  reste la meilleure protection.
- Streamlit n'a pas d'authentification intégrée : si l'application est
  exposée sur le réseau, mets un reverse proxy (nginx) avec
  authentification devant, ou restreins l'accès par IP/VPN — les données
  affichées sont des écritures comptables et des informations clients.

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
streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```

Mises à jour futures sur le serveur : `git pull` (le `.env` local n'est
jamais touché), puis redémarrer le service (`sudo systemctl restart getly`
si tu utilises le service systemd décrit précédemment).

## Évolutions possibles

- Authentification des utilisateurs, avec extractions visibles selon le
  rôle (voir discussion en cours).
- Nouvelles extractions (balance, grand livre, situation client...).
- Export PDF en plus de l'Excel.
