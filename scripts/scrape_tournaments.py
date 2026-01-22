#!/usr/bin/env python3
"""
Scrape Disc Golf Scene tournaments using regex pattern matching.
Filters to tournaments within ~60 miles of Greenville, NC.
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

# Cities within ~60 miles of Greenville, NC
NEARBY_CITIES = [
    'greenville', 'winterville', 'ayden', 'farmville', 'grifton',
    'kinston', 'new bern', 'washington', 'williamston', 'tarboro',
    'rocky mount', 'wilson', 'goldsboro', 'la grange', 'snow hill',
    'jacksonville', 'havelock', 'morehead city', 'richlands', 'maysville',
    'robersonville', 'bethel', 'pinetops', 'hookerton', 'trenton',
]


def fetch_page():
    """Fetch the DGS NC tournaments page."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    print(f"Fetching: {DGS_NC_URL}")
    response = requests.get(DGS_NC_URL, headers=headers, timeout=30)
    response.raise_for_status()
    print(f"Got {len(response.text)} bytes")
    return response.text


def extract_tournaments(html):
    """Extract tournaments by finding links and their associated text."""
    soup = BeautifulSoup(html, 'html.parser')
    tournaments = []
    seen = set()
    
    # Find all links that point to tournament pages
    for link in soup.find_all('a', href=True):
        href = link.get('href', '')
        
        # Must be a tournament detail page (has year suffix like _2026)
        if not re.search(r'/tournaments?/[\w_]+_20\d{2}$', href):
            continue
        
        # Build full URL
        url = f"https://www.discgolfscene.com{href}" if href.startswith('/') else href
        
        # Skip if we've seen this tournament
        if url in seen:
            continue
        seen.add(url)
        
        # The link text should be JUST the tournament name
        name = link.get_text(strip=True)
        
        # Skip if name is too short or is a navigation element
        if not name or len(name) < 5:
            continue
        if name.lower() in ['tournaments', 'north carolina', 'register', 'results']:
            continue
        
        # Now find the surrounding context to extract date and location
        # Look at siblings and parent text
        date_str = ''
        location = ''
        tier = ''
        
        # Get the parent container
        parent = link.find_parent()
        if parent:
            # Look at previous siblings for date info
            prev_text = ''
            for sib in link.previous_siblings:
                if hasattr(sib, 'get_text'):
                    prev_text = sib.get_text(strip=True) + ' ' + prev_text
                elif isinstance(sib, str):
                    prev_text = sib.strip() + ' ' + prev_text
            
            # Look at next siblings for location/tier info
            next_text = ''
            for sib in link.next_siblings:
                if hasattr(sib, 'get_text'):
                    next_text += ' ' + sib.get_text(strip=True)
                elif isinstance(sib, str):
                    next_text += ' ' + sib.strip()
            
            context = prev_text + ' ' + next_text
            
            # Extract date from context - pattern like "Jan 24" or "Feb 7-8"
            date_match = re.search(
                r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})(?:-\d{1,2})?\b',
                prev_text,
                re.IGNORECASE
            )
            if date_match:
                month = date_match.group(1)[:3].capitalize()
                day = date_match.group(2)
                date_str = f"{month} {day}, 2026"
            
            # Extract location from context - "City, NC" pattern
            loc_match = re.search(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?),\s*NC\b', context)
            if loc_match:
                location = loc_match.group(1) + ', NC'
            
            # Extract tier
            tier_match = re.search(r'\b([ABCX]-tier|XC-tier|XB-tier)\b', context, re.IGNORECASE)
            if tier_match:
                tier = tier_match.group(1)
        
        # Check if this is a nearby tournament
        check_text = (name + ' ' + location + ' ' + url).lower()
        is_nearby = any(city in check_text for city in NEARBY_CITIES)
        
        # Also match GVDG specifically
        if 'gvdg' in check_text:
            is_nearby = True
        
        if is_nearby:
            tournaments.append({
                'date': date_str,
                'name': name,
                'location': location,
                'tier': tier,
                'url': url
            })
            print(f"  ✓ {name[:50]}")
    
    return tournaments


