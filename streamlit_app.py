import re
import time
import typing as t
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup
import streamlit as st
import pandas as pd

st.set_page_config(page_title="Kleinanzeigen Dealer Link Collector", page_icon="🔗", layout="wide")

st.title("🔗 Kleinanzeigen Händler-Link-Sammler")
st.write(
    "Gib die URL einer **Händlerseite** (z. B. `https://www.kleinanzeigen.de/pro/ff-wheels-by-felgenforum`) ein. "
    "Die App blättert durch alle Seiten und sammelt **alle individuellen Inserat-Links**."
)

with st.expander("⚙️ Erweitert (optional)"):
    default_headers = {
        "User-Agent": st.text_input("User-Agent", value="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": st.text_input("Accept-Language", value="de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7"),
        "Referer": st.text_input("Referer", value="https://www.kleinanzeigen.de/"),
        "Upgrade-Insecure-Requests": "1",
    }
    cookie_help = "Optional. Füge z. B. `__cf_bm=...; kdfl=...` etc. ein, falls nötig."
    raw_cookie = st.text_input("Cookies (optional)", value="", help=cookie_help, type="password")
    delay_s = st.number_input("Pause zwischen Seitenabrufen (Sek.)", min_value=0.0, max_value=10.0, value=0.8, step=0.1)
    max_pages = st.number_input("Max. Seiten (0 = automatisch bis Ende)", min_value=0, max_value=10000, value=0, step=1)

dealer_url = st.text_input("Händler-URL", placeholder="https://www.kleinanzeigen.de/pro/ff-wheels-by-felgenforum", label_visibility="visible")

def normalize_url(base: str, href: str) -> str:
    if not href:
        return ""
    abs_url = urljoin(base, href)
    # Entferne URL-Parameter, die für den eindeutigen Inserat-Link unnötig sind
    parsed = urlparse(abs_url)
    clean = parsed._replace(query="", fragment="")
    return clean.geturl()

def extract_listing_links(base_url: str, html: str) -> t.Set[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = set()
    # Inserate enthalten id-basierte Pfade wie /s-anzeige/.../<id>
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if re.search(r"/s-anzeige/.*?/\\d+(?:\\?|$|/)", href):
            links.add(normalize_url(base_url, href))
    return links

def find_next_page_url(base_url: str, html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    # 1) <link rel="next" href="...">
    link_next = soup.find("link", rel=lambda v: v and "next" in v.lower())
    if link_next and link_next.get("href"):
        return urljoin(base_url, link_next["href"])

    # 2) <a aria-label="Nächste"> oder Knopf mit 'Nächste'
    #    Manche Seiten nutzen Buttons, aber häufig gibt es auch <a>-Links.
    candidates = []
    for a in soup.find_all(["a", "button"]):
        label = (a.get("aria-label") or a.text or "").strip().lower()
        if "nächste" in label or "weiter" in label or "next" in label:
            href = a.get("href")
            if href:
                candidates.append(urljoin(base_url, href))
    if candidates:
        # Nehme den ersten brauchbaren Kandidaten
        return candidates[0]

    # 3) Heuristik: Paginierungs-Links mit page-Query
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if re.search(r"[?&]page=\\d+", href, re.I):
            # Optional: höchsten page-Wert wählen, der > aktuelle Seite ist – hier vereinfachen wir.
            return urljoin(base_url, href)

    return ""

def scrape_all_listing_urls(start_url: str, headers: dict, cookie_string: str = "", max_pages: int = 0, delay: float = 0.0) -> pd.DataFrame:
    session = requests.Session()
    session.headers.update(headers or {})
    if cookie_string:
        # Simplest: send raw Cookie header
        session.headers.update({"Cookie": cookie_string})

    seen_urls: t.Set[str] = set()
    visited_pages = 0
    current_url = start_url

    while current_url:
        visited_pages += 1
        st.info(f"📄 Lade Seite {visited_pages}: {current_url}")
        try:
            resp = session.get(current_url, timeout=30)
        except Exception as e:
            st.warning(f"Fehler beim Abruf: {e}")
            break

        if resp.status_code != 200:
            st.warning(f"HTTP {resp.status_code} bei {current_url}. Vorgang beendet.")
            break

        found = extract_listing_links(current_url, resp.text)
        new_links = found - seen_urls
        seen_urls.update(found)

        st.write(f"➕ Neue Links auf dieser Seite: **{len(new_links)}**, Gesamt: **{len(seen_urls)}**")

        # Abbruch, wenn max_pages gesetzt ist
        if max_pages and visited_pages >= max_pages:
            st.info("Maximale Seitenzahl erreicht. Stoppe.")
            break

        next_url = find_next_page_url(current_url, resp.text)
        if not next_url or next_url == current_url:
            st.success("Keine weitere Seite gefunden. Fertig!")
            break

        current_url = next_url
        if delay > 0:
            time.sleep(delay)

    df = pd.DataFrame(sorted(seen_urls), columns=["url"])
    return df

col1, col2 = st.columns([3,1])
with col1:
    run = st.button("🔍 Alle Inserat-Links sammeln", type="primary")
with col2:
    clear = st.button("🧹 Zurücksetzen")

if clear:
    st.experimental_rerun()

if run:
    if not dealer_url.strip():
        st.error("Bitte eine gültige Händler-URL eingeben.")
        st.stop()

    st.caption("Bitte beachte die **Nutzungsbedingungen** und **robots.txt** von Kleinanzeigen. Verwende angemessene Abrufraten.")
    df = scrape_all_listing_urls(
        start_url=dealer_url.strip(),
        headers=default_headers,
        cookie_string=raw_cookie.strip(),
        max_pages=int(max_pages or 0),
        delay=float(delay_s or 0.0),
    )

    st.divider()
    st.subheader("Ergebnis")
    st.write(f"Gefundene Inserat-Links: **{len(df)}**")
    st.dataframe(df, use_container_width=True, hide_index=True)

    if not df.empty:
        # Downloads
        csv_bytes = df.to_csv(index=False).encode("utf-8")
        txt_bytes = ("\n".join(df["url"].tolist())).encode("utf-8")
        json_bytes = df.to_json(orient="records", force_ascii=False, indent=2).encode("utf-8")

        # Excel
        import io
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="links")
        xlsx_bytes = buffer.getvalue()

        st.download_button("⬇️ CSV herunterladen", data=csv_bytes, file_name="inserat_links.csv", mime="text/csv")
        st.download_button("⬇️ TXT herunterladen", data=txt_bytes, file_name="inserat_links.txt", mime="text/plain")
        st.download_button("⬇️ JSON herunterladen", data=json_bytes, file_name="inserat_links.json", mime="application/json")
        st.download_button("⬇️ Excel herunterladen", data=xlsx_bytes, file_name="inserat_links.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

st.divider()
st.caption("Hinweis: Diese App sammelt ausschließlich die **URL-Links** der Inserate. Sie öffnet keine einzelnen Inserate und speichert keine Inhalte daraus.")
