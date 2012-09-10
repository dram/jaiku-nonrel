# Copyright 2009 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
import urllib
import urllib2

# TODO(termie): abstract away app engine specifics
from google.appengine.api import urlfetch

from django.conf import settings

from common import exception
from common.protocol import base

class _DevRpc(object):
  def get_result(self):
    pass

class PshbConnection(base.Connection):
  def __init__(self, endpoint):
    self.endpoint = endpoint

  def publish_async(self, urls):
    if settings.MANAGE_PY:
      logging.info('pshb.publish(%s, %s)', self.endpoint, self.urls)
      return _DevRpc()

    rpc = urlfetch.create_rpc()
    def _callback():
      result = rpc.get_result()
      if result.status_code == 204:
        return
      raise exception.ServiceError(result.content)

    rpc.callback = _callback
    data = urllib.urlencode(
        {'hub.url': urls, 'hub.mode': 'publish'}, doseq=True)
    urlfetch.make_fetch_call(rpc, self.endpoint, method='POST', payload=data)
    return rpc
