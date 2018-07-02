
import kubernetes
from kubernetes.client import V1Container, V1DeleteOptions, V1ObjectMeta, V1Pod, V1PodSpec
from kubernetes.watch import Watch
from kubernetes.client.rest import ApiException
from kubernetes.client.api_client import ApiClient

import jinja2
import yaml
import json
from datetime import datetime, timedelta
import traceback
import requests
import gzip
import sys
import os
import humanize

PROGRESS_BAR_WIDTH = 25

class PodController(object):
	def __init__(self, config, namespace="default"):
		self.namespace = namespace
		kubernetes.config.load_incluster_config()
		self.kube_config = kubernetes.client.configuration
		self.core_api = kubernetes.client.CoreV1Api()
		self.beta1_api = kubernetes.client.ExtensionsV1beta1Api()
		self.rbac_api = kubernetes.client.RbacAuthorizationV1beta1Api()
		self.resources = {
			"pods": {},
			"services": {},
			"ingress": {},
			"config_maps": {},
			"roles": {},
			"role_bindings": {},
			"service_accounts": {},
		}

		self.jinja = jinja2.Environment(loader=jinja2.FileSystemLoader(config.template_path),
										autoescape=False, extensions=['jinja2.ext.with_'])

	def wait_pod_event(self, name, cond):
		w = Watch()
		for event in w.stream(self.core_api.list_namespaced_pod, self.namespace, timeout_seconds=120):
			object = event['object']
			etype = event['type']
			if object.metadata.name != name: continue
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
		rv.append(("YAML", template_name, yamldoc))
		try:
			manifests = yaml.load_all(yamldoc)
		except:
			print("Inflicting YAML doc:\n%s" % yamldoc)
			raise

		for manifest in manifests:
			if manifest["kind"] == "Pod":
				#print("Creating Pod '%s'" % manifest["metadata"]["name"])
				s = manifest["metadata"]["name"] + " (" \
				    + ",".join(["{}{}".format("*" if c["name"] in sufficient_containers else "", c["name"])
				                for c in manifest["spec"]["containers"]]) \
				    + ")"
				print("    - %s: %s" % (manifest["kind"], s))
				try:
					self.create_pod(manifest, sufficient_containers=sufficient_containers)
				except:
					print("Inflicting YAML doc:\n%s" % yamldoc)
					raise
				rv.append((manifest["kind"], s, manifest))

			elif manifest["kind"] == "Service":
				#print("Creating Service '%s'" % manifest["metadata"]["name"])
				print("    - %s: %s" % (manifest["kind"], manifest["metadata"]["name"]))
				try:
					self.create_service(manifest)
				except:
					print("Inflicting YAML doc:\n%s" % yamldoc)
					raise
				rv.append((manifest["kind"], manifest["metadata"]["name"], manifest))

			elif manifest["kind"] == "Ingress":
				#print("Creating Ingress '%s'" % manifest["metadata"]["name"])
				print("    - %s: %s" % (manifest["kind"], manifest["metadata"]["name"]))
				try:
					self.create_ingress(manifest)
				except:
					print("Inflicting YAML doc:\n%s" % yamldoc)
					raise
				rv.append((manifest["kind"], manifest["metadata"]["name"], manifest))

			elif manifest["kind"] == "ConfigMap":
				#print("Creating ConfigMap '%s'" % manifest["metadata"]["name"])
				print("    - %s: %s" % (manifest["kind"], manifest["metadata"]["name"]))
				try:
					self.create_config_map(manifest)
				except:
					print("Inflicting YAML doc:\n%s" % yamldoc)
					raise
				rv.append((manifest["kind"], manifest["metadata"]["name"], manifest))

			elif manifest["kind"] == "Role":
				print("    - %s: %s" % (manifest["kind"], manifest["metadata"]["name"]))
				try:
					self.create_role(manifest)
				except:
					print("Inflicting YAML doc:\n%s" % yamldoc)
					raise
				rv.append((manifest["kind"], manifest["metadata"]["name"], manifest))

			elif manifest["kind"] == "RoleBinding":
				print("    - %s: %s" % (manifest["kind"], manifest["metadata"]["name"]))
				try:
					self.create_role_binding(manifest)
				except:
					print("Inflicting YAML doc:\n%s" % yamldoc)
					raise
				rv.append((manifest["kind"], manifest["metadata"]["name"], manifest))

			else:
				raise ValueError("Unsupported manifest kind '%s'" % manifest["kind"])

			#print("%s\n\n" % str(manifest))
		return rv
	
	def create_pod(self, manifest, sufficient_containers=[]):
		try:
			res = self.core_api.create_namespaced_pod(namespace=manifest["metadata"]["namespace"],
													  body=manifest)
			self.resources["pods"][(manifest["metadata"]["namespace"], manifest["metadata"]["name"])] = \
				{ "phase": "Requested",
				  "status": "Requested",
				  "manifest": manifest,
				  "sufficient_containers": sufficient_containers,
				  "total": 0,
				  "ready": 0,
				}
		except ApiException as e:
			print("Failed to create pod %s/%s: '%s'" % (manifest["metadata"]["namespace"],
														manifest["metadata"]["name"], e))
			raise e
			
	def create_service(self, manifest):
		try:
			res = self.core_api.create_namespaced_service(namespace=manifest["metadata"]["namespace"],
														  body=manifest)
			self.resources["services"][(manifest["metadata"]["namespace"], manifest["metadata"]["name"])] = \
				{ "phase": "Requested", "manifest": manifest }
		except ApiException as e:
			print("Failed to create service %s/%s: '%s'" % (manifest["metadata"]["namespace"],
														manifest["metadata"]["name"], e))
			raise e

	def create_ingress(self, manifest):
		try:
			res = self.beta1_api.create_namespaced_ingress(namespace=manifest["metadata"]["namespace"],
			                                               body=manifest)
			self.resources["ingress"][(manifest["metadata"]["namespace"], manifest["metadata"]["name"])] = \
				{ "phase": "Requested", "manifest": manifest }
		except ApiException as e:
			print("Failed to create ingress %s/%s: '%s'" % (manifest["metadata"]["namespace"],
			                                                manifest["metadata"]["name"], e))
			raise e

	def create_config_map(self, manifest):
		try:
			res = self.core_api.create_namespaced_config_map(namespace=manifest["metadata"]["namespace"],
			                                                 body=manifest)
			self.resources["config_maps"][(manifest["metadata"]["namespace"], manifest["metadata"]["name"])] = \
				{ "phase": "Requested", "manifest": manifest }
		except ApiException as e:
			print("Failed to create config map %s/%s: '%s'" % (manifest["metadata"]["namespace"],
			                                                   manifest["metadata"]["name"], e))
			raise e

	def create_role(self, manifest):
		try:
			res = self.rbac_api.create_namespaced_role(namespace=manifest["metadata"]["namespace"],
			                                           body=manifest)
			self.resources["roles"][(manifest["metadata"]["namespace"], manifest["metadata"]["name"])] = \
				{ "phase": "Requested", "manifest": manifest }
		except ApiException as e:
			print("Failed to create role %s/%s: '%s'" % (manifest["metadata"]["namespace"],
			                                             manifest["metadata"]["name"], e))
			raise e

	def create_role_binding(self, manifest):
		try:
			res = self.rbac_api.create_namespaced_role_binding(namespace=manifest["metadata"]["namespace"],
			                                                   body=manifest)
			self.resources["role_bindings"][(manifest["metadata"]["namespace"], manifest["metadata"]["name"])] = \
				{ "phase": "Requested", "manifest": manifest }
		except ApiException as e:
			print("Failed to create role binding %s/%s: '%s'" % (manifest["metadata"]["namespace"],
			                                                     manifest["metadata"]["name"], e))
			raise e

	def create_service_account(self, manifest):
		try:
			res = self.core_api.create_namespaced_service_account(namespace=manifest["metadata"]["namespace"],
			                                                      body=manifest)
			self.resources["service_accounts"][(manifest["metadata"]["namespace"],
			                                    manifest["metadata"]["name"])] = \
				{ "phase": "Requested", "manifest": manifest }
		except ApiException as e:
			print("Failed to create service account %s/%s: '%s'" % (manifest["metadata"]["namespace"],
			                                                        manifest["metadata"]["name"], e))
			raise e

	def download_all_pod_logs(self, output_dir, progress=True, compress=True):

		# K8s API Server compression is an alpha feature as of 1.9 and disabled by default
		# (feature gate APIResponseCompression). Therefore, requesting compression is not
		# enabled here but we rather compress ourselves. Can be added later.

		headers = {"Authorization": self.kube_config.get_api_key_with_prefix('authorization')}
		params = {"timestamps": True}

		print("Downloading pod logs")
		for uid in self.resources["pods"]:
			namespace = uid[0]
			pod_name  = uid[1]

			pod = self.core_api.read_namespaced_pod(pod_name, namespace)
			if not pod:
				print("Failed to get info for pod %s:%s" % uid)
				continue

			containers = [c.name for c in pod.spec.containers]
			print("  - Pod %s:%s %s" % (namespace, pod_name, str(containers)))

			output_poddir   = "%s/%s" % (output_dir, pod_name)
			os.makedirs(output_poddir)

			for container in containers:
				output_filename = "%s/%s.log.gz" % (output_poddir, container)

				url = "%s/api/v1/namespaces/%s/pods/%s/log" % \
				      (self.kube_config.host, namespace, pod_name)

				#print("URL: %s" % url)
				#print("Output: %s" % output_filename)

				headers = {"Authorization": self.kube_config.get_api_key_with_prefix('authorization')}
				params = {"container": container, "timestamps": True}

				r = requests.get(url, stream=True, headers=headers, params=params,
				                 verify=self.kube_config.ssl_ca_cert)

				with gzip.open(output_filename, 'wb') as f:
					dl_progress = progress
					dl = 0
					last_done = 0
					total_length = 0
					cl = r.headers.get('content-length')
					if cl is not None:
						total_length = int(cl)
					else:
						dl_progress = False

					if progress and not dl_progress:
						sys.stdout.write("    - container %-30s (chunked response)" % container)
						sys.stdout.flush()
					else:
						sys.stdout.write("    - container %-30s" % container)
						sys.stdout.flush()

					for chunk in r.iter_content(chunk_size=4096):
						if chunk: # filter out keep-alive new chunks
							dl += len(chunk)
							f.write(chunk)

							if dl_progress:
								done = int(PROGRESS_BAR_WIDTH * dl / total_length)
								if done > last_done:
									sys.stdout.write("\r    - %-30s [%s%s] %10s / %-10s" %
									                 (container,
									                  '=' * done, ' ' * (PROGRESS_BAR_WIDTH - done),
									                  humanize.naturalsize(dl, binary=True),
									                  humanize.naturalsize(total_length, binary=True)))
									sys.stdout.flush()
									last_done = done

					if dl_progress:
						sys.stdout.write("\n")
					else:
						sys.stdout.write(" %40s\n" % (humanize.naturalsize(dl, binary=True)))

	def delete_all(self):
		# We must pass a new default API client to avoid urllib conn pool warnings
		start_time = datetime.now()
		print("Deleting items")
		for uid in self.resources["pods"]:
			print("  - Pod %s:%s" % uid)
			try:
				res = self.core_api.delete_namespaced_pod(namespace = uid[0],
				                                          name = uid[1],
				                                          body = V1DeleteOptions())
			except:
				print("    (issue cleaning up, ignored)")

		for uid in self.resources["services"]:
			print("  - Service %s:%s" % uid)
			try:
				res = self.core_api.delete_namespaced_service(namespace = uid[0], name = uid[1])
			except:
				print("    (issue cleaning up, ignored)")


		for uid in self.resources["ingress"]:
			print("  - Ingress %s:%s" % uid)
			try:
				res = self.beta1_api.delete_namespaced_ingress(namespace = uid[0], name = uid[1],
				                                               body = V1DeleteOptions())
			except:
				print("    (issue cleaning up, ignored)")
		self.resources["ingress"] = {}

		for uid in self.resources["config_maps"]:
			print("  - ConfigMap %s:%s" % uid)
			try:
				res = self.core_api.delete_namespaced_config_map(namespace = uid[0],
				                                                 name = uid[1],
				                                                 body = V1DeleteOptions())
			except:
				print("    (issue cleaning up, ignored)")
		self.resources["config_maps"] = {}

		for uid in self.resources["role_bindings"]:
			print("  - RoleBinding %s:%s" % uid)
			try:
				res = self.rbac_api.delete_namespaced_role_binding(namespace = uid[0],
				                                                   name = uid[1],
				                                                   body = V1DeleteOptions())
			except:
				print("    (issue cleaning up, ignored)")
		self.resources["role_bindings"] = {}

		for uid in self.resources["roles"]:
			print("  - Role %s:%s" % uid)
			try:
				res = self.rbac_api.delete_namespaced_role(namespace = uid[0],
				                                           name = uid[1],
				                                           body = V1DeleteOptions())
			except:
				print("    (issue cleaning up, ignored)")
		self.resources["roles"] = {}

		for uid in self.resources["service_accounts"]:
			print("  - ServiceAccount %s:%s" % uid)
			try:
				res = self.rbac_api.delete_namespaced_service_account(namespace = uid[0],
				                                                      name = uid[1],
				                                                      body = V1DeleteOptions())
			except:
				print("    (issue cleaning up, ignored)")
		self.resources["service_accounts"] = {}

		# Not checking for possibly deleted pods, pods take a while to
		# delete and they will not be listed anymore

		print("Waiting for pod and service deletion")
		#print("Waiting for pods to be deleted: %s" % ', '.join(["%s:%s" % uid for uid in self.resources["pods"]]))
		while self.resources["pods"]:
			current_pods = [(i.metadata.namespace, i.metadata.name)
			                for i in self.core_api.list_namespaced_pod(self.namespace).items]
			#print("Current pods: %s" % ', '.join(["%s:%s" % uid for uid in current_pods]))
			deleted_pods = [uid for uid in self.resources["pods"] if uid not in current_pods]
			#print("Deleted pods: %s" % ', '.join(["%s:%s" % uid for uid in deleted_pods]))
			for uid in deleted_pods:
				print("  - Pod %s:%s*" % uid)
				del self.resources["pods"][uid]
			if not self.resources["pods"]: break

			#print("Remaining: %s" % ', '.join(["%s:%s" % uid for uid in self.resources["pods"]]))
			w = Watch()
			for event in w.stream(self.core_api.list_namespaced_pod, self.namespace,
			                      timeout_seconds=30):
				object = event['object']
				etype = event['type']
				uid = (object.metadata.namespace, object.metadata.name)
				if etype == "DELETED" and uid in self.resources["pods"]:
					print("  - Pod %s:%s" % uid)
					del self.resources["pods"][uid]
					if not self.resources["pods"]: w.stop()
		#print("Done deleting pods")

		#print("Waiting for services to be deleted: %s" % ', '.join(["%s:%s" % uid for uid in self.resources["services"]]))
		while self.resources["services"]:
			current_services = [(i.metadata.namespace, i.metadata.name)
			                    for i in self.core_api.list_namespaced_service(self.namespace).items]
			#print("Current services: %s" % ', '.join(["%s:%s" % uid for uid in current_services]))
			deleted_services = [uid for uid in self.resources["services"] if uid not in current_services]
			#print("Deleted services: %s" % ', '.join(["%s:%s" % uid for uid in deleted_services]))
			for uid in deleted_services:
				print("  - Service %s:%s*" % uid)
				del self.resources["services"][uid]
			if not self.resources["services"]: break

			# There is a short gap here that could trigger a race condition
			# but there seems to be no "query and keep watching" API that could
			# prevent that.

			#print("Remaining: %s" % ', '.join(["%s:%s" % uid for uid in self.resources["services"]]))
			w = Watch()
			for event in w.stream(self.core_api.list_namespaced_service, self.namespace,
			                      timeout_seconds=30):
				object = event['object']
				etype = event['type']
				uid = (object.metadata.namespace, object.metadata.name)
				if etype == "DELETED" and uid in self.resources["services"]:
					print("  - Service %s:%s" % uid)
					del self.resources["services"][uid]
					if not self.resources["services"]: w.stop()
		#print("Done deleting services")

		all_deleted_time = datetime.now()
		print("All items deleted (deletion took %s)" % str(all_deleted_time-start_time))

	def monitor_pods(self):
		# Wrap watch in outer loop, it might get interrupted before we
		# are finished looking
		printed_all_up=False
		start_time = datetime.now()
		while self.resources["pods"]:
			try:
				w = Watch()
				for event in w.stream(self.core_api.list_namespaced_pod, self.namespace):
					object = event['object']
					etype = event['type']
					uid = (object.metadata.namespace, object.metadata.name)
					if uid in self.resources["pods"]:
						if etype == "MODIFIED":

							#print("************************************\n%s %s\n%s" \
							#      % (etype, object.metadata.name, object))

							ready = 0
							total = len(object.spec.containers)
							pod_name_ip = "n/a"
							status = object.status.phase
							if object.status.reason is not None:
								status = object.status.reason
							if object.spec.node_name and object.spec.node_name != "":
								pod_name_ip = object.spec.node_name
							if object.status.pod_ip and object.status.pod_ip != "":
								pod_name_ip += "/" + object.status.pod_ip

							initializing = False

							# On Kubernetes 1.5, get init container status out of the annotation manually
							if not object.status.init_container_statuses \
							   and object.metadata.annotations \
							   and "pod.alpha.kubernetes.io/init-container-statuses" in object.metadata.annotations:
								jp = json.loads(object.metadata.annotations["pod.alpha.kubernetes.io/init-containers"])
								js = json.loads(object.metadata.annotations["pod.alpha.kubernetes.io/init-container-statuses"])
								a = ApiClient()
								object.spec.init_containers = \
									a._ApiClient__deserialize(jp, "list[V1Container]")
								object.status.init_container_statuses = \
									a._ApiClient__deserialize(js, "list[V1ContainerStatus]")

							if object.status.init_container_statuses is not None:
								for i, cs in enumerate(object.status.init_container_statuses):
									if cs.state.terminated and cs.state.terminated.exit_code == 0:
										continue
									elif cs.state.terminated:
										if len(cs.state.terminated.reason) == 0:
											if cs.state.terminated.signal != 0:
												status = "Init:Signal:%d" % cs.state.terminated.signal
											else:
												status = "Init:ExitCode:%d" % cs.state.terminated.exit_code
										else:
											status = "Init:" + cs.state.terminated.reason
										initializing = True
									elif cs.state.waiting and len(cs.state.waiting.reason) > 0 \
										 and cs.state.waiting.reason != "PodInitializing":
										status = "Init:" + cs.state.waiting.reason
										initializing = True
									else:
										status = "Init:%d/%d" % (i, len(object.spec.init_containers))
										initializing = True
									break

							if not initializing and object.status.container_statuses is not None:
								for cs in object.status.container_statuses:
									if cs.ready: ready += 1
									if cs.state.waiting and cs.state.waiting.reason != "":
										status = cs.state.waiting.reason
									elif cs.state.terminated and cs.state.terminated.reason != "":
										status = cs.state.terminated.reason
									elif cs.state.terminated and cs.state.terminated.reason == "":
										if cs.state.terminated.signal != 0:
											status = "Signal:%d" % cs.state.terminated.signal
										else:
											statis = "ExitCode:%d" % cs.state.terminated.exit_code

							print(" - %-24s %-18s %d/%d  %s" \
								  % (object.metadata.name, status, ready, total, pod_name_ip))

							self.resources["pods"][uid]["phase"] = object.status.phase
							self.resources["pods"][uid]["status"] = status
							self.resources["pods"][uid]["ready"] = ready
							self.resources["pods"][uid]["total"] = total
							if ((object.status.phase == "Succeeded" or object.status.phase == "Failed")
								and object.metadata.deletion_timestamp == None):

								if object.status.phase == "Failed":
									return False

								#print("Pod %s/%s is finished" % (object.metadata.namespace, object.metadata.name))
								#self.delete_all()

							if object.status.container_statuses is not None:
								for c in filter(lambda c: c.state.terminated, object.status.container_statuses):

									# If any container failed, assume overall failure
									if c.state.terminated.exit_code != 0:
										print("Container '%s' of pod '%s:%s' failed"
											  % (c.name, uid[0], uid[1]))
										return False

									# If a sufficient container completed, assume overall completion
									elif c.name in self.resources["pods"][uid]["sufficient_containers"]:
										print("Container '%s' of pod '%s:%s' succeeded, finishing"
											  % (c.name, uid[0], uid[1]))
										return True

						if etype == "DELETED":
							print("Pod %s/%s has been deleted" % (object.metadata.namespace, object.metadata.name))
							del self.resources["pods"][uid]
							if not self.resources["pods"]:
								w.stop()
								print("Done watching events")

					if not printed_all_up:
						all_up = True
						for k, p in self.resources["pods"].items():
							if p["status"] != "Running":
								all_up = False
							if p["ready"] != p["total"]:
								all_up = False
						if all_up:
							printed_all_up = True
							all_up_time = datetime.now()
							print("All pods up and running (setup took %s)" % str(all_up_time-start_time))

			except Exception as e:
				if str(e) != "TERM":
					print("Exception while monitoring pods")
					print(traceback.format_exc())
				return False

		return True
