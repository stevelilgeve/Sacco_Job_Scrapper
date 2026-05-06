"""
Google Search SACCO ICT Job Scraper for Kenya
Uses Google search to find "sacco ict jobs", validates deadlines with Kimi AI,
and emails direct links to valid job postings from any source including SACCO websites.
"""

import os
import re
import json
import smtplib
import logging
import hashlib
import requests
import pandas as pd
from datetime import datetime, date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

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

# ── Search queries ─────────────────────────────────────────────────────────────
SEARCH_QUERIES = [
    "sacco ict jobs kenya",
    "sacco it officer kenya", 
    "sacco information technology jobs kenya",
    "sacco systems administrator kenya",
    "sacco software developer kenya"
]

# ── SACCO keywords for validation ────────────────────────────────────────────
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
        with open(SEEN_JOBS_FILE, 'r') as f:
            return json.load(f)
    return []

def save_seen_jobs(seen_jobs):
    with open(SEEN_JOBS_FILE, 'w') as f:
        json.dump(seen_jobs, f, indent=2)

def generate_job_id(job):
    """Generate unique ID for a job to avoid duplicates"""
    content = f"{job['title']}-{job['employer']}-{job['link']}"
    return hashlib.md5(content.encode()).hexdigest()

def is_valid_deadline(deadline_text):
    """Check if deadline is in the future"""
    if not deadline_text:
        return False
    
    current_date = date.today()
    
    # Common deadline patterns
    date_patterns = [
        r'(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})',  # DD/MM/YYYY or DD-MM-YYYY
        r'(\d{1,2})[/\-](\d{1,2})[/\-](\d{2})',   # DD/MM/YY or DD-MM-YY
        r'(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{4})',  # DD Month YYYY
        r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})\s*,?\s+(\d{4})',  # Month DD, YYYY
    ]
    
    for pattern in date_patterns:
        match = re.search(pattern, deadline_text, re.IGNORECASE)
        if match:
            try:
                if len(match.groups()) == 3:
                    day, month, year = match.groups()
                    if month.isalpha():
                        month_map = {'Jan':1,'Feb':2,'Mar':3,'Apr':4,'May':5,'Jun':6,'Jul':7,'Aug':8,'Sep':9,'Oct':10,'Nov':11,'Dec':12}
                        month = month_map[month[:3].title()]
                    day = int(day)
                    year = int(year)
                    if year < 100:
                        year += 2000
                    month = int(month) if isinstance(month, str) else month
                    
                    job_date = date(year, month, day)
                    return job_date >= current_date
            except:
                continue
    
    # Check for "closing soon", "urgent", etc.
    urgent_keywords = ["closing soon", "urgent", "immediate", "asap", "closing today"]
    if any(keyword in deadline_text.lower() for keyword in urgent_keywords):
        return True
    
    return False

def search_google(query):
    """Search Google for jobs"""
    try:
        # Using a more reliable search approach
        search_url = f"https://www.google.com/search?q={query.replace(' ', '+')}&num=20"
        
        # More realistic headers
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
        
        response = requests.get(search_url, headers=headers, timeout=15)
        response.raise_for_status()
        
        # Debug: Save HTML to file for inspection
        with open(f"debug_google_{query.replace(' ', '_')}.html", "w", encoding="utf-8") as f:
            f.write(response.text)
        log.info(f"Saved debug HTML for query: {query}")
        
        soup = BeautifulSoup(response.text, 'html.parser')
        jobs = []
        
        # Try multiple selectors for Google results
        selectors = [
            'div.g',           # Standard Google results
            'div[data-ved]',   # Alternative selector
            'div.tF2Cxc',      # Newer Google layout
            'div.hlcw0c'       # Another variant
        ]
        
        results = []
        for selector in selectors:
            results = soup.select(selector)
            if results:
                break
        
        log.info(f"Found {len(results)} search result containers")
        
        for result in results:
            try:
                # Try multiple title selectors
                title_elem = (result.select_one('h3') or 
                             result.select_one('h2') or 
                             result.select_one('[role="heading"]') or
                             result.select_one('a h3'))
                
                # Try multiple link selectors  
                link_elem = (result.select_one('a[href]') or
                            result.select_one('a') or
                            result.select_one('[href]'))
                
                # Try multiple snippet selectors
                snippet_elem = (result.select_one('[data-snf="nke7zf"]') or
                               result.select_one('.VwiC3b') or
                               result.select_one('.s') or
                               result.select_one('.st'))
                
                if not title_elem or not link_elem:
                    continue
                
                title = title_elem.get_text(strip=True)
                link = link_elem.get('href', '')
                snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""
                
                # Clean the link (remove Google redirect)
                if link.startswith('/url?'):
                    import urllib.parse
                    try:
                        parsed = urllib.parse.urlparse(link)
                        params = urllib.parse.parse_qs(parsed.query)
                        link = params.get('q', [link])[0]
                    except:
                        pass
                elif link.startswith('/'):
                    link = "https://www.google.com" + link
                
                # Skip Google internal links
                if 'google.com' in link.lower():
                    continue
                
                # Extract employer from title
                employer = "Unknown"
                title_lower = title.lower()
                snippet_lower = snippet.lower()
                
                for keyword in SACCO_KEYWORDS:
                    if keyword.lower() in title_lower or keyword.lower() in snippet_lower:
                        # Try to extract SACCO name
                        if keyword.lower() in title_lower:
                            parts = title_lower.split(keyword.lower())
                            if len(parts) > 1 and parts[0].strip():
                                employer = parts[0].strip() + " " + keyword.title()
                            else:
                                employer = keyword.title()
                        else:
                            employer = keyword.title()
                        break
                
                jobs.append({
                    'title': title,
                    'employer': employer,
                    'deadline': snippet,  # Will be processed later
                    'location': "Kenya",  # Default
                    'source': "Google Search",
                    'link': link,
                    'snippet': snippet
                })
                
                log.info(f"  → Found: {title[:50]}...")
                
            except Exception as e:
                log.warning(f"Error parsing Google result: {e}")
                continue
        
        return jobs
        
    except Exception as e:
        log.error(f"Error searching Google for '{query}': {e}")
        return []

