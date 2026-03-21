import os
import math
import json
from xml.etree import ElementTree as ET
from flask import Flask, render_template, request, jsonify
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload

ALLOWED_EXTENSIONS = {'gpx'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def haversine(lat1, lon1, lat2, lon2):
    """Calculate distance in meters between two lat/lon points."""
    R = 6371000  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def parse_gpx(file_stream):
    """Parse GPX file and return track points."""
    tree = ET.parse(file_stream)
    root = tree.getroot()

    # Handle namespace
    ns = ''
    if root.tag.startswith('{'):
        ns = root.tag.split('}')[0] + '}'

    points = []
    for trkpt in root.iter(f'{ns}trkpt'):
        lat = float(trkpt.attrib['lat'])
        lon = float(trkpt.attrib['lon'])
        ele_el = trkpt.find(f'{ns}ele')
        ele = float(ele_el.text) if ele_el is not None else 0.0
        time_el = trkpt.find(f'{ns}time')
        time_str = time_el.text if time_el is not None else None
        points.append({'lat': lat, 'lon': lon, 'ele': ele, 'time': time_str})

    return points


def analyze_track(points):
    """Compute stats and elevation profile from track points."""
    if len(points) < 2:
        return None

    total_distance = 0.0
    elevation_gain = 0.0
    elevation_loss = 0.0
    cumulative_distances = [0.0]

    for i in range(1, len(points)):
        p1, p2 = points[i - 1], points[i]
        seg_dist = haversine(p1['lat'], p1['lon'], p2['lat'], p2['lon'])
        total_distance += seg_dist
        cumulative_distances.append(total_distance)

        ele_diff = p2['ele'] - p1['ele']
        if ele_diff > 0:
            elevation_gain += ele_diff
        else:
            elevation_loss += abs(ele_diff)

    # Average speed (requires time data)
    avg_speed_kmh = None
    if points[0]['time'] and points[-1]['time']:
        from datetime import datetime
        fmt = '%Y-%m-%dT%H:%M:%SZ'
        try:
            t_start = datetime.strptime(points[0]['time'].rstrip('Z').split('.')[0], '%Y-%m-%dT%H:%M:%S')
            t_end = datetime.strptime(points[-1]['time'].rstrip('Z').split('.')[0], '%Y-%m-%dT%H:%M:%S')
            duration_h = (t_end - t_start).total_seconds() / 3600
            if duration_h > 0:
                avg_speed_kmh = (total_distance / 1000) / duration_h
        except ValueError:
            pass

    # Build elevation profile (downsample to at most 500 points for chart)
    n = len(points)
    step = max(1, n // 500)
    profile = [
        {'d': round(cumulative_distances[i] / 1000, 3), 'e': round(points[i]['ele'], 1)}
        for i in range(0, n, step)
    ]
    # Always include last point
    if (n - 1) % step != 0:
        profile.append({'d': round(cumulative_distances[-1] / 1000, 3), 'e': round(points[-1]['ele'], 1)})

    return {
        'distance_km': round(total_distance / 1000, 2),
        'elevation_gain_m': round(elevation_gain, 1),
        'elevation_loss_m': round(elevation_loss, 1),
        'avg_speed_kmh': round(avg_speed_kmh, 2) if avg_speed_kmh is not None else None,
        'profile': profile,
        'point_count': n,
    }


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/analyze', methods=['POST'])
def analyze():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    if not allowed_file(file.filename):
        return jsonify({'error': 'Only .gpx files are supported'}), 400

    try:
        points = parse_gpx(file.stream)
    except ET.ParseError as e:
        return jsonify({'error': f'Invalid GPX file: {e}'}), 400

    if not points:
        return jsonify({'error': 'No track points found in GPX file'}), 400

    stats = analyze_track(points)
    if stats is None:
        return jsonify({'error': 'Track must have at least 2 points'}), 400

    return jsonify(stats)


if __name__ == '__main__':
    app.run(debug=True)
