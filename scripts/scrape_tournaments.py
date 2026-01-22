#!/usr/bin/env python3
"""
Scrape Disc Golf Scene tournaments from the North Carolina page
and filter to those within ~60 miles of Greenville, NC.

Since the DGS search page loads results via JavaScript (which we can't scrape),
we instead scrape the static NC tournaments page and filter by known nearby cities.
"""

import requests
from bs4 import BeautifulSoup
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json
import os
from datetime import datetime
import re

# Google Sheet ID - YOUR ACTUAL SHEET ID
SHEET_ID = '1s-GhF_K0i1vACYlHBiprzpuY4cNHJnRvlwHxNaTnVWw'

# NC Tournaments page (static HTML, easier to scrape)
DGS_NC_URL = "https://www.discgolfscene.com/tournaments/North_Carolina"

# Cities/areas within ~60 miles of Greenville, NC
NEARBY_LOCATIONS = [
    # Greenville area
    'greenville', 'winterville', 'ayden', 'farmville', 'simpson',
    # Pitt County
    'pitt county', 'bethel', 'grifton', 'fountain',
    # Within 30 miles
    'kinston', 'new bern', 'washington', 'williamston', 'tarboro',
    'rocky mount', 'wilson', 'goldsboro', 'la grange', 'snow hill',
    # Within 60 miles  
    'jacksonville', 'havelock', 'morehead city', 'beaufort',
    'roanoke rapids', 'elizabeth city', 'edenton', 'plymouth',
    'nashville', 'spring hope', 'zebulon', 'wendell',
    'smithfield', 'selma', 'dunn', 'clinton',
    'maysville', 'richlands', 'swansboro',
    # Course names that might appear
    'west meadowbrook', 'ecu', 'north rec', 'covenant',
    'third street', 'barnet', 'creek side', 'northeast creek',
    # Club names
    'gvdg'
]