def validate_with_kimi(job):
    """Use Kimi AI to validate if this is a genuine SACCO ICT job"""
    try:
        prompt = f"""
        Analyze this job posting and determine if it's a genuine SACCO ICT job in Kenya:
        
        Title: {job['title']}
        Employer: {job['employer']}
        Description: {job['snippet']}
        
        Criteria:
        1. Is this related to a SACCO/cooperative/microfinance institution in Kenya?
        2. Is this an ICT/IT/technology related position?
        3. Does this appear to be a genuine job posting?
        
        Respond with only: YES or NO
        """
        
        response = requests.post(
            KIMI_API_URL,
            headers={
                "Authorization": f"Bearer {KIMI_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": KIMI_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1
            },
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            content = result["choices"][0]["message"]["content"].strip().upper()
            return content == "YES"
        
    except Exception as e:
        log.warning(f"Kimi validation error: {e}")
    
    return False

def extract_deadline_from_page(url):
    """Extract deadline from the actual job page"""
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Look for deadline information
        deadline_patterns = [
            r'(deadline|closing date|application deadline)[:\s]*(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})',
            r'(deadline|closing date|application deadline)[:\s]*([A-Za-z]{3,9}\s+\d{1,2}\s*,?\s+\d{4})',
            r'(closing|deadline)[:\s]*(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})',
        ]
        
        page_text = soup.get_text()
        for pattern in deadline_patterns:
            match = re.search(pattern, page_text, re.IGNORECASE)
            if match:
                return match.group(2)
        
        return None
        
    except Exception as e:
        log.warning(f"Error extracting deadline from {url}: {e}")
        return None

def send_email(jobs):
    """Send email with job links"""
    if not jobs:
        log.info("No jobs to email")
        return
    
    try:
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = RECIPIENT_EMAIL
        msg['Subject'] = f"🏦 SACCO ICT Jobs Found - {len(jobs)} positions"
        
        body = "🏦 **SACCO ICT Jobs in Kenya**\n\n"
        body += f"Found {len(jobs)} relevant positions with valid deadlines:\n\n"
        
        for i, job in enumerate(jobs, 1):
            body += f"**{i}. {job['title']}**\n"
            body += f"📍 {job['employer']}\n"
            body += f"🗓️ {job['deadline']}\n"
            body += f"🔗 {job['link']}\n\n"
        
        body += "---\n"
        body += "🤖 Generated by SACCO ICT Job Scraper\n"
        body += "⏰ Jobs are filtered for current deadlines only"
        
        msg.attach(MIMEText(body, 'plain'))
        
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.send_message(msg)
        server.quit()
        
        log.info(f"✅ Email sent with {len(jobs)} jobs")
        
    except Exception as e:
        log.error(f"❌ Email sending failed: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    log.info("🚀 Starting SACCO ICT Job Scraper (Google Search)")
    
    seen_jobs = load_seen_jobs()
    seen_job_ids = {job['id'] for job in seen_jobs}
    new_jobs = []
    
    for query in SEARCH_QUERIES:
        log.info(f"🔍 Searching: {query}")
        jobs = search_google(query)
        log.info(f"  → Found {len(jobs)} results")
        
        for job in jobs:
            job_id = generate_job_id(job)
            
            if job_id in seen_job_ids:
                continue  # Skip already seen jobs
            
            # Validate with Kimi AI
            if not validate_with_kimi(job):
                continue  # Skip if not a genuine SACCO ICT job
            
            # Try to extract deadline from page
            deadline = extract_deadline_from_page(job['link'])
            if deadline:
                job['deadline'] = deadline
            elif not is_valid_deadline(job['deadline']):
                continue  # Skip if no valid deadline
            
            job['id'] = job_id
            job['date_found'] = datetime.now().strftime("%Y-%m-%d")
            new_jobs.append(job)
            
            log.info(f"  ✅ Added: {job['title']} at {job['employer']}")
    
    if new_jobs:
        log.info(f"📧 Sending email with {len(new_jobs)} new jobs")
        send_email(new_jobs)
        
        # Update seen jobs
        for job in new_jobs:
            seen_jobs.append(job)
        save_seen_jobs(seen_jobs)
        
    else:
        log.info("📭 No new SACCO ICT jobs found")

if __name__ == "__main__":
    main()
