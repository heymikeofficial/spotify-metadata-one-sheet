"""
🎧 Spotify Metadata One-Sheet Generator
----------------------------------------
Paste a Spotify album (or track) link and this app pulls all the metadata
for that release, shows a progress bar while it works, and lets you download
a clean, formatted PDF one-sheet with the album artwork at the top.

ISRC codes are pulled from Spotify where available, and fall back to the
MusicBrainz API (looked up by the release's UPC barcode) when they're not.

Credentials are read from Streamlit secrets / environment variables —
never hard-coded. See README for setup.
"""

import os
import re
import io
import time

import requests
import streamlit as st
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Image as RLImage, Paragraph, Spacer, Table, TableStyle,
)


# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------
st.set_page_config(page_title="Spotify Metadata One-Sheet", page_icon="🎧")

CONTACT_EMAIL = "mikealanepstein@gmail.com"  # used in the MusicBrainz User-Agent
USER_AGENT = f"MusicMetadataOneSheet/1.0 ( {CONTACT_EMAIL} )"


def get_secret(name):
    """Read a secret from Streamlit secrets first, then the environment."""
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.environ.get(name)


def get_spotify_client():
    client_id = get_secret("SPOTIFY_CLIENT_ID")
    client_secret = get_secret("SPOTIFY_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None
    return spotipy.Spotify(
        auth_manager=SpotifyClientCredentials(
            client_id=client_id, client_secret=client_secret
        )
    )


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def extract_id(url):
    """Return (item_type, spotify_id) for a track or album URL, else (None, None)."""
    match = re.search(r"spotify\.com/(track|album)/([a-zA-Z0-9]+)", url)
    if match:
        return match.group(1), match.group(2)
    return None, None


def ms_to_length(ms):
    """Convert milliseconds to m:ss."""
    seconds = int(round(ms / 1000))
    return f"{seconds // 60}:{seconds % 60:02d}"


def normalize_title(title):
    """Loose title key for matching tracks across Spotify and MusicBrainz."""
    title = title.lower()
    title = re.sub(r"\(.*?\)|\[.*?\]", "", title)        # drop bracketed bits
    title = re.sub(r"[^a-z0-9]", "", title)               # drop punctuation/spaces
    return title


def musicbrainz_lookup_by_upc(upc):
    """Look up a release on MusicBrainz by its UPC barcode.

    Returns {"isrcs": {normalized_title: isrc}, "label": str|None}. MusicBrainz
    asks for a descriptive User-Agent and ~1 request/second, both of which we
    respect.
    """
    empty = {"isrcs": {}, "label": None}
    if not upc:
        return empty
    headers = {"User-Agent": USER_AGENT}
    try:
        search = requests.get(
            "https://musicbrainz.org/ws/2/release/",
            params={"query": f"barcode:{upc}", "fmt": "json"},
            headers=headers, timeout=15,
        )
        releases = search.json().get("releases", [])
        if not releases:
            return empty
        release_id = releases[0]["id"]

        time.sleep(1.1)  # be polite to MusicBrainz
        detail = requests.get(
            f"https://musicbrainz.org/ws/2/release/{release_id}",
            params={"inc": "recordings+isrcs+labels", "fmt": "json"},
            headers=headers, timeout=15,
        )
        data = detail.json()
    except Exception:
        return empty

    isrc_map = {}
    for medium in data.get("media", []):
        for track in medium.get("tracks", []):
            recording = track.get("recording", {})
            isrcs = recording.get("isrcs", [])
            if isrcs:
                isrc_map[normalize_title(recording.get("title", ""))] = isrcs[0]

    label = None
    for li in data.get("label-info", []):
        name = (li.get("label") or {}).get("name")
        if name:
            label = name
            break

    return {"isrcs": isrc_map, "label": label}


def label_from_copyrights(album):
    """Last-resort label: the phonographic (P) copyright line from Spotify."""
    for c in album.get("copyrights", []):
        if c.get("type") == "P" and c.get("text"):
            return c["text"]
    copyrights = album.get("copyrights")
    return copyrights[0]["text"] if copyrights else None


def fetch_album_data(sp, album_id, progress):
    """Pull all metadata for an album, with ISRC fallback to MusicBrainz."""
    progress.progress(15, text="Fetching album details from Spotify…")
    album = sp.album(album_id)

    upc = album.get("external_ids", {}).get("upc")
    artwork_url = album["images"][0]["url"] if album.get("images") else None

    info = {
        "name": album["name"],
        "artist": ", ".join(a["name"] for a in album["artists"]),
        "release_date": album.get("release_date", "—"),
        "label": album.get("label"),  # often stripped by Spotify; filled in below
        "upc": upc or "—",
        "artwork_url": artwork_url,
    }

    progress.progress(35, text="Collecting the tracklist…")
    items = album["tracks"]["items"]
    track_ids = [t["id"] for t in items if t.get("id")]

    # Try to get ISRCs from Spotify directly. Spotify currently restricts the
    # tracks endpoint for many apps (returns 403), so this may yield nothing —
    # in which case we fall back to MusicBrainz below.
    progress.progress(55, text="Looking up ISRC codes on Spotify…")
    spotify_isrcs = {}
    for i in range(0, len(track_ids), 50):
        try:
            batch = sp.tracks(track_ids[i : i + 50])["tracks"]
            for t in batch:
                spotify_isrcs[t["id"]] = t.get("external_ids", {}).get("isrc")
        except Exception:
            break  # Spotify restricted ISRC access — rely on MusicBrainz instead

    # Backfill from MusicBrainz (by UPC) whatever Spotify didn't give us —
    # ISRCs and/or the record label.
    missing = [t["id"] for t in items if not spotify_isrcs.get(t["id"])]
    mb_map = {}
    if missing or not info["label"]:
        progress.progress(75, text="Filling gaps from MusicBrainz…")
        mb = musicbrainz_lookup_by_upc(upc)
        mb_map = mb["isrcs"]
        if not info["label"] and mb["label"]:
            info["label"] = mb["label"]

    # Final label fallback: the (P) copyright line from Spotify.
    if not info["label"]:
        info["label"] = label_from_copyrights(album) or "—"

    progress.progress(90, text="Assembling your one-sheet…")
    tracks = []
    for t in items:
        isrc = spotify_isrcs.get(t["id"])
        if not isrc:
            isrc = mb_map.get(normalize_title(t["name"]), "—")
        tracks.append({
            "number": t.get("track_number", "—"),
            "name": t["name"],
            "length": ms_to_length(t.get("duration_ms", 0)),
            "isrc": isrc or "—",
        })

    return info, tracks


def build_pdf(info, tracks, artwork_bytes):
    """Render a clean PDF one-sheet with the artwork at the top."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
        title=f"{info['artist']} — {info['name']}",
    )

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Title"], fontSize=20, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=styles["Normal"], fontSize=13,
                        textColor=colors.HexColor("#555555"), spaceAfter=10)

    elements = []

    if artwork_bytes:
        art = RLImage(io.BytesIO(artwork_bytes), width=55 * mm, height=55 * mm)
        art.hAlign = "CENTER"
        elements.append(art)
        elements.append(Spacer(1, 8 * mm))

    elements.append(Paragraph(info["name"], h1))
    elements.append(Paragraph(info["artist"], h2))

    meta_rows = [
        ["Release date", info["release_date"]],
        ["Record label", info["label"]],
        ["UPC barcode", info["upc"]],
        ["Total tracks", str(len(tracks))],
    ]
    meta_table = Table(meta_rows, colWidths=[35 * mm, 130 * mm])
    meta_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#888888")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(meta_table)
    elements.append(Spacer(1, 8 * mm))

    track_rows = [["#", "Track", "Length", "ISRC"]]
    for t in tracks:
        track_rows.append([str(t["number"]), t["name"], t["length"], t["isrc"]])

    track_table = Table(track_rows, colWidths=[10 * mm, 95 * mm, 20 * mm, 40 * mm],
                        repeatRows=1)
    track_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1DB954")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#f4f4f4")]),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ALIGN", (2, 0), (2, -1), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.white),
    ]))
    elements.append(track_table)

    doc.build(elements)
    return buf.getvalue()


# ----------------------------------------------------------------------------
# UI
# ----------------------------------------------------------------------------
st.title("🎧 Spotify Metadata One-Sheet")
st.write(
    "Paste a Spotify **album** link and get a clean PDF one-sheet — artwork, "
    "label, UPC, and every track's ISRC. No technical skills required."
)

sp = get_spotify_client()
if sp is None:
    st.error(
        "Spotify credentials aren't configured. Add `SPOTIFY_CLIENT_ID` and "
        "`SPOTIFY_CLIENT_SECRET` to your Streamlit secrets (or environment)."
    )
    st.stop()

spotify_url = st.text_input("Spotify album link", placeholder="https://open.spotify.com/album/…")

if spotify_url:
    item_type, item_id = extract_id(spotify_url)

    if not item_id:
        st.error("That doesn't look like a Spotify track or album link. Try again.")
        st.stop()

    # If a track link is pasted, resolve it to its parent album.
    if item_type == "track":
        item_id = sp.track(item_id)["album"]["id"]

    progress = st.progress(5, text="Getting started…")
    try:
        info, tracks = fetch_album_data(sp, item_id, progress)

        artwork_bytes = None
        if info["artwork_url"]:
            try:
                artwork_bytes = requests.get(info["artwork_url"], timeout=15).content
            except Exception:
                artwork_bytes = None

        progress.progress(100, text="Done!")
        time.sleep(0.3)
        progress.empty()
    except Exception as e:
        progress.empty()
        st.error(f"Something went wrong fetching that release: {e}")
        st.stop()

    # ---- On-screen display ----
    col_art, col_meta = st.columns([1, 2])
    with col_art:
        if info["artwork_url"]:
            st.image(info["artwork_url"], use_container_width=True)
    with col_meta:
        st.subheader(info["name"])
        st.write(f"**Artist:** {info['artist']}")
        st.write(f"**Release date:** {info['release_date']}")
        st.write(f"**Label:** {info['label']}")
        st.write(f"**UPC:** {info['upc']}")
        st.write(f"**Tracks:** {len(tracks)}")

    st.subheader("Tracklist")
    st.table([
        {"#": t["number"], "Track": t["name"], "Length": t["length"], "ISRC": t["isrc"]}
        for t in tracks
    ])

    # ---- PDF download ----
    pdf_bytes = build_pdf(info, tracks, artwork_bytes)
    safe_name = re.sub(r"[^A-Za-z0-9]+", "_", f"{info['artist']}_{info['name']}").strip("_")
    st.download_button(
        "⬇️  Download PDF one-sheet",
        data=pdf_bytes,
        file_name=f"{safe_name}_one_sheet.pdf",
        mime="application/pdf",
    )
