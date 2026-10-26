# SmartAgri website

A standalone, English, static presentation of SmartAgri core. No build step, no framework, no external font,
no CDN and no analytics. All paths are relative, so the folder works on a domain root and on a project subpath
such as GitHub Pages (`https://zeljkodzafic.github.io/smartagri-core/`), and on Cloudflare (see below).

The website is separate from the web app: the web app is served by the research API
(`python -m smartagri.research_api`) and is shipped inside the Python package. GitHub Pages and Cloudflare serve
only these static files and run no Python.

## Preview

From the repository root:

```bash
python3 tools/check_presentation_site.py
python3 -m http.server 8080 --directory website
```

Then open `http://127.0.0.1:8080/`.

## Contents

- `index.html`: what SmartAgri is, its four acts, features, the decision layers, interfaces, evaluation and
  reproducibility, limitations, install and run.
- `assets/site.css`, `assets/site.js`: system fonts, light and dark themes that follow the system, responsive
  layout down to 360 px, accessible tabs (arrow keys, Home, End), a screenshot dialog, a copy button for the install
  commands, and section reveals on scroll (IntersectionObserver). Content is fully visible without JavaScript and
  with reduced motion.
- `assets/images/`: actual screenshots of the web app.
- `assets/screenshots.json`: provenance of every screenshot (source commit, capture method, inputs, sha256).

## Screenshots

The screenshots were taken with headless Chromium (Playwright) from the web app running locally with offline
settings (`SMARTAGRI_OFFLINE=1`, `LLM_PROVIDER=template`, `EMBEDDINGS_PROVIDER=none`, a fresh SQLite database).
The parcel was drawn in the app; no image was edited. Offline mode means no weather or satellite data were
fetched, so most inputs are shown as missing; the answers shown are what the system produced in that state. No
results, accuracy figures or user numbers are shown or claimed.

Answers are in English, the default answer language (`SMARTAGRI_LOCALE=sr-Latn` switches to the local language).
Source titles and excerpts stay in their original language: the published development corpus consists of short
paraphrases in Serbian.

When the web app changes, capture new screenshots, update `assets/screenshots.json` (commit and sha256) and run
the check.

## Publish on Cloudflare

The site is deployed as static assets of a Cloudflare Worker named `smartagri-core` (`wrangler.jsonc` at the
repository root, assets directory `./website`). It is live at <https://smartagri-core.calm-silence-b9f5.workers.dev>.

- Automatic: the workflow `.github/workflows/cloudflare-pages.yml` checks the site and runs `wrangler deploy` on every
  push to `main` that changes `website/` (and on demand). It needs two repository secrets: `CLOUDFLARE_API_TOKEN`, an
  API token with the **Workers Scripts: Edit** permission, and `CLOUDFLARE_ACCOUNT_ID`. Without them the site is only
  checked, not deployed. The account ID is a secret of the repository, never a value in a file.
- By hand, from the repository root: `python3 tools/check_presentation_site.py && npx wrangler deploy` (wrangler asks
  you to log in, or reads `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` from the environment).
- Custom domain `smartagri.rs.ba`: once the `smartagri.rs.ba` zone is on Cloudflare, add
  `"routes": [{ "pattern": "smartagri.rs.ba", "custom_domain": true }]` to `wrangler.jsonc` and deploy again;
  Cloudflare creates the DNS record and the certificate.

The web app itself is not part of this site (it needs the Python server); a public deployment of it is described in
`docs/deployment.md`.

## Publish on GitHub Pages (manual alternative)

The workflow `.github/workflows/pages.yml` runs only when started by hand.

1. Settings, Pages, Build and deployment, Source: select **GitHub Actions** (once).
2. Actions, **Deploy website to GitHub Pages**, Run workflow on `main`.
3. Open `https://zeljkodzafic.github.io/smartagri-core/`.

The workflow checks the site before it uploads the `website/` folder. A Pages site is public.

## Validate

`tools/check_presentation_site.py` checks local links and anchors, `aria-controls`, `aria-labelledby` and
`aria-describedby` targets, alt text, that no script, style or image is loaded from another host, and that every
screenshot matches its recorded sha256. CI runs it in the `website` job. These checks cover the site, not the
quality of the advice.