def fetch_tournament_details(tournaments):
    """Fetch individual tournament pages to get accurate details."""
    print(f"\nFetching details for {len(tournaments)} tournaments...")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    for t in tournaments:
        try:
            response = requests.get(t['url'], headers=headers, timeout=15)
            if response.status_code != 200:
                continue
                
            soup = BeautifulSoup(response.text, 'html.parser')
            page_text = soup.get_text(' ', strip=True)
            
            # Get title - usually in h1 or title tag
            title_tag = soup.find('h1')
            if title_tag:
                clean_title = title_tag.get_text(strip=True)
                # Remove "· Disc Golf Scene" suffix if present
                clean_title = re.sub(r'\s*·\s*Disc Golf Scene.*$', '', clean_title)
                if clean_title and len(clean_title) > 3:
                    t['name'] = clean_title
            
            # Get date - look for pattern like "Sat, Feb 21, 2026" or "Sat-Sun, Feb 21-22, 2026"
            date_match = re.search(
                r'(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)(?:-(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun))?,\s+'
                r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})(?:-\d{1,2})?,\s+(\d{4})',
                page_text
            )
            if date_match:
                t['date'] = f"{date_match.group(1)} {date_match.group(2)}, {date_match.group(3)}"
            
            # Get location - look for "Course Name City, NC" pattern
            loc_match = re.search(r'([A-Z][A-Za-z\s\'\.]+),\s*NC\b', page_text)
            if loc_match:
                loc_text = loc_match.group(1).strip()
                # Try to extract just the city (last 1-2 words before ", NC")
                words = loc_text.split()
                if len(words) >= 2:
                    # Check if last word is part of a two-word city
                    if words[-1].lower() in ['mount', 'bern', 'hill', 'city', 'beach', 'point', 'creek']:
                        t['location'] = ' '.join(words[-2:]) + ', NC'
                    else:
                        t['location'] = words[-1] + ', NC'
                else:
                    t['location'] = loc_text + ', NC'
            
            # Get tier
            tier_match = re.search(r'PDGA\s+([ABCX](?:/[ABCX])?-tier|XC-tier|XB-tier)', page_text, re.IGNORECASE)
            if tier_match:
                t['tier'] = tier_match.group(1)
            
            print(f"    → {t['name'][:40]} | {t['location']} | {t['date']}")
            
        except Exception as e:
            print(f"    ! Error fetching {t['url']}: {e}")
            continue
    
    return tournaments


def sort_by_date(tournaments):
    """Sort tournaments by date."""
    month_order = {
        'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
        'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12
    }
    
    def get_sort_key(t):
        date_str = t.get('date', '')
        match = re.search(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2}),\s*(\d{4})', date_str)
        if match:
            return (int(match.group(3)), month_order.get(match.group(1), 0), int(match.group(2)))
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
        print(f"\nUsing service account: {creds_dict.get('client_email', 'unknown')}")
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
        
        # Clear sheet completely
        print("Clearing sheet...")
        sheet.clear()
        
        # Write header row
        headers = ['Date', 'Name', 'Location', 'Tier', 'URL']
        sheet.update('A1:E1', [headers])
        
        # Write data
        if tournaments:
            rows = [[
                t.get('date', ''),
                t.get('name', ''),
                t.get('location', ''),
                t.get('tier', ''),
                t.get('url', '')
            ] for t in tournaments]
            
            print(f"Writing {len(rows)} rows...")
            sheet.update(f'A2:E{len(rows) + 1}', rows)
        
        # Timestamp
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        sheet.update('G1', [[f'Updated: {timestamp}']])
        
        print(f"✓ Done at {timestamp}")
        return True
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("=" * 60)
    print("DGS Scraper - 60mi from Greenville, NC")
    print("=" * 60)
    
    try:
        html = fetch_page()
        tournaments = extract_tournaments(html)
        
        if tournaments:
            # Fetch individual pages to get clean data
            tournaments = fetch_tournament_details(tournaments)
            tournaments = sort_by_date(tournaments)
            
            print(f"\n{'='*60}")
            print(f"Final: {len(tournaments)} tournaments")
            print('='*60)
            for t in tournaments:
                print(f"  {t['date']:12} | {t['name'][:40]:40} | {t['location']}")
            
            update_google_sheet(tournaments)
        else:
            print("\nNo nearby tournaments found")
            update_google_sheet([])
            
    except Exception as e:
        print(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == '__main__':
    exit(main())
