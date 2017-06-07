#!/bin/bash
set -ex

cd generator
./generate_secrets.sh all `./generate_secrets.sh fsid` "$@"

kubectl create namespace ceph
kubectl create secret generic ceph-conf-combined --from-file=ceph.conf --from-file=ceph.client.admin.keyring --from-file=ceph.mon.keyring --namespace=ceph
kubectl create secret generic ceph-bootstrap-rgw-keyring --from-file=ceph.keyring=ceph.rgw.keyring --namespace=ceph
kubectl create secret generic ceph-bootstrap-mds-keyring --from-file=ceph.keyring=ceph.mds.keyring --namespace=ceph
kubectl create secret generic ceph-bootstrap-osd-keyring --from-file=ceph.keyring=ceph.osd.keyring --namespace=ceph
kubectl create secret generic ceph-client-key --from-file=ceph-client-key --namespace=ceph
kubectl create secret generic ceph-client-key --from-file=ceph-client-key --namespace=default
kubectl create secret generic ceph-client-key --from-file=ceph-client-key --namespace=kube-system
#kubectl create namespace database
kubectl create secret generic ceph-client-key --from-file=ceph-client-key --namespace=database
kubectl create secret generic ceph-admin-secret --from-literal=key="$(cat ceph-client-key)" --type=kubernetes.io/rbd --namespace=kube-system

cd ..
