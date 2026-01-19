#!/usr/bin/env python3
"""
GVDG Tournament Scraper v3.0
Scrapes tournaments from Disc Golf Scene within 60 miles of Greenville, NC

COMPLETE REWRITE - v3.0 fixes:
- Properly filters out navigation menu items (states/countries)
- Correctly parses individual tournament fields
- Better handling of DGS page structure

Usage:
    python dgs-scraper.py

Output:
    tournaments.json - JSON file with tournament data
"""

import json
import re
import sys
from datetime import datetime, timedelta
from urllib.parse import urlencode, urljoin
import time

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
    "distance": 60,
    "formats": ["s", "d", "t"],
    "gvdg_keywords": [
        "gvdg", "greenville valley", "hangover", "chili bowl",
        "frozen bowl", "ayden founders"
    ],
    "timeout": 30,
    "retry_attempts": 3,
    "retry_delay": 2,
    "output_file": "tournaments.json"
}

DGS_BASE_URL = "https://www.discgolfscene.com"

# ============================================
# URLS THAT ARE NOT TOURNAMENTS (navigation/menu items)
# ============================================
NON_TOURNAMENT_PATHS = {
    # Navigation menu items
    '/tournaments/mine', '/tournaments/new',
    # US States
    '/tournaments/AB', '/tournaments/BC', '/tournaments/MB', '/tournaments/NB',
    '/tournaments/NL', '/tournaments/NS', '/tournaments/ON', '/tournaments/PE',
    '/tournaments/QC', '/tournaments/SK', '/tournaments/YT',
    '/tournaments/AA', '/tournaments/AE', '/tournaments/AP',
    '/tournaments/AL', '/tournaments/AK', '/tournaments/AZ', '/tournaments/AR',
    '/tournaments/CA', '/tournaments/CO', '/tournaments/CT', '/tournaments/DC',
    '/tournaments/DE', '/tournaments/FL', '/tournaments/GA', '/tournaments/HI',
    '/tournaments/ID', '/tournaments/IL', '/tournaments/IN', '/tournaments/IA',
    '/tournaments/KS', '/tournaments/KY', '/tournaments/LA', '/tournaments/ME',
    '/tournaments/MD', '/tournaments/MA', '/tournaments/MI', '/tournaments/MN',
    '/tournaments/MS', '/tournaments/MO', '/tournaments/MT', '/tournaments/NE',
    '/tournaments/NV', '/tournaments/NH', '/tournaments/NJ', '/tournaments/NM',
    '/tournaments/NY', '/tournaments/NC', '/tournaments/ND', '/tournaments/OH',
    '/tournaments/OK', '/tournaments/OR', '/tournaments/PA', '/tournaments/PR',
    '/tournaments/RI', '/tournaments/SC', '/tournaments/SD', '/tournaments/TN',
    '/tournaments/TX', '/tournaments/UT', '/tournaments/VT', '/tournaments/VA',
    '/tournaments/VI', '/tournaments/WA', '/tournaments/WV', '/tournaments/WI',
    '/tournaments/WY',
    # Countries
    '/tournaments/Canada', '/tournaments/USA', '/tournaments/Mexico',
    '/tournaments/Australia', '/tournaments/New_Zealand',
}

