#!/usr/bin/env python3

import pymongo
from pymongo.errors import ConnectionFailure

import datetime
import dns.resolver

class WorkQueue(object):
	def	__init__(self, database=None, collection=None,
				 host=None, port=None, srv_name=None, uri=None,
				 replicaset=None):

		self.database_name = database or "workqueue"
		self.collection_name = collection or "q"

		if host is not None and port is not None:
			self.client = pymongo.MongoClient(host, port, replicaset=replicaset)
		elif srv_name is not None:
			srv_records = dns.resolver.query('_mongodb._tcp.mongodb', 'SRV')
			uri="mongodb://" \
			     + ','.join([str(srv.target) + ":" + str(srv.port) for srv in srv_records])
			if self.database_name is not None:
				uri = uri + "/" + self.database_name
			if replicaset is not None:
				uri = uri + "?replicaSet=" + replicaset

			print("Connecting to %s" % uri)
			self.client = pymongo.MongoClient(uri)
		else:
			raise ValueError("No valid connection parameter passed")

		
		# The following throws on connection failure
		# The ismaster command is cheap and does not require auth.
		self.client.admin.command('ismaster')

		self.db = self.client[self.database_name]
		self.collection = self.db[self.collection_name]
		self.collection.create_index([('name', pymongo.ASCENDING)], unique=True)

	def clear(self):
		self.collection.delete_many({})

	def add_item(self, name, params):
		doc = \
		{
			"name": name,
			"params": params,
			"status": {
				"state": "pending",
				"created": datetime.datetime.utcnow(),
			}
		}
		self.collection.insert_one(doc)

	def get_next_item(self):
		filter = {"status.state": "pending"}
		update = {"$set": {"status.state": "running",
		                   "status.running": datetime.datetime.utcnow()}}
		sort = [("status.created", pymongo.ASCENDING)]
		item = self.collection.find_one_and_update(filter, update, sort=sort)
		#print("Item: %s" % item)
		if item is None:
			return None
		else:
			return { "name": item["name"], "params": item["params"] }

	def mark_item_done(self, name):
		filter = {"name": name}
		update = {"$set": {"status.state": "completed",
		                   "status.completed": datetime.datetime.utcnow()}}
		self.collection.update_one(filter, update)

	def requeue_item(self, name):
		filter = {"name": name}
		update = {"$set": {"status.state": "pending"},
		          "$unset": {"status.running": ""}}
		self.collection.update_one(filter, update)

	def total_num_jobs(self):
		return self.collection.count()

		
if __name__ == '__main__':
	wq = WorkQueue(srv_name="_mongodb._tcp.mongodb")
	wq.clear()
	wq.add_item("test", {"team-cyan": "A-Team", "team-magenta": "B-Team"})
	item = wq.get_next_item()
	print("Item: %s" % item)
	wq.mark_item_done(item["name"])
