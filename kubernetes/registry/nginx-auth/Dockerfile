FROM       fedora:27

# Disable Delta RPM, since docs are stripped doesn't work
RUN echo "deltarpm=0" >> /etc/dnf/dnf.conf && \
	# Update and clean cache afterwards
	dnf -y update && dnf clean all

RUN \
  dnf -y install python3-urllib3 &&\
	dnf clean all

RUN mkdir -p /opt/nginx-registry-auth
COPY nginx-registry-auth /opt/nginx-registry-auth

