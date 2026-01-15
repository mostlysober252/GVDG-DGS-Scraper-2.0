#!/usr/bin/env python3
"""
GVDG Tournament Scraper v2.0
Scrapes tournaments from Disc Golf Scene within 60 miles of Greenville, NC

This script is designed to run via GitHub Actions on a schedule.
It outputs tournaments.json which is consumed by the GVDG website.

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
        "hangover",  # The Hangover tournaments
        "chili bowl",
        "frozen bowl",
        "ayden founders"  # GVDG helps organize this one
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
        "User-Agent": "GVDG Tournament Scraper/2.0 (https://github.com/mostlysober252/GVDG-DGS-Scraper-2.0)",
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
    
    Returns the START date in YYYY-MM-DD format.
    """
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


def extract_distance(text):
    """Extract distance in miles from tournament listing."""
    # Look for patterns like "~45 mi" or "45mi" or "45 miles"
    match = re.search(r'~?(\d+)\s*mi', text, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return 0


def extract_spots(text):
    """Extract registration spots info like '10/72' or '90/90'."""
    match = re.search(r'(\d+)\s*/\s*(\d+)', text)
    if match:
        return f"{match.group(1)}/{match.group(2)}"
    return None


def is_gvdg_tournament(name):
    """Check if tournament is GVDG-hosted based on name."""
    name_lower = name.lower()
    return any(keyword in name_lower for keyword in CONFIG["gvdg_keywords"])


def calculate_distance(city):
    """
    Calculate approximate distance from Greenville, NC to a city.
    This is a rough estimate based on known distances.
    For production, you'd want to use a geocoding API.
    """
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
    }
    
    city_lower = city.lower()
    for known_city, distance in known_distances.items():
        if known_city in city_lower:
            return distance
    
    # Default to middle of search radius if unknown
    return 30


def parse_tournaments(html):
    """Parse tournament listings from HTML."""
    soup = BeautifulSoup(html, 'html.parser')
    tournaments = []
    
    # Find all tournament entries
    # DGS uses various structures, so we need to be flexible
    
    # Look for tournament links/cards
    tournament_elements = soup.find_all('a', href=re.compile(r'/tournaments/[^/]+$'))
    
    seen_urls = set()
    
    for elem in tournament_elements:
        try:
            # Get the tournament URL
            url = elem.get('href', '')
            if not url or url in seen_urls:
                continue
            
            # Make URL absolute
            if url.startswith('/'):
                url = DGS_BASE_URL + url
            
            seen_urls.add(url)
            
            # Get the parent container for more context
            parent = elem.find_parent(['div', 'li', 'article']) or elem
            parent_text = parent.get_text(separator=' ', strip=True)
            
            # Extract tournament name
            name = elem.get_text(strip=True)
            if not name or len(name) < 3:
                continue
            
            # Skip non-tournament links
            skip_keywords = ['privacy', 'terms', 'help', 'contact', 'sign in', 'classic version']
            if any(kw in name.lower() for kw in skip_keywords):
                continue
            
            # Extract date from parent context
            date_match = re.search(
                r'((?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)(?:-(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun))?,\s*)?'
                r'([A-Za-z]{3})\s+(\d{1,2})(?:-(?:[A-Za-z]{3}\s+)?\d{1,2})?,\s*(\d{4})',
                parent_text
            )
            
            if not date_match:
                continue
            
            date_str = date_match.group(0)
            parsed_date = parse_date(date_str)
            
            if not parsed_date:
                continue
            
            # Extract city/location
            city_match = re.search(r'([A-Za-z\s]+),\s*(NC|North Carolina)', parent_text)
            city = city_match.group(1).strip() + ", NC" if city_match else "NC"
            
            # Extract other info
            tier = extract_tier(parent_text)
            spots = extract_spots(parent_text)
            distance = calculate_distance(city)
            is_gvdg = is_gvdg_tournament(name)
            
            tournament = {
                "name": name,
                "date": parsed_date,
                "city": city,
                "tier": tier,
                "url": url,
                "distance": distance,
                "isGVDG": is_gvdg,
                "spots": spots
            }
            
            tournaments.append(tournament)
            print(f"  Found: {name} ({parsed_date}) - {city}")
            
        except Exception as e:
            print(f"  Error parsing tournament element: {e}")
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


def main():
    """Main scraper function."""
    print("=" * 60)
    print("GVDG Tournament Scraper v2.0")
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
    
    # Parse tournaments
    print("\nParsing tournaments...")
    tournaments = parse_tournaments(html)
    
    # Deduplicate
    tournaments = deduplicate_tournaments(tournaments)
    
    # Filter to future tournaments
    tournaments = filter_future_tournaments(tournaments)
    
    # Sort by date
    tournaments = sort_tournaments(tournaments)
    
    print(f"\nFound {len(tournaments)} upcoming tournaments")
    
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
