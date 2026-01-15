// ============================================
// Tournament Feed from Disc Golf Scene
// OPTIMIZED VERSION - v2.0
// ============================================
// 
// IMPROVEMENTS OVER ORIGINAL:
// ✓ Consistent date handling (fixes timezone bugs)
// ✓ Retry logic with exponential backoff
// ✓ Smarter cache validation
// ✓ Error state UI for users
// ✓ Request timeout protection
// ✓ Background cache refresh
// ✓ Performance optimizations (Map lookups, single-pass filtering)
// ✓ Better debugging with data source indicators
//
// ============================================

(function() {
    'use strict';
    
    // ============================================
    // CONFIGURATION
    // ============================================
    const CONFIG = {
        // Primary data URL (GitHub raw)
        jsonUrl: 'https://raw.githubusercontent.com/mostlysober252/GVDG-DGS-Scraper-2.0/main/tournaments.json',
        
        // Cache settings
        cacheHours: 6,
        cacheKey: 'gvdg_tournaments_v2', // Changed key to avoid conflicts with old cache
        
        // Retry settings
        maxRetries: 2,
        retryDelayMs: 1000,
        
        // Request timeout (ms) - prevents hanging on slow connections
        fetchTimeout: 8000
    };
    
    // ============================================
    // FALLBACK DATA
    // Used when fetch fails and no cache exists
    // ============================================
    const FALLBACK_TOURNAMENTS = [
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
        }
    ];
    
    // ============================================
    // DOM ELEMENTS (cached for performance)
    // ============================================
    const grid = document.getElementById('tournamentGrid');
    const filterBtns = document.querySelectorAll('.filter-tab');
    
    // ============================================
    // STATE
    // ============================================
    let tournaments = [];
    let currentFilter = 'all';
    let lastUpdated = null;
    let dataSource = 'none'; // 'live', 'cache', 'fallback'
    
    // ============================================
    // DATE UTILITIES
    // Key fix: Consistent date handling prevents timezone bugs
    // ============================================
    
    /**
     * Normalize date string to start of day (midnight)
     * This fixes the bug where tournaments on "today" could be
     * incorrectly marked as past due to time comparison
     */
    function normalizeDate(dateStr) {
        const date = new Date(dateStr + 'T00:00:00');
        date.setHours(0, 0, 0, 0);
        return date;
    }
    
    /**
     * Get today's date normalized to midnight
     */
    function getToday() {
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        return today;
    }
    
    /**
     * Check if a tournament date is in the past
     * Uses normalized dates for consistent comparison
     */
    function isPastTournament(dateStr) {
        return normalizeDate(dateStr) < getToday();
    }
    
    /**
     * Format date for display in tournament cards
     */
    function formatDate(dateStr) {
        const date = normalizeDate(dateStr);
        const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
        return {
            day: date.getDate(),
            month: months[date.getMonth()],
            year: date.getFullYear()
        };
    }
    
    // ============================================
    // TIER UTILITIES
    // Using Map for O(1) lookups instead of object
    // ============================================
    const tierClassMap = new Map([
        ['A', 'tier-a'],
        ['B', 'tier-b'],
        ['C', 'tier-c'],
        ['XC', 'tier-xc'],
        ['League', 'tier-league'],
        ['Doubles', 'tier-other'],
        ['Other', 'tier-other']
    ]);
    
    function getTierClass(tier) {
        return tierClassMap.get(tier) || 'tier-other';
    }
    
    function getTierLabel(tier) {
        if (tier === 'Other' || tier === 'Doubles') return tier;
        if (tier === 'XC') return 'XC-Tier';
        return tier + '-Tier';
    }
    
    // ============================================
    // UI RENDERING
    // ============================================
    
    function showLoading() {
        grid.innerHTML = `
            <div class="tournament-loading" style="grid-column: 1 / -1;">
                <div class="spinner"></div>
                <p>Loading tournaments...</p>
            </div>
        `;
    }
    
    /**
     * NEW: Show error state to users
     * Original version had no error UI
     */
    function showError(message) {
        grid.innerHTML = `
            <div class="tournament-error" style="grid-column: 1 / -1; text-align: center; padding: 2rem;">
                <p style="color: var(--primary); font-size: 1.5rem; margin-bottom: 0.5rem;">⚠️</p>
                <p style="color: var(--text-secondary);">${message}</p>
                <p style="margin-top: 1rem;">
                    <a href="https://www.discgolfscene.com/tournaments/North_Carolina" 
                       target="_blank" rel="noopener noreferrer" 
                       style="color: var(--primary); text-decoration: underline;">
                        Browse tournaments on Disc Golf Scene →
                    </a>
                </p>
            </div>
        `;
    }
    
    /**
     * Create tournament card HTML
     * Optimized: pre-compute values outside template literal
     */
    function createTournamentCard(tournament) {
        const dateInfo = formatDate(tournament.date);
        const isPast = isPastTournament(tournament.date);
        const spotsHTML = tournament.spots ? `<span class="tournament-spots">${tournament.spots}</span>` : '';
        const tierLabel = tournament.isGVDG ? '⭐ GVDG' : getTierLabel(tournament.tier);
        
        return `
            <div class="tournament-card ${isPast ? 'past' : ''}" onclick="window.open('${tournament.url}', '_blank')">
                <div class="tournament-card-header">
                    <div class="tournament-date-badge">
                        <div class="day">${dateInfo.day}</div>
                        <div class="month">${dateInfo.month}</div>
                        <div class="year">${dateInfo.year}</div>
                    </div>
                    <div class="tournament-details">
                        <h4 class="tournament-name">${tournament.name}</h4>
                        <p class="tournament-location">📍 ${tournament.city}</p>
                    </div>
                </div>
                <div class="tournament-card-footer">
                    <span class="tournament-tier ${getTierClass(tournament.tier)}">${tierLabel}</span>
                    <span class="tournament-distance">~${tournament.distance} mi</span>
                    ${spotsHTML}
                </div>
                <a href="${tournament.url}" target="_blank" rel="noopener noreferrer" class="tournament-card-link" onclick="event.stopPropagation()">
                    View on Disc Golf Scene →
                </a>
            </div>
        `;
    }
    
    // ============================================
    // FILTERING & RENDERING
    // ============================================
    
    /**
     * Filter tournaments based on selected category
     * Optimized: Single-pass filter combining date check and category
     */
    function filterTournaments(filter) {
        const today = getToday();
        
        // Single-pass filter (more efficient than multiple filters)
        let filtered = tournaments.filter(t => {
            // Filter out past tournaments (using consistent date comparison)
            if (normalizeDate(t.date) < today) return false;
            
            // Apply category filter
            if (filter === 'gvdg') return t.isGVDG;
            if (filter === 'pdga') return ['A', 'B', 'C', 'XC'].includes(t.tier);
            return true; // 'all' filter
        });
        
        // Sort by date (ascending)
        filtered.sort((a, b) => normalizeDate(a.date) - normalizeDate(b.date));
        
        return filtered;
    }
    
    function renderTournaments(filter = 'all') {
        const filtered = filterTournaments(filter);
        
        if (filtered.length === 0) {
            grid.innerHTML = `
                <div class="no-tournaments" style="grid-column: 1 / -1;">
                    <p>No upcoming tournaments found for this filter.</p>
                    <p style="margin-top: 0.5rem;">
                        <a href="https://www.discgolfscene.com/tournaments/North_Carolina" 
                           target="_blank" rel="noopener noreferrer" style="color: var(--primary);">
                            Browse all NC tournaments on Disc Golf Scene →
                        </a>
                    </p>
                </div>
            `;
        } else {
            // Build HTML in one go (more efficient than multiple DOM updates)
            grid.innerHTML = filtered.map(createTournamentCard).join('');
        }
    }
    
    // ============================================
    // CACHING (Enhanced)
    // ============================================
    
    /**
     * Get cached data with validation
     * Enhanced: Validates data structure, clears corrupted cache
     */
    function getCachedData() {
        try {
            const cached = localStorage.getItem(CONFIG.cacheKey);
            if (!cached) return null;
            
            const data = JSON.parse(cached);
            
            // Check cache age
            const cacheAgeHours = (Date.now() - data.cachedAt) / (1000 * 60 * 60);
            if (cacheAgeHours >= CONFIG.cacheHours) {
                console.log('📦 Cache expired');
                return null;
            }
            
            // Validate data structure
            if (!Array.isArray(data.tournaments) || data.tournaments.length === 0) {
                console.warn('⚠️ Invalid cache data structure');
                return null;
            }
            
            return data;
        } catch (e) {
            console.warn('⚠️ Cache read error:', e);
            // Clear corrupted cache
            try { localStorage.removeItem(CONFIG.cacheKey); } catch {}
            return null;
        }
    }
    
    /**
     * Save data to cache
     */
    function setCachedData(data) {
        try {
            const cacheData = {
                tournaments: data.tournaments,
                lastUpdated: data.lastUpdated,
                cachedAt: Date.now()
            };
            localStorage.setItem(CONFIG.cacheKey, JSON.stringify(cacheData));
        } catch (e) {
            console.warn('⚠️ Cache write error:', e);
        }
    }
    
    // ============================================
    // DATA FETCHING (Enhanced with retry & timeout)
    // ============================================
    
    /**
     * NEW: Fetch with timeout protection
     * Prevents hanging on slow/unresponsive servers
     */
    async function fetchWithTimeout(url, timeoutMs) {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
        
        try {
            const response = await fetch(url, { signal: controller.signal });
            clearTimeout(timeoutId);
            return response;
        } catch (error) {
            clearTimeout(timeoutId);
            throw error;
        }
    }
    
    /**
     * NEW: Fetch with exponential backoff retry
     * Handles transient network failures gracefully
     */
    async function fetchWithRetry(url, retries = CONFIG.maxRetries) {
        let lastError;
        
        for (let attempt = 0; attempt <= retries; attempt++) {
            try {
                if (attempt > 0) {
                    // Exponential backoff: 1s, 2s, 4s...
                    const delay = CONFIG.retryDelayMs * Math.pow(2, attempt - 1);
                    console.log(`🔄 Retry attempt ${attempt} after ${delay}ms`);
                    await new Promise(resolve => setTimeout(resolve, delay));
                }
                
                const response = await fetchWithTimeout(url, CONFIG.fetchTimeout);
                
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }
                
                return await response.json();
            } catch (error) {
                lastError = error;
                console.warn(`❌ Fetch attempt ${attempt + 1} failed:`, error.message);
            }
        }
        
        throw lastError;
    }
    
    /**
     * Main load function
     * Strategy: Cache → Fresh fetch → Fallback
     */
    async function loadTournaments() {
        showLoading();
        
        // 1. Check cache first (fast path)
        const cached = getCachedData();
        if (cached) {
            console.log('✅ Using cached tournament data');
            tournaments = cached.tournaments;
            lastUpdated = cached.lastUpdated;
            dataSource = 'cache';
            initializeUI();
            
            // Background refresh if cache is getting stale (>50% of cache lifetime)
            const cacheAgeHours = (Date.now() - cached.cachedAt) / (1000 * 60 * 60);
            if (cacheAgeHours > CONFIG.cacheHours * 0.5) {
                console.log('📦 Cache getting stale, refreshing in background...');
                backgroundRefresh();
            }
            return;
        }
        
        // 2. Try to fetch fresh data
        try {
            const data = await fetchWithRetry(CONFIG.jsonUrl);
            
            if (!data.tournaments || !Array.isArray(data.tournaments)) {
                throw new Error('Invalid data format');
            }
            
            tournaments = data.tournaments;
            lastUpdated = data.lastUpdated;
            dataSource = 'live';
            
            // Cache the fresh data
            setCachedData(data);
            
            console.log(`✅ Loaded ${tournaments.length} tournaments from live JSON`);
        } catch (error) {
            console.warn('❌ Failed to load tournaments.json:', error.message);
            
            // 3. Use fallback data
            tournaments = FALLBACK_TOURNAMENTS;
            lastUpdated = null;
            dataSource = 'fallback';
            
            console.log('⚠️ Using fallback tournament data');
        }
        
        initializeUI();
    }
    
    /**
     * NEW: Background refresh without blocking UI
     * Updates cache silently for next page load
     */
    async function backgroundRefresh() {
        try {
            const data = await fetchWithRetry(CONFIG.jsonUrl);
            if (data.tournaments && Array.isArray(data.tournaments)) {
                setCachedData(data);
                console.log('✅ Background cache refresh complete');
            }
        } catch (error) {
            console.warn('⚠️ Background refresh failed:', error.message);
        }
    }
    
    // ============================================
    // INITIALIZATION
    // ============================================
    
    function initializeUI() {
        // Render tournaments
        renderTournaments(currentFilter);
        
        // Setup filter buttons
        filterBtns.forEach(btn => {
            btn.addEventListener('click', function() {
                filterBtns.forEach(b => b.classList.remove('active'));
                this.classList.add('active');
                currentFilter = this.dataset.filter;
                renderTournaments(currentFilter);
            });
        });
        
        // Add data freshness note
        updateFreshnessNote();
    }
    
    /**
     * Enhanced: Shows data source indicator for debugging
     */
    function updateFreshnessNote() {
        const feedHeader = document.querySelector('.tournament-feed-header');
        if (!feedHeader) return;
        
        // Remove any existing note
        const existingNote = feedHeader.querySelector('.data-freshness-note');
        if (existingNote) existingNote.remove();
        
        // Build note
        const note = document.createElement('p');
        note.className = 'data-freshness-note';
        note.style.cssText = 'font-size: 0.75rem; color: var(--text-muted); margin-top: 0.5rem; opacity: 0.7;';
        
        let noteText = 'Data from <a href="https://www.discgolfscene.com" target="_blank" rel="noopener noreferrer" style="color: var(--primary);">discgolfscene.com</a>.';
        
        if (lastUpdated) {
            const updated = new Date(lastUpdated);
            noteText += ` Last updated: ${updated.toLocaleDateString()}.`;
        }
        
        // Data source indicator (helpful for debugging)
        if (dataSource === 'cache') {
            noteText += ' <span title="Data loaded from browser cache">📦</span>';
        } else if (dataSource === 'fallback') {
            noteText += ' <span title="Using backup data - live feed unavailable" style="color: var(--accent);">⚠️ Backup data</span>';
        }
        
        noteText += ' For current info, visit event pages directly.';
        note.innerHTML = noteText;
        
        const headerDiv = feedHeader.querySelector('div');
        if (headerDiv) headerDiv.appendChild(note);
    }
    
    // ============================================
    // START
    // ============================================
    loadTournaments();
})();
