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
from email.mime.base import MIMEBase
from email import encoders
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
# Will scrape pages 1-10 for each source
SEARCH_SOURCES = [
    {
        "name": "MyJobMag ICT Jobs",
        "base_url": "https://www.myjobmag.co.ke",
        "url_template": "https://www.myjobmag.co.ke/jobs-by-field/information-technology/{page}",
        "max_pages": 10
    },
    {
        "name": "MyJobMag SACCO Jobs", 
        "base_url": "https://www.myjobmag.co.ke",
        "url_template": "https://www.myjobmag.co.ke/jobs-by-field/saco/{page}",
        "max_pages": 10
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

def get_job_details(job_url):
    """Visit individual job page and extract full details"""
    try:
        log.info(f"    � Visiting job page: {job_url[:60]}...")
        response = requests.get(job_url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Extract job title
        title = "Unknown"
        title_elem = (soup.select_one('h1') or 
                     soup.select_one('h2.job-title') or
                     soup.select_one('.job-title') or
                     soup.select_one('h2'))
        if title_elem:
            title = title_elem.get_text(strip=True)
        
        # Extract employer/company
        employer = "Unknown"
        employer_elem = (soup.select_one('.company-name') or
                        soup.select_one('.employer') or
                        soup.select_one('[class*="company"]') or
                        soup.select_one('h3'))
        if employer_elem:
            employer = employer_elem.get_text(strip=True)
        
        # Extract full job description
        description = ""
        desc_elem = (soup.select_one('.job-description') or
                    soup.select_one('.description') or
                    soup.select_one('[class*="desc"]') or
                    soup.select_one('article') or
                    soup.select_one('.content'))
        if desc_elem:
            description = desc_elem.get_text(strip=True)
        
        # Extract deadline from page
        deadline = None
        deadline_patterns = [
            r'(?:deadline|closing date|apply by)[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
            r'(?:deadline|closing date|apply by)[:\s]*(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})',
            r'(?:deadline|closing date|apply by)[:\s]*((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4})',
        ]
        
        page_text = soup.get_text()
        for pattern in deadline_patterns:
            match = re.search(pattern, page_text, re.IGNORECASE)
            if match:
                deadline = match.group(1)
                break
        
        # Check if SACCO-related from full page content
        is_sacco = is_sacco_related(f"{title} {employer} {description}".lower())
        
        return {
            'title': title,
            'employer': employer,
            'description': description[:500] + "..." if len(description) > 500 else description,
            'deadline': deadline or "Check job page",
            'is_sacco': is_sacco
        }
        
    except Exception as e:
        log.warning(f"    ⚠️ Error visiting job page: {e}")
        return None

def scrape_page(source, page_num):
    """Scrape a single page for job links"""
    job_links = []
    
    try:
        # Build URL with page number
        # MyJobMag uses: /jobs-by-field/information-technology/ for page 1
        # and /jobs-by-field/information-technology/2/ for page 2, etc.
        if page_num == 1:
            # First page - use base URL without page number
            url = source['url_template'].replace("/{page}", "")
        else:
            # Pages 2+ - add page number
            url = source['url_template'].format(page=page_num)
        
        log.info(f"  📄 Fetching page {page_num}: {url[:80]}...")
        response = requests.get(url, headers=HEADERS, timeout=20)
        
        if response.status_code == 404:
            log.info(f"    ⚠️ Page {page_num} not found (end of results)")
            return job_links, False  # No more pages
        
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Find all job links on the page
        page_job_count = 0
        for link in soup.select('a[href*="/job/"]'):
            href = link.get('href', '')
            if href and '/job/' in href:
                # Make absolute URL
                if not href.startswith('http'):
                    href = source['base_url'] + href
                # Remove duplicates
                if href not in [j['link'] for j in job_links]:
                    job_links.append({'link': href, 'title': link.get_text(strip=True)})
                    page_job_count += 1
        
        log.info(f"    → Found {page_job_count} jobs on page {page_num}")
        
        # Check if page has jobs or if we've reached the end
        if page_job_count == 0:
            return job_links, False  # No more pages
        
        return job_links, True  # More pages may exist
        
    except Exception as e:
        log.warning(f"    ⚠️ Error fetching page {page_num}: {e}")
        return job_links, False

def scrape_myjobmag(source):
    """Scrape jobs from MyJobMag - get links from listing pages 1-10, details from job pages"""
    all_job_links = []
    jobs = []
    
    log.info(f"🔍 Scraping {source['name']} (up to {source['max_pages']} pages)")
    
    # Collect job links from all pages
    for page_num in range(1, source['max_pages'] + 1):
        page_links, has_more = scrape_page(source, page_num)
        all_job_links.extend(page_links)
        
        if not has_more:
            log.info(f"  🛑 Stopping at page {page_num} (no more results)")
            break
    
    # Remove duplicates across all pages
    unique_links = []
    seen_urls = set()
    for job_info in all_job_links:
        if job_info['link'] not in seen_urls:
            unique_links.append(job_info)
            seen_urls.add(job_info['link'])
    
    log.info(f"  📊 Total unique jobs found: {len(unique_links)} from {source['max_pages']} pages")
    
    if not unique_links:
        log.warning(f"  ⚠️ No job links found across all pages!")
        return jobs
    
    sacco_jobs_found = 0
    
    # Visit each job page to get details (limit to first 30 to avoid timeouts)
    for job_info in unique_links[:30]:
        try:
            # Get full details from job page
            details = get_job_details(job_info['link'])
            
            if not details:
                continue
            
            if not details['is_sacco']:
                log.info(f"  ⏭️ SKIPPED (not SACCO): {details['title'][:50]}...")
                continue
            
            sacco_jobs_found += 1
            log.info(f"  ✅ SACCO JOB #{sacco_jobs_found}: {details['title'][:50]}...")
            
            jobs.append({
                'title': details['title'],
                'employer': details['employer'],
                'deadline': details['deadline'],
                'location': "Kenya",
                'source': source['name'],
                'link': job_info['link'],
                'snippet': details['description']
            })
            
        except Exception as e:
            log.warning(f"  ⚠️ Error processing job: {e}")
            continue
    
    log.info(f"  📊 FINAL SUMMARY: {sacco_jobs_found} SACCO jobs from {len(unique_links)} total jobs")
    
    return jobs

def send_email(jobs, excel_filename=None):
    """Send email with job links and Excel attachment"""
    if not jobs:
        log.info("No jobs to email")
        return
    
    try:
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = RECIPIENT_EMAIL
        msg['Subject'] = f"🏦 {len(jobs)} SACCO ICT Jobs - {datetime.now().strftime('%B %Y')}"
        
        body = "🏦 **SACCO ICT Jobs in Kenya**\n\n"
        body += f"📅 Found {len(jobs)} new SACCO ICT positions:\n\n"
        
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
        body += "📎 Excel file attached with full details\n"
        
        msg.attach(MIMEText(body, 'plain'))
        
        # Attach Excel file if it exists
        if excel_filename and os.path.exists(excel_filename):
            with open(excel_filename, 'rb') as f:
                excel_attachment = MIMEBase('application', 'octet-stream')
                excel_attachment.set_payload(f.read())
                encoders.encode_base64(excel_attachment)
                excel_attachment.add_header(
                    'Content-Disposition',
                    f'attachment; filename= {os.path.basename(excel_filename)}'
                )
                msg.attach(excel_attachment)
            log.info(f"📎 Attached Excel: {excel_filename}")
        
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

def get_current_month_year():
    """Get current month and year as string"""
    now = datetime.now()
    return f"{now.year}-{now.month:02d}"

def load_sent_jobs():
    """Load list of jobs already sent this month"""
    current_month = get_current_month_year()
    sent_file = f"sent_jobs_{current_month}.json"
    
    if os.path.exists(sent_file):
        with open(sent_file, 'r') as f:
            return set(json.load(f))  # Return set of job IDs
    return set()

def save_sent_jobs(sent_job_ids):
    """Save list of jobs sent this month"""
    current_month = get_current_month_year()
    sent_file = f"sent_jobs_{current_month}.json"
    
    with open(sent_file, 'w') as f:
        json.dump(list(sent_job_ids), f)

def is_posted_this_month(job):
    """Check if job was posted in current month (or assume yes if unknown)"""
    # For now, assume all found jobs are current since MyJobMag shows current listings
    # Could be enhanced to parse actual posting dates if available in HTML
    return True

def main():
    log.info("🚀 Starting SACCO ICT Job Scraper (MyJobMag Focus)")
    
    current_month_year = get_current_month_year()
    log.info(f"📅 Current month: {current_month_year}")
    
    # Load jobs already sent this month
    sent_job_ids = load_sent_jobs()
    log.info(f"📧 Already sent this month: {len(sent_job_ids)} jobs")
    
    # Load all previously seen jobs
    seen_jobs = load_seen_jobs()
    seen_job_ids = {job['id'] for job in seen_jobs}
    
    jobs_to_email = []
    new_jobs_found = []
    
    for source in SEARCH_SOURCES:
        jobs = scrape_myjobmag(source)
        
        for job in jobs:
            job_id = generate_job_id(job)
            job['id'] = job_id
            
            # Check if already sent this month
            if job_id in sent_job_ids:
                log.info(f"  ⏭️ Already sent this month: {job['title'][:50]}...")
                continue
            
            # Check if posted in current month
            if not is_posted_this_month(job):
                log.info(f"  ⏭️ Not current month: {job['title'][:50]}...")
                continue
            
            # New job to send
            log.info(f"  ✨ New job to send: {job['title'][:50]}...")
            job['found_date'] = datetime.now().strftime("%Y-%m-%d %H:%M")
            jobs_to_email.append(job)
            sent_job_ids.add(job_id)
            
            # Track if this is truly new (never seen before)
            if job_id not in seen_job_ids:
                new_jobs_found.append(job)
    
    if jobs_to_email:
        # Save to Excel FIRST (before sending email)
        excel_filename = f"sacco_ict_jobs_{current_month_year}.xlsx"
        try:
            df = pd.DataFrame(jobs_to_email)
            # Select and order columns nicely
            columns = ['title', 'employer', 'deadline', 'location', 'link', 'source', 'snippet']
            df = df[[col for col in columns if col in df.columns]]
            df.to_excel(excel_filename, index=False, engine='openpyxl')
            log.info(f"📊 Saved {len(jobs_to_email)} jobs to {excel_filename}")
        except Exception as e:
            log.warning(f"Could not save Excel: {e}")
            excel_filename = None
        
        # Send email with Excel attachment
        log.info(f"📧 Sending email with {len(jobs_to_email)} new SACCO ICT jobs")
        send_email(jobs_to_email, excel_filename)
        
        # Save updated sent jobs list
        save_sent_jobs(sent_job_ids)
        
        # Update seen jobs with truly new jobs
        for job in new_jobs_found:
            seen_jobs.append(job)
        save_seen_jobs(seen_jobs)
        
    else:
        log.info(f"📭 No new SACCO ICT jobs to send (already sent {len(sent_job_ids)} this month)")

if __name__ == "__main__":
    main()
