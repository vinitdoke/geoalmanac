import glob
import json
import os
from pathlib import Path
import urllib.parse

import gpxpy

import math
from PIL import Image, ImageOps
from PIL.ExifTags import TAGS, GPSTAGS
import pillow_heif

# Try importing local module
try:
    import process_ski_data
except ImportError:
    # If running from different context, try relative
    try:
        from . import process_ski_data
    except ImportError:
        # Fallback for direct script execution in some envs
        import sys
        sys.path.append(str(Path(__file__).parent))
        import process_ski_data

pillow_heif.register_heif_opener()

def get_exif_data(image):
    """Returns a dictionary from the exif data of an PIL Image item. Also converts the GPS Tags"""
    exif_data = {}
    try:
        # Use getexif() which is more standard and supports HEIC/DNG
        exif = image.getexif()
        if exif:
            for tag, value in exif.items():
                decoded = TAGS.get(tag, tag)
                exif_data[decoded] = value

            # Extract GPS Info from the GPS IFD (tag 0x8825 / 34853)
            gps_info = exif.get_ifd(0x8825)
            if gps_info:
                gps_data = {}
                for t, value in gps_info.items():
                    sub_decoded = GPSTAGS.get(t, t)
                    gps_data[sub_decoded] = value
                
                exif_data["GPSInfo"] = gps_data
    except Exception as e:
        print(f"Error extracting EXIF: {e}")
    
    # Fallback to _getexif for JPEGs if getexif missed something (rare but possible) or for old Pillow/JPEG handling
    if not exif_data and hasattr(image, "_getexif"):
        try:
            info = image._getexif()
            if info:
                for tag, value in info.items():
                    decoded = TAGS.get(tag, tag)
                    if decoded == "GPSInfo":
                        gps_data = {}
                        for t in value:
                            sub_decoded = GPSTAGS.get(t, t)
                            gps_data[sub_decoded] = value[t]
                        exif_data[decoded] = gps_data
                    else:
                        exif_data[decoded] = value
        except Exception:
            pass

    return exif_data

def get_lat_lon(exif_data):
    """Returns the latitude and longitude, if available, from the provided exif_data"""
    lat = None
    lon = None

    if "GPSInfo" in exif_data:
        gps_info = exif_data["GPSInfo"]

        gps_latitude = gps_info.get("GPSLatitude")
        gps_latitude_ref = gps_info.get("GPSLatitudeRef")
        gps_longitude = gps_info.get("GPSLongitude")
        gps_longitude_ref = gps_info.get("GPSLongitudeRef")

        if gps_latitude and gps_latitude_ref and gps_longitude and gps_longitude_ref:
            lat = convert_to_degrees(gps_latitude)
            if gps_latitude_ref != "N":
                lat = 0 - lat

            lon = convert_to_degrees(gps_longitude)
            if gps_longitude_ref != "E":
                lon = 0 - lon

    return lat, lon

def convert_to_degrees(value):
    """Helper function to convert the GPS coordinates stored in the EXIF to degrees in float format"""
    d = float(value[0])
    m = float(value[1])
    s = float(value[2])
    return d + (m / 60.0) + (s / 3600.0)

