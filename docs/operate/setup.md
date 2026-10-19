# Setting up Mycel

Two parts, done by different people.

| Part | Who | How often |
|---|---|---|
| [Setup](#setup--once-by-an-admin) | an admin | once per deployment |
| [Use](#use--each-person) | everyone | once per person |

`.env` holds only what hosting needs: the stores, the app's own identities, and the key
that encrypts stored tokens. Nothing in it belongs to one person — each person's Jira,
calendar and mail are connected by that person, in the app.

## Setup — once, by an admin

### 1. A Jira service account for the sync

The sync reads Jira in the background, when nobody is signed in. It reads as its own
account, so nobody leaving can stop it. It needs **Browse** on the projects to sync and
nothing more — never admin.

Needs: organization admin on Atlassian Cloud. Free: up to five service accounts.

1. [admin.atlassian.com](https://admin.atlassian.com) → **Directory** → **Service accounts**
   → **Create service account**. Name it e.g. `mycel-sync`. App role: **Jira → User**,
   everything else **None**.
   ([Atlassian: service accounts](https://support.atlassian.com/user-management/docs/understand-service-accounts/))
2. Open it → **Create credentials** → **API token**. Expiry: up to 365 days. Scopes:
   `read:jira-work` and `read:jira-user` only.
   ([Atlassian: API tokens for service accounts](https://support.atlassian.com/user-management/docs/manage-api-tokens-for-service-accounts/))
   The token is shown once.
3. Add it to **every project to sync**: Jira → the project → **Project settings** →
   **Access** → **Add people** → pick `mycel-sync` (the entry with an avatar, not the
   email invite) → role **Viewer**. Do the same for any project added later.
   Atlassian does not let a service account join a group, so this is per project.
4. Find the site's cloud id: open `https://<your-site>.atlassian.net/_edge/tenant_info`
   and copy `cloudId`.
5. In `.env`:
   ```
   JIRA_SERVICE_TOKEN=<the token>
   JIRA_CLOUD_ID=<the cloud id>
   JIRA_SERVICE_TOKEN_EXPIRES=<its last day, YYYY-MM-DD>
   ```
   `doctor` warns a month before that day. Make the next token then.

Every project the service account can browse is synced. There is no project list to keep.

### 2. The Jira OAuth app, for "Connect Jira"

Each person connects their own Jira so Mycel can ask Jira which projects *they* may browse,
and write comments or tickets under *their* name.

1. [developer.atlassian.com/console/myapps](https://developer.atlassian.com/console/myapps/)
   → **Create** → **OAuth 2.0 integration**.
2. **Permissions** → Jira API: `read:jira-work`, `read:jira-user`, `write:jira-work`.
3. **Authorization** → callback URL: `<PUBLIC_BASE_URL>/auth/jira/callback`.
4. **Settings** → copy the client id and secret into `.env`:
   `JIRA_CLIENT_ID`, `JIRA_CLIENT_SECRET`.

### 3. The Google OAuth client, for "Connect Google"

Each person's own calendar and mail.

1. [console.cloud.google.com](https://console.cloud.google.com/) → a project → enable the
   **Google Calendar API** and the **Gmail API**.
2. **OAuth consent screen**: add the scopes `calendar.events` and `gmail.readonly`.
3. **Credentials** → **OAuth client ID** → Web application → redirect URI:
   `<PUBLIC_BASE_URL>/auth/google/callback`.
4. Into `.env`: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`.

### 4. Models

Copy `config/litellm/models.example.yaml` to `config/litellm/models.yaml` (not tracked) and
keep the providers you have. Each `model_name` is what `config/agents/*.yaml` asks for as
`cloud:<model_name>`. Put the keys it names in `.env`.

### 5. The rest of `.env`

| Key | What |
|---|---|
| `TOKEN_ENCRYPTION_KEY` | encrypts every stored refresh token. `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Rotating it disconnects everyone |
| `SMTP_HOST`, `SMTP_FROM`, `SMTP_USERNAME`, `SMTP_PASSWORD` | the sender for password-reset mail. Gmail: `smtp.gmail.com` and an [app password](https://myaccount.google.com/apppasswords). Without it, reset is off and `doctor` says so |
| `PUBLIC_BASE_URL` (in `config/environments/`) | the address people reach the app at. Every callback and reset link is built from it |

Then:

```bash
scripts/stack.sh dev up      # or compose / k8s
scripts/stack.sh doctor      # what is set, what is broken, what is off
```

### Not supported yet

- **Jira Server / Data Center.** No service accounts there; it would need a plain user and
  a personal access token. Not built, and nothing to test it against.
- **Per-issue permissions** (Jira issue security). Access is per project.

## Use — each person

Open the app → account menu → **Settings**:

- **Connect Jira.** Mycel asks Jira which projects you may browse and shows you exactly
  those. It asks again after every sync, so a project you lose in Jira leaves here within
  one sync (15 minutes).
- **Connect Google.** Your own calendar and your own mail. Nobody else's.

Not connected → no Jira data, no calendar, no mail. Your own documents still work.
