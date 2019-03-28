# RCLL Simulation Cluster

## Introduction

This repository contains all configuration files and scripts (aside the actual
containers, they are maintained in
[docker-robotics](https://github.com/timn/docker-robotics)) required to run the
RCLL simulation on a Kubernetes cluster.

The current setup has been used and tested on Fedora 27 with Kubernetes 1.10.1
and Ceph Kraken.

This file describes the setup hosted at the
[Knowledge-Based Systems Group](https://kbsg.rwth-aachen.de) used for the
[Planning and Execution Competitions for Logistics Robots in Simulation](http://www.robocup-logistics.org/sim-comp)
held at
[ICAPS 2017 and 2018](http://icaps-conference.org/index.php/Main/Competitions).

## Cluster Setup

### Overview
In the following, you need to setup the following:
- Kubernetes on Hosts
- Kubernetes Cluster using kubeadm
- Basic services in the cluster
- Ceph Storage cluster
- MongoDB replicated database

### 0. Run kbsg-ansible kubernetes playbook to assert pre-requisites
```
cd kbsg-ansible
ansible-playbook -i kbsg.inv kubernetes.yaml
```

At this time, this is a private ansible playbook which simply installs the
relevant Kubernetes packages on a Fedora base system. In principal, you can use
any Kubernetes cluster.

### 1. Create kube-master (on enterprise)

```
kubeadm init --ignore-preflight-errors "SystemVerification,Swap" --config=kubeadm-master.conf
cp /etc/kubernetes/admin.conf $HOME/.kube/config
# note join command in /etc/kubernetes/join.txt, add --ignore-preflight-errors "SystemVerification,Swap"
# to command line (we use btrfs and have swap since we run the cluster on our regular desktops)
kubectl apply -f https://raw.githubusercontent.com/coreos/flannel/master/Documentation/kube-flannel.yml
```

### 2. Join nodes
On each node in the cluster (all nodes in robolab but enterprise):
execute the join command noted earlier

### 3. Add the required addons and services
- dns-expose/kubedns-ext.yaml
  (now you can enable lookups through dnsmasq on enterprise)
- dashboard/*.yaml
  (this enables a full authorized non-login dashboard. Note that this is a security risk
   depending on its exposure, consider looking more closely into RBAC, e.g.,
   https://docs.bitnami.com/kubernetes/how-to/configure-rbac-in-your-kubernetes-cluster/)

### 4. Bring up Ceph cluster

Ceph is used for distributed storage to pool resources of all machines and make
them fail-safe. Note that we are using an older version of Ceph since we ran into
trouble with newer versions (cf.
[Ceph Issue 21142](https://tracker.ceph.com/issues/21142), might have been resolved
since our initial testing in
Ceph PR 22704](https://github.com/ceph/ceph/pull/22704)).

#### Fresh Setup
If there is no Ceph cluster or you want to wipe the existing one, use the following
procedure.

Note, that the cluster depends on deploying a valid client key. For now, we pass a valid
one on request from which to deploy the cluster.
In `kubernetes/ceph`:
- run `create_ceph_cluster`
- `kubectl label node enterprise.kbsg.rwth-aachen.de cluster-services=true`
- Create labels on nodes which run osds (actual storage nodes). Create one by one and
  let ceph-osd pods come up before labeling the next node.
  ```
  for n in voyager defiant pegasus agamemnon orinoco stargazer; do \
    kubectl label node $n.kbsg.rwth-aachen.de node-type=storage; \
    sleep 60; \
  done
  ```
- in rbd-provisioner:
  ```
  for f in *.yaml; do
    kubectl apply -f $f;
  done
  ```
  The RBD provisioner is used to fulfill RBD volume requests.

- On an initial setup, you need to make some changes directly on the
  running ceph-mon instance. Find the instance with
  `kubectl -n ceph get pods | grep ceph-mon`. Then exec into the
  pod using `kubectl exec -ti ceph-mon-xxxxxxxx-xxxxx bash` and do:
  ```
  ceph osd pool application enable kube rbd
  ceph mgr module enable dashboard
  ceph mgr module enable prometheus
  ceph auth get-or-create client.kube mon 'allow r' osd \
    'allow class-read object_prefix rbd_children, allow rwx pool=kube' \
    > ceph.client.kube.keyring
  ```
  Then create the necessary secret:
  ```
  kubectl --namespace=ceph create secret generic ceph-rbd-kube \
    --from-literal="key=$(grep key ceph.client.kube.keyring  | awk '{ print $3 }')" \
    --type=kubernetes.io/rbd
  ```
  With kubectl proxy enabled you can access the dashboard at:
  http://localhost:8001/api/v1/namespaces/ceph/services/http:ceph-mgr-dashboard:/proxy/

#### To recover an existing setup
This works on machines where you originally created the keys or can restore
them from a backup. In that case, edit `create_secrets.sh` and comment the
line starting with `./generate_secrets.sh`. This prevents creating new
credentials. Then follow the same instructions as above.
  
### 5. Bring up logging system

Centralized logs which can be searched can be very useful for troubleshooting.
However, these come at a cost. Therefore, we recommend enabling the logging
system only if enough resources can be spared (elasticsearch easily consumes
several GB of RAM and several cores) or to debug a problem.

We use logging based on fluentd, writing to elasticsearch and to local files.
We use a custom fluentd configmap that disables pushing anything in the logs
from before fluentd was run (setting read_from_head to false).
We disable logging docker (and thus container) output to journald by removing
the flag "--log-driver=journald" from OPTIONS in /etc/sysconfig/docker
(taken care of by kbsg-ansible).

Currently broken for kubelet < 1.10.3:
https://github.com/kubernetes/kubernetes/pull/62462

In `kubernetes/fluentd-elasticsearch`:
```
kubectl create -f es-service.yaml -f es-statefulset.yaml
kubectl create -f kibana-service.yaml -f kibana-deployment.yaml
kubectl create -f fluentd-es-configmap.yaml -f fluentd-es-ds.yaml
```
Then label the nodes:
```
for n in voyager defiant pegasus agamemnon orinoco enterprise stargazer; do
  kubectl label node $n.kbsg.rwth-aachen.de beta.kubernetes.io/fluentd-ds-ready=true
  sleep 30
done
```

After running kubectl proxy, you can access kibana at:
http://localhost:8001/api/v1/proxy/namespaces/kube-system/services/kibana-logging

### 6. Setup private registry credentials
We use a private internal registry for some images, e.g., competition entries.
If you do not use one, you can skip this step. Otherwise make sure that you
add read-only credentials for all images deployed from the private registry.
For our nginx-auth container this is the "nodes" user. For the externally
available registry it is cluster. In the following, replace "PASS" by the
actual password.

```
kubectl --namespace=kube-system create secret docker-registry defiantregsecret \
  --docker-server=defiant.kbsg.rwth-aachen.de:5000 \
  --docker-username=nodes --docker-password=PASS \
  --docker-email=docker+defiant@kbsg.rwth-aachen.de

for namespace in kube-system default ceph; do
  kubectl --namespace=$namespace create secret docker-registry regsecret \
    --docker-server=registry.kbsg.rwth-aachen.de \
    --docker-username=cluster --docker-password=PASS \
    --docker-email=docker+registry@kbsg.rwth-aachen.de; \
done
```

### 7. Deploy nginx-ingress
The ingress controller is used to provide external access to the nginx
registry auth pod as well as the simulation visualization.

In our current setup, this has to be a specific machine.

```
kubectl label node defiant.kbsg.rwth-aachen.de ingress-controller=nginx
kubectl create \
  -f namespace.yaml -f rbac.yaml -f configmap.yaml \
  -f default-backend.yaml -f with-rbac.yaml -f service-nodeport.yaml \
  -f udp-services-configmap.yaml -f tcp-services-configmap.yaml
```

### 8. Deploy nginx-registry-auth
The nginx-registry-auth pod provides our authorization policy enforced
by the nginx reverse proxy (which resides outside the cluster).
```
kubectl apply -f kubernetes/registry/nginx-auth/nginx-registry-auth-dp.yaml
```

### 9. Enable cluster monitoring via Prometheus

Cluster monitoring is useful to estimate the required resources for simulation
and analyze problems and bottlenecks. We use a standard prometheus/grafana stack
for this.

- in `prometheus`:
```
kubectl create -f namespace.yaml
kubectl create -f prometheus-claim.yaml -f grafana-claim.yaml
kubectl create -f manifest-all.yaml -f ingress.yaml
kubectl create -f grafana-import-job.yaml
```
Once the job pod completes, the job may be removed again.

*WARNING*: the default password must be changed immediately, it is admin/admin,
 change to something sane and create a user.

You can login to grafana at
https://kube-monitoring.kbsg.rwth-aachen.de
or via kubectl proxy at:
http://localhost:8001/api/v1/namespaces/monitoring/services/http:grafana:/proxy/login

### 10. Create MongoDB ReplicaSet
```
kubectl apply -f kubernetes/mongodb/mongodb-namespace.yaml
kubectl apply -f kubernetes/mongodb/rbac.yaml
kubectl apply -f kubernetes/mongodb/mongodb-statefulset.yaml
```

### Using the cluster
Create a devpod for easy access to the database:
```
kubectl apply -f kubernetes/rcll-sim/devpod.yaml
```
The exec into the devpod and use the cluster tools (see sim-ctrl directory).

## Cluster Teardown
To teardown the cluster issue the following commands (assumes a working PSSH setup):

```
pssh -h .ssh/pssh-kube-nodes kubeadm reset
ssh root@enterprise kubeadm reset
pssh -h .ssh/pssh-robolab systemctl stop kubelet
pssh -h .ssh/pssh-robolab systemctl stop docker
pssh -h .ssh/pssh-robolab rm -rf /var/lib/cni/*
pssh -h .ssh/pssh-robolab rm -rf /var/lib/kubelet/*
pssh -h .ssh/pssh-robolab ifconfig cni0 down
pssh -h .ssh/pssh-robolab ifconfig flannel.1 down
pssh -h .ssh/pssh-robolab ifconfig docker0 down
pssh -h .ssh/pssh-robolab brctl delbr docker0
pssh -h .ssh/pssh-robolab ip link delete cni0
pssh -h .ssh/pssh-robolab ip link delete flannel.1
```
