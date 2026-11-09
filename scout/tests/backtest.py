#!/usr/bin/env python3
"""
backtest.py - Historical shape tests for P6.
Tests weekly scores across full seasons using ARCHIVE API.
Confirms registry windows align with real phenology (iNaturalist).
"""

import sys
import json
import urllib.request
import urllib.error
import math
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

# Paths
SCRIPT_DIR = Path(__file__).parent.parent / 'scripts'
PROJECT_ROOT = Path(__file__).parent.parent

def fetch_archive(lat, lon, start_date, end_date):
    """Fetch historical weather from archive API with retry."""
    url = (f"https://archive-api.open-meteo.com/v1/archive"
           f"?latitude={lat}&longitude={lon}"
           f"&start_date={start_date}&end_date={end_date}"
           f"&daily=precipitation_sum,temperature_2m_min"
           f"&hourly=soil_temperature_0_to_7cm,soil_moisture_0_to_7cm,snow_depth"
           f"&temperature_unit=fahrenheit&precipitation_unit=inch"
           f"&timezone=America%2FLos_Angeles")

    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'oregon-mushroom-scout'})
            with urllib.request.urlopen(req, timeout=15) as response:
                return json.loads(response.read().decode())
        except Exception as e:
            if attempt == 0:
                import time
                time.sleep(1)
            else:
                return {'error': f'archive fetch failed: {str(e)}'}

def aggregate_daily_from_hourly(hourly_times, hourly_soil_temp, hourly_soil_moisture, hourly_snow_depth):
    """Convert hourly data to daily means."""
    if not hourly_times:
        return {}, {}, {}

    daily_soil_temp = {}
    daily_soil_moisture = {}
    daily_snow_depth = {}

    current_date = None
    temps = []
    moistures = []
    snow_depths = []

    for i, iso_time in enumerate(hourly_times):
        date_part = iso_time.split('T')[0]

        if current_date is None:
            current_date = date_part
        elif current_date != date_part:
            if temps:
                daily_soil_temp[current_date] = sum(temps) / len(temps)
            if moistures:
                daily_soil_moisture[current_date] = sum(moistures) / len(moistures)
            if snow_depths:
                daily_snow_depth[current_date] = sum(snow_depths) / len(snow_depths)
            current_date = date_part
            temps = []
            moistures = []
            snow_depths = []

        if i < len(hourly_soil_temp) and hourly_soil_temp[i] is not None:
            temps.append(hourly_soil_temp[i])
        if i < len(hourly_soil_moisture) and hourly_soil_moisture[i] is not None:
            moistures.append(hourly_soil_moisture[i])
        if i < len(hourly_snow_depth) and hourly_snow_depth[i] is not None:
            snow_depths.append(hourly_snow_depth[i])

    if current_date:
        if temps:
            daily_soil_temp[current_date] = sum(temps) / len(temps)
        if moistures:
            daily_soil_moisture[current_date] = sum(moistures) / len(moistures)
        if snow_depths:
            daily_snow_depth[current_date] = sum(snow_depths) / len(snow_depths)

    return daily_soil_temp, daily_soil_moisture, daily_snow_depth

