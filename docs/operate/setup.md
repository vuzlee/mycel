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

### 1. The Jira OAuth app, for "Connect Jira"

Each person connects their own Jira. Mycel asks Jira which projects *they* may browse,
writes under *their* name, and the background sync reads each project on the token of one
person who may browse it. A project nobody connected can browse is not synced.

1. [developer.atlassian.com/console/myapps](https://developer.atlassian.com/console/myapps/)
   → **Create** → **OAuth 2.0 integration**.
2. **Permissions** → Jira API: `read:jira-work`, `read:jira-user`, `write:jira-work`.
3. **Authorization** → callback URL: `<PUBLIC_BASE_URL>/auth/jira/callback`.
4. **Settings** → copy the client id and secret into `.env`:
   `JIRA_CLIENT_ID`, `JIRA_CLIENT_SECRET`.

### 2. The Google OAuth client, for "Connect Google"

Each person's own calendar and mail.

1. [console.cloud.google.com](https://console.cloud.google.com/) → a project → enable the
   **Google Calendar API** and the **Gmail API**.
2. **OAuth consent screen**: add the scopes `calendar.events` and `gmail.readonly`.
3. **Credentials** → **OAuth client ID** → Web application → redirect URI:
   `<PUBLIC_BASE_URL>/auth/google/callback`.
4. Into `.env`: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`.

### 3. Models

Copy `config/litellm/models.example.yaml` to `config/litellm/models.yaml` (not tracked) and
keep the providers you have. Each `model_name` is what `config/agents/*.yaml` asks for as
`cloud:<model_name>`. Put the keys it names in `.env`.

### 4. The rest of `.env`

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

- **Jira Server / Data Center.** Only Atlassian Cloud OAuth is built; Server would need
  personal access tokens. Nothing to test it against.
- **Per-issue permissions** (Jira issue security). Access is per project.

## Use — each person

Open the app → account menu → **Settings**:

- **Connect Jira.** Mycel asks Jira which projects you may browse and shows you exactly
  those. It asks again after every sync, so a project you lose in Jira leaves here within
  one sync (15 minutes).
- **Connect Google.** Your own calendar and your own mail. Nobody else's.

Not connected → no Jira data, no calendar, no mail. Your own documents still work.
