"""Portail Tissandier — Merci Handy.

Application Streamlit SÉPARÉE du hub (dépôt public merci-handy-tissandier) :
Tissandier n'y voit que ses demandes de transport, rien d'autre du hub
(le dossier pages/ du hub n'est pas chargé, il est à la racine du dépôt).

Tissandier y fait trois choses :
  1. coter une demande (prix HT + commentaire) ;
  2. confirmer l'enlèvement et la livraison (dates + référence CO…) ;
  3. déposer la lettre de voiture.
Elle télécharge la packing list déposée par Merci Handy.

Secrets de cette app (Streamlit Cloud → Settings → Secrets) :
  [gcp_service_account] …          (le même que le hub)
  [tissandier] access_code, drive_folder_id, portal_url
  [slack] webhook_url              (#fr-log-b2b-marketplaces : notifier Merci Handy)
"""
from __future__ import annotations

import hmac
import sys
from pathlib import Path

import streamlit as st

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from services import tissandier as tz  # noqa: E402
from services import tissandier_ui as ui  # noqa: E402

st.set_page_config(page_title="Merci Handy × Tissandier", page_icon="🚚", layout="wide")
st.markdown(ui.CSS + "<style>[data-testid='stSidebarNav']{display:none}</style>",
            unsafe_allow_html=True)
st.markdown('<div class="tz-hero"><h1>🚚 Merci Handy × Tissandier</h1>'
            '<p>Vos demandes de transport Merci Handy : cotez, confirmez, déposez la lettre de voiture.</p></div>',
            unsafe_allow_html=True)

# --- Accès ------------------------------------------------------------------
code_ok = ui.secret("tissandier", "access_code")
if not code_ok:
    st.error("Portail non configuré (code d'accès manquant).")
    st.stop()
if not st.session_state.get("tz_auth"):
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid.form("login"):
        st.markdown("#### Connexion")
        code = st.text_input("Code d'accès", type="password")
        if st.form_submit_button("Entrer", type="primary", use_container_width=True):
            if hmac.compare_digest(code.strip(), str(code_ok)):
                st.session_state.tz_auth = True
                st.rerun()
            else:
                st.error("Code incorrect.")
    st.stop()

tz.SUIVI_SHEET_ID = ui.secret("tissandier", "sheet_id") or ""
gc = ui.gclient()
if gc is None or not tz.SUIVI_SHEET_ID:
    st.error("Connexion indisponible, merci de prévenir Merci Handy.")
    st.stop()

# Libellés vus par Tissandier (ce qu'elle doit faire, pas l'état interne)
PILLS = {
    tz.A_COTER: ("💶 À coter", "#fff0f6", "#c2185b"),
    tz.COTEE: ("⏳ Prix envoyé, attente Merci Handy", "#eaf3ff", "#1d5fb8"),
    tz.VALIDEE: ("✅ À confirmer", "#fff0f6", "#c2185b"),
    tz.CONFIRMEE: ("📄 Lettre de voiture à déposer", "#fff1e0", "#a35200"),
    tz.LV_DEPOSEE: ("✔️ Complet", "#e8f8ee", "#1e7a44"),
    tz.LIVREE: ("🏁 Livré", "#f0f0f3", "#555"),
}

demandes = [d for d in tz.load(gc) if d["statut"] in tz.STATUTS_TISSANDIER]
demandes.sort(key=lambda d: (d.get("date_mad") or "99/99/9999")[-4:] + (d.get("date_mad") or "")[3:5] + (d.get("date_mad") or "")[:2])


def needs_me(d: dict) -> bool:
    return d["statut"] in (tz.A_COTER, tz.VALIDEE) or (d["statut"] == tz.CONFIRMEE and not d.get("lettre_voiture"))


todo = [d for d in demandes if needs_me(d)]
attente = [d for d in demandes if not needs_me(d) and d["statut"] not in (tz.LV_DEPOSEE, tz.LIVREE)]
fini = [d for d in demandes if d["statut"] in (tz.LV_DEPOSEE, tz.LIVREE)]

st.markdown(ui.kpis_html([
    ("à coter", sum(d["statut"] == tz.A_COTER for d in demandes), True),
    ("à confirmer", sum(d["statut"] == tz.VALIDEE for d in demandes), True),
    ("lettres de voiture à déposer", sum(d["statut"] == tz.CONFIRMEE and not d.get("lettre_voiture") for d in demandes), True),
    ("en attente de Merci Handy", len(attente), False),
]), unsafe_allow_html=True)


