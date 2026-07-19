# Recipe System

This directory contains playlist generation recipes that define how different types of
playlists are created. A recipe is a JSON document that drives both the **LLM prompt** used
for curation and the **source-track filtering** applied before the model ever sees the data.

## Structure

- `registry.json` - Maps playlist types to their current default recipe files
- `{type}_v{major}_{minor}.json` - Individual recipe files with versioning
- `archive/` - Superseded recipe versions kept for reference

### `registry.json`

```json
{
  "this_is": "this_is_v2.json",
  "re_discover": "re_discover_phase2_v2.json",
  "genre_mix": "genre_mix_v2.json",
  "re_discover_phase1_v2": "re_discover_phase1_v2.json",
  "re_discover_phase2_v2": "re_discover_phase2_v2.json"
}
```

The key is the playlist type requested by the API; the value is the recipe file used.

## Recipe File Format

There are two formats. The **new-style** format (used by all current recipes) is described
below. A **legacy** format (with `version`, `prompt_template`, `llm_params`, etc.) is still
supported for backward compatibility and is handled automatically by `RecipeManager`.

### New-style recipe fields

| Field | Purpose |
|-------|---------|
| `recipe_id` | Unique identifier for the recipe |
| `name` | Human-readable name |
| `user_parameters` | Placeholders (`{{TARGET_ARTIST}}`, `{{DESIRED_TRACK_COUNT}}`, …) filled from the API request |
| `llm_config` | `max_output_tokens` and `temperature` for the curation call |
| `description_llm_config` | Optional LLM settings for the editorial-description call |
| `model_instructions` | The main prompt sent to the LLM (supports `{{MATH:...}}` expressions). Used by This Is and Re-Discover recipes |
| `selection_instructions` | The main prompt sent to the LLM for track selection (used by Genre Mix; falls back to `model_instructions` when absent) |
| `description_instructions` | Optional prompt for generating a short editorial blurb |
| `source_filtering` | Engagement-scoring / diversity config applied before the LLM runs |
| `output_sorting` | Post-curation spacing rules (see below) |
| `global_strategy` / `processing_steps` | Optional metadata describing the curation strategy |

Placeholders use `{{NAME}}` syntax and are substituted from the request. Math expressions
such as `{{MATH:ceil(DESIRED_TRACK_COUNT/5)}}` are evaluated first.

## Recipe Types

### This Is (`this_is`)
- LLM-based curation for a **single artist**
- Balances popular hits with deep cuts, mixing albums and release years
- Uses `source_filtering` for engagement-based pre-selection (see Filters below)
- Recipe: `this_is_v2.json`

### Genre Mix (`genre_mix`)
- LLM-based curation across **one or more genres**
- Selects iconic hits and spreads tracks across decades
- Supports the full filter set: year range, artist blacklist, quality floor, and
  per-album / per-artist diversity caps
- Recipe: `genre_mix_v2.json`

### Re-Discover Weekly (`re_discover`)
- Two-phase pipeline (no single-shot LLM curation)
- **Phase 1** (`re_discover_phase1_v2.json`): analyzes listening history, detects a theme,
  and selects a search strategy (genre/decade/play-count filters)
- **Phase 2** (`re_discover_phase2_v2.json`): an LLM sequences the candidate tracks into a
  cohesive, flowing playlist and writes the editorial description

## Filters

Filters reduce the source-track pool sent to the LLM, lowering token cost and improving
curation quality. They are applied in `backend/track_scoring.py`
(`filter_tracks_for_this_is_playlist`) and configured per recipe via `source_filtering` and
per request via the frontend.

### 1. Engagement-based source filtering (`source_filtering`)
Applied when the source pool is significantly larger than the target playlist size. Tracks are scored by
user engagement (play count, loved/rating, playlist appearances, recency) and the top
`target_playlist_size × multiplier` are kept.

| Key | Default | Meaning |
|-----|---------|---------|
| `exploration_ratio` | `0.6` | Fraction of the kept set filled by a randomized mid-tier "exploration" band |
| `high_tier_ratio` | `0.4` | Fraction of the kept set drawn from a randomized high-scored core |
| `high_tier_multiplier` | `3.0` | Size of the high-tier candidate pool as a multiple of the core count |

When `exploration_ratio > 0` the selection is diversified across runs (different high/mid
tracks each time) while keeping quality high. The threshold multiplier shrinks as the target
playlist grows (e.g. 10× for ≤25 tracks, 5× for ≤100).

