"""
SACCO ICT Job Scraper for Kenya
Scrapes multiple job boards, filters SACCO ICT jobs with deadlines in current month,
uses Kimi AI to validate relevance, generates Excel, and emails results.
"""

import os
import re
import json
import smtplib
import logging
import hashlib
import requests
import pandas as pd
from datetime import datetime, date
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from bs4 import BeautifulSoup
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL", "stevemburuligeve@gmail.com")
SENDER_EMAIL    = os.environ.get("SENDER_EMAIL")        # Gmail address
SENDER_PASSWORD = os.environ.get("SENDER_PASSWORD")     # Gmail App Password
KIMI_API_KEY    = os.environ.get("KIMI_API_KEY")        # Moonshot AI key

KIMI_API_URL    = "https://api.moonshot.cn/v1/chat/completions"
KIMI_MODEL      = "moonshot-v1-8k"

SEEN_JOBS_FILE  = "seen_jobs.json"   # persisted via GitHub Actions cache

# ── SACCO / ICT keywords ──────────────────────────────────────────────────────
SACCO_KEYWORDS = [
    "sacco", "savings and credit", "cooperative", "co-operative", "saccos",
    "credit union", "microfinance", "chama"
]
ICT_KEYWORDS = [
    "ict", "it officer", "information technology", "systems administrator",
    "software", "developer", "programmer", "database", "network", "cybersecurity",
    "core banking", "tech support", "helpdesk", "data analyst", "web developer",
    "infrastructure", "cloud", "fintech", "digital", "erp", "mis officer"
]

