"""
Smart Track Scoring & Filtering for "This Is" Playlists

Optimizes payload size for LLM compatibility and token cost efficiency by intelligently 
scoring and filtering source tracks based on user listening behavior.
"""

import re
import random
from datetime import datetime
from typing import List, Dict, Tuple, Any, Optional


def score_tracks_by_user_engagement(tracks: List[Dict], library_stats: Dict) -> List[Tuple[float, Dict]]:
    """
    Score tracks based on user's listening behavior.
    Returns list of (score, track) tuples sorted by score descending.
    
    Args:
        tracks: List of track objects to score
        library_stats: Dict containing user's library statistics:
            - max_play_count: Highest play count in library
            - max_playlist_appearances: Most appearances any track has
            
    Returns:
        List of (score, track) tuples, sorted descending by score
    """
    scored_tracks = []
    
    # Initialize counters for detailed logging
    engagement_stats = {
        'total_tracks': len(tracks),
        'loved_tracks': 0,
        'rated_tracks': 0,
        'tracks_with_plays': 0,
        'tracks_in_playlists': 0,
        'recent_tracks': 0,
        'total_play_count': 0,
        'total_playlist_appearances': 0,
        'max_score': 0,
        'min_score': float('inf'),
        'avg_score': 0
    }
    
    total_score = 0
    
    for track in tracks:
        score = 0.0
        track_breakdown = {}  # For detailed per-track logging if needed
        
        # Play count (normalize to 0-100 scale)
        play_count = track.get('play_count', 0)
        if play_count > 0:
            engagement_stats['tracks_with_plays'] += 1
            engagement_stats['total_play_count'] += play_count
            
        if library_stats.get('max_play_count', 0) > 0:
            normalized_plays = (play_count / library_stats['max_play_count']) * 100
            score += normalized_plays
            track_breakdown['play_score'] = normalized_plays
        
        # Loved/hearted tracks (high value binary signal)
        if track.get('loved', False) or track.get('favorited', False):
            score += 50
            engagement_stats['loved_tracks'] += 1
            track_breakdown['loved_bonus'] = 50
        
        # Star ratings (0-5 scale, normalize to 0-50)
        rating = track.get('rating', 0)
        if rating > 0:
            engagement_stats['rated_tracks'] += 1
            score += rating * 10
            track_breakdown['rating_score'] = rating * 10
        
        # Playlist appearances (cap at 50 to avoid over-weighting)
        playlist_count = track.get('playlist_appearances', 0)
        if playlist_count > 0:
            engagement_stats['tracks_in_playlists'] += 1
            engagement_stats['total_playlist_appearances'] += playlist_count
            
        playlist_score = min(playlist_count * 5, 50)
        score += playlist_score
        track_breakdown['playlist_score'] = playlist_score
        
        # Optional: Recency bonus (tracks played in last 30 days)
        # Only include if last_played data is available
        if track.get('last_played'):
            try:
                # Handle both string and datetime objects
                if isinstance(track['last_played'], str):
                    last_played_date = datetime.fromisoformat(track['last_played'].replace('Z', '+00:00'))
                else:
                    last_played_date = track['last_played']
                
                days_since = (datetime.now() - last_played_date.replace(tzinfo=None)).days
                if days_since <= 30:
                    recency_bonus = max(0, 30 - days_since)
                    score += recency_bonus
                    engagement_stats['recent_tracks'] += 1
                    track_breakdown['recency_bonus'] = recency_bonus
            except (ValueError, TypeError):
                # Skip recency bonus if date parsing fails
                pass
        
        scored_tracks.append((score, track))
        
        # Update score statistics
        total_score += score
        engagement_stats['max_score'] = max(engagement_stats['max_score'], score)
        engagement_stats['min_score'] = min(engagement_stats['min_score'], score)
    
    # Calculate average score
    engagement_stats['avg_score'] = total_score / len(tracks) if tracks else 0
    if engagement_stats['min_score'] == float('inf'):
        engagement_stats['min_score'] = 0
    
    # Sort by score descending
    scored_tracks.sort(reverse=True, key=lambda x: x[0])
    
    # Log detailed engagement statistics
    print(f"🎯 SCORING ANALYSIS:")
    print(f"   📊 Sourced {engagement_stats['total_tracks']} tracks for analysis")
    print(f"   ❤️  Found {engagement_stats['loved_tracks']} loved/favorited tracks")
    print(f"   ⭐ Found {engagement_stats['rated_tracks']} rated tracks")
    print(f"   🎵 Found {engagement_stats['tracks_with_plays']} tracks with play counts (total: {engagement_stats['total_play_count']} plays)")
    print(f"   📋 Found {engagement_stats['tracks_in_playlists']} tracks in playlists (total: {engagement_stats['total_playlist_appearances']} appearances)")
    print(f"   🕐 Found {engagement_stats['recent_tracks']} recently played tracks (last 30 days)")
    print(f"   🏆 Score range: {engagement_stats['max_score']:.1f} - {engagement_stats['min_score']:.1f} (avg: {engagement_stats['avg_score']:.1f})")
    
    return scored_tracks


