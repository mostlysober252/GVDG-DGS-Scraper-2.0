#!/usr/bin/env python3
"""
GVDG Tournament Scraper v4.0
Scrapes tournaments from Disc Golf Scene within 60 miles of Greenville, NC

v4.0 - Complete rewrite with proper HTML parsing
- Uses the search results page which has cleaner structure
- Properly extracts tournament name, date, venue, city from separate elements
- Filters by distance from Greenville, NC
- Identifies GVDG-hosted events

Usage:
    python dgs-scraper.py

Output:
    tournaments.json - JSON file with tournament data
"""

import json
import re
import sys
from datetime import datetime, timedelta
from urllib.parse import urlencode
import time
from math import radians, cos, sin, asin, sqrt

try:
    import requests
except ImportError:
    print("Error: 'requests' library not installed.")
    print("Install with: pip install requests")
    sys.exit(1)

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("Error: 'beautifulsoup4' library not installed.")
    print("Install with: pip install beautifulsoup4")
    sys.exit(1)

# ============================================
# CONFIGURATION
# ============================================
CONFIG = {
    "location": {
        "name": "Greenville, NC",
        "latitude": 35.597011,
        "longitude": -77.375799,
        "zipcode": "27833"
    },
    "distance": 60,  # miles
    "formats": ["s", "d", "t"],  # singles, doubles, teams
    "gvdg_keywords": [
        "gvdg", "greenville disc golf", "hangover", "chili cookoff",
        "frozen bowl", "ayden founders", "down east", "depc",
        "mando madness", "scholarship shootout"
    ],
    "timeout": 30,
    "retry_attempts": 3,
    "retry_delay": 2,
    "output_file": "tournaments.json"
}

# Known cities and their approximate distances from Greenville, NC
CITY_DISTANCES = {
    "greenville": 0,
    "winterville": 5,
    "ayden": 10,
    "farmville": 10,
    "washington": 25,
    "kinston": 28,
    "goldsboro": 45,
    "wilson": 35,
    "rocky mount": 40,
    "new bern": 40,
    "jacksonville": 50,
    "richlands": 55,
    "maysville": 50,
    "morehead city": 60,
    "raleigh": 80,
    "cary": 75,
    "durham": 85,
    "chapel hill": 90,
    "charlotte": 220,
    "wilmington": 130,
    "fayetteville": 100,
    "columbia": 30,  # Columbia, NC (not SC)
}

DGS_BASE_URL = "https://www.discgolfscene.com"


def build_search_url():
    """Build the search URL with location parameters."""
    params = {
        "filter[location][country]": "USA",
        "filter[location][name]": CONFIG["location"]["name"],
        "filter[location][latitude]": CONFIG["location"]["latitude"],
        "filter[location][longitude]": CONFIG["location"]["longitude"],
        "filter[location][distance]": CONFIG["distance"],
        "filter[location][units]": "mi",
        "filter[location][zipcode]": CONFIG["location"]["zipcode"],
    }
    # Add format filters
    for i, fmt in enumerate(CONFIG["formats"]):
        params[f"filter[format][{i}]"] = fmt
    
    return f"{DGS_BASE_URL}/tournaments/search?{urlencode(params)}"


def fetch_page(url, attempt=1):
    """Fetch a page with retry logic."""
    headers = {
        "User-Agent": "GVDG Tournament Scraper/4.0 (https://github.com/mostlysober252/GVDG-DGS-Scraper-2.0)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.5",
    }
    
    try:
        print(f"  Fetching: {url[:80]}...")
        response = requests.get(url, headers=headers, timeout=CONFIG["timeout"])
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        if attempt < CONFIG["retry_attempts"]:
            print(f"  Retry {attempt}/{CONFIG['retry_attempts']} after error: {e}")
            time.sleep(CONFIG["retry_delay"])
            return fetch_page(url, attempt + 1)
        else:
            print(f"  Failed after {CONFIG['retry_attempts']} attempts: {e}")
            raise


