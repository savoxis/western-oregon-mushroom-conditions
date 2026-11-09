#!/usr/bin/env python3
"""
geo.py - Geocoding, elevation, haversine distance.
CLI: python3 geo.py "location_string" [lat lon for distance calc]
Returns JSON: {lat, lon, elev_ft, matched, ambiguous: [...]}
"""

import sys
import json
import math
import urllib.request
import urllib.error
import urllib.parse
import os
import time
from datetime import datetime, timedelta

CACHE_DIR = os.path.join(os.path.dirname(__file__), '..', 'cache')
ZONES_FILE = os.path.join(os.path.dirname(__file__), '..', 'references', 'zones.json')
GEOCODE_CACHE = os.path.join(CACHE_DIR, 'geocode_cache.json')
ELEV_CACHE = os.path.join(CACHE_DIR, 'elevation_cache.json')

BBOX = {"min_lat": 41.9, "max_lat": 44.8, "min_lon": -124.7, "max_lon": -120.6}

def ensure_cache_dir():
    """Create cache directory if missing."""
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)

def load_zones():
    """Load and return the zones gazetteer."""
    try:
        with open(ZONES_FILE) as f:
            return json.load(f)['zones']
    except Exception:
        return []

def match_zone_name(location):
    """Try to match location against gazetteer zone names exactly or fuzzy."""
    zones = load_zones()
    location_lower = location.lower().strip()

    # Exact match on zone name
    for zone in zones:
        if zone['name'].lower() == location_lower:
            return {
                'lat': zone['lat'],
                'lon': zone['lon'],
                'elev_ft': zone['elev_ft'],
                'matched': zone['id'],
                'ambiguous': []
            }

    # Fuzzy: check if location appears in zone name
    matches = []
    for zone in zones:
        if location_lower in zone['name'].lower():
            matches.append(zone)

    if len(matches) == 1:
        z = matches[0]
        return {
            'lat': z['lat'],
            'lon': z['lon'],
            'elev_ft': z['elev_ft'],
            'matched': z['id'],
            'ambiguous': []
        }
    elif len(matches) > 1:
        return {
            'matched': None,
            'ambiguous': [z['name'] for z in matches]
        }

    return None

def parse_raw_coords(location):
    """Try to parse 'lat,lon' or 'lat, lon' raw coordinate strings."""
    parts = location.split(',')
    if len(parts) != 2:
        return None
    try:
        lat = float(parts[0].strip())
        lon = float(parts[1].strip())
        if BBOX['min_lat'] <= lat <= BBOX['max_lat'] and BBOX['min_lon'] <= lon <= BBOX['max_lon']:
            return {'lat': lat, 'lon': lon}
    except (ValueError, AttributeError):
        pass
    return None

def read_cache(cache_file, ttl_seconds):
    """Read cache if exists and not expired."""
    if not os.path.exists(cache_file):
        return {}
    try:
        with open(cache_file) as f:
            cache = json.load(f)
        now = time.time()
        result = {}
        for key, entry in cache.items():
            if now - entry.get('timestamp', 0) < ttl_seconds:
                result[key] = entry['data']
        return result
    except Exception:
        return {}

def write_cache(cache_file, key, data):
    """Write single entry to cache."""
    ensure_cache_dir()
    cache = {}
    if os.path.exists(cache_file):
        try:
            with open(cache_file) as f:
                cache = json.load(f)
        except Exception:
            cache = {}

    cache[key] = {
        'data': data,
        'timestamp': time.time()
    }
    try:
        with open(cache_file, 'w') as f:
            json.dump(cache, f)
    except Exception:
        pass

