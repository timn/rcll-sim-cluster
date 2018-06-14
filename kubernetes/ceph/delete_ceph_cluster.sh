#!/bin/bash

kubectl delete namespace ceph
kubectl delete secret ceph-secret-admin --namespace=kube-system
kubectl delete secret ceph-client-key --namespace=kube-system
kubectl delete secret ceph-client-key --namespace=default
kubectl delete secret ceph-client-key --namespace=database
kubectl delete storageclass rbd
kubectl delete pv --all
kubectl label nodes --all node-type-