def calculate_filter_threshold(target_playlist_size: int, ollama_max_tracks: Optional[int] = None) -> int:
    """
    Calculate optimal multiplier for filtering source tracks.
    
    Rationale: As playlist size increases, we can use a lower multiplier
    because probability of capturing high-quality tracks increases.
    
    Args:
        target_playlist_size: Desired number of tracks in final playlist
        ollama_max_tracks: Optional absolute maximum track count for Ollama provider.
            When provided, this value is returned directly instead of calculating
            the dynamic threshold.
        
    Returns:
        int: Multiplier for filtering (e.g., 10 means keep 10x target size)
    """
    # If Ollama max tracks is set, use it as absolute threshold
    if ollama_max_tracks is not None:
        return ollama_max_tracks
    
    if target_playlist_size <= 25:
        return 10  # 25 tracks -> keep top 250
    elif target_playlist_size <= 50:
        return 8   # 50 tracks -> keep top 400
    elif target_playlist_size <= 100:
        return 5   # 100 tracks -> keep top 600
    else:
        # For larger playlists, use diminishing multiplier
        # Cap at 5x to balance quality and token efficiency
        return max(5, int(600 / target_playlist_size * 6))


def should_apply_smart_filtering(source_tracks: List[Dict], target_playlist_size: int, ollama_max_tracks: Optional[int] = None) -> bool:
    """
    Determine if smart filtering should be applied based on track count and target size.
    
    Args:
        source_tracks: List of all available tracks for the artist
        target_playlist_size: Desired number of tracks in final playlist
        ollama_max_tracks: Optional absolute maximum track count for Ollama provider
        
    Returns:
        bool: True if filtering should be applied
    """
    threshold_multiplier = calculate_filter_threshold(target_playlist_size, ollama_max_tracks)
    threshold = ollama_max_tracks if ollama_max_tracks is not None else target_playlist_size * threshold_multiplier
    
    return len(source_tracks) > threshold


def filter_tracks_by_engagement(
    tracks: List[Dict], 
    target_playlist_size: int, 
    library_stats: Dict,
    ollama_max_tracks: Optional[int] = None
) -> List[Dict]:
    """
    Apply smart filtering to tracks if needed, returning filtered subset.
    
    Args:
        tracks: List of all available tracks
        target_playlist_size: Desired number of tracks in final playlist
        library_stats: Library statistics for scoring
        ollama_max_tracks: Optional absolute maximum track count for Ollama provider
        
    Returns:
        List[Dict]: Filtered tracks (or original if filtering not needed)
    """
    # Check if filtering is needed
    if not should_apply_smart_filtering(tracks, target_playlist_size, ollama_max_tracks):
        return tracks
    
    # Calculate how many tracks to keep
    threshold_multiplier = calculate_filter_threshold(target_playlist_size, ollama_max_tracks)
    max_tracks_to_keep = ollama_max_tracks if ollama_max_tracks is not None else target_playlist_size * threshold_multiplier
    
    # Score and filter tracks
    scored_tracks = score_tracks_by_user_engagement(tracks, library_stats)
    
    # Return top-scored tracks up to the limit
    filtered_tracks = [track for score, track in scored_tracks[:max_tracks_to_keep]]
    
    return filtered_tracks


