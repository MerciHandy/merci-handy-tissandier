"""Portail Tissandier — demandes de transport partagées entre Merci Handy et
Tissandier (TLA), à la place des allers-retours d'emails.

Cycle d'une demande (une par BL en mode TISSANDIER) :

  À COMPLÉTER  créée toute seule depuis le fichier de suivi BX (colonne K =
               TISSANDIER), pré-remplie : client, adresse, RDV, date de
               livraison, date de mise à dispo, palettes / poids (colonne V).
  À COTER      Merci Handy a complété (packing list…) et l'a envoyée.
  COTÉE        Tissandier a donné son prix.
  VALIDÉE      Merci Handy a accepté le prix (→ réservation).
  CONFIRMÉE    Tissandier a confirmé enlèvement / livraison (+ sa référence CO…).
  LV DÉPOSÉE   Tissandier a déposé la lettre de voiture.
  LIVRÉE       clôturée.
  ANNULÉE

Stockage : onglet masqué « _tissandier » du fichier de suivi BX (le compte de
service y est déjà éditeur). Fichiers (packing list, lettre de voiture) : dossier
Google Drive [tissandier].drive_folder_id, lus/écrits par le compte de service —
Tissandier les télécharge depuis le portail, sans partage Drive.

Ce module ne dépend pas de Streamlit : la page du hub, le portail et le script
de synchro lui passent un client gspread.
"""
from __future__ import annotations

import datetime as dt
import re
import uuid
from typing import Any, Iterable, Optional

SUIVI_SHEET_ID = ""   # dépôt public : vient du secret [tissandier].sheet_id
TAB = "_tissandier"

A_COMPLETER, A_COTER, COTEE, VALIDEE = "À COMPLÉTER", "À COTER", "COTÉE", "VALIDÉE"
CONFIRMEE, LV_DEPOSEE, LIVREE, ANNULEE = "CONFIRMÉE", "LV DÉPOSÉE", "LIVRÉE", "ANNULÉE"
STATUTS = [A_COMPLETER, A_COTER, COTEE, VALIDEE, CONFIRMEE, LV_DEPOSEE, LIVREE, ANNULEE]
# Ce que Tissandier voit : tout sauf les brouillons internes
STATUTS_TISSANDIER = [A_COTER, COTEE, VALIDEE, CONFIRMEE, LV_DEPOSEE, LIVREE]

FIELDS = [
    "id", "statut", "bl", "client", "ref_commande", "adresse_livraison",
    "rdv", "contact_rdv", "date_livraison_demandee", "date_mad",
    "nb_palettes", "dimensions", "poids_kg", "matiere_dangereuse",
    "packing_list", "commentaire_mh",
    "prix_ht", "commentaire_tissandier",
    "date_enlevement", "date_livraison", "ref_tissandier", "lettre_voiture",
    "historique", "created_at", "updated_at", "updated_by",
]

# Colonnes du fichier de suivi BX (0-based)
C = {k: i for i, k in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ")}
C.update({"AA": 26, "AB": 27})
HEADER_ROWS = 3


# ---------------------------------------------------------------------------
# Utilitaires purs
# ---------------------------------------------------------------------------
def now_str() -> str:
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("Europe/Paris")).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return dt.datetime.now().strftime("%d/%m/%Y %H:%M")


def bl_key(v: Any) -> str:
    """« BL-10288 », « 10288 », « BL-L1730 » → « 10288 » / « L1730 »."""
    m = re.search(r"\b(L?\d{4,6})\b", str(v or "").upper().replace("BL-", " "))
    return m.group(1) if m else ""


def parse_colisage(txt: str) -> dict:
    """Colonne V du suivi (« 1 PALETTE 1200°800°1000 200KG », « 80*120*120 DE
    250 KG // 80*120*100 DE 260 KG », « 3 palettes ») → palettes / dims / kg."""
    t = str(txt or "").upper().replace(",", ".")
    out = {"nb_palettes": "", "dimensions": "", "poids_kg": ""}
    if not t.strip():
        return out
    n = sum(int(x) for x in re.findall(r"(\d+)\s*(?:PALETTES?|PAL\b|EURO)", t))
    dims = re.findall(r"(\d{2,4})\s*[°*X/]\s*(\d{2,4})\s*[°*X/]\s*(\d{2,4})", t)
    if not n and dims and "COLIS" not in t:
        n = len(dims)
    kgs = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*KG", t)]
    out["nb_palettes"] = str(n) if n else ""
    out["dimensions"] = " / ".join("×".join(d) for d in dims)
    out["poids_kg"] = f"{sum(kgs):g}" if kgs else ""
    return out


