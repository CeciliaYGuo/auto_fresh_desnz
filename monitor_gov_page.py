import requests
from bs4 import BeautifulSoup
import json
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# Configuration
SPECIFIC_URL = "https://www.gov.uk/government/publications/capacity-market-auction-parameters-letter-from-desnz-to-neso-july-2025"
PARENT_URL = "https://www.gov.uk/search/all?organisations[]=department-for-energy-security-and-net-zero&order=updated-newest&parent=department-for-energy-security-and-net-zero"
STATE_FILE = "last_state.json"

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

def fetch_desnz_publications():
    """Fetch ALL publications from DESNZ search page"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(PARENT_URL, headers=headers, timeout=30)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        publications = []
        
        # Look for search results - gov.uk search results are in specific divs
        search_results = soup.find_all('li', class_='gem-c-document-list__item')
        
        for result in search_results:
            link = result.find('a', class_='gem-c-document-list__item-title')
            if link:
                title = link.get_text(strip=True)
                href = link.get('href', '')
                
                # Only include publication links
                if href.startswith('/government/publications/'):
                    full_url = f"https://www.gov.uk{href}"
                    
                    # Get the description/metadata if available
                    description_elem = result.find('p', class_='gem-c-document-list__item-description')
                    description = description_elem.get_text(strip=True) if description_elem else ""
                    
                    # Get the date if available
                    time_elem = result.find('time')
                    date = time_elem.get_text(strip=True) if time_elem else "Unknown"
                    
                    pub_info = {
                        'title': title,
                        'url': full_url,
                        'description': description,
                        'date': date,
                        'found_on': 'desnz_search'
                    }
                    publications.append(pub_info)
        
        # If no results with that class, try alternative structure
        if not publications:
            # Try finding all links that point to publications
            all_links = soup.find_all('a', href=True)
            for link in all_links:
                href = link.get('href', '')
                if href.startswith('/government/publications/'):
                    full_url = f"https://www.gov.uk{href}"
                    title = link.get_text(strip=True)
                    
                    if title and full_url not in [p['url'] for p in publications]:
                        pub_info = {
                            'title': title,
                            'url': full_url,
                            'description': "",
                            'date': "Unknown",
                            'found_on': 'desnz_search'
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
        print(f"Error fetching DESNZ publications: {e}")
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
            'new_publications': current.get('desnz_publications', []),
            'message': "First run - monitoring started"
        }
    
    changes = {
        'is_first_run': False,
        'new_documents': [],
        'new_publications': [],
        'page_updated': False
    }
    
    # Check for new documents on specific page
    prev_docs = {doc['url']: doc for doc in previous.get('specific_page_documents', [])}
    curr_docs = {doc['url']: doc for doc in current.get('specific_page_documents', [])}
    
    new_doc_urls = set(curr_docs.keys()) - set(prev_docs.keys())
    changes['new_documents'] = [curr_docs[url] for url in new_doc_urls]
    
    # Check for new publications on DESNZ search page
    prev_pubs = {pub['url']: pub for pub in previous.get('desnz_publications', [])}
    curr_pubs = {pub['url']: pub for pub in current.get('desnz_publications', [])}
    
    new_pub_urls = set(curr_pubs.keys()) - set(prev_pubs.keys())
    changes['new_publications'] = [curr_pubs[url] for url in new_pub_urls]
    
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
            msg['Subject'] = "🔔 Monitoring Started - DESNZ Publications"
            
            # Show first 10 publications for initial email
            pubs_to_show = current_state.get('desnz_publications', [])[:10]
            pubs_list_text = "\n".join([f"  - {pub['title']}\n    Published: {pub['date']}" 
                                       for pub in pubs_to_show])
            
            text = f"""
Monitoring Started for DESNZ Publications
=========================================

SPECIFIC PAGE (Capacity Market): {SPECIFIC_URL}
ALL DESNZ PUBLICATIONS: {PARENT_URL}

Currently tracking:
- {len(current_state.get('specific_page_documents', []))} documents on capacity market page
- {len(current_state.get('desnz_publications', []))} DESNZ publications (showing first 10 below)

You will receive alerts for:
✓ New documents on the capacity market page
✓ ANY new publication from DESNZ

Recent DESNZ Publications:
{pubs_list_text}

---
Started at: {current_state['check_time']}
This is an automated message from your GitHub page monitor.
            """
            
            pubs_list_html = "".join([f"<li><strong>{pub['title']}</strong><br>Published: {pub['date']}<br><a href='{pub['url']}'>{pub['url']}</a></li>" 
                                for pub in pubs_to_show])
            
            html = f"""
<html>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
    <h2 style="color: #0066cc;">✅ Monitoring Started</h2>
    <p><strong>DESNZ Publications Monitor</strong></p>
    
    <div style="background: #f5f5f5; padding: 15px; border-left: 4px solid #0066cc; margin: 20px 0;">
        <p><strong>Capacity Market page:</strong> <a href="{SPECIFIC_URL}">View Page</a></p>
        <p><strong>All DESNZ publications:</strong> <a href="{PARENT_URL}">View Search</a></p>
        <p><strong>Documents tracked:</strong> {len(current_state.get('specific_page_documents', []))}</p>
        <p><strong>DESNZ publications tracked:</strong> {len(current_state.get('desnz_publications', []))}</p>
    </div>
    
    <h3>Recent DESNZ Publications (First 10):</h3>
    <ul>{pubs_list_html}</ul>
    
    <p>You will receive alerts for any new documents or publications.</p>
    
    <hr style="margin-top: 30px; border: none; border-top: 1px solid #ddd;">
    <p style="font-size: 12px; color: #666;">This is an automated message from your GitHub page monitor.</p>