def _split_artists(artist_field: str) -> List[str]:
    """
    Split a combined artist string into individual artist names.
    
    Handles common collaboration separators such as " & ", " feat. ", " ft. ",
    " featuring ", " x ", " and ", and ",". Each resulting name is stripped and
    lowercased for case-insensitive matching.
    
    Args:
        artist_field: Raw artist string (may contain featured artists)
        
    Returns:
        List of individual artist names (lowercased, stripped)
    """
    if not artist_field:
        return []
    # Normalize separators to a common delimiter
    normalized = re.sub(
        r'\s*(?:&|feat\.?|ft\.?|featuring|x|and|,)\s*',
        '|',
        artist_field,
        flags=re.IGNORECASE
    )
    parts = [p.strip().lower() for p in normalized.split('|') if p.strip()]
    # De-duplicate while preserving order
    seen = set()
    result = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            result.append(p)
    return result


def select_diverse_tracks(
    scored_tracks: List[Tuple[float, Dict]],
    threshold_count: int,
    exploration_ratio: float = 0.0,
    high_tier_ratio: float = 0.4,
    high_tier_multiplier: float = 3.0,
    rng: Optional[random.Random] = None
) -> Tuple[List[Tuple[float, Dict]], Dict[str, Any]]:
    """
    Build a diversified, partially-randomized selection from score-sorted tracks.

    The kept set is composed of two parts:
    1. **Core (high-scored, randomized):** `high_tier_ratio` of the kept count, randomly
       sampled from the top `core_count * high_tier_multiplier` scored tracks. This varies
       *which* high-scoring tracks are chosen between runs while keeping quality high.
    2. **Exploration (fill-up):** the remaining `1 - high_tier_ratio` of the kept count,
       filled by walking the score-sorted list starting at a random offset (with wrap),
       skipping any track already picked for the core. This diversifies the mid-tier
       selection across runs.

    Args:
        scored_tracks: Globally score-sorted list of (score, track) tuples (descending)
        threshold_count: Total number of tracks to keep
        exploration_ratio: Fraction of the kept set that comes from the exploration band.
            (Retained for backward-compatibility naming; the core fraction is derived as
            `1 - exploration_ratio` when `high_tier_ratio` is not explicitly provided.)
        high_tier_ratio: Fraction of the kept set that forms the randomized high-scored core.
        high_tier_multiplier: Size of the high-tier candidate pool as a multiple of the
            core count (pool = top `core_count * high_tier_multiplier` tracks).
        rng: Optional `random.Random` instance for reproducible runs (None = fresh variety).

    Returns:
        tuple: (selected, selection_meta)
            - selected: List of (score, track) tuples (length <= threshold_count)
            - selection_meta: Dict with core/explore counts, offsets, and exhaustion flag
    """
    if rng is None:
        rng = random.Random()

    # Core fraction: prefer explicit high_tier_ratio, else derive from exploration_ratio
    core_fraction = high_tier_ratio if high_tier_ratio > 0 else (1.0 - exploration_ratio)
    core_count = max(0, int(round(threshold_count * core_fraction)))
    explore_count = max(0, threshold_count - core_count)

    # High-tier candidate pool (top N scored tracks) for the randomized core pick
    high_tier_size = max(core_count, int(round(core_count * high_tier_multiplier)))
    high_tier_size = min(high_tier_size, len(scored_tracks))

    core: List[Tuple[float, Dict]] = []
    if core_count > 0 and high_tier_size > 0:
        # Sample without replacement from the high-tier pool
        pool = scored_tracks[:high_tier_size]
        sample_n = min(core_count, len(pool))
        core = rng.sample(pool, sample_n)

    core_ids = {id(track) for _, track in core}

    # Random starting offset for the exploration walk (avoids always scanning the same region)
    start_offset = 0
    if explore_count > 0 and len(scored_tracks) > core_count:
        start_offset = rng.randint(core_count, len(scored_tracks) - 1)

    explore: List[Tuple[float, Dict]] = []
    exhausted = False
    if explore_count > 0:
        n = len(scored_tracks)
        i = 0
        # Walk at most one full loop; stop early once explore_count is filled
        while len(explore) < explore_count and i < n:
            idx = (start_offset + i) % n
            i += 1
            score, track = scored_tracks[idx]
            if id(track) in core_ids:
                continue
            explore.append((score, track))
        exhausted = len(explore) < explore_count

    selected = core + explore

    selection_meta = {
        'core_count': len(core),
        'explore_count': len(explore),
        'high_tier_size': high_tier_size,
        'start_offset': start_offset,
        'exhausted': exhausted,
        'core_fraction': core_fraction,
    }

    return selected, selection_meta


