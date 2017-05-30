#!/bin/bash

./create_ceph_cluster.sh \
  global_osd_pool_default_size=2 \
  osd_cluster_network=10.23.0.0/16 \
  osd_public_network=10.23.0.0/16 \
  mon_data_avail_warn=10 \
  global_osd_pool_default_pg_num=256 \
  global_osd_pool_default_pgp_num=256

kubectl create -f rbd-storage-class.yaml

#kubectl create -f rbd-storage-class.yaml
echo "Waiting for monitoring pod to come up"
while true; do
  POD_NAME=$(kubectl --namespace=ceph get pods -o custom-columns=":.metadata.name" 2>/dev/null | grep ceph-mon | grep -v ceph-mon-check)
	if [ -n "$POD_NAME" ]; then break; fi
	sleep 1
done

echo "Monitoring Pod: $POD_NAME"

while true; do
	POD_IP=$(kubectl --namespace=ceph get pods $POD_NAME -o custom-columns=":.metadata.name,:.status.podIP" 2>/dev/null | grep ceph-mon | awk '{ print $2 }')
	if [ -n "$POD_IP" ]; then break; fi
	sleep 1
done

echo "Monitoring Pod IP: $POD_IP"

cat >/tmp/pod_ip <<EOM
monitor_ip: !!str $POD_IP
EOM
jinja2 --format=yaml generator/templates/ceph/rbd-storage-class.yaml.jinja /tmp/pod_ip >/tmp/rbd.yaml
kubectl create -f /tmp/rbd.yaml
rm /tmp/pod_ip /tmp/rbd.yaml

