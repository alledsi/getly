-- Correction : compte oublie dans le referentiel rubriques.xlsx initial
-- 701260000 INTERETS SUR DAT -> rubrique 'Interets payes' (meme famille que 701330000, 702121000, ...)
-- SOLDE = mouvement du mois, classe 7 = MvtCredit - MvtDebit (meme regle que les autres comptes)
-- DELETE defensif (idempotent) au cas ou une tentative precedente aurait deja insere cette ligne :
DELETE FROM RPT_RENTABILITE WHERE COMPTE = 701260000 AND CATEGORIE = 'Consolidé' AND DATE_ARRETE = TO_DATE('2026-07-31','YYYY-MM-DD');

INSERT INTO RPT_RENTABILITE (RUBRIQUE, COMPTE, CHAPITRE, SOLDE, CATEGORIE, DATE_ARRETE) VALUES ('Intérêts payés', 701260000, '701260000  INTERETS SUR DAT', -7926693.0, 'Consolidé', TO_DATE('2026-07-31','YYYY-MM-DD'));

COMMIT;