def _track_passes_caps(
    track: Dict,
    artist_state: Dict[str, Dict[str, Any]],
    max_albums_per_artist: int,
    max_tracks_per_artist: int
) -> bool:
    """
    Check whether a track passes the per-artist diversity caps given current state.

    Mirrors the cap logic in `apply_artist_diversity_caps`: a track is kept only if none of
    its (possibly multiple, featured) artists has yet exceeded the track cap, and either the
    album was already seen for every involved artist or no involved artist has yet reached the
    album cap. Featured artists are treated as a union.

    Args:
        track: The track dict to test
        artist_state: Per-artist state dict (artist -> {"track_count": int, "albums": set})
        max_albums_per_artist: Maximum distinct albums allowed per artist
        max_tracks_per_artist: Maximum total tracks allowed per artist

    Returns:
        bool: True if the track may be kept without violating any cap
    """
    artist_field = track.get('artist', 'Unknown Artist')
    album = (track.get('album') or '').strip()

    artists = _split_artists(artist_field)
    if not artists:
        artists = [artist_field.strip().lower() or 'unknown artist']

    states = []
    for a in artists:
        st = artist_state.get(a)
        if st is None:
            st = {'track_count': 0, 'albums': set()}
            artist_state[a] = st
        states.append(st)

    # Blocked if ANY involved artist already hit the track cap
    if any(st['track_count'] >= max_tracks_per_artist for st in states):
        return False

    album_seen_by_all = all(album in st['albums'] for st in states)
    # Blocked if this is a new album AND every involved artist already hit the album cap
    if not album_seen_by_all and all(len(st['albums']) >= max_albums_per_artist for st in states):
        return False

    return True


def _apply_caps_to_track(
    track: Dict,
    artist_state: Dict[str, Dict[str, Any]]
) -> None:
    """
    Update per-artist state to count a kept track against every involved artist.

    Must only be called after `_track_passes_caps` returned True for the same track/state.
    """
    artist_field = track.get('artist', 'Unknown Artist')
    album = (track.get('album') or '').strip()

    artists = _split_artists(artist_field)
    if not artists:
        artists = [artist_field.strip().lower() or 'unknown artist']

    states = [artist_state[a] for a in artists]
    if album:
        for st in states:
            st['albums'].add(album)
    for st in states:
        st['track_count'] += 1


