#!/usr/bin/env python3
"""
fires.py - Query WFIGS fire perimeters, compute distance and elevation.
CLI: python3 fires.py lat lon [radius_km]
Returns JSON list of fires >= 500 acres.
"""

import sys
import json
import urllib.request
import urllib.error
import urllib.parse
import math
import os
import time
from datetime import datetime, timedelta

CACHE_DIR = os.path.join(os.path.dirname(__file__), '..', 'cache')
FIRES_CACHE = os.path.join(CACHE_DIR, 'fires_cache.json')

BBOX = {"min_lat": 41.9, "max_lat": 44.8, "min_lon": -124.7, "max_lon": -120.6}

def ensure_cache_dir():
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)

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

def query_wfigs():
    """Query WFIGS for fires 2025-01-01 onward, >= 500 acres."""
    cache = read_cache(FIRES_CACHE, 24 * 3600)  # 24-hour TTL
    if 'wfigs' in cache:
        return cache['wfigs']

    # Build where clause and URL
    where_clause = "poly_GISAcres >= 500 AND attr_FireDiscoveryDateTime >= DATE '2025-01-01'"
    geometry = f"{BBOX['min_lon']},{BBOX['min_lat']},{BBOX['max_lon']},{BBOX['max_lat']}"

    url = (f"https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/"
           f"WFIGS_Interagency_Perimeters/FeatureServer/0/query"
           f"?where={urllib.parse.quote(where_clause)}"
           f"&geometry={geometry}"
           f"&geometryType=esriGeometryEnvelope"
           f"&inSR=4326"
           f"&spatialRel=esriSpatialRelIntersects"
           f"&outFields=poly_IncidentName,attr_FireDiscoveryDateTime,poly_GISAcres"
           f"&returnGeometry=true"
           f"&outSR=4326"
           f"&f=geojson")

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
                return {'error': f'WFIGS query failed: {str(e)}'}

    write_cache(FIRES_CACHE, 'wfigs', data)
    return data

def get_elevation(lat, lon):
    """Fetch elevation for a point."""
    cache = os.path.join(CACHE_DIR, 'elevation_cache.json')
    key = f"{lat:.4f},{lon:.4f}"

    # Try cache
    try:
        if os.path.exists(cache):
            with open(cache) as f:
                cache_data = json.load(f)
                if key in cache_data:
                    return cache_data[key]
    except Exception:
        pass

    url = f"https://api.open-meteo.com/v1/elevation?latitude={lat}&longitude={lon}"

    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'oregon-mushroom-scout'})
            with urllib.request.urlopen(req, timeout=15) as response:
                data = json.loads(response.read().decode())
                break
        except (urllib.error.URLError, urllib.error.HTTPError, Exception):
            if attempt == 0:
                time.sleep(1)
            else:
                return None

    elev_m = data.get('elevation', [None])[0]
    if elev_m is None:
        return None

    elev_ft = int(round(elev_m * 3.28084))

    # Write to cache
    try:
        ensure_cache_dir()
        cache_data = {}
        if os.path.exists(cache):
            with open(cache) as f:
                cache_data = json.load(f)
        cache_data[key] = elev_ft
        with open(cache, 'w') as f:
            json.dump(cache_data, f)
    except Exception:
        pass

    return elev_ft

def centroid_of_polygon(coordinates):
    """Compute centroid of a polygon (list of [lon, lat] pairs)."""
    if not coordinates or not coordinates[0]:
        return None, None

    # First ring of polygon
    ring = coordinates[0]
    if not ring:
        return None, None

    # Simple centroid: average of all points
    lats = [pt[1] for pt in ring]
    lons = [pt[0] for pt in ring]

    return sum(lats) / len(lats), sum(lons) / len(lons)

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

def process_fires(features, user_lat, user_lon, radius_km):
    """Process fire features, compute centroids and distances."""
    fires = []

    for feature in features:
        try:
            props = feature.get('properties', {})
            geom = feature.get('geometry', {})

            name = props.get('poly_IncidentName', 'Unknown')
            acres = props.get('poly_GISAcres', 0)

            # Parse discovery date to get year
            discovery_str = props.get('attr_FireDiscoveryDateTime', '')
            try:
                if 'T' in discovery_str:
                    year = int(discovery_str.split('-')[0])
                else:
                    year = int(discovery_str[:4])
            except (ValueError, IndexError):
                year = datetime.utcnow().year

            # Get centroid from geometry
            if geom.get('type') == 'Polygon':
                coords = geom.get('coordinates', [])
                cent_lat, cent_lon = centroid_of_polygon(coords)
            else:
                continue

            if cent_lat is None or cent_lon is None:
                continue

            # Get elevation at centroid
            elev_ft = get_elevation(cent_lat, cent_lon)

            # Compute distance
            dist_km = haversine(user_lat, user_lon, cent_lat, cent_lon)

            # Filter by radius
            if dist_km > radius_km:
                continue

            fires.append({
                'name': name,
                'year': year,
                'acres': int(acres),
                'centroid_lat': round(cent_lat, 4),
                'centroid_lon': round(cent_lon, 4),
                'elev_ft': elev_ft,
                'distance_km': round(dist_km, 1),
                'geometry': geom
            })

        except Exception:
            continue

    return fires

def main():
    if len(sys.argv) < 3:
        print(json.dumps({'error': 'usage: fires.py lat lon [radius_km]'}))
        sys.exit(0)

    try:
        user_lat = float(sys.argv[1])
        user_lon = float(sys.argv[2])
        radius_km = float(sys.argv[3]) if len(sys.argv) > 3 else 120
    except (ValueError, IndexError):
        print(json.dumps({'error': 'invalid arguments'}))
        sys.exit(0)

    try:
        wfigs_data = query_wfigs()

        if isinstance(wfigs_data, dict) and 'error' in wfigs_data:
            print(json.dumps({'error': wfigs_data['error'], 'fires': []}))
            sys.exit(0)

        if 'features' not in wfigs_data:
            print(json.dumps({'error': 'no features in WFIGS response', 'fires': []}))
            sys.exit(0)

        fires = process_fires(wfigs_data['features'], user_lat, user_lon, radius_km)

        # Sort by distance
        fires.sort(key=lambda f: f['distance_km'])

        result = {
            'fires': fires,
            'query_lat': user_lat,
            'query_lon': user_lon,
            'radius_km': radius_km,
            'count': len(fires),
            'data_timestamp': datetime.utcnow().isoformat() + 'Z'
        }

        print(json.dumps(result, indent=2))

    except Exception as e:
        print(json.dumps({'error': f'internal error: {str(e)}', 'fires': []}))

    sys.exit(0)

if __name__ == '__main__':
    main()
