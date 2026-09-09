-- ============================================================
-- RPT_RENTABILITE : compte de résultat par rubrique/compte,
-- catégorie (mutuelle ou 'Consolidé') et date d'arrêté.
-- ============================================================
CREATE TABLE RPT_RENTABILITE (
    RUBRIQUE      VARCHAR2(50)   NOT NULL,
    COMPTE        NUMBER(12)     NOT NULL,
    CHAPITRE      VARCHAR2(100),
    SOLDE         NUMBER(18,2),
    CATEGORIE     VARCHAR2(50)   NOT NULL,   -- nom de la mutuelle, ou 'Consolidé'
    DATE_ARRETE   DATE           NOT NULL,
    CONSTRAINT PK_RPT_RENTABILITE PRIMARY KEY (COMPTE, CATEGORIE, DATE_ARRETE)
);

-- ============================================================
-- RPT_ENCOURS : encours global par catégorie et date d'arrêté.
-- ============================================================
CREATE TABLE RPT_ENCOURS (
    CATEGORIE     VARCHAR2(50)   NOT NULL,   -- nom de la mutuelle, ou 'Consolidé'
    MONTANT       NUMBER(18,2)   NOT NULL,
    DATE_ARRETE   DATE           NOT NULL,
    CONSTRAINT PK_RPT_ENCOURS PRIMARY KEY (CATEGORIE, DATE_ARRETE)
);