def select_diverse_tracks_with_caps(
    scored_tracks: List[Tuple[float, Dict]],
    threshold_count: int,
    exploration_ratio: float = 0.0,
    high_tier_ratio: float = 0.4,
    high_tier_multiplier: float = 3.0,
    max_albums_per_artist: int = 0,
    max_tracks_per_artist: int = 0,
    rng: Optional[random.Random] = None
) -> Tuple[List[Tuple[float, Dict]], Dict[str, Any]]:
    """
    Cap-aware selection over the FULL scored list (single source of truth for genre paths).

    Builds the kept set from a high-scored core plus an exploration band, enforcing the
    per-artist diversity caps *during* the walk over the entire `scored_tracks` list (not as
    a post-filter on a pre-truncated subset). This guarantees the selection reaches
    `threshold_count` whenever enough diverse tracks exist, because the walk keeps scanning
    past capped artists instead of stopping early with a depleted candidate pool.

    Two modes, selected by `exploration_ratio`:
    - **Diversified** (`exploration_ratio > 0`): the core is a *random sample* from the top
      `core_count * high_tier_multiplier` scored tracks, and the exploration band walks the
      full list from a *random offset*. Varies which tracks are chosen between runs.
    - **Deterministic** (`exploration_ratio <= 0`): the core is the top `threshold_count`
      tracks by score (no randomization) and the walk proceeds in score order. This reproduces
      the original `apply_artist_diversity_caps` behavior exactly.

    Args:
        scored_tracks: Globally score-sorted list of (score, track) tuples (descending)
        threshold_count: Total number of tracks to keep
        exploration_ratio: Fraction of the kept set from the exploration band. When > 0 the
            selection is diversified across runs; when <= 0 the selection is deterministic.
        high_tier_ratio: Fraction of the kept set that forms the high-scored core (diversified
            mode only).
        high_tier_multiplier: Size of the high-tier candidate pool as a multiple of the core
            count (pool = top `core_count * high_tier_multiplier` tracks). Diversified mode only.
        max_albums_per_artist: Maximum distinct albums allowed per artist (0 disables).
        max_tracks_per_artist: Maximum total tracks allowed per artist (0 disables).
        rng: Optional `random.Random` instance for reproducible runs (None = fresh variety).

    Returns:
        tuple: (selected, selection_meta)
            - selected: List of (score, track) tuples (length <= threshold_count)
            - selection_meta: Dict with core/explore counts, caps_dropped, offsets, exhaustion
    """
    if rng is None:
        rng = random.Random()

    caps_enabled = max_albums_per_artist > 0 and max_tracks_per_artist > 0
    diversified = exploration_ratio > 0

    # Core fraction: diversified uses high_tier_ratio; deterministic takes the whole set
    # (the exploration band is empty, so the core IS the full selection in score order).
    core_fraction = high_tier_ratio if (diversified and high_tier_ratio > 0) else (1.0 - exploration_ratio if diversified else 1.0)
    core_count = max(0, int(round(threshold_count * core_fraction)))

    high_tier_size = max(core_count, int(round(core_count * high_tier_multiplier)))
    high_tier_size = min(high_tier_size, len(scored_tracks))

    artist_state: Dict[str, Dict[str, Any]] = {}
    core: List[Tuple[float, Dict]] = []
    caps_dropped = 0

    if core_count > 0 and high_tier_size > 0:
        if diversified:
            # Random sample without replacement from the high-tier pool; only keep tracks
            # that pass caps. Keep sampling until we fill the core or exhaust the pool.
            pool = scored_tracks[:high_tier_size]
            attempts = 0
            max_attempts = max(len(pool), 1) * 4  # bound work; pool is small relative to source
            while len(core) < core_count and attempts < max_attempts:
                candidate = rng.choice(pool)
                attempts += 1
                if caps_enabled and not _track_passes_caps(candidate[1], artist_state, max_albums_per_artist, max_tracks_per_artist):
                    caps_dropped += 1
                    continue
                if caps_enabled:
                    _apply_caps_to_track(candidate[1], artist_state)
                core.append(candidate)
        else:
            # Deterministic: take the top core_count tracks by score, honoring caps.
            for entry in scored_tracks[:core_count]:
                if caps_enabled and not _track_passes_caps(entry[1], artist_state, max_albums_per_artist, max_tracks_per_artist):
                    caps_dropped += 1
                    continue
                if caps_enabled:
                    _apply_caps_to_track(entry[1], artist_state)
                core.append(entry)

    core_ids = {id(track) for _, track in core}

    # Exploration walk over the FULL list, honoring caps. Diversified mode starts at a random
    # offset; deterministic mode continues from where the core slice ended (no re-scan).
    start_offset = 0
    if threshold_count > len(core) and len(scored_tracks) > 0:
        if diversified:
            start_offset = rng.randint(0, len(scored_tracks) - 1)
        else:
            start_offset = min(core_count, len(scored_tracks) - 1)

    explore: List[Tuple[float, Dict]] = []
    exhausted = False
    n = len(scored_tracks)
    if threshold_count > len(core) and n > 0:
        i = 0
        # Walk at most one full loop over the entire source; caps may skip many tracks, so
        # the loop continues until threshold is met or the whole list has been scanned.
        while len(explore) + len(core) < threshold_count and i < n:
            idx = (start_offset + i) % n
            i += 1
            score, track = scored_tracks[idx]
            if id(track) in core_ids:
                continue
            if caps_enabled and not _track_passes_caps(track, artist_state, max_albums_per_artist, max_tracks_per_artist):
                caps_dropped += 1
                continue
            if caps_enabled:
                _apply_caps_to_track(track, artist_state)
            explore.append((score, track))
        exhausted = (len(explore) + len(core)) < threshold_count

    selected = core + explore

    selection_meta = {
        'core_count': len(core),
        'explore_count': len(explore),
        'high_tier_size': high_tier_size,
        'start_offset': start_offset,
        'caps_dropped': caps_dropped,
        'exhausted': exhausted,
        'core_fraction': core_fraction,
        'diversified': diversified,
    }

    return selected, selection_meta


