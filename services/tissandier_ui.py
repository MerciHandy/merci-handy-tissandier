"""Briques Streamlit communes à la page « 🚚 Tissandier » du hub (Merci Handy)
et au portail Tissandier (portail/app.py) : accès Google, notifications Slack,
affichage d'une demande.

Secrets utilisés :
  [gcp_service_account]          compte de service (éditeur du fichier de suivi BX)
  [tissandier]
    access_code = "…"            code d'accès du portail (Tissandier)
    drive_folder_id = "…"        dossier Drive des packing lists / lettres de voiture
                                  (partagé en éditeur au compte de service)
    portal_url = "https://…"     URL du portail (mise dans les notifications)
    slack_webhook = "https://hooks.slack.com/…"   canal partagé avec Tissandier (facultatif)
  [slack] webhook_url            #fr-log-b2b-marketplaces (notifications côté Merci Handy)
"""
from __future__ import annotations

from typing import Optional

import requests
import streamlit as st

from services import tissandier as tz

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets",
           "https://www.googleapis.com/auth/drive"]


def secret(section: str, key: str) -> Optional[str]:
    try:
        return st.secrets[section][key]
    except Exception:
        return None


def creds():
    try:
        sa = dict(st.secrets["gcp_service_account"])
    except Exception:
        return None
    from google.oauth2 import service_account
    return service_account.Credentials.from_service_account_info(sa, scopes=_SCOPES)


@st.cache_resource(show_spinner=False)
def gclient():
    c = creds()
    if c is None:
        return None
    import gspread
    return gspread.authorize(c)


def notify(text: str, to: str) -> None:
    """to = « mh » (#fr-log-b2b-marketplaces) ou « tissandier » (canal partagé)."""
    hook = secret("slack", "webhook_url") if to == "mh" else secret("tissandier", "slack_webhook")
    if not hook:
        return
    try:
        requests.post(hook, json={"text": text}, timeout=10)
    except Exception:
        pass


def portal_link() -> str:
    return secret("tissandier", "portal_url") or ""


def summary_md(d: dict) -> str:
    """Bloc récapitulatif d'une demande (markdown)."""
    lines = [
        f"**{d['client']}** — {d['bl']}" + (f" · commande `{d['ref_commande']}`" if d.get("ref_commande") else ""),
        f"📍 {d['adresse_livraison'].replace(chr(10), ', ')}" if d.get("adresse_livraison") else "📍 adresse à compléter",
        f"📦 {d.get('nb_palettes') or '?'} palette(s) · {d.get('dimensions') or 'dimensions ?'} · "
        f"{d.get('poids_kg') or '?'} kg"
        + (" · ⚠️ matière dangereuse" if d.get("matiere_dangereuse") else ""),
        f"🗓️ Mise à dispo chez BX (Neufchâteau) : **{d.get('date_mad') or '?'}** · "
        f"livraison demandée : **{d.get('date_livraison_demandee') or '?'}**",
    ]
    if d.get("rdv") or d.get("contact_rdv"):
        lines.append(f"📞 RDV : {d.get('rdv') or ''} {d.get('contact_rdv') or ''}".replace("\n", " "))
    if d.get("commentaire_mh"):
        lines.append(f"💬 Merci Handy : {d['commentaire_mh']}")
    if d.get("prix_ht"):
        lines.append(f"💶 Prix Tissandier : **{d['prix_ht']} € HT**"
                     + (f" — {d['commentaire_tissandier']}" if d.get("commentaire_tissandier") else ""))
    if d.get("date_enlevement"):
        lines.append(f"🚚 Enlèvement {d['date_enlevement']} → livraison {d.get('date_livraison')}"
                     + (f" · réf. {d['ref_tissandier']}" if d.get("ref_tissandier") else ""))
    return "  \n".join(lines)


def download_buttons(field_value: str, label: str, key: str) -> None:
    refs = tz.file_refs(field_value)
    if not refs:
        return
    c = creds()
    for i, ref in enumerate(refs):
        name = ref.partition("|")[2] or f"fichier_{i + 1}"
        try:
            fname, data = tz.drive_download(c, ref)
            st.download_button(f"⬇️ {label} : {fname}", data, file_name=fname, key=f"{key}_{i}")
        except Exception as e:
            st.caption(f"⚠️ {name} indisponible ({e})")


def upload(files, prefix: str) -> list[str]:
    """Dépose les fichiers dans le dossier Drive, renvoie leurs références."""
    folder = secret("tissandier", "drive_folder_id")
    if not folder:
        raise RuntimeError("Dossier Drive non configuré ([tissandier].drive_folder_id).")
    out = []
    for f in files or []:
        out.append(tz.drive_upload(creds(), folder, f"{prefix} - {f.name}", f.getvalue(),
                                   f.type or "application/octet-stream"))
    return out


def save_and_sync(d: dict) -> None:
    gc = gclient()
    tz.save(gc, d)
    try:
        tz.push_to_suivi(gc, d)
    except Exception as e:
        st.caption(f"⚠️ Fichier de suivi BX non mis à jour : {e}")


