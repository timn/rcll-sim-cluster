
import kubernetes
from kubernetes.client import V1Container, V1DeleteOptions, V1ObjectMeta, V1Pod, V1PodSpec
from kubernetes.watch import Watch
from kubernetes.client.rest import ApiException

import jinja2
import yaml

class PodController(object):
	def __init__(self, config):
		self.kube_config = kubernetes.config.load_incluster_config()
		self.core_api = kubernetes.client.CoreV1Api()
		self.pods = {}
		self.services = {}

		self.jinja = jinja2.Environment(loader=jinja2.FileSystemLoader(config.template_path),
										autoescape=False)

	def wait_pod_event(self, namespace, name, cond):
		w = Watch()
		for event in w.stream(self.core_api.list_pod_for_all_namespaces, timeout_seconds=120):
			object = event['object']
			etype = event['type']
			if object.metadata.namespace != namespace or object.metadata.name != name: continue
			if cond(etype, object):
				w.stop()

	def _pod_completed_cond(etype, object):
		return (etype == "MODIFIED" and
				(object.status.phase == "Succeeded" or object.status.phase == "Failed"))

	def create_from_template(self, template_name, vars, sufficient_containers=[]):
		template = self.jinja.get_template(template_name + ".yaml.j2")
		if template is None:
			print("Failed to get template '%s'" % template_name)
			raise FileNotFoundError("Could not find template '%s'" % template_name)

		rv = []
		
		yamldoc = template.render(vars)
		#print("YAML doc:\n%s\n\n" % yamldoc)
		rv.append(("yamldoc", template_name, yamldoc))
		manifests = yaml.load_all(yamldoc)
		for manifest in manifests:
			if manifest["kind"] == "Pod":
				print("Creating Pod '%s'" % manifest["metadata"]["name"])
				self.create_pod(manifest, sufficient_containers=sufficient_containers)
				s = ",".join(["{}{}".format("*" if c["name"] in sufficient_containers else "", c["name"])
				              for c in manifest["spec"]["containers"]])
				rv.append((manifest["kind"], manifest["metadata"]["name"] + " (" + s + ")", manifest))

			elif manifest["kind"] == "Service":
				print("Creating Service '%s'" % manifest["metadata"]["name"])
				self.create_service(manifest)
				rv.append((manifest["kind"], manifest["metadata"]["name"], manifest))

			else:
				raise ValueError("Unsupported manifest kind '%s'" % manifest["kind"])

			#print("%s\n\n" % str(manifest))
		return rv

	def create_namespace(self, namespace):
		body = {
			"kind": "Namespace",
			"apiVersion": "v1",
			"metadata": {
				"name": namespace
			}
		}
		try:
			res = self.core_api.create_namespace(body)
		except ApiException as e:
			print("Failed to create namespace %s: '%s'" % (namespace, e))
			raise

	def create_pod(self, manifest, sufficient_containers=[]):
		try:
			res = self.core_api.create_namespaced_pod(namespace=manifest["metadata"]["namespace"],
													  body=manifest)
			self.pods[(manifest["metadata"]["namespace"], manifest["metadata"]["name"])] = \
				{ "phase": "Requested",
				  "manifest": manifest,
				  "sufficient_containers": sufficient_containers }
		except ApiException as e:
			print("Failed to create pod %s/%s: '%s'" % (manifest["metadata"]["namespace"],
														manifest["metadata"]["name"], e))
			
	def create_service(self, manifest):
		try:
			res = self.core_api.create_namespaced_service(namespace=manifest["metadata"]["namespace"],
														  body=manifest)
			self.services[(manifest["metadata"]["namespace"], manifest["metadata"]["name"])] = \
				{ "phase": "Requested", "manifest": manifest }
		except ApiException as e:
			print("Failed to create service %s/%s: '%s'" % (manifest["metadata"]["namespace"],
														manifest["metadata"]["name"], e))

	def delete_all(self):
		# We must pass a new default API client to avoid urllib conn pool warnings
		core_api_del = kubernetes.client.CoreV1Api(kubernetes.client.ApiClient())
		for uid in self.pods:
			print("Deleting pod %s:%s" % uid)
			res = core_api_del.delete_namespaced_pod(namespace = uid[0],
			                                         name = uid[1],
			                                         body = V1DeleteOptions())

		for uid in self.services:
			print("Deleting service %s:%s" % uid)
			res = core_api_del.delete_namespaced_service(namespace = uid[0], name = uid[1])

		# Not checking for possibly deleted pods, pods take a while to
		# delete and they will not be listed anymore

		print("Waiting for pods to be deleted: %s" % ', '.join(["%s:%s" % uid for uid in self.pods]))
		current_pods = [(i.metadata.namespace, i.metadata.name)
		                for i in core_api_del.list_pod_for_all_namespaces().items]
		print("Current pods: %s" % ', '.join(["%s:%s" % uid for uid in current_pods]))
		deleted_pods = [uid for uid in self.pods if uid not in current_pods]
		print("Deleted pods: %s" % ', '.join(["%s:%s" % uid for uid in deleted_pods]))
		for uid in deleted_pods:
			print("  - %s:%s*" % uid)
			#del self.pods[uid]

		while self.pods:
			print("Remaining: %s" % ', '.join(["%s:%s" % uid for uid in self.pods]))
			w = Watch()
			for event in w.stream(core_api_del.list_pod_for_all_namespaces):
				object = event['object']
				etype = event['type']
				uid = (object.metadata.namespace, object.metadata.name)
				if etype == "DELETED" and uid in self.pods:
					print("  - %s:%s" % uid)
					del self.pods[uid]
					if not self.pods: w.stop()
		print("Done deleting pods")

		print("Waiting for services to be deleted: %s" % ', '.join(["%s:%s" % uid for uid in self.services]))
		current_services = [(i.metadata.namespace, i.metadata.name)
		                    for i in core_api_del.list_service_for_all_namespaces().items]
		print("Current services: %s" % ', '.join(["%s:%s" % uid for uid in current_services]))
		deleted_services = [uid for uid in self.services if uid not in current_services]
		print("Deleted services: %s" % ', '.join(["%s:%s" % uid for uid in deleted_services]))
		for uid in deleted_services:
			print("  - %s:%s*" % uid)
			del self.services[uid]

		# There is a short gap here that could trigger a race condition
		# but there seems to be no "query and keep watching" API that could
		# prevent that.

		while self.services:
			print("Remaining: %s" % ', '.join(["%s:%s" % uid for uid in self.services]))
			w = Watch()
			for event in w.stream(core_api_del.list_service_for_all_namespaces):
				object = event['object']
				etype = event['type']
				uid = (object.metadata.namespace, object.metadata.name)
				if etype == "DELETED" and uid in self.services:
					print("  - %s:%s" % uid)
					del self.services[uid]
					if not self.services: w.stop()
		print("Done deleting services")

	def monitor_pods(self):
		success=True
		# Wrap watch in outer loop, it might get interrupted before we
		# are finished looking
		while self.pods:
			w = Watch()
			for event in w.stream(self.core_api.list_pod_for_all_namespaces):
				object = event['object']
				etype = event['type']
				uid = (object.metadata.namespace, object.metadata.name)
				if uid in self.pods:
					print("Event: %s %s %s" % (etype, object.metadata.name, object.status.phase))
				
					if etype == "MODIFIED":
						#print("  %s" % object)
						self.pods[uid]["phase"] = object.status.phase
						if ((object.status.phase == "Succeeded" or object.status.phase == "Failed")
						    and object.metadata.deletion_timestamp == None):

							if not success_determined:
								if object.status.phase == "Failed":
									return False

							print("Pod %s/%s is finished" % (object.metadata.namespace, object.metadata.name))
							self.delete_all()

						if object.status.container_statuses is not None:
							for c in filter(lambda c: c.state.terminated, object.status.container_statuses):

								# If any container failed, assume overall failure
								if c.state.terminated.exit_code != 0:
									print("Container '%s' of pod '%s:%s' failed"
									      % (c.name, uid[0], uid[1]))
									return False

								# If a sufficient container completed, assume overall completion
								elif c.name in self.pods[uid]["sufficient_containers"]:
									print("Container '%s' of pod '%s:%s' succeeded, finishing"
									      % (c.name, uid[0], uid[1]))
									return True

					if etype == "DELETED":
						print("Pod %s/%s has been deleted" % (object.metadata.namespace, object.metadata.name))
						del self.pods[uid]
						if not self.pods:
							w.stop()
							print("Done watching events")

		return True
