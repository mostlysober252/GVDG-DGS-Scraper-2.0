#!/usr/bin/env python3
"""
GVDG Tournament Scraper v2.1
Scrapes tournaments from Disc Golf Scene within 60 miles of Greenville, NC

FIXES in v2.1:
- Improved HTML parsing to handle DGS's specific page structure
- Better extraction of individual tournament fields
- More robust date parsing
- Better handling of venue/city separation

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

# Try to import requests, provide helpful error if missing
try:
    import requests
except ImportError:
    print("Error: 'requests' library not installed.")
    print("Install with: pip install requests")
    sys.exit(1)

# Try to import BeautifulSoup, provide helpful error if missing
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
    # Search center point (Greenville, NC)
    "location": {
        "name": "Greenville, NC",
        "latitude": 35.597011,
        "longitude": -77.375799,
        "zipcode": "27833"
    },
    
    # Search radius in miles
    "distance": 60,
    
    # Tournament formats to include (s=singles, d=doubles, t=teams)
    "formats": ["s", "d", "t"],
    
    # GVDG-hosted tournament identifiers (case-insensitive partial matches)
    "gvdg_keywords": [
        "gvdg",
        "greenville valley",
        "hangover",
        "chili bowl",
        "frozen bowl",
        "ayden founders"
    ],
    
    # Request settings
    "timeout": 30,
    "retry_attempts": 3,
    "retry_delay": 2,
    
    # Output file
    "output_file": "tournaments.json"
}

# Base URL for Disc Golf Scene
DGS_BASE_URL = "https://www.discgolfscene.com"
DGS_SEARCH_URL = f"{DGS_BASE_URL}/tournaments/search"


def build_search_url():
    """Build the search URL with all parameters."""
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
    
    return f"{DGS_SEARCH_URL}?{urlencode(params)}"


def fetch_page(url, attempt=1):
    """Fetch a page with retry logic."""
    headers = {
        "User-Agent": "GVDG Tournament Scraper/2.1 (https://github.com/mostlysober252/GVDG-DGS-Scraper-2.0)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
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
    """
    Parse date text from DGS format to ISO date string.
    Handles formats like:
    - "Sat, Jan 24, 2026"
    - "Sat-Sun, Jan 31-Feb 1, 2026"
    - "Fri-Sun, Mar 20-22, 2026"
    - "Mon, Jan 19, 2026"
    
    Returns the START date in YYYY-MM-DD format.
    """
    if not date_text:
        return None
        
    # Clean up the text
    date_text = date_text.strip()
    
    # Remove day-of-week prefix (e.g., "Sat, " or "Sat-Sun, ")
    date_text = re.sub(r'^[A-Za-z]{3}(-[A-Za-z]{3})?,\s*', '', date_text)
    
    # Handle multi-day formats like "Jan 31-Feb 1, 2026" or "Mar 20-22, 2026"
    # Extract just the start date
    
    # Pattern for "Month Day-Day, Year" (same month)
    match = re.match(r'([A-Za-z]{3})\s+(\d{1,2})-\d{1,2},\s*(\d{4})', date_text)
    if match:
        month, day, year = match.groups()
        date_text = f"{month} {day}, {year}"
    
    # Pattern for "Month Day-Month Day, Year" (different months)
    match = re.match(r'([A-Za-z]{3})\s+(\d{1,2})-[A-Za-z]{3}\s+\d{1,2},\s*(\d{4})', date_text)
    if match:
        month, day, year = match.groups()
        date_text = f"{month} {day}, {year}"
    
    # Now parse the cleaned date
    try:
        # Try "Mon DD, YYYY" format
        dt = datetime.strptime(date_text.strip(), "%b %d, %Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        pass
    
    try:
        # Try "Month DD, YYYY" format (full month name)
        dt = datetime.strptime(date_text.strip(), "%B %d, %Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        pass
    
    print(f"  Warning: Could not parse date '{date_text}'")
    return None


def extract_tier(text):
    """Extract PDGA tier from tournament text."""
    if not text:
        return "Other"
    text = text.upper()
    
    if "A-TIER" in text:
        return "A"
    elif "B-TIER" in text:
        return "B"
    elif "C-TIER" in text or "C/B-TIER" in text:
        return "C"
    elif "XC-TIER" in text:
        return "XC"
    elif "LEAGUE" in text:
        return "League"
    elif "DOUBLES" in text:
        return "Doubles"
    else:
        return "Other"


def extract_spots(text):
    """Extract registration spots info like '10/72' or '90/90'."""
    if not text:
        return None
    match = re.search(r'(\d+)\s*/\s*(\d+)', text)
    if match:
        return f"{match.group(1)}/{match.group(2)}"
    return None


def is_gvdg_tournament(name):
    """Check if tournament is GVDG-hosted based on name."""
    if not name:
        return False
    name_lower = name.lower()
    return any(keyword in name_lower for keyword in CONFIG["gvdg_keywords"])


def calculate_distance(city):
    """
    Calculate approximate distance from Greenville, NC to a city.
    """
    if not city:
        return 30
        
    # Known distances from Greenville, NC (approximate)
    known_distances = {
        "greenville": 0,
        "farmville": 10,
        "ayden": 10,
        "winterville": 5,
        "kinston": 28,
        "rocky mount": 40,
        "wilson": 35,
        "jacksonville": 50,
        "richlands": 55,
        "maysville": 50,
        "new bern": 40,
        "zebulon": 55,
        "raleigh": 80,
        "goldsboro": 45,
        "cary": 75,
    }
    
    city_lower = city.lower()
    for known_city, distance in known_distances.items():
        if known_city in city_lower:
            return distance
    
    # Default to middle of search radius if unknown
    return 30


def extract_city_from_venue(venue_text):
    """
    Extract city from venue text like "The Z at Zebulon Community ParkZebulon, NC"
    or "Farmville Municipal DGCFarmville, NC"
    """
    if not venue_text:
        return "NC"
    
    # Look for pattern: City, State (NC or North Carolina)
    match = re.search(r'([A-Za-z\s]+),\s*(NC|North Carolina)\s*$', venue_text)
    if match:
        city = match.group(1).strip()
        # Clean up city name - sometimes the venue name runs into it
        # Look for capital letter that starts the actual city name
        # E.g., "Community ParkZebulon" -> we want "Zebulon"
        parts = re.split(r'(?<=[a-z])(?=[A-Z])', city)
        if parts:
            city = parts[-1].strip()
        return f"{city}, NC"
    
    return "NC"


def parse_tournaments(html):
    """
    Parse tournament listings from HTML.
    
    DGS search results structure (as of 2024):
    - Each tournament is in a card/row with tournament link
    - Contains: date, name, tier badge, venue, city, spots info
    """
    soup = BeautifulSoup(html, 'html.parser')
    tournaments = []
    seen_urls = set()
    
    print("  Analyzing page structure...")
    
    # DGS uses tournament cards - look for links to tournament pages
    # Tournament URLs follow pattern: /tournaments/Tournament_Name_Year
    tournament_links = soup.find_all('a', href=re.compile(r'/tournaments/[A-Za-z0-9_-]+(?:_\d{4})?/?$'))
    
    print(f"  Found {len(tournament_links)} potential tournament links")
    
    for link in tournament_links:
        try:
            url = link.get('href', '')
            
            # Skip if we've seen this URL or it's not a tournament
            if not url or url in seen_urls:
                continue
                
            # Skip non-tournament pages
            skip_patterns = ['search', 'North_Carolina', 'PDGA', '/tournaments/$', 'registration']
            if any(pattern in url for pattern in skip_patterns):
                continue
            
            # Make URL absolute
            if url.startswith('/'):
                full_url = DGS_BASE_URL + url
            else:
                full_url = url
                
            seen_urls.add(url)
            
            # Get tournament name from link text
            name = link.get_text(strip=True)
            
            # Skip if name is too short or looks like navigation
            if not name or len(name) < 5:
                continue
            
            skip_keywords = ['privacy', 'terms', 'help', 'contact', 'sign in', 
                           'classic version', 'load more', 'view all', 'cookies']
            if any(kw in name.lower() for kw in skip_keywords):
                continue
            
            # Find the parent container that has all the tournament info
            # Try multiple levels up to find the card/row
            parent = link
            for _ in range(5):
                parent = parent.parent
                if parent is None:
                    break
                parent_text = parent.get_text(separator='|', strip=True)
                
                # Check if this parent contains date info
                if re.search(r'(Mon|Tue|Wed|Thu|Fri|Sat|Sun).*\d{4}', parent_text):
                    break
            
            if parent is None:
                continue
                
            # Get all text from parent, separated to help parsing
            parent_text = parent.get_text(separator='|', strip=True)
            
            # Extract date - look for pattern like "Mon, Jan 19, 2026" or "Sat-Sun, Jan 24-25, 2026"
            date_match = re.search(
                r'((?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)(?:-(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun))?,\s*'
                r'[A-Za-z]{3}\s+\d{1,2}(?:-(?:[A-Za-z]{3}\s+)?\d{1,2})?,\s*\d{4})',
                parent_text
            )
            
            if not date_match:
                # Try simpler date pattern
                date_match = re.search(
                    r'([A-Za-z]{3}\s+\d{1,2},\s*\d{4})',
                    parent_text
                )
            
            if not date_match:
                print(f"    Skipping {name[:30]}... - no date found")
                continue
            
            date_str = date_match.group(1)
            parsed_date = parse_date(date_str)
            
            if not parsed_date:
                print(f"    Skipping {name[:30]}... - could not parse date: {date_str}")
                continue
            
            # Extract tier
            tier = extract_tier(parent_text)
            
            # Extract spots (registration numbers like "10/72")
            spots = extract_spots(parent_text)
            
            # Extract venue and city
            # Look for venue patterns - usually after the date
            # Common pattern: "VenueNameCity, NC" or "Venue Name City, NC"
            city = "NC"
            venue_match = re.search(
                r'(?:at\s+)?([A-Za-z0-9\s\'\-\.]+(?:Park|Course|DGC|Complex|Woods|Creek|Farm|Club|Disc Golf)[A-Za-z\s]*),?\s*([A-Za-z\s]+),\s*(NC|North Carolina)',
                parent_text,
                re.IGNORECASE
            )
            if venue_match:
                city = f"{venue_match.group(2).strip()}, NC"
            else:
                # Try simpler city pattern
                city_match = re.search(r'([A-Za-z\s]+),\s*(NC|North Carolina)', parent_text)
                if city_match:
                    # Get the last word before ", NC" as the city
                    city_text = city_match.group(1).strip()
                    # Split on capital letters to get actual city name
                    parts = re.split(r'(?<=[a-z])(?=[A-Z])', city_text)
                    if parts:
                        city = f"{parts[-1].strip()}, NC"
                    else:
                        city = f"{city_text}, NC"
            
            # Clean up city name
            city = re.sub(r'\s+', ' ', city).strip()
            
            # Calculate distance
            distance = calculate_distance(city)
            
            # Check if GVDG tournament
            is_gvdg = is_gvdg_tournament(name)
            
            # Clean up tournament name
            # Remove tier info that might be in the name
            name = re.sub(r'\s*PDGA\s*(A|B|C|XC)-?[Tt]ier\s*', ' ', name)
            name = re.sub(r'\s*[·•]\s*$', '', name)
            name = re.sub(r'\s+', ' ', name).strip()
            
            tournament = {
                "name": name,
                "date": parsed_date,
                "city": city,
                "tier": tier,
                "url": full_url,
                "distance": distance,
                "isGVDG": is_gvdg,
                "spots": spots
            }
            
            tournaments.append(tournament)
            print(f"  ✓ {name[:40]:<40} | {parsed_date} | {city}")
            
        except Exception as e:
            print(f"  Error parsing element: {e}")
            continue
    
    return tournaments


def deduplicate_tournaments(tournaments):
    """Remove duplicate tournaments based on URL."""
    seen = set()
    unique = []
    
    for t in tournaments:
        if t['url'] not in seen:
            seen.add(t['url'])
            unique.append(t)
    
    return unique


def sort_tournaments(tournaments):
    """Sort tournaments by date."""
    return sorted(tournaments, key=lambda t: t['date'])


def filter_future_tournaments(tournaments, days_back=1):
    """Filter to only include future tournaments (with grace period)."""
    cutoff = datetime.now() - timedelta(days=days_back)
    cutoff_str = cutoff.strftime("%Y-%m-%d")
    
    return [t for t in tournaments if t['date'] >= cutoff_str]


def validate_tournament(t):
    """Validate a single tournament has all required fields with correct types."""
    required_fields = {
        'name': str,
        'date': str,
        'city': str,
        'tier': str,
        'url': str,
        'distance': int,
        'isGVDG': bool,
    }
    
    for field, field_type in required_fields.items():
        if field not in t:
            return False, f"Missing field: {field}"
        if not isinstance(t[field], field_type):
            return False, f"Wrong type for {field}: expected {field_type.__name__}, got {type(t[field]).__name__}"
    
    # Validate date format
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', t['date']):
        return False, f"Invalid date format: {t['date']}"
    
    # Validate URL
    if 'discgolfscene.com' not in t['url']:
        return False, f"Invalid URL: {t['url']}"
    
    # Validate tier
    valid_tiers = ['A', 'B', 'C', 'XC', 'League', 'Doubles', 'Other']
    if t['tier'] not in valid_tiers:
        return False, f"Invalid tier: {t['tier']}"
    
    # Validate name length (catch concatenated garbage)
    if len(t['name']) > 200:
        return False, f"Name too long ({len(t['name'])} chars)"
    
    return True, "OK"


def main():
    """Main scraper function."""
    print("=" * 60)
    print("GVDG Tournament Scraper v2.1")
    print("=" * 60)
    print(f"Location: {CONFIG['location']['name']}")
    print(f"Radius: {CONFIG['distance']} miles")
    print(f"Formats: {', '.join(CONFIG['formats'])}")
    print()
    
    # Build search URL
    search_url = build_search_url()
    print(f"Search URL:\n{search_url}\n")
    
    # Fetch the search results page
    print("Fetching tournaments...")
    try:
        html = fetch_page(search_url)
    except Exception as e:
        print(f"FATAL: Could not fetch search page: {e}")
        sys.exit(1)
    
    # Debug: save HTML for inspection
    with open('debug_page.html', 'w', encoding='utf-8') as f:
        f.write(html)
    print("  (Saved debug_page.html for inspection)")
    
    # Parse tournaments
    print("\nParsing tournaments...")
    tournaments = parse_tournaments(html)
    
    # Validate all tournaments
    print("\nValidating tournaments...")
    valid_tournaments = []
    for t in tournaments:
        is_valid, message = validate_tournament(t)
        if is_valid:
            valid_tournaments.append(t)
        else:
            print(f"  ✗ Invalid: {t.get('name', 'UNKNOWN')[:30]}... - {message}")
    
    print(f"  {len(valid_tournaments)}/{len(tournaments)} passed validation")
    tournaments = valid_tournaments
    
    # Deduplicate
    tournaments = deduplicate_tournaments(tournaments)
    
    # Filter to future tournaments
    tournaments = filter_future_tournaments(tournaments)
    
    # Sort by date
    tournaments = sort_tournaments(tournaments)
    
    print(f"\nFound {len(tournaments)} upcoming tournaments")
    
    if len(tournaments) == 0:
        print("\n⚠️  WARNING: No tournaments found! Check debug_page.html to see what was returned.")
        print("    The website structure may have changed.")
    
    # Build output data
    output = {
        "lastUpdated": datetime.now().isoformat(),
        "searchCenter": CONFIG["location"]["name"],
        "searchRadius": CONFIG["distance"],
        "tournaments": tournaments
    }
    
    # Write to file
    output_file = CONFIG["output_file"]
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    print(f"\nWrote {len(tournaments)} tournaments to {output_file}")
    
    # Print summary
    print("\n" + "=" * 60)
    print("TOURNAMENT SUMMARY")
    print("=" * 60)
    
    gvdg_count = sum(1 for t in tournaments if t['isGVDG'])
    print(f"Total: {len(tournaments)}")
    print(f"GVDG Events: {gvdg_count}")
    print()
    
    for t in tournaments[:10]:  # Show first 10
        gvdg_marker = "⭐ " if t['isGVDG'] else "   "
        print(f"{gvdg_marker}{t['date']} | {t['name'][:40]:<40} | {t['city']}")
    
    if len(tournaments) > 10:
        print(f"   ... and {len(tournaments) - 10} more")
    
    print("\nDone!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
