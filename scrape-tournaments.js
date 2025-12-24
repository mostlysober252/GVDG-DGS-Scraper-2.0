/**
 * GVDG Tournament Scraper
 * 
 * Scrapes disc golf tournaments from discgolfscene.com using their
 * location-based search filter (60 miles from Greenville, NC)
 * 
 * Search URL format:
 * https://www.discgolfscene.com/tournaments/search?filter[location][country]=USA
 *   &filter[location][name]=Greenville,+NC
 *   &filter[location][zip]=27858
 *   &filter[location][latitude]=35.589407
 *   &filter[location][longitude]=-77.351275
 *   &filter[location][distance]=60
 *   &filter[location][units]=mi
 *   &filter[format][0]=s (singles)
 *   &filter[format][1]=d (doubles)
 *   &filter[format][2]=t (teams)
 * 
 * Run manually: node scrape-tournaments.js
 * Or via GitHub Actions on a schedule
 */

const fs = require('fs');
const path = require('path');

// ============================================
// Configuration
// ============================================

const CONFIG = {
  // Greenville, NC coordinates (from the DGS search URL)
  centerPoint: {
    name: 'Greenville, NC',
    zip: '27858',
    lat: 35.589407,
    lng: -77.351275
  },
  maxDistanceMiles: 60,
  
  // The search URL with location filter
  searchUrl: 'https://www.discgolfscene.com/tournaments/search?' + 
    'filter%5Blocation%5D%5Bcountry%5D=USA' +
    '&filter%5Blocation%5D%5Bname%5D=Greenville%2C+NC' +
    '&filter%5Blocation%5D%5Bzip%5D=27858' +
    '&filter%5Blocation%5D%5Blatitude%5D=35.589407' +
    '&filter%5Blocation%5D%5Blongitude%5D=-77.351275' +
    '&filter%5Blocation%5D%5Bdistance%5D=60' +
    '&filter%5Blocation%5D%5Bunits%5D=mi' +
    '&filter%5Bformat%5D%5B0%5D=s' +  // Singles
    '&filter%5Bformat%5D%5B1%5D=d' +  // Doubles
    '&filter%5Bformat%5D%5B2%5D=t',   // Teams
  
  outputFile: 'tournaments.json',
  
  // GVDG-specific keywords to identify club events
  gvdgKeywords: [
    'GVDG', 
    'Greenville Disc Golf', 
    'Hangover', 
    'Mando Madness', 
    'Down East Players Cup', 
    'DEPC',
    'Frozen Bowl',
    'ECU',
    'East Carolina'
  ]
};

// ============================================
// Utility Functions
// ============================================

/**
 * Check if tournament is a GVDG event
 */
function isGVDGEvent(name, venue, city) {
  const searchText = `${name} ${venue || ''} ${city || ''}`.toLowerCase();
  return CONFIG.gvdgKeywords.some(keyword => 
    searchText.includes(keyword.toLowerCase())
  );
}

/**
 * Parse tier from tournament text
 */
function parseTier(text) {
  const tierPatterns = [
    { pattern: /A-tier/i, tier: 'A' },
    { pattern: /B-tier/i, tier: 'B' },
    { pattern: /C-tier/i, tier: 'C' },
    { pattern: /XC-tier/i, tier: 'XC' },
    { pattern: /\bdoubles\b/i, tier: 'Doubles' },
    { pattern: /\bteams?\b/i, tier: 'Teams' },
    { pattern: /\bleague\b/i, tier: 'League' },
  ];
  
  for (const { pattern, tier } of tierPatterns) {
    if (pattern.test(text)) {
      return tier;
    }
  }
  return 'Other';
}

/**
 * Parse date from various formats (e.g., "Sat, Dec 27, 2025" or "Dec 27")
 */
