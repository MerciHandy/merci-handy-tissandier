"""Portail Tissandier (services/tissandier.py) — sans réseau.
Lignes = vraies saisies du fichier de suivi BX (octobre 2026)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pytest  # noqa: E402

from services import tissandier as tz  # noqa: E402


def row(**kw):
    r = [""] * 28
    for k, v in kw.items():
        r[tz.C[k]] = v
    return r


HDR = [[""] * 28] * 3
ROWS = HDR + [
    row(A="MARIONNAUD", D="04/11/2026", E="695543", F="BL-10316", G="DERET 45770 Saran",
        K="TISSANDIER", L="OUI", M="Tel : 02 46 26 31 78", I="", V="1 PALETTE 1200°800°1000 200KG"),
    row(A="SEPHORA S.A.", F="BL-10298", K="TISSANDIER", J="28/10/2026",       # déjà parti
        V="1 PALETTE 1200°800°1000 270KG"),
    row(A="NOCIBE 0090", F="BL-10319", K="BX"),                               # pas Tissandier
    row(A="SEPHORA SARAN", F="BL-10051", K="TISSANDIER",
        V="80*120*120 DE 260 KG ///   80*120*100 DE 240 KG"),
]


def test_parse_colisage():
    assert tz.parse_colisage("1 PALETTE 1200°800°1000 200KG") == \
        {"nb_palettes": "1", "dimensions": "1200×800×1000", "poids_kg": "200"}
    p = tz.parse_colisage("80*120*120 DE 260 KG ///   80*120*100 DE 240 KG")
    assert p["nb_palettes"] == "2" and p["poids_kg"] == "500"
    assert tz.parse_colisage("3 palettes")["nb_palettes"] == "3"
    assert tz.parse_colisage("1 COLIS 600°400°400 20KG")["nb_palettes"] == ""
    assert tz.parse_colisage("") == {"nb_palettes": "", "dimensions": "", "poids_kg": ""}


def test_bl_key():
    assert tz.bl_key("BL-10288") == "10288" == tz.bl_key("10288")
    assert tz.bl_key("BL-L1730") == "L1730"


def test_brouillons_depuis_le_suivi():
    new = tz.drafts_from_suivi(ROWS, [])
    assert [d["bl"] for d in new] == ["BL-10316", "BL-10051"]
    d = new[0]
    assert d["statut"] == tz.A_COMPLETER and d["client"] == "MARIONNAUD"
    assert d["poids_kg"] == "200" and d["nb_palettes"] == "1" and d["rdv"] == "OUI"
    # idempotent : une demande existe déjà pour ces BL
    assert tz.drafts_from_suivi(ROWS, new) == []
    # une demande ANNULÉE ne bloque pas une nouvelle création
    assert len(tz.drafts_from_suivi(ROWS, [dict(new[0], statut=tz.ANNULEE)])) == 2


def _draft():
    return tz.drafts_from_suivi(ROWS, [])[0]


def test_cycle_complet():
    d = _draft()
    with pytest.raises(ValueError, match="date de mise à dispo"):
        tz.apply_action(d, "mh", "envoyer")
    d = tz.apply_action(d, "mh", "envoyer", {"date_mad": "02/11/2026"})
    assert d["statut"] == tz.A_COTER
    with pytest.raises(ValueError):
        tz.apply_action(d, "mh", "valider")                 # rien à valider encore
    with pytest.raises(ValueError):
        tz.apply_action(d, "mh", "coter", {"prix_ht": "200"})   # MH ne cote pas
    with pytest.raises(ValueError, match="prix"):
        tz.apply_action(d, "tissandier", "coter", {"prix_ht": ""})
    d = tz.apply_action(d, "tissandier", "coter", {"prix_ht": "206,40"})
    assert d["statut"] == tz.COTEE
    r = tz.apply_action(d, "mh", "refuser")
    assert r["statut"] == tz.A_COTER
    d = tz.apply_action(d, "mh", "valider")
    with pytest.raises(ValueError, match="date"):
        tz.apply_action(d, "tissandier", "confirmer", {"date_enlevement": "02/11/2026"})
    d = tz.apply_action(d, "tissandier", "confirmer",
                        {"date_enlevement": "02/11/2026", "date_livraison": "04/11/2026",
                         "ref_tissandier": "CO2610-3742"})
    assert d["statut"] == tz.CONFIRMEE
    with pytest.raises(ValueError, match="lettre de voiture"):
        tz.apply_action(d, "tissandier", "deposer_lv")
    d = tz.apply_action(d, "tissandier", "deposer_lv", {"lettre_voiture": "drive:abc|LV.pdf"})
    assert d["statut"] == tz.LV_DEPOSEE
    d = tz.apply_action(d, "mh", "livree")
    assert d["statut"] == tz.LIVREE
    assert d["historique"].count("\n") == 6          # création + 6 actions
    with pytest.raises(ValueError):
        tz.apply_action(d, "mh", "annuler")          # une livraison close ne s'annule pas


def test_tissandier_ne_modifie_pas_les_champs_proteges():
    d = tz.apply_action(_draft(), "mh", "envoyer", {"date_mad": "02/11/2026"})
    d2 = tz.apply_action(d, "tissandier", "coter", {"prix_ht": "200", "statut": tz.LIVREE, "id": "x"})
    assert d2["statut"] == tz.COTEE and d2["id"] == d["id"]


def test_reflet_dans_le_suivi():
    d = tz.apply_action(_draft(), "mh", "envoyer", {"date_mad": "02/11/2026"})
    upd = tz.suivi_updates(d, ROWS)
    assert {"range": "I4", "values": [["02/11/2026"]]} in upd
    assert any(u["range"] == "X4" and "en attente de prix" in u["values"][0][0] for u in upd)
    d = tz.apply_action(tz.apply_action(d, "tissandier", "coter", {"prix_ht": "206.4"}), "mh", "valider")
    upd = tz.suivi_updates(d, ROWS)
    assert {"range": "AB4", "values": [["206,40 €"]]} in upd
    # la trace remplace la précédente, sans toucher au reste de X (lien DGD…)
    rows = [list(r) for r in ROWS]
    rows[3][tz.C["X"]] = "DGD : https://drive/x\n🚚 Tissandier : demande envoyée, en attente de prix"
    x = next(u for u in tz.suivi_updates(d, rows) if u["range"] == "X4")["values"][0][0]
    assert x.startswith("DGD : https://drive/x") and "prix validé" in x and "en attente de prix" not in x
    assert tz.suivi_updates(dict(d, bl="BL-99999"), ROWS) == []
