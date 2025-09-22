import re, time, json, typing as t
from urllib.parse import urljoin, urlparse, parse_qsl, urlencode, urlunparse
import requests
from bs4 import BeautifulSoup
import streamlit as st
import pandas as pd

st.set_page_config(page_title="Händler-Link-Sammler (v3)", page_icon="🔗", layout="wide")
st.title("🔗 Kleinanzeigen Händler-Link-Sammler (v3)")
st.write("Mit **Diagnose-Check** für Cookies/Consent und Header.")

with st.expander("⚙️ Erweitert (optional)"):
    default_headers = {
        "User-Agent": st.text_input("User-Agent", value="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
        "Accept": st.text_input("Accept", value="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
        "Accept-Language": st.text_input("Accept-Language", value="de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7"),
        "Referer": st.text_input("Referer", value="https://www.kleinanzeigen.de/"),
        "Upgrade-Insecure-Requests": "1",
        "DNT": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "sec-ch-ua": st.text_input("sec-ch-ua", value='"Chromium";v="120", "Not.A/Brand";v="24", "Google Chrome";v="120"'),
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": st.text_input("sec-ch-ua-platform", value='"Windows"'),
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    raw_cookie = st.text_input("Cookies (optional)", value="", help="Kompletter Cookie-String (aus DevTools → Network → document → Request Headers → cookie).", type="password")
    delay_s = st.number_input("Pause zwischen Seitenabrufen (Sek.)", min_value=0.0, max_value=10.0, value=0.8, step=0.1)
    max_pages = st.number_input("Max. Seiten (0 = automatisch bis Ende)", min_value=0, max_value=10000, value=0, step=1)
    force_query_pagination = st.checkbox("Erzwinge `?page=`-Paginierung", value=True)
    save_html_debug = st.checkbox("HTML-Debug speichern", value=False)

dealer_url = st.text_input("Händler-URL", placeholder="https://www.kleinanzeigen.de/pro/ff-wheels-by-felgenforum", label_visibility="visible")

AD_HREF_RE = re.compile(r"/s-anzeige/[^\"']*?/(\d+)(?:[/?#]|$)", re.I)

def normalize_url(base: str, href: str) -> str:
    if not href:
        return ""
    from urllib.parse import urljoin, urlparse
    abs_url = urljoin(base, href)
    parsed = urlparse(abs_url)
    clean = parsed._replace(query="", fragment="")
    return clean.geturl()

def extract_from_json_blobs(base_url: str, html: str):
    links = set()
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script"):
        script_type = (script.get("type") or "").lower()
        text = script.string or script.text or ""
        if not text:
            continue
        try:
            if script_type in ("application/json", "application/ld+json"):
                import json as _json
                data = _json.loads(text)
                text_to_scan = _json.dumps(data, ensure_ascii=False)
                for m in AD_HREF_RE.finditer(text_to_scan):
                    href = f"/s-anzeige/x/{m.group(1)}"
                    links.add(normalize_url(base_url, href))
            else:
                if ("__NEXT_DATA__" in text) or ("__INITIAL_STATE__" in text) or ("__PRELOADED_STATE__" in text):
                    for candidate in re.findall(r"(\{.*\}|\[.*\])", text, flags=re.S):
                        if len(candidate) < 10:
                            continue
                        try:
                            import json as _json
                            data = _json.loads(candidate)
                            text_to_scan = _json.dumps(data, ensure_ascii=False)
                            for m in AD_HREF_RE.finditer(text_to_scan):
                                href = f"/s-anzeige/x/{m.group(1)}"
                                links.add(normalize_url(base_url, href))
                        except Exception:
                            continue
        except Exception:
            continue
    return links

def extract_listing_links(base_url: str, html: str):
    soup = BeautifulSoup(html, "html.parser")
    links = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if AD_HREF_RE.search(href):
            links.add(normalize_url(base_url, href))
    for m in AD_HREF_RE.finditer(html):
        href = f"/s-anzeige/x/{m.group(1)}"
        links.add(normalize_url(base_url, href))
    links.update(extract_from_json_blobs(base_url, html))
    return links

def update_query(url: str, **kv) -> str:
    from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
    p = urlparse(url)
    qs = dict(parse_qsl(p.query, keep_blank_values=True))
    for k, v in kv.items():
        if v is None:
            qs.pop(k, None)
        else:
            qs[k] = str(v)
    new_q = urlencode(qs, doseq=True)
    return urlunparse((p.scheme, p.netloc, p.path, p.params, new_q, p.fragment))

def looks_like_consent(html: str) -> bool:
    txt = html.lower()
    keywords = ["cookie", "zustimmung", "einwilligung", "consent", "datenschutz", "we value your privacy"]
    return any(k in txt for k in keywords) and ("/cmp" in txt or "consent" in txt or "accept" in txt)

def diagnose_once(url: str, headers: dict, cookie_string: str):
    s = requests.Session()
    s.headers.update(headers or {})
    if cookie_string:
        s.headers.update({"Cookie": cookie_string})
    r = s.get(url, timeout=30)
    info = {
        "status_code": r.status_code,
        "content_length": len(r.text or ""),
        "found_links": len(extract_listing_links(url, r.text or "")),
        "looks_like_consent": looks_like_consent(r.text or ""),
        "sample": (r.text or "")[:1200],
    }
    return info

def scrape_all_listing_urls(start_url: str, headers: dict, cookie_string: str = "", max_pages: int = 0, delay: float = 0.0, force_query_pagination: bool = False, save_html_debug: bool = False):
    s = requests.Session()
    s.headers.update(headers or {})
    if cookie_string:
        s.headers.update({"Cookie": cookie_string})
    seen = set()
    visited = 0
    current_url = start_url
    debug_htmls = []

    if force_query_pagination:
        current_url = update_query(start_url, page=1)

    while current_url:
        visited += 1
        st.info(f"📄 Lade Seite {visited}: {current_url}")
        try:
            r = s.get(current_url, timeout=30)
        except Exception as e:
            st.warning(f"Fehler beim Abruf: {e}")
            break
        if r.status_code != 200:
            st.warning(f"HTTP {r.status_code} bei {current_url}.")
            break
        html = r.text or ""
        if save_html_debug:
            try:
                debug_htmls.append((visited, html.encode("utf-8", errors="ignore")))
            except Exception:
                pass
        found = extract_listing_links(current_url, html)
        new_links = found - seen
        seen |= found
        st.write(f"➕ Neue Links: **{len(new_links)}**, Gesamt: **{len(seen)}**")
        if max_pages and visited >= max_pages:
            st.info("Max. Seiten erreicht.")
            break
        if force_query_pagination:
            # wenn keine neuen Links -> Ende
            if len(new_links) == 0:
                st.info("Keine neuen Links auf dieser Seite. Ende.")
                break
            from urllib.parse import urlparse, parse_qsl
            p = urlparse(current_url)
            qs = dict(parse_qsl(p.query, keep_blank_values=True))
            page = int(qs.get("page", "1"))
            current_url = update_query(current_url, page=page+1)
        else:
            # Minimal: kein Linkrel/kein Button -> Ende
            break
        if delay > 0:
            time.sleep(delay)

    df = pd.DataFrame(sorted(seen), columns=["url"])
    return df, debug_htmls

col_run, col_diag = st.columns([2,1])
with col_run:
    run = st.button("🔍 Alle Inserat-Links sammeln", type="primary")
with col_diag:
    diag = st.button("🧪 Diagnose (nur Seite 1 prüfen)")

if diag:
    if dealer_url.strip():
        info = diagnose_once(dealer_url.strip(), default_headers, raw_cookie.strip())
        st.code(json.dumps({k: (v if k != "sample" else v[:400]+"…") for k,v in info.items()}, ensure_ascii=False, indent=2))
        if info["looks_like_consent"]:
            st.warning("Sieht nach Consent/Cookie-Seite aus. Bitte Cookies aus dem eingeloggten Browser übernehmen.")
    else:
        st.error("Bitte Händler-URL eingeben.")

if run:
    if not dealer_url.strip():
        st.error("Bitte Händler-URL eingeben.")
        st.stop()
    df, html_debugs = scrape_all_listing_urls(
        dealer_url.strip(), default_headers, raw_cookie.strip(),
        int(max_pages or 0), float(delay_s or 0.0), force_query_pagination, save_html_debug
    )
    st.subheader("Ergebnis")
    st.write(f"Gefundene Links: **{len(df)}**")
    st.dataframe(df, use_container_width=True, hide_index=True)
    if not df.empty:
        import io
        csv_bytes = df.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ CSV", data=csv_bytes, file_name="inserat_links.csv", mime="text/csv")
    if html_debugs:
        import io, zipfile
        zbuf = io.BytesIO()
        with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as z:
            for idx, content in html_debugs:
                z.writestr(f"page_{idx:03d}.html", content)
        st.download_button("⬇️ Debug-HTML (ZIP)", data=zbuf.getvalue(), file_name="html_debug_pages.zip", mime="application/zip")

st.caption("Tipp: In Chrome/Edge → F12 → Network → (Dokument anklicken) → Request Headers → **cookie** komplett kopieren und hier einfügen.")