function parseDate(dateText) {
  const months = {
    'jan': '01', 'feb': '02', 'mar': '03', 'apr': '04',
    'may': '05', 'jun': '06', 'jul': '07', 'aug': '08',
    'sep': '09', 'oct': '10', 'nov': '11', 'dec': '12'
  };
  
  // Try to match full date with year: "Sat, Dec 27, 2025"
  let match = dateText.match(/([A-Za-z]{3})[,\s]+(\d{1,2})[,\s]+(\d{4})/i);
  if (match) {
    const month = months[match[1].toLowerCase()];
    const day = match[2].padStart(2, '0');
    const year = match[3];
    return `${year}-${month}-${day}`;
  }
  
  // Try date range: "Dec 27-28" or "Jan 31-Feb 1"
  match = dateText.match(/([A-Za-z]{3})\s+(\d{1,2})(?:-\d{1,2})?/i);
  if (match) {
    const month = months[match[1].toLowerCase()];
    const day = match[2].padStart(2, '0');
    
    // Determine year - if month is before current month, assume next year
    const currentDate = new Date();
    const currentMonth = currentDate.getMonth() + 1;
    const parsedMonth = parseInt(month);
    let year = currentDate.getFullYear();
    
    // If the month is more than 2 months in the past, assume next year
    if (parsedMonth < currentMonth - 2) {
      year += 1;
    }
    
    return `${year}-${month}-${day}`;
  }
  
  return null;
}

/**
 * Extract distance in miles from text like "~38 mi" or "(38 mi)"
 */
function parseDistance(text) {
  const match = text.match(/[~(]?\s*(\d+(?:\.\d+)?)\s*mi/i);
  return match ? Math.round(parseFloat(match[1])) : null;
}

/**
 * Simple HTML entity decoder
 */
function decodeHtmlEntities(text) {
  return text
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&#x27;/g, "'")
    .replace(/&nbsp;/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

// ============================================
// HTML Parsing
// ============================================

/**
 * Parse tournaments from the search results HTML
 */
function parseTournamentsFromHtml(html) {
  const tournaments = [];
  
  // The search results page has tournament cards as <a> links
  // Pattern: <a href="https://www.discgolfscene.com/tournaments/TOURNAMENT_NAME">
  
  // Find all tournament card sections
  // Each card contains: date, name, tier, venue, city, distance, spots
  
  // Match tournament links with their surrounding content
  const cardRegex = /\[([A-Za-z]{3})\s*(\d{1,2}(?:-\d{1,2})?)\s*([A-Za-z]{3}(?:-[A-Za-z]{3})?)?[^\]]*\]\s*\(https:\/\/www\.discgolfscene\.com\/tournaments\/([^)]+)\)/gi;
  
  // Alternative: parse the raw HTML structure
  // Tournament cards appear as links with tournament info
  const tournamentBlockRegex = /<a[^>]*href="(https:\/\/www\.discgolfscene\.com\/tournaments\/[^"]+)"[^>]*>([\s\S]*?)<\/a>/gi;
  
  let match;
  const seenUrls = new Set();
  
  while ((match = tournamentBlockRegex.exec(html)) !== null) {
    const url = match[1];
    const cardContent = match[2];
    
    // Skip duplicate URLs and non-tournament links
    if (seenUrls.has(url) || 
        url.includes('/search') || 
        url.includes('/new') || 
        url.includes('/mine') ||
        url.includes('/options') ||
        url.includes('search-filter')) {
      continue;
    }
    seenUrls.add(url);
    
    // Extract text content
    const text = decodeHtmlEntities(cardContent.replace(/<[^>]+>/g, ' '));
    
    // Skip if too short or doesn't look like a tournament
    if (text.length < 10) continue;
    
    // Try to parse the tournament info
    // Typical format: "Dec 27 Sat Tournament Name PDGA C-tier · Sat, Dec 27, 2025 VenueCity, NC 12/72 2"
    
    // Extract date
    const dateMatch = text.match(/([A-Za-z]{3})\s+(\d{1,2})/);
    if (!dateMatch) continue;
    
    const date = parseDate(text);
    if (!date) continue;
    
    // Extract tournament name (usually after day of week, before venue/tier info)
    let name = '';
    const nameMatch = text.match(/(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)(?:-[A-Za-z]{3})?\s+(.+?)(?:PDGA|·|\d+\s*\/\s*\d+|[A-Z][a-z]+\s+Park|[A-Z][a-z]+\s+DGC)/i);
    if (nameMatch) {
      name = nameMatch[1].trim();
    } else {
      // Fallback: use text between date and first location-like word
      const parts = text.split(/(?:PDGA|Park|DGC|Course|NC|SC)/i);
      if (parts[0]) {
        name = parts[0].replace(/^[A-Za-z]{3}\s+\d{1,2}(?:-\d{1,2})?\s+[A-Za-z]{3}(?:-[A-Za-z]{3})?\s+/, '').trim();
      }
    }
    
    // Clean up name
    name = name
      .replace(/\s+/g, ' ')
      .replace(/^[·\s]+|[·\s]+$/g, '')
      .substring(0, 100);
    
    if (!name || name.length < 3) continue;
    
    // Extract venue and city
    let venue = '';
    let city = '';
    
    // Look for "VenueName City, NC" pattern
    const locationMatch = text.match(/([A-Za-z\s\-'\.]+(?:Park|DGC|Course|Farm|Club|University|College|Church|Center|Complex|Woods|Creek|Haven|Farms|Camp|Campground|Elementary|High School)[A-Za-z\s\-'\.]*)\s*([A-Za-z\s]+,\s*NC)/i);
    if (locationMatch) {
      venue = locationMatch[1].trim();
      city = locationMatch[2].trim();
    } else {
      // Try just city
      const cityMatch = text.match(/([A-Za-z\s]+),\s*NC/i);
      if (cityMatch) {
        city = cityMatch[0].trim();
      }
    }
    
    // Extract tier
    const tier = parseTier(text);
    
    // Extract spots (e.g., "12/72" or "12 / 72")
    let spots = null;
    const spotsMatch = text.match(/(\d+)\s*\/\s*(\d+)/);
    if (spotsMatch) {
      spots = `${spotsMatch[1]}/${spotsMatch[2]}`;
    }
    
    // Extract distance from center
    const distance = parseDistance(text);
    
    // Determine if GVDG event
    const isGVDG = isGVDGEvent(name, venue, city);
    
    tournaments.push({
      name,
      date,
      venue: venue || null,
      city: city || null,
      tier,
      url,
      distance: distance || estimateDistance(city),
      isGVDG,
      spots
    });
  }
  
  return tournaments;
}

