
import zipfile
import xml.etree.ElementTree as ET
import json
import sys
from pathlib import Path
from datetime import datetime
import math

# Namespace constants
NS = {'kml': 'http://www.opengis.net/kml/2.2', 'gx': 'http://www.google.com/kml/ext/2.2', 'gpx': 'http://www.topografix.com/GPX/1/1'}

def parse_gpx_elevation(gpx_path):
    print(f"Loading elevation from {gpx_path}...")
    tree = ET.parse(gpx_path)
    root = tree.getroot()
    
    # Handle GPX namespace if present (it usually is)
    # But often ElementTree doesn't need it if we use local name or handle it generally
    # Let's try to be robust. 
    # GPX 1.1: http://www.topografix.com/GPX/1/1
    
    ele_map = {}
    
    # Find all trkpt
    # Use generic xpath with local-name checking or just the namespace
    # Let's assume standard GPX 1.1
    
    for trkpt in root.findall('.//{http://www.topografix.com/GPX/1/1}trkpt'):
        ele_tag = trkpt.find('{http://www.topografix.com/GPX/1/1}ele')
        time_tag = trkpt.find('{http://www.topografix.com/GPX/1/1}time')
        
        if ele_tag is not None and time_tag is not None:
            try:
                # Parse time
                # Format: 2026-01-24T12:52:35+09:00
                dt = datetime.fromisoformat(time_tag.text)
                ele = float(ele_tag.text)
                ele_map[dt] = ele
            except Exception:
                continue
                
    print(f"Loaded {len(ele_map)} elevation points.")
    return ele_map

def find_nearest_elevation(target_dt, ele_map):
    # Exact match first
    if target_dt in ele_map:
        return ele_map[target_dt]
    
    # Simple nearest neighbor? Or just return 0 if not found?
    # Given the frequency of GPS, nearest is probably safest if exact match fails due to ms differences
    # converting to list for checking is slow.
    # checking +/- 1 second
    # For now, let's assume exact match usually works if data is from same source
    # If not, let's just return 0 to keep it simple, or implement a proper KDTree if efficiency needed (overkill here)
    return 0.0