def is_tissandier(k_value: Any) -> bool:
    return "TISSANDIER" in str(k_value or "").upper()


def drafts_from_suivi(rows: list[list[str]], existing: Iterable[dict]) -> list[dict]:
    """Lignes du suivi en TISSANDIER, pas encore parties (J vide), sans demande
    existante pour ce BL → nouvelles demandes « À COMPLÉTER » pré-remplies."""
    known = {bl_key(d.get("bl")) for d in existing if d.get("statut") != ANNULEE}
    out = []
    for r in rows[HEADER_ROWS:]:
        r = list(r) + [""] * 30
        key = bl_key(r[C["F"]])
        if not key or key in known or not is_tissandier(r[C["K"]]):
            continue
        if str(r[C["J"]]).strip():          # déjà parti de chez BX
            continue
        col = parse_colisage(r[C["V"]])
        d = {f: "" for f in FIELDS}
        d.update({
            "id": uuid.uuid4().hex[:8],
            "statut": A_COMPLETER,
            "bl": str(r[C["F"]]).strip(),
            "client": str(r[C["A"]]).strip(),
            "ref_commande": str(r[C["E"]]).strip(),
            "adresse_livraison": str(r[C["G"]]).strip(),
            "rdv": str(r[C["L"]]).strip(),
            "contact_rdv": str(r[C["M"]]).strip(),
            "date_livraison_demandee": str(r[C["D"]]).strip(),
            "date_mad": str(r[C["I"]]).strip(),
            "matiere_dangereuse": "",
            "created_at": now_str(),
            "updated_at": now_str(),
            "updated_by": "synchro fichier BX",
            "historique": f"{now_str()} · créée depuis le fichier de suivi BX",
            **col,
        })
        known.add(key)
        out.append(d)
    return out


# Champs obligatoires avant l'envoi à Tissandier
REQUIS_ENVOI = {"date_mad": "date de mise à dispo", "nb_palettes": "nombre de palettes",
                "dimensions": "dimensions", "poids_kg": "poids", "adresse_livraison": "adresse"}

# (rôle, action) → (statuts de départ autorisés, statut d'arrivée)
TRANSITIONS = {
    ("mh", "envoyer"): ({A_COMPLETER}, A_COTER),
    ("tissandier", "coter"): ({A_COTER, COTEE}, COTEE),
    ("mh", "valider"): ({COTEE}, VALIDEE),
    ("mh", "refuser"): ({COTEE}, A_COTER),
    ("tissandier", "confirmer"): ({VALIDEE, CONFIRMEE}, CONFIRMEE),
    ("tissandier", "deposer_lv"): ({VALIDEE, CONFIRMEE, LV_DEPOSEE}, LV_DEPOSEE),
    ("mh", "livree"): ({CONFIRMEE, LV_DEPOSEE}, LIVREE),
    ("mh", "annuler"): (set(STATUTS) - {LIVREE, ANNULEE}, ANNULEE),
}

LIBELLES = {"envoyer": "envoyée à Tissandier", "coter": "cotée", "valider": "prix validé",
            "refuser": "prix refusé", "confirmer": "transport confirmé",
            "deposer_lv": "lettre de voiture déposée", "livree": "livrée", "annuler": "annulée"}