/**
 * Estimate distance based on city if not provided
 */
function estimateDistance(city) {
  if (!city) return null;
  
  const cityDistances = {
    'greenville': 0,
    'farmville': 10,
    'ayden': 12,
    'winterville': 5,
    'washington': 25,
    'kinston': 28,
    'new bern': 38,
    'rocky mount': 40,
    'wilson': 45,
    'columbia': 45,
    'maysville': 50,
    'jacksonville': 55,
    'goldsboro': 50,
    'tarboro': 35
  };
  
  const cityLower = city.toLowerCase();
  for (const [name, dist] of Object.entries(cityDistances)) {
    if (cityLower.includes(name)) {
      return dist;
    }
  }
  
  return null;
}

// ============================================
// Main Scraper Function
// ============================================

async function scrapeTournaments() {
  console.log('🥏 GVDG Tournament Scraper');
  console.log('==========================\n');
  console.log(`📍 Center: ${CONFIG.centerPoint.name} (${CONFIG.centerPoint.zip})`);
  console.log(`📏 Radius: ${CONFIG.maxDistanceMiles} miles`);
  console.log(`🌐 Using DGS location search filter\n`);
  
  try {
    // Fetch the search results page
    console.log('⏳ Fetching tournament data from discgolfscene.com...');
    console.log(`   URL: ${CONFIG.searchUrl.substring(0, 80)}...`);
    
    const response = await fetch(CONFIG.searchUrl, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (compatible; GVDG Tournament Scraper)',
        'Accept': 'text/html,application/xhtml+xml',
        'Accept-Language': 'en-US,en;q=0.9'
      }
    });
    
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }
    
    const html = await response.text();
    console.log(`✅ Received ${(html.length / 1024).toFixed(1)}KB of data\n`);
    
    // Parse tournaments from HTML
    console.log('🔍 Parsing tournaments...');
    let tournaments = parseTournamentsFromHtml(html);
    console.log(`   Found ${tournaments.length} tournaments from search results\n`);
    
    // Add manual/fallback events that we know about
    const manualEvents = getManualEvents();
    console.log(`📝 Adding ${manualEvents.length} manually tracked events...`);
    
    // Merge manual events (avoid duplicates by URL)
    const existingUrls = new Set(tournaments.map(t => t.url));
    for (const event of manualEvents) {
      if (!existingUrls.has(event.url)) {
        tournaments.push(event);
        existingUrls.add(event.url);
      }
    }
    
    // Filter out past tournaments
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    
    const upcomingTournaments = tournaments.filter(t => {
      if (!t.date) return false;
      const tournamentDate = new Date(t.date + 'T12:00:00');
      return tournamentDate >= today;
    });
    
    console.log(`   ${tournaments.length - upcomingTournaments.length} past events filtered out\n`);
    
    // Sort by date
    upcomingTournaments.sort((a, b) => new Date(a.date) - new Date(b.date));
    
    // Create output
    const output = {
      lastUpdated: new Date().toISOString(),
      centerPoint: CONFIG.centerPoint,
      radiusMiles: CONFIG.maxDistanceMiles,
      searchUrl: CONFIG.searchUrl,
      totalCount: upcomingTournaments.length,
      tournaments: upcomingTournaments
    };
    
    // Save to file
    const outputPath = path.join(__dirname, CONFIG.outputFile);
    fs.writeFileSync(outputPath, JSON.stringify(output, null, 2));
    
    console.log('✅ Results:');
    console.log(`   ${upcomingTournaments.length} upcoming tournaments within ${CONFIG.maxDistanceMiles} miles`);
    console.log(`   ${upcomingTournaments.filter(t => t.isGVDG).length} GVDG events`);
    console.log(`   Saved to: ${CONFIG.outputFile}\n`);
    
    // Print summary
    console.log('📅 Upcoming Tournaments:');
    console.log('------------------------');
    upcomingTournaments.slice(0, 15).forEach(t => {
      const gvdgBadge = t.isGVDG ? ' ⭐ GVDG' : '';
      const tierBadge = t.tier !== 'Other' ? ` [${t.tier}]` : '';
      console.log(`   ${t.date} | ${t.name.substring(0, 45)}${tierBadge}${gvdgBadge}`);
      if (t.city) {
        console.log(`            📍 ${t.city}${t.distance ? ` (~${t.distance} mi)` : ''}`);
      }
    });
    
    if (upcomingTournaments.length > 15) {
      console.log(`   ... and ${upcomingTournaments.length - 15} more`);
    }
    
    return output;
    
  } catch (error) {
    console.error('❌ Error:', error.message);
    console.log('\n📦 Using fallback data...');
    
    // Return fallback data
    const fallbackData = {
      lastUpdated: new Date().toISOString(),
      centerPoint: CONFIG.centerPoint,
      radiusMiles: CONFIG.maxDistanceMiles,
      error: error.message,
      usingFallback: true,
      totalCount: 0,
      tournaments: getManualEvents().filter(t => {
        const tournamentDate = new Date(t.date + 'T12:00:00');
        return tournamentDate >= new Date();
      }).sort((a, b) => new Date(a.date) - new Date(b.date))
    };
    
    fallbackData.totalCount = fallbackData.tournaments.length;
    
    const outputPath = path.join(__dirname, CONFIG.outputFile);
    fs.writeFileSync(outputPath, JSON.stringify(fallbackData, null, 2));
    
    console.log(`   Saved ${fallbackData.totalCount} fallback events to: ${CONFIG.outputFile}`);
    
    return fallbackData;
  }
}

