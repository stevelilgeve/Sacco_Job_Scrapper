# 🏦 SACCO ICT Job Scraper — Kenya

Automatically finds **SACCO ICT jobs in Kenya** with deadlines in the current month,
validates them with **Kimi AI**, exports an **Excel file**, and emails it to you — **every hour, for free**.

---

## 📁 Files

```
├── scraper.py                          # Main scraper script
├── requirements.txt                    # Python dependencies
├── .github/
│   └── workflows/
│       └── scraper.yml                 # GitHub Actions (hourly cron)
└── seen_jobs.json                      # Auto-created; tracks sent jobs
```

---

## 🚀 Setup (One-Time, ~10 Minutes)

### Step 1 — Create a Free GitHub Repository

1. Go to [github.com](https://github.com) and sign in (or create a free account)
2. Click **New repository**
3. Name it: `sacco-ict-jobs`
4. Set to **Private** (recommended — keeps your secrets safe)
5. Click **Create repository**

---

### Step 2 — Upload These Files

Upload all files maintaining the folder structure:
- `scraper.py` → root of repo
- `requirements.txt` → root of repo
- `.github/workflows/scraper.yml` → create the folders as shown

You can drag-and-drop files in the GitHub web interface.

---

### Step 3 — Get Your Free Kimi API Key

1. Go to [platform.moonshot.cn](https://platform.moonshot.cn)
2. Sign up for a free account
3. Go to **API Keys** → **Create API Key**
4. Copy the key (starts with `sk-...`)

> Kimi's free tier gives you enough tokens for hourly job validation.

---

### Step 4 — Set Up Gmail App Password (for sending emails)

> You need a **Gmail App Password** — NOT your regular Gmail password.

1. Go to [myaccount.google.com](https://myaccount.google.com)
2. Click **Security** → **2-Step Verification** (enable if not already)
3. Search for **App Passwords** at the top
4. Select app: **Mail**, device: **Other** → type `SACCOJobBot`
5. Click **Generate** → copy the 16-character password

---

### Step 5 — Add GitHub Secrets

In your GitHub repo:
1. Go to **Settings** → **Secrets and variables** → **Actions**
2. Click **New repository secret** for each of these:

| Secret Name        | Value                                      |
|--------------------|--------------------------------------------|
| `KIMI_API_KEY`     | Your Kimi API key (sk-...)                 |
| `SENDER_EMAIL`     | Your Gmail address (e.g. you@gmail.com)    |
| `SENDER_PASSWORD`  | The 16-char Gmail App Password             |
| `RECIPIENT_EMAIL`  | stevemburuligeve@gmail.com                 |

---

### Step 6 — Enable GitHub Actions

1. Go to the **Actions** tab in your repo
2. Click **I understand my workflows, go ahead and enable them**
3. The scraper now runs **automatically every hour**!

---

## ▶️ Test It Immediately

To run it right now without waiting an hour:
1. Go to **Actions** tab
2. Click **SACCO ICT Job Scraper** in the left sidebar
3. Click **Run workflow** → **Run workflow**
4. Watch the logs — you should get an email within 2 minutes!

---

## 📊 What the Excel Contains

| Column | Description |
|--------|-------------|
| # | Row number |
| Job Title | Full job title |
| Employer / Organisation | SACCO or organisation name |
| Deadline | Application closing date |
| Location | City/region in Kenya |
| Source | Which job board it came from |
| Date Found | When the bot found it |
| Link | Direct apply link |

---

## 🔍 Job Boards Scraped

- BrighterMonday Kenya
- MyJobMag Kenya
- Fuzu Kenya
- NGO Recruitment Kenya
- Career Point Kenya
- Jobs in Kenya

---

## 🤖 How Kimi AI Is Used

Each job listing passes through **two filters**:

1. **Keyword filter** — fast check for SACCO/ICT terms
2. **Kimi AI filter** — confirms the job is genuinely a SACCO ICT role in Kenya

This ensures you only receive relevant, high-quality listings.

---

## 📧 Email Behaviour

- Only **new** jobs (not seen before) trigger an email
- If no new jobs are found in a cycle, no email is sent (no spam!)
- Jobs are tracked to avoid duplicates across runs

---

## 💰 Cost

| Service | Cost |
|---------|------|
| GitHub Actions | **Free** (2,000 mins/month — more than enough) |
| Kimi AI | **Free tier** available |
| Gmail SMTP | **Free** |

**Total: KES 0 / month** 🎉

---

## ❓ Troubleshooting

**No email received?**
- Check the Actions tab for errors (red ✗)
- Verify your Gmail App Password is correct
- Check spam/junk folder

**Kimi API errors?**
- Verify your API key in GitHub Secrets
- Check your Kimi free tier quota at platform.moonshot.cn

**Too many/few jobs?**
- The scraper focuses on current-month deadlines only
- Some job boards may block scrapers — this is normal

---

*Built for Kenya's SACCO sector job seekers 🇰🇪*