# ---------------------------------------------------------------------------
# Habillage (cartes, statuts, frise d'avancement)
# ---------------------------------------------------------------------------
import html as _html
import re as _re

CSS = """
<style>
:root{--mh-pink:#ff6b9d;--mh-purple:#b266ff;--mh-blue:#66b2ff;--mh-ink:#2b2640;--mh-muted:#6b6580;}
.block-container{padding-top:1.6rem;max-width:1180px}
.tz-hero{background:linear-gradient(120deg,#ff6b9d 0%,#b266ff 45%,#66b2ff 100%);color:#fff;
  border-radius:18px;padding:22px 26px;margin-bottom:18px;box-shadow:0 8px 24px rgba(178,102,255,.22)}
.tz-hero h1{margin:0;font-size:26px;font-weight:800;color:#fff;letter-spacing:-.3px}
.tz-hero p{margin:4px 0 0;opacity:.92;font-size:14px}
.tz-kpis{display:flex;gap:10px;flex-wrap:wrap;margin:0 0 14px}
.tz-kpi{background:#fff;border:1px solid #eee;border-radius:14px;padding:10px 16px;min-width:130px}
.tz-kpi b{display:block;font-size:24px;color:var(--mh-ink);line-height:1.1}
.tz-kpi span{font-size:12px;color:var(--mh-muted)}
.tz-kpi.hot{border-color:#ffb3cd;background:#fff5f9}
.tz-card-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap}
.tz-client{font-size:19px;font-weight:800;color:var(--mh-ink);margin:0}
.tz-sub{font-size:13px;color:var(--mh-muted);margin-top:2px}
.tz-pill{display:inline-block;padding:4px 12px;border-radius:999px;font-size:12px;font-weight:700;white-space:nowrap}
.tz-route{display:flex;align-items:center;gap:10px;margin:12px 0 8px;font-size:14px;color:var(--mh-ink)}
.tz-route .pt{background:#f6f3ff;border-radius:10px;padding:6px 10px}
.tz-route .pt small{display:block;color:var(--mh-muted);font-size:11px}
.tz-route .arrow{color:var(--mh-purple);font-size:18px}
.tz-chips{display:flex;gap:6px;flex-wrap:wrap;margin:6px 0 4px}
.tz-chip{background:#f4f4f7;border-radius:8px;padding:4px 9px;font-size:12.5px;color:var(--mh-ink)}
.tz-chip.warn{background:#fff1e0;color:#a35200}
.tz-steps{display:flex;gap:0;margin:12px 0 4px}
.tz-step{flex:1;text-align:center;font-size:11px;color:#aaa;position:relative;padding-top:16px}
.tz-step:before{content:"";position:absolute;top:5px;left:0;right:0;height:3px;background:#eee}
.tz-step:first-child:before{left:50%}.tz-step:last-child:before{right:50%}
.tz-step i{position:absolute;top:0;left:50%;margin-left:-6px;width:13px;height:13px;border-radius:50%;
  background:#ddd;border:2px solid #fff;box-shadow:0 0 0 1px #ddd}
.tz-step.done{color:var(--mh-ink)}.tz-step.done:before{background:var(--mh-purple)}
.tz-step.done i{background:var(--mh-purple);box-shadow:0 0 0 1px var(--mh-purple)}
.tz-step.now{color:var(--mh-pink);font-weight:700}
.tz-step.now i{background:var(--mh-pink);box-shadow:0 0 0 3px #ffd0e0}
.tz-note{background:#f8f7fc;border-left:3px solid var(--mh-purple);padding:7px 10px;border-radius:6px;
  font-size:13px;margin:6px 0;color:var(--mh-ink)}
.tz-price{font-size:22px;font-weight:800;color:var(--mh-ink)}
.tz-empty{text-align:center;color:var(--mh-muted);padding:30px;border:1px dashed #ddd;border-radius:14px}
</style>
"""

PILL = {
    tz.A_COMPLETER: ("✏️ À compléter", "#fff1e0", "#a35200"),
    tz.A_COTER: ("⏳ En attente de prix", "#eaf3ff", "#1d5fb8"),
    tz.COTEE: ("💶 Prix reçu", "#fff0f6", "#c2185b"),
    tz.VALIDEE: ("👍 Prix validé", "#f1ebff", "#6b3fc4"),
    tz.CONFIRMEE: ("✅ Confirmé", "#e8f8ee", "#1e7a44"),
    tz.LV_DEPOSEE: ("📄 Lettre de voiture reçue", "#e8f8ee", "#1e7a44"),
    tz.LIVREE: ("🏁 Livré", "#f0f0f3", "#555"),
    tz.ANNULEE: ("✖️ Annulé", "#f0f0f3", "#888"),
}
STEPS = [("Demande", {tz.A_COTER}), ("Prix", {tz.COTEE}), ("Validé", {tz.VALIDEE}),
         ("Confirmé", {tz.CONFIRMEE}), ("Lettre de voiture", {tz.LV_DEPOSEE}), ("Livré", {tz.LIVREE})]