/**
 * Manual/fallback events - these are reliable events we know about
 * Update this list periodically with known upcoming tournaments
 * Data sourced from: https://www.discgolfscene.com/tournaments/search (60mi from Greenville, NC)
 */
function getManualEvents() {
  return [
    // ==========================================
    // GVDG Events (Greenville - 0 miles)
    // ==========================================
    {
      name: "The Hangover 6 (Morning)",
      date: "2026-01-01",
      venue: "West Meadowbrook Park",
      city: "Greenville, NC",
      tier: "C",
      url: "https://www.discgolfscene.com/tournaments/The_Hangover_6_2026",
      distance: 0,
      isGVDG: true,
      spots: "12/72"
    },
    {
      name: "The Hangover 7 (Afternoon)",
      date: "2026-01-01",
      venue: "West Meadowbrook Park",
      city: "Greenville, NC",
      tier: "C",
      url: "https://www.discgolfscene.com/tournaments/The_Hangover_7_2026",
      distance: 0,
      isGVDG: true,
      spots: "10/72"
    },
    {
      name: "GVDG Frozen Bowl and Chili Cookoff",
      date: "2026-01-24",
      venue: "Farmville Municipal DGC",
      city: "Farmville, NC",
      tier: "Other",
      url: "https://www.discgolfscene.com/tournaments/GVDG_Frozen_Bowl_2025",
      distance: 10,
      isGVDG: true,
      spots: null
    },
    
    // ==========================================
    // Nearby Events (within 60 miles)
    // ==========================================
    {
      name: "2025 Whiskey/Bourbon Open The Bottle",
      date: "2025-12-27",
      venue: "Creek Side",
      city: "New Bern, NC",
      tier: "Other",
      url: "https://www.discgolfscene.com/tournaments/2025_Whiskey_Bourbon_Open_The_Bottle",
      distance: 38,
      isGVDG: false,
      spots: "16"
    },
    {
      name: "The Final 31",
      date: "2025-12-31",
      venue: "Northeast Creek Park",
      city: "Jacksonville, NC",
      tier: "XC",
      url: "https://www.discgolfscene.com/tournaments/The_Final_31_2025",
      distance: 55,
      isGVDG: false,
      spots: "26/60"
    },
    {
      name: "2026 Goat Neck Farms Fling in the New Year",
      date: "2026-01-01",
      venue: "Goat Neck Farms Disc Golf Course",
      city: "Columbia, NC",
      tier: "Other",
      url: "https://www.discgolfscene.com/tournaments/2026_Goat_Neck_Farms_Fling_in_the_New_Year_2026",
      distance: 45,
      isGVDG: false,
      spots: "3"
    },
    {
      name: "White Oak Gold Grand Opening",
      date: "2026-01-24",
      venue: "White Oak River Campground",
      city: "Maysville, NC",
      tier: "Other",
      url: "https://www.discgolfscene.com/tournaments/White_Oak_Gold_Grand_Opening_2025",
      distance: 50,
      isGVDG: false,
      spots: null
    },
    {
      name: "Kings Cup XXI Pro/Am",
      date: "2026-01-31",
      venue: "Barnet Park",
      city: "Kinston, NC",
      tier: "B",
      url: "https://www.discgolfscene.com/tournaments/Kings_Cup_XX_Pro_Am_2026",
      distance: 28,
      isGVDG: false,
      spots: "37/90"
    },
    {
      name: "16th Annual Rocky Mount Ice Bowl",
      date: "2026-02-07",
      venue: "Battle Park DGC",
      city: "Rocky Mount, NC",
      tier: "Other",
      url: "https://www.discgolfscene.com/tournaments/16th_Annual_Rocky_Mount_Ice_Bowl_2026",
      distance: 40,
      isGVDG: false,
      spots: "5/72"
    },
    {
      name: "The Joel Smith Memorial Birdie Shootout Finale",
      date: "2026-09-12",
      venue: "Barnet Park",
      city: "Kinston, NC",
      tier: "Other",
      url: "https://www.discgolfscene.com/tournaments/The_Joel_Smith_Memorial_Finale_2026",
      distance: 28,
      isGVDG: false,
      spots: null
    }
  ];
}

// ============================================
// Run Scraper
// ============================================

scrapeTournaments()
  .then((result) => {
    console.log('\n🎯 Scrape complete!');
    if (result.error) {
      console.log('⚠️  Note: Used fallback data due to fetch error');
    }
    process.exit(0);
  })
  .catch(error => {
    console.error('\n💥 Fatal error:', error);
    process.exit(1);
  });
