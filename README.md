# 🥏 GVDG Tournament Scraper

Automatically scrapes disc golf tournaments from [discgolfscene.com](https://www.discgolfscene.com) within **60 miles of Greenville, NC** using their built-in location search filter.

## How It Works

This scraper uses the same search URL that you'd use on the DGS website:

```
https://www.discgolfscene.com/tournaments/search?
  filter[location][name]=Greenville, NC
  filter[location][zip]=27858
  filter[location][latitude]=35.589407
  filter[location][longitude]=-77.351275
  filter[location][distance]=60
  filter[location][units]=mi
  filter[format]=singles,doubles,teams
```

This ensures we get the **exact same results** as browsing the site manually with the 60-mile radius filter.

## Features

- 📍 **Location-Based Search** - Uses DGS's own 60-mile radius filter from Greenville, NC (27858)
- 📅 **Daily Updates** - GitHub Actions runs automatically every day
- ⭐ **GVDG Detection** - Automatically flags GVDG club events  
- 🏆 **Tier Information** - Captures PDGA tier (A, B, C, XC)
- 📊 **JSON Output** - Clean, structured data for your website
- 🔄 **Fallback Data** - If scraping fails, uses known upcoming events

## Quick Start

### 1. Fork/Clone This Repository

### 2. Enable GitHub Actions
- Go to Settings → Actions → General
- Select "Allow all actions and reusable workflows"

### 3. Run Your First Scrape
- Go to Actions tab → "Scrape Tournaments" → "Run workflow"
- Or push a commit to trigger automatically

### 4. Use the Data

The scraper outputs `tournaments.json` with this structure:

```json
{
  "lastUpdated": "2024-12-24T12:00:00.000Z",
  "centerPoint": {
    "name": "Greenville, NC",
    "zip": "27858",
    "lat": 35.589407,
    "lng": -77.351275
  },
  "radiusMiles": 60,
  "totalCount": 15,
  "tournaments": [
    {
      "name": "The Hangover 6 (Morning)",
      "date": "2026-01-01",
      "venue": "West Meadowbrook Park",
      "city": "Greenville, NC",
      "tier": "C",
      "url": "https://www.discgolfscene.com/tournaments/The_Hangover_6_2026",
      "distance": 0,
      "isGVDG": true,
      "spots": "12/72"
    }
  ]
}
```

### 5. Load in Your Website

```javascript
// Fetch from GitHub raw URL
const TOURNAMENTS_URL = 'https://raw.githubusercontent.com/YOUR_USERNAME/gvdg-tournament-scraper/main/tournaments.json';

async function loadTournaments() {
  const response = await fetch(TOURNAMENTS_URL);
  const data = await response.json();
  
  // Render tournaments
  data.tournaments.forEach(tournament => {
    console.log(`${tournament.date}: ${tournament.name} @ ${tournament.city}`);
  });
}
```

## Viewing the Search Results Manually

You can see what the scraper is pulling by visiting this URL:

**[View 60-Mile Search Results](https://www.discgolfscene.com/tournaments/search?filter%5Blocation%5D%5Bcountry%5D=USA&filter%5Blocation%5D%5Bname%5D=Greenville%2C+NC&filter%5Blocation%5D%5Bzip%5D=27858&filter%5Blocation%5D%5Blatitude%5D=35.589407&filter%5Blocation%5D%5Blongitude%5D=-77.351275&filter%5Blocation%5D%5Bdistance%5D=60&filter%5Blocation%5D%5Bunits%5D=mi&filter%5Bformat%5D%5B0%5D=s&filter%5Bformat%5D%5B1%5D=d&filter%5Bformat%5D%5B2%5D=t)**

## Configuration

Edit the `CONFIG` object in `scrape-tournaments.js`:

```javascript
const CONFIG = {
  centerPoint: {
    name: 'Greenville, NC',
    zip: '27858',
    lat: 35.589407,
    lng: -77.351275
  },
  maxDistanceMiles: 60,  // Change radius here
  
  // Keywords to identify GVDG events
  gvdgKeywords: ['GVDG', 'Greenville Disc Golf', 'Hangover', ...]
};
```

## Adding Manual Events

If events aren't being scraped properly, add them to `getManualEvents()`:

```javascript
function getManualEvents() {
  return [
    {
      name: "Your Tournament Name",
      date: "2026-03-15",
      venue: "West Meadowbrook Park",
      city: "Greenville, NC",
      tier: "C",
      url: "https://www.discgolfscene.com/tournaments/...",
      distance: 0,
      isGVDG: true,
      spots: null
    }
  ];
}
```

## Running Locally

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/gvdg-tournament-scraper.git
cd gvdg-tournament-scraper

# Run the scraper (requires Node.js 18+)
node scrape-tournaments.js

# Output saved to tournaments.json
```

## Troubleshooting

**Scraper returns 0 tournaments?**
- Check if discgolfscene.com has changed their HTML structure
- Run locally to see error messages
- Fallback data will be used automatically

**Missing tournaments?**
- Add them to `getManualEvents()` function
- Check the search URL manually to verify they appear

**GitHub Actions not running?**
- Check the Actions tab for error logs
- Ensure workflow file is in `.github/workflows/`

## License

MIT - Feel free to use and modify for your disc golf club!

---

Made with 🥏 for the Greenville Disc Golf community

**Search URL Reference:**
```
https://www.discgolfscene.com/tournaments/search?filter[location][country]=USA&filter[location][name]=Greenville,+NC&filter[location][zip]=27858&filter[location][latitude]=35.589407&filter[location][longitude]=-77.351275&filter[location][distance]=60&filter[location][units]=mi&filter[format][0]=s&filter[format][1]=d&filter[format][2]=t
```
