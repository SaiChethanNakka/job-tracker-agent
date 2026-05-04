# Job Application Tracker Agent

AI-powered Gmail agent that tracks job applications, classifies recruiter emails, and generates weekly rejection pattern analysis with resume gap recommendations.

## Architecture

```
Gmail API (read-only)
    ↓
EmailClassifier (Claude API)    → Labels each email with type, company, stage
    ↓
ApplicationTracker (SQLite)     → Persists state machine per application
    ↓
ReportGenerator (Claude API)    → Analyzes patterns, flags keyword gaps
    ↓
Flask Server + Web Dashboard    → Local UI at localhost:5050
```

## Setup

### 1. Python environment

```bash
cd job-tracker-agent
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Anthropic API key

```bash
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
```

### 3. Gmail API credentials (one-time setup)

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project → name it "Job Tracker"
3. Go to **APIs & Services** → **Enable APIs** → search **Gmail API** → Enable
4. Go to **APIs & Services** → **Credentials** → **Create Credentials** → **OAuth 2.0 Client ID**
5. Application type: **Desktop app**
6. Download the JSON file → rename it `credentials.json` → place it in the project root (same level as `requirements.txt`)
7. Go to **OAuth consent screen** → set to **External** → add your Gmail as a test user

### 4. First run (browser auth)

On first run, a browser window will open asking you to authorize Gmail access.
This is a **read-only** scope (`gmail.readonly`) — the agent never modifies your emails.
After consent, `token.json` is saved and auto-refreshed going forward.

---

## Running the Agent

### Option A: One-shot scan (testing or manual use)

```bash
cd src
python agent.py --mode once --days 7
```

This scans the last 7 days of Gmail and exits. Good for initial setup verification.

### Option B: Scheduled (runs daily at 8 AM)

```bash
cd src
python agent.py --mode schedule
```

Leave this running in a terminal (or set up as a background service — see below).

### Option C: Run the web dashboard

Open a **second terminal**:

```bash
cd src
python server.py
```

Then open: [http://localhost:5050](http://localhost:5050)

---

## Web Dashboard Pages

| Page | What it shows |
|------|---------------|
| **Dashboard** | Stats summary, application funnel, recent activity |
| **All Applications** | Full table with stage, status, dates — click any row for email timeline |
| **Analysis Reports** | AI-generated rejection pattern reports with resume gap recommendations |

---

## Running as a Background Service (macOS)

To have the agent run daily without keeping a terminal open:

Create `~/Library/LaunchAgents/com.jobtracker.agent.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.jobtracker.agent</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/job-tracker-agent/venv/bin/python</string>
        <string>/path/to/job-tracker-agent/src/agent.py</string>
        <string>--mode</string>
        <string>schedule</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/path/to/job-tracker-agent/agent.log</string>
    <key>StandardErrorPath</key>
    <string>/path/to/job-tracker-agent/agent.log</string>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.jobtracker.agent.plist
```

---

## Running as a Background Service (Linux/WSL)

```bash
# Create a systemd service or simply use cron
crontab -e

# Add this line (runs daily at 8 AM):
0 8 * * * /path/to/job-tracker-agent/venv/bin/python /path/to/job-tracker-agent/src/agent.py --mode once --days 1 >> /path/to/job-tracker-agent/agent.log 2>&1
```

---

## Project Structure

```
job-tracker-agent/
├── .env                    ← Your secrets (gitignored)
├── .env.example            ← Template
├── credentials.json        ← Downloaded from GCP (gitignored)
├── token.json              ← Auto-generated after first OAuth (gitignored)
├── requirements.txt
├── agent.log               ← Auto-generated run log
├── db/
│   └── applications.db     ← SQLite database
├── reports/
│   └── YYYY-MM-DD.md       ← Generated Markdown reports
├── src/
│   ├── agent.py            ← Main orchestrator + scheduler
│   ├── gmail_client.py     ← Gmail OAuth + email fetching
│   ├── classifier.py       ← Claude API email classification
│   ├── tracker.py          ← SQLite persistence layer
│   ├── reporter.py         ← Claude API rejection analysis
│   └── server.py           ← Flask API + dashboard server
└── web/
    └── index.html          ← Local web dashboard
```

---

## Keeping Resume Keywords Current

In `src/reporter.py`, update `MY_RESUME_KEYWORDS` whenever you update your resume:

```python
MY_RESUME_KEYWORDS = [
    "Java 17", "Spring Boot", "Kafka", "PostgreSQL", ...
]
```

The agent cross-references this list against patterns it detects in rejection email contexts to flag gaps.

---

## Security Notes

- `credentials.json` and `token.json` are local only — add both to `.gitignore` if you push this to GitHub
- The agent uses `gmail.readonly` scope — it cannot send, delete, or modify any email
- No email content is stored permanently — only extracted metadata (company, role, stage, summary) goes into SQLite