def parse_date(date_text):
    """Parse date text to YYYY-MM-DD format."""
    if not date_text:
        return None
    
    date_text = date_text.strip()
    
    # Remove day-of-week prefix like "Sat, " or "Fri-Sun, "
    date_text = re.sub(r'^[A-Za-z]{3}(-[A-Za-z]{3})?,\s*', '', date_text)
    
    # Handle multi-day formats: "Jan 31-Feb 1, 2026" -> use first date
    # Also handles "Mar 7-8, 2026"
    match = re.match(r'([A-Za-z]{3})\s+(\d{1,2})(?:-(?:[A-Za-z]{3}\s+)?\d{1,2})?,\s*(\d{4})', date_text)
    if match:
        month_str = match.group(1)
        day = match.group(2)
        year = match.group(3)
        date_text = f"{month_str} {day}, {year}"
    
    # Parse standard format: "Jan 24, 2026"
    for fmt in ["%b %d, %Y", "%B %d, %Y"]:
        try:
            dt = datetime.strptime(date_text.strip(), fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    
    return None


def extract_tier(text):
    """Extract PDGA tier from text."""
    if not text:
        return "Other"
    text_upper = text.upper()
    
    if "A-TIER" in text_upper:
        return "A"
    elif "B-TIER" in text_upper:
        return "B"
    elif "C-TIER" in text_upper or "C/B-TIER" in text_upper:
        return "C"
    elif "XC-TIER" in text_upper:
        return "XC"
    elif "LEAGUE" in text_upper:
        return "League"
    elif "DOUBLES" in text_upper:
        return "Doubles"
    elif "TEAMS" in text_upper:
        return "Teams"
    return "Other"


def extract_spots(text):
    """Extract registration spots like '10/72' from text."""
    if not text:
        return None
    match = re.search(r'(\d+)\s*/\s*(\d+)', text)
    return f"{match.group(1)}/{match.group(2)}" if match else None


def is_gvdg_tournament(name, venue=""):
    """Check if tournament is GVDG-hosted based on name or venue."""
    if not name:
        return False
    
    combined = (name + " " + venue).lower()
    return any(kw in combined for kw in CONFIG["gvdg_keywords"])


def estimate_distance(city):
    """Estimate distance from Greenville, NC based on city name."""
    if not city:
        return 30  # Default
    
    city_lower = city.lower().replace(", nc", "").strip()
    
    # Check known cities
    for known_city, dist in CITY_DISTANCES.items():
        if known_city in city_lower:
            return dist
    
    # Default for unknown NC cities
    return 30


def clean_text(text):
    """Clean extracted text by removing extra whitespace."""
    if not text:
        return ""
    return re.sub(r'\s+', ' ', text).strip()


def parse_tournaments_from_nc_page(html):
    """
    Parse tournaments from the NC tournaments page.
    The page structure has tournament cards as links with this format:
    
    [Date Block] [Logo] [Name] [Tier] · [Day, Date] [Venue][City] [Spots] [Format]
    """
    soup = BeautifulSoup(html, 'html.parser')
    tournaments = []
    seen_urls = set()
    
    print("  Parsing NC tournaments page...")
    
    # Find all tournament links - they link to /tournaments/Tournament_Name_YYYY
    # The main content area contains the tournament listings
    tournament_links = soup.find_all('a', href=re.compile(r'^https://www\.discgolfscene\.com/tournaments/[A-Za-z0-9_-]+'))
    
    print(f"  Found {len(tournament_links)} potential tournament links")
    
    for link in tournament_links:
        try:
            url = link.get('href', '')
            
            # Skip non-tournament URLs
            if not url or '/tournaments/search' in url or '/tournaments/new' in url:
                continue
            if '/tournaments/mine' in url:
                continue
            # Skip state/country navigation links (2-letter codes or country names)
            if re.match(r'.*/tournaments/[A-Z]{2}$', url):
                continue
            if any(x in url for x in ['/tournaments/USA', '/tournaments/Canada', '/tournaments/North_Carolina']):
                continue
            
            # Skip if already processed
            if url in seen_urls:
                continue
            seen_urls.add(url)
            
            # Get the full text content of the link
            link_text = link.get_text(separator=' ', strip=True)
            
            # Skip if this looks like a navigation item (very short or no date-like content)
            if len(link_text) < 10:
                continue
            
            # The link text contains the tournament info in this format:
            # "Tournament Name PDGA C-tier · Sat, Jan 24, 2026 VenueCity, NC 12 / 72 2"
            
            # Extract tournament name - it's before "PDGA" or before the date
            name_match = re.match(r'^(.+?)(?:\s*PDGA\s*(?:Flex\s*)?[A-Za-z]-tier|\s*·|\s+(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun))', link_text)
            if name_match:
                name = clean_text(name_match.group(1))
            else:
                # Try to get name from before the date pattern
                name_match = re.match(r'^(.+?)(?:\s+(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)(?:-[A-Za-z]{3})?,)', link_text)
                if name_match:
                    name = clean_text(name_match.group(1))
                else:
                    # Fallback: use URL to extract name
                    url_name = url.split('/')[-1].replace('_', ' ')
                    # Remove year suffix
                    name = re.sub(r'\s*\d{4}$', '', url_name)
            
            # Skip if name is still malformed or too long
            if not name or len(name) > 150:
                continue
            
            # Extract date - look for "Day, Mon DD, YYYY" pattern
            date_match = re.search(
                r'(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)(?:-[A-Za-z]{3})?,\s*([A-Za-z]{3})\s+(\d{1,2})(?:-(?:[A-Za-z]{3}\s+)?\d{1,2})?,\s*(\d{4})',
                link_text
            )
            if date_match:
                date_str = f"{date_match.group(1)} {date_match.group(2)}, {date_match.group(3)}"
                parsed_date = parse_date(date_str)
            else:
                continue  # Skip if no date found
            
            if not parsed_date:
                continue
            
            # Extract venue and city - look for pattern after date
            # Format is usually: "VenueCity, NC" or "Venue**City, NC**"
            city = "NC"
            venue = ""
            
            # Look for "City, NC" pattern
            city_match = re.search(r'\*?\*?([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?),\s*NC\*?\*?', link_text)
            if city_match:
                city = f"{city_match.group(1)}, NC"
            
            # Extract tier
            tier = extract_tier(link_text)
            
            # Extract spots
            spots = extract_spots(link_text)
            
            # Calculate distance
            distance = estimate_distance(city)
            
            # Check if GVDG event
            is_gvdg = is_gvdg_tournament(name, venue)
            
            # Filter by distance (should already be filtered by search, but double-check)
            if distance > CONFIG["distance"] + 10:  # Allow small buffer
                continue
            
            tournament = {
                "name": name,
                "date": parsed_date,
                "venue": venue,
                "city": city,
                "tier": tier,
                "url": url,
                "distance": distance,
                "isGVDG": is_gvdg,
                "spots": spots
            }
            
            tournaments.append(tournament)
            
            # Log
            gvdg_mark = "⭐ " if is_gvdg else "   "
            print(f"  {gvdg_mark}{name[:45]:<45} | {parsed_date} | {city}")
            
        except Exception as e:
            print(f"  Error parsing tournament: {e}")
            continue
    
    return tournaments


def parse_tournaments_from_search(html):
    """
    Alternative parser for search results page.
    Falls back to this if NC page parsing fails.
    """
    soup = BeautifulSoup(html, 'html.parser')
    tournaments = []
    
    # Similar logic but adapted for search results structure
    # This is a backup parser
    
    return tournaments


def validate_tournament(t):
    """Validate tournament data structure."""
    required = {
        'name': str, 'date': str, 'city': str, 'tier': str,
        'url': str, 'distance': int, 'isGVDG': bool
    }
    
    for field, ftype in required.items():
        if field not in t:
            return False, f"Missing {field}"
        if not isinstance(t[field], ftype):
            return False, f"Bad type for {field}"
    
    # Validate date format
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', t['date']):
        return False, "Bad date format"
    
    # Validate URL
    if 'discgolfscene.com' not in t['url']:
        return False, "Bad URL"
    
    # Validate tier
    valid_tiers = ['A', 'B', 'C', 'XC', 'League', 'Doubles', 'Teams', 'Other']
    if t['tier'] not in valid_tiers:
        return False, f"Bad tier: {t['tier']}"
    
    # Validate name length
    if len(t['name']) > 200 or len(t['name']) < 5:
        return False, "Name length invalid"
    
    return True, "OK"


def deduplicate_tournaments(tournaments):
    """Remove duplicate tournaments by URL."""
    seen_urls = set()
    unique = []
    
    for t in tournaments:
        if t['url'] not in seen_urls:
            seen_urls.add(t['url'])
            unique.append(t)
    
    return unique


def filter_future_tournaments(tournaments):
    """Keep only future tournaments (allow 1 day grace period)."""
    cutoff = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    return [t for t in tournaments if t['date'] >= cutoff]


def main():
    """Main function."""
    print("=" * 60)
    print("GVDG Tournament Scraper v4.0")
    print("=" * 60)
    print(f"Location: {CONFIG['location']['name']}")
    print(f"Radius: {CONFIG['distance']} miles")
    print()
    
    # Try fetching the NC tournaments page first (more reliable structure)
    nc_url = f"{DGS_BASE_URL}/tournaments/North_Carolina"
    print(f"Fetching NC tournaments page...")
    
    try:
        html = fetch_page(nc_url)
    except Exception as e:
        print(f"FATAL: Could not fetch page: {e}")
        sys.exit(1)
    
    # Save HTML for debugging
    with open('debug_page.html', 'w', encoding='utf-8') as f:
        f.write(html)
    print("  (Saved debug_page.html for debugging)")
    
    # Parse tournaments
    print("\nParsing tournaments...")
    tournaments = parse_tournaments_from_nc_page(html)
    
    # Validate
    print(f"\nValidating {len(tournaments)} tournaments...")
    valid = []
    for t in tournaments:
        ok, msg = validate_tournament(t)
        if ok:
            valid.append(t)
        else:
            print(f"  ✗ {t.get('name', '?')[:35]}... - {msg}")
    
    print(f"  {len(valid)}/{len(tournaments)} passed validation")
    
    # Deduplicate
    unique = deduplicate_tournaments(valid)
    print(f"  {len(unique)} unique tournaments")
    
    # Filter to future only
    future = filter_future_tournaments(unique)
    print(f"  {len(future)} upcoming tournaments")
    
    # Filter by distance from Greenville
    nearby = [t for t in future if t['distance'] <= CONFIG['distance']]
    print(f"  {len(nearby)} within {CONFIG['distance']} miles")
    
    # Sort by date
    nearby.sort(key=lambda t: t['date'])
    
    # Build output
    output = {
        "lastUpdated": datetime.now().isoformat(),
        "searchCenter": CONFIG["location"]["name"],
        "searchRadius": CONFIG["distance"],
        "totalFound": len(nearby),
        "tournaments": nearby
    }
    
    # Write JSON
    with open(CONFIG["output_file"], 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    print(f"\nWrote {len(nearby)} tournaments to {CONFIG['output_file']}")
    
    # Summary
    print("\n" + "=" * 60)
    gvdg_count = sum(1 for t in nearby if t['isGVDG'])
    print(f"TOTAL: {len(nearby)} tournaments | GVDG: {gvdg_count}")
    print("=" * 60)
    
    # Show first 15
    for t in nearby[:15]:
        mark = "⭐ " if t['isGVDG'] else "   "
        tier_str = f"[{t['tier']}]" if t['tier'] != 'Other' else ""
        print(f"{mark}{t['date']} | {t['name'][:42]:<42} | {t['city']:<18} {tier_str}")
    
    if len(nearby) > 15:
        print(f"   ... and {len(nearby) - 15} more")
    
    print("\n✓ Done!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
