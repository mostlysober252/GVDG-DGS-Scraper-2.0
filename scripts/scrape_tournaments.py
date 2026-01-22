#!/usr/bin/env python3
"""
Scrape Disc Golf Scene tournaments from the North Carolina page
and filter to those within ~60 miles of Greenville, NC.
"""

import requests
from bs4 import BeautifulSoup
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json
import os
from datetime import datetime
import re

# Google Sheet ID
SHEET_ID = '1s-GhF_K0i1vACYlHBiprzpuY4cNHJnRvlwHxNaTnVWw'

# NC Tournaments page
DGS_NC_URL = "https://www.discgolfscene.com/tournaments/North_Carolina"

# Cities within ~60 miles of Greenville, NC (lowercase for matching)
NEARBY_CITIES = [
    'greenville', 'winterville', 'ayden', 'farmville', 'grifton',
    'kinston', 'new bern', 'washington', 'williamston', 'tarboro',
    'rocky mount', 'wilson', 'goldsboro', 'la grange', 'snow hill',
    'jacksonville', 'havelock', 'morehead city', 'richlands', 'maysville',
    'robersonville', 'bethel', 'pinetops', 'hookerton', 'trenton',
    'pollocksville', 'vanceboro', 'chocowinity', 'belhaven',
]


def scrape_tournaments():
    """Scrape tournament data from DGS North Carolina page."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    print(f"Fetching: {DGS_NC_URL}")
    
    try:
        response = requests.get(DGS_NC_URL, headers=headers, timeout=30)
        response.raise_for_status()
        print(f"Response: {response.status_code}, Length: {len(response.text)}")
    except requests.RequestException as e:
        print(f"Error fetching DGS: {e}")
        return []
    
    soup = BeautifulSoup(response.text, 'html.parser')
    tournaments = []
    seen_urls = set()
    
    # Find all tournament links - they follow pattern /tournament/Name_Year or /tournaments/Name_Year
    all_links = soup.find_all('a', href=True)
    
    for link in all_links:
        href = link.get('href', '')
        
        # Only process tournament detail page links
        if not re.search(r'/tournaments?/[A-Za-z0-9_]+_\d{4}', href):
            continue
        
        # Skip registration/results subpages
        if '/register' in href or '/results' in href or '/pictures' in href:
            continue
            
        # Build full URL
        if href.startswith('/'):
            full_url = f"https://www.discgolfscene.com{href}"
        else:
            full_url = href
        
        # Skip duplicates
        base_url = full_url.split('?')[0].rstrip('/')
        if base_url in seen_urls:
            continue
        seen_urls.add(base_url)
        
        # Get the raw link text (tournament name)
        raw_name = link.get_text(strip=True)
        
        # Skip empty or navigation links
        if not raw_name or len(raw_name) < 5:
            continue
        if raw_name.lower() in ['tournaments', 'north carolina', 'load more']:
            continue
        
        # Now we need to find the context around this link to get date and location
        # Walk up to find the container element
        parent = link.parent
        for _ in range(5):  # Go up max 5 levels
            if parent is None:
                break
            parent = parent.parent
        
        if parent is None:
            continue
            
        # Get all text in the parent container
        container_text = parent.get_text(' ', strip=True)
        
        # Extract date - look for patterns like "Jan 24" or "Feb 21-22" or "Sat, Jan 24, 2026"
        date_str = ''
        date_match = re.search(
            r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s,]+(\d{1,2})(?:-\d{1,2})?(?:[\s,]+(\d{4}))?',
            container_text,
            re.IGNORECASE
        )
        if date_match:
            month = date_match.group(1)[:3].capitalize()
            day = date_match.group(2)
            year = date_match.group(3) if date_match.group(3) else '2026'
            date_str = f"{month} {day}, {year}"
        
        # Extract location - look for "City, NC" pattern
        location = ''
        # Look for pattern like "CourseName City, NC" or just "City, NC"
        loc_match = re.search(r'([A-Za-z][A-Za-z\s\.\']+),\s*NC\b', container_text)
        if loc_match:
            location = loc_match.group(1).strip() + ', NC'
            # Clean up - sometimes course name is included, try to get just city
            # Common pattern: "Course Name City, NC" - take last word before comma
            words = loc_match.group(1).strip().split()
            if len(words) > 1:
                # Usually the city is the last word(s)
                location = words[-1] + ', NC'
                # Handle two-word cities
                if words[-1].lower() in ['mount', 'bern', 'hill', 'city', 'beach', 'point']:
                    location = ' '.join(words[-2:]) + ', NC'
        
        # Extract tier
        tier = ''
        tier_match = re.search(r'\b([ABCX](?:/[ABCX])?-tier|XC-tier|XB-tier)\b', container_text, re.IGNORECASE)
        if tier_match:
            tier = tier_match.group(1)
        
        # Check if this tournament is in a nearby city
        location_lower = location.lower()
        is_nearby = any(city in location_lower for city in NEARBY_CITIES)
        
        # Also check URL and name for GVDG or specific courses
        text_to_check = (raw_name + ' ' + full_url).lower()
        if 'gvdg' in text_to_check or 'greenville' in text_to_check:
            is_nearby = True
        if any(course in text_to_check for course in ['meadowbrook', 'north_rec', 'ecu', 'barnet', 'northeast_creek']):
            is_nearby = True
        
        if is_nearby:
            tournament = {
                'date': date_str,
                'name': raw_name,
                'location': location,
                'tier': tier,
                'url': full_url
            }
            tournaments.append(tournament)
            print(f"  ✓ {raw_name[:50]} | {location}")
    
    # Sort by date
    tournaments = sort_by_date(tournaments)
    
    # Remove exact duplicates by name
    seen_names = set()
    unique = []
    for t in tournaments:
        name_key = t['name'].lower()[:50]
        if name_key not in seen_names:
            seen_names.add(name_key)
            unique.append(t)
    
    print(f"\nTotal nearby tournaments: {len(unique)}")
    return unique


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
            year = int(match.group(3)) if match.group(3) else 2026
            return (year, month, day)
        return (9999, 99, 99)
    
    return sorted(tournaments, key=get_sort_key)


def update_google_sheet(tournaments):
    """Update Google Sheet with tournament data."""
    creds_json = os.environ.get('GOOGLE_CREDENTIALS')
    if not creds_json:
        print("Error: GOOGLE_CREDENTIALS not set")
        return False
    
    try:
        creds_dict = json.loads(creds_json)
        print(f"Using credentials for: {creds_dict.get('client_email', 'unknown')}")
    except json.JSONDecodeError as e:
        print(f"Error parsing credentials: {e}")
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
        
        # Clear ALL data first
        print("Clearing sheet...")
        sheet.clear()
        
        # Write header row
        headers = ['Date', 'Name', 'Location', 'Tier', 'URL']
        sheet.update('A1:E1', [headers])
        
        # Write data rows
        if tournaments:
            rows = []
            for t in tournaments:
                rows.append([
                    t.get('date', ''),
                    t.get('name', ''),
                    t.get('location', ''),
                    t.get('tier', ''),
                    t.get('url', '')
                ])
            
            print(f"Writing {len(rows)} tournaments...")
            sheet.update(f'A2:E{len(rows) + 1}', rows)
        
        # Update timestamp in column G
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        sheet.update('G1', [[f'Last updated: {timestamp}']])
        
        print(f"✓ Sheet updated at {timestamp}")
        return True
        
    except Exception as e:
        print(f"Error updating sheet: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("=" * 60)
    print("DGS Scraper - Tournaments within 60mi of Greenville, NC")
    print("=" * 60)
    
    tournaments = scrape_tournaments()
    
    if tournaments:
        print(f"\n{'='*60}")
        print(f"Found {len(tournaments)} tournaments:")
        print(f"{'='*60}")
        for i, t in enumerate(tournaments, 1):
            print(f"{i:2}. {t['date']:12} | {t['name'][:45]:45} | {t['location']}")
        
        success = update_google_sheet(tournaments)
        return 0 if success else 1
    else:
        print("\nNo tournaments found near Greenville")
        update_google_sheet([])
        return 0


if __name__ == '__main__':
    exit(main())