def apply_action(d: dict, role: str, action: str, values: Optional[dict] = None,
                 who: str = "") -> dict:
    """Nouvelle version de la demande après une action. Lève ValueError si
    l'action n'est pas permise (mauvais rôle, mauvais statut, champ manquant)."""
    if (role, action) not in TRANSITIONS:
        raise ValueError(f"Action « {action} » non autorisée pour {role}.")
    allowed, target = TRANSITIONS[(role, action)]
    if d.get("statut") not in allowed:
        raise ValueError(f"Impossible depuis le statut « {d.get('statut')} ».")
    new = dict(d)
    for k, v in (values or {}).items():
        if k in FIELDS and k not in ("id", "statut", "historique", "created_at"):
            new[k] = "" if v is None else str(v).strip()
    missing = []
    if action == "envoyer":
        missing = [lab for f, lab in REQUIS_ENVOI.items() if not new.get(f)]
    elif action == "coter" and not _num(new.get("prix_ht")):
        missing = ["prix HT"]
    elif action == "confirmer" and not (new.get("date_enlevement") and new.get("date_livraison")):
        missing = ["date d'enlèvement et date de livraison"]
    elif action == "deposer_lv" and not new.get("lettre_voiture"):
        missing = ["lettre de voiture"]
    if missing:
        raise ValueError("Il manque : " + ", ".join(missing) + ".")
    new["statut"] = target
    new["updated_at"] = now_str()
    new["updated_by"] = who or role
    detail = ""
    if action == "coter":
        detail = f" : {new['prix_ht']} € HT"
    elif action == "confirmer":
        detail = f" : enlèvement {new['date_enlevement']}, livraison {new['date_livraison']}"
    line = f"{new['updated_at']} · {who or role} · {LIBELLES[action]}{detail}"
    new["historique"] = (str(d.get("historique") or "") + "\n" + line).strip()
    return new


def _num(v: Any) -> Optional[float]:
    m = re.search(r"\d+(?:[.,]\d+)?", str(v or ""))
    return float(m.group().replace(",", ".")) if m else None


def suivi_updates(d: dict, rows: list[list[str]]) -> list[dict]:
    """Écritures à faire dans le fichier de suivi BX pour refléter la demande :
    I date de mise à dispo, AB prix transport, X trace « Booking Tissandier »."""
    key = bl_key(d.get("bl"))
    for i in range(HEADER_ROWS, len(rows)):
        r = list(rows[i]) + [""] * 30
        if bl_key(r[C["F"]]) != key:
            continue
        upd = []
        if d.get("date_mad") and not str(r[C["I"]]).strip():
            upd.append({"range": f"I{i + 1}", "values": [[d["date_mad"]]]})
        if d.get("statut") in (VALIDEE, CONFIRMEE, LV_DEPOSEE, LIVREE) and _num(d.get("prix_ht")):
            prix = f"{_num(d['prix_ht']):.2f}".replace(".", ",") + " €"
            if str(r[C["AB"]]).strip() != prix:
                upd.append({"range": f"AB{i + 1}", "values": [[prix]]})
        trace = booking_trace(d)
        if trace and trace not in str(r[C["X"]]):
            cur = str(r[C["X"]]).strip()
            cur = re.sub(r"🚚 Tissandier :[^\n]*", "", cur).strip()
            upd.append({"range": f"X{i + 1}", "values": [[(cur + "\n" + trace).strip()]]})
        return upd
    return []


def booking_trace(d: dict) -> str:
    st = d.get("statut")
    if st == A_COTER:
        return "🚚 Tissandier : demande envoyée, en attente de prix"
    if st == COTEE:
        return f"🚚 Tissandier : coté {d.get('prix_ht')} € HT, à valider"
    if st == VALIDEE:
        return "🚚 Tissandier : prix validé, en attente de confirmation"
    if st in (CONFIRMEE, LV_DEPOSEE, LIVREE):
        ref = f" {d['ref_tissandier']}" if d.get("ref_tissandier") else ""
        lv = " · LV ✅" if d.get("lettre_voiture") else ""
        return f"🚚 Tissandier :{ref} enl. {d.get('date_enlevement')} → liv. {d.get('date_livraison')}{lv}"
    return ""


# ---------------------------------------------------------------------------
# Stockage (gspread)
# ---------------------------------------------------------------------------
def _ws(gc, create: bool = True):
    sh = gc.open_by_key(SUIVI_SHEET_ID)
    try:
        return sh.worksheet(TAB)
    except Exception:
        if not create:
            return None
        ws = sh.add_worksheet(title=TAB, rows=500, cols=len(FIELDS))
        ws.update(values=[FIELDS], range_name="A1")
        try:
            ws.hide()
        except Exception:
            pass
        return ws


