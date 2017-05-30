#!/usr/bin/env python3

import pymongo
from pymongo import ReturnDocument
from pymongo.errors import ConnectionFailure

import datetime
import dns.resolver

class WorkQueue(object):
	def	__init__(self, database=None, collection=None,
				 host=None, port=None, srv_name=None, uri=None,
				 replicaset=None, count_collection="counters"):

		self.database_name = database or "workqueue"
		self.collection_name = collection or "q"
		self.count_collection_name = count_collection

		if host is not None and port is not None:
			self.client = pymongo.MongoClient(host, port, replicaset=replicaset)
		elif srv_name is not None:
			srv_records = dns.resolver.query(srv_name, 'SRV')
			uri="mongodb://" \
			     + ','.join([str(srv.target) + ":" + str(srv.port) for srv in srv_records])
			if self.database_name is not None:
				uri = uri + "/" + self.database_name
			if replicaset is not None:
				uri = uri + "?replicaSet=" + replicaset

			print("Connecting to %s" % uri)
			self.client = pymongo.MongoClient(uri)

		elif uri is not None:
			self.client = pymongo.MongoClient(uri)		
		else:
			raise ValueError("No valid connection parameter passed")

		# The following throws on connection failure
		# The ismaster command is cheap and does not require auth.
		self.client.admin.command('ismaster')

		self.db = self.client[self.database_name]
		self.collection = self.db[self.collection_name]
		self.collection.create_index([('name', pymongo.ASCENDING)], unique=True)

		self.count_collection = self.db[self.count_collection_name]

	def clear(self):
		self.collection.delete_many({})
		self.count_collection.delete_many({})

	def get_next_id(self):
		filter = {"_id": "workqueue_counter"}
		update = {"$inc": { "count": 1 }}
		doc = self.count_collection.find_one_and_update(filter, update,
		                                                upsert=True,
		                                                return_document=ReturnDocument.AFTER)
		return doc["count"]

	def add_item(self, name, idnum, params):
		doc = \
		{
			"name": name,
			"idnum": idnum,
			"params": params,
			"status": {
				"state": "pending",
				"created": datetime.datetime.utcnow(),
			}
		}
		self.collection.insert_one(doc)

	def get_specific_item(self, name):
		filter = {"name": name}
		item = self.collection.find_one(filter)
		#print("Item: %s" % item)
		return item

	def get_next_item(self, recently_failed_deadline=None):
		filter = {"status.state": "pending"}
		if recently_failed_deadline is not None:
			filter["$or"] = [ {"status.failed": { "$exists": False} },
			                  {"status.failed": { "$size": 0} },
			                  {"status.failed": { "$all": [ {"$elemMatch": { "$lte": recently_failed_deadline}}]}}]
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
		update = {"$set":   {"status.state": "pending"},
		          "$unset": {"status.running": ""},
		          "$push":  {"status.failed": datetime.datetime.utcnow()}}
		self.collection.update_one(filter, update)

	def update_item(self, name, update):
		filter = {"name": name}
		self.collection.update_one(filter, update)

	def total_num_jobs(self):
		return self.collection.count()

	def num_pending_jobs(self, recently_failed_deadline=None):
		all_pending_filter = {"status.state": "pending"}
		all_pending = self.collection.count(all_pending_filter)

		without_recently_failed = all_pending
		if recently_failed_deadline is not None:
			no_recently_failed_filter = {
				"status.state": "pending",
				"$or": [ {"status.failed": { "$exists": False} },
				         {"status.failed": { "$size": 0} },
				         {"status.failed": { "$all": [ {"$elemMatch": { "$lte": recently_failed_deadline}}]}}]
			}
			without_recently_failed = self.collection.count(no_recently_failed_filter)

		return (all_pending, without_recently_failed)
