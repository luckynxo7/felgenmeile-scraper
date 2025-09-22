import re
import time
import json
import typing as t
from urllib.parse import urljoin, urlparse, parse_qsl, urlencode, urlunparse
import requests
from bs4 import BeautifulSoup
import streamlit as st
import pandas as pd

st.set_page_config(page_title="Kleinanzeigen Dealer Link Collector", page_icon="🔗", layout="wide")
st.title("🔗 Kleinanzeigen Händler-Link-Sammler (v2)")
st.write("Robuster Sammler für **alle Inserat-Links** einer Händlerseite – inkl. Fallbacks für JSON/SSR und erzwungene `?page=`-Paginierung.")

with st.expander("⚙️ Erweitert (optional)"):
    default_headers = {
        "User-Agent": st.text_input("User-Agent", value="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
        "Accept": st.text_input("Accept", value="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
        "Accept-Language": st.text_input("Accept-Language", value="de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7"),
        "Referer": st.text_input("Referer", value="https://www.kleinanzeigen.de/"),
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    raw_cookie = st.text_input("Cookies (optional)", value="", help="Kompletter Cookie-String, falls benötigt.", type="password")
    delay_s = st.number_input("Pause zwischen Seitenabrufen (Sek.)", min_value=0.0, max_value=10.0, value=0.8, step=0.1)
    max_pages = st.number_input("Max. Seiten (0 = automatisch bis Ende)", min_value=0, max_value=10000, value=0, step=1)
    force_query_pagination = st.checkbox("Erzwinge `?page=`-Paginierung (ignoriert 'Weiter'-Buttons)", value=True)
    save_html_debug = st.checkbox("HTML-Debug (Roh-HTML als Download speichern)", value=False)

dealer_url = st.text_input("Händler-URL", placeholder="https://www.kleinanzeigen.de/pro/ff-wheels-by-felgenforum", label_visibility="visible")

def normalize_url(base: str, href: str) -> str:
    if not href:
        return ""
    abs_url = urljoin(base, href)
    parsed = urlparse(abs_url)
    clean = parsed._replace(query="", fragment="")
    return clean.geturl()

AD_HREF_RE = re.compile(r"/s-anzeige/[^\"']*?/(\d+)(?:[/?#]|$)", re.I)

def extract_from_json_blobs(base_url: str, html: str) -> t.Set[str]:
    links = set()
    # Suche nach JSON-Blöcken, z. B. __NEXT_DATA__, window.__INITIAL_STATE__, application/json im Script
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script"):
        script_type = (script.get("type") or "").lower()
        text = script.string or script.text or ""
        if not text:
            continue
        try:
            if script_type in ("application/json", "application/ld+json"):
                data = json.loads(text)
                text_to_scan = json.dumps(data, ensure_ascii=False)
                for m in AD_HREF_RE.finditer(text_to_scan):
                    href = f"/s-anzeige/x/{m.group(1)}"
                    links.add(normalize_url(base_url, href))
            else:
                # Heuristisch JSON herausziehen
                if ("__NEXT_DATA__" in text) or ("__INITIAL_STATE__" in text) or ("__PRELOADED_STATE__" in text):
                    # Versuche JSON-Objekt aus dem Script zu extrahieren
                    # sehr defensiv: Alle 10+ Zeichen langen {...} oder [...] Blöcke testen
                    for candidate in re.findall(r"(\{.*\}|\[.*\])", text, flags=re.S):
                        if len(candidate) < 10:
                            continue
                        try:
                            data = json.loads(candidate)
                            text_to_scan = json.dumps(data, ensure_ascii=False)
                            for m in AD_HREF_RE.finditer(text_to_scan):
                                href = f"/s-anzeige/x/{m.group(1)}"
                                links.add(normalize_url(base_url, href))
                        except Exception:
                            continue
        except Exception:
            continue
    return links

def extract_listing_links(base_url: str, html: str) -> t.Set[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = set()
    # 1) Direkte <a href="/s-anzeige/.../id">
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if AD_HREF_RE.search(href):
            links.add(normalize_url(base_url, href))

    # 2) Fallback: IDs im HTML-Text (auch wenn kein <a> vorhanden ist)
    for m in AD_HREF_RE.finditer(html):
        href = f"/s-anzeige/x/{m.group(1)}"
        links.add(normalize_url(base_url, href))

    # 3) JSON-Blobs (Next.js / Redux etc.)
    json_links = extract_from_json_blobs(base_url, html)
    links.update(json_links)

    return links

def update_query(url: str, **kv) -> str:
    p = urlparse(url)
    qs = dict(parse_qsl(p.query, keep_blank_values=True))
    for k, v in kv.items():
        if v is None:
            qs.pop(k, None)
        else:
            qs[k] = str(v)
    new_q = urlencode(qs, doseq=True)
    return urlunparse((p.scheme, p.netloc, p.path, p.params, new_q, p.fragment))

def find_next_by_linkrel_or_button(base_url: str, html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    link_next = soup.find("link", rel=lambda v: v and "next" in v.lower())
    if link_next and link_next.get("href"):
        return urljoin(base_url, link_next["href"])
    for a in soup.find_all(["a", "button"]):
        label = (a.get("aria-label") or a.text or "").strip().lower()
        if "nächste" in label or "weiter" in label or "next" in label:
            href = a.get("href")
            if href:
                return urljoin(base_url, href)
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if re.search(r"[?&]page=\d+", href, re.I):
            return urljoin(base_url, href)
    return ""

def scrape_all_listing_urls(start_url: str, headers: dict, cookie_string: str = "", max_pages: int = 0, delay: float = 0.0, force_query_pagination: bool = False, save_html_debug: bool = False) -> t.Tuple[pd.DataFrame, t.List[t.Tuple[int, bytes]]]:
    session = requests.Session()
    session.headers.update(headers or {})
    if cookie_string:
        session.headers.update({"Cookie": cookie_string})

    seen_urls: t.Set[str] = set()
    visited_pages = 0
    current_url = start_url
    debug_htmls: t.List[t.Tuple[int, bytes]] = []

    # Falls wir die page-Paginierung erzwingen, initialisieren wir auf page=1
    if force_query_pagination:
        current_url = update_query(start_url, page=1)

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

        html = resp.text or ""
        if save_html_debug:
            try:
                debug_htmls.append((visited_pages, html.encode("utf-8", errors="ignore")))
            except Exception:
                pass

        found = extract_listing_links(current_url, html)
        new_links = found - seen_urls
        seen_urls.update(found)

        st.write(f"➕ Neue Links auf dieser Seite: **{len(new_links)}**, Gesamt: **{len(seen_urls)}**")

        if max_pages and visited_pages >= max_pages:
            st.info("Maximale Seitenzahl erreicht. Stoppe.")
            break

        if force_query_pagination:
            # erhöhe page um 1 bis keine neuen Links mehr kommen
            parsed = urlparse(current_url)
            qs = dict(parse_qsl(parsed.query, keep_blank_values=True))
            page = int(qs.get("page", "1"))
            next_url = update_query(current_url, page=page + 1)
        else:
            next_url = find_next_by_linkrel_or_button(current_url, html)

        if not next_url or next_url == current_url:
            st.success("Keine weitere Seite gefunden. Fertig!")
            break

        # Stop-Heuristik: Wenn innerhalb von zwei Seiten keine neuen Links
        if force_query_pagination and len(new_links) == 0:
            st.info("Keine neuen Links auf dieser Seite. Vermutlich Ende erreicht.")
            break

        current_url = next_url
        if delay > 0:
            time.sleep(delay)

    df = pd.DataFrame(sorted(seen_urls), columns=["url"])
    return df, debug_htmls

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
    df, html_debugs = scrape_all_listing_urls(
        start_url=dealer_url.strip(),
        headers=default_headers,
        cookie_string=raw_cookie.strip(),
        max_pages=int(max_pages or 0),
        delay=float(delay_s or 0.0),
        force_query_pagination=force_query_pagination,
        save_html_debug=save_html_debug,
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

        import io
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="links")
        xlsx_bytes = buffer.getvalue()

        st.download_button("⬇️ CSV herunterladen", data=csv_bytes, file_name="inserat_links.csv", mime="text/csv")
        st.download_button("⬇️ TXT herunterladen", data=txt_bytes, file_name="inserat_links.txt", mime="text/plain")
        st.download_button("⬇️ JSON herunterladen", data=json_bytes, file_name="inserat_links.json", mime="application/json")
        st.download_button("⬇️ Excel herunterladen", data=xlsx_bytes, file_name="inserat_links.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    if html_debugs:
        # Packe alle HTMLs in ein ZIP zum Download
        import zipfile, io
        zbuf = io.BytesIO()
        with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as z:
            for page_idx, content in html_debugs:
                z.writestr(f"page_{page_idx:03d}.html", content)
        st.download_button("⬇️ Debug-HTML (ZIP)", data=zbuf.getvalue(), file_name="html_debug_pages.zip", mime="application/zip")

st.divider()
st.caption("Hinweis: Diese App sammelt ausschließlich die **URL-Links** der Inserate. Sie öffnet keine einzelnen Inserate und speichert keine Inhalte daraus.")
