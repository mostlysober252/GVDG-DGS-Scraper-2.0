#!/usr/bin/env python3
"""
Scrape Disc Golf Scene tournaments within 60 miles of Greenville, NC
and update Google Sheet with the results.
"""

import requests
from bs4 import BeautifulSoup
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json
import os
from datetime import datetime
import re

# DGS search URL with filters applied
DGS_URL = (
    "https://www.discgolfscene.com/tournaments/search?"
    "filter%5Blocation%5D%5Bcountry%5D=USA&"
    "filter%5Blocation%5D%5Bname%5D=Greenville%2C+NC&"
    "filter%5Blocation%5D%5Blatitude%5D=35.597011&"
    "filter%5Blocation%5D%5Blongitude%5D=-77.375799&"
    "filter%5Blocation%5D%5Bdistance%5D=60&"
    "filter%5Blocation%5D%5Bunits%5D=mi&"
    "filter%5Blocation%5D%5Bzipcode%5D=27833&"
    "filter%5Bformat%5D%5B0%5D=s&"
    "filter%5Bformat%5D%5B1%5D=d&"
    "filter%5Bformat%5D%5B2%5D=t"
)

# Google Sheet ID (extract from your published URL)
# From: https://docs.google.com/spreadsheets/d/e/2PACX-1vRz6V6BAwII4eoqITz4MW5zmM_3mYJqrtqtZl9xB87lAZgDT1E0Do1r2cp2aa1tvEKWevnPhb2zQu4s/pub
# The actual sheet ID is different - you'll need to get it from the editable URL
SHEET_ID = os.environ.get('GOOGLE_SHEET_ID', 'YOUR_SHEET_ID_HERE')


def scrape_tournaments():
    """Scrape tournament data from Disc Golf Scene."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        response = requests.get(DGS_URL, headers=headers, timeout=30)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"Error fetching DGS: {e}")
        return []
    
    soup = BeautifulSoup(response.text, 'html.parser')
    tournaments = []
    
    # Find tournament cards/rows - DGS uses various selectors
    # Try multiple possible selectors since their HTML may change
    tournament_elements = soup.select('.tournament-card, .tournament-row, [data-tournament], .event-card')
    
    # If no elements found with those selectors, try finding links to tournament pages
    if not tournament_elements:
        tournament_elements = soup.select('a[href*="/tournaments/"]')
    
    for element in tournament_elements:
        try:
            tournament = parse_tournament_element(element, soup)
            if tournament and tournament.get('name'):
                tournaments.append(tournament)
        except Exception as e:
            print(f"Error parsing tournament: {e}")
            continue
    
    # Remove duplicates based on URL
    seen_urls = set()
    unique_tournaments = []
    for t in tournaments:
        if t.get('url') and t['url'] not in seen_urls:
            seen_urls.add(t['url'])
            unique_tournaments.append(t)
    
    print(f"Found {len(unique_tournaments)} tournaments")
    return unique_tournaments


def parse_tournament_element(element, soup):
    """Parse a single tournament element and extract data."""
    tournament = {
        'date': '',
        'name': '',
        'location': '',
        'tier': '',
        'url': ''
    }
    
    # Get tournament URL
    if element.name == 'a':
        href = element.get('href', '')
    else:
        link = element.select_one('a[href*="/tournaments/"]')
        href = link.get('href', '') if link else ''
    
    if href:
        if not href.startswith('http'):
            href = 'https://www.discgolfscene.com' + href
        tournament['url'] = href
    
    # Get tournament name
    name_elem = element.select_one('.tournament-name, .event-name, h3, h4, .title')
    if name_elem:
        tournament['name'] = name_elem.get_text(strip=True)
    elif element.name == 'a':
        tournament['name'] = element.get_text(strip=True)
    
    # Skip if it's a navigation link or empty
    skip_names = ['search', 'filter', 'load more', 'view all', 'sign in', 'register']
    if tournament['name'].lower() in skip_names or len(tournament['name']) < 3:
        return None
    
    # Get date
    date_elem = element.select_one('.date, .tournament-date, .event-date, time')
    if date_elem:
        tournament['date'] = date_elem.get_text(strip=True)
        # Also check datetime attribute
        if date_elem.get('datetime'):
            tournament['date'] = date_elem.get('datetime')[:10]
    
    # Get location
    location_elem = element.select_one('.location, .tournament-location, .venue, .course-name')
    if location_elem:
        tournament['location'] = location_elem.get_text(strip=True)
    
    # Get tier (PDGA tier if available)
    tier_elem = element.select_one('.tier, .pdga-tier, .event-tier, .badge')
    if tier_elem:
        tournament['tier'] = tier_elem.get_text(strip=True)
    
    return tournament


def update_google_sheet(tournaments):
    """Update Google Sheet with tournament data."""
    # Load credentials from environment variable
    creds_json = os.environ.get('GOOGLE_CREDENTIALS')
    if not creds_json:
        print("Error: GOOGLE_CREDENTIALS environment variable not set")
        return False
    
    try:
        creds_dict = json.loads(creds_json)
    except json.JSONDecodeError as e:
        print(f"Error parsing credentials JSON: {e}")
        return False
    
    # Set up Google Sheets API
    scope = [
        'https://spreadsheets.google.com/feeds',
        'https://www.googleapis.com/auth/drive'
    ]
    
    try:
        credentials = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(credentials)
        
        # Open the sheet
        sheet = client.open_by_key(SHEET_ID).sheet1
        
        # Clear existing data (except header row)
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
        
        # Update sheet if we have data
        if rows:
            sheet.update(f'A2:E{len(rows) + 1}', rows)
            print(f"Updated sheet with {len(rows)} tournaments")
        else:
            print("No tournaments to update")
        
        # Update last-updated timestamp in a separate cell
        sheet.update('G1', [[f'Last updated: {datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}']])
        
        return True
        
    except Exception as e:
        print(f"Error updating Google Sheet: {e}")
        return False


def main():
    print("Starting DGS tournament scraper...")
    print(f"Target URL: {DGS_URL[:80]}...")
    
    tournaments = scrape_tournaments()
    
    if tournaments:
        print("\nTournaments found:")
        for t in tournaments[:5]:  # Print first 5 for debugging
            print(f"  - {t.get('name', 'Unknown')} ({t.get('date', 'No date')})")
        if len(tournaments) > 5:
            print(f"  ... and {len(tournaments) - 5} more")
        
        success = update_google_sheet(tournaments)
        if success:
            print("\nSheet updated successfully!")
        else:
            print("\nFailed to update sheet")
    else:
        print("\nNo tournaments found - check if DGS changed their HTML structure")


if __name__ == '__main__':
    main()
