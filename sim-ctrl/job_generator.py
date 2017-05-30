
from work_queue import WorkQueue
from config import Configuration
from pprint import pprint
import jinja2

import random
import os
import yaml

class JobGenerator(object):
	def __init__(self, template, debug=False, dry_run=False):
		self.config = Configuration()
		self.debug = debug
		self.dry_run = dry_run

		if not dry_run:
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

	def generate(self, tournament_name, team_cyan, team_magenta):
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

		(tournament_doc, parameter_doc) = yaml.load_all(yamldoc)

		#if self.debug:
			#print("Tournament:\n")
			#pprint(tournament_doc)
			#print("Parameters:\n")
			#pprint(parameter_doc)
			#print("Parameters:")
			#for p in parameter_doc["parameters"]:
			#	print("- %s" % p["template"])

		idnum = 1 if self.dry_run else self.wq.get_next_id()
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
