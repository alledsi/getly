"""
Écrans Streamlit liés à l'authentification : connexion, changement de mot
de passe (forcé ou volontaire), et administration des utilisateurs.
Toute la logique (hachage, base SQLite) est dans `auth.py` — ce fichier
ne fait que l'affichage.
"""

from __future__ import annotations

from typing import Optional

import streamlit as st

import auth


def _programmer_message(kind: str, message: str) -> None:
    """Mémorise un message à afficher juste après un `st.rerun()` — appeler
    `st.success()`/`st.error()` puis `st.rerun()` immédiatement après ne
    laisse pas le temps au message de s'afficher, il faut le reporter au
    prochain run."""
    st.session_state["_message_en_attente"] = (kind, message)


def afficher_message_en_attente() -> None:
    """À appeler une fois en haut de `app.py`, avant l'affichage de la page
    courante : affiche puis efface le message laissé par `_programmer_message`."""
    en_attente = st.session_state.pop("_message_en_attente", None)
    if en_attente:
        kind, message = en_attente
        getattr(st, kind)(message)


def render_login() -> None:
    st.title("📊 Getly")
    st.caption("Rapports et extractions — ACEP")
    st.subheader("Connexion")

    with st.form("connexion_form"):
        username = st.text_input("Identifiant")
        password = st.text_input("Mot de passe", type="password")
        submitted = st.form_submit_button("Se connecter", width="stretch", type="primary")

    if submitted:
        user = auth.authentifier(username, password)
        if user:
            st.session_state["user"] = user
            st.rerun()
        else:
            st.error("Identifiant ou mot de passe incorrect, ou compte désactivé.")


def render_forced_password_change(user: dict) -> None:
    st.title("📊 Getly")
    st.warning(
        "Pour des raisons de sécurité, tu dois changer ton mot de passe "
        "avant de continuer."
    )

    with st.form("changement_force_form"):
        ancien = st.text_input("Mot de passe actuel", type="password")
        nouveau = st.text_input("Nouveau mot de passe", type="password")
        confirmation = st.text_input("Confirmer le nouveau mot de passe", type="password")
        submitted = st.form_submit_button(
            "Changer le mot de passe", width="stretch", type="primary"
        )

    if submitted:
        if nouveau != confirmation:
            st.error("Les deux mots de passe ne correspondent pas.")
        else:
            ok, message = auth.changer_mon_mot_de_passe(user["id"], ancien, nouveau)
            if ok:
                st.session_state["user"]["doit_changer_mdp"] = False
                _programmer_message("success", message)
                st.rerun()
            else:
                st.error(message)


def render_account_page(user: dict) -> None:
    st.header("👤 Mon compte")
    st.write(f"**Identifiant :** {user['username']}")
    if user.get("nom_complet"):
        st.write(f"**Nom :** {user['nom_complet']}")
    st.write(f"**Rôle :** {'Administrateur' if user['role'] == 'admin' else 'Utilisateur'}")

    st.divider()
    st.subheader("Changer mon mot de passe")

    with st.form("changement_mdp_form", clear_on_submit=True):
        ancien = st.text_input("Mot de passe actuel", type="password")
        nouveau = st.text_input("Nouveau mot de passe", type="password")
        confirmation = st.text_input("Confirmer le nouveau mot de passe", type="password")
        submitted = st.form_submit_button("Mettre à jour", type="primary")

    if submitted:
        if nouveau != confirmation:
            st.error("Les deux mots de passe ne correspondent pas.")
        else:
            ok, message = auth.changer_mon_mot_de_passe(user["id"], ancien, nouveau)
            (st.success if ok else st.error)(message)


