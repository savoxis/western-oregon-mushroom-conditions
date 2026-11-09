#!/usr/bin/env python3
"""
score.py - Fruiting condition scoring per zone and species.
Reads species_registry.json, weather/snotel/fires JSON, outputs scores.
CLI: python3 score.py lat lon month [zone_id] < weather_json
"""

import sys
import json
import math
import os
from datetime import datetime

# Get paths relative to script location
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
REGISTRY_FILE = os.path.join(PROJECT_ROOT, 'references', 'species_registry.json')
ZONES_FILE = os.path.join(PROJECT_ROOT, 'references', 'zones.json')

def tri(x, zero_lo, opt_lo, opt_hi, zero_hi):
    """Triangular membership function."""
    if x is None or x <= zero_lo or x >= zero_hi:
        return 0.0
    if x < opt_lo:
        return (x - zero_lo) / (opt_lo - zero_lo)
    if x <= opt_hi:
        return 1.0
    return (zero_hi - x) / (zero_hi - opt_hi)

def ramp(x, lo, hi):
    """Linear ramp membership."""
    if x is None:
        return 0.0
    return max(0.0, min(1.0, (x - lo) / (hi - lo)))

def load_registry():
    """Load species registry."""
    try:
        with open(REGISTRY_FILE) as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading registry: {e}", file=sys.stderr)
        return {}

def load_zones():
    """Load zones gazetteer."""
    try:
        with open(ZONES_FILE) as f:
            return json.load(f)['zones']
    except Exception:
        return []

def get_zone(zone_id):
    """Get zone by ID."""
    zones = load_zones()
    for z in zones:
        if z['id'] == zone_id:
            return z
    return None

def get_species_config(registry, species_key):
    """Get full species config, resolving inheritance."""
    species = registry.get('species', {}).get(species_key, {})
    if 'inherits' in species:
        parent = registry.get('species', {}).get(species['inherits'], {})
        # Merge parent into species (species overrides parent)
        merged = {**parent, **species}
        return merged
    return species

def check_gates(registry, species_key, zone, month, weather):
    """Check if species passes all gates. Return (pass, reason)."""
    species = get_species_config(registry, species_key)

    # Gate 1: Month in season window
    if 'months' in species:
        if month not in species['months']:
            return False, f"month {month} outside {species['months']}"
    elif 'months_coastal' in species or 'months_interior' in species:
        if zone.get('coastal'):
            if month not in species.get('months_coastal', []):
                return False, f"coastal month {month} outside {species.get('months_coastal', [])}"
        else:
            if month not in species.get('months_interior', []):
                return False, f"interior month {month} outside {species.get('months_interior', [])}"

    # Gate 2: Elevation band
    elev_bands = species.get('elev_bands_ft', {})
    if elev_bands:
        if 'all' in elev_bands:
            lo, hi = elev_bands['all']
        else:
            month_str = str(month)
            if month_str in elev_bands:
                lo, hi = elev_bands[month_str]
            else:
                return False, f"no elevation band for month {month}"

        # Apply southern shift for lat < 43.2
        if zone['lat'] < 43.2 and 'southern_shift_weeks' in species:
            shift_weeks = species['southern_shift_weeks']
            # Not implemented in scoring, just in doc
            pass

        if not (lo <= zone['elev_ft'] <= hi):
            return False, f"elev {zone['elev_ft']} outside [{lo}, {hi}]"

    # Gate 3: Side allow
    if 'side_allow' in species:
        if zone.get('side') not in species['side_allow']:
            return False, f"zone side {zone.get('side')} not in {species['side_allow']}"

    # Gate 4: Species in zone
    if species_key not in zone.get('species', []):
        return False, f"species not in zone species list"

    # Gate 5: Hard freeze (chanterelle, king_fall)
    if species_key in ['chanterelle', 'king_fall']:
        frost_3n = weather.get('frost_nights_last3', 0)
        if frost_3n >= 3:
            if species_key == 'chanterelle' and 'hard_freeze_3n_27F' in species.get('penalties', {}):
                if species['penalties']['hard_freeze_3n_27F'] == 0.0:
                    return False, "hard freeze kills season"
            elif species_key == 'king_fall':
                if species['penalties'].get('hard_freeze_3n_27F') == 0.0:
                    return False, "hard freeze kills season"

    return True, None

