
import os

class Configuration(object):
	def __init__(self):
		self.mongodb_uri = self.value("MONGODB_URI", "mongodb://localhost:27017/")
		self.mongodb_rs = self.value("MONGODB_RS")
		self.mongodb_host = self.value("MONGODB_HOST")
		self.mongodb_port = self.value("MONGODB_PORT")
		self.mongodb_queue_db = self.value("MONGODB_QUEUE_DB", "workqueue")
		self.mongodb_queue_col = self.value("MONGODB_QUEUE_COLLECTION", "q")
		self.mongodb_rs_srv = self.value("MONGODB_RS_SRV")
		self.template_path = self.value("TEMPLATE_PATH", "/opt/rcll-sim-ctrl/templates")
		self.kube_namespace = self.value("NAMESPACE", "default")

	def value(self, key, default=None):
		if key in os.environ:
			return os.environ[key]
		else:
			return default
