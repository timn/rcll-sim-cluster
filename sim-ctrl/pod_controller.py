
import kubernetes
from kubernetes.client import V1Container, V1DeleteOptions, V1ObjectMeta, V1Pod, V1PodSpec
from kubernetes.watch import Watch
from kubernetes.client.rest import ApiException

import jinja2

class PodController(object):
    def __init__(self, config, work_queue):
        self.core_api = kubernetes.client.CoreV1Api()
        self.pods = {}
        self.kube_config = kubernetes.config.load_incluster_config()

        self.queue = work_queue
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

    def create_pod_from_template(self, template_name, vars):
        template = self.jinja.get_template(template_name + ".yaml.j2")
        if template == None:
            print("Failed to get template '%s'", template_name)
            yamldoc = template.render(vars)

        manifest = yaml.load(yamldoc)

        
        return self.create_pod(manifest)
    
    def create_pod(self, manifest):
        try:
            res = self.core_api.create_namespaced_pod(namespace=manifest["metadata"]["namespace"],
                                                      body=manifest)
            self.pods[(manifest["metadata"]["namespace"], manifest["metadata"]["name"])] = \
                                                                                           { "phase": "Requested", "manifest": manifest }
        except ApiException as e:
            print("Failed to create pod %s/%s: '%s'" % (manifest["metadata"]["namespace"],
                                                        manifest["metadata"]["name"], e))

    def monitor_pods(self):
        w = Watch()
        for event in w.stream(self.core_api.list_pod_for_all_namespaces, timeout_seconds=120):
            object = event['object']
            etype = event['type']
            uid = (object.metadata.namespace, object.metadata.name)
            if uid in self.pods:
                print("Event: %s %s %s" % (etype, object.metadata.name, object.status.phase))
                
                if etype == "MODIFIED":
                    #print("  %s" % event)
                    self.pods[uid]["phase"] = object.status.phase
                    if ((object.status.phase == "Succeeded" or object.status.phase == "Failed")
                        and object.metadata.deletion_timestamp == None):

                        # it's done, cleanup pod
                        print("Pod %s/%s is finished" % (object.metadata.namespace, object.metadata.name))
                        # We must pass a new default API client to avoid urllib conn pool warnings
                        core_api_del = kubernetes.client.CoreV1Api(kubernetes.client.ApiClient())
                        res = core_api_del.delete_namespaced_pod(namespace = object.metadata.namespace,
                                                                 name = object.metadata.name,
                                                                 body = V1DeleteOptions())

                if etype == "DELETED":
                    print("Pod %s/%s has been deleted" % (object.metadata.namespace, object.metadata.name))
                    del self.pods[uid]
                    if not self.pods:
                        w.stop()
                        print("Done watching events")