def score_species(registry, species_key, zone, month, weather, fires_data=None):
    """Score one species in one zone."""
    species = get_species_config(registry, species_key)

    # Check gates
    passed, reason = check_gates(registry, species_key, zone, month, weather)
    if not passed:
        return {
            'zone': zone['id'],
            'species': species_key,
            'score': 0,
            'label': 'gated out',
            'reasons': [reason or 'gated'],
            'negatives': [],
            'confidence': 'high',
            'data_asof': weather.get('data_timestamp', '')
        }

    # Compute components
    reasons = []
    negatives = []

    # Soil temperature
    soil_t_7d = weather.get('soil_t_7d_mean')
    soil_temp_tri = species.get('soil_temp_tri', [41, 48, 56, 63])
    s_soil = tri(soil_t_7d, *soil_temp_tri)
    if soil_t_7d:
        reasons.append(f"soil {int(soil_t_7d)}F ({'prime' if 0.8 <= s_soil <= 1.0 else 'marginal' if s_soil > 0.4 else 'poor'})")

    # Moisture
    moist_config = species.get('moisture', {})
    s_moist = 0.0
    if 'precip_30d_ramp' in moist_config:
        precip_30d = weather.get('precip_30d', 0)
        lo, hi = moist_config['precip_30d_ramp']
        s_moist_precip = ramp(precip_30d, lo, hi)
        if moist_config.get('combine') == 'solo':
            s_moist = s_moist_precip
        else:
            s_moist = max(s_moist, s_moist_precip)
    if 'soil_moisture_ramp' in moist_config:
        soil_moist = weather.get('soil_moisture_7d_mean')
        lo, hi = moist_config['soil_moisture_ramp']
        s_moist_soil = ramp(soil_moist, lo, hi)
        if moist_config.get('combine') == 'solo':
            s_moist = s_moist_soil
        else:
            s_moist = max(s_moist, s_moist_soil)
    if 'precip_14d_ramp' in moist_config:
        precip_14d = weather.get('precip_14d', 0)
        lo, hi = moist_config['precip_14d_ramp']
        s_moist = ramp(precip_14d, lo, hi)

    if s_moist > 0:
        reasons.append(f"{weather.get('precip_14d', weather.get('precip_30d', 0)):.1f}in/14d ({'good' if s_moist > 0.7 else 'fair'})")

    # Trigger
    trigger_config = species.get('trigger', {})
    s_trig = 0.0
    trigger_reason = ""

    if trigger_config.get('type') == 'days_since_meltout':
        # Try SNOTEL melt date first
        melt_date = weather.get('melt_out_date')
        if melt_date:
            try:
                melt_dt = datetime.fromisoformat(melt_date)
                today_dt = datetime.utcnow()
                days_since = (today_dt.date() - melt_dt.date()).days
                tri_params = trigger_config.get('tri', [5, 10, 24, 35])
                s_trig = tri(days_since, *tri_params)
                trigger_reason = f"melt-out {melt_date} +{days_since}d ({'peak' if 0.8 <= s_trig <= 1.0 else 'marginal'})"
            except:
                pass
        else:
            # Fallback to rain event if available
            fallback = trigger_config.get('fallback', {})
            if fallback.get('type') == 'days_since_rain_event':
                last_rain = weather.get('last_rain_event')
                if last_rain:
                    try:
                        rain_dt = datetime.fromisoformat(last_rain)
                        today_dt = datetime.utcnow()
                        days_since = (today_dt.date() - rain_dt.date()).days
                        tri_params = fallback.get('tri', [3, 7, 18, 28])
                        s_trig = tri(days_since, *tri_params)
                        trigger_reason = f"rain {last_rain} +{days_since}d (estimated)"
                    except:
                        pass

    elif trigger_config.get('type') == 'days_since_rain_event':
        last_rain = weather.get('last_rain_event')
        event_in = trigger_config.get('event_in', 0.5)
        if last_rain:
            try:
                rain_dt = datetime.fromisoformat(last_rain)
                today_dt = datetime.utcnow()
                days_since = (today_dt.date() - rain_dt.date()).days
                tri_params = trigger_config.get('tri', [7, 10, 21, 30])
                s_trig = tri(days_since, *tri_params)
                trigger_reason = f"rain {last_rain} +{days_since}d"
            except:
                pass

    elif trigger_config.get('type') == 'days_since_season_opener':
        opener_rule = trigger_config.get('opener_rule', {})
        archive = weather.get('archive_data', {})
        if archive and 'daily' in archive:
            precip_daily = archive.get('daily', {}).get('precipitation_sum', [])
            time_daily = archive.get('daily', {}).get('time', [])
            # Find rolling 7-day with >= opener precip threshold
            opener_precip_threshold = opener_rule.get('rolling_7d_precip_in', 1.5)
            opener_date = None
            for i in range(len(precip_daily)):
                rolling_7d = sum(precip_daily[max(0, i-6):i+1])
                if rolling_7d >= opener_precip_threshold:
                    opener_date = time_daily[i]
                    break
            if opener_date:
                try:
                    opener_dt = datetime.fromisoformat(opener_date)
                    today_dt = datetime.utcnow()
                    days_since = (today_dt.date() - opener_dt.date()).days
                    tri_params = trigger_config.get('tri', [10, 20, 70, 100])
                    s_trig = tri(days_since, *tri_params)
                    trigger_reason = f"season opened {opener_date} +{days_since}d"
                except:
                    s_trig = trigger_config.get('no_opener_score', 0)
                    trigger_reason = "no season opener detected"
            else:
                s_trig = trigger_config.get('no_opener_score', 0)
                trigger_reason = "no season opener"
        else:
            s_trig = trigger_config.get('no_opener_score', 0)
            trigger_reason = "no archive data"

    if trigger_reason:
        reasons.append(trigger_reason)

    # Air temperature (if weighted)
    s_air = 0.0
    if 'air' in species.get('weights', {}):
        air_max = weather.get('air_temp_7d_mean_max')
        s_air = tri(air_max, 45, 55, 72, 85) if air_max else 0.0

    # Compute base score
    weights = species.get('weights', {})
    score = 100 * (
        weights.get('soil_temp', 0) * s_soil +
        weights.get('moisture', 0) * s_moist +
        weights.get('trigger', 0) * s_trig +
        weights.get('air', 0) * s_air
    )

    # Apply penalties
    penalties = species.get('penalties', {})

    # Frost penalty
    if 'frost_28F_last3d' in penalties:
        frost_3d = weather.get('frost_nights_last3', 0)
        if frost_3d > 0:
            score *= penalties['frost_28F_last3d']
            negatives.append(f"frost {frost_3d} nights last 3d")

    # Frost memory: any night at 28 F or colder in the last 14 days (fruiting ends with the first frosts)
    if 'frost_28F_last14d' in penalties and weather.get('frost_nights_last14', 0) > 0:
        score *= penalties['frost_28F_last14d']
        negatives.append("frost in the last 14 days")

    # Heat penalty
    if 'soil_7d_mean_above' in penalties:
        threshold, factor = penalties['soil_7d_mean_above']
        soil_t_7d = weather.get('soil_t_7d_mean', 0)
        if soil_t_7d > threshold:
            score *= factor
            negatives.append(f"soil {int(soil_t_7d)}F above {threshold}F")

    # Hard freeze for chanterelle
    if species_key == 'chanterelle' and 'hard_freeze_3n_27F' in penalties:
        frost_5d = weather.get('frost_nights_last5', 0)
        if frost_5d >= 3:
            score *= penalties['hard_freeze_3n_27F']

    # Single frost for chanterelle
    if species_key == 'chanterelle' and 'single_frost_28F' in penalties:
        frost_3d = weather.get('frost_nights_last3', 0)
        if frost_3d >= 1:                    # was == 1, which skipped 2 frost nights in 3 days
            score *= penalties['single_frost_28F']

    # Dry gap for chanterelle
    if species_key == 'chanterelle' and 'dry_gap_21d' in penalties:
        # Simple check: if last 21d precip is low
        precip_14d = weather.get('precip_14d', 0)
        if precip_14d < 0.5:
            score *= penalties['dry_gap_21d']

    # Clamp and get label
    score = max(0, min(100, score))

    labels = registry.get('score_labels', [])
    label = 'unknown'
    for lo, hi, lbl in labels:
        if lo <= score <= hi:
            label = lbl
            break

    confidence = 'high' if all(k in weather for k in ['soil_t_7d_mean', 'precip_14d', 'last_rain_event']) else 'med'

    return {
        'zone': zone['id'],
        'species': species_key,
        'score': int(round(score)),
        'label': label,
        'reasons': reasons,
        'negatives': negatives,
        'confidence': confidence,
        'data_asof': weather.get('data_timestamp', '')
    }

