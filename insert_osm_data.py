"""This program parses an OSM XML file and inserts the data in a
MongoDB database"""

import sys
import os
import time
import pymongo
from datetime import datetime
from xml.sax import make_parser
from xml.sax.handler import ContentHandler
from pymongo import Connection

class OsmHandler(ContentHandler):
    """Base class for parsing OSM XML data"""
    def __init__(self, client):
        self.records = []
        self.record = {}
        self.client = client
        """
        self.client.osm.nodes.ensure_index([('loc', pymongo.GEO2D)])
        self.client.osm.nodes.ensure_index([('id', pymongo.ASCENDING),
                                            ('version', pymongo.DESCENDING)])
        self.client.osm.ways.ensure_index([('id', pymongo.ASCENDING),
                                           ('version', pymongo.DESCENDING)])
        self.client.osm.ways.ensure_index([('loc', pymongo.GEO2D)])
        self.client.osm.relations.ensure_index([('id', pymongo.ASCENDING),
                                                ('version', pymongo.DESCENDING)])
        """
        self.stats = {'nodes': 0, 'ways': 0, 'relations': 0}
        self.lastStatString = ""
        self.statsCount = 0

    def writeStatsToScreen(self):
        for char in self.lastStatString:
            sys.stdout.write('\b')
        self.lastStatString = "%dk nodes, %dk ways, %d relations" % (self.stats['nodes'] / 1000,
                                                                     self.stats['ways'] / 1000,
                                                                     self.stats['relations'])
        sys.stdout.write(self.lastStatString)

    def fillDefault(self, attrs):
        """Fill in default record values"""
        self.record['_id'] = long(attrs['id'])
        self.record['timestamp'] = self.isoToTimestamp(attrs['timestamp'])
        self.record['tags'] = [] 
        self.record['keys'] = []
        if attrs.has_key('user'):
            self.record['user'] = attrs['user']
        if attrs.has_key('uid'):
            self.record['uid'] = long(attrs['uid'])
        if attrs.has_key('version'):
            self.record['version'] = int(attrs['version'])
        if attrs.has_key('changeset'):
            self.record['changeset'] = long(attrs['changeset'])

    def isoToTimestamp(self, isotime):
        """Parse a date and return a time tuple"""
        t = datetime.strptime(isotime, "%Y-%m-%dT%H:%M:%SZ")
        return time.mktime(t.timetuple())

    def startElement(self, name, attrs):
        """Parse the XML element at the start"""
        if name == 'node':
            self.fillDefault(attrs)
            self.record['loc'] = {'lat': float(attrs['lat']),
                                  'lon': float(attrs['lon'])}
        elif name == 'changeset':
            self.fillDefault(attrs)
        elif name == 'tag':
            k = attrs['k']
            v = attrs['v']
            # MongoDB doesn't let us have dots in the key names.
            #k = k.replace('.', ',,')
            self.record['tags'].append((k, v))
            self.record['keys'].append(k)
        elif name == 'way':
            # Insert remaining nodes
            if len(self.records) > 0:
                self.client.osm.nodes.insert(self.records)
                self.records = []

            self.fillDefault(attrs)
            self.record['nodes'] = []
        elif name == 'relation':
            self.fillDefault(attrs)
            self.record['members'] = []
        elif name == 'nd':
            ref = long(attrs['ref'])
            self.record['nodes'].append(ref)
        elif name == 'member':
            ref = long(attrs['ref'])
            member = {'type': attrs['type'],
                      'ref':  ref,
                      'role': attrs['role']}
            self.record['members'].append(member)
            
            if attrs['type'] == 'way':
                ways2relations = self.client.osm.ways.find_one({ '_id' : ref})
                if ways2relations:
                    if 'relations' not in ways2relations:
                        ways2relations['relations'] = []
                    ways2relations['relations'].append(self.record['_id'])
                    self.client.osm.ways.save(ways2relations)
            elif attrs['type'] == 'node':
                nodes2relations = self.client.osm.nodes.find_one({ '_id' : ref})
                if nodes2relations:
                    if 'relations' not in nodes2relations:
                        nodes2relations['relations'] = []
                    nodes2relations['relations'].append(self.record['_id'])
                    self.client.osm.nodes.save(nodes2relations)
        
    def endElement(self, name):
        """Finish parsing an element
        (only really used with nodes, ways and relations)"""
        if name == 'node':
            self.records.append(self.record)
            if len(self.records) > 1500:
                self.client.osm.nodes.insert(self.records)
                self.records = []
                self.writeStatsToScreen()
            self.record = {}
            self.stats['nodes'] = self.stats['nodes'] + 1
        elif name == 'way':
            nodes = self.client.osm.nodes.find({ '_id': { '$in': self.record['nodes'] } }, { 'loc': 1, '_id': 0 })
            self.record['loc'] = []
            for node in nodes:
                self.record['loc'].append(node['loc'])

            self.client.osm.ways.insert(self.record)
            self.record = {}
            self.statsCount = self.statsCount + 1
            if self.statsCount > 1000:
                self.writeStatsToScreen()
                self.statsCount = 0
            self.stats['ways'] = self.stats['ways'] + 1
        elif name == 'relation':
            self.client.osm.relations.save(self.record)
            self.record = {}
            self.statsCount = self.statsCount + 1
            if self.statsCount > 10:
                self.writeStatsToScreen()
                self.statsCount = 0
            self.stats['relations'] = self.stats['relations'] + 1

if __name__ == "__main__":
    filename = sys.argv[1]

    if not os.path.exists(filename):
        print "Path %s doesn't exist." % (filename)
        sys.exit(-1)

    client = Connection()
    parser = make_parser()
    handler = OsmHandler(client)
    parser.setContentHandler(handler)
    parser.parse(open(filename))
    client.disconnect()