_ORDER = [tz.A_COMPLETER, tz.A_COTER, tz.COTEE, tz.VALIDEE, tz.CONFIRMEE, tz.LV_DEPOSEE, tz.LIVREE]


def _e(v) -> str:
    return _html.escape(str(v or ""))


def pill(statut: str, overrides: dict | None = None) -> str:
    lab, bg, fg = (overrides or {}).get(statut) or PILL.get(statut, (statut, "#eee", "#333"))
    return f'<span class="tz-pill" style="background:{bg};color:{fg}">{lab}</span>'


def city(addr: str) -> str:
    """« …\\n45770 Saran\\nFrance » → « Saran (45) » ; à défaut la dernière ligne utile."""
    lines = [l.strip() for l in str(addr or "").splitlines() if l.strip()]
    for l in reversed(lines):
        m = _re.search(r"\b(\d{5})\s+([A-Za-zÀ-ÿ' \-]+)", l)
        if m:
            return f"{m.group(2).strip().title()} ({m.group(1)[:2]})"
    return lines[-1] if lines else "?"


def steps_html(statut: str) -> str:
    if statut == tz.ANNULEE:
        return ""
    idx = max(1, _ORDER.index(statut)) if statut in _ORDER else 1   # À COMPLÉTER = étape « Demande »
    out = []
    for i, (lab, _) in enumerate(STEPS, start=1):
        cls = "done" if idx > i else "now" if idx == i else ""
        if statut == tz.LIVREE and i == len(STEPS):
            cls = "done"
        out.append(f'<div class="tz-step {cls}"><i></i>{lab}</div>')
    return f'<div class="tz-steps">{"".join(out)}</div>'


def card_html(d: dict, pills: dict | None = None) -> str:
    chips = []
    if d.get("nb_palettes"):
        chips.append(f"📦 {_e(d['nb_palettes'])} palette{'s' if str(d['nb_palettes']) != '1' else ''}")
    if d.get("poids_kg"):
        chips.append(f"⚖️ {_e(d['poids_kg'])} kg")
    if d.get("dimensions"):
        chips.append(f"📐 {_e(d['dimensions'])}")
    if d.get("rdv") or d.get("contact_rdv"):
        chips.append("📞 RDV à prendre")
    chip_html = "".join(f'<span class="tz-chip">{c}</span>' for c in chips)
    if d.get("matiere_dangereuse"):
        chip_html += '<span class="tz-chip warn">⚠️ Matière dangereuse (DGD)</span>'
    dates_l = f"Dispo {_e(d.get('date_mad') or '?')}"
    dates_r = f"Livraison {_e(d.get('date_livraison') or d.get('date_livraison_demandee') or '?')}"
    if d.get("date_enlevement"):
        dates_l = f"Enlèvement {_e(d['date_enlevement'])}"
    ref = f" · commande {_e(d['ref_commande'])}" if d.get("ref_commande") else ""
    tref = f" · réf. Tissandier {_e(d['ref_tissandier'])}" if d.get("ref_tissandier") else ""
    return f"""
<div class="tz-card-head">
  <div><p class="tz-client">{_e(d['client'])}</p>
       <div class="tz-sub">{_e(d['bl'])}{ref}{tref}</div></div>
  <div>{pill(d['statut'], pills)}</div>
</div>
<div class="tz-route">
  <div class="pt"><small>Départ</small>BX · Neufchâteau (88)<small>{dates_l}</small></div>
  <div class="arrow">➜</div>
  <div class="pt"><small>Arrivée</small>{_e(city(d.get('adresse_livraison')))}<small>{dates_r}</small></div>
</div>
<div class="tz-chips">{chip_html}</div>
{steps_html(d['statut'])}
"""


def kpis_html(items: list[tuple[str, int, bool]]) -> str:
    return '<div class="tz-kpis">' + "".join(
        f'<div class="tz-kpi{" hot" if hot and n else ""}"><b>{n}</b><span>{_e(lab)}</span></div>'
        for lab, n, hot in items) + "</div>"


def details(d: dict) -> None:
    """Adresse complète, RDV, commentaires, prix (dans un repli)."""
    with st.expander("Détails : adresse, RDV, commentaires"):
        a, b = st.columns(2)
        a.markdown("**Adresse de livraison**  \n" + _e(d.get("adresse_livraison")).replace("\n", "  \n"))
        b.markdown("**RDV / contact**  \n" + (_e(d.get("contact_rdv")) or "—"))
        if d.get("commentaire_mh"):
            st.markdown(f'<div class="tz-note">💬 Merci Handy : {_e(d["commentaire_mh"])}</div>',
                        unsafe_allow_html=True)
        if d.get("commentaire_tissandier"):
            st.markdown(f'<div class="tz-note">💬 Tissandier : {_e(d["commentaire_tissandier"])}</div>',
                        unsafe_allow_html=True)
        st.caption((d.get("historique") or "").replace("\n", "  \n"))