def render_admin_page(user: dict) -> None:
    st.header("🛠️ Administration des utilisateurs")

    df = auth.lister_utilisateurs()

    if df.empty:
        st.info("Aucun utilisateur.")
    else:
        affichage = df.drop(columns=["id"]).copy()
        affichage["role"] = affichage["role"].map(
            {"admin": "Administrateur", "user": "Utilisateur"}
        )
        affichage["actif"] = affichage["actif"].map({1: "Oui", 0: "Non"})
        affichage["doit_changer_mdp"] = affichage["doit_changer_mdp"].map({1: "Oui", 0: "Non"})
        affichage = affichage.rename(
            columns={
                "username": "Identifiant",
                "nom_complet": "Nom complet",
                "role": "Rôle",
                "actif": "Actif",
                "doit_changer_mdp": "Doit changer son mot de passe",
                "cree_le": "Créé le",
            }
        )
        st.dataframe(affichage, width="stretch", hide_index=True)

    st.divider()
    st.subheader("Créer un utilisateur")

    with st.form("creation_utilisateur_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            nouvel_identifiant = st.text_input("Identifiant")
            nouveau_role = st.selectbox(
                "Rôle",
                options=["user", "admin"],
                format_func=lambda r: "Administrateur" if r == "admin" else "Utilisateur",
            )
        with c2:
            nouveau_nom = st.text_input("Nom complet (facultatif)")
            nouveau_mdp = st.text_input("Mot de passe provisoire", type="password")
        submitted_creation = st.form_submit_button("Créer", type="primary")

    if submitted_creation:
        ok, message = auth.creer_utilisateur(
            nouvel_identifiant, nouveau_mdp, role=nouveau_role, nom_complet=nouveau_nom
        )
        if ok:
            _programmer_message(
                "success",
                f"{message} Il/elle devra changer ce mot de passe à sa première connexion.",
            )
            st.rerun()
        else:
            st.error(message)

    if df.empty:
        return

    st.divider()
    st.subheader("Gérer un utilisateur existant")

    options = {
        f"{row.username} ({'Administrateur' if row.role == 'admin' else 'Utilisateur'})": row.id
        for row in df.itertuples()
    }
    choix = st.selectbox(
        "Utilisateur", options=list(options.keys()), index=None, placeholder="Choisir un utilisateur"
    )
    if not choix:
        return

    cible_id = int(options[choix])
    cible = df[df["id"] == cible_id].iloc[0]
    est_soi_meme = cible_id == user["id"]

    if est_soi_meme:
        st.caption(
            "Tu gères ton propre compte ici : utilise plutôt « Mon compte » dans "
            "le menu pour changer ton mot de passe. Le rôle et le statut de ton "
            "propre compte ne peuvent pas être modifiés depuis cette page."
        )
    else:
        c1, c2, c3 = st.columns(3)
        with c1:
            nouveau_role_cible = st.selectbox(
                "Rôle",
                options=["user", "admin"],
                index=["user", "admin"].index(cible["role"]),
                format_func=lambda r: "Administrateur" if r == "admin" else "Utilisateur",
                key=f"role_{cible_id}",
            )
            if st.button("Mettre à jour le rôle", key=f"maj_role_{cible_id}"):
                ok, message = auth.modifier_role(cible_id, nouveau_role_cible)
                if ok:
                    _programmer_message("success", message)
                    st.rerun()
                else:
                    st.error(message)
        with c2:
            est_actif = bool(cible["actif"])
            if est_actif:
                if st.button("Désactiver ce compte", key=f"desactiver_{cible_id}"):
                    ok, message = auth.activer_desactiver(cible_id, False)
                    if ok:
                        _programmer_message("success", message)
                        st.rerun()
                    else:
                        st.error(message)
            else:
                if st.button("Réactiver ce compte", key=f"activer_{cible_id}"):
                    ok, message = auth.activer_desactiver(cible_id, True)
                    if ok:
                        _programmer_message("success", message)
                        st.rerun()
                    else:
                        st.error(message)
        with c3:
            if st.button("🗑️ Supprimer ce compte", key=f"supprimer_{cible_id}"):
                ok, message = auth.supprimer_utilisateur(cible_id)
                if ok:
                    _programmer_message("success", message)
                    st.rerun()
                else:
                    st.error(message)

        st.caption(
            "Réinitialiser le mot de passe (l'utilisateur devra le changer à sa "
            "prochaine connexion) :"
        )
        with st.form(f"reset_mdp_form_{cible_id}", clear_on_submit=True):
            nouveau_mdp_reset = st.text_input(
                "Nouveau mot de passe provisoire", type="password", key=f"reset_mdp_{cible_id}"
            )
            submitted_reset = st.form_submit_button("Réinitialiser le mot de passe")
        if submitted_reset:
            ok, message = auth.reinitialiser_mot_de_passe(cible_id, nouveau_mdp_reset)
            (st.success if ok else st.error)(message)