</body>
</html>
            """
        else:
            # Check if there are any changes worth reporting
            has_changes = (changes['new_documents'] or changes['new_publications'])
            
            if not has_changes:
                return False  # No changes, don't send email
            
            msg['Subject'] = "🚨 ALERT: New DESNZ Publications Detected"
            
            alerts = []
            alerts_html = []
            
            if changes['new_documents']:
                alerts.append(f"\n📄 NEW DOCUMENTS on Capacity Market page ({len(changes['new_documents'])}):")
                for doc in changes['new_documents']:
                    alerts.append(f"  - {doc['title']}")
                    alerts.append(f"    {doc['url']}")
                
                alerts_html.append(f"<h3 style='color: #d32f2f;'>📄 New Capacity Market Documents ({len(changes['new_documents'])})</h3><ul>")
                for doc in changes['new_documents']:
                    alerts_html.append(f"<li><strong>{doc['title']}</strong><br><a href='{doc['url']}'>{doc['url']}</a></li>")
                alerts_html.append("</ul>")
            
            if changes['new_publications']:
                alerts.append(f"\n📰 NEW DESNZ PUBLICATIONS ({len(changes['new_publications'])}):")
                for pub in changes['new_publications']:
                    alerts.append(f"  - {pub['title']}")
                    if pub.get('date'):
                        alerts.append(f"    Published: {pub['date']}")
                    if pub.get('description'):
                        alerts.append(f"    {pub['description'][:100]}...")
                    alerts.append(f"    {pub['url']}")
                
                alerts_html.append(f"<h3 style='color: #ff6f00;'>📰 New DESNZ Publications ({len(changes['new_publications'])})</h3><ul>")
                for pub in changes['new_publications']:
                    desc = f"<br><em>{pub['description'][:150]}...</em>" if pub.get('description') else ""
                    date_info = f"<br>Published: {pub['date']}" if pub.get('date') else ""
                    alerts_html.append(f"<li><strong>{pub['title']}</strong>{date_info}{desc}<br><a href='{pub['url']}'>{pub['url']}</a></li>")
                alerts_html.append("</ul>")
            
            text = f"""
NEW DESNZ PUBLICATIONS DETECTED!
=================================

{''.join(alerts)}

Checked at: {current_state['check_time']}

View all DESNZ publications: {PARENT_URL}

---
This is an automated message from your GitHub page monitor.
            """
            
            html = f"""
<html>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
    <h2 style="color: #d32f2f;">🚨 New Publications Detected!</h2>
    <p><strong>DESNZ Publications Alert</strong></p>
    
    <div style="background: #fff3cd; padding: 15px; border-left: 4px solid #d32f2f; margin: 20px 0;">
        {''.join(alerts_html)}
    </div>
    
    <div style="background: #f5f5f5; padding: 15px; margin: 20px 0;">
        <p><strong>Capacity Market page:</strong> <a href="{SPECIFIC_URL}">View Page</a></p>
        <p><strong>All DESNZ publications:</strong> <a href="{PARENT_URL}">View Search</a></p>
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
    print(f"Starting DESNZ publications monitor at {datetime.now()}")
    print(f"Checking capacity market page: {SPECIFIC_URL}")
    print(f"Checking ALL DESNZ publications: {PARENT_URL}")
    
    # Fetch specific page content
    specific_page = fetch_page_content(SPECIFIC_URL)
    
    if not specific_page:
        print("Failed to fetch capacity market page content")
        return
    
    print(f"Found {len(specific_page['documents'])} documents on capacity market page")
    
    # Fetch ALL DESNZ publications
    desnz_pubs = fetch_desnz_publications()
    print(f"Found {len(desnz_pubs)} DESNZ publications on search page")
    
    # Build current state
    current_state = {
        'specific_page_documents': specific_page['documents'],
        'specific_page_title': specific_page['page_title'],
        'specific_page_last_updated': specific_page['last_updated'],
        'desnz_publications': desnz_pubs,
        'check_time': datetime.now().isoformat()
    }
    
    # Load previous state
    previous_state = load_previous_state()
    
    # Compare states
    changes = compare_states(previous_state, current_state)
    
    # Report findings
    if changes['is_first_run']:
        print("First run - establishing baseline")
        print(f"Monitoring {len(desnz_pubs)} DESNZ publications")
        send_email_alert(changes, current_state)
    else:
        alerts_found = False
        
        if changes['new_documents']:
            print(f"🚨 ALERT: {len(changes['new_documents'])} new document(s) on capacity market page!")
            for doc in changes['new_documents']:
                print(f"  - {doc['title']}")
            alerts_found = True
        
        if changes['new_publications']:
            print(f"🚨 ALERT: {len(changes['new_publications'])} new DESNZ publication(s)!")
            for pub in changes['new_publications']:
                print(f"  - {pub['title']}")
                if pub.get('date'):
                    print(f"    Published: {pub['date']}")
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
