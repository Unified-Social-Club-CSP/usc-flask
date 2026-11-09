# OCS Kit Inventory: usc-flask

Everything Team Triple T changed or added on top of the OCS Flask backend
([Open-Coding-Society/flask](https://github.com/Open-Coding-Society/flask)) for
the Unified Social Club website, so the CSA team's OCS kit can turn these edits
into settings. Frontend changes are in
[usc-pages/OCS-KIT-INVENTORY.md](https://github.com/Unified-Social-Club-CSP/usc-pages/blob/main/OCS-KIT-INVENTORY.md).

## 1. Settings we had to change (should be kit settings)

| File | Change | Why |
|---|---|---|
| `__init__.py` | Default `FLASK_PORT` 8587 → 8588 | Runs next to the class backend on one laptop |
| `__init__.py` | CORS origins include our frontend (`localhost:4600`, `unified-social-club-csp.github.io`) | The club site calls this API with cookies |
| `templates/layouts/base.html` | `basename`, `frontend` URL, admin stylesheet | Admin pages carry the club's name and link back to its site |
| `templates/layouts/navbar.html`, `index.html` | Club name, capstone link, our API list, Interest Survey menu item | Admin home describes this site's APIs |

**Kit idea:** a single settings file for organization name, frontend URL(s), port, and CORS origins, read by `__init__.py` and the templates.

## 2. OCS files we edited

| File | Change | Why | Upstream? |
|---|---|---|---|
| `api/user.py` | Sign-up no longer requires the uid to be a GitHub account | Club members are community adults, not GitHub users | Kit setting: "require GitHub uid" on/off |
| `main.py` | Register our blueprints, create our tables at start-up, `/usc/interests/` admin page | Load the club APIs | Kit: a plug-in list instead of editing `main.py` |
| `templates/login.html`, `404.html` | Titles and layout using the OCS templates | Consistent admin pages | Optional |
| `README.md` | Club setup, ports, and each API | Docs for the next team | Expected |

## 3. Files we added

| API | Model | What it does | Check script |
|---|---|---|---|
| `api/usc_progress.py` | `model/usc_progress.py` | Saved progress per member per game (Bingo, Jeopardy, Trivia) | — |
| `api/usc_bingo.py` | `model/usc_bingo.py` | Bingo rooms with 4-digit codes; the server checks every BINGO claim | — |
| `api/usc_interests.py` | `model/usc_interests.py` | Tap-only interest survey; admin and volunteer summaries | `scripts/verify_interests.py` |
| `api/usc_dm.py` | `model/usc_dm.py` | Direct messages, members only with volunteers and staff | `scripts/verify_dm.py` (13 checks) |
| `api/usc_jeopardy.py` | `model/usc_jeopardy.py`, `usc_jeopardy_default.json` | Jeopardy boards written by volunteers; saved games with server-checked scores | `scripts/verify_jeopardy.py` (18 checks) |

Also: `templates/usc_interests.html`, `static/css/usc-admin.css`, and the Quick and Formal issue templates in `.github/ISSUE_TEMPLATE/`.

## 4. What a kit should offer (from our experience)

1. **A settings file** for name, frontend URLs, port, and CORS (section 1).
2. **A switch for non-GitHub accounts**, since most organizations' members aren't on GitHub.
3. **A blueprint plug-in list** so new APIs register and create their tables without editing `main.py`.
4. **Role-based staff access** already works through `token_required(roles)`; documenting the roles (Admin, Teacher, Volunteer) would help other organizations.
5. **A check-script pattern** (`scripts/verify_*.py`): throwaway accounts, real requests, cleanup.

## 5. Changes still planned

- Club Trivia Live rooms API (Chetan), modeled on `api/usc_bingo.py`.
- Hosting on an opencodingsociety.com domain, then adding that origin to CORS.
