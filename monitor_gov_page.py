import requests
from bs4 import BeautifulSoup
import json
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# Configuration - Monitor both specific page and parent listing
SPECIFIC_URL = "https://www.gov.uk/government/publications/capacity-market-auction-parameters-letter-from-desnz-to-neso-july-2025"
PARENT_URL = "https://www.gov.uk/government/publications"
STATE_FILE = "last_state.json"

# Keywords to look for in publications listing
KEYWORDS = ["capacity market", "auction parameters", "desnz", "neso", "capacity auction"]

# Email configuration
SENDER_EMAIL = os.environ.get('SENDER_EMAIL')
SENDER_PASSWORD = os.environ.get('SENDER_PASSWORD')
RECIPIENT_EMAIL = os.environ.get('RECIPIENT_EMAIL')

def fetch_page_content(url):
    """Fetch a page and extract document links"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        documents = []
        
        # Look for attachment sections
        attachment_sections = soup.find_all('section', class_='attachment')
        for section in attachment_sections:
            link = section.find('a', href=True)
            if link:
                doc_info = {
                    'title': link.get_text(strip=True),
                    'url': link['href'] if link['href'].startswith('http') else f"https://www.gov.uk{link['href']}",
                    'type': 'attachment'
                }
                documents.append(doc_info)
        
        # Look for document download links
        doc_links = soup.find_all('a', class_='govuk-link')
        for link in doc_links:
            if 'download' in link.get('class', []) or link.get('href', '').endswith(('.pdf', '.docx', '.xlsx', '.csv')):
                doc_info = {
                    'title': link.get_text(strip=True),
                    'url': link['href'] if link['href'].startswith('http') else f"https://www.gov.uk{link['href']}",
                    'type': 'document'
                }
                documents.append(doc_info)
        
        # Get page info
        page_title = soup.find('h1')
        page_title_text = page_title.get_text(strip=True) if page_title else "Unknown"
        
        updated_time = soup.find('time')
        updated_text = updated_time.get_text(strip=True) if updated_time else "Unknown"
        
        return {
            'page_title': page_title_text,
            'last_updated': updated_text,
            'documents': documents,
            'check_time': datetime.now().isoformat(),
            'url': url
        }
    
    except Exception as e:
        print(f"Error fetching page {url}: {e}")
        return None

def fetch_publications_listing():
    """Fetch the parent publications page and find capacity market related publications"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(PARENT_URL, headers=headers, timeout=30)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        publications = []
        
        # Look for publication links
        pub_links = soup.find_all('a', class_='govuk-link')
        
        for link in pub_links:
            title = link.get_text(strip=True).lower()
            href = link.get('href', '')
            
            # Check if this publication matches our keywords
            if any(keyword in title for keyword in KEYWORDS):
                # Skip if it's not a publication link
                if not href.startswith('/government/publications/'):
                    continue
                    
                full_url = f"https://www.gov.uk{href}" if not href.startswith('http') else href
                
                pub_info = {
                    'title': link.get_text(strip=True),
                    'url': full_url,
                    'found_on': 'publications_listing'
                }
                publications.append(pub_info)
        
        # Remove duplicates
        seen = set()
        unique_pubs = []
        for pub in publications:
            if pub['url'] not in seen:
                seen.add(pub['url'])
                unique_pubs.append(pub)
        
        return unique_pubs
    
    except Exception as e:
        print(f"Error fetching publications listing: {e}")
        return []

def load_previous_state():
    """Load the previous state from file"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except:
            return None
    return None

def save_current_state(state):
    """Save current state to file"""
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

def compare_states(previous, current):
    """Compare previous and current states"""
    if not previous:
        return {
            'is_first_run': True,
            'new_documents': current.get('specific_page_documents', []),
            'new_publications': current.get('related_publications', []),
            'message': "First run - monitoring started"
        }
    
    changes = {
        'is_first_run': False,
        'new_documents': [],
        'new_publications': [],
        'changed_publications': [],
        'page_updated': False
    }
    
    # Check for new documents on specific page
    prev_docs = {doc['url']: doc for doc in previous.get('specific_page_documents', [])}
    curr_docs = {doc['url']: doc for doc in current.get('specific_page_documents', [])}
    
    new_doc_urls = set(curr_docs.keys()) - set(prev_docs.keys())
    changes['new_documents'] = [curr_docs[url] for url in new_doc_urls]
    
    # Check for new or changed publications on listing page
    prev_pubs = {pub['url']: pub for pub in previous.get('related_publications', [])}
    curr_pubs = {pub['url']: pub for pub in current.get('related_publications', [])}
    
    new_pub_urls = set(curr_pubs.keys()) - set(prev_pubs.keys())
    changes['new_publications'] = [curr_pubs[url] for url in new_pub_urls]
    
    # Check if any publication titles changed (indicating page rename/update)
    for url in set(curr_pubs.keys()) & set(prev_pubs.keys()):
        if curr_pubs[url]['title'] != prev_pubs[url]['title']:
            changes['changed_publications'].append({
                'url': url,
                'old_title': prev_pubs[url]['title'],
                'new_title': curr_pubs[url]['title']
            })
    
    # Check if main page was updated
    changes['page_updated'] = previous.get('specific_page_last_updated') != current.get('specific_page_last_updated')
    
    return changes

def send_email_alert(changes, current_state):
    """Send email notification about changes"""
    if not all([SENDER_EMAIL, SENDER_PASSWORD, RECIPIENT_EMAIL]):
        print("Email credentials not configured. Skipping email notification.")
        return False
    
    try:
        msg = MIMEMultipart('alternative')
        
        if changes['is_first_run']:
            msg['Subject'] = "🔔 Monitoring Started - DESNZ Capacity Market"
            
            text = f"""
