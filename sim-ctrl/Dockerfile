FROM       fedora:27

# Disable Delta RPM, since docs are stripped doesn't work
RUN echo "deltarpm=0" >> /etc/dnf/dnf.conf && \
	# Update and clean cache afterwards
	dnf -y update && dnf clean all

# openssh-server is installed to use the image as devpod
RUN \
  dnf -y install python3-kubernetes python3-jinja2 python3-pymongo \
                 python3-dns python3-requests python3-humanize \
								 jq mongodb openssh-server findutils &&\
	dnf clean all

RUN mkdir -p /opt/rcll-sim-ctrl
COPY *.py run-sim-jobs create-sim-job create-tournament get-logs \
		 print-job-info print-results update-jobs Dockerfile /opt/rcll-sim-ctrl/
RUN bash -c "cd /bin; \
		for f in \$(find /opt/rcll-sim-ctrl/ -executable -type f ! -iname '*~'); do ln -s \$f; done; \
		"

COPY templates /opt/rcll-sim-ctrl/templates