def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371000  # radius of Earth in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    
    a = math.sin(delta_phi / 2)**2 + \
        math.cos(phi1) * math.cos(phi2) * \
        math.sin(delta_lambda / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c

def process_gpx_files(trails_dir: Path, output_file: Path, ski_dir: Path = None):
    hikes = []
    
    # Ensure output directory exists
    output_file.parent.mkdir(parents=True, exist_ok=True)

    gpx_files = sorted(glob.glob(str(trails_dir / "*.gpx")))
    
    print(f"Found {len(gpx_files)} GPX files in {trails_dir}")

    # Process all Hiking GPX
    for file_path in gpx_files:
        try:
            with open(file_path, 'r') as gpx_file:
                gpx = gpxpy.parse(gpx_file)
                
                # Iterate tracks
                for track in gpx.tracks:
                    points = []
                    # Merge all segments in the track
                    for segment in track.segments:
                        for point in segment.points:
                            points.append([point.latitude, point.longitude, point.elevation])
                    
                    if not points:
                        continue

                    # Basic stats (calculated from the whole track)
                    moving_data = track.get_moving_data()
                    
                    stem = urllib.parse.unquote(Path(file_path).stem)
                    track_name = urllib.parse.unquote(track.name) if track.name else None
                    name_to_use = track_name or stem
                    if track_name and len(stem) > len(track_name):
                        # If track name is a substring of the filename, or very generic, prefer the filename
                        if track_name.lower() in stem.lower().replace(" ", "") or track_name in ["Mount", "Activity", "Hike", "Track"]:
                            name_to_use = stem
                    
                    # Restore colons if we fell back to track_name because it matches but has colon
                    if track_name and len(stem) == len(track_name) and stem.replace("_", ":") == track_name:
                        name_to_use = track_name
                         
                    name_to_use = urllib.parse.unquote(name_to_use)

                    hike_data = {
                        "name": name_to_use,
                        "points": points,
                        "length_2d": track.length_2d(),
                        "duration": track.get_duration(),
                        "uphill": track.get_uphill_downhill().uphill,
                        "downhill": track.get_uphill_downhill().downhill,
                        "moving_time": moving_data.moving_time,
                        "stopped_time": moving_data.stopped_time,
                        "max_speed": moving_data.max_speed,
                        "photos": [] # Initialize photo list
                    }
                    
                    
                    # Add date if available (from first point of first segment)
                    date_found = None
                    if track.segments and track.segments[0].points and track.segments[0].points[0].time:
                        date_found = track.segments[0].points[0].time
                    
                    
                    # If date is missing or is 1970 (invalid/default), look elsewhere
                    if not date_found or date_found.year <= 1970:
                        # Try GPX metadata
                        if gpx.time and gpx.time.year > 1970:
                            date_found = gpx.time
                        # Try Waypoints
                        elif gpx.waypoints:
                            # Use earliest waypoint time
                            valid_wpts = [w.time for w in gpx.waypoints if w.time and w.time.year > 1970]
                            if valid_wpts:
                                date_found = min(valid_wpts)
                    
                    # Last resort: Regex search in raw file content if gpxpy failed to parse weird timestamps
                    if not date_found or date_found.year <= 1970:
                        import re
                        # Read file raw content
                        try:
                            with open(file_path, 'r') as f:
                                raw_content = f.read()
                                # Look for 202x- timestamps
                                matches = re.findall(r'<time>(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}.*?)</time>', raw_content)
                                for m in matches:
                                    if m.startswith("20") and not m.startswith("1970"): # Simple check for 21st century
                                        # Manually parse or just take the string if we just need date
                                        # But we need a datetime object or iso format for consistency.
                                        # Attempt to parse strictly or loosely
                                        try:
                                            # Clean up the weird suffix if present (e.g. Z.319Z -> .319Z)
                                            # The generic dateutil parser is good for this.
                                            # Or just simple string slicing if we trust the beginning.
                                            from dateutil import parser
                                            # Pre-cleaning: Remove 'Z' if it appears before fractional seconds or duplicates?
                                            # '2025-12-12T13:31:51Z.319Z'
                                            # If we just need the Date, slicing is enough.
                                            dt = parser.parse(m, fuzzy=True)
                                            if dt.year > 1970:
                                                date_found = dt
                                                break
                                        except:
                                            continue
                        except Exception as e:
                            pass

                    if date_found:
                         hike_data["date"] = date_found.isoformat()
                    
                    hikes.append(hike_data)
                    print(f"Processed Hike: {hike_data['name']}")
                        
        except Exception as e:
            print(f"Error processing {file_path}: {e}")

    # Process Skiing Data
    if ski_dir and ski_dir.exists():
        kmz_files = sorted(glob.glob(str(ski_dir / "*.kmz")))
        print(f"Found {len(kmz_files)} KMZ files in {ski_dir}")
        
        ski_trips = []
        for kmz_path in kmz_files:
            try:
                # Look for parallel GPX file with same name
                gpx_path = Path(kmz_path).with_suffix(".gpx")
                gpx_arg = None
                if gpx_path.exists():
                     gpx_arg = str(gpx_path)
                else: 
                     # Try searching for "raw gps" variant if exact match fails? 
                     # Or assuming user renames?
                     # Workflow says: Move both files. Usually filenames might differ slightly 
                     # e.g. "Trip.kmz" and "Trip - raw gps.gpx"
                     # Let's try a glob match if exact match fails
                     stem = Path(kmz_path).stem
                     candidates = list(ski_dir.glob(f"{stem}*.gpx"))
                     if candidates:
                         gpx_arg = str(candidates[0])
                
                # Process
                ski_data = process_ski_data.parse_kmz(kmz_path, gpx_arg)
                ski_trips.append(ski_data)
                
            except Exception as e:
                 print(f"Error processing ski file {kmz_path}: {e}")

        # Group ski trips by mountain name
        trips_by_name = {}
        for trip in ski_trips:
            trips_by_name.setdefault(trip["name"], []).append(trip)
            
        # Append ' Day X' to names and add to hikes
        for name, trips in trips_by_name.items():
            if len(trips) > 1:
                # Sort chronologically by date
                trips.sort(key=lambda x: x.get("date", ""))
                for i, trip in enumerate(trips, 1):
                    trip["name"] = f"{name} Day {i}"
            
            for trip in trips:
                hikes.append(trip)
                print(f"Processed Ski Trip: {trip['name']}")

    # Process Photos & Write Output (Existing Logic)
    # ... (Need to ensure photos directory is correct, maybe use trails/photos for now or add ski_dir/photos?)
    
    # Process Photos (Trails)
    photos_dir = trails_dir / "photos"
    process_photos(hikes, photos_dir, output_file)

    # Process Photos (Skiing - Optional)
    if ski_dir:
        process_photos(hikes, ski_dir / "photos", output_file)

    with open(output_file, 'w') as f:
        json.dump(hikes, f, indent=2)
    
    print(f"Successfully wrote {len(hikes)} hikes to {output_file}")


def process_photos(hikes, photos_dir, output_file):
    if not photos_dir.exists():
        return

    extensions = ["*.jpg", "*.jpeg", "*.png", "*.heic", "*.dng"]
    extensions += [ext.upper() for ext in extensions]
    
    photo_files = []
    for ext in extensions:
        photo_files.extend(photos_dir.glob(ext))
    
    photo_files = sorted(photo_files)
    print(f"Found {len(photo_files)} photos in {photos_dir}")
    
    dest_dir_root = output_file.parent.parent / "photos"
    dest_dir_root.mkdir(parents=True, exist_ok=True)

    for photo_path in photo_files:
        try:
            image = Image.open(photo_path)
            exif_data = get_exif_data(image)
            lat, lon = get_lat_lon(exif_data)
            
            if lat and lon:
                # Find closest hike
                min_dist = float('inf')
                closest_hike = None
                
                for hike in hikes:
                    # Optimize check: Every 10th point
                    points = hike.get("points", [])
                    if not points: continue
                    
                    for point in points[::10]:
                        dist = haversine_distance(lat, lon, point[0], point[1])
                        if dist < min_dist:
                            min_dist = dist
                            closest_hike = hike
                
                if closest_hike and min_dist < 2000:
                    # Save optimized photo
                    dest_path = dest_dir_root / photo_path.with_suffix(".jpg").name
                    
                    # Check if already exists to avoid re-compressing? (Optional optimizing)
                    if not dest_path.exists():
                        try:
                            image = ImageOps.exif_transpose(image)
                            image.info.clear()
                            image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
                            image.save(dest_path, "JPEG", quality=85, optimize=True)
                            print(f"Compressed {dest_path.name}")
                        except Exception as e:
                            print(f"Error compressing {photo_path.name}: {e}")
                            continue
                    
                    photo_url = f"photos/{dest_path.name}"
                    
                    # Avoid duplicates if running multiple times? (List is rebuilt each time though)
                    closest_hike["photos"].append({
                        "url": photo_url,
                        "lat": lat,
                        "lon": lon
                    })
                    
                    print(f"Matched {photo_path.name} to {closest_hike['name']} ({int(min_dist)}m)")
            else:
                pass 
                
        except Exception as e:
            print(f"Error processing photo {photo_path}: {e}")

    # Set Thumbnails
    for hike in hikes:
        if hike["photos"]:
            hike["thumbnail"] = hike["photos"][0]["url"] 

if __name__ == "__main__":
    base_dir = Path(__file__).parent.parent.parent
    trails_dir = base_dir / "trails"
    ski_dir = base_dir / "ski_tracks"
    output_file = base_dir / "src" / "web" / "data" / "hikes.json"
    
    process_gpx_files(trails_dir, output_file, ski_dir)
