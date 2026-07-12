"""
Smart Track Scoring & Filtering for "This Is" Playlists

Optimizes payload size for LLM compatibility and token cost efficiency by intelligently 
scoring and filtering source tracks based on user listening behavior.
"""

import re
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


def calculate_filter_threshold(target_playlist_size: int) -> int:
    """
    Calculate optimal multiplier for filtering source tracks.
    
    Rationale: As playlist size increases, we can use a lower multiplier
    because probability of capturing high-quality tracks increases.
    
    Args:
        target_playlist_size: Desired number of tracks in final playlist
        
    Returns:
        int: Multiplier for filtering (e.g., 10 means keep 10x target size)
    """
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


def should_apply_smart_filtering(source_tracks: List[Dict], target_playlist_size: int) -> bool:
    """
    Determine if smart filtering should be applied based on track count and target size.
    
    Args:
        source_tracks: List of all available tracks for the artist
        target_playlist_size: Desired number of tracks in final playlist
        
    Returns:
        bool: True if filtering should be applied
    """
    threshold_multiplier = calculate_filter_threshold(target_playlist_size)
    threshold = target_playlist_size * threshold_multiplier
    
    return len(source_tracks) > threshold


def filter_tracks_by_engagement(
    tracks: List[Dict], 
    target_playlist_size: int, 
    library_stats: Dict
) -> List[Dict]:
    """
    Apply smart filtering to tracks if needed, returning filtered subset.
    
    Args:
        tracks: List of all available tracks
        target_playlist_size: Desired number of tracks in final playlist
        library_stats: Library statistics for scoring
        
    Returns:
        List[Dict]: Filtered tracks (or original if filtering not needed)
    """
    # Check if filtering is needed
    if not should_apply_smart_filtering(tracks, target_playlist_size):
        return tracks
    
    # Calculate how many tracks to keep
    threshold_multiplier = calculate_filter_threshold(target_playlist_size)
    max_tracks_to_keep = target_playlist_size * threshold_multiplier
    
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


def apply_artist_diversity_caps(
    scored_tracks: List[Tuple[float, Dict]],
    max_albums_per_artist: int,
    max_tracks_per_artist: int,
    keep_limit: int
) -> Tuple[List[Dict], int]:
    """
    Enforce per-artist diversity caps on globally score-sorted tracks.
    
    Walks the tracks in descending score order and keeps a track only if none of its
    (possibly multiple, featured) artists has yet exceeded the track cap, and either the
    album was already seen for every involved artist or no involved artist has yet reached
    the album cap. Featured artists are treated as a union: if "Lost Frequencies" is capped,
    a "Lost Frequencies & David Guetta" track is also blocked, while "David Guetta" alone
    remains selectable.
    
    Args:
        scored_tracks: Globally score-sorted list of (score, track) tuples
        max_albums_per_artist: Maximum distinct albums allowed per artist
        max_tracks_per_artist: Maximum total tracks allowed per artist
        keep_limit: Stop once this many tracks have been kept
        
    Returns:
        tuple: (kept_tracks, dropped_count)
            - kept_tracks: List of track dicts that passed the caps
            - dropped_count: Number of tracks skipped due to caps
    """
    kept_tracks: List[Dict] = []
    dropped_count = 0
    
    # Per-artist state: artist -> {"track_count": int, "albums": set}
    artist_state: Dict[str, Dict[str, Any]] = {}
    
    for score, track in scored_tracks:
        if len(kept_tracks) >= keep_limit:
            break
        
        artist_field = track.get('artist', 'Unknown Artist')
        album = (track.get('album') or '').strip()
        
        # Resolve all involved artists (handles features/collaborations)
        artists = _split_artists(artist_field)
        if not artists:
            artists = [artist_field.strip().lower() or 'unknown artist']
        
        # Ensure state exists for each involved artist
        states = []
        for a in artists:
            st = artist_state.get(a)
            if st is None:
                st = {'track_count': 0, 'albums': set()}
                artist_state[a] = st
            states.append(st)
        
        # Skip if ANY involved artist already hit the track cap
        if any(st['track_count'] >= max_tracks_per_artist for st in states):
            dropped_count += 1
            continue
        
        album_seen_by_all = all(album in st['albums'] for st in states)
        # Skip if this is a new album AND every involved artist already hit the album cap
        if not album_seen_by_all and all(len(st['albums']) >= max_albums_per_artist for st in states):
            dropped_count += 1
            continue
        
        # Keep the track - count it against every involved artist
        if album:
            for st in states:
                st['albums'].add(album)
        for st in states:
            st['track_count'] += 1
        kept_tracks.append(track)
    
    return kept_tracks, dropped_count