# Names that indicate navigation items, not tournaments
NON_TOURNAMENT_NAMES = {
    'my tournaments', '+ new tournament', 'new tournament',
    'alabama', 'alaska', 'arizona', 'arkansas', 'california', 'colorado',
    'connecticut', 'delaware', 'florida', 'georgia', 'hawaii', 'idaho',
    'illinois', 'indiana', 'iowa', 'kansas', 'kentucky', 'louisiana',
    'maine', 'maryland', 'massachusetts', 'michigan', 'minnesota',
    'mississippi', 'missouri', 'montana', 'nebraska', 'nevada',
    'new hampshire', 'new jersey', 'new mexico', 'new york',
    'north carolina', 'north dakota', 'ohio', 'oklahoma', 'oregon',
    'pennsylvania', 'rhode island', 'south carolina', 'south dakota',
    'tennessee', 'texas', 'utah', 'vermont', 'virginia', 'washington',
    'west virginia', 'wisconsin', 'wyoming', 'district of columbia',
    'puerto rico', 'virgin islands',
    # Canadian provinces
    'alberta', 'british columbia', 'manitoba', 'new brunswick',
    'newfoundland', 'nova scotia', 'ontario', 'prince edward island',
    'quebec', 'saskatchewan', 'yukon territory',
    # Armed forces
    'aa armed forces', 'ae armed forces', 'ap armed forces',
    # Countries
    'argentina', 'australia', 'austria', 'belgium', 'brazil', 'canada',
    'china', 'denmark', 'england', 'finland', 'france', 'germany',
    'ireland', 'italy', 'japan', 'mexico', 'netherlands', 'new zealand',
    'norway', 'poland', 'scotland', 'spain', 'sweden', 'switzerland',
    'wales', 'aland islands', 'belize', 'bulgaria', 'cambodia', 'chile',
    'colombia', 'costa rica', 'croatia', 'cyprus', 'czech republic',
    'ecuador', 'el salvador', 'estonia', 'ethiopia', 'greece', 'guatemala',
    'honduras', 'hungary', 'iceland', 'india', 'kenya', 'kosovo', 'kuwait',
    'latvia', 'lithuania', 'luxembourg', 'malawi', 'malaysia', 'mongolia',
    'montenegro', 'nicaragua', 'northern ireland', 'the philippines',
    'panama', 'portugal', 'saudi arabia', 'serbia', 'singapore', 'slovakia',
    'slovenia', 'south africa', 'south korea', 'thailand', 'ukraine',
    'uganda', 'uruguay', 'venezuela', 'vietnam', 'zambia', 'zimbabwe',
}


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
    for i, fmt in enumerate(CONFIG["formats"]):
        params[f"filter[format][{i}]"] = fmt
    
    return f"{DGS_BASE_URL}/tournaments/search?{urlencode(params)}"


