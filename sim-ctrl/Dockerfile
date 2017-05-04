FROM       fedora:25

# Disable Delta RPM, since docs are stripped doesn't work
RUN echo "deltarpm=0" >> /etc/dnf/dnf.conf && \
	# Update and clean cache afterwards
	dnf -y update && dnf clean all

# openssh-server is installed to use the image as devpod
RUN \
  dnf -y install 'dnf-command(copr)' &&\
  dnf -y copr enable timn/python-kubernetes &&\
  dnf -y install python3-kubernetes python3-jinja2 python3-pymongo \
                 openssh-server &&\
	dnf clean all

RUN mkdir -p /opt/rcll-sim-ctrl
COPY print_pods run_print_pod /opt/rcll-sim-ctrl
