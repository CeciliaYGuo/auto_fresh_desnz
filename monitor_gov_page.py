import requests
from bs4 import BeautifulSoup
import json
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# Configuration
URL = "https://www.gov.uk/government/publications/capacity-market-auction-parameters-letter-from-desnz-to-neso-july-2025"
STATE_FILE = "last_state.json"

# Email configuration (from GitHub Secrets)
SENDER_EMAIL = os.environ.get('SENDER_EMAIL')
SENDER_PASSWORD = os.environ.get('SENDER_PASSWORD')
RECIPIENT_EMAIL = os.environ.get('RECIPIENT_EMAIL')

def fetch_page_content():
    """Fetch the government page and extract all document links"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(URL, headers=headers, timeout=30)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Find all document links and attachments
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
        
        # Get page title and last updated
        page_title = soup.find('h1')
        page_title_text = page_title.get_text(strip=True) if page_title else "Unknown"
        
        updated_time = soup.find('time')
        updated_text = updated_time.get_text(strip=True) if updated_time else "Unknown"
        
        return {
            'page_title': page_title_text,
            'last_updated': updated_text,
            'documents': documents,
            'check_time': datetime.now().isoformat()
        }
    
    except Exception as e:
        print(f"Error fetching page: {e}")
        return None

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
    """Compare previous and current states to find new documents"""
    if not previous:
        return {
            'is_first_run': True,
            'new_documents': current['documents'],
            'message': "First run - monitoring started"
        }
    
    prev_docs = {doc['url']: doc for doc in previous.get('documents', [])}
    curr_docs = {doc['url']: doc for doc in current.get('documents', [])}
    
    # Find new documents
    new_doc_urls = set(curr_docs.keys()) - set(prev_docs.keys())
    new_documents = [curr_docs[url] for url in new_doc_urls]
    
    # Check if page was updated
    page_updated = previous.get('last_updated') != current.get('last_updated')
    
    return {
        'is_first_run': False,
        'new_documents': new_documents,
        'page_updated': page_updated,
        'total_documents': len(curr_docs)
    }

def send_email_alert(changes, current_state):
    """Send email notification about changes"""
    if not all([SENDER_EMAIL, SENDER_PASSWORD, RECIPIENT_EMAIL]):
        print("Email credentials not configured. Skipping email notification.")
        return False
    
    try:
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"🔔 New Updates on DESNZ Capacity Market Page"
        msg['From'] = SENDER_EMAIL
        msg['To'] = RECIPIENT_EMAIL
        
        # Create email body
        if changes['is_first_run']:
            text = f"""
Monitoring Started for DESNZ Capacity Market Page
================================================

Page URL: {URL}
Started monitoring at: {current_state['check_time']}

Currently tracking {len(current_state['documents'])} documents on this page.

You will receive alerts when new documents are published.

---
This is an automated message from your GitHub page monitor.
            """
            html = f"""
<html>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
    <h2 style="color: #0066cc;">✅ Monitoring Started</h2>
    <p><strong>DESNZ Capacity Market Auction Parameters</strong></p>
    
    <div style="background: #f5f5f5; padding: 15px; border-left: 4px solid #0066cc; margin: 20px 0;">
        <p><strong>Page:</strong> <a href="{URL}">View Page</a></p>
        <p><strong>Started:</strong> {current_state['check_time']}</p>
        <p><strong>Documents tracked:</strong> {len(current_state['documents'])}</p>
    </div>
    
    <p>You will receive alerts when new documents are published.</p>
    
    <hr style="margin-top: 30px; border: none; border-top: 1px solid #ddd;">
    <p style="font-size: 12px; color: #666;">This is an automated message from your GitHub page monitor.</p>
</body>
</html>
            """
        else:
            new_count = len(changes['new_documents'])
            
            if new_count == 0:
                return False  # No changes, don't send email
            
            docs_list = "\n".join([f"- {doc['title']}\n  {doc['url']}" for doc in changes['new_documents']])
            docs_html = "".join([f"<li><strong>{doc['title']}</strong><br><a href='{doc['url']}'>{doc['url']}</a></li>" 
                                for doc in changes['new_documents']])
            
            text = f"""
NEW DOCUMENTS DETECTED on DESNZ Capacity Market Page!
===================================================

{new_count} new document(s) found:

{docs_list}

Page URL: {URL}
Checked at: {current_state['check_time']}
Total documents now: {changes['total_documents']}

---
This is an automated message from your GitHub page monitor.
            """
            
            html = f"""
<html>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
    <h2 style="color: #d32f2f;">🚨 New Documents Detected!</h2>
    <p><strong>DESNZ Capacity Market Auction Parameters</strong></p>
    
    <div style="background: #fff3cd; padding: 15px; border-left: 4px solid #d32f2f; margin: 20px 0;">
        <h3 style="margin-top: 0; color: #d32f2f;">{new_count} New Document(s)</h3>
        <ul style="margin: 10px 0;">
            {docs_html}
        </ul>
    </div>
    
    <div style="background: #f5f5f5; padding: 15px; margin: 20px 0;">
        <p><strong>Page:</strong> <a href="{URL}">View Full Page</a></p>
        <p><strong>Checked:</strong> {current_state['check_time']}</p>
        <p><strong>Total documents:</strong> {changes['total_documents']}</p>
    </div>
    
    <hr style="margin-top: 30px; border: none; border-top: 1px solid #ddd;">
    <p style="font-size: 12px; color: #666;">This is an automated message from your GitHub page monitor.</p>
</body>
</html>
            """
        
        # Attach both plain text and HTML versions
        part1 = MIMEText(text, 'plain')
        part2 = MIMEText(html, 'html')
        msg.attach(part1)
        msg.attach(part2)
        
        # Send email
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.send_message(msg)
        
        print(f"✅ Email sent successfully to {RECIPIENT_EMAIL}")
        return True
        
    except Exception as e:
        print(f"❌ Error sending email: {e}")
        return False

def main():
    print(f"Starting monitor check at {datetime.now()}")
    print(f"Checking URL: {URL}")
    
    # Fetch current page content
    current_state = fetch_page_content()
    
    if not current_state:
        print("Failed to fetch page content")
        return
    
    print(f"Found {len(current_state['documents'])} documents on page")
    
    # Load previous state
    previous_state = load_previous_state()
    
    # Compare states
    changes = compare_states(previous_state, current_state)
    
    # Report findings
    if changes['is_first_run']:
        print("First run - establishing baseline")
        send_email_alert(changes, current_state)
    elif changes['new_documents']:
        print(f"🚨 ALERT: {len(changes['new_documents'])} new document(s) detected!")
        for doc in changes['new_documents']:
            print(f"  - {doc['title']}")
            print(f"    {doc['url']}")
        send_email_alert(changes, current_state)
    else:
        print("No new documents detected")
    
    # Save current state
    save_current_state(current_state)
    print("State saved successfully")

if __name__ == "__main__":
    main()
