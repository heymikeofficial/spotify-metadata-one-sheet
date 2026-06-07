# 🎧 Spotify Metadata One-Sheet

A simple, free web app for music professionals. Paste a Spotify **album** link
and it pulls all the release metadata — artwork, artist, album, release date,
record label, UPC barcode — plus the track number, name, length, and **ISRC**
for every track. It shows a progress bar while it works, then lets you download
a clean, formatted **PDF one-sheet** with the artwork at the top.

ISRCs come from Spotify where available, and fall back to the **MusicBrainz**
API (looked up by the release's UPC barcode) when Spotify doesn't return them.

## Run it locally

1. Install the dependencies:
   ```bash
   python3 -m pip install -r requirements.txt
   ```
2. Add your free Spotify Developer credentials. Copy
   `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and fill in
   your `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET`
   (get them at https://developer.spotify.com/dashboard).
3. Start the app:
   ```bash
   streamlit run metadata_app.py
   ```

## Deploy it for free (so anyone can use it)

1. Push this folder to a GitHub repository.
2. Go to https://share.streamlit.io and sign in with GitHub.
3. Click **New app**, pick this repo, and set the main file to `metadata_app.py`.
4. Under **Advanced settings → Secrets**, paste:
   ```toml
   SPOTIFY_CLIENT_ID = "your-client-id"
   SPOTIFY_CLIENT_SECRET = "your-client-secret"
   ```
5. Deploy. You'll get a public `https://…streamlit.app` URL anyone can open.

> **Never** commit your real credentials. `.streamlit/secrets.toml` is
> gitignored on purpose — secrets live in the Streamlit Cloud dashboard.

## Files

| File | What it is |
|------|-----------|
| `metadata_app.py` | The web app (this is the one that runs) |
| `metadata_clean.py` | Earlier command-line version (kept for reference) |
| `spotify_metadata.py` | First command-line version (kept for reference) |
| `requirements.txt` | Python dependencies |