### 2. Pre-filters (Genre Mix)
These narrow the pool **before** scoring and are exposed in the Genre Mix UI:

| Filter | Field | Description |
|--------|-------|-------------|
| **Year range** | `year_start`, `year_end` | Keep only tracks released within `[year_start, year_end]` (1950–2026) |
| **Exclude artists** | `blacklisted_artists` | Drop any track whose artist (or featured artist) matches one of the listed names (case-insensitive) |
| **Minimum quality** | `min_bitrate` | Minimum bitrate in kbps (128/192/256/320). Used in MP3/Any mode |
| | `min_format` | Minimum format tier (`mp3`, `flac`, …). Selecting `flac` switches to FLAC mode |
| | `min_bit_depth` | Minimum FLAC bit depth (16/24). FLAC-only filter; drops all lossy and other lossless formats when a depth is set |

In FLAC mode, `min_bitrate` is ignored and only FLAC tracks meeting the requested bit depth
are kept (unknown depth is kept conservatively). In MP3/Any mode, lossless formats are always
kept and lossy formats are filtered by format tier and bitrate floor.

### 3. Diversity caps (Genre Mix)
Per-album / per-artist caps keep the payload sent to the LLM varied. They are applied for
genre playlists **every time** (even when the source is small), and a value of `0` disables
that cap.

| Cap | Field | Default | Description |
|-----|-------|---------|-------------|
| Tracks per album | `max_tracks_per_album` | `2` | Max tracks from the same album (global) |
| Tracks per artist | `max_tracks_per_artist` | `3` | Max tracks per artist |

These caps are sent from the frontend (with the defaults above applied when omitted) and can
also be defined in the recipe's `source_filtering` block.

### 4. Output sorting (`output_sorting`)
Applied **after** the LLM returns the ordered track list, to avoid jarring repetition:

| Key | Default | Meaning |
|-----|---------|---------|
| `space_between_same_artist` | `5` | Minimum tracks separating two songs by the same artist |
| `space_between_same_album` | `4` | Minimum tracks separating two songs from the same album |

> **Note:** The "This Is" playlist currently applies engagement-based source filtering only
> (no year/quality/blacklist/diversity-cap filters, since it targets a single artist). Only the
> Genre Mix playlist exposes the full filter set described above.

## LLM Instructions & Description Generation

Each recipe drives up to two LLM calls: one to **select/sequence tracks**, and one to write a
short **editorial description** of the finished playlist.

### Selection / curation instructions
The curation prompt tells the model how to pick and order tracks. Recipes use one of:

- `model_instructions` — the curation prompt for This Is and Re-Discover recipes.
- `selection_instructions` — the curation prompt for Genre Mix. If a recipe has neither,
  `model_instructions` is used as a fallback (`backend/ai_client.py`).

Both support `{{PLACEHOLDER}}` substitution and `{{MATH:...}}` expressions. The prompt
typically defines the selection rules (iconic hits, decade spread, artist/album diversity)
and the exact JSON output format the model must return (e.g. `{"track_ids": [...]}`).

### Description instructions
`description_instructions` is an optional prompt used to generate a short, magazine-style
blurb for the already-built playlist. It is given the final ordered track list and must return
a single JSON field, e.g. `{"description": "..."}`. When omitted, no description is generated.

### Description LLM config (`description_llm_config`)
The description call can use its own LLM settings, separate from the curation call. This is
useful because description writing benefits from a higher temperature (more creative phrasing)
and a much smaller token budget than track selection.

| Key | Typical value | Meaning |
|-----|---------------|---------|
| `max_output_tokens` | `2000` | Token budget for the description response (far smaller than the curation call) |
| `temperature` | `0.7` | Sampling temperature — slightly higher than curation for more varied, editorial phrasing |

If `description_llm_config` is absent, the backend falls back to
`{"temperature": 0.7, "max_output_tokens": 500}`.

> **Summary of the two configs:** `llm_config` controls the **track-selection** call
> (e.g. `max_output_tokens: 22000`, `temperature: 0.6` for Genre Mix), while
> `description_llm_config` controls the lighter-weight **description** call.

## Adding New Recipes

1. Create a new recipe file with proper versioning (e.g. `my_type_v1.json`)
2. Update `registry.json` to point the playlist type to the new file
3. Optional: Test with the `/api/recipes/validate` endpoint
4. The system will automatically use the new recipe

## Validation

Use the API endpoints to validate recipes:
- `GET /api/recipes` - List all available recipes
- `GET /api/recipes/validate` - Validate all recipe files