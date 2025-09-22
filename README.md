# Kleinanzeigen Händler-Link-Sammler (Streamlit)

Diese App sammelt **alle individuellen Inserat-Links** von einer Kleinanzeigen-Händlerseite (z. B. `https://www.kleinanzeigen.de/pro/ff-wheels-by-felgenforum`) über alle Seiten hinweg.

## Features
- Gibt nur die **URLs** der Inserate zurück (keine Detaildaten)
- Paginierung: folgt automatisch der nächsten Seite (per `<link rel="next">`, `aria-label="Nächste"`, `?page=`-Heuristik)
- Konfigurierbare Header, optionale Cookies
- Deduplizierung
- Downloads als **CSV**, **TXT**, **JSON** oder **Excel**

## Nutzung lokal
```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Deployment auf Streamlit Cloud
1. Repositorium mit diesen Dateien auf GitHub pushen.
2. In Streamlit Cloud das Repo und `streamlit_app.py` als Entry auswählen.
3. (Optional) Umgebungsvariablen setzen:
   - `KLEINANZEIGEN_COOKIE` (wenn notwendig)
4. App starten.

## Hinweise & Fair Use
- Bitte beachte **Nutzungsbedingungen** und **robots.txt** von Kleinanzeigen.
- Setze eine **angemessene Verzögerung** zwischen Seitenabrufen (Einstellung in der App).
- Diese App öffnet **keine** einzelnen Inserate, sie extrahiert nur die Links, die auf der Händlerliste sichtbar sind.
