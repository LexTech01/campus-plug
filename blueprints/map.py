from flask import Blueprint, render_template, request, jsonify
import requests
from models import db, User

map_bp = Blueprint('map', __name__, url_prefix='/map')


@map_bp.route('')
def sellers_map():
    q = request.args.get('q', '').strip()

    query = User.query.filter(
        User.account_type.in_(['seller', 'admin']),
        User.is_suspended == False,
        User.latitude != None,
        User.longitude != None
    )

    if q:
        query = query.filter(User.full_name.ilike(f'%{q}%'))

    sellers = query.all()

    features = []
    for s in sellers:
        features.append({
            'id': s.id,
            'name': s.full_name,
            'university': s.university,
            'avatar': s.avatar or '/static/images/default-avatar.png',
            'lat': s.latitude,
            'lng': s.longitude,
            'location_name': s.location_name or '',
        })

    return render_template('map.html', sellers=features)


@map_bp.route('/geocode')
def geocode():
    q = request.args.get('q', '').strip()
    limit = request.args.get('limit', 8, type=int)
    if not q:
        return jsonify({'error': 'Missing query'}), 400

    try:
        resp = requests.get(
            'https://nominatim.openstreetmap.org/search',
            params={'format': 'json', 'limit': limit, 'q': q},
            headers={'User-Agent': 'CampusPlug/1.0 (Ghana)'},
            timeout=10
        )
        data = resp.json()
        if data:
            results = []
            for r in data:
                results.append({
                    'lat': r['lat'],
                    'lon': r['lon'],
                    'display_name': r['display_name']
                })
            return jsonify({'results': results})
        return jsonify({'results': []})
    except Exception as e:
        return jsonify({'error': 'Geocoding service temporarily unavailable.'}), 500


@map_bp.route('/reverse')
def reverse_geocode():
    lat = request.args.get('lat', '').strip()
    lon = request.args.get('lon', '').strip()
    if not lat or not lon:
        return jsonify({'error': 'Missing lat/lon'}), 400

    try:
        resp = requests.get(
            'https://nominatim.openstreetmap.org/reverse',
            params={'format': 'json', 'lat': lat, 'lon': lon, 'zoom': 18},
            headers={'User-Agent': 'CampusPlug/1.0 (Ghana)'},
            timeout=10
        )
        data = resp.json()
        if data and 'display_name' in data:
            return jsonify({
                'lat': data.get('lat', lat),
                'lon': data.get('lon', lon),
                'display_name': data['display_name']
            })
        return jsonify({'error': 'Location not found'}), 404
    except Exception as e:
        return jsonify({'error': 'Reverse geocoding service temporarily unavailable.'}), 500