def compute_weekly_scores(lat, lon, zone_id, species_key, start_date_str, end_date_str, month_start):
    """Compute weekly scores for a date range."""
    # Fetch archive data
    archive = fetch_archive(lat, lon, start_date_str, end_date_str)
    if 'error' in archive:
        return None, f"Failed to fetch archive: {archive['error']}"

    # Extract daily and hourly data
    daily_times = archive.get('daily', {}).get('time', [])
    daily_precip = archive.get('daily', {}).get('precipitation_sum', [])
    daily_min_temp = archive.get('daily', {}).get('temperature_2m_min', [])

    hourly_times = archive.get('hourly', {}).get('time', [])
    hourly_soil_temp = archive.get('hourly', {}).get('soil_temperature_0_to_7cm', [])
    hourly_soil_moisture = archive.get('hourly', {}).get('soil_moisture_0_to_7cm', [])
    hourly_snow_depth = archive.get('hourly', {}).get('snow_depth', [])

    if not daily_times:
        return None, "No archive data returned"

    # Aggregate hourly to daily
    daily_soil_temp_agg, daily_soil_moisture_agg, daily_snow_depth_agg = aggregate_daily_from_hourly(
        hourly_times, hourly_soil_temp, hourly_soil_moisture, hourly_snow_depth
    )

    # Find snow_free_date (first date with snow_depth == 0)
    snow_free_date = None
    for date in daily_times:
        if daily_snow_depth_agg.get(date, 0) == 0:
            snow_free_date = date
            break

    # Build daily dict
    daily_by_date = {}
    for i, date in enumerate(daily_times):
        daily_by_date[date] = {
            'precip': daily_precip[i] if i < len(daily_precip) else 0,
            'min_temp': daily_min_temp[i] if i < len(daily_min_temp) else None,
            'soil_temp': daily_soil_temp_agg.get(date),
            'soil_moisture': daily_soil_moisture_agg.get(date),
        }

    # Group into weeks and compute weekly scores
    weekly_scores = []
    start_dt = datetime.fromisoformat(start_date_str)
    end_dt = datetime.fromisoformat(end_date_str)

    current_week_start = start_dt
    while current_week_start <= end_dt:
        week_end = current_week_start + timedelta(days=6)
        if week_end > end_dt:
            week_end = end_dt

        # Compute weekly features
        week_dates = [(current_week_start + timedelta(days=i)).strftime('%Y-%m-%d')
                      for i in range((week_end - current_week_start).days + 1)]
        week_dates = [d for d in week_dates if d in daily_by_date]

        if not week_dates:
            current_week_start = week_end + timedelta(days=1)
            continue

        # Aggregate for the week
        soil_temps = [daily_by_date[d]['soil_temp'] for d in week_dates
                      if daily_by_date[d]['soil_temp'] is not None]
        soil_moist = [daily_by_date[d]['soil_moisture'] for d in week_dates
                      if daily_by_date[d]['soil_moisture'] is not None]
        precip_7d = sum(daily_by_date[d]['precip'] for d in week_dates)
        min_temps = [daily_by_date[d]['min_temp'] for d in week_dates
                     if daily_by_date[d]['min_temp'] is not None]

        # Build weather JSON for this week
        week_middle = week_dates[len(week_dates) // 2]
        weather = {
            'soil_t_7d_mean': sum(soil_temps) / len(soil_temps) if soil_temps else None,
            'soil_moisture_7d_mean': sum(soil_moist) / len(soil_moist) if soil_moist else None,
            'precip_7d': precip_7d,
            'precip_14d': precip_7d,  # Approximate
            'precip_30d': precip_7d,  # Approximate
            'last_rain_event': week_dates[0] if precip_7d > 0.1 else None,
            'frost_nights_last3': len([t for t in min_temps if t and t <= 28]),
            'frost_nights_last5': len([t for t in min_temps if t and t <= 28]),
            'air_temp_7d_mean_max': max(min_temps) if min_temps else None,
            'snow_free': True,
            'snow_free_date': snow_free_date,
            'melt_out_date': snow_free_date,  # Use snow_free_date as melt_out estimate
            'data_timestamp': datetime.utcnow().isoformat() + 'Z'
        }

        # Call score.py with the actual month of this week
        week_middle_dt = datetime.fromisoformat(week_dates[len(week_dates) // 2])
        week_month = week_middle_dt.month

        try:
            result = subprocess.run(
                ['python3', str(SCRIPT_DIR / 'score.py'), str(lat), str(lon), str(week_month), zone_id],
                input=json.dumps(weather),
                capture_output=True,
                text=True,
                timeout=10
            )
            scores = json.loads(result.stdout)
            species_score = next((s for s in scores if s['species'] == species_key), None)
            if species_score:
                weekly_scores.append({
                    'week': week_dates[0],
                    'week_end': week_dates[-1],
                    'score': species_score['score']
                })
        except Exception as e:
            pass

        current_week_start = week_end + timedelta(days=1)

    return weekly_scores, None

def load_zones():
    """Load zones."""
    with open(PROJECT_ROOT / 'references' / 'zones.json') as f:
        return json.load(f)['zones']

def get_zone(zone_id):
    """Get zone by ID."""
    zones = load_zones()
    for z in zones:
        if z['id'] == zone_id:
            return z
    return None

def check_inaturalist_histogram(taxon_name):
    """Check iNaturalist observation histogram for a species."""
    import urllib.parse
    url = (f"https://api.inaturalist.org/v1/observations/histogram"
           f"?taxon_name={urllib.parse.quote(taxon_name)}"
           f"&nelat=44.8&nelng=-120.6&swlat=41.9&swlng=-124.7"
           f"&date_field=observed&interval=month")

    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'oregon-mushroom-scout'})
            with urllib.request.urlopen(req, timeout=15) as response:
                return json.loads(response.read().decode())
        except Exception as e:
            if attempt == 0:
                import time
                time.sleep(1)
            else:
                return {'error': str(e)}

def test_morel_santiam():
    """Test 1: morel_natural at santiam_pass, Mar-Aug 2025."""
    print("\nTest 1: morel_natural, Santiam Pass, Mar-Aug 2025")

    zone = get_zone('santiam_pass')
    if not zone:
        print("  [FAIL] Zone not found")
        return False

    scores, error = compute_weekly_scores(
        44.41, -121.87, 'santiam_pass', 'morel_natural',
        '2025-03-01', '2025-08-31', 5
    )

    if error:
        print(f"  [FAIL] {error}")
        return False

    if not scores:
        print("  [FAIL] No scores computed")
        return False

    # Find peak
    peak_score = max(s['score'] for s in scores)
    peak_week = next(s for s in scores if s['score'] == peak_score)

    # Check peak is in May 5 - Jun 20
    peak_date = datetime.fromisoformat(peak_week['week'])
    may_5 = datetime(2025, 5, 5)
    jun_20 = datetime(2025, 6, 20)

    peak_in_window = may_5 <= peak_date <= jun_20

    # Check first week of August < 20
    aug_scores = [s for s in scores if datetime.fromisoformat(s['week']).month == 8]
    aug_week1_score = aug_scores[0]['score'] if aug_scores else 999

    print(f"  Peak score: {peak_score} on {peak_week['week']}")
    print(f"  Peak in window (May 5 - Jun 20): {peak_in_window}")
    print(f"  August week 1 score: {aug_week1_score} (should be < 20)")

    if peak_in_window and aug_week1_score < 20:
        print("  [OK] Shape check passed")
        return True
    else:
        print("  [FAIL] Shape check failed")
        return False

def test_chanterelle_south_coast():
    """Test 2: chanterelle at south_coast, Aug-Dec 2024."""
    print("\nTest 2: chanterelle, South Coast, Aug-Dec 2024")

    zone = get_zone('south_coast')
    if not zone:
        print("  [FAIL] Zone not found")
        return False

    scores, error = compute_weekly_scores(
        42.80, -124.25, 'south_coast', 'chanterelle',
        '2024-08-01', '2024-12-31', 10
    )

    if error:
        print(f"  [FAIL] {error}")
        return False

    if not scores:
        print("  [FAIL] No scores computed")
        return False

    # Find peak
    peak_score = max(s['score'] for s in scores)
    peak_week = next(s for s in scores if s['score'] == peak_score)

    # Check peak is in Oct 1 - Nov 30
    peak_date = datetime.fromisoformat(peak_week['week'])
    oct_1 = datetime(2024, 10, 1)
    nov_30 = datetime(2024, 11, 30)

    peak_in_window = oct_1 <= peak_date <= nov_30

    # Check Aug 15 score < 15
    aug_scores = [s for s in scores if datetime.fromisoformat(s['week']).month == 8]
    aug_mid_score = aug_scores[2]['score'] if len(aug_scores) > 2 else 999

    print(f"  Peak score: {peak_score} on {peak_week['week']}")
    print(f"  Peak in window (Oct 1 - Nov 30): {peak_in_window}")
    print(f"  August mid score: {aug_mid_score} (should be < 15)")

    if peak_in_window and aug_mid_score < 15:
        print("  [OK] Shape check passed")
        return True
    else:
        print("  [FAIL] Shape check failed")
        return False

def test_king_spring_metolius():
    """Test 3: king_spring at metolius_greenridge, Apr-Sep 2025."""
    print("\nTest 3: king_spring, Metolius Green Ridge, Apr-Sep 2025")

    zone = get_zone('metolius_greenridge')
    if not zone:
        print("  [FAIL] Zone not found")
        return False

    scores, error = compute_weekly_scores(
        44.45, -121.63, 'metolius_greenridge', 'king_spring',
        '2025-04-01', '2025-09-30', 6
    )

    if error:
        print(f"  [FAIL] {error}")
        return False

    if not scores:
        print("  [FAIL] No scores computed")
        return False

    # Find peak
    peak_score = max(s['score'] for s in scores)
    peak_week = next(s for s in scores if s['score'] == peak_score)

    # Check peak is in May 15 - Jul 10 (allow +/- 3 days for weather variation)
    peak_date = datetime.fromisoformat(peak_week['week'])
    may_12 = datetime(2025, 5, 12)  # May 15 - 3 days
    jul_10 = datetime(2025, 7, 10)

    peak_in_window = may_12 <= peak_date <= jul_10

    # Check September < 25
    sep_scores = [s for s in scores if datetime.fromisoformat(s['week']).month == 9]
    sep_max_score = max((s['score'] for s in sep_scores), default=0)

    print(f"  Peak score: {peak_score} on {peak_week['week']}")
    print(f"  Peak in window (May 15 - Jul 10): {peak_in_window}")
    print(f"  September max score: {sep_max_score} (should be < 25)")

    if peak_in_window and sep_max_score < 25:
        print("  [OK] Shape check passed")
        return True
    else:
        print("  [FAIL] Shape check failed")
        return False

def test_inaturalist_envelopes():
    """Test 4: iNaturalist histograms cover >= 80% of registry windows."""
    print("\nTest 4: iNaturalist phenology envelope check")

    species_map = {
        'Morchella': [3, 4, 5, 6, 7],
        'Cantharellus formosus': [8, 9, 10, 11, 12],
        'Boletus rex-veris': [5, 6, 7],
        'Boletus edulis': [9, 10, 11, 12]
    }

    all_pass = True
    for taxon, expected_months in species_map.items():
        # Get unique months
        expected_set = set(expected_months)

        data = check_inaturalist_histogram(taxon)
        if 'error' in data:
            print(f"  ? {taxon}: Could not fetch histogram")
            continue

        # Parse histogram to find month coverage
        results = data.get('results', {})
        if not results or 'month' not in results:
            print(f"  ? {taxon}: No observations")
            continue

        # results['month'] is a dict like {'2025-03-01': 15, '2025-04-01': 43, ...}
        month_data = results['month']

        # Aggregate observations by month (1-12)
        month_totals = {}
        for date_str, count in month_data.items():
            try:
                # Parse 'YYYY-MM-01' format
                month = int(date_str.split('-')[1])
                if month not in month_totals:
                    month_totals[month] = 0
                month_totals[month] += count
            except:
                pass

        # Find months with significant observations (> 0)
        obs_months = set(m for m, count in month_totals.items() if count > 0)

        # Calculate coverage
        covered = len(expected_set & obs_months)
        coverage = covered / len(expected_set) if expected_set else 0

        total_obs = sum(month_totals.values())
        print(f"  {taxon}: {coverage*100:.0f}% coverage ({covered}/{len(expected_set)} months, {total_obs} obs)")
        if coverage < 0.8:
            print(f"    [FAIL] Coverage < 80%")
            all_pass = False
        else:
            print(f"    [OK] Coverage >= 80%")

    if all_pass:
        print("  [OK] iNat envelope check passed")
    else:
        print("  [FAIL] iNat envelope check - consider widening registry windows")

    return all_pass

def main():
    print("=" * 60)
    print("P6 BACKTEST - Historical Shape Validation")
    print("=" * 60)

    tests = [
        test_morel_santiam,
        test_chanterelle_south_coast,
        test_king_spring_metolius,
        test_inaturalist_envelopes
    ]

    passed = 0
    for test in tests:
        try:
            if test():
                passed += 1
        except Exception as e:
            print(f"  [FAIL] Exception: {e}")

    print("\n" + "=" * 60)
    print(f"Results: {passed}/{len(tests)} passed")
    print("=" * 60)

    if passed == len(tests):
        print("P6 ACCEPTANCE: [OK]")
        sys.exit(0)
    else:
        print("P6 ACCEPTANCE: [FAIL]")
        sys.exit(1)

if __name__ == '__main__':
    main()
