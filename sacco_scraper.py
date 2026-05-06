"""
SACCO ICT Job Scraper - Focused on working job boards
Scrapes MyJobMag ICT field and filters for SACCO jobs with valid deadlines.
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
from email.mime.text import MIMEText
from bs4 import BeautifulSoup

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL", "stevemburuligeve@gmail.com")
SENDER_EMAIL    = os.environ.get("SENDER_EMAIL")
SENDER_PASSWORD = os.environ.get("SENDER_PASSWORD")

SEEN_JOBS_FILE  = "seen_jobs.json"

# ── SACCO Keywords ───────────────────────────────────────────────────────────
SACCO_KEYWORDS = [
    "sacco", "savings and credit", "cooperative", "co-operative", "saccos",
    "credit union", "microfinance", "chama", "sacco society"
]

# ── Job Sources ──────────────────────────────────────────────────────────────
SEARCH_SOURCES = [
    {
        "name": "MyJobMag ICT Jobs",
        "url": "https://www.myjobmag.co.ke/jobs-by-field/information-technology",
        "base_url": "https://www.myjobmag.co.ke"
    },
    {
        "name": "MyJobMag SACCO Jobs",
        "url": "https://www.myjobmag.co.ke/jobs-by-field/saco",
        "base_url": "https://www.myjobmag.co.ke"
    }
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
}

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def load_seen_jobs():
    if os.path.exists(SEEN_JOBS_FILE):
        with open(SEEN_JOBS_FILE, 'r') as f:
            return json.load(f)
    return []

def save_seen_jobs(seen_jobs):
    with open(SEEN_JOBS_FILE, 'w') as f:
        json.dump(seen_jobs, f, indent=2)

def generate_job_id(job):
    content = f"{job['title']}-{job['employer']}-{job['link']}"
    return hashlib.md5(content.encode()).hexdigest()

def is_sacco_related(text):
    """Check if text contains SACCO-related keywords"""
    text_lower = text.lower()
    return any(keyword.lower() in text_lower for keyword in SACCO_KEYWORDS)

def extract_deadline(text):
    """Extract deadline from text"""
    if not text:
        return None
    
    current_date = date.today()
    current_year = current_date.year
    
    # Date patterns
    patterns = [
        r'(\d{1,2})\s*(?:st|nd|rd|th)?\s*(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*(\d{4})',
        r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*(\d{1,2})\s*,?\s*(\d{4})',
        r'(\d{1,2})/(\d{1,2})/(\d{4})',
        r'(\d{1,2})-(\d{1,2})-(\d{4})',
    ]
    
    month_map = {
        'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
        'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
    }
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                groups = match.groups()
                
                if len(groups) == 3:
                    # Handle different date formats
                    if groups[1].lower() in month_map:  # DD Month YYYY
                        day = int(groups[0])
                        month = month_map[groups[1].lower()[:3]]
                        year = int(groups[2])
                    elif groups[0].lower() in month_map:  # Month DD YYYY
                        month = month_map[groups[0].lower()[:3]]
                        day = int(groups[1])
                        year = int(groups[2])
                    else:  # DD/MM/YYYY or DD-MM-YYYY
                        day = int(groups[0])
                        month = int(groups[1])
                        year = int(groups[2])
                    
                    # Validate date is in current/future
                    job_date = date(year, month, day)
                    if job_date >= current_date or (current_date - job_date).days < 30:
                        return f"{day:02d}/{month:02d}/{year}"
            except:
                continue
    
    return None

def scrape_myjobmag(source):
    """Scrape jobs from MyJobMag"""
    jobs = []
    
    try:
        log.info(f"🔍 Fetching: {source['name']}")
        response = requests.get(source['url'], headers=HEADERS, timeout=20)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # MyJobMag job cards
        job_cards = soup.select('.job-list-item, .job-item, article.job, div.job-listing')
        
        if not job_cards:
            # Try alternative selectors
            job_cards = soup.select('li.job, .mag-b, .job-list-section')
        
        log.info(f"  → Found {len(job_cards)} job cards")
        
        for card in job_cards:
            try:
                # Extract title
                title_elem = (card.select_one('h2 a') or 
                             card.select_one('h3 a') or 
                             card.select_one('.job-title a') or
                             card.select_one('a[href*="/job/"]'))
                
                if not title_elem:
                    continue
                
                title = title_elem.get_text(strip=True)
                link = title_elem.get('href', '')
                
                # Make link absolute
                if link and not link.startswith('http'):
                    link = source['base_url'] + link
                
                # Extract employer
                employer_elem = (card.select_one('.company-name') or 
                                 card.select_one('.employer') or
                                 card.select_one('.job-company') or
                                 card.select_one('[class*="company"]') or
                                 card.select_one('span:not([class])'))
                
                employer = employer_elem.get_text(strip=True) if employer_elem else "Unknown"
                
                # Extract snippet/description
                snippet_elem = (card.select_one('.job-desc') or 
                               card.select_one('.job-summary') or
                               card.select_one('p') or
                               card.select_one('.description'))
                
                snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""
                
                # Check if SACCO-related
                full_text = f"{title} {employer} {snippet}"
                if not is_sacco_related(full_text):
                    continue  # Skip non-SACCO jobs
                
                # Extract deadline
                deadline_text = ""
                deadline_elem = (card.select_one('.deadline') or 
                                card.select_one('.job-deadline') or
                                card.select_one('[class*="date"]') or
                                card.select_one('[class*="deadline"]'))
                
                if deadline_elem:
                    deadline_text = deadline_elem.get_text(strip=True)
                
                deadline = extract_deadline(deadline_text) or extract_deadline(snippet)
                
                jobs.append({
                    'title': title,
                    'employer': employer,
                    'deadline': deadline or "Check application link",
                    'location': "Kenya",
                    'source': source['name'],
                    'link': link,
                    'snippet': snippet[:200] + "..." if len(snippet) > 200 else snippet
                })
                
                log.info(f"  ✅ SACCO Job: {title[:60]}...")
                
            except Exception as e:
                log.warning(f"  ⚠️ Error parsing job card: {e}")
                continue
        
    except Exception as e:
        log.error(f"❌ Error fetching {source['name']}: {e}")
    
    return jobs

def send_email(jobs):
    """Send email with job links"""
    if not jobs:
        log.info("No jobs to email")
        return
    
    try:
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = RECIPIENT_EMAIL
        msg['Subject'] = f"🏦 {len(jobs)} SACCO ICT Jobs Found - MyJobMag"
        
        body = "🏦 **SACCO ICT Jobs in Kenya**\n\n"
        body += f"Found {len(jobs)} relevant positions from MyJobMag:\n\n"
        
        for i, job in enumerate(jobs, 1):
            body += f"**{i}. {job['title']}**\n"
            body += f"🏢 {job['employer']}\n"
            body += f"📍 {job['location']}\n"
            body += f"🗓️ Deadline: {job['deadline']}\n"
            body += f"🔗 Apply: {job['link']}\n"
            if job['snippet']:
                body += f"📝 {job['snippet'][:100]}...\n"
            body += "\n" + "="*50 + "\n\n"
        
        body += "---\n"
        body += "🤖 Generated by SACCO ICT Job Scraper\n"
        body += "⏰ Auto-checks every hour for new SACCO ICT positions\n"
        
        msg.attach(MIMEText(body, 'plain'))
        
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.send_message(msg)
        server.quit()
        
        log.info(f"✅ Email sent with {len(jobs)} SACCO ICT jobs")
        
    except Exception as e:
        log.error(f"❌ Email sending failed: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def is_deadline_valid(deadline_str):
    """Check if job deadline is still valid (not expired)"""
    if not deadline_str or deadline_str == "Check application link":
        return True  # Assume valid if deadline unknown
    
    try:
        # Parse various date formats
        current_date = date.today()
        
        # Try DD/MM/YYYY format
        if '/' in deadline_str:
            parts = deadline_str.split('/')
            if len(parts) == 3:
                day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
                deadline_date = date(year, month, day)
                return deadline_date >= current_date
        
        return True  # Assume valid if can't parse
    except:
        return True  # Assume valid on error

def main():
    log.info("🚀 Starting SACCO ICT Job Scraper (MyJobMag Focus)")
    
    seen_jobs = load_seen_jobs()
    seen_job_map = {job['id']: job for job in seen_jobs}  # Map by ID for quick lookup
    jobs_to_email = []
    all_found_jobs = []
    
    for source in SEARCH_SOURCES:
        jobs = scrape_myjobmag(source)
        
        for job in jobs:
            job_id = generate_job_id(job)
            job['id'] = job_id
            all_found_jobs.append(job)
            
            # Check if we've seen this job before
            if job_id in seen_job_map:
                # Already seen - check if deadline still valid
                seen_job = seen_job_map[job_id]
                if is_deadline_valid(job.get('deadline')):
                    # Job still active, include it
                    log.info(f"  🔄 Including (still active): {job['title'][:50]}...")
                    jobs_to_email.append(job)
                else:
                    log.info(f"  ⏭️ Skipping (deadline expired): {job['title'][:50]}...")
            else:
                # New job - always include
                log.info(f"  ✨ New job: {job['title'][:50]}...")
                job['first_seen'] = datetime.now().strftime("%Y-%m-%d %H:%M")
                jobs_to_email.append(job)
    
    if jobs_to_email:
        # Remove duplicates (keep latest version)
        unique_jobs = {}
        for job in jobs_to_email:
            unique_jobs[job['id']] = job
        jobs_to_email = list(unique_jobs.values())
        
        log.info(f"📧 Sending email with {len(jobs_to_email)} SACCO ICT jobs")
        send_email(jobs_to_email)
        
        # Update seen jobs with all found jobs
        for job in all_found_jobs:
            if job['id'] not in seen_job_map:
                seen_jobs.append(job)
        save_seen_jobs(seen_jobs)
        
        # Save to Excel
        try:
            df = pd.DataFrame(jobs_to_email)
            df.to_excel("sacco_ict_jobs.xlsx", index=False)
            log.info("📊 Saved jobs to sacco_ict_jobs.xlsx")
        except Exception as e:
            log.warning(f"Could not save Excel: {e}")
        
    else:
        log.info("📭 No SACCO ICT jobs found (or all deadlines expired)")

if __name__ == "__main__":
    main()