def fetch_page(url, attempt=1):
    """Fetch a page with retry logic."""
    headers = {
        "User-Agent": "GVDG Tournament Scraper/3.0 (https://github.com/mostlysober252/GVDG-DGS-Scraper-2.0)",
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


def is_navigation_item(name, url):
    """Check if this looks like a navigation menu item rather than a tournament."""
    if not name or not url:
        return True
    
    # Check URL path
    path = url.replace(DGS_BASE_URL, '')
    if path in NON_TOURNAMENT_PATHS:
        return True
    
    # Check if URL is just a state/country code (2-letter paths)
    if re.match(r'^/tournaments/[A-Z]{2}$', path):
        return True
    
    # Check name against known non-tournament names
    name_lower = name.lower().strip()
    if name_lower in NON_TOURNAMENT_NAMES:
        return True
    
    # Tournament names should have years or specific keywords
    # Navigation items are usually just place names
    if len(name) < 10 and not re.search(r'\d{4}', name):
        # Short name with no year - probably navigation
        if name_lower in NON_TOURNAMENT_NAMES:
            return True
    
    return False


def parse_date(date_text):
    """Parse date text to YYYY-MM-DD format."""
    if not date_text:
        return None
    
    date_text = date_text.strip()
    
    # Remove day-of-week prefix
    date_text = re.sub(r'^[A-Za-z]{3}(-[A-Za-z]{3})?,\s*', '', date_text)
    
    # Handle multi-day: "Jan 31-Feb 1, 2026" or "Mar 20-22, 2026"
    match = re.match(r'([A-Za-z]{3})\s+(\d{1,2})-(?:[A-Za-z]{3}\s+)?\d{1,2},\s*(\d{4})', date_text)
    if match:
        date_text = f"{match.group(1)} {match.group(2)}, {match.group(3)}"
    
    # Parse
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
    return "Other"


def extract_spots(text):
    """Extract registration spots like '10/72'."""
    if not text:
        return None
    match = re.search(r'(\d+)\s*/\s*(\d+)', text)
    return f"{match.group(1)}/{match.group(2)}" if match else None


def is_gvdg_tournament(name):
    """Check if tournament is GVDG-hosted."""
    if not name:
        return False
    name_lower = name.lower()
    return any(kw in name_lower for kw in CONFIG["gvdg_keywords"])


def calculate_distance(city):
    """Calculate approximate distance from Greenville, NC."""
    if not city:
        return 30
    
    known = {
        "greenville": 0, "farmville": 10, "ayden": 10, "winterville": 5,
        "kinston": 28, "rocky mount": 40, "wilson": 35, "jacksonville": 50,
        "richlands": 55, "maysville": 50, "new bern": 40, "zebulon": 55,
        "raleigh": 80, "goldsboro": 45, "cary": 75,
    }
    
    city_lower = city.lower()
    for known_city, dist in known.items():
        if known_city in city_lower:
            return dist
    return 30


def parse_tournaments(html):
    """Parse tournament listings from HTML."""
    soup = BeautifulSoup(html, 'html.parser')
    tournaments = []
    seen_urls = set()
    
    print("  Parsing page...")
    
    # Find all links that look like tournament pages
    # Tournament URLs: /tournaments/Tournament_Name_2026
    links = soup.find_all('a', href=re.compile(r'/tournaments/[A-Za-z0-9_-]+(?:_\d{4})?/?$'))
    
    print(f"  Found {len(links)} potential links")
    
    for link in links:
        try:
            href = link.get('href', '')
            if not href:
                continue
            
            # Build full URL
            url = urljoin(DGS_BASE_URL, href)
            
            # Skip if already seen
            if url in seen_urls:
                continue
            seen_urls.add(url)
            
            # Get name from link text
            name = link.get_text(strip=True)
            
            # Skip navigation items
            if is_navigation_item(name, url):
                continue
            
            # Skip very short names or obvious non-tournaments
            if not name or len(name) < 5:
                continue
            
            # Skip if name looks like it contains concatenated data
            # (this is a sign the scraper grabbed wrong element)
            if 'Mon,' in name or 'Tue,' in name or 'Wed,' in name or \
               'Thu,' in name or 'Fri,' in name or 'Sat,' in name or 'Sun,' in name:
                # This name has date info embedded - it's concatenated
                # Try to extract just the tournament name
                # Pattern: "Jan19MonTournament Name · Day, Date..."
                # We want just "Tournament Name"
                
                # Try to find the actual tournament name
                # Usually after the day abbreviation and before the interpunct
                match = re.search(r'(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)([A-Z][^·]+?)(?:\s*·|PDGA|$)', name)
                if match:
                    name = match.group(1).strip()
                else:
                    # Can't extract clean name, skip
                    continue
            
            # Find parent container for context
            parent = link.find_parent(['div', 'li', 'article', 'tr'])
            if parent is None:
                parent = link
            
            parent_text = parent.get_text(separator=' ', strip=True)
            
            # Extract date
            date_match = re.search(
                r'(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)(?:-(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun))?,\s*'
                r'([A-Za-z]{3}\s+\d{1,2}(?:-(?:[A-Za-z]{3}\s+)?\d{1,2})?,\s*\d{4})',
                parent_text
            )
            
            if not date_match:
                # Try simpler pattern
                date_match = re.search(r'([A-Za-z]{3}\s+\d{1,2},\s*\d{4})', parent_text)
            
            if not date_match:
                continue
            
            parsed_date = parse_date(date_match.group(1) if date_match.lastindex else date_match.group(0))
            if not parsed_date:
                continue
            
            # Extract city - look for "City, NC" pattern
            city = "NC"
            city_match = re.search(r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?),\s*NC', parent_text)
            if city_match:
                city = f"{city_match.group(1)}, NC"
            
            # Extract tier and spots
            tier = extract_tier(parent_text)
            spots = extract_spots(parent_text)
            distance = calculate_distance(city)
            is_gvdg = is_gvdg_tournament(name)
            
            # Clean up name
            name = re.sub(r'\s*PDGA\s*(Flex\s*)?(A|B|C|XC)-?[Tt]ier\s*', ' ', name)
            name = re.sub(r'\s*·.*$', '', name)  # Remove everything after interpunct
            name = re.sub(r'\s+', ' ', name).strip()
            
            # Final validation
            if len(name) < 5 or len(name) > 200:
                continue
            
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
            gvdg_mark = "⭐ " if is_gvdg else "   "
            print(f"  {gvdg_mark}{name[:40]:<40} | {parsed_date} | {city}")
            
        except Exception as e:
            print(f"  Error parsing: {e}")
            continue
    
    return tournaments


def validate_tournament(t):
    """Validate tournament data structure."""
    required = {
        'name': str, 'date': str, 'city': str, 'tier': str,
        'url': str, 'distance': int, 'isGVDG': bool
    }
    
    for field, ftype in required.items():
        if field not in t or not isinstance(t[field], ftype):
            return False, f"Bad {field}"
    
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', t['date']):
        return False, "Bad date format"
    
    if 'discgolfscene.com' not in t['url']:
        return False, "Bad URL"
    
    if t['tier'] not in ['A', 'B', 'C', 'XC', 'League', 'Doubles', 'Other']:
        return False, "Bad tier"
    
    if len(t['name']) > 200:
        return False, "Name too long"
    
    return True, "OK"


def main():
    """Main function."""
    print("=" * 60)
    print("GVDG Tournament Scraper v3.0")
    print("=" * 60)
    print(f"Location: {CONFIG['location']['name']}")
    print(f"Radius: {CONFIG['distance']} miles")
    print()
    
    search_url = build_search_url()
    print(f"Search URL:\n{search_url}\n")
    
    print("Fetching tournaments...")
    try:
        html = fetch_page(search_url)
    except Exception as e:
        print(f"FATAL: {e}")
        sys.exit(1)
    
    # Save for debugging
    with open('debug_page.html', 'w', encoding='utf-8') as f:
        f.write(html)
    print("  (Saved debug_page.html)")
    
    print("\nParsing tournaments...")
    tournaments = parse_tournaments(html)
    
    # Validate
    print("\nValidating...")
    valid = []
    for t in tournaments:
        ok, msg = validate_tournament(t)
        if ok:
            valid.append(t)
        else:
            print(f"  ✗ {t.get('name', '?')[:30]}... - {msg}")
    
    print(f"  {len(valid)}/{len(tournaments)} valid")
    
    # Deduplicate by URL
    seen = set()
    unique = []
    for t in valid:
        if t['url'] not in seen:
            seen.add(t['url'])
            unique.append(t)
    
    # Filter future only
    cutoff = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    future = [t for t in unique if t['date'] >= cutoff]
    
    # Sort by date
    future.sort(key=lambda t: t['date'])
    
    print(f"\nFound {len(future)} upcoming tournaments")
    
    # Output
    output = {
        "lastUpdated": datetime.now().isoformat(),
        "searchCenter": CONFIG["location"]["name"],
        "searchRadius": CONFIG["distance"],
        "tournaments": future
    }
    
    with open(CONFIG["output_file"], 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    print(f"Wrote to {CONFIG['output_file']}")
    
    # Summary
    print("\n" + "=" * 60)
    gvdg_count = sum(1 for t in future if t['isGVDG'])
    print(f"Total: {len(future)} | GVDG: {gvdg_count}")
    print("=" * 60)
    
    for t in future[:10]:
        mark = "⭐ " if t['isGVDG'] else "   "
        print(f"{mark}{t['date']} | {t['name'][:40]:<40} | {t['city']}")
    
    if len(future) > 10:
        print(f"   ... and {len(future) - 10} more")
    
    print("\nDone!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
