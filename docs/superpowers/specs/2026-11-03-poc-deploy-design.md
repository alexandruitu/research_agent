# Corporate POC deploy: signup, per-user keys, two libraries, plain-language UX, Docker

Date: 2026-11-03 · Status: approved by the user. Decisions: no SSO yet; every user brings their own keys; all
members may add to the company library, full text only; topics and runs visible to all; Docker on one LAN
machine.

## 1. Signup

- The login screen gets a "Create an account" link to a signup form with email, name and password (the same
  policy as invites, minimum 12 characters).
- **Allowed email domains:** an admin setting, `signup_domains` (a list). It is empty by default, which means
  signup is off. The deploy sets it, for example to `siemens-healthineers.com`. Any other domain is refused
  with a plain message.
- **New accounts** get the role `member` and status active. No email confirmation for the POC (there is no
  SMTP). An admin can deactivate an account in Users.
- **Abuse limits:**
  - a rate limit per IP on signup and login;
  - an email that is already taken returns the same generic message as a new one, so it does not reveal which
    accounts exist.
- An admin can still invite users as today.

## 2. Per-user keys and models

- **Settings → My keys** (every user):
  - Providers: Anthropic, Google (Gemini), OpenAI, xAI, TypeSafe (Jev), and the optional sources that take a
    key (Semantic Scholar, CORE, IEEE, Springer, Scopus).
  - For each provider, the user can add or replace a key, test it, and delete it.
  - After saving, the key is never shown again; the UI shows only "…last 4" and the date it was saved.
- **Storage:**
  - Table `user_secrets` (user_id, provider, ciphertext, last4, created_at, checked_at, check_ok).
  - The ciphertext is encrypted with Fernet. The master key `RESEARCH_SECRETS_KEY` lives in the server
    environment only; without it the server refuses to start.
  - The API only encrypts. Only the worker decrypts, and only when it makes a call.
  - Keys never appear in logs, errors, job payloads or API responses.
- **Use:**
  - A job runs with the keys of the user who started it. The worker passes them to the child process through
    the environment (as today with `.env`) and never writes them to disk.
  - There is **no fallback** to a company key. A step that needs a missing key is blocked before the job
    starts, with "Add your <provider> key in Settings → My keys".
  - The worker's own `.env` keys are used only in demo and development mode.
- **Models per user:**
  - Settings → My models: for each role (screen, extract, each reviewer, editor, reader, paper map), choose a
    provider and a model from a list, for example Claude Opus 5.5 or Sonnet 5, Gemini, GPT, Grok.
  - Only providers the user has a key for can be picked.
  - The admin defaults stay as the starting point.
- **New providers:** OpenAI (`openai:`) and xAI (`xai:`) through the same LangChain `init_chat_model`
  structured-output path. They are added to the cost table, with prices marked "estimate" when unknown.
- **Cache:** the cache key includes the user id, so cached answers are never shared between users and each
  user's costs stay true. Existing caches belong to a legacy namespace and stay readable by their runs.
- **Costs:** the run's cost table already exists. "My usage" in Settings sums a user's calls and estimated
  cost per month.

## 3. Two libraries

- When saving, the user picks **My library** (private) or **Company library** (everyone). A paper can be in
  both.
- **Company library:**
  - only papers **with full text**. Save is disabled for abstract-only papers, with the reason shown and an
    "Upload the PDF" action;
  - any member can add; the adder, or an admin, can remove;
  - notes on a company item are visible to everyone; Reader notes have a private/company choice.
- **Library page:** tabs "My library" and "Company library", with the same filters, authors and export.
- **Migration:** the existing library becomes the Company library, keeping its current items. Items without
  full text stay, flagged "abstract only".
- Licence: the Company library shows the stored text to logged-in users only, inside the company LAN. The
  item records the licence and source of its text.

## 4. Plain-language UX (from the demo: "what is a Run?")

- **Wording everywhere:**
  - Topic stays "Topic".
  - "Run" becomes **"Search"** in the user interface: "Start a search", "Your searches", "Search results".
    Each search shows a plain one-line description, for example "Searched 6 sources for 'CCTA plaque' and
    reviewed 5 papers".
  - "Screening" in the nav becomes **"② Search"**.
  - Internal names (run, stage, job) stay in Validation only.
- **First-use guide:** a 3-step welcome card on an empty start page: create a topic → start a search → read the
  results. It can be dismissed, and it comes back from a "How it works" link in the header.
- **Page intros:** every page has a one-sentence intro saying what it is for and what to do next.
- **Glossary:** jargon (screening, red flag, coverage, provisional, recall) carries the existing "?" glossary
  tip, and the glossary is reviewed for plain wording.
- **Empty states and errors:** they always say the next action.

## 5. Docker deploy (one LAN machine)

- `Dockerfile` (multi-stage: build the web app, then a Python runtime) and `docker-compose.yml` with:
  - `db` (PostgreSQL 16, persistent volume);
  - `api` (`research-web serve`, which also serves the built frontend);
  - `worker` (`research-web worker`);
  - `proxy` (Caddy with internal TLS, or a provided certificate).
- **Persistence:** volumes for the database, runs/cache and uploads.
- **Environment:** `.env.example` holds `RESEARCH_SECRETS_KEY`, the database URL, the signup domains, an admin
  bootstrap email and password, and the contact address for polite API pools. No LLM keys, because each user
  brings their own.
- **Proxy:** outbound HTTP(S) proxy variables (`HTTPS_PROXY`, `NO_PROXY`) are passed to the worker for
  networks that need them.
- **Operations:**
  - health checks;
  - `docker compose up -d` brings the stack up; migrations run on start;
  - `scripts/backup.sh` dumps the database and archives the volumes.
- `docs/deployment-docker.md`: step-by-step install, first admin, backup and restore, upgrade.

## Order

1 signup → 2 keys and models → 3 libraries → 4 UX → 5 Docker. Each step gets targeted tests; full suites run
before the merge.
