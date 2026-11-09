#!/usr/bin/env python3
"""
weather.py - Fetch weather from Open-Meteo, compute derived features.
CLI: python3 weather.py lat lon [month for archive call]
Returns JSON with daily history, forecast, and derived aggregates.
"""

import sys
import json
import urllib.request
import urllib.error
import os
import time
from datetime import datetime, timedelta

CACHE_DIR = os.path.join(os.path.dirname(__file__), '..', 'cache')
WEATHER_CACHE = os.path.join(CACHE_DIR, 'weather_cache.json')

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

def fetch_forecast(lat, lon):
    """Fetch forecast API: 31 days history + 10 days forecast."""
    cache = read_cache(WEATHER_CACHE, 6 * 3600)  # 6-hour TTL
    cache_key = f"forecast_{lat}_{lon}"
    if cache_key in cache:
        return cache[cache_key]

    url = (f"https://api.open-meteo.com/v1/forecast"
           f"?latitude={lat}&longitude={lon}"
           f"&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,rain_sum,snowfall_sum"
           f"&hourly=soil_temperature_6cm,soil_moisture_3_to_9cm,snow_depth"
           f"&past_days=31&forecast_days=10"
           f"&temperature_unit=fahrenheit&precipitation_unit=inch"
           f"&timezone=America%2FLos_Angeles")

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
                return {'error': f'forecast fetch failed: {str(e)}'}

    write_cache(WEATHER_CACHE, cache_key, data)
    return data

def fetch_archive(lat, lon, start_date, end_date):
    """Fetch archive API for historical precip and temps (e.g., Aug 1 to today)."""
    cache = read_cache(WEATHER_CACHE, 6 * 3600)  # 6-hour TTL
    cache_key = f"archive_{lat}_{lon}_{start_date}_{end_date}"
    if cache_key in cache:
        return cache[cache_key]

    url = (f"https://archive-api.open-meteo.com/v1/archive"
           f"?latitude={lat}&longitude={lon}"
           f"&start_date={start_date}&end_date={end_date}"
           f"&daily=precipitation_sum,temperature_2m_min"
           f"&temperature_unit=fahrenheit&precipitation_unit=inch"
           f"&timezone=America%2FLos_Angeles")

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
                return {'error': f'archive fetch failed: {str(e)}'}

    write_cache(WEATHER_CACHE, cache_key, data)
    return data

def aggregate_daily_from_hourly(hourly_times, hourly_soil_temp, hourly_soil_moisture, hourly_snow_depth):
    """Convert hourly soil/snow data to daily means."""
    if not hourly_times or not hourly_soil_temp:
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
            # Store previous day
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

    # Store last day
    if current_date:
        if temps:
            daily_soil_temp[current_date] = sum(temps) / len(temps)
        if moistures:
            daily_soil_moisture[current_date] = sum(moistures) / len(moistures)
        if snow_depths:
            daily_snow_depth[current_date] = sum(snow_depths) / len(snow_depths)

    return daily_soil_temp, daily_soil_moisture, daily_snow_depth

