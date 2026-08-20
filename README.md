# Getly

Plateforme d'extractions comptables pour le core banking ACEP. Chaque
extraction est un module indépendant (formulaire + requête + export
Excel) branché sur une interface commune, ce qui permet d'en ajouter de
nouvelles facilement.

**Extractions disponibles aujourd'hui :**

- 📒 **Journal des écritures** — formulaire (code opération, date début,
  date fin obligatoires ; matricule client, n° compte, bureau, agence,
  mutuelle facultatifs) → tableau du journal des écritures → export Excel.

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

1. Dans la barre latérale, choisis le **type d'extraction** (pour
   l'instant : Journal des écritures).
2. Clique sur **"Tester la connexion à la base"** pour vérifier que
   l'application arrive à joindre Oracle.
3. Renseigne les champs obligatoires du formulaire, et facultativement
   les filtres avancés.
4. Clique sur le bouton de génération : le tableau s'affiche avec les
   totaux utiles.
5. Clique sur **"Télécharger en Excel"** pour récupérer le fichier `.xlsx`
   (mise en forme : en-têtes colorés, montants au format numérique,
   ligne de total le cas échéant).

## Architecture (pour ajouter une nouvelle extraction)

```
getly/
├── app.py                       # Shell Streamlit générique : menu, formulaire,
│                                 # tableau, export — pilote la classe Extraction active
├── db.py                        # Connexion Oracle générique (pool + fetch_df)
├── export_excel.py              # Générateur Excel générique (en-têtes, formats, totaux)
├── config.py                    # Lecture des paramètres depuis .env
├── extractions/
│   ├── base.py                  # Interface Extraction (contrat commun)
│   ├── __init__.py              # Registre EXTRACTIONS = [...]
│   └── journal_ecritures.py     # 1er module : Journal des écritures
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
   (`render_form`) et sa fonction d'exécution (`execute`).
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

## ⚠️ Sécurité

- Le fichier `.env` contient un identifiant/mot de passe Oracle en clair.
  Il est exclu de Git via `.gitignore`, mais il reste **en clair sur le
  disque** : ne le partage pas, et évite de l'envoyer par email/chat.
- Il est fortement recommandé de :
  - créer un compte Oracle dédié, **en lecture seule (SELECT only)** sur
    les tables utilisées (`ECRITURE, COMPTE, CLIENT, BUREAU, REGION,
    MUTUELLE, OPERATION`, et celles des futures extractions), plutôt que
    d'utiliser un compte applicatif générique ;
  - changer le mot de passe communiqué dans la conversation d'origine,
    puisqu'il a transité en clair.
- Chaque extraction est plafonnée à `MAX_ROWS` lignes (50 000 par défaut,
  réglable dans `.env`) pour éviter de surcharger l'application sur une
  période/un filtre trop large.
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
jamais touché).

## Évolutions possibles

- Authentification des utilisateurs de l'application elle-même.
- Nouvelles extractions (balance, grand livre, situation client...).
- Filtre par plusieurs codes opération à la fois.
- Export PDF en plus de l'Excel.
