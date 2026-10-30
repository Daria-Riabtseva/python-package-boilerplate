"""Extract city layers and an OSMnx-compatible drive network from a regional PBF.

Uses original OSM node IDs for connectivity (no geometric junction guessing).
Area assembly, including multipolygon relations, is handled by libosmium.
"""
import json
import re
from collections import Counter
from pathlib import Path

import geopandas as gpd
import osmium
import osmnx as ox
import shapely
from shapely.geometry import Point, LineString


def matches(tags, query):
    for key, value in query.items():
        if key not in tags:
            continue
        if value is True or isinstance(value, list) and tags[key] in value or tags[key] == value:
            return True
    return False


def drive_matcher():
    # Mirror the exact tag predicates of the pinned OSMnx drive preset.
    predicates = re.findall(r'\["([^"]+)"(?:(=|!=|~|!~)"([^"]*)")?\]',
                            ox._overpass._get_network_filter('drive'))
    def accepted(tags):
        for key, op, value in predicates:
            found = tags.get(key, '')
            if not op and key not in tags:
                return False
            if op == '=' and found != value or op == '!=' and found == value:
                return False
            if op == '~' and not re.search(value, found) or op == '!~' and re.search(value, found):
                return False
        return True
    return accepted


def extract_city(pbf, boundary, queries):
    area = boundary.to_crs(4326).union_all()
    metric = boundary.to_crs(boundary.estimate_utm_crs())
    context = gpd.GeoSeries([metric.union_all().convex_hull.buffer(1000)], crs=metric.crs).to_crs(4326).iloc[0]
    factory = osmium.geom.WKBFactory()
    accepts_drive = drive_matcher()

    class CityHandler(osmium.SimpleHandler):
        def __init__(self):
            super().__init__()
            self.rows = {name: [] for name in queries}
            self.graph_nodes = {}
            self.graph_ways = []
            self.errors = Counter()

        def add(self, tags, geom, uid, oid, kind, names):
            if not geom.is_empty and geom.intersects(area):
                row = dict(tags, geometry=geom, osm_uid=uid, osm_id=str(oid), osm_type=kind)
                for name in names:
                    self.rows[name].append(row.copy())

        def node(self, node):
            if not node.tags:
                return
            tags = dict(node.tags)
            names = [name for name, query in queries.items() if matches(tags, query)]
            if names and node.location.valid():
                self.add(tags, Point(node.lon, node.lat), f'node/{node.id}', node.id, 'node', names)

        def way(self, way):
            tags = dict(way.tags)
            names = [name for name, query in queries.items() if matches(tags, query)]
            driving = accepts_drive(tags)
            if not names and not driving:
                return
            try:
                coords = [(n.lon, n.lat) for n in way.nodes]
                if len(coords) < 2 or len(set(coords)) < 2:
                    self.errors['degenerate_way'] += 1
                    return
                geom = LineString(coords)
            except (osmium.InvalidLocationError, RuntimeError):
                self.errors['missing_way_locations'] += 1
                return
            if driving and geom.intersects(context):
                self.graph_ways.append({'type': 'way', 'id': way.id,
                                       'nodes': [n.ref for n in way.nodes], 'tags': tags})
                for n in way.nodes:
                    self.graph_nodes[n.ref] = {'type': 'node', 'id': n.ref, 'lat': n.lat, 'lon': n.lon}
            if way.is_closed():
                # Polygon layers are supplied by the area callback, once per OSM feature.
                names = [name for name in names if name in ('roads', 'railways') or
                         name == 'water' and tags.get('waterway') in ('river', 'canal', 'ditch')]
            if names:
                self.add(tags, geom, f'way/{way.id}', way.id, 'way', names)

        def area(self, osm_area):
            tags = dict(osm_area.tags)
            names = [name for name, query in queries.items()
                     if name not in ('roads', 'railways') and matches(tags, query)]
            if not names:
                return
            try:
                geom = shapely.from_wkb(factory.create_multipolygon(osm_area))
            except (osmium.InvalidLocationError, RuntimeError):
                self.errors['area_assembly'] += 1
                return
            kind = 'way' if osm_area.from_way() else 'relation'
            self.add(tags, geom, f'{kind}/{osm_area.orig_id()}', osm_area.orig_id(), kind, names)

    handler = CityHandler()
    print('Чтение регионального PBF и сборка полигонов libosmium...', flush=True)
    # libosmium's Windows file API cannot open this workspace's Cyrillic path.
    # Python handles the path, and libosmium reads the same PBF bytes from memory.
    handler.apply_buffer(Path(pbf).read_bytes(), 'pbf', locations=True, idx='flex_mem')
    layers = {}
    for name, rows in handler.rows.items():
        layer = gpd.GeoDataFrame(rows, geometry='geometry', crs=4326) if rows else gpd.GeoDataFrame(geometry=[], crs=4326)
        if len(layer):
            layer = layer.drop_duplicates('osm_uid').reset_index(drop=True)
            layer = compact_layer(layer)
        layers[name] = layer
        print(name, len(layer), flush=True)
    response = {'elements': list(handler.graph_nodes.values()) + handler.graph_ways}
    print('Исходных узлов графа:', len(handler.graph_nodes), '; дорожных ways:', len(handler.graph_ways), flush=True)
    return layers, response, dict(handler.errors)


def compact_layer(layer):
    """Keep study inputs; the original PBF preserves the full set of OSM tags."""
    keep = {'geometry', 'osm_uid', 'osm_type', 'osm_id', 'name', 'ref', 'addr:street',
            'addr:housenumber', 'building', 'building:levels', 'building:flats',
            'landuse', 'highway', 'service', 'railway', 'waterway', 'water', 'natural',
            'riverbank', 'reservoir', 'basin', 'dock', 'canal', 'pond', 'amenity',
            'capacity', 'operator', 'maxspeed', 'oneway', 'access', 'motor_vehicle', 'motorcar'}
    return layer[[column for column in layer.columns if column in keep]].copy()


def graph_from_response(response):
    graph = ox.graph._create_graph([response], bidirectional=False)
    graph = ox.simplification.simplify_graph(graph)
    graph = ox.routing.add_edge_speeds(graph)
    graph = ox.routing.add_edge_travel_times(graph)
    return graph
