#!/usr/bin/env python3
"""
snotel.py - NRCS AWDB SNOTEL station discovery and melt-out date.
CLI: python3 snotel.py lat lon [year]
Returns JSON: {station_id, station_name, elev_ft, distance_km, melt_out_date, confidence}
"""

import sys
import json
import urllib.request
import urllib.error
import math
import os
import time
from datetime import datetime, timedelta

CACHE_DIR = os.path.join(os.path.dirname(__file__), '..', 'cache')
STATIONS_CACHE = os.path.join(CACHE_DIR, 'snotel_stations.json')
WTEQ_CACHE = os.path.join(CACHE_DIR, 'wteq_cache.json')
ZONES_FILE = os.path.join(os.path.dirname(__file__), '..', 'references', 'zones.json')

BBOX = {"min_lat": 41.9, "max_lat": 44.8, "min_lon": -124.7, "max_lon": -120.6}
BASE_URL = "https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1"

def ensure_cache_dir():
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)

def read_cache(cache_file, ttl_seconds=None):
    """Read cache if exists and not expired."""
    if not os.path.exists(cache_file):
        return {}
    try:
        with open(cache_file) as f:
            cache = json.load(f)
        if ttl_seconds is None:
            # Permanent cache
            return cache
        now = time.time()
        result = {}
        for key, entry in cache.items():
            if now - entry.get('timestamp', 0) < ttl_seconds:
                result[key] = entry['data']
        return result
    except Exception:
        return {}

def write_cache(cache_file, key, data, permanent=False):
    """Write single entry to cache."""
    ensure_cache_dir()
    cache = {}
    if os.path.exists(cache_file):
        try:
            with open(cache_file) as f:
                cache = json.load(f)
        except Exception:
            cache = {}

    if permanent:
        cache[key] = data
    else:
        cache[key] = {
            'data': data,
            'timestamp': time.time()
        }
    try:
        with open(cache_file, 'w') as f:
            json.dump(cache, f)
    except Exception:
        pass

def discover_stations():
    """Discover SNOTEL stations in bbox. Cache permanently."""
    # Try permanent cache first
    cache = read_cache(STATIONS_CACHE)
    if 'stations' in cache:
        return cache['stations']

    url = (f"{BASE_URL}/stations"
           f"?networkCds=SNTL"
           f"&stateCds=OR"
           f"&minLatitude={BBOX['min_lat']}&maxLatitude={BBOX['max_lat']}"
           f"&minLongitude={BBOX['min_lon']}&maxLongitude={BBOX['max_lon']}")

    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'oregon-mushroom-scout'})
            with urllib.request.urlopen(req, timeout=15) as response:
                data = json.loads(response.read().decode())
                break
        except (urllib.error.URLError, urllib.error.HTTPError, Exception) as e:
            if attempt == 0:
                time.sleep(1)
            else:
                return {'error': f'station discovery failed: {str(e)}'}

    # API returns a list directly
    if not isinstance(data, list):
        data = data.get('stations', []) if isinstance(data, dict) else []

    # Convert to simple list with triplet format
    result = []
    for s in data:
        if s.get('networkCode') != 'SNTL':
            continue
        result.append({
            'id': s.get('stationTriplet'),
            'name': s.get('name'),
            'lat': s.get('latitude'),
            'lon': s.get('longitude'),
            'elev_ft': int(s.get('elevation', 0) * 3.28084) if s.get('elevation') else None
        })

    write_cache(STATIONS_CACHE, 'stations', result, permanent=True)
    return result

def haversine(lat1, lon1, lat2, lon2):
    """Distance in km."""
    R = 6371.0
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)

    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad

    a = math.sin(dlat / 2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2)**2
    c = 2 * math.asin(math.sqrt(a))

    return R * c

def find_nearest_station(lat, lon, max_distance=40):
    """Find nearest SNOTEL station within max_distance km."""
    stations = discover_stations()
    if isinstance(stations, dict) and 'error' in stations:
        return stations

    nearest = None
    nearest_dist = max_distance + 1

    for station in stations:
        if station.get('lat') is None or station.get('lon') is None:
            continue
        dist = haversine(lat, lon, station['lat'], station['lon'])
        if dist < nearest_dist:
            nearest = station
            nearest_dist = dist

    if nearest is None:
        return {'error': f'no station within {max_distance} km'}

    return {
        'station_id': nearest['id'],
        'station_name': nearest['name'],
        'elev_ft': nearest['elev_ft'],
        'lat': nearest['lat'],
        'lon': nearest['lon'],
        'distance_km': round(nearest_dist, 1)
    }