def filter_tracks_for_this_is_playlist(
    source_tracks: List[Dict], 
    target_playlist_size: int, 
    library_stats: Dict,
    playlist_type: str = "artist",
    diversity_config: Optional[Dict] = None,
    ollama_max_tracks: Optional[int] = None,
    exploration_ratio: float = 0.0,
    high_tier_ratio: float = 0.4,
    high_tier_multiplier: float = 3.0,
    random_seed: Optional[int] = None,
    # Filter options
    year_start: Optional[int] = None,
    year_end: Optional[int] = None,
    blacklisted_artists: Optional[List[str]] = None,
    min_bitrate: Optional[int] = None,
    min_format: Optional[str] = None
) -> Tuple[List[Dict], Dict[str, Any]]:
    """
    Filter source tracks for "This Is" / "Genre Mix" playlists using engagement scoring.
    
    For genre playlists, per-artist diversity caps (max albums and max tracks per artist)
    are applied on top of the score-based filtering to ensure track diversity in the
    payload sent to the AI model. Artist ("This Is") playlists keep the original
    score-based filtering unchanged.
    
    Args:
        source_tracks: Full list of tracks matching artist/criteria
        target_playlist_size: Desired final playlist length
        library_stats: User's library statistics for normalization
        playlist_type: "artist" or "genre" - controls diversity cap application
        diversity_config: Dict with max_albums_per_artist and max_tracks_per_artist
            (used only when playlist_type == "genre")
        ollama_max_tracks: Optional absolute maximum track count for Ollama provider.
            When provided, this value overrides the calculated threshold entirely.
        exploration_ratio: Fraction of the kept set filled by the randomized exploration
            band. When > 0, selection is diversified across runs (see `select_diverse_tracks`).
            Ignored when `high_tier_ratio` is explicitly provided. Default 0.0 = current
            deterministic top-N behavior (backward compatible).
        high_tier_ratio: Fraction of the kept set that forms the randomized high-scored core.
            Default 0.4. Only used when `exploration_ratio > 0` (or when explicitly set).
        high_tier_multiplier: Size of the high-tier candidate pool as a multiple of the core
            count. Default 3.0.
        random_seed: Optional seed for reproducible runs (None = fresh variety each call).
        year_start: Optional minimum release year filter (1950-2026).
        year_end: Optional maximum release year filter (1950-2026).
        blacklisted_artists: Optional list of artist names to exclude.
        min_bitrate: Optional minimum bitrate in kbps (128, 192, 256, 320).
        min_format: Optional minimum format (mp3, flac, aac, etc.).
        
    Returns:
        tuple: (filtered_tracks, filter_metadata)
            - filtered_tracks: Subset of tracks to send to LLM
            - filter_metadata: Dict with info about filtering for logging/UI
    """
    threshold_multiplier = calculate_filter_threshold(target_playlist_size, ollama_max_tracks)
    threshold_count = ollama_max_tracks if ollama_max_tracks is not None else target_playlist_size * threshold_multiplier
    
    # Apply pre-scoring filters (year, artist blacklist, quality)
    pre_filtered_tracks = []
    filter_stats = {
        'year_filtered': 0,
        'artist_filtered': 0,
        'quality_filtered': 0
    }
    
    # Normalize blacklisted artists to lowercase for case-insensitive matching
    blacklisted_lower = set()
    if blacklisted_artists:
        blacklisted_lower = {a.lower().strip() for a in blacklisted_artists if a}
    
    for track in source_tracks:
        # Year filter
        track_year = track.get('year')
        if year_start is not None and track_year is not None and track_year < year_start:
            filter_stats['year_filtered'] += 1
            continue
        if year_end is not None and track_year is not None and track_year > year_end:
            filter_stats['year_filtered'] += 1
            continue
        
        # Artist blacklist filter
        track_artist = track.get('artist', '')
        artist_match = False
        if blacklisted_lower:
            # Check if any blacklisted artist matches (case-insensitive)
            track_artists = _split_artists(track_artist)
            for ta in track_artists:
                if ta in blacklisted_lower:
                    artist_match = True
                    break
            if artist_match:
                filter_stats['artist_filtered'] += 1
                continue
        
        # Quality filter (bitrate and format)
        track_bitrate = track.get('bit_rate', 0) or 0
        track_format = track.get('format', '').lower() or ''
        
        if min_bitrate is not None and track_bitrate > 0 and track_bitrate < min_bitrate:
            filter_stats['quality_filtered'] += 1
            continue
        
        if min_format is not None and track_format and track_format != min_format.lower():
            filter_stats['quality_filtered'] += 1
            continue
        
        pre_filtered_tracks.append(track)
    
    # Log pre-filtering stats
    if any(filter_stats.values()):
        print(f"🔍 PRE-FILTERING APPLIED:")
        print(f"   📅 Year filter: {filter_stats['year_filtered']} tracks excluded")
        print(f"   🚫 Artist blacklist: {filter_stats['artist_filtered']} tracks excluded")
        print(f"   🎧 Quality filter: {filter_stats['quality_filtered']} tracks excluded")
        print(f"   📊 Remaining: {len(pre_filtered_tracks)} tracks (from {len(source_tracks)})")
    
    # Only filter if source tracks exceed threshold
    if len(pre_filtered_tracks) <= threshold_count:
        return pre_filtered_tracks, {
            'filtered': False,
            'reason': 'below_threshold',
            'source_count': len(pre_filtered_tracks),
            'sent_count': len(pre_filtered_tracks),
            'diversity_applied': False,
            'pre_filter_stats': filter_stats
        }
    
    # Score all tracks
    scored_tracks = score_tracks_by_user_engagement(pre_filtered_tracks, library_stats)
    
    # Determine whether per-artist diversity caps should be applied
    apply_diversity = (
        playlist_type == "genre"
        and diversity_config is not None
        and diversity_config.get('max_albums_per_artist', 0) > 0
        and diversity_config.get('max_tracks_per_artist', 0) > 0
    )
    
    # Initialize for metadata (used in both branches)
    max_albums = 0
    max_tracks = 0
    selection_meta: Dict[str, Any] = {}
    use_diverse_selection = exploration_ratio > 0

    if apply_diversity:
        # Genre: both diversified and deterministic genre paths use the single cap-aware
        # selection function. It enforces per-artist caps DURING the walk over the full
        # source so the selection reaches threshold_count (caps drop but we keep scanning
        # past capped artists instead of stopping with a depleted pool). With
        # exploration_ratio <= 0 it reproduces the original deterministic top-N behavior.
        rng = random.Random(random_seed)
        max_albums = int(diversity_config['max_albums_per_artist'])
        max_tracks = int(diversity_config['max_tracks_per_artist'])
        selected, selection_meta = select_diverse_tracks_with_caps(
            scored_tracks=scored_tracks,
            threshold_count=threshold_count,
            exploration_ratio=exploration_ratio,
            high_tier_ratio=high_tier_ratio,
            high_tier_multiplier=high_tier_multiplier,
            max_albums_per_artist=max_albums,
            max_tracks_per_artist=max_tracks,
            rng=rng
        )
        filtered_tracks = [track for score, track in selected]
        diversity_dropped = selection_meta.get('caps_dropped', 0)
    elif use_diverse_selection:
        # Artist ("This Is"): diversified, partially-randomized selection (no caps).
        rng = random.Random(random_seed)
        selected, selection_meta = select_diverse_tracks(
            scored_tracks=scored_tracks,
            threshold_count=threshold_count,
            exploration_ratio=exploration_ratio,
            high_tier_ratio=high_tier_ratio,
            high_tier_multiplier=high_tier_multiplier,
            rng=rng
        )
        filtered_tracks = [track for score, track in selected]
        diversity_dropped = 0
    else:
        # Take top N scored tracks (default deterministic behavior, no caps)
        filtered_tracks = [track for score, track in scored_tracks[:threshold_count]]
        diversity_dropped = 0
    
    # Log filtering decision and final payload
    print(f"🎯 FILTERING DECISION:")
    if ollama_max_tracks is not None:
        print(f"   🎯 Ollama max tracks threshold: {threshold_count} tracks (absolute limit)")
    else:
        print(f"   🎯 Threshold: {threshold_count} tracks (target: {target_playlist_size} × {threshold_multiplier}x multiplier)")
    print(f"   ✂️  Filtered {len(pre_filtered_tracks)} → {len(filtered_tracks)} tracks for LLM payload")
    print(f"   📤 Payload reduction: {((len(pre_filtered_tracks) - len(filtered_tracks)) / len(pre_filtered_tracks) * 100):.1f}%")
    if use_diverse_selection:
        print(f"   🎲 Diversified selection: core {selection_meta.get('core_count', 0)} "
              f"(from top {selection_meta.get('high_tier_size', 0)}) + explore "
              f"{selection_meta.get('explore_count', 0)} (offset {selection_meta.get('start_offset', 0)})"
              f"{' [exhausted]' if selection_meta.get('exhausted') else ''}")
    if apply_diversity:
        print(f"   🎭 Diversity caps applied: max {max_albums} albums / {max_tracks} tracks per artist "
              f"(dropped {diversity_dropped} tracks"
              f"{' during selection' if use_diverse_selection else ''})"
              f"{' [exhausted]' if selection_meta.get('exhausted') else ''}")
    
    # Metadata for logging and user feedback
    # Recompute score range from the actual selected tracks (selection is no longer a
    # clean prefix of the sorted list when diversified selection is used).
    if use_diverse_selection:
        # Derive scores from the filtered tracks by matching against scored_tracks
        sent_scores = [s for s, t in scored_tracks if t in filtered_tracks]
        score_range = {
            'highest': max(sent_scores) if sent_scores else 0,
            'lowest': min(sent_scores) if sent_scores else 0,
            'cutoff': 0  # not meaningful for non-prefix selection
        }
    else:
        score_range = {
            'highest': scored_tracks[0][0] if scored_tracks else 0,
            'lowest': scored_tracks[threshold_count-1][0] if len(scored_tracks) >= threshold_count else 0,
            'cutoff': scored_tracks[threshold_count][0] if len(scored_tracks) > threshold_count else 0
        }
    filter_metadata = {
        'filtered': True,
        'source_count': len(source_tracks),
        'pre_filtered_count': len(pre_filtered_tracks),
        'sent_count': len(filtered_tracks),
        'threshold_multiplier': threshold_multiplier,
        'diversity_applied': apply_diversity,
        'diversity_dropped': diversity_dropped,
        'max_albums_per_artist': max_albums,
        'max_tracks_per_artist': max_tracks,
        'ollama_max_tracks': ollama_max_tracks,
        'exploration_applied': use_diverse_selection,
        'exploration_ratio': exploration_ratio,
        'high_tier_ratio': high_tier_ratio,
        'high_tier_multiplier': high_tier_multiplier,
        'selection_meta': selection_meta,
        'score_range': score_range,
        'pre_filter_stats': filter_stats
    }
    
    return filtered_tracks, filter_metadata