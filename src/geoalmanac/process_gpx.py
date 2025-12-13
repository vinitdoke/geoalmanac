import glob
import json
import os
from pathlib import Path

import gpxpy

import math
from PIL import Image, ImageOps
from PIL.ExifTags import TAGS, GPSTAGS
import pillow_heif

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

def process_gpx_files(trails_dir: Path, output_file: Path):
    hikes = []
    
    # Ensure output directory exists
    output_file.parent.mkdir(parents=True, exist_ok=True)

    gpx_files = sorted(glob.glob(str(trails_dir / "*.gpx")))
    
    print(f"Found {len(gpx_files)} GPX files in {trails_dir}")

    # Process all Hikes first
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
                    
                    hike_data = {
                        "name": track.name or Path(file_path).stem,
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
                    print(f"Processed: {hike_data['name']}")
                        
        except Exception as e:
            print(f"Error processing {file_path}: {e}")

    # Process Photos
    photos_dir = trails_dir / "photos"
    if photos_dir.exists():
        extensions = ["*.jpg", "*.jpeg", "*.png", "*.heic", "*.dng"]
        # Add uppercase variants just in case
        extensions += [ext.upper() for ext in extensions]
        
        photo_files = []
        for ext in extensions:
            photo_files.extend(photos_dir.glob(ext))
        
        photo_files = sorted(photo_files)
        print(f"Found {len(photo_files)} photos in {photos_dir}")
        
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
                        # Optimization: Check bounding box or center first? 
                        # For now, simplistic approach: check some points or all points?
                        # Checking ALL points is expensive O(N*M).
                        # Let's check distance to every 10th point to speed up
                        for point in hike["points"][::10]:
                            dist = haversine_distance(lat, lon, point[0], point[1])
                            if dist < min_dist:
                                min_dist = dist
                                closest_hike = hike
                    
                    # If reasonably close (e.g. within 500m? or just closest?)
                    # Let's say 2km matching radius to be safe against GPS drift/offsets
                    if closest_hike and min_dist < 2000:
                         # Copy photo to web accessible dir? 
                         # Or just reference relative path if web server serves root.
                         # Since simple http server is at root, we can link effectively.
                         # Need to make sure photo path is relative to index.html (in src/web)
                         # Actually, src/web is served. trails/ is outside src/web.
                         # We should copy/symlink photos or output hikes.json with corrected paths?
                         # BEST APPROACH: Symlink 'trails/photos' to 'src/web/data/photos' or just configure server?
                         # Server is running in root, serve dir is src/web.
                         # So 'trails' folder is NOT accessible via http://localhost:8000/trails
                         # We must move/copy photos to src/web/photos for them to be visible.
                         
                        dest_dir = output_file.parent.parent / "photos"
                        dest_dir.mkdir(parents=True, exist_ok=True)
                         
                        # Ensure extension is .jpg
                        dest_path = dest_dir / photo_path.with_suffix(".jpg").name
                         
                        # Optimize Image
                        try:
                            # Auto-rotate based on EXIF
                            image = ImageOps.exif_transpose(image)
                            
                            # Strip metadata: Create a new image data container to be safe, 
                            # or simply clearing info handles most cases in Pillow.
                            # exif_transpose returns a copy, we can just clear .info
                            image.info.clear()
                            
                            # Resize to max 1024px
                            image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
                            
                            # Save optimized (default save behavior for JPEG drops EXIF unless explicit, but clearing info confirms it)
                            image.save(dest_path, "JPEG", quality=85, optimize=True)
                            print(f"Compressed and saved {dest_path.name}")
                        except Exception as e:
                            print(f"Error compressing {photo_path.name}, skipping: {e}")
                            continue
                        
                        photo_url = f"photos/{dest_path.name}"
                        
                        closest_hike["photos"].append({
                            "url": photo_url,
                            "lat": lat,
                            "lon": lon
                        })
                        
                        print(f"Matched {photo_path.name} to {closest_hike['name']} ({int(min_dist)}m)")
                else:
                    print(f"No GPS in {photo_path.name}")
                    
            except Exception as e:
                print(f"Error processing photo {photo_path}: {e}")

    # Set Thumbnails
    for hike in hikes:
        if hike["photos"]:
            hike["thumbnail"] = hike["photos"][0]["url"] 

    with open(output_file, 'w') as f:
        json.dump(hikes, f, indent=2)
    
    print(f"Successfully wrote {len(hikes)} hikes to {output_file}")

if __name__ == "__main__":
    base_dir = Path(__file__).parent.parent.parent
    trails_dir = base_dir / "trails"
    output_file = base_dir / "src" / "web" / "data" / "hikes.json"
    
    process_gpx_files(trails_dir, output_file)
