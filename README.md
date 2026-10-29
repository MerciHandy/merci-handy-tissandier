# Portail Merci Handy × Tissandier

Portail où Tissandier cote, confirme et dépose les lettres de voiture des demandes de transport Merci Handy.

- Accès protégé par un code (secret `[tissandier].access_code`), aucune donnée dans ce dépôt.
- Les demandes vivent dans un onglet masqué du fichier de suivi BX (Google Sheets), les fichiers dans un dossier Drive partagé, lus par un compte de service (secrets de l'app).
- **Copie** du portail du dépôt privé `merci-handy-ocr` (`portail/app.py`, `services/tissandier*.py`) : c'est là qu'on modifie, puis on recopie ici.

Secrets Streamlit Cloud : `[gcp_service_account]`, `[slack] webhook_url`, `[tissandier] access_code / drive_folder_id / portal_url / sheet_id`.