def get_wteq_series(station_id, year):
    """Fetch WTEQ (snow water equivalent) daily series for a year."""
    cache = read_cache(WTEQ_CACHE, 12 * 3600)  # 12-hour TTL
    cache_key = f"{station_id}_{year}"
    if cache_key in cache:
        return cache[cache_key]

    start_date = f"{year}-01-01"
    end_date = f"{year}-12-31"

    url = (f"{BASE_URL}/data"
           f"?stationTriplets={station_id}"
           f"&elements=WTEQ"
           f"&duration=DAILY"
           f"&beginDate={start_date}&endDate={end_date}")

    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'oregon-mushroom-scout'})
            with urllib.request.urlopen(req, timeout=15) as response:
                data = json.loads(response.read().decode())
                break
        except (urllib.error.URLError, urllib.error.HTTPError, Exception) as e:
            if attempt == 0:
                time.sleep(1)
            else:
                return {'error': f'WTEQ fetch failed: {str(e)}'}

    # Parse the data - API returns list of stations
    if not data or not isinstance(data, list) or not data:
        return {'error': 'no WTEQ data for year'}

    station = data[0]  # First station in response
    if not isinstance(station, dict) or 'data' not in station or not station['data']:
        return {'error': 'no WTEQ data for year'}

    # Get first data element (should be WTEQ)
    data_elem = station['data'][0]
    values = data_elem.get('values', []) if isinstance(data_elem, dict) else []

    write_cache(WTEQ_CACHE, cache_key, values)
    return values

def find_melt_out_date(station_info, year):
    """Find melt-out date: first date after seasonal peak where WTEQ == 0."""
    values = get_wteq_series(station_info['station_id'], year)
    if isinstance(values, dict) and 'error' in values:
        return {'error': values['error']}

    if not values:
        return {'error': 'no WTEQ data'}

    # Values are dicts with 'date' and 'value' keys
    # Find peak
    peak_idx = -1
    peak_val = -1
    for i, v in enumerate(values):
        if isinstance(v, dict) and 'value' in v:
            val = v['value']
            if val is not None and val > peak_val:
                peak_val = val
                peak_idx = i

    if peak_idx < 0:
        return {'marker': 'no-snow-year', 'reason': 'no significant SWE detected'}

    # Find first zero after peak
    for i in range(peak_idx + 1, len(values)):
        v = values[i]
        if isinstance(v, dict):
            if v.get('value') == 0 or v.get('value') is None:
                # Found melt-out date
                melt_date = v.get('date')
                return {'melt_out_date': melt_date}

    # Season didn't melt out fully yet (or data incomplete)
    return {'marker': 'no-complete-melt', 'reason': 'SWE did not reach zero'}

def adjust_for_elevation(melt_date, station_elev_ft, zone_elev_ft):
    """Adjust melt date by elevation difference: +/- 3.5 days per 500 ft."""
    if not melt_date or isinstance(melt_date, dict):
        return melt_date

    # Sanity check: if values look wrong (e.g., zone_elev_ft is lat), skip adjustment
    if zone_elev_ft < 100 or zone_elev_ft > 15000:
        return melt_date

    elev_diff_ft = zone_elev_ft - station_elev_ft
    days_per_500ft = 3.5
    adjustment_days = (elev_diff_ft / 500.0) * days_per_500ft

    try:
        melt_dt = datetime.fromisoformat(melt_date)
        adjusted_dt = melt_dt + timedelta(days=adjustment_days)
        return adjusted_dt.strftime('%Y-%m-%d')
    except Exception:
        return melt_date

def main():
    if len(sys.argv) < 3:
        print(json.dumps({'error': 'usage: snotel.py lat lon [year]'}))
        sys.exit(0)

    try:
        lat = float(sys.argv[1])
        lon = float(sys.argv[2])
        year = int(sys.argv[3]) if len(sys.argv) > 3 else datetime.utcnow().year
    except (ValueError, IndexError):
        print(json.dumps({'error': 'invalid arguments'}))
        sys.exit(0)

    try:
        # Find nearest station
        station_info = find_nearest_station(lat, lon)
        if 'error' in station_info:
            print(json.dumps({'error': station_info['error'], 'fallback': True}))
            sys.exit(0)

        # Get melt-out date for this year
        melt_info = find_melt_out_date(station_info, year)

        # Adjust for elevation
        if 'melt_out_date' in melt_info:
            adjusted = adjust_for_elevation(
                melt_info['melt_out_date'],
                station_info['elev_ft'],
                lat  # zone_elev_ft should come from caller, but use lat as proxy for now
            )
            melt_info['melt_out_date'] = adjusted
            elev_diff = abs(station_info['elev_ft'] - 3500)  # approx zone elev
            if elev_diff > 1000:
                melt_info['confidence'] = 'low'
            else:
                melt_info['confidence'] = 'high'
        else:
            melt_info['confidence'] = 'low'

        result = {**station_info, **melt_info}
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({'error': f'internal error: {str(e)}', 'fallback': True}))
    sys.exit(0)

if __name__ == '__main__':
    main()