def parse_kmz(kmz_path, gpx_path=None):
    print(f"Processing {kmz_path}...")
    
    ele_map = {}
    if gpx_path:
        ele_map = parse_gpx_elevation(gpx_path)
    
    with zipfile.ZipFile(kmz_path, 'r') as z:
        kml_filename = [n for n in z.namelist() if n.endswith('.kml')][0]
        with z.open(kml_filename) as f:
            tree = ET.parse(f)
            
    root = tree.getroot()
    
    placemarks = root.findall('.//kml:Placemark', NS)
    if not placemarks:
        print("No placemarks found with namespace, trying without...")
        placemarks = root.findall('.//Placemark')
        
    segments = []
    all_points = []
    
    hike_name = Path(kmz_path).stem.split(' - ')[0] 
    doc_name = root.find('.//kml:Document/kml:name', NS)
    if doc_name is not None:
        hike_name = doc_name.text

    for pm in placemarks:
        style = pm.find('kml:styleUrl', NS)
        if style is None: style = pm.find('styleUrl')
        style_id = style.text if style is not None else ""
        
        seg_type = "unknown"
        if "#RunLine" in style_id:
            seg_type = "run"
        elif "#LiftLine" in style_id:
            seg_type = "lift"
            
        track = pm.find('.//gx:Track', NS)
        if track is not None:
            coords = track.findall('gx:coord', NS)
            whens = track.findall('kml:when', NS)
            
            # They should be parallel
            segment_points = []
            
            count = min(len(coords), len(whens))
            
            for i in range(count):
                coord_text = coords[i].text
                time_text = whens[i].text
                
                parts = coord_text.split()
                if len(parts) >= 2:
                    lon, lat = float(parts[0]), float(parts[1])
                    
                    # Try to get elevation
                    ele = 0.0
                    if len(parts) >= 3:
                        ele = float(parts[2])
                    
                    # If ele is 0 (missing) and we have GXP data, try look up
                    if ele == 0.0 and ele_map:
                        try:
                            # Parse time: 2026-01-24T15:26:56+09:00
                            dt = datetime.fromisoformat(time_text)
                            
                            # Lookup
                            if dt in ele_map:
                                ele = ele_map[dt]
                            else:
                                # Find nearest?
                                # Let's try exact first. If fails, maybe a tolerance loop?
                                pass
                                
                        except Exception:
                            pass
                            
                    segment_points.append([lat, lon, ele])
                    all_points.append([lat, lon, ele])
                
            if segment_points:
                segments.append({
                    "type": seg_type,
                    "points": segment_points
                })
                
    # Calculate Stats
    total_dist = 0
    total_uphill = 0
    
    def distance(p1, p2): 
        R = 6371e3
        phi1 = p1[0] * math.pi/180
        phi2 = p2[0] * math.pi/180
        dphi = (p2[0]-p1[0]) * math.pi/180
        dlam = (p2[1]-p1[1]) * math.pi/180
        a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2) * math.sin(dlam/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        return R * c

    for i in range(len(all_points)-1):
        d = distance(all_points[i], all_points[i+1])
        total_dist += d
        ele_diff = all_points[i+1][2] - all_points[i][2]
        if ele_diff > 0:
            total_uphill += ele_diff

    # Date from filename or first point
    # Filename format: "January 24, 2026 - ..."
    date_str = "2026-01-01" # Default
    default_name = hike_name # Fallback
    
    try:
        # "January 24, 2026 - Yuzawa Nakazato..."
        parts = Path(kmz_path).stem.split(' - ')
        
        # Try parse date
        if len(parts) >= 1:
            date_part = parts[0]
            try:
                dt = datetime.strptime(date_part, "%B %d, %Y")
                date_str = dt.strftime("%Y-%m-%d")
            except ValueError:
                # Try 24-hr format or other locale?
                # "February 1, 2026"
                pass
                
        # Improve default name if parts[1] exists
        if len(parts) >= 2:
            default_name = parts[1]
            
    except Exception as e:
        print(f"Could not parse filename metadata: {e}")

    # Use KML name if valid, else default
    if doc_name is not None and doc_name.text and doc_name.text.strip():
        hike_name = doc_name.text.strip()
    else:
        hike_name = default_name

    
    # Calculate Duration
    total_duration = 0
    all_timestamps = []
    
    # helper to parse kml timestamps like 2026-01-31T15:47:17+09:00
    def parse_ts(t):
        try:
            return datetime.fromisoformat(t)
        except:
             return None

    # Collect timestamps from segments
    # Note: segments points is just [lat, lon, ele] so we lost timestamps there
    # But we iterate 'placemarks' earlier.
    # To fix this cleanly without re-iterating, let's just re-iterate placemarks or 
    # extract timestamps during invalidation above.
    
    # Actually, we didn't store timestamps in "all_points".
    # Let's verify if we need to store them or just min/max.
    # We need total duration = end - start of the whole day? Or moving time?
    # Slopes exports might have gaps.
    # "Total Time" usually implies (Last Point Time - First Point Time).
    # "Moving Time" is harder. 
    # Let's go with Total Duration for now (Max - Min).
    
    min_time = None
    max_time = None
    
    for pm in placemarks:
        track = pm.find('.//gx:Track', NS)
        if track is not None:
             whens = track.findall('kml:when', NS)
             for w in whens:
                 dt = parse_ts(w.text)
                 if dt:
                     if min_time is None or dt < min_time: min_time = dt
                     if max_time is None or dt > max_time: max_time = dt
                     
    if min_time and max_time:
        total_duration = (max_time - min_time).total_seconds()

    result = {
        "name": hike_name,
        "date": date_str,
        "length_2d": round(total_dist, 2),
        "uphill": round(total_uphill, 2),
        "duration": total_duration, 
        "points": all_points,
        "segments": segments,
        "photos": [] 
    }
    
    return result

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python process_ski_data.py <path_to_kmz> [path_to_gpx]")
        sys.exit(1)
        
    kmz_path = sys.argv[1]
    gpx_path = sys.argv[2] if len(sys.argv) > 2 else None
        
    data = parse_kmz(kmz_path, gpx_path)
    
    with open("ski_data_output.json", "w") as f:
        json.dump(data, f, indent=2)
    
    print("Saved to ski_data_output.json")