# ── Job board search URLs ─────────────────────────────────────────────────────
SEARCH_SOURCES = [
    {
        "name": "BrighterMonday Kenya",
        "url": "https://www.brightermonday.co.ke/jobs/information-technology",
        "type": "brightermonday"
    },
    {
        "name": "MyJobMag Kenya",
        "url": "https://www.myjobmag.co.ke/jobs-by-field/information-technology",
        "type": "myjobmag"
    },
    {
        "name": "Fuzu Kenya",
        "url": "https://www.fuzu.com/kenya/jobs?industry=Information+Technology",
        "type": "fuzu"
    },
    # {
    #     "name": "NGO Recruitment Kenya",
    #     "url": "https://ngorecruitment.org/category/ict/",
    #     "type": "ngorecruitment"
    # },
    # {
    #     "name": "Career Point Kenya",
    #     "url": "https://careerpointkenya.co.ke/?s=sacco+ict",
    #     "type": "generic"
    # },
    # {
    #     "name": "Jobs in Kenya",
    #     "url": "https://www.jobsinkenya.co.ke/search/?q=sacco+ict",
    #     "type": "generic"
    # },
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def load_seen_jobs():
    if os.path.exists(SEEN_JOBS_FILE):
        with open(SEEN_JOBS_FILE) as f:
            return set(json.load(f))
    return set()


def save_seen_jobs(seen: set):
    with open(SEEN_JOBS_FILE, "w") as f:
        json.dump(list(seen), f)


def job_id(job: dict) -> str:
    key = f"{job.get('title','')}{job.get('link','')}"
    return hashlib.md5(key.encode()).hexdigest()


def deadline_in_current_month(deadline_str: str) -> bool:
    """Return True if deadline is within the current calendar month and not yet passed."""
    if not deadline_str or deadline_str.lower() in ("n/a", "not specified", "ongoing", ""):
        return False
    now = datetime.now()
    for fmt in ("%d %B %Y", "%B %d, %Y", "%d/%m/%Y", "%Y-%m-%d",
                "%d-%m-%Y", "%d %b %Y", "%b %d, %Y"):
        try:
            d = datetime.strptime(deadline_str.strip(), fmt)
            return d.year == now.year and d.month == now.month and d.date() >= now.date()
        except ValueError:
            continue
    # fallback: look for month name in string
    month_name = now.strftime("%B").lower()
    short_name = now.strftime("%b").lower()
    year_str   = str(now.year)
    dl_lower   = deadline_str.lower()
    if (month_name in dl_lower or short_name in dl_lower) and year_str in dl_lower:
        return True
    return False


def quick_keyword_match(text: str) -> bool:
    """Fast pre-filter before calling Kimi."""
    t = text.lower()
    has_sacco = any(k in t for k in SACCO_KEYWORDS)
    has_ict   = any(k in t for k in ICT_KEYWORDS)
    return has_sacco or has_ict


# ─────────────────────────────────────────────────────────────────────────────
# Kimi AI validation
# ─────────────────────────────────────────────────────────────────────────────

def kimi_validate(job: dict) -> bool:
    """Ask Kimi whether this job is genuinely SACCO-ICT related in Kenya."""
    if not KIMI_API_KEY:
        # Fallback to keyword-only matching if no API key
        return quick_keyword_match(f"{job.get('title','')} {job.get('description','')}")

    prompt = f"""You are a job relevance classifier for a Kenyan SACCO ICT job alert system.

A SACCO (Savings and Credit Cooperative) ICT job means:
- The employer is a SACCO, cooperative, credit union, or similar financial cooperative in Kenya
- OR the role is an ICT/IT role (software, systems, network, data, core banking, helpdesk, etc.) 
  at any Kenyan financial cooperative organisation.

Job details:
Title: {job.get('title', '')}
Employer: {job.get('employer', '')}
Description: {job.get('description', '')[:500]}

Reply with ONLY "YES" if this qualifies, or "NO" if it does not. No explanation."""

    try:
        resp = requests.post(
            KIMI_API_URL,
            headers={"Authorization": f"Bearer {KIMI_API_KEY}", "Content-Type": "application/json"},
            json={"model": KIMI_MODEL, "max_tokens": 5,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=15
        )
        resp.raise_for_status()
        answer = resp.json()["choices"][0]["message"]["content"].strip().upper()
        return answer.startswith("YES")
    except Exception as e:
        log.warning(f"Kimi API error: {e} — falling back to keyword match")
        return quick_keyword_match(f"{job.get('title','')} {job.get('description','')}")


# ─────────────────────────────────────────────────────────────────────────────
# Scrapers per board
# ─────────────────────────────────────────────────────────────────────────────

def parse_generic(soup, source_name, source_url) -> list:
    jobs = []
    for card in soup.select("article, .job-listing, .job-item, .job_listing, li.job"):
        title_el  = card.select_one("h2, h3, .job-title, .position, a[href*='job']")
        link_el   = card.select_one("a[href]")
        employer_el = card.select_one(".company, .employer, .organisation")
        deadline_el = card.select_one(".deadline, .closing, .expiry, time")
        if not title_el:
            continue
        jobs.append({
            "title":       title_el.get_text(strip=True),
            "employer":    employer_el.get_text(strip=True) if employer_el else "N/A",
            "deadline":    deadline_el.get_text(strip=True) if deadline_el else "N/A",
            "location":    "Kenya",
            "link":        link_el["href"] if link_el else source_url,
            "source":      source_name,
            "description": card.get_text(" ", strip=True)[:300],
        })
    return jobs


def scrape_brightermonday(soup, source_name, source_url) -> list:
    jobs = []
    for card in soup.select("div[class*='JobSearch'], article[class*='job']"):
        title_el    = card.select_one("h3, h2, [class*='title']")
        employer_el = card.select_one("[class*='company'], [class*='employer']")
        deadline_el = card.select_one("[class*='deadline'], [class*='date'], time")
        link_el     = card.select_one("a[href]")
        if not title_el:
            continue
        href = link_el["href"] if link_el else ""
        if href and not href.startswith("http"):
            href = "https://www.brightermonday.co.ke" + href
        jobs.append({
            "title":       title_el.get_text(strip=True),
            "employer":    employer_el.get_text(strip=True) if employer_el else "N/A",
            "deadline":    deadline_el.get_text(strip=True) if deadline_el else "N/A",
            "location":    "Kenya",
            "link":        href,
            "source":      source_name,
            "description": card.get_text(" ", strip=True)[:300],
        })
    return jobs


def scrape_myjobmag(soup, source_name, source_url) -> list:
    jobs = []
    for card in soup.select(".job-listing-section, .job-list-item, article"):
        title_el    = card.select_one("h2 a, h3 a, .job-title a")
        employer_el = card.select_one(".company-name, .recruiter")
        deadline_el = card.select_one(".closing-date, .deadline, time")
        if not title_el:
            continue
        href = title_el.get("href", "")
        if href and not href.startswith("http"):
            href = "https://www.myjobmag.co.ke" + href
        jobs.append({
            "title":       title_el.get_text(strip=True),
            "employer":    employer_el.get_text(strip=True) if employer_el else "N/A",
            "deadline":    deadline_el.get_text(strip=True) if deadline_el else "N/A",
            "location":    "Kenya",
            "link":        href,
            "source":      source_name,
            "description": card.get_text(" ", strip=True)[:300],
        })
    return jobs


SCRAPER_MAP = {
    "brightermonday": scrape_brightermonday,
    "myjobmag":       scrape_myjobmag,
    "fuzu":           parse_generic,
    "ngorecruitment": parse_generic,
    "generic":        parse_generic,
}


def fetch_jobs_from_source(source: dict) -> list:
    log.info(f"Fetching: {source['name']}")
    try:
        resp = requests.get(source["url"], headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        scraper = SCRAPER_MAP.get(source["type"], parse_generic)
        jobs = scraper(soup, source["name"], source["url"])
        log.info(f"  → {len(jobs)} raw listings found")
        return jobs
    except Exception as e:
        log.warning(f"  ✗ Failed to fetch {source['name']}: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Excel generation
# ─────────────────────────────────────────────────────────────────────────────

def build_excel(jobs: list, filepath: str):
    wb = Workbook()
    ws = wb.active
    ws.title = "SACCO ICT Jobs"

    # Palette
    DARK_TEAL   = "1A3C5E"
    MID_TEAL    = "2E7D9B"
    LIGHT_BLUE  = "D6EAF8"
    ACCENT      = "F0A500"
    WHITE       = "FFFFFF"
    GREY_ROW    = "F2F6FA"

    thin = Side(style="thin", color="BBCCDD")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    # ── Title row ──
    ws.merge_cells("A1:H1")
    title_cell = ws["A1"]
    title_cell.value = f"🏦 SACCO ICT Job Alerts — Kenya  |  {datetime.now().strftime('%B %Y')}"
    title_cell.font      = Font(name="Calibri", bold=True, size=15, color=WHITE)
    title_cell.fill      = PatternFill("solid", fgColor=DARK_TEAL)
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 36

    # ── Sub-header ──
    ws.merge_cells("A2:H2")
    sub = ws["A2"]
    sub.value = f"Generated: {datetime.now().strftime('%d %b %Y %H:%M')} EAT  |  Jobs: {len(jobs)}  |  Deadline: within {datetime.now().strftime('%B %Y')}"
    sub.font      = Font(name="Calibri", italic=True, size=10, color=WHITE)
    sub.fill      = PatternFill("solid", fgColor=MID_TEAL)
    sub.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[2].height = 20

    # ── Column headers ──
    headers = ["#", "Job Title", "Employer / Organisation", "Deadline", "Location", "Source", "Date Found", "Link"]
    col_widths = [5, 40, 35, 18, 18, 22, 15, 55]
    for col_idx, (h, w) in enumerate(zip(headers, col_widths), start=1):
        cell = ws.cell(row=3, column=col_idx, value=h)
        cell.font      = Font(name="Calibri", bold=True, size=11, color=WHITE)
        cell.fill      = PatternFill("solid", fgColor=ACCENT)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border    = border
        ws.column_dimensions[get_column_letter(col_idx)].width = w
    ws.row_dimensions[3].height = 22

    # ── Data rows ──
    for i, job in enumerate(jobs, start=1):
        row = i + 3
        fill_color = GREY_ROW if i % 2 == 0 else WHITE
        row_data = [
            i,
            job.get("title", ""),
            job.get("employer", "N/A"),
            job.get("deadline", "N/A"),
            job.get("location", "Kenya"),
            job.get("source", ""),
            datetime.now().strftime("%d %b %Y"),
            job.get("link", ""),
        ]
        for col_idx, value in enumerate(row_data, start=1):
            cell = ws.cell(row=row, column=col_idx, value=value)
            cell.font      = Font(name="Calibri", size=10)
            cell.fill      = PatternFill("solid", fgColor=fill_color)
            cell.alignment = Alignment(vertical="center", wrap_text=(col_idx == 2))
            cell.border    = border
            if col_idx == 8 and value:  # Hyperlink column
                cell.hyperlink = value
                cell.font  = Font(name="Calibri", size=10, color="1155CC", underline="single")
                cell.value = "Apply Here →"
        ws.row_dimensions[row].height = 20

    # ── Freeze panes & auto-filter ──
    ws.freeze_panes = "A4"
    ws.auto_filter.ref = f"A3:H{3 + len(jobs)}"

    # ── Footer ──
    footer_row = len(jobs) + 5
    ws.merge_cells(f"A{footer_row}:H{footer_row}")
    footer = ws.cell(row=footer_row, column=1,
                     value="⚡ Auto-generated by SACCO ICT Job Bot — runs every hour via GitHub Actions")
    footer.font      = Font(name="Calibri", italic=True, size=9, color="888888")
    footer.alignment = Alignment(horizontal="center")

    wb.save(filepath)
    log.info(f"Excel saved → {filepath}")


# ─────────────────────────────────────────────────────────────────────────────
# Email sender
# ─────────────────────────────────────────────────────────────────────────────

def send_email(filepath: str, job_count: int):
    if not SENDER_EMAIL or not SENDER_PASSWORD:
        log.error("SENDER_EMAIL / SENDER_PASSWORD not set — skipping email.")
        return

    subject = (
        f"[SACCO ICT Jobs] {job_count} New Listing{'s' if job_count != 1 else ''} "
        f"— {datetime.now().strftime('%d %b %Y %H:%M')}"
    )
    body = f"""Hello,

Your hourly SACCO ICT job scan has found {job_count} relevant listing(s) in Kenya 
with deadlines in {datetime.now().strftime('%B %Y')}.

Please find the attached Excel file for full details.

Job categories covered:
• ICT/IT roles at SACCOs and cooperatives
• Core banking & fintech positions
• Systems administration at financial cooperatives
• Data & network roles in the SACCO sector

---
This alert is generated automatically every hour.
Only jobs with unexpired deadlines in the current month are included.

Best regards,
SACCO ICT Job Bot 🤖
"""

    msg = MIMEMultipart()
    msg["From"]    = SENDER_EMAIL
    msg["To"]      = RECIPIENT_EMAIL
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    with open(filepath, "rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="{os.path.basename(filepath)}"')
    msg.attach(part)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, RECIPIENT_EMAIL, msg.as_string())

    log.info(f"Email sent to {RECIPIENT_EMAIL}")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    log.info("═" * 60)
    log.info("SACCO ICT Job Scraper starting …")
    log.info(f"Target month: {datetime.now().strftime('%B %Y')}")

    seen_jobs = load_seen_jobs()
    all_raw   = []

    # 1. Collect from all sources
    for source in SEARCH_SOURCES:
        all_raw.extend(fetch_jobs_from_source(source))

    log.info(f"Total raw listings collected: {len(all_raw)}")

    # 2. Pre-filter by keywords
    keyword_filtered = [j for j in all_raw if quick_keyword_match(
        f"{j.get('title','')} {j.get('employer','')} {j.get('description','')}")]
    log.info(f"After keyword filter: {len(keyword_filtered)}")

    # 3. Filter by deadline (current month, not expired)
    deadline_filtered = [j for j in keyword_filtered if deadline_in_current_month(j.get("deadline", ""))]
    # Also keep jobs with no deadline info but still keyword-matched (fallback)
    no_deadline = [j for j in keyword_filtered
                   if not deadline_in_current_month(j.get("deadline", ""))
                   and j.get("deadline", "").strip() in ("", "N/A", "Not specified")]
    # Only use no-deadline jobs if we have fewer than 3 confirmed ones
    if len(deadline_filtered) < 3:
        deadline_filtered += no_deadline[:10]

    log.info(f"After deadline filter: {len(deadline_filtered)}")

    # 4. Deduplicate against seen jobs
    new_jobs = [j for j in deadline_filtered if job_id(j) not in seen_jobs]
    log.info(f"New (unseen) jobs: {len(new_jobs)}")

    if not new_jobs:
        log.info("No new jobs found this cycle — skipping Excel & email.")
        return

    # 5. Kimi AI validation
    log.info("Running Kimi AI validation …")
    validated = []
    for job in new_jobs:
        if kimi_validate(job):
            validated.append(job)
            seen_jobs.add(job_id(job))

    log.info(f"Validated by Kimi: {len(validated)}")

    if not validated:
        log.info("Kimi filtered out all listings — nothing to send.")
        save_seen_jobs(seen_jobs)
        return

    # 6. Build Excel
    ts       = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"sacco_ict_jobs_{ts}.xlsx"
    build_excel(validated, filename)

    # 7. Send email
    send_email(filename, len(validated))

    # 8. Persist seen jobs
    save_seen_jobs(seen_jobs)

    log.info(f"Done. {len(validated)} job(s) sent to {RECIPIENT_EMAIL}")
    log.info("═" * 60)


if __name__ == "__main__":
    main()