def geocode_open_meteo(location):
    """Geocode via Open-Meteo, return best Oregon match or list of ambiguous."""
    cache = read_cache(GEOCODE_CACHE, 86400 * 30)  # 30-day TTL
    if location in cache:
        return cache[location]

    url = (f"https://geocoding-api.open-meteo.com/v1/search"
           f"?name={urllib.parse.quote(location)}"
           f"&count=5&language=en&format=json&countryCode=US")

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
                return {'error': f'geocoding unavailable: {str(e)}'}

    if 'results' not in data or not data['results']:
        return {'error': 'location not found'}

    # Filter for Oregon, check bbox
    oregon_matches = []
    for result in data['results']:
        if result.get('admin1') == 'Oregon':
            lat, lon = result['latitude'], result['longitude']
            if BBOX['min_lat'] <= lat <= BBOX['max_lat'] and BBOX['min_lon'] <= lon <= BBOX['max_lon']:
                oregon_matches.append({
                    'name': result.get('name', ''),
                    'lat': lat,
                    'lon': lon,
                    'admin1': result.get('admin1', '')
                })

    if len(oregon_matches) == 0:
        # No Oregon match in bbox, try all results
        for result in data['results']:
            lat, lon = result['latitude'], result['longitude']
            if BBOX['min_lat'] <= lat <= BBOX['max_lat'] and BBOX['min_lon'] <= lon <= BBOX['max_lon']:
                return {
                    'lat': lat,
                    'lon': lon,
                    'matched': result.get('name', ''),
                    'ambiguous': []
                }
        return {'error': 'location outside service area'}

    if len(oregon_matches) == 1:
        result = oregon_matches[0]
        result['matched'] = result.pop('name')
        result['ambiguous'] = []
        write_cache(GEOCODE_CACHE, location, result)
        return result
    else:
        # Multiple matches
        result = {
            'matched': None,
            'ambiguous': [m['name'] for m in oregon_matches]
        }
        write_cache(GEOCODE_CACHE, location, result)
        return result

def get_elevation(lat, lon):
    """Fetch elevation in feet from Open-Meteo."""
    cache = read_cache(ELEV_CACHE, 86400 * 365)  # 1-year TTL (permanent-ish)
    key = f"{lat:.4f},{lon:.4f}"
    if key in cache:
        return cache[key]

    url = f"https://api.open-meteo.com/v1/elevation?latitude={lat}&longitude={lon}"

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
                return None

    elev_m = data.get('elevation', [None])[0]
    if elev_m is None:
        return None

    elev_ft = int(round(elev_m * 3.28084))
    write_cache(ELEV_CACHE, key, elev_ft)
    return elev_ft

def haversine(lat1, lon1, lat2, lon2):
    """Distance in km between two lat/lon points."""
    R = 6371.0  # Earth radius in km
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)

    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad

    a = math.sin(dlat / 2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2)**2
    c = 2 * math.asin(math.sqrt(a))

    return R * c

def main():
    if len(sys.argv) < 2:
        print(json.dumps({'error': 'usage: geo.py location_string [ref_lat ref_lon]'}))
        sys.exit(1)

    location = sys.argv[1]

    # Step 1: Try gazetteer match
    result = match_zone_name(location)
    if result:
        if result.get('matched'):
            # Get elevation if not already have it
            if 'elev_ft' not in result:
                elev = get_elevation(result['lat'], result['lon'])
                if elev:
                    result['elev_ft'] = elev
        print(json.dumps(result))
        sys.exit(0)

    # Step 2: Try raw coordinates
    coords = parse_raw_coords(location)
    if coords:
        elev = get_elevation(coords['lat'], coords['lon'])
        result = {
            'lat': coords['lat'],
            'lon': coords['lon'],
            'elev_ft': elev,
            'matched': 'raw_coordinates',
            'ambiguous': []
        }
        print(json.dumps(result))
        sys.exit(0)

    # Step 3: Geocode via Open-Meteo
    result = geocode_open_meteo(location)

    if result.get('error'):
        print(json.dumps(result))
        sys.exit(0)

    if result.get('matched') is None:
        print(json.dumps(result))
        sys.exit(0)

    # Get elevation
    if 'elev_ft' not in result:
        elev = get_elevation(result['lat'], result['lon'])
        if elev:
            result['elev_ft'] = elev

    print(json.dumps(result))
    sys.exit(0)

if __name__ == '__main__':
    main()