def scrape_tournaments():
    """Scrape tournament data from DGS North Carolina page."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
    }
    
    print(f"Fetching: {DGS_NC_URL}")
    
    try:
        response = requests.get(DGS_NC_URL, headers=headers, timeout=30)
        response.raise_for_status()
        print(f"Response status: {response.status_code}")
        print(f"Content length: {len(response.text)} characters")
    except requests.RequestException as e:
        print(f"Error fetching DGS: {e}")
        return []
    
    soup = BeautifulSoup(response.text, 'html.parser')
    tournaments = []
    seen_urls = set()
    
    # Get all text content for debugging
    page_text = soup.get_text()
    print(f"Page text length: {len(page_text)} characters")
    
    # Find all links to tournament pages
    all_links = soup.find_all('a', href=True)
    print(f"Total links found: {len(all_links)}")
    
    tournament_links = [a for a in all_links if '/tournament' in a.get('href', '').lower() 
                        and '/tournaments/' not in a.get('href', '').lower()]
    
    # Also try the /tournaments/ pattern but exclude state pages
    tournament_links2 = [a for a in all_links if re.search(r'/tournaments/[^/]+_\d{4}', a.get('href', ''))]
    tournament_links.extend(tournament_links2)
    
    print(f"Tournament links found: {len(tournament_links)}")
    
    for link in tournament_links:
        href = link.get('href', '')
        
        # Build full URL
        if href.startswith('/'):
            full_url = f"https://www.discgolfscene.com{href}"
        elif href.startswith('http'):
            full_url = href
        else:
            continue
            
        # Skip duplicates
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)
        
        # Get tournament name
        name = link.get_text(strip=True)
        if not name or len(name) < 3:
            continue
            
        # Skip navigation links
        skip_words = ['tournaments', 'search', 'filter', 'load more', 'sign in', 'register', 'north carolina']
        if name.lower() in skip_words:
            continue
        
        # Get parent element for context
        parent = link.find_parent(['div', 'li', 'td', 'span'])
        context_text = ''
        location = ''
        tier = ''
        date_str = ''
        
        if parent:
            # Get broader context
            grandparent = parent.find_parent(['div', 'tr', 'section'])
            if grandparent:
                context_text = grandparent.get_text(' ', strip=True)
            else:
                context_text = parent.get_text(' ', strip=True)
            
            # Extract location (City, NC pattern)
            loc_match = re.search(r'at\s+[^·]+?([A-Za-z\s\.]+),\s*NC', context_text)
            if not loc_match:
                loc_match = re.search(r'([A-Za-z\s\.]+),\s*NC', context_text)
            if loc_match:
                location = loc_match.group(1).strip() + ', NC'
            
            # Extract tier
            tier_match = re.search(r'(PDGA\s+)?([ABCX](?:/[ABCX])?-tier|XC-tier|Flex)', context_text, re.IGNORECASE)
            if tier_match:
                tier = tier_match.group(2) if tier_match.group(2) else tier_match.group(0)
            
            # Extract date
            date_match = re.search(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})(?:-\d{1,2})?(?:,?\s*(\d{4}))?', context_text, re.IGNORECASE)
            if date_match:
                month = date_match.group(1)[:3].capitalize()
                day = date_match.group(2)
                year = date_match.group(3) if date_match.group(3) else '2025'
                date_str = f"{month} {day}, {year}"
        
        # Check if nearby
        check_text = (name + ' ' + location + ' ' + full_url + ' ' + context_text).lower()
        is_nearby = any(loc in check_text for loc in NEARBY_LOCATIONS)
        
        if is_nearby:
            tournament = {
                'date': date_str,
                'name': clean_name(name),
                'location': location,
                'tier': tier,
                'url': full_url
            }
            tournaments.append(tournament)
            print(f"  ✓ Found: {tournament['name'][:50]} | {location}")
    
    # Sort by date
    tournaments = sort_by_date(tournaments)
    
    print(f"\nTotal nearby tournaments: {len(tournaments)}")
    return tournaments


def clean_name(name):
    """Clean up tournament name."""
    name = re.sub(r'\s*·\s*\d{4}\s*$', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def sort_by_date(tournaments):
    """Sort tournaments by date."""
    month_order = {
        'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
        'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12
    }
    
    def get_sort_key(t):
        date_str = t.get('date', '')
        match = re.search(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2}),?\s*(\d{4})?', date_str)
        if match:
            month = month_order.get(match.group(1), 0)
            day = int(match.group(2))
            year = int(match.group(3)) if match.group(3) else 2025
            return (year, month, day)
        return (9999, 99, 99)
    
    return sorted(tournaments, key=get_sort_key)


def update_google_sheet(tournaments):
    """Update Google Sheet with tournament data."""
    creds_json = os.environ.get('GOOGLE_CREDENTIALS')
    if not creds_json:
        print("Error: GOOGLE_CREDENTIALS environment variable not set")
        return False
    
    try:
        creds_dict = json.loads(creds_json)
        print(f"Credentials loaded for: {creds_dict.get('client_email', 'unknown')}")
    except json.JSONDecodeError as e:
        print(f"Error parsing credentials JSON: {e}")
        return False
    
    scope = [
        'https://spreadsheets.google.com/feeds',
        'https://www.googleapis.com/auth/drive'
    ]
    
    try:
        credentials = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(credentials)
        
        print(f"Opening sheet: {SHEET_ID}")
        sheet = client.open_by_key(SHEET_ID).sheet1
        
        # Clear existing data (except header row)
        print("Clearing old data...")
        sheet.batch_clear(['A2:E1000'])
        
        # Prepare data rows
        rows = []
        for t in tournaments:
            rows.append([
                t.get('date', ''),
                t.get('name', ''),
                t.get('location', ''),
                t.get('tier', ''),
                t.get('url', '')
            ])
        
        if rows:
            print(f"Writing {len(rows)} rows...")
            sheet.update(f'A2:E{len(rows) + 1}', rows)
            print(f"Updated sheet with {len(rows)} tournaments")
        else:
            print("No tournaments to update")
        
        # Update timestamp
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        sheet.update('G1', [[f'Last updated: {timestamp}']])
        print(f"Timestamp updated: {timestamp}")
        
        return True
        
    except Exception as e:
        print(f"Error updating Google Sheet: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("=" * 60)
    print("DGS Tournament Scraper - Greenville NC Area (60 mile radius)")
    print("=" * 60)
    print()
    
    tournaments = scrape_tournaments()
    
    print()
    print("-" * 60)
    
    if tournaments:
        print(f"\nFound {len(tournaments)} tournaments near Greenville:")
        for i, t in enumerate(tournaments, 1):
            print(f"  {i}. {t.get('date', 'TBD'):15} | {t.get('name', '')[:40]}")
        
        print()
        success = update_google_sheet(tournaments)
        if success:
            print("\n✅ Google Sheet updated successfully!")
        else:
            print("\n❌ Failed to update Google Sheet")
            return 1
    else:
        print("\n⚠️  No nearby tournaments found")
        print("Updating sheet with empty data to show scraper ran...")
        update_google_sheet([])
    
    return 0


if __name__ == '__main__':
    exit(main())