def load(gc) -> list[dict]:
    ws = _ws(gc, create=False)
    if ws is None:
        return []
    values = ws.get_all_values()
    if not values:
        return []
    hdr = values[0]
    return [{f: (dict(zip(hdr, r)).get(f) or "") for f in FIELDS}
            for r in values[1:] if any(str(c).strip() for c in r)]


def save(gc, d: dict) -> None:
    """Crée ou remplace la demande (clé = id)."""
    ws = _ws(gc)
    ids = ws.col_values(1)
    row = [str(d.get(f) or "") for f in FIELDS]
    if d["id"] in ids:
        ws.update(values=[row], range_name=f"A{ids.index(d['id']) + 1}")
    else:
        ws.append_row(row, value_input_option="RAW")


def add_drafts(gc, suivi_rows: list[list[str]]) -> list[dict]:
    new = drafts_from_suivi(suivi_rows, load(gc))
    if new:
        _ws(gc).append_rows([[str(d.get(f) or "") for f in FIELDS] for d in new],
                            value_input_option="RAW")
    return new


def suivi_month_tabs(sh, n: int = 2) -> list:
    mois = ["JANVIER", "FEVRIER", "MARS", "AVRIL", "MAI", "JUIN", "JUILLET",
            "AOUT", "SEPTEMBRE", "OCTOBRE", "NOVEMBRE", "DECEMBRE"]
    tabs = []
    for ws in sh.worksheets():
        m = re.fullmatch(r"\s*([A-ZÉÛ]+)\s+(\d{4})\s*", ws.title.upper())
        if m and m.group(1).replace("É", "E").replace("Û", "U") in mois:
            tabs.append((int(m.group(2)), mois.index(m.group(1).replace("É", "E").replace("Û", "U")), ws))
    return [w for *_k, w in sorted(tabs, key=lambda t: (t[0], t[1]), reverse=True)[:n]]


def push_to_suivi(gc, d: dict) -> int:
    """Reflète la demande dans le fichier de suivi (onglet du mois ou précédent)."""
    sh = gc.open_by_key(SUIVI_SHEET_ID)
    for ws in suivi_month_tabs(sh, 2):
        rows = ws.get_all_values()
        upd = suivi_updates(d, rows)
        if upd:
            ws.batch_update(upd, value_input_option="USER_ENTERED")
            return len(upd)
        if any(bl_key(r[C["F"]] if len(r) > C["F"] else "") == bl_key(d.get("bl"))
               for r in rows[HEADER_ROWS:]):
            return 0
    return 0


# ---------------------------------------------------------------------------
# Fichiers (Drive, via le compte de service)
# ---------------------------------------------------------------------------
def drive_upload(creds, folder_id: str, filename: str, data: bytes, mimetype: str) -> str:
    """Dépose le fichier, renvoie « drive:<id>|<nom> » (stocké dans la demande)."""
    import io
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseUpload
    svc = build("drive", "v3", credentials=creds, cache_discovery=False)
    f = svc.files().create(body={"name": filename, "parents": [folder_id]},
                           media_body=MediaIoBaseUpload(io.BytesIO(data), mimetype=mimetype),
                           fields="id", supportsAllDrives=True).execute()
    return f"drive:{f['id']}|{filename}"


def drive_download(creds, ref: str) -> tuple[str, bytes]:
    from googleapiclient.discovery import build
    fid, _, name = ref.removeprefix("drive:").partition("|")
    svc = build("drive", "v3", credentials=creds, cache_discovery=False)
    data = svc.files().get_media(fileId=fid, supportsAllDrives=True).execute()
    return name or fid, data


def drive_link(ref: str) -> str:
    fid = ref.removeprefix("drive:").partition("|")[0]
    return f"https://drive.google.com/file/d/{fid}/view" if fid else ""


def file_refs(value: str) -> list[str]:
    return [x for x in str(value or "").split("\n") if x.startswith("drive:")]
