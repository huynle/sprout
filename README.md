# Sprout

A small family web app for printable learning material: worksheets made to your child's level,
coloring pages, a history of what each child did and how it went, and a board of project ideas.
It works on a phone, tablet or laptop and can be installed as an app from the browser.

- **Make a sheet**: math drills (1 or 2 digits, with or without carrying, 20 to 60 problems) and name
  tracing with single-stroke letters, previewed before you print.
- **Each child**: age (worked out from the birthday every day), current level, next steps, and a
  history with a quick "How did it go?" (too easy, just right, too hard, loved it).
- **Coloring pages**: upload pictures or PDFs, tag them, print them, log them for a child.
- **Ask for something**: describe what you want ("30 two-digit addition problems", "a coloring page
  of a hot air balloon"). An AI model turns it into settings for a built-in worksheet, or draws a
  black-and-white coloring page. Everything is a draft you preview first.
- **Project ideas**: things to build together (CNC router, laser cutter, printer, other).
- **Families**: each family's data is separate and shared by everyone in it. Owners add children and invite
  a partner or others by Google email. With open sign-up anyone can create their own family; members can
  leave and owners can delete the family with everything in it.

## Run it locally

```bash
uv sync
SPROUT_ADMINS=you@example.com DEV_LOGIN_EMAIL=you@example.com uv run sprout serve
```

Open http://localhost:8000, continue, create your family, add children. Add `SPROUT_SIGNUP=open
SPROUT_OPERATOR_NAME=You SPROUT_CONTACT_EMAIL=you@example.com` to let anyone create a family. `DEV_LOGIN_EMAIL` skips
Google sign-in and only works when `PUBLIC_BASE_URL` is localhost. Add `?as=other@example.com` to
`/dev-login` to try a second person.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `PUBLIC_BASE_URL` | `http://localhost:8000` | Address people use; secure cookies when https |
| `DATA_DIR` | `data` | SQLite database and files |
| `SPROUT_ADMINS` | (required) | Comma-separated emails of instance admins (can always create families; see `/admin`) |
| `SPROUT_SIGNUP` | `invite` | `open`: anyone who signs in with Google can create one family; `invite`: only invited emails and admins |
| `SPROUT_OPERATOR_NAME` | | Who runs this site, shown on the privacy and terms pages (required with `open`) |
| `SPROUT_CONTACT_EMAIL` | | Contact address on the privacy and terms pages (required with `open`) |
| `SPROUT_FAMILY_QUOTA_MB` | `500` | Storage per family for sheets and uploads |
| `AI_INSTANCE_DAILY_CAP` | `300` | Assistant requests per day across all families (each family also has 40/day) |
| `GOOGLE_CLIENT_ID` | | Google OAuth client (web application) |
| `GOOGLE_CLIENT_SECRET` | | Its secret; redirect URI is `PUBLIC_BASE_URL/auth/callback` |
| `DEV_LOGIN_EMAIL` | | Local development only: sign in as this email without Google |
| `LLM_URL` | | OpenAI-compatible API base URL (e.g. `https://api.openai.com/v1`) for "Ask for something" |
| `LLM_KEY` | | API key for `LLM_URL` |
| `LLM_MODEL` | | Chat model that supports JSON output |
| `IMAGE_MODEL` | | Image model at the same API for coloring pages (optional) |
| `STUDIO_URL` | | Optional. Base URL of a [Studio](#studio-worksheets-optional) server (e.g. `http://image-mcp.image-mcp.svc` in-cluster); enables the Studio worksheet kinds |
| `STUDIO_TOKEN` | | Studio personal access token (`imcp_…`); required with `STUDIO_URL` |
| `STUDIO_FAMILY_DAILY_CAP` | `30` | Studio-rendered sheets per family per day |
| `PRINTER_URL` | | Reserved for server-side printing (not used yet) |
| `PRINTER_TOKEN` | | Reserved for server-side printing (not used yet) |
| `PRINTER_ID` | | Reserved for server-side printing (not used yet) |

## Studio worksheets (optional)

Some worksheet kinds ("Big addition") are laid out in HTML and rendered to PDF by Studio, an MCP
server with an isolated headless Chromium (`html_to_pdf`). Without `STUDIO_URL` those kinds are
simply not offered; everything else works. Sprout sends only the generated HTML (numbers and
options): the child's name is never sent, it is stamped onto page 1 by Sprout after rendering.
Studio's copy of each PDF expires there on its own; Sprout keeps its own copy like any other sheet.

## Command line

| Command | What it does |
|---|---|
| `sprout serve [--host H] [--port P]` | Run the web app |
| `sprout import FILE.json` | Load a family's history from a JSON file (see `docs/import.md`) |
| `python -m sprout.worksheets.math_drill [seed] [out.pdf] [--ops ...] [--digits 1\|2] [--regroup] [--count N]` | Math drill PDF |
| `python -m sprout.worksheets.name_trace NAME [out.pdf] [--size 88]` | Name tracing PDF |

## Privacy and safety

- Each family's rows and files are only reachable by that family's members.
- Birthdays are stored to show ages; the AI is only told a child's first name, age in years and
  current level.
- The AI can't write HTML or code: it can only choose a built-in worksheet with validated settings
  or describe a picture. A family can make at most 40 requests a day.
- Coloring-page links can only be imported from a short list of sites; uploads are re-encoded.
  Use pictures for your own family and respect their creators' terms.
- For projects made with tools: sand every edge, avoid small parts for children under 3, use
  non-toxic finishes, and never laser-cut PVC or vinyl.

## Development

```bash
uv sync
uv run ruff check . && uv run pytest -q
```

Adding a worksheet: write `src/sprout/worksheets/<kind>.py` with `make_<kind>(...) -> bytes` and a
CLI, then register it in `src/sprout/sheets.py` with its fields. The form, the AI's options and
validation all come from that one field list.

## License

Sprout is free software under the GNU Affero General Public License v3.0 or later
([LICENSE](LICENSE)). Contributions need the [Contributor License Agreement](CLA.md); see
[CONTRIBUTING.md](CONTRIBUTING.md). For other licensing terms, contact the maintainer.
