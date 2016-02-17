from logging import debug, warning, error

_service_configs = None

def setup_services(config):
	global _service_configs
	_service_configs = config.services

def _get_service_config(key):
	if key in _service_configs:
		return _service_configs[key]
	return dict()

def _make_service(service):
	service.set_config(_get_service_config(service.key))
	return service

##############
# Requesting #
##############

from functools import wraps, lru_cache
from time import perf_counter, sleep
import requests
from json import JSONDecodeError
from xml.etree import ElementTree as xml_parser
from bs4 import BeautifulSoup

def rate_limit(wait_length):
	last_time = 0
	
	def decorate(f):
		@wraps(f)
		def rate_limited(*args, **kwargs):
			nonlocal last_time
			diff = perf_counter() - last_time
			if diff < wait_length:
				sleep(wait_length - diff)
			
			r = f(*args, **kwargs)
			last_time = perf_counter()
			return r
		return rate_limited
	return decorate

class Requestable:
	rate_limit_wait = 1
	
	@lru_cache(maxsize=100)
	@rate_limit(rate_limit_wait)
	def request(self, url, json=False, xml=False, html=False, proxy=None, useragent=None, auth=None):
		"""
		Sends a request to the service.
		:param url: The request URL
		:param json: If True, return the response as parsed JSON
		:param xml: If True, return the response as parsed XML
		:param html: If True, return the response as parsed HTML
		:param proxy: Optional proxy, a tuple of address and port
		:param useragent: Ideally should always be set
		:param auth: Tuple of username and password to use for HTTP basic auth
		:return: The response if successful, otherwise None
		"""
		if proxy is not None:
			if len(proxy) != 2:
				warning("Invalid number of proxy values, need address and port")
				proxy = None
			else:
				proxy = {"http": "http://{}:{}".format(*proxy)}
				debug("Using proxy: {}", proxy)
		
		headers = {"User-Agent": useragent}
		debug("Sending request")
		debug("  URL={}".format(url))
		debug("  Headers={}".format(headers))
		response = requests.get(url, headers=headers, proxies=proxy, auth=auth)
		debug("  Status code: {}".format(response.status_code))
		if not response.ok or response.status_code == 204:		#204 is a special case for MAL errors
			error("Response {}: {}".format(response.status_code, response.reason))
			return None
		
		if json:
			debug("Response returning as JSON")
			try:
				return response.json()
			except JSONDecodeError as e:
				error("Response is not JSON", exc_info=e)
				return None
		if xml:
			debug("Response returning as XML")
			#TODO: error checking
			raw_entry = xml_parser.fromstring(response.text)
			#entry = dict((attr.tag, attr.text) for attr in raw_entry)
			return raw_entry
		if html:
			debug("Returning response as HTML")
			soup = BeautifulSoup(response.text, 'html.parser')
			return soup
		debug("Response returning as text")
		return response.text

###################
# Service handler #
###################

from abc import abstractmethod, ABC

class AbstractServiceHandler(ABC, Requestable):
	def __init__(self, key, name):
		self.key = key
		self.name = name
		self.config = None
	
	def set_config(self, config):
		self.config = config
	
	@abstractmethod
	def get_latest_episode(self, show_id, **kwargs):
		"""
		Gets information on the latest episode for this service.
		:param show_id: The ID of the show being checked
		:param kwargs: Arguments passed to the request, such as proxy and authentication
		:return: The latest episode
		"""
		return None
	
	@abstractmethod
	def get_stream_link(self, stream):
		"""
		Creates a URL to a show's main stream page hosted by this service.
		:param stream: The show's stream
		:return: A URL to the stream's page
		"""
		return None
	
	@abstractmethod
	def get_seasonal_streams(self, year=None, season=None, **kwargs):
		"""
		Gets a list of streams for shows airing in a particular season.
		If year and season are None, uses the current season.
		Note: Not all sites may allow specific years and seasons.
		:param year: 
		:param season: 
		:param kwargs: Extra arguments, particularly useragent
		:return: A list of UnprocessedStreams (empty list if no shows or error)
		"""
		return list()

# Services

_services = None

def _ensure_service_handlers():
	global _services
	if _services is None:
		from . import stream
		_services = {x.key: _make_service(x) for x in [
			stream.crunchyroll.ServiceHandler(),
			stream.funimation.ServiceHandler()
		]}

def get_service_handlers():
	"""
	Creates an instance of every service in the services module and returns a mapping to their keys.
	:return: A dict of service keys to an instance of the service
	"""
	_ensure_service_handlers()
	return _services

def get_service_handler(service):
	"""
	Returns an instance of a service handler representing the given service.
	:param service: A service
	:return: A service handler instance
	"""
	_ensure_service_handlers()
	if service is not None and service.key in _services:
		return _services[service.key]
	return None

################
# Link handler #
################

class AbstractInfoHandler(ABC, Requestable):
	def __init__(self, key, name):
		self.key = key
		self.name = name
		self.config = None
	
	def set_config(self, config):
		debug("Setting config of {} to {}".format(self.key, config))
		self.config = config
	
	@abstractmethod
	def get_link(self, link):
		"""
		Creates a URL using the information provided by a link object.
		:param link: The link object
		:return: A URL
		"""
		return None
	
	@abstractmethod
	def find_show(self, show_name, **kwargs):
		"""
		Searches the link site for a show with the specified name.
		:param show_name: The desired show's name
		:param kwargs: Extra arguments, particularly useragent
		:return: A list of shows (empty list if no shows or error)
		"""
		return list()
	
	@abstractmethod
	def get_episode_count(self, show, link, **kwargs):
		"""
		Gets the episode count of the specified show on the site given by the link.
		:param show: The show being checked
		:param link: The link pointing to the site being checked
		:param kwargs: Extra arguments, particularly useragent
		:return: The episode count, otherwise None
		"""
		return None
	
	@abstractmethod
	def get_seasonal_shows(self, year=None, season=None, **kwargs):
		"""
		Gets a list of shows airing in a particular season.
		If year and season are None, uses the current season.
		Note: Not all sites may allow specific years and seasons.
		:param year: 
		:param season: 
		:param kwargs: Extra arguments, particularly useragent
		:return: A list of UnprocessedShows (empty list if no shows or error)
		"""
		return list()
	
# Link sites

_link_sites = None

def _ensure_link_handlers():
	global _link_sites
	if _link_sites is None:
		from . import info
		_link_sites = {x.key: _make_service(x) for x in [
			info.myanimelist.InfoHandler(),
			info.anidb.InfoHandler()
		]}

def get_link_handlers():
	"""
	Creates an instance of every link handler in the links module and returns a mapping to their keys.
	:return: A dict of link handler keys to an instance of the link handler
	"""
	_ensure_link_handlers()
	return _link_sites

def get_link_handler(link_site):
	"""
	Returns an instance of a link handler representing the given link site.
	:param link_site: A link site
	:return: A link handler instance
	"""
	_ensure_link_handlers()
	if link_site is not None and link_site.key in _link_sites:
		return _link_sites[link_site.key]
	return None