def main():
    if len(sys.argv) < 3:
        print(json.dumps({'error': 'usage: score.py lat lon month [zone_id]'}))
        sys.exit(0)

    try:
        lat = float(sys.argv[1])
        lon = float(sys.argv[2])
        month = int(sys.argv[3])
        zone_id = sys.argv[4] if len(sys.argv) > 4 else None
    except (ValueError, IndexError):
        print(json.dumps({'error': 'invalid arguments'}))
        sys.exit(0)

    # Read weather from stdin
    try:
        weather = json.load(sys.stdin)
    except:
        print(json.dumps({'error': 'invalid weather JSON'}))
        sys.exit(0)

    registry = load_registry()
    if not registry:
        print(json.dumps({'error': 'registry not found'}))
        sys.exit(0)

    # Determine zone(s)
    zones = load_zones()
    if zone_id:
        zones = [z for z in zones if z['id'] == zone_id]
    else:
        zones = [z for z in zones if abs(z['lat'] - lat) < 1 and abs(z['lon'] - lon) < 1]

    results = []
    for zone in zones:
        # Score each species in this zone
        for species_key in zone.get('species', []):
            result = score_species(registry, species_key, zone, month, weather)
            results.append(result)

    # Sort by score (highest first)
    results.sort(key=lambda r: (-r['score'], r['zone']))

    print(json.dumps(results, indent=2))
    sys.exit(0)

if __name__ == '__main__':
    main()