def compute_derived_features(forecast_data, archive_data=None):
    """Compute derived weather features."""
    features = {}

    if 'error' in forecast_data:
        return {'error': forecast_data['error']}

    daily_times = forecast_data.get('daily', {}).get('time', [])
    daily_max = forecast_data.get('daily', {}).get('temperature_2m_max', [])
    daily_min = forecast_data.get('daily', {}).get('temperature_2m_min', [])
    daily_precip = forecast_data.get('daily', {}).get('precipitation_sum', [])
    daily_snow = forecast_data.get('daily', {}).get('snowfall_sum', [])

    hourly_times = forecast_data.get('hourly', {}).get('time', [])
    hourly_soil_temp = forecast_data.get('hourly', {}).get('soil_temperature_6cm', [])
    hourly_soil_moisture = forecast_data.get('hourly', {}).get('soil_moisture_3_to_9cm', [])
    hourly_snow_depth = forecast_data.get('hourly', {}).get('snow_depth', [])

    # Aggregate hourly to daily
    daily_soil_temp, daily_soil_moisture, daily_snow_depth = aggregate_daily_from_hourly(
        hourly_times, hourly_soil_temp, hourly_soil_moisture, hourly_snow_depth
    )

    # Build day-indexed dict
    daily_by_date = {}
    for i, date in enumerate(daily_times):
        daily_by_date[date] = {
            'max_temp': daily_max[i] if i < len(daily_max) else None,
            'min_temp': daily_min[i] if i < len(daily_min) else None,
            'precip': daily_precip[i] if i < len(daily_precip) else None,
            'snow': daily_snow[i] if i < len(daily_snow) else None,
            'soil_temp': daily_soil_temp.get(date),
            'soil_moisture': daily_soil_moisture.get(date),
            'snow_depth': daily_snow_depth.get(date),
        }

    # Today is the last day of the historical data
    today_idx = len(daily_times) - 11  # last of the 31-day history before forecast
    if 0 <= today_idx < len(daily_times):
        today_date = daily_times[today_idx]
        features['soil_t_today'] = daily_soil_temp.get(today_date)
    else:
        features['soil_t_today'] = None

    # 7-day mean soil temp
    soil_temps_7d = []
    for i in range(max(0, today_idx - 6), today_idx + 1):
        if i >= 0 and i < len(daily_times):
            st = daily_soil_temp.get(daily_times[i])
            if st is not None:
                soil_temps_7d.append(st)
    features['soil_t_7d_mean'] = (sum(soil_temps_7d) / len(soil_temps_7d)) if soil_temps_7d else None

    # 7-day mean soil moisture
    soil_moist_7d = []
    for i in range(max(0, today_idx - 6), today_idx + 1):
        if i >= 0 and i < len(daily_times):
            sm = daily_soil_moisture.get(daily_times[i])
            if sm is not None:
                soil_moist_7d.append(sm)
    features['soil_moisture_7d_mean'] = (sum(soil_moist_7d) / len(soil_moist_7d)) if soil_moist_7d else None

    # Precip windows
    precip_7d = sum([daily_by_date.get(daily_times[i], {}).get('precip') or 0
                     for i in range(max(0, today_idx - 6), today_idx + 1)])
    precip_14d = sum([daily_by_date.get(daily_times[i], {}).get('precip') or 0
                      for i in range(max(0, today_idx - 13), today_idx + 1)])
    precip_30d = sum([daily_by_date.get(daily_times[i], {}).get('precip') or 0
                      for i in range(max(0, today_idx - 29), today_idx + 1)])
    features['precip_7d'] = precip_7d
    features['precip_14d'] = precip_14d
    features['precip_30d'] = precip_30d

    # Last rain event detection
    features['last_rain_event'] = None
    for threshold in [0.1, 0.5, 1.0]:
        last_rain = None
        rolling_sum = 0
        for i in range(today_idx, -1, -1):
            precip = daily_by_date.get(daily_times[i], {}).get('precip') or 0
            rolling_sum += precip
            if rolling_sum >= threshold:
                last_rain = daily_times[i]
                break
            if i < today_idx - 0:  # Look back within 1 day for rolling 24h
                rolling_sum = 0
        if last_rain and features['last_rain_event'] is None:
            features['last_rain_event'] = last_rain
            break

    # Frost nights
    frost_3d = sum([1 for i in range(max(0, today_idx - 2), today_idx + 1)
                    if i >= 0 and i < len(daily_times)
                    and (daily_by_date.get(daily_times[i], {}).get('min_temp') or 100) <= 28])
    frost_5d = sum([1 for i in range(max(0, today_idx - 4), today_idx + 1)
                    if i >= 0 and i < len(daily_times)
                    and (daily_by_date.get(daily_times[i], {}).get('min_temp') or 100) <= 28])
    features['frost_nights_last3'] = frost_3d
    features['frost_nights_last5'] = frost_5d
    features['frost_nights_last14'] = sum([1 for i in range(max(0, today_idx - 13), today_idx + 1)
                                           if i >= 0 and i < len(daily_times)
                                           and (daily_by_date.get(daily_times[i], {}).get('min_temp') or 100) <= 28])

    # Snow-free detection
    features['snow_free'] = daily_snow_depth.get(daily_times[today_idx], 0) == 0 if today_idx >= 0 else False
    features['snow_free_date'] = None
    for i in range(len(daily_times) - 1, -1, -1):
        if daily_snow_depth.get(daily_times[i], 0) == 0:
            features['snow_free_date'] = daily_times[i]
            break

    # Forecast summary (next 10 days)
    forecast_precip_10d = sum([daily_by_date.get(daily_times[i], {}).get('precip') or 0
                               for i in range(today_idx + 1, min(today_idx + 11, len(daily_times)))])
    forecast_temps = [daily_by_date.get(daily_times[i], {}).get('max_temp')
                      for i in range(today_idx + 1, min(today_idx + 11, len(daily_times)))]
    forecast_temps = [t for t in forecast_temps if t is not None]

    features['forecast_precip_10d'] = forecast_precip_10d
    features['forecast_temp_max_10d'] = max(forecast_temps) if forecast_temps else None
    features['forecast_temp_min_10d'] = min(forecast_temps) if forecast_temps else None

    # Air temp 7-day mean
    air_temps_7d = []
    for i in range(max(0, today_idx - 6), today_idx + 1):
        if i >= 0 and i < len(daily_times):
            max_t = daily_by_date.get(daily_times[i], {}).get('max_temp')
            if max_t is not None:
                air_temps_7d.append(max_t)
    features['air_temp_7d_mean_max'] = (sum(air_temps_7d) / len(air_temps_7d)) if air_temps_7d else None

    features['data_timestamp'] = datetime.utcnow().isoformat() + 'Z'

    return features

def main():
    if len(sys.argv) < 3:
        print(json.dumps({'error': 'usage: weather.py lat lon [month]'}))
        sys.exit(1)

    try:
        lat = float(sys.argv[1])
        lon = float(sys.argv[2])
        month = int(sys.argv[3]) if len(sys.argv) > 3 else None
    except (ValueError, IndexError):
        print(json.dumps({'error': 'invalid lat/lon/month'}))
        sys.exit(1)

    # Fetch forecast data
    forecast = fetch_forecast(lat, lon)
    if 'error' in forecast:
        print(json.dumps(forecast))
        sys.exit(0)

    features = compute_derived_features(forecast)

    # For Aug-Dec, also fetch archive for season opener detection
    if month and month >= 8:
        today = datetime.utcnow().strftime('%Y-%m-%d')
        aug_1 = f"{datetime.utcnow().year}-08-01"
        archive = fetch_archive(lat, lon, aug_1, today)
        # Store archive data alongside features for season_opener logic
        if 'error' not in archive:
            features['archive_data'] = archive

    print(json.dumps(features, indent=2))
    sys.exit(0)

if __name__ == '__main__':
    main()
