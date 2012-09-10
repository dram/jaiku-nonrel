# Copyright 2010 Google Inc.
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

import datetime

from appengine_django.sessions.models import Session
from django.conf import settings
from google.appengine.ext import db

from common import api
from common.test.base import ViewTestCase
from common.user import (generate_user_auth_token, lookup_user_auth_token,
                         purge_expired_user_auth_token_keys)

class SessionTest(ViewTestCase):
  users = ('popular@example.com',
           'girlfriend@example.com')

  def test_sessions_should_be_cached(self):
    for user in self.users:
      token = generate_user_auth_token(user, 'password hash')
      auth_token = lookup_user_auth_token(user, token)
      self.assertEqual('password hash', auth_token)

  def test_look_up_nonexistent_sessions(self):
    for user in self.users:
      token = generate_user_auth_token(user, 'password hash')
      auth_token = lookup_user_auth_token('missing@example.com',
                                          'password hash')
      self.assertEqual(None, auth_token)
      auth_token = lookup_user_auth_token(user, 'some other password hash')
      self.assertEqual(None, auth_token)

  def test_purge_expired_tokens(self):
    """ Generate tokens with current time as expiration date/time.
    That is, tokens are expired as soon as they are generated.

    """
    for user in self.users:
      token = generate_user_auth_token(user,
                                       'password hash',
                                       timeout=0)
      auth_token = lookup_user_auth_token(user, token)
      self.assertEqual(None, auth_token)

    # As expired tokens are purged from the DB just before
    # they are generated, the above should leave us with one
    # expired token in the DB
    query = Session.gql("WHERE expire_date <= :1", api.utcnow())
    expired_tokens = query.count()
    self.assertEqual(1, expired_tokens)

    # Generate another token to trigger cache purging which
    # should leave us with no expired sessions in the DB (as
    # this token is generated with a future expiration date.)
    token = generate_user_auth_token('fake user', 'password hash')

    query = Session.gql("WHERE expire_date <= :1", api.utcnow())
    expired_tokens = query.count()
    self.assertEqual(0, expired_tokens)