def filter_tracks_for_this_is_playlist(
    source_tracks: List[Dict], 
    target_playlist_size: int, 
    library_stats: Dict,
    playlist_type: str = "artist",
    diversity_config: Optional[Dict] = None
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
        
    Returns:
        tuple: (filtered_tracks, filter_metadata)
            - filtered_tracks: Subset of tracks to send to LLM
            - filter_metadata: Dict with info about filtering for logging/UI
    """
    threshold_multiplier = calculate_filter_threshold(target_playlist_size)
    threshold_count = target_playlist_size * threshold_multiplier
    
    # Only filter if source tracks exceed threshold
    if len(source_tracks) <= threshold_count:
        return source_tracks, {
            'filtered': False,
            'reason': 'below_threshold',
            'source_count': len(source_tracks),
            'sent_count': len(source_tracks),
            'diversity_applied': False
        }
    
    # Score all tracks
    scored_tracks = score_tracks_by_user_engagement(source_tracks, library_stats)
    
    # Determine whether per-artist diversity caps should be applied
    apply_diversity = (
        playlist_type == "genre"
        and diversity_config is not None
        and diversity_config.get('max_albums_per_artist', 0) > 0
        and diversity_config.get('max_tracks_per_artist', 0) > 0
    )
    
    if apply_diversity:
        max_albums = int(diversity_config['max_albums_per_artist'])
        max_tracks = int(diversity_config['max_tracks_per_artist'])
        filtered_tracks, diversity_dropped = apply_artist_diversity_caps(
            scored_tracks=scored_tracks,
            max_albums_per_artist=max_albums,
            max_tracks_per_artist=max_tracks,
            keep_limit=threshold_count
        )
    else:
        # Take top N scored tracks
        filtered_tracks = [track for score, track in scored_tracks[:threshold_count]]
        diversity_dropped = 0
    
    # Log filtering decision and final payload
    print(f"🎯 FILTERING DECISION:")
    print(f"   🎯 Threshold: {threshold_count} tracks (target: {target_playlist_size} × {threshold_multiplier}x multiplier)")
    print(f"   ✂️  Filtered {len(source_tracks)} → {len(filtered_tracks)} tracks for LLM payload")
    print(f"   📤 Payload reduction: {((len(source_tracks) - len(filtered_tracks)) / len(source_tracks) * 100):.1f}%")
    if apply_diversity:
        print(f"   🎭 Diversity caps applied: max {max_albums} albums / {max_tracks} tracks per artist (dropped {diversity_dropped} tracks)")
    
    # Metadata for logging and user feedback
    filter_metadata = {
        'filtered': True,
        'source_count': len(source_tracks),
        'sent_count': len(filtered_tracks),
        'threshold_multiplier': threshold_multiplier,
        'diversity_applied': apply_diversity,
        'diversity_dropped': diversity_dropped,
        'max_albums_per_artist': max_albums if apply_diversity else 0,
        'max_tracks_per_artist': max_tracks if apply_diversity else 0,
        'score_range': {
            'highest': scored_tracks[0][0] if scored_tracks else 0,
            'lowest': scored_tracks[threshold_count-1][0] if len(scored_tracks) >= threshold_count else 0,
            'cutoff': scored_tracks[threshold_count][0] if len(scored_tracks) > threshold_count else 0
        }
    }
    
    return filtered_tracks, filter_metadata