Monitoring Started for DESNZ Capacity Market Publications
========================================================

SPECIFIC PAGE: {SPECIFIC_URL}
PARENT LISTING: {PARENT_URL}

Currently tracking:
- {len(current_state.get('specific_page_documents', []))} documents on specific page
- {len(current_state.get('related_publications', []))} related publications on listing page

You will receive alerts for:
✓ New documents on the specific page
✓ New capacity market publications on the listing page
✓ Changes to publication titles/URLs

---
Started at: {current_state['check_time']}
This is an automated message from your GitHub page monitor.
            """
            
            pubs_list = "".join([f"<li><a href='{pub['url']}'>{pub['title']}</a></li>" 
                                for pub in current_state.get('related_publications', [])])
            
            html = f"""
<html>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
    <h2 style="color: #0066cc;">✅ Monitoring Started</h2>
    <p><strong>DESNZ Capacity Market Publications</strong></p>
    
    <div style="background: #f5f5f5; padding: 15px; border-left: 4px solid #0066cc; margin: 20px 0;">
        <p><strong>Specific page:</strong> <a href="{SPECIFIC_URL}">View Page</a></p>
        <p><strong>Parent listing:</strong> <a href="{PARENT_URL}">View Listing</a></p>
        <p><strong>Documents tracked:</strong> {len(current_state.get('specific_page_documents', []))}</p>
        <p><strong>Related publications:</strong> {len(current_state.get('related_publications', []))}</p>
    </div>
    
    <h3>Related Publications Being Monitored:</h3>
    <ul>{pubs_list}</ul>
    
    <p>You will receive alerts for new documents, publications, or changes.</p>
    
    <hr style="margin-top: 30px; border: none; border-top: 1px solid #ddd;">
    <p style="font-size: 12px; color: #666;">This is an automated message from your GitHub page monitor.</p>
</body>
</html>
            """
        else:
            # Check if there are any changes worth reporting
            has_changes = (changes['new_documents'] or 
                          changes['new_publications'] or 
                          changes['changed_publications'])
            
            if not has_changes:
                return False  # No changes, don't send email
            
            msg['Subject'] = "🚨 ALERT: Changes Detected - DESNZ Capacity Market"
            
            alerts = []
            alerts_html = []
            
            if changes['new_documents']:
                alerts.append(f"\n📄 NEW DOCUMENTS on specific page ({len(changes['new_documents'])}):")
                for doc in changes['new_documents']:
                    alerts.append(f"  - {doc['title']}")
                    alerts.append(f"    {doc['url']}")
                
                alerts_html.append(f"<h3 style='color: #d32f2f;'>📄 New Documents ({len(changes['new_documents'])})</h3><ul>")
                for doc in changes['new_documents']:
                    alerts_html.append(f"<li><strong>{doc['title']}</strong><br><a href='{doc['url']}'>{doc['url']}</a></li>")
                alerts_html.append("</ul>")
            
            if changes['new_publications']:
                alerts.append(f"\n📰 NEW PUBLICATIONS on listing page ({len(changes['new_publications'])}):")
                for pub in changes['new_publications']:
                    alerts.append(f"  - {pub['title']}")
                    alerts.append(f"    {pub['url']}")
                
                alerts_html.append(f"<h3 style='color: #ff6f00;'>📰 New Publications ({len(changes['new_publications'])})</h3><ul>")
                for pub in changes['new_publications']:
                    alerts_html.append(f"<li><strong>{pub['title']}</strong><br><a href='{pub['url']}'>{pub['url']}</a></li>")
                alerts_html.append("</ul>")
            
            if changes['changed_publications']:
                alerts.append(f"\n⚠️ CHANGED PUBLICATIONS ({len(changes['changed_publications'])}):")
                for change in changes['changed_publications']:
                    alerts.append(f"  - Old: {change['old_title']}")
                    alerts.append(f"    New: {change['new_title']}")
                    alerts.append(f"    URL: {change['url']}")
                
                alerts_html.append(f"<h3 style='color: #f57c00;'>⚠️ Changed Publications ({len(changes['changed_publications'])})</h3><ul>")
                for change in changes['changed_publications']:
                    alerts_html.append(f"<li><strong>Old:</strong> {change['old_title']}<br><strong>New:</strong> {change['new_title']}<br><a href='{change['url']}'>{change['url']}</a></li>")
                alerts_html.append("</ul>")
            
            text = f"""
CHANGES DETECTED on DESNZ Capacity Market Pages!
================================================

{''.join(alerts)}

Checked at: {current_state['check_time']}

---
This is an automated message from your GitHub page monitor.
            """
            
            html = f"""
<html>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
    <h2 style="color: #d32f2f;">🚨 Changes Detected!</h2>
    <p><strong>DESNZ Capacity Market Publications</strong></p>
    
    <div style="background: #fff3cd; padding: 15px; border-left: 4px solid #d32f2f; margin: 20px 0;">
        {''.join(alerts_html)}
    </div>
    
    <div style="background: #f5f5f5; padding: 15px; margin: 20px 0;">
        <p><strong>Specific page:</strong> <a href="{SPECIFIC_URL}">View Page</a></p>
        <p><strong>Parent listing:</strong> <a href="{PARENT_URL}">View Listing</a></p>
        <p><strong>Checked:</strong> {current_state['check_time']}</p>
    </div>
    
    <hr style="margin-top: 30px; border: none; border-top: 1px solid #ddd;">
    <p style="font-size: 12px; color: #666;">This is an automated message from your GitHub page monitor.</p>
</body>
</html>
            """
        
        msg['From'] = SENDER_EMAIL
        msg['To'] = RECIPIENT_EMAIL
        
        part1 = MIMEText(text, 'plain')
        part2 = MIMEText(html, 'html')
        msg.attach(part1)
        msg.attach(part2)
        
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.send_message(msg)
        
        print(f"✅ Email sent successfully to {RECIPIENT_EMAIL}")
        return True
        
    except Exception as e:
        print(f"❌ Error sending email: {e}")
        return False

def main():
    print(f"Starting enhanced monitor check at {datetime.now()}")
    print(f"Checking specific URL: {SPECIFIC_URL}")
    print(f"Checking parent URL: {PARENT_URL}")
    
    # Fetch specific page content
    specific_page = fetch_page_content(SPECIFIC_URL)
    
    if not specific_page:
        print("Failed to fetch specific page content")
        return
    
    print(f"Found {len(specific_page['documents'])} documents on specific page")
    
    # Fetch related publications from parent listing
    related_pubs = fetch_publications_listing()
    print(f"Found {len(related_pubs)} related publications on listing page")
    
    # Build current state
    current_state = {
        'specific_page_documents': specific_page['documents'],
        'specific_page_title': specific_page['page_title'],
        'specific_page_last_updated': specific_page['last_updated'],
        'related_publications': related_pubs,
        'check_time': datetime.now().isoformat()
    }
    
    # Load previous state
    previous_state = load_previous_state()
    
    # Compare states
    changes = compare_states(previous_state, current_state)
    
    # Report findings
    if changes['is_first_run']:
        print("First run - establishing baseline")
        print(f"Monitoring {len(related_pubs)} related publications")
        send_email_alert(changes, current_state)
    else:
        alerts_found = False
        
        if changes['new_documents']:
            print(f"🚨 ALERT: {len(changes['new_documents'])} new document(s) on specific page!")
            for doc in changes['new_documents']:
                print(f"  - {doc['title']}")
            alerts_found = True
        
        if changes['new_publications']:
            print(f"🚨 ALERT: {len(changes['new_publications'])} new related publication(s)!")
            for pub in changes['new_publications']:
                print(f"  - {pub['title']}")
            alerts_found = True
        
        if changes['changed_publications']:
            print(f"⚠️ WARNING: {len(changes['changed_publications'])} publication(s) changed!")
            for change in changes['changed_publications']:
                print(f"  - {change['old_title']} → {change['new_title']}")
            alerts_found = True
        
        if not alerts_found:
            print("No new changes detected")
        else:
            send_email_alert(changes, current_state)
    
    # Save current state
    save_current_state(current_state)
    print("State saved successfully")

if __name__ == "__main__":
    main()