def act(d: dict, action: str, values: dict) -> None:
    try:
        new = tz.apply_action(d, "tissandier", action, values, who="Tissandier")
    except ValueError as e:
        st.error(str(e))
        return
    ui.save_and_sync(new)
    msg = {
        "coter": f"💶 *Tissandier a coté* {new['client']} ({new['bl']}) : *{new['prix_ht']} € HT* — à valider dans le hub (page 🚚 Tissandier).",
        "confirmer": f"✅ *Tissandier confirme* {new['client']} ({new['bl']}) : enlèvement {new['date_enlevement']} → livraison {new['date_livraison']}"
                     + (f" · réf. {new['ref_tissandier']}" if new.get("ref_tissandier") else ""),
        "deposer_lv": f"📄 *Lettre de voiture déposée* — {new['client']} ({new['bl']}).",
    }[action]
    ui.notify(msg, "mh")
    st.toast("Merci, c'est enregistré !", icon="✅")
    st.rerun()


def lv_form(d: dict, key: str, label: str) -> None:
    with st.form(key, border=False):
        files = st.file_uploader(label, accept_multiple_files=True, key=f"u_{key}")
        if st.form_submit_button("📄 Déposer la lettre de voiture", type="primary"):
            try:
                refs = ui.upload(files, f"{d['bl']} lettre de voiture")
            except Exception as e:
                st.error(str(e))
                refs = []
            if refs:
                act(d, "deposer_lv", {"lettre_voiture": "\n".join(tz.file_refs(d.get("lettre_voiture")) + refs)})
            elif not files:
                st.error("Ajoutez le fichier de la lettre de voiture.")


def card(d: dict, actions: bool) -> None:
    with st.container(border=True):
        left, right = st.columns([3, 2], gap="large")
        with left:
            st.markdown(ui.card_html(d, PILLS), unsafe_allow_html=True)
            ui.download_buttons(d.get("packing_list"), "Packing list", f"pl_{d['id']}")
            ui.details(d)
        with right:
            if not actions:
                if d.get("prix_ht"):
                    st.markdown(f'<div class="tz-price">{d["prix_ht"]} € HT</div>', unsafe_allow_html=True)
                ui.download_buttons(d.get("lettre_voiture"), "Lettre de voiture", f"lv_{d['id']}")
                return
            if d["statut"] == tz.A_COTER:
                st.markdown("**Votre prix**")
                with st.form(f"q_{d['id']}", border=False):
                    prix = st.text_input("Prix HT (€)", d.get("prix_ht") or "", placeholder="ex. 206,40")
                    com = st.text_area("Commentaire (facultatif)", d.get("commentaire_tissandier") or "",
                                       placeholder="délai, groupage possible…", height=70)
                    if st.form_submit_button("💶 Envoyer le prix", type="primary", use_container_width=True):
                        act(d, "coter", {"prix_ht": prix, "commentaire_tissandier": com})
            elif d["statut"] == tz.VALIDEE:
                st.markdown(f'Prix validé par Merci Handy : <span class="tz-price">{d["prix_ht"]} € HT</span>',
                            unsafe_allow_html=True)
                with st.form(f"c_{d['id']}", border=False):
                    a, b = st.columns(2)
                    enl = a.date_input("Enlèvement chez BX", value=None, format="DD/MM/YYYY")
                    liv = b.date_input("Livraison", value=None, format="DD/MM/YYYY")
                    ref = st.text_input("Votre référence", d.get("ref_tissandier") or "", placeholder="CO2610-…")
                    if st.form_submit_button("✅ Confirmer le transport", type="primary", use_container_width=True):
                        act(d, "confirmer", {"date_enlevement": enl.strftime("%d/%m/%Y") if enl else "",
                                             "date_livraison": liv.strftime("%d/%m/%Y") if liv else "",
                                             "ref_tissandier": ref})
            else:
                lv_form(d, f"l_{d['id']}", "Lettre de voiture (PDF ou photo)")


t1, t2, t3 = st.tabs([f"À traiter ({len(todo)})", f"En attente de Merci Handy ({len(attente)})",
                      f"Terminées ({len(fini)})"])
with t1:
    if not todo:
        st.markdown('<div class="tz-empty">🎉 Rien en attente. Merci !</div>', unsafe_allow_html=True)
    for d in todo:
        card(d, actions=True)
with t2:
    if not attente:
        st.markdown('<div class="tz-empty">Aucune demande en attente.</div>', unsafe_allow_html=True)
    for d in attente:
        card(d, actions=False)
with t3:
    for d in fini:
        card(d, actions=False)
