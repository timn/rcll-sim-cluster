
from work_queue import WorkQueue
from config import Configuration
from pprint import pprint
from difflib import unified_diff
import jinja2

import random
import os
import yaml
import datetime

class JobGenerator(object):
	def __init__(self, template, debug=False, dry_run=False):
		self.config = Configuration()
		self.debug = debug
		self.dry_run = dry_run

		# The work queue will figure out a valid combination of MongoDB access
		# parameters, e.g., host/port, URI, or replica set discovery via DNS
		self.wq = WorkQueue(host=self.config.mongodb_host,
		                    port=self.config.mongodb_port,
		                    uri=self.config.mongodb_uri,
		                    srv_name=self.config.mongodb_rs_srv,
		                    database=self.config.mongodb_queue_db,
		                    replicaset=self.config.mongodb_rs,
		                    collection=self.config.mongodb_queue_col)

		if not os.path.exists(template):
			raise Exception("Template file does not exist")
		self.template_dir = os.path.dirname(template)
		self.template_file = os.path.basename(template)
		if self.template_file == "":
			raise Exception("Template must be a file, not a directory")

		self.jinja = jinja2.Environment(loader=jinja2.FileSystemLoader(self.template_dir),
		                                autoescape=False)

	def _generate_random_id(self, team_cyan, team_magenta, suffix_length=8):
		return team_cyan + "-vs-" + team_magenta + ":" + \
			''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(suffix_length))
		#''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

	def _generate_id(self, tournament_name, team_cyan, team_magenta, index, suffix_length=6):
		return \
			"{tournament_name}:{:0{width}}:{team_cyan}-vs-{team_magenta}"\
			.format(index, width=suffix_length, tournament_name=tournament_name,
			        team_cyan=team_cyan, team_magenta=team_magenta)

	@staticmethod
	def id_regex(tournament_name):
		return "^%s:\d+:.*" % tournament_name

	def generate(self, tournament_name, team_cyan, team_magenta, job_num=None):
		param_vars = {
			"tournament_name": tournament_name,
			"team_name_cyan": team_cyan,
			"team_name_magenta": team_magenta or ""
		}
		template = self.jinja.get_template(self.template_file)
		if template is None:
			print("Failed to get template '%s' (in '%s')" % (self.template_file, self.template_dir))
			raise FileNotFoundError("Could not find template '%s' ( in '%s')" \
			                        % (template_name, self.template_dir))

		yamldoc = template.render(param_vars)
		if self.debug: print("YAML:\n%s" % yamldoc)

		try:
			(tournament_doc, parameter_doc) = yaml.load_all(yamldoc)
		except:
			for idx, line in enumerate(yamldoc.splitlines()):
				print("%-4d: %s" % (idx, line))
			raise

		#if self.debug:
			#print("Tournament:\n")
			#pprint(tournament_doc)
			#print("Parameters:\n")
			#pprint(parameter_doc)
			#print("Parameters:")
			#for p in parameter_doc["parameters"]:
			#	print("- %s" % p["template"])

		idnum = job_num if job_num is not None else 1 if self.dry_run else self.wq.get_next_id()
		jobname = self._generate_id(tournament_name, team_cyan, team_magenta, idnum)

		params = {
			"parameter_vars": param_vars,
			"parameter_doc_yaml": yamldoc,
			"template_parameters": parameter_doc["parameters"]
		}
		#if self.debug:
			#print("Job Parameters")
			#pprint(params)

		return (jobname, idnum, params)

	def store(self, jobname, idnum, params):
		if not self.dry_run:
			self.wq.add_item(jobname, idnum, params)

	def generate_and_store(self, tournament_name, team_cyan, team_magenta):
		(jobname, idnum, params) = self.generate(tournament_name, team_cyan, team_magenta)
		self.store(jobname, idnum, params)
		return (jobname, idnum, params)

	def update_params(self, tournament_name, print_diffs=False, only_pending=True):
		for i in self.wq.get_items(JobGenerator.id_regex(tournament_name)):
			if only_pending and i['status']['state'] != 'pending': continue

			job_parts = i['name'].split(':')
			teams = job_parts[2].split("-vs-")
			(jobname, idnum, params) = \
			    self.generate(job_parts[0], teams[0], teams[1], job_num=int(job_parts[1]))
			if jobname != i['name']:
				raise Exception("Invalid jobname, expected '%s', got '%s'" %
					                (i['name'], jobname))
			diff = unified_diff(i["params"]["parameter_doc_yaml"].splitlines(True),
			                    params['parameter_doc_yaml'].splitlines(True),
			                    fromfile='%s OLD' % jobname, tofile='%s' % jobname)
			diffstr = ''.join(diff)
			if print_diffs:
				if len(diffstr) == 0:
					print("%s: no update required" % jobname)
				else:
					print(diffstr)

			if not self.dry_run and len(diffstr) > 0:
				update={"$push": { "updates": { "updated": datetime.datetime.utcnow(),
				                                "diff": diffstr }},
				        "$set": {"status.state": "pending", "params": params},
				        "$unset": { "manifests": "", "status.completed": "",
				                    "status.running": ""}
				}
				if self.debug: pprint(update)
				self.wq.update_item(jobname, update)

	def cancel_jobs(self, tournament_name, only_pending = True):
		update = {"$set": { "status.state": "cancelled",
		                    "status.cancelled": datetime.datetime.utcnow()}}
		for i in self.wq.get_items(JobGenerator.id_regex(tournament_name)):
			if i['status']['state'] != 'cancelled' and \
			   (not only_pending or i['status']['state'] == 'pending'):
				print("Cancelling %s" % i['name'])
				if not self.dry_run:
					self.wq.update_item(i['name'], update